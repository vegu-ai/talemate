from __future__ import annotations

from typing import Callable, Literal, get_args

import pydantic
import structlog
from typing_extensions import TypedDict

import talemate.emit.async_signals as async_signals

# circular-import-safe at runtime only (talemate.instance imports
# talemate.agents); same pattern as agents/director/character_management.py
import talemate.instance as instance
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    DynamicInstruction,
    set_processing,
)
from talemate.character import Character
from talemate.exceptions import LLMAccuracyError
from talemate.game import focal
from talemate.prompts import Prompt
from talemate.prompts.response import ResponseSpec, StrictAnchorExtractor
from talemate.util.data import parse_attribute_lines
from talemate.ux.schema import Condition

from .response_specs import NAME_SPEC

log = structlog.get_logger("talemate.agents.creator.character")

DEFAULT_CONTENT_CONTEXT = "a fun and engaging adventure aimed at an adult audience."

CharacterGenerationAspect = Literal[
    "name",
    "description",
    "attributes",
    "dialogue_instructions",
    "example_dialogue",
]

# Aspects that can be generated for a character, in canonical generation
# order (the Literal definition order above). The consolidated ("Fast")
# one-shot can cover any subset of these.
CHARACTER_GENERATION_ASPECTS: list[CharacterGenerationAspect] = list(
    get_args(CharacterGenerationAspect)
)

# extra (non-aspect) entry of the Consolidate flags: fold selected attribute
# world-state templates into the one-shot instead of one prompt per template
CONSOLIDATE_TEMPLATES_FLAG = "attribute_templates"

# the Consolidate setting's value shape: aspects plus the fold flag
ConsolidateFlag = CharacterGenerationAspect | Literal["attribute_templates"]

# tokens reserved on top of the response budget when sizing the scene
# history for the consolidated one-shot (covers the fixed prompt sections)
ONE_SHOT_CONTEXT_OVERHEAD_TOKENS = 256

# lower bound for the scene history budget - keeps tiny-context clients
# from ending up with a negative reservation
ONE_SHOT_MIN_HISTORY_TOKENS = 512

# aspect -> fill method name for generate_character_aspects' individual
# fills (totality pinned by test)
_ASPECT_FILL_METHODS: dict[CharacterGenerationAspect, str] = {
    "name": "_fill_aspect_name",
    "description": "_fill_aspect_description",
    "attributes": "_fill_aspect_attributes",
    "dialogue_instructions": "_fill_aspect_dialogue_instructions",
    "example_dialogue": "_fill_aspect_example_dialogue",
}


def one_shot_history_budget(max_tokens: int, response_budget: int) -> int:
    """Scene history budget for the consolidated one-shot: the client's
    context minus the response budget and overhead, floored so
    small-context clients don't get a negative reservation."""
    return max(
        ONE_SHOT_MIN_HISTORY_TOKENS,
        max_tokens - response_budget - ONE_SHOT_CONTEXT_OVERHEAD_TOKENS,
    )


def one_shot_effective_response_budget(configured_budget: int, max_tokens: int) -> int:
    """Response budget for the consolidated one-shot, clamped so that
    history + overhead + response fit the client's context (guaranteed for
    contexts >= 1792 = 512 + 256 + 1024; below that the response/history
    floors take precedence - no practical Fast-mode client is that small)."""
    return min(
        configured_budget,
        max(
            1024,
            max_tokens - ONE_SHOT_MIN_HISTORY_TOKENS - ONE_SHOT_CONTEXT_OVERHEAD_TOKENS,
        ),
    )


class AttributeInstructionSpec(TypedDict):
    """Per-attribute generation instructions, folded into the attributes
    section of consolidated generation (from attribute world-state
    templates)."""

    attribute: str
    instructions: str


def format_attribute_instructions(specs: list[AttributeInstructionSpec]) -> str:
    """Render an attribute instruction spec list for prompt inclusion -
    single formatting shared by the one-shot template var and the
    fill-misses fallback."""
    return "\n".join(
        f"- {spec['attribute']}: {spec['instructions']}"
        if spec["instructions"]
        else f"- {spec['attribute']}"
        for spec in specs
    )


async_signals.register(
    "agent.creator.dialogue_examples.before",
    "agent.creator.dialogue_examples.after",
)


class DialogueExamplesEmission(AgentEmission):
    character: Character
    text: str = ""
    instructions: str = ""
    dynamic_instructions: list[DynamicInstruction] = pydantic.Field(
        default_factory=list
    )
    dialogue_examples: list[str] = pydantic.Field(default_factory=list)


class CharacterGenerationResult(pydantic.BaseModel):
    """
    Result of (consolidated or hybrid) character generation. Each field
    corresponds to one character generation aspect and is None when that
    aspect was not generated (or was missed and not filled in).
    """

    name: str | None = None
    description: str | None = None
    attributes: dict[str, str] | None = None
    dialogue_instructions: str | None = None
    example_dialogue: list[str] | None = None

    def extracted_aspects(self) -> set[str]:
        """Aspects that hold a non-empty value."""
        found = set()
        if self.name:
            found.add("name")
        if self.description:
            found.add("description")
        if self.attributes:
            found.add("attributes")
        if self.dialogue_instructions:
            found.add("dialogue_instructions")
        if self.example_dialogue:
            found.add("example_dialogue")
        return found


class CharacterGenerationRequest(pydantic.BaseModel):
    """Request parameters for generate_character_aspects.

    `unified` / `consolidate` / `fill_misses` default to the creator agent's
    "Character Creation" settings when not given.

    Attributes:
        aspects: Requested aspects (subset of CHARACTER_GENERATION_ASPECTS)
        name: Current or descriptive character name
        content: Guiding content / instructions for the creation
        description: Existing description (if any)
        character: Existing character for context (e.g. card import).
            Used read-only - a copy is made for internal bookkeeping.
        unified: Override for the Fast mode setting
        consolidate: Override for the consolidated aspects setting (aspect
            names; may include the 'attribute_templates' fold flag, like the
            raw setting value)
        fill_misses: Override for the fill-in-misses setting
        instructions: Extra instructions for dialogue instructions
        example_dialogue_instructions: Guidance for example dialogue
        max_examples: Maximum number of example dialogue lines
        max_attributes: Maximum number of attributes
        dynamic_instructions: Extra dynamic instructions for the prompts
        content_role: How `content` is passed to individual description
            generation (split mode or one-shot fallback): "information"
            layers it on top of the scene context, "text" replaces the
            scene context with it
        attribute_instructions: Per-attribute generation instructions
            (from attribute world-state templates) to fold into the
            attributes section of the one-shot (and of its individual
            fallback)
        augment_attributes: Augmentation instruction to fold into the
            attributes section of the one-shot (add attributes beyond the
            instructed ones)
        on_aspect_start: Optional callback invoked with each aspect right
            before its individual fill runs (progress reporting)
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    aspects: list[CharacterGenerationAspect]
    name: str = ""
    content: str = ""
    description: str = ""
    character: Character | None = None
    unified: bool | None = None
    consolidate: list[ConsolidateFlag] | None = None
    fill_misses: bool | None = None
    instructions: str = ""
    example_dialogue_instructions: str = ""
    max_examples: int = 5
    max_attributes: int | None = None
    dynamic_instructions: list | None = None
    content_role: Literal["information", "text"] = "information"
    attribute_instructions: list[AttributeInstructionSpec] | None = None
    augment_attributes: str = ""
    on_aspect_start: Callable[[CharacterGenerationAspect], None] | None = None

    @property
    def effective_name(self) -> str:
        """The request's name, falling back to the context character's."""
        return self.name or (self.character.name if self.character else "")


def _is_other_speaker(speaker: str) -> bool:
    """Whether a `Word Word:` speaker prefix looks like another character's
    name (2-3 capitalized words, digits allowed for the likes of "Agent 47").

    Single-word prefixes ("Warning:", "Narrator:") deliberately don't
    qualify: they are the dominant false-positive class (plausible dialogue
    content) and a relabeled line is the lesser evil there.
    """
    words = speaker.strip().split()
    return (
        2 <= len(words) <= 3
        and len(speaker) <= 40
        and all(word[:1].isupper() or word[:1].isdigit() for word in words)
    )


def _normalize_example_dialogue_lines(
    lines: list[str],
    example_name: str,
    other_known_names: list[str] | None = None,
    max_examples: int = 5,
) -> list[str]:
    """Normalize example dialogue lines to `example_name: <line>` entries.

    - lines whose speaker prefix is a known name (the final name, or a raw /
      descriptive name the model may have echoed) are re-prefixed with the
      final name
    - bare `Name:` / name-only lines (no dialogue content) are dropped
    - lines with an unrecognized name-shaped speaker prefix (another
      character's line) are dropped
    - anything else is prefixed with the final name
    """
    known_prefixes = {
        p.lower() for p in [example_name, *(other_known_names or [])] if p and p.strip()
    }
    normalized = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        speaker, colon, rest = line.partition(":")
        if colon and not rest.strip():
            continue
        if not colon and line.lower() in known_prefixes:
            continue
        if speaker.strip().lower() in known_prefixes:
            normalized.append(f"{example_name}: {rest.strip()}")
        elif colon and _is_other_speaker(speaker):
            # unrecognized name-shaped speaker prefix - another character's
            # line, not an example for this character
            log.debug("normalize_example_dialogue_lines: dropping line", line=line)
            continue
        else:
            normalized.append(f"{example_name}: {line}")
    return normalized[:max_examples]


class CharacterCreatorMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["character_creation"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Character Creation",
            icon="mdi-account-plus",
            description="Configure how AI-assisted character creation generates characters.",
            config={
                "fast": AgentActionConfig(
                    type="bool",
                    label="Fast Character Generation",
                    description=(
                        "Consolidate character generation into a single prompt "
                        "instead of one prompt per aspect. This is much faster "
                        "(one request instead of several), but note that less "
                        "detail in the individual aspects is a possible failure "
                        "mode of this approach, and the model needs a large "
                        "context window and reliable structured output. Keep "
                        "this off for older or smaller models."
                    ),
                    value=False,
                    title="Generation Mode",
                    quick_toggle=True,
                ),
                "consolidate": AgentActionConfig(
                    type="flags",
                    label="Consolidate",
                    description=(
                        "Aspects generated by the single consolidated prompt "
                        "when Fast Character Generation is enabled. Aspects not "
                        "selected are still "
                        "generated with their individual prompts. 'Attribute "
                        "templates' additionally folds selected attribute "
                        "world-state templates into the consolidated prompt "
                        "instead of one prompt per template - their "
                        "instructions are formatted with the character's name "
                        "(or 'the character' when it is still being "
                        "determined). Requires Attributes to be selected as "
                        "well."
                    ),
                    value=list(CHARACTER_GENERATION_ASPECTS)
                    + [CONSOLIDATE_TEMPLATES_FLAG],
                    choices=[
                        {
                            "label": aspect.replace("_", " ").capitalize(),
                            "value": aspect,
                        }
                        for aspect in CHARACTER_GENERATION_ASPECTS
                    ]
                    + [
                        {
                            "label": "Attribute templates",
                            "value": CONSOLIDATE_TEMPLATES_FLAG,
                        }
                    ],
                    condition=Condition(
                        attribute="character_creation.config.fast", value=True
                    ),
                ),
                "one_shot_token_budget": AgentActionConfig(
                    type="number",
                    label="One-shot token budget",
                    description=(
                        "Maximum response tokens for the consolidated prompt. "
                        "All consolidated aspects share this budget - if the "
                        "response is truncated, later sections come out missing "
                        "(and are regenerated individually when Fill in misses "
                        "is on)."
                    ),
                    value=4096,
                    min=1024,
                    max=8192,
                    step=1024,
                    condition=Condition(
                        attribute="character_creation.config.fast", value=True
                    ),
                ),
                "fill_misses": AgentActionConfig(
                    type="bool",
                    label="Fill in misses",
                    description=(
                        "When the consolidated response misses an aspect "
                        "entirely, run that aspect's individual request to fill "
                        "it in. When disabled, missed aspects are left empty. "
                        "A completely unparseable response is always a hard "
                        "error."
                    ),
                    value=True,
                    condition=Condition(
                        attribute="character_creation.config.fast", value=True
                    ),
                ),
            },
        )

    @set_processing
    async def determine_content_context_for_character(
        self,
        character: Character,
    ):
        response, extracted = await Prompt.request(
            "creator.determine-content-context",
            self.client,
            "create_192",
            vars={
                "character": character,
            },
        )
        return extracted["response"].split("\n")[0].strip()

    @set_processing
    async def determine_character_dialogue_instructions(
        self,
        character: Character,
        instructions: str = "",
        information: str = "",
        update_existing: bool = False,
    ):
        response, extracted = await Prompt.request(
            "creator.determine-character-dialogue-instructions",
            self.client,
            "create_concise",
            vars={
                "character": character,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "instructions": instructions,
                "information": information,
                "update_existing": update_existing,
            },
        )

        r = extracted["response"].strip().split("\n")[0].strip('"').strip()
        return r

    @set_processing
    async def determine_character_attributes(
        self,
        character: Character,
    ):
        # This template uses data_response, returns parsed JSON in second element
        response, _ = await Prompt.request(
            "creator.determine-character-attributes",
            self.client,
            "analyze_long",
            vars={
                "character": character,
            },
        )
        return response

    @set_processing
    async def determine_character_name(
        self,
        character_name: str,
        allowed_names: list[str] = None,
        group: bool = False,
        instructions: str = "",
    ) -> str:
        response, extracted = await Prompt.request(
            "creator.determine-character-name",
            self.client,
            "analyze_freeform_24",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character_name": character_name,
                "allowed_names": allowed_names or [],
                "group": group,
                "instructions": instructions,
            },
            response_spec=NAME_SPEC,
        )

        # Extract name from <NAME></NAME> tags
        extracted_name = extracted.get("name")
        if not extracted_name:
            # Fallback to old parsing method
            extracted_name = response.split('"', 1)[0].strip()

        return extracted_name.strip(".").strip()

    @set_processing
    async def determine_character_description(
        self,
        character: Character,
        text: str = "",
        instructions: str = "",
        information: str = "",
        dynamic_instructions: list = None,
    ):
        vars_dict = {
            "character": character,
            "scene": self.scene,
            "text": text,
            "max_tokens": self.client.max_token_length,
            "instructions": instructions,
            "information": information,
        }

        if dynamic_instructions:
            vars_dict["dynamic_instructions"] = dynamic_instructions

        response, extracted = await Prompt.request(
            "creator.determine-character-description",
            self.client,
            "create",
            vars=vars_dict,
        )
        return extracted["response"].strip()

    @set_processing
    async def determine_character_goals(
        self,
        character: Character,
        goal_instructions: str,
    ):
        response, extracted = await Prompt.request(
            "creator.determine-character-goals",
            self.client,
            "create",
            vars={
                "character": character,
                "scene": self.scene,
                "goal_instructions": goal_instructions,
                "npc_name": character.name,
                "player_name": self.scene.get_player_character().name,
                "max_tokens": self.client.max_token_length,
            },
        )

        result = extracted["response"]
        log.debug("determine_character_goals", goals=result, character=character)
        await character.set_detail("goals", result.strip())

        return result.strip()

    @set_processing
    async def determine_character_dialogue_examples(
        self,
        character: Character,
        text: str = "",
        instructions: str = "",
        dynamic_instructions: list = None,
        max_examples: int = 5,
    ) -> list[str]:
        """Extract or generate dialogue examples for a character from given text.

        Args:
            character: The character to extract dialogue examples for
            text: Text containing dialogue examples and relevant character information
            instructions: Optional user-provided guidance for the dialogue examples
            dynamic_instructions: Optional dynamic instructions for context
            max_examples: Maximum number of dialogue examples to generate (default: 5)

        Returns:
            List of dialogue examples (up to max_examples), formatted as "Character Name: ..."
        """
        dialogue_examples = []

        emission = DialogueExamplesEmission(
            agent=self,
            character=character,
            text=text,
            instructions=instructions,
            dynamic_instructions=list(dynamic_instructions or []),
        )
        await async_signals.get("agent.creator.dialogue_examples.before").send(emission)
        dynamic_instructions = emission.dynamic_instructions

        async def add_dialogue_example(example: str) -> str:
            """Add a dialogue example for the character."""
            # Ensure example starts with character name if not already present
            character_prefix = f"{character.name}:"
            if not example.strip().startswith(character_prefix):
                formatted_example = f"{character_prefix} {example.strip()}"
            else:
                formatted_example = example.strip()

            dialogue_examples.append(formatted_example)
            return formatted_example

        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="add_dialogue_example",
                    arguments=[
                        focal.Argument(
                            name="example", type="str", preserve_newlines=True
                        ),
                    ],
                    fn=add_dialogue_example,
                ),
            ],
            max_calls=max_examples,
            character=character,
            scene=self.scene,
            text=text,
            instructions=instructions,
            max_examples=max_examples,
            existing_examples=character.example_dialogue[:3]
            if character.example_dialogue
            else [],
            max_tokens=self.client.max_token_length,
        )

        if dynamic_instructions:
            focal_handler.context["dynamic_instructions"] = dynamic_instructions

        await focal_handler.request(
            "creator.determine-character-dialogue-examples",
        )

        emission.dialogue_examples = dialogue_examples
        await async_signals.get("agent.creator.dialogue_examples.after").send(emission)

        log.debug(
            "determine_character_dialogue_examples",
            character=character.name,
            count=len(emission.dialogue_examples),
            examples=emission.dialogue_examples,
        )

        return emission.dialogue_examples

    # character creation config helpers

    @property
    def cc_fast(self) -> bool:
        """Fast mode: consolidate character generation into a single prompt."""
        return bool(self.resolve_config("character_creation", "fast"))

    @property
    def cc_consolidate(self) -> list[ConsolidateFlag]:
        """Aspects the consolidated one-shot covers when Fast mode is on."""
        return list(self.resolve_config("character_creation", "consolidate") or [])

    @property
    def cc_fill_misses(self) -> bool:
        """Whether to fill aspects the consolidated response missed with their
        individual requests."""
        return bool(self.resolve_config("character_creation", "fill_misses"))

    @property
    def cc_one_shot_token_budget(self) -> int:
        """Response token budget for the consolidated one-shot prompt."""
        return max(
            1024,
            min(
                8192,
                int(
                    self.resolve_config("character_creation", "one_shot_token_budget")
                    or 4096
                ),
            ),
        )

    @property
    def cc_consolidate_templates(self) -> bool:
        """Whether attribute world-state templates are folded into the
        consolidated one-shot (as instructions) instead of one prompt per
        template."""
        return CONSOLIDATE_TEMPLATES_FLAG in self.cc_consolidate

    # consolidated character generation

    @set_processing
    async def generate_character_unified(
        self,
        request: CharacterGenerationRequest,
    ) -> CharacterGenerationResult:
        """
        Generate multiple character aspects with a single consolidated prompt
        ("Fast" mode).

        Args:
            request: The generation request (see CharacterGenerationRequest).
                Only the fields the consolidated prompt consumes are read.

        Returns:
            CharacterGenerationResult with whatever aspects could be extracted.
            Callers decide how to handle missed aspects — a result with no
            aspects extracted at all means the response was unprocessable.
        """
        aspects = request.aspects
        response_spec = ResponseSpec(
            extractors={
                aspect: StrictAnchorExtractor(
                    left=f"<{aspect.upper()}>", right=f"</{aspect.upper()}>"
                )
                for aspect in aspects
            },
            required=[],
        )

        response_budget = one_shot_effective_response_budget(
            self.cc_one_shot_token_budget, self.client.max_token_length
        )
        if response_budget < self.cc_one_shot_token_budget:
            log.warning(
                "generate_character_unified: configured one-shot token budget "
                "does not fit the client context - clamping",
                configured=self.cc_one_shot_token_budget,
                effective=response_budget,
                max_token_length=self.client.max_token_length,
            )

        response, extracted = await Prompt.request(
            "creator.generate-character",
            self.client,
            f"create_{response_budget}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "aspects": aspects,
                "character_name": request.effective_name,
                "content": request.content,
                "description": request.description,
                "character": request.character,
                "dynamic_instructions": request.dynamic_instructions or [],
                "max_examples": request.max_examples,
                "max_attributes": request.max_attributes,
                "example_dialogue_instructions": request.example_dialogue_instructions,
                "attribute_instructions_text": format_attribute_instructions(
                    request.attribute_instructions
                )
                if request.attribute_instructions
                else "",
                "augment_attributes": request.augment_attributes,
                "history_budget": one_shot_history_budget(
                    self.client.max_token_length, response_budget
                ),
            },
            response_spec=response_spec,
        )

        log.debug(
            "generate_character_unified",
            aspects=aspects,
            extracted={k: bool(v) for k, v in extracted.items()},
        )

        return self._parse_unified_character_response(
            extracted,
            aspects,
            fallback_name=request.effective_name,
            max_examples=request.max_examples,
            max_attributes=request.max_attributes,
        )

    def _parse_unified_character_response(
        self,
        extracted: dict,
        aspects: list[CharacterGenerationAspect],
        fallback_name: str = "",
        max_examples: int = 5,
        max_attributes: int | None = None,
    ) -> CharacterGenerationResult:
        """Normalize the extracted sections into a CharacterGenerationResult.

        Aspects whose section could not be extracted (missing or unclosed
        tags - see StrictAnchorExtractor) are left empty for the caller's
        fill-misses policy.
        """
        result = CharacterGenerationResult()

        if "name" in aspects:
            raw_name = (extracted.get("name") or "").strip().strip('"').strip()
            if raw_name:
                result.name = raw_name.strip(".").strip()

        if "description" in aspects:
            raw_description = (extracted.get("description") or "").strip()
            if raw_description:
                result.description = raw_description

        if "attributes" in aspects:
            raw_attributes = (extracted.get("attributes") or "").strip()
            if raw_attributes:
                attributes = parse_attribute_lines(
                    raw_attributes, max_attributes=max_attributes
                )
                if attributes:
                    result.attributes = attributes

        if "dialogue_instructions" in aspects:
            raw_instructions = (
                (extracted.get("dialogue_instructions") or "")
                .strip()
                .strip('"')
                .strip()
            )
            if raw_instructions:
                result.dialogue_instructions = raw_instructions

        if "example_dialogue" in aspects:
            raw_examples = (extracted.get("example_dialogue") or "").strip()
            example_name = result.name or fallback_name
            if raw_examples and example_name:
                lines = [
                    line.strip() for line in raw_examples.split("\n") if line.strip()
                ]
                normalized = _normalize_example_dialogue_lines(
                    lines,
                    example_name,
                    other_known_names=[fallback_name],
                    max_examples=max_examples,
                )
                if normalized:
                    result.example_dialogue = normalized

        return result

    @set_processing
    async def generate_character_aspects(
        self,
        request: CharacterGenerationRequest,
    ) -> CharacterGenerationResult:
        """
        Orchestrates character aspect generation.

        When `unified` (Fast mode) is on, all requested aspects that are part
        of `consolidate` are generated with a single consolidated prompt; the
        remaining aspects are generated with their individual requests.
        Aspects the consolidated response missed entirely are retried with
        their individual requests when `fill_misses` is on, otherwise they
        are left empty (with a warning). A consolidated response from which
        none of the requested aspects could be extracted is a hard error
        (LLMAccuracyError) regardless of `fill_misses`.

        Args:
            request: The generation request (see CharacterGenerationRequest).

        Returns:
            CharacterGenerationResult with all requested aspects filled in
            (unless missed with fill_misses disabled).
        """
        unified = request.unified if request.unified is not None else self.cc_fast
        consolidate = (
            request.consolidate
            if request.consolidate is not None
            else self.cc_consolidate
        )
        fill_misses = (
            request.fill_misses
            if request.fill_misses is not None
            else self.cc_fill_misses
        )

        one_shot = [a for a in request.aspects if unified and a in consolidate]

        result = CharacterGenerationResult()

        # name the one-shot's example dialogue normalization fell back to
        # (relevant when the real name is only determined afterwards)
        one_shot_fallback_name = request.effective_name
        one_shot_example_name = None

        if one_shot:
            result = await self.generate_character_unified(
                request.model_copy(update={"aspects": one_shot})
            )
            if not result.extracted_aspects():
                raise LLMAccuracyError(
                    "creator.generate-character - none of the requested aspects "
                    f"({', '.join(one_shot)}) could be extracted from the "
                    "consolidated response. The model did not follow the "
                    "structured response format - choose a different model or "
                    "disable Fast Character Generation.",
                    model_name=self.client.model_name if self.client else "unknown",
                )
            # the name the one-shot's example dialogue was actually
            # normalized against
            one_shot_example_name = result.name or one_shot_fallback_name

        # transient character carrying everything generated so far, so
        # individual generations build on the consolidated results (and on
        # each other) even before a real character exists in the scene. A
        # provided character is detached via model_dump (actor/agent are
        # exclude=True and not deep-copyable), so scene-bound characters are
        # safe to pass and callers never see mutation.
        working_character = (
            Character(**request.character.model_dump())
            if request.character
            else Character(
                name=result.name or request.name or "the character",
                description=result.description or request.description or "",
            )
        )
        if result.name:
            working_character.name = result.name
        if result.description:
            working_character.description = result.description
        if result.attributes:
            working_character.base_attributes.update(result.attributes)

        for aspect in request.aspects:
            if aspect in result.extracted_aspects():
                continue

            missed = aspect in one_shot
            if missed and not fill_misses:
                log.warning(
                    "generate_character_aspects: aspect missed by consolidated "
                    "response and fill_misses is disabled - leaving empty",
                    aspect=aspect,
                )
                continue

            if missed:
                log.info(
                    "generate_character_aspects: filling in missed aspect with "
                    "individual request",
                    aspect=aspect,
                )

            if request.on_aspect_start:
                request.on_aspect_start(aspect)

            fill = getattr(self, _ASPECT_FILL_METHODS[aspect])
            await fill(request, result, working_character)

        # the one-shot normalized example dialogue against an earlier name
        # (raw fallback or missed name section) - redo the prefixes once the
        # real name is known
        if (
            result.example_dialogue
            and result.name
            and "example_dialogue" in one_shot
            and one_shot_example_name
            and result.name != one_shot_example_name
        ):
            result.example_dialogue = _normalize_example_dialogue_lines(
                result.example_dialogue,
                result.name,
                other_known_names=[one_shot_example_name, one_shot_fallback_name],
                max_examples=request.max_examples,
            )

        log.debug(
            "generate_character_aspects",
            requested=request.aspects,
            one_shot=one_shot,
            extracted=sorted(result.extracted_aspects()),
        )

        return result

    # per-aspect fill functions - name, description and attributes chain
    # onto the working character so later aspects build on them

    async def _fill_aspect_name(
        self,
        request: CharacterGenerationRequest,
        result: CharacterGenerationResult,
        working_character: Character,
    ) -> None:
        result.name = await self.determine_character_name(
            request.name, instructions=request.content
        )
        working_character.name = result.name

    async def _fill_aspect_description(
        self,
        request: CharacterGenerationRequest,
        result: CharacterGenerationResult,
        working_character: Character,
    ) -> None:
        result.description = await self.determine_character_description(
            working_character,
            text=request.content if request.content_role == "text" else "",
            information=request.content
            if request.content_role == "information"
            else "",
            dynamic_instructions=request.dynamic_instructions,
        )
        working_character.description = result.description

    async def _fill_aspect_attributes(
        self,
        request: CharacterGenerationRequest,
        result: CharacterGenerationResult,
        working_character: Character,
    ) -> None:
        world_state = instance.get_agent("world_state")
        fallback_instructions = list(request.dynamic_instructions or [])
        if request.attribute_instructions or request.augment_attributes:
            fallback_instruction_content = (
                format_attribute_instructions(request.attribute_instructions)
                if request.attribute_instructions
                else ""
            )
            if request.augment_attributes:
                # passing augmentation_instructions would flip
                # extract-character-sheet.jinja2 into its augment branch,
                # which renders character.sheet from the transient working
                # character - the augment text must ride in the dynamic
                # instruction instead
                fallback_instruction_content += (
                    f"\nAdditionally: {request.augment_attributes}"
                )
            fallback_instructions.append(
                DynamicInstruction(
                    title="ATTRIBUTE INSTRUCTIONS",
                    content=fallback_instruction_content.strip(),
                )
            )
        result.attributes = await world_state.extract_character_sheet(
            name=working_character.name,
            text=request.content,
            dynamic_instructions=fallback_instructions,
            max_attributes=request.max_attributes,
            character=working_character,
        )
        working_character.base_attributes.update(result.attributes)

    async def _fill_aspect_dialogue_instructions(
        self,
        request: CharacterGenerationRequest,
        result: CharacterGenerationResult,
        working_character: Character,
    ) -> None:
        result.dialogue_instructions = (
            await self.determine_character_dialogue_instructions(
                working_character,
                instructions=request.instructions,
                information=request.content,
            )
        )

    async def _fill_aspect_example_dialogue(
        self,
        request: CharacterGenerationRequest,
        result: CharacterGenerationResult,
        working_character: Character,
    ) -> None:
        result.example_dialogue = await self.determine_character_dialogue_examples(
            working_character,
            text=request.content,
            instructions=request.example_dialogue_instructions,
            dynamic_instructions=request.dynamic_instructions,
            max_examples=request.max_examples,
        )
