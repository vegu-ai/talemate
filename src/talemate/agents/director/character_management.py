from typing import TYPE_CHECKING
import traceback
import pydantic
import structlog
import talemate.instance as instance
import talemate.agents.tts.voice_library as voice_library
from talemate.agents.tts.schema import Voice
from talemate.util import random_color, chunk_items_by_tokens, remove_substring_names
from talemate.character import Character, set_voice, activate_character
from talemate.status import LoadingStatus
from talemate.exceptions import GenerationCancelled
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    set_processing,
    AgentEmission,
)
from talemate.agents.creator.character import (
    CharacterGenerationAspect,
    CharacterGenerationRequest,
    CharacterGenerationResult,
)
import talemate.game.focal as focal
from talemate.client.context import ClientContext
import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate import Scene
    from talemate.agents.tts import TTSAgent

async_signals.register(
    "agent.director.character_management.before_persist_character",
    "agent.director.character_management.after_persist_character",
)

__all__ = [
    "CharacterManagementMixin",
]

log = structlog.get_logger()

PERSIST_CHARACTER_EXAMPLE_DIALOGUE_COUNT = 3

NAME_REQUIRED_MESSAGE = (
    "A character name is required - none was provided or determined."
)

# per-aspect loading status messages for split-mode generation
SPLIT_ASPECT_LOADING_MESSAGES: dict[CharacterGenerationAspect, str] = {
    "name": "Determining character name",
    "attributes": "Generating character sheet",
    "description": "Generating character description",
    "dialogue_instructions": "Generating acting instructions",
    "example_dialogue": "Generating example dialogue",
}


def _requested_aspects(
    request: "PersistCharacterRequest",
    *,
    description: str,
    dialogue_instructions: str,
    example_dialogue: list[str] | None,
    any_attribute_templates: bool,
    include_name: bool = False,
    attributes_first: bool = False,
) -> list[CharacterGenerationAspect]:
    """Aspects still needing generation - shared by the fast and split
    paths. The name aspect only exists before the character is created
    (fast mode); split mode puts the sheet first so the later prompts
    render it."""
    aspects = []
    if include_name and request.determine_name:
        aspects.append("name")
    if not description:
        aspects.append("description")
    if (
        request.generate_attributes
        and not request.attributes
        and not any_attribute_templates
    ):
        aspects.append("attributes")
    if not dialogue_instructions:
        aspects.append("dialogue_instructions")
    if request.generate_example_dialogue and not example_dialogue:
        aspects.append("example_dialogue")
    if attributes_first and "attributes" in aspects:
        aspects.insert(0, aspects.pop(aspects.index("attributes")))
    return aspects


def _merge_generated(
    generated: CharacterGenerationResult,
    *,
    description: str,
    dialogue_instructions: str,
    example_dialogue: list[str] | None,
) -> tuple[str, str, list[str] | None]:
    """Fold generated aspects into the caller-supplied values (generated
    wins) - shared by the fast and split paths."""
    description = generated.description or description
    if generated.dialogue_instructions:
        dialogue_instructions = generated.dialogue_instructions
    if generated.example_dialogue:
        example_dialogue = generated.example_dialogue
    return description, dialogue_instructions, example_dialogue


class _FastPreparation(pydantic.BaseModel):
    """Outcome of the Fast-mode pre-generation step of persist_character."""

    name: str
    description: str
    dialogue_instructions: str
    example_dialogue: list[str] | None
    generated: CharacterGenerationResult | None
    collected_templates: dict | None


class _SplitPreparation(pydantic.BaseModel):
    """Outcome of the split-mode aspect-generation step of
    persist_character."""

    description: str
    dialogue_instructions: str
    example_dialogue: list[str] | None
    generated: CharacterGenerationResult | None


class PersistCharacterEmission(AgentEmission):
    character: Character


class VoiceCandidate(Voice):
    used: bool = False


class PersistCharacterRequest(pydantic.BaseModel):
    """Request parameters for persist_character.

    Attributes:
        generate: Master switch for AI generation. When False, no LLM
            calls are made at all: the character is created with the given
            name (required), description and attributes. Voice assignment
            and entry narration are skipped as well (both are AI features).
        dialogue_instructions: Pre-generated dialogue instructions (e.g.
            from the creator GenerateCharacter node) - skips the
            corresponding generation step.
        example_dialogue: Pre-generated example dialogue - skips the
            corresponding generation step.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    name: str
    content: str | None = None
    attributes: str | None = None
    determine_name: bool = True
    templates: list[str] | None = None
    active: bool = True
    narrate_entry: bool = False
    narrate_entry_direction: str = ""
    augment_attributes: str = ""
    generate_attributes: bool = True
    description: str = ""
    assign_voice: bool = True
    is_player: bool = False
    generate_example_dialogue: bool = False
    example_dialogue_instructions: str = ""
    generate: bool = True
    dialogue_instructions: str = ""
    example_dialogue: list[str] | None = None


class CharacterManagementMixin:
    """
    Director agent mixin that provides functionality for automatically guiding
    the actors or the narrator during the scene progression.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["character_management"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Character Management",
            icon="mdi-account",
            description="Configure how the director manages characters.",
            config={
                "assign_voice": AgentActionConfig(
                    type="bool",
                    label="Assign Voice (TTS)",
                    description="If enabled, the director is allowed to assign a text-to-speech voice when persisting a character.",
                    value=True,
                    title="Persisting Characters",
                ),
                "generate_visuals": AgentActionConfig(
                    type="bool",
                    label="Generate Visuals",
                    description="If enabled, the director is allowed to generate visuals for characters.",
                    value=True,
                    title="Generating Visuals",
                ),
                "max_attributes": AgentActionConfig(
                    type="number",
                    label="Limit character attributes",
                    description="Maximum number of attributes to generate for character sheets. Set to 0 for unlimited (default).",
                    value=0,
                    min=0,
                    max=40,
                    step=1,
                    title="Character Creation",
                ),
            },
        )

    # config property helpers

    @property
    def cm_assign_voice(self) -> bool:
        return self.resolve_config("character_management", "assign_voice")

    @property
    def cm_generate_visuals(self) -> bool:
        return self.resolve_config("character_management", "generate_visuals")

    @property
    def cm_max_attributes(self) -> int:
        return int(self.resolve_config("character_management", "max_attributes") or 0)

    @property
    def cm_should_assign_voice(self) -> bool:
        if not self.cm_assign_voice:
            return False

        tts_agent: "TTSAgent" = instance.get_agent("tts")
        if not tts_agent.enabled:
            return False

        if not tts_agent.ready_apis:
            return False

        return True

    # actions

    @set_processing
    async def persist_characters_from_worldstate(
        self, exclude: list[str] = None
    ) -> list[Character]:
        created_characters = []

        for character_name in self.scene.world_state.characters.keys():
            if exclude and character_name.lower() in exclude:
                continue

            if character_name in self.scene.character_names:
                continue

            character = await self.persist_character(
                PersistCharacterRequest(name=character_name)
            )

            created_characters.append(character)

        self.scene.emit_status()

        return created_characters

    async def _prepare_fast_generation(
        self,
        request: PersistCharacterRequest,
        *,
        max_attrs: int | None,
        loading_status: LoadingStatus,
    ) -> _FastPreparation:
        """Fast (consolidated) generation for persist_character.

        Runs before the character exists - the determined name is needed to
        create it. Also pre-collects generation templates so attribute
        templates can be folded into the attributes aspect (fold on) or
        suppress it (fold off).
        """
        creator = instance.get_agent("creator")
        scene: "Scene" = self.scene

        name = request.name
        description = request.description
        dialogue_instructions = request.dialogue_instructions
        example_dialogue = request.example_dialogue
        content = request.content or ""

        collected_templates = None
        any_attribute_templates = False
        if request.templates:
            collected_templates = (
                scene.world_state_manager.template_collection.collect_all(
                    request.templates
                )
            )
            any_attribute_templates = any(
                template.template_type == "character_attribute"
                for template in collected_templates.values()
            )

        # whether the attributes aspect can be consolidated at all (the
        # template fold below decides whether attribute templates suppress
        # it or feed it their instructions)
        can_one_shot_attributes = request.generate_attributes and not request.attributes

        # fold the attribute templates' instructions into the one-shot
        # instead of one prompt per template - only when the attributes
        # aspect can actually be consolidated; otherwise the templates apply
        # per-template as before. placeholders in the template text are
        # formatted with the input name (or "the character" while the name
        # is still being determined)
        attribute_instructions = None
        if (
            any_attribute_templates
            and creator.cc_consolidate_templates
            and "attributes" in creator.cc_consolidate
            and can_one_shot_attributes
        ):
            any_attribute_templates = False
            format_name = "the character" if request.determine_name else name
            attribute_instructions = [
                {
                    "attribute": template.formatted("attribute", scene, format_name),
                    "instructions": template.formatted(
                        "instructions", scene, format_name
                    )
                    or "",
                }
                for template in collected_templates.values()
                if template.template_type == "character_attribute"
            ]
            collected_templates = {
                uid: template
                for uid, template in collected_templates.items()
                if template.template_type != "character_attribute"
            }

        fast_aspects = _requested_aspects(
            request,
            description=description,
            dialogue_instructions=dialogue_instructions,
            example_dialogue=example_dialogue,
            any_attribute_templates=any_attribute_templates,
            include_name=True,
        )

        generated = None
        if fast_aspects:
            loading_status("Generating character")
            generated = await creator.generate_character_aspects(
                CharacterGenerationRequest(
                    aspects=fast_aspects,
                    name=name,
                    content=content,
                    description=description,
                    example_dialogue_instructions=request.example_dialogue_instructions,
                    max_examples=PERSIST_CHARACTER_EXAMPLE_DIALOGUE_COUNT,
                    max_attributes=max_attrs,
                    attribute_instructions=attribute_instructions,
                    augment_attributes=request.augment_attributes
                    if attribute_instructions
                    else "",
                )
            )
            if request.determine_name and generated.name:
                name = generated.name
                log.debug("persist_character", adjusted_name=name)
            description, dialogue_instructions, example_dialogue = _merge_generated(
                generated,
                description=description,
                dialogue_instructions=dialogue_instructions,
                example_dialogue=example_dialogue,
            )

        # a name is existential - if the one-shot missed it, try the
        # individual request before the caller's name guard rejects it
        if request.determine_name and not name:
            loading_status(SPLIT_ASPECT_LOADING_MESSAGES["name"])
            name = await creator.determine_character_name(name, instructions=content)
            log.debug("persist_character", adjusted_name=name)

        return _FastPreparation(
            name=name,
            description=description,
            dialogue_instructions=dialogue_instructions,
            example_dialogue=example_dialogue,
            generated=generated,
            collected_templates=collected_templates,
        )

    async def _determine_split_name(
        self,
        request: PersistCharacterRequest,
        *,
        loading_status: LoadingStatus,
    ) -> str:
        """Split mode: determine the name with its individual request - runs
        before the character exists, the name is needed to create it."""
        creator = instance.get_agent("creator")
        loading_status(SPLIT_ASPECT_LOADING_MESSAGES["name"])
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["name"],
                name=request.name,
                content=request.content or "",
                unified=False,
            )
        )
        log.debug("persist_character", adjusted_name=result.name)
        return result.name

    async def _prepare_split_generation(
        self,
        request: PersistCharacterRequest,
        *,
        character: Character,
        any_attribute_templates: bool,
        max_attrs: int | None,
        loading_status: LoadingStatus,
    ) -> _SplitPreparation:
        """Split (per-aspect) generation for persist_character - runs after
        the character exists and its sheet was resolved."""
        creator = instance.get_agent("creator")

        description = request.description
        dialogue_instructions = request.dialogue_instructions
        example_dialogue = request.example_dialogue

        aspects = _requested_aspects(
            request,
            description=description,
            dialogue_instructions=dialogue_instructions,
            example_dialogue=example_dialogue,
            any_attribute_templates=any_attribute_templates,
            attributes_first=True,
        )

        generated = None
        if aspects:
            generated = await creator.generate_character_aspects(
                CharacterGenerationRequest(
                    aspects=aspects,
                    name=character.name,
                    content=request.content or "",
                    character=character,
                    unified=False,
                    example_dialogue_instructions=request.example_dialogue_instructions,
                    max_examples=PERSIST_CHARACTER_EXAMPLE_DIALOGUE_COUNT,
                    max_attributes=max_attrs,
                    on_aspect_start=lambda aspect: loading_status(
                        SPLIT_ASPECT_LOADING_MESSAGES[aspect]
                    ),
                )
            )
            description, dialogue_instructions, example_dialogue = _merge_generated(
                generated,
                description=description,
                dialogue_instructions=dialogue_instructions,
                example_dialogue=example_dialogue,
            )

        return _SplitPreparation(
            description=description,
            dialogue_instructions=dialogue_instructions,
            example_dialogue=example_dialogue,
            generated=generated,
        )

    @set_processing
    async def persist_character(self, request: PersistCharacterRequest) -> Character:
        """
        Persist a character into the scene - the single backend process all
        character creation paths route through.

        When the creator agent's "Character Creation -> Fast Character
        Generation" setting is enabled, all applicable generation steps are
        consolidated into a single prompt (see
        creator.generate_character_aspects); otherwise each aspect is
        generated with its individual request via the same orchestrator
        (unified=False).

        Args:
            request: The creation request (see PersistCharacterRequest).
        """
        world_state = instance.get_agent("world_state")
        creator = instance.get_agent("creator")
        narrator = instance.get_agent("narrator")
        memory = instance.get_agent("memory")
        scene: "Scene" = self.scene

        loading_status = LoadingStatus(max_steps=None, cancellable=True)

        # Start of character creation
        log.debug("persist_character", name=request.name, generate=request.generate)

        # a name is existential - fail before any LLM call when no name was
        # provided and none will be determined
        if not request.name and not (request.generate and request.determine_name):
            raise ValueError(NAME_REQUIRED_MESSAGE)

        fast = request.generate and creator.cc_fast
        max_attrs = self.cm_max_attributes if self.cm_max_attributes > 0 else None

        name = request.name
        description = request.description
        dialogue_instructions = request.dialogue_instructions
        example_dialogue = request.example_dialogue

        generated = None
        collected_templates = None
        if fast:
            preparation = await self._prepare_fast_generation(
                request,
                max_attrs=max_attrs,
                loading_status=loading_status,
            )
            name = preparation.name
            description = preparation.description
            dialogue_instructions = preparation.dialogue_instructions
            example_dialogue = preparation.example_dialogue
            generated = preparation.generated
            collected_templates = preparation.collected_templates
        elif request.generate and request.determine_name:
            name = await self._determine_split_name(
                request, loading_status=loading_status
            )

        # a name is existential - regardless of mode and flag combination
        if not name:
            raise ValueError(NAME_REQUIRED_MESSAGE)

        if name in self.scene.all_character_names:
            raise ValueError(f'Name "{name}" already exists.')

        # Create the blank character
        character: Character = self.scene.Character(
            name=name, is_player=request.is_player
        )

        if description:
            character.description = description

        emission = PersistCharacterEmission(
            agent=self,
            character=character,
        )
        await async_signals.get(
            "agent.director.character_management.before_persist_character"
        ).send(emission)

        # Add the character to the scene
        character.color = random_color()

        if request.is_player:
            actor = self.scene.Player(
                character=character, agent=instance.get_agent("conversation")
            )
        else:
            actor = self.scene.Actor(
                character=character, agent=instance.get_agent("conversation")
            )

        await self.scene.add_actor(actor)

        try:
            any_attribute_templates = await self._apply_generation_templates(
                character,
                request,
                collected_templates=collected_templates,
                max_attrs=max_attrs,
                loading_status=loading_status,
            )

            # caller-provided attributes are resolved onto the character
            # before aspect generation - the downstream prompts render the
            # sheet
            if (
                not any_attribute_templates
                and request.generate_attributes
                and request.attributes
            ):
                character.base_attributes = world_state._parse_character_sheet(
                    request.attributes, max_attributes=max_attrs
                )

            # Enforce max_attributes limit on base_attributes if configured -
            # before aspect generation, so the downstream prompts render the
            # truncated sheet
            if max_attrs and len(character.base_attributes) > max_attrs:
                # Keep only the first N attributes (preserving insertion order)
                limited_attrs = dict(
                    list(character.base_attributes.items())[:max_attrs]
                )
                log.debug(
                    "persist_character",
                    limiting_attributes=True,
                    original_count=len(character.base_attributes),
                    limited_count=len(limited_attrs),
                )
                character.base_attributes = limited_attrs

            if not fast and request.generate:
                split = await self._prepare_split_generation(
                    request,
                    character=character,
                    any_attribute_templates=any_attribute_templates,
                    max_attrs=max_attrs,
                    loading_status=loading_status,
                )
                description = split.description
                dialogue_instructions = split.dialogue_instructions
                example_dialogue = split.example_dialogue
                generated = split.generated

            self._apply_base_attributes(
                character,
                request,
                generated=generated,
                any_attribute_templates=any_attribute_templates,
            )

            if description:
                character.description = description
                log.debug("persist_character", description=description)

            if dialogue_instructions:
                character.dialogue_instructions = dialogue_instructions
                log.debug(
                    "persist_character", dialogue_instructions=dialogue_instructions
                )

            if example_dialogue:
                character.example_dialogue = example_dialogue
                log.debug("persist_character", example_dialogue=example_dialogue)

            # Narrate the character's entry if the option is selected
            if request.generate and request.active and request.narrate_entry:
                loading_status("Narrating character entry")
                is_present = await world_state.is_character_present(name)
                if not is_present:
                    await narrator.action_to_narration(
                        "narrate_character_entry",
                        emit_message=True,
                        character=character,
                        narrative_direction=request.narrate_entry_direction,
                    )

            if request.generate and request.assign_voice:
                await self.assign_voice_to_character(character)

            # done() no-ops at step 0 - every mode needs one step to report
            # a terminal status
            loading_status("Adding character to scene")

            # Deactivate the character if not active
            if request.active:
                await activate_character(scene, character)

            # Commit the character's details to long term memory
            await character.commit_to_memory(memory)
            self.scene.emit_status()
            self.scene.world_state.emit()

            loading_status.done(
                message=f"{character.name} added to scene", status="success"
            )

            await async_signals.get(
                "agent.director.character_management.after_persist_character"
            ).send(emission)

            return character
        except GenerationCancelled:
            loading_status.done(message="Character creation cancelled", status="idle")
            await scene.remove_actor(actor)
        except Exception:
            loading_status.done(message="Character creation failed", status="error")
            await scene.remove_actor(actor)
            log.error("Error persisting character", error=traceback.format_exc())

    async def _apply_generation_templates(
        self,
        character: Character,
        request: PersistCharacterRequest,
        *,
        collected_templates: dict | None,
        max_attrs: int | None,
        loading_status: LoadingStatus,
    ) -> bool:
        """Apply the request's character generation templates (AI generation
        only - template values are LLM-generated, so manual mode skips them),
        augmenting the sheet from the content when instructed.

        Returns whether any attribute templates were applied - those suppress
        character sheet generation. Fast mode's template fold removes the
        folded templates from the collection beforehand, so the same
        computation holds for both modes.
        """
        if not (request.templates and request.generate):
            return False

        world_state = instance.get_agent("world_state")
        scene: "Scene" = self.scene

        loading_status("Applying character generation templates")
        if collected_templates is None:
            collected_templates = (
                scene.world_state_manager.template_collection.collect_all(
                    request.templates
                )
            )
        log.debug("persist_character", applying_templates=collected_templates)
        await scene.world_state_manager.apply_templates(
            collected_templates.values(),
            character_name=character.name,
            information=request.content,
        )

        # if any of the templates are attribute templates, then we no longer
        # need to generate a character sheet
        any_attribute_templates = any(
            template.template_type == "character_attribute"
            for template in collected_templates.values()
        )
        log.debug("persist_character", any_attribute_templates=any_attribute_templates)

        if (
            any_attribute_templates
            and request.augment_attributes
            and request.generate_attributes
        ):
            log.debug(
                "persist_character", augmenting_attributes=request.augment_attributes
            )
            loading_status("Augmenting character attributes")
            additional_attributes = await world_state.extract_character_sheet(
                name=character.name,
                text=request.content,
                augmentation_instructions=request.augment_attributes,
                max_attributes=max_attrs,
            )
            character.base_attributes.update(additional_attributes)

        return any_attribute_templates

    def _apply_base_attributes(
        self,
        character: Character,
        request: PersistCharacterRequest,
        *,
        generated: CharacterGenerationResult | None,
        any_attribute_templates: bool,
    ) -> None:
        """Apply the orchestrator's generated attributes (fast one-shot or
        split-mode individual request)."""
        if any_attribute_templates or not request.generate_attributes:
            return

        if generated and generated.attributes:
            character.base_attributes = generated.attributes

    @set_processing
    async def assign_voice_to_character(self, character: Character) -> list[focal.Call]:
        tts_agent: "TTSAgent" = instance.get_agent("tts")
        if not self.cm_should_assign_voice:
            log.debug("assign_voice_to_character", skip=True, reason="not enabled")
            return

        vl: voice_library.VoiceLibrary = voice_library.get_instance()

        ready_tts_apis = tts_agent.ready_apis

        voices_global = voice_library.voices_for_apis(ready_tts_apis, vl)
        voices_scene = voice_library.voices_for_apis(
            ready_tts_apis, self.scene.voice_library
        )

        voices = voices_global + voices_scene

        if not voices:
            log.debug(
                "assign_voice_to_character", skip=True, reason="no voices available"
            )
            return

        voice_candidates = {
            voice.id: VoiceCandidate(**voice.model_dump()) for voice in voices
        }

        for scene_character in self.scene.all_characters:
            if scene_character.voice and scene_character.voice.id in voice_candidates:
                voice_candidates[scene_character.voice.id].used = True

        async def assign_voice(voice_id: str):
            voice = vl.get_voice(voice_id) or self.scene.voice_library.get_voice(
                voice_id
            )
            if not voice:
                log.error(
                    "assign_voice_to_character",
                    skip=True,
                    reason="voice not found",
                    voice_id=voice_id,
                )
                return
            await set_voice(character, voice, auto=True)
            await self.log_action(
                f"Assigned voice `{voice.label}` to `{character.name}`",
                "Assigned voice",
                console_only=True,
            )

        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="assign_voice",
                    arguments=[focal.Argument(name="voice_id", type="str")],
                    fn=assign_voice,
                ),
            ],
            max_calls=1,
            character=character,
            voices=list(voice_candidates.values()),
            scene=self.scene,
            narrator_voice=tts_agent.narrator_voice,
        )

        await focal_handler.request("director.cm-assign-voice")

        log.debug("assign_voice_to_character", calls=focal_handler.state.calls)

        return focal_handler.state.calls

    async def _detect_characters_from_texts_chunk(
        self,
        texts: list[str],
        already_detected_names: list[str] | None = None,
    ) -> list[str]:
        """
        Internal method to detect characters from a single chunk of texts.

        Args:
            texts: List of texts to analyze for character detection
            already_detected_names: List of character names already detected (to avoid duplicates)

        Returns:
            List of unique character names detected in the texts
        """
        detected_character_names = []

        # Filter out empty texts
        texts = [t for t in texts if t and t.strip()]

        if not texts:
            return []

        if already_detected_names is None:
            already_detected_names = []

        async def add_detected_character(character_name: str):
            """Callback to add a detected character name."""
            if character_name not in detected_character_names:
                detected_character_names.append(character_name)
                log.debug(
                    "detect_characters_from_texts",
                    detected_character=character_name,
                )

        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="add_detected_character",
                    arguments=[
                        focal.Argument(name="character_name", type="str"),
                    ],
                    fn=add_detected_character,
                ),
            ],
            max_calls=20,  # Allow multiple detections
            texts=texts,
            already_detected_names=already_detected_names,
        )

        with ClientContext(requires_active_scene=False):
            await focal_handler.request("director.cm-detect-characters-from-texts")

        return detected_character_names

    @set_processing
    async def detect_characters_from_texts(
        self,
        texts: list[str],
        chunk_size_ratio: float = 0.75,
    ) -> list[str]:
        """
        Detect multiple characters from a list of texts by processing them in chunks
        based on the client's max context size.

        Args:
            texts: List of texts to analyze for character detection
            chunk_size_ratio: Ratio of max context size to use for chunk size (default: 0.75, i.e., 75%)

        Returns:
            List of unique character names detected in the texts
        """
        detected_character_names = []

        # Filter out empty texts
        texts = [t for t in texts if t and t.strip()]

        if not texts:
            log.debug("detect_characters_from_texts", no_texts=True)
            return []

        if not self.client:
            log.debug("detect_characters_from_texts", no_client=True)
            return []

        # Calculate chunk size based on ratio of max context size
        max_context_size = self.client.max_token_length
        chunk_size = int(max_context_size * chunk_size_ratio)

        # Process texts in chunks using the generic chunking utility
        # Pass through already detected names to avoid duplicates
        for chunk in chunk_items_by_tokens(texts, chunk_size):
            chunk_results = await self._detect_characters_from_texts_chunk(
                chunk, already_detected_names=detected_character_names
            )
            detected_character_names.extend(chunk_results)

        # Remove duplicates while preserving order
        seen = set()
        detected_character_names = [
            name
            for name in detected_character_names
            if name not in seen and not seen.add(name)
        ]

        # Always discard generic/system names
        excluded_names = {
            "user",
            "char",
            "__user__",
            "__char__",
            "{{user}}",
            "{{char}}",
        }
        detected_character_names = [
            name
            for name in detected_character_names
            if name.lower().strip() not in excluded_names
        ]

        # Remove shorter names that appear as whole words within longer names
        detected_character_names = remove_substring_names(detected_character_names)

        log.debug(
            "detect_characters_from_texts",
            detected_count=len(detected_character_names),
            characters=detected_character_names,
        )

        return detected_character_names
