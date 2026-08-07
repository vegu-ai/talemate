import re

import pydantic
import structlog
from thefuzz import fuzz

from .schema import (
    FINALIZER_MODE,
    VIS_TYPE,
    GenerationRequest,
    PromptFinalizer,
)

import talemate.emit.async_signals as async_signals
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    AgentEmission,
)
from talemate.prompts import Prompt
from talemate.ux.schema import Column, Condition, DynamicLabel, DynamicSpan

__all__ = [
    "PromptFinalizationMixin",
    "PromptFinalizeEmission",
    "apply_exact",
    "apply_fuzzy",
    "apply_regex",
    "cleanup_prompt",
    "validate_finalizers",
]

log = structlog.get_logger("talemate.agents.visual.finalize")

DEFAULT_FUZZY_THRESHOLD = 85

AI_RESPONSE_TAG = re.compile(
    r"<FINALIZED_PROMPT>(.*?)</FINALIZED_PROMPT>", re.DOTALL | re.IGNORECASE
)

async_signals.register(
    "agent.visual.prompt_finalize.before",
    "agent.visual.prompt_finalize.after",
)


class PromptFinalizeEmission(AgentEmission):
    positive_prompt: str | None = None
    negative_prompt: str | None = None
    vis_type: VIS_TYPE = VIS_TYPE.UNSPECIFIED
    character_name: str | None = None
    finalizers: list[PromptFinalizer] = pydantic.Field(default_factory=list)


def cleanup_prompt(text: str) -> str:
    """
    Tidy a prompt string after a removal: collapse segments left empty
    ("a, , b" -> "a, b"), squash duplicate spaces and strip dangling
    commas from the edges.
    """
    text = re.sub(r",(\s*,)+", ",", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"^[,\s]+|[,\s]+$", "", text)


def apply_exact(text: str, match: str, replace: str, case_sensitive: bool) -> str:
    """Substring search and replace; an empty replacement removes the match."""
    if not match:
        return text
    pattern = re.compile(re.escape(match), 0 if case_sensitive else re.IGNORECASE)
    if not pattern.search(text):
        return text
    result = pattern.sub(lambda _: replace, text)
    return cleanup_prompt(result) if not replace.strip() else result


def apply_fuzzy(text: str, match: str, replace: str, threshold: int) -> str:
    """
    Fuzzy search and replace on comma-separated prompt segments (always
    case insensitive). A segment scoring at or above the threshold is
    replaced whole; an empty replacement removes it.
    """
    if not match.strip():
        return text

    changed = False
    segments: list[str] = []

    for segment in text.split(","):
        segment = segment.strip()
        if segment and fuzz.ratio(segment.lower(), match.strip().lower()) >= threshold:
            changed = True
            if replace.strip():
                segments.append(replace.strip())
        elif segment:
            segments.append(segment)

    if not changed:
        return text
    return ", ".join(segments)


def apply_regex(text: str, pattern: str, replace: str, flags: list[str]) -> str:
    """
    Regex search and replace with group passthrough (``\\1`` / ``\\g<name>``).
    Invalid patterns or group references leave the text unchanged.
    """
    if not pattern:
        return text

    re_flags = 0 if "case_sensitive" in flags else re.IGNORECASE
    if "dot_all" in flags:
        re_flags |= re.DOTALL
    if "multiline" in flags:
        re_flags |= re.MULTILINE

    try:
        result = re.sub(pattern, replace, text, flags=re_flags)
    except re.error as exc:
        log.warning(
            "prompt_finalization.invalid_regex", pattern=pattern, error=str(exc)
        )
        return text

    return cleanup_prompt(result) if not replace.strip() else result


def validate_finalizers(rows: list) -> list[PromptFinalizer]:
    """Coerce raw config/table rows into PromptFinalizer models, skipping invalid rows."""
    finalizers = []
    for row in rows or []:
        if isinstance(row, PromptFinalizer):
            finalizers.append(row)
            continue
        try:
            finalizers.append(PromptFinalizer(**row))
        except (pydantic.ValidationError, TypeError) as exc:
            log.warning("prompt_finalization.invalid_row", row=row, error=str(exc))
    return finalizers


def finalizer_table_columns() -> list[Column]:
    return [
        Column(
            name="enabled",
            type="bool",
            label="",
            default_value=True,
            rail=True,
            disables_row=True,
        ),
        Column(
            name="mode",
            type="text",
            label="Mode",
            default_value=FINALIZER_MODE.EXACT.value,
            span=3,
            choices=[
                {"label": "Exact match", "value": FINALIZER_MODE.EXACT.value},
                {"label": "Fuzzy match", "value": FINALIZER_MODE.FUZZY.value},
                {"label": "Regex", "value": FINALIZER_MODE.REGEX.value},
                {"label": "AI", "value": FINALIZER_MODE.AI.value},
            ],
        ),
        Column(
            name="target",
            type="text",
            label="Target",
            default_value="POSITIVE",
            span=3,
            choices=[
                {"label": "Positive", "value": "POSITIVE"},
                {"label": "Negative", "value": "NEGATIVE"},
                {"label": "Both", "value": "BOTH"},
            ],
        ),
        Column(
            name="flags",
            type="flags",
            label="Flags",
            span=3,
            choices=[
                {"label": "Case sensitive", "value": "case_sensitive"},
                {"label": "Dot all (regex)", "value": "dot_all"},
                {"label": "Multiline (regex)", "value": "multiline"},
            ],
            # fuzzy matching is always case insensitive and AI mode has no
            # flags — the stored value is ignored for those modes
            condition=Condition(
                attribute="mode",
                value=[FINALIZER_MODE.EXACT.value, FINALIZER_MODE.REGEX.value],
            ),
        ),
        Column(
            name="vis_types",
            type="flags",
            label="Types",
            description="Visual types this action applies to. Empty applies to all.",
            span=3,
            # take over the row when the flags column is hidden
            dynamic_span=DynamicSpan(
                attribute="mode",
                spans={FINALIZER_MODE.FUZZY.value: 6, FINALIZER_MODE.AI.value: 6},
            ),
            choices=[
                {
                    "label": vis_type.value.replace("_", " ").title(),
                    "value": vis_type.value,
                }
                for vis_type in VIS_TYPE
            ],
        ),
        Column(
            name="match",
            type="blob",
            label="Match",
            description="Search string (exact, fuzzy) or pattern (regex).",
            span=12,
            rows=1,
            auto_grow=True,
            condition=Condition(
                attribute="mode",
                value=[
                    FINALIZER_MODE.EXACT.value,
                    FINALIZER_MODE.FUZZY.value,
                    FINALIZER_MODE.REGEX.value,
                ],
            ),
        ),
        Column(
            name="replace",
            type="blob",
            label="Replace",
            dynamic_label=DynamicLabel(
                attribute="mode",
                labels={FINALIZER_MODE.AI.value: "Instruct"},
            ),
            description="Replacement text, or the instruction for AI processing. An empty replacement removes the match.",
            span=12,
            rows=1,
            max_rows=15,
            auto_grow=True,
        ),
    ]


class PromptFinalizationMixin:
    """
    Visualizer agent mixin that applies user configured post-processing
    actions to the final prompt strings before image generation.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_prompt_finalization"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=True,
            label="Prompt Finalization",
            icon="mdi-auto-fix",
            description="Post-processing of image generation prompts. Actions run in order, right before the prompt is sent to the image generation backend.",
            config={
                "finalizers": AgentActionConfig(
                    type="table",
                    value=[],
                    # tags the table for the frontend's preset insert control,
                    # which appends editable copies of a template's actions
                    wstemplate_type="visual_finalizer",
                    label="Post-processing actions",
                    description="Actions are applied in order. Character specific actions (World Editor -> Character -> Visuals) run after these.",
                    columns=finalizer_table_columns(),
                    note=AgentActionNote(
                        title="AI processing",
                        text="AI actions send an extra AI query per targeted prompt (an action targeting Both adds two when a negative prompt is set), using the instruction in the Instruct field.",
                        icon="mdi-creation",
                    ),
                ),
                "fuzzy_threshold": AgentActionConfig(
                    type="number",
                    value=DEFAULT_FUZZY_THRESHOLD,
                    min=50,
                    max=100,
                    step=5,
                    label="Fuzzy match threshold",
                    description="Similarity (0-100) a prompt segment must reach to be considered a fuzzy match.",
                ),
            },
        )
        return actions

    # config

    @property
    def prompt_finalization_enabled(self) -> bool:
        return self.resolve_enabled("_prompt_finalization")

    @property
    def prompt_finalization_fuzzy_threshold(self) -> int:
        value = self.resolve_config("_prompt_finalization", "fuzzy_threshold")
        return int(value) if value else DEFAULT_FUZZY_THRESHOLD

    # helpers

    def gather_prompt_finalizers(
        self, character_name: str | None = None
    ) -> list[PromptFinalizer]:
        """
        Collect finalizers in execution order: the agent's actions first
        (scene overrides already resolved), then character specific actions
        when a character is targeted.
        """
        finalizers: list[PromptFinalizer] = []

        finalizers.extend(
            validate_finalizers(
                self.resolve_config("_prompt_finalization", "finalizers")
            )
        )

        scene = getattr(self, "scene", None)
        if scene and character_name:
            character = scene.get_character(character_name)
            if character and character.visual_finalizers:
                finalizers.extend(validate_finalizers(character.visual_finalizers))

        return finalizers

    # actions

    async def apply_prompt_finalizer(
        self,
        finalizer: PromptFinalizer,
        text: str,
        vis_type: VIS_TYPE,
        character_name: str | None = None,
    ) -> str:
        if finalizer.mode == FINALIZER_MODE.EXACT:
            return apply_exact(
                text, finalizer.match, finalizer.replace, finalizer.case_sensitive
            )
        if finalizer.mode == FINALIZER_MODE.FUZZY:
            return apply_fuzzy(
                text,
                finalizer.match,
                finalizer.replace,
                self.prompt_finalization_fuzzy_threshold,
            )
        if finalizer.mode == FINALIZER_MODE.REGEX:
            return apply_regex(
                text, finalizer.match, finalizer.replace, finalizer.flags
            )
        if finalizer.mode == FINALIZER_MODE.AI:
            return await self.apply_ai_finalizer(
                text, finalizer, vis_type, character_name
            )
        return text

    async def apply_ai_finalizer(
        self,
        text: str,
        finalizer: PromptFinalizer,
        vis_type: VIS_TYPE,
        character_name: str | None = None,
    ) -> str:
        instruction = finalizer.replace.strip()
        if not self.client or not text.strip() or not instruction:
            return text

        response, _ = await Prompt.request(
            "visual.finalize-prompt",
            self.client,
            "visualize_2048",
            vars={
                "scene": getattr(self, "scene", None),
                "prompt_text": text,
                "instruction": instruction,
                "character_name": character_name,
                "vis_type": vis_type.value,
                "max_tokens": self.client.max_token_length,
            },
        )

        tagged = AI_RESPONSE_TAG.search(response or "")
        finalized = tagged.group(1).strip() if tagged else (response or "").strip()
        return finalized or text

    async def finalize_prompts(
        self,
        positive: str | None,
        negative: str | None,
        vis_type: VIS_TYPE,
        character_name: str | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Apply all configured prompt finalizers to a positive / negative
        prompt string pair and return the finalized pair.

        The `agent.visual.prompt_finalize.before` / `.after` signals fire
        even when prompt finalization is disabled, so listeners can act as
        their own finalization mechanism. Handlers may mutate the prompt
        strings and (on `.before`) the finalizer list.
        """
        finalizers = (
            self.gather_prompt_finalizers(character_name)
            if self.prompt_finalization_enabled
            else []
        )

        emission = PromptFinalizeEmission(
            agent=self,
            positive_prompt=positive,
            negative_prompt=negative,
            vis_type=vis_type,
            character_name=character_name,
            finalizers=finalizers,
        )
        await async_signals.get("agent.visual.prompt_finalize.before").send(emission)

        positive = emission.positive_prompt
        negative = emission.negative_prompt

        for finalizer in emission.finalizers:
            if positive and finalizer.applies_to(vis_type, True):
                positive = await self.apply_prompt_finalizer(
                    finalizer, positive, vis_type, character_name
                )
            if negative and finalizer.applies_to(vis_type, False):
                negative = await self.apply_prompt_finalizer(
                    finalizer, negative, vis_type, character_name
                )

        emission.positive_prompt = positive
        emission.negative_prompt = negative
        await async_signals.get("agent.visual.prompt_finalize.after").send(emission)

        if emission.finalizers:
            log.debug(
                "prompt_finalization",
                vis_type=vis_type,
                character_name=character_name,
                finalizers=len(emission.finalizers),
                prompt=emission.positive_prompt,
                negative_prompt=emission.negative_prompt,
            )
        return emission.positive_prompt, emission.negative_prompt

    async def finalize_prompt_request(self, request: GenerationRequest):
        """
        Apply all configured prompt finalizers to the request's prompt
        strings, in place.
        """
        request.prompt, request.negative_prompt = await self.finalize_prompts(
            request.prompt,
            request.negative_prompt,
            request.vis_type,
            request.character_name,
        )
