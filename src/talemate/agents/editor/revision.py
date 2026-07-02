"""
Editor agent mixin that handles editing of dialogue and narration based on criteria and instructions

Signals:
- agent.editor.revision-analysis.before - sent before the revision analysis is requested
- agent.editor.revision-analysis.after - sent after the revision analysis is requested
"""

from typing import TYPE_CHECKING, Literal
import structlog
import uuid
import pydantic
from pydantic import ConfigDict
import re
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentActionNote,
    AgentTemplateEmission,
)
from talemate.instance import get_agent
from talemate.emit import emit
import talemate.emit.async_signals as async_signals
from talemate.agents.creator.assistant import ContextualGenerateEmission
from talemate.agents.summarize import SummarizeEmission
from talemate.agents.summarize.layered_history import LayeredHistoryFinalizeEmission
from talemate.events import HistoryEvent
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    NarratorMessage,
    SceneMessage,
)
from talemate.util.dedupe import (
    SimilarityMatch,
    compile_text_to_sentences,
    split_sentences_on_comma,
    dedupe_sentences_from_matches,
    similarity_matches,
)
from talemate.util.diff import dmp_inline_diff
from talemate.util import count_tokens
from talemate.prompts import Prompt
from talemate.prompts.response import ResponseSpec, AnchorExtractor
from talemate.exceptions import GenerationCancelled
from talemate.status import LoadingStatus
from talemate.world_state.templates.content import PhraseDetection
from contextvars import ContextVar

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

log = structlog.get_logger()

## RESPONSE SPECS

FIX_SPEC = ResponseSpec(
    extractors={
        "fix": AnchorExtractor(left="<FIX>", right="</FIX>"),
    },
    required=[],  # Not required - we handle None case
)

REWRITE_SPEC = ResponseSpec(
    extractors={
        "revision": AnchorExtractor(left="<REVISION>", right="</REVISION>"),
    },
    required=[],  # Not required - we handle None case
)

## CONFIG CONDITIONALS

dedupe_condition = AgentActionConditional(
    attribute="revision.config.revision_method",
    value="dedupe",
)

rewrite_condition = AgentActionConditional(
    attribute="revision.config.revision_method",
    value=["rewrite"],
)

rewrite_unslop_condition = AgentActionConditional(
    attribute="revision.config.revision_method",
    value=["rewrite", "unslop"],
)

detect_bad_prose_condition = AgentActionConditional(
    attribute="revision.config.detect_bad_prose",
    value=True,
)

automatic_revision_condition = AgentActionConditional(
    attribute="revision.config.automatic_revision",
    value=True,
)

## CONTEXT


class RevisionContextState(pydantic.BaseModel):
    message_id: int | None = None


revision_disabled_context = ContextVar("revision_disabled", default=False)
revision_context = ContextVar("revision_context", default=RevisionContextState())


class RevisionDisabled:
    def __enter__(self):
        self.token = revision_disabled_context.set(True)

    def __exit__(self, exc_type, exc_value, traceback):
        revision_disabled_context.reset(self.token)


class RevisionContext:
    def __init__(self, message_id: int | None = None):
        self.message_id = message_id

    def __enter__(self):
        self.token = revision_context.set(
            RevisionContextState(message_id=self.message_id)
        )

    def __exit__(self, exc_type, exc_value, traceback):
        revision_context.reset(self.token)


## SCHEMAS


class Issues(pydantic.BaseModel):
    repetition: list[dict] = pydantic.Field(default_factory=list)
    repetition_matches: list[SimilarityMatch] = pydantic.Field(default_factory=list)
    bad_prose: list[PhraseDetection] = pydantic.Field(default_factory=list)
    repetition_log: list[str] = pydantic.Field(default_factory=list)
    bad_prose_log: list[str] = pydantic.Field(default_factory=list)

    @property
    def log(self) -> list[str]:
        return self.repetition_log + self.bad_prose_log


class RevisionInformation(pydantic.BaseModel):
    text: str | None = None
    revision_method: Literal["dedupe", "rewrite", "unslop"] | None = None
    character: object = None
    context_type: str | None = None
    context_name: str | None = None
    loading_status: LoadingStatus | None = pydantic.Field(
        default_factory=LoadingStatus, exclude=True
    )
    summarization_history: list[str] | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


CONTEXTUAL_GENERATION_TYPES = [
    "character attribute",
    "character detail",
    # "scene intent",
    # "scene phase intent",
    "world context",
    "scene intro",
]

## SIGNALS

async_signals.register(
    "agent.editor.revision-analysis.before",
    "agent.editor.revision-analysis.after",
    "agent.editor.revision-revise.before",
    "agent.editor.revision-revise.after",
)


class RevisionEmission(AgentTemplateEmission):
    """
    Emission for the revision agent
    """

    info: RevisionInformation = pydantic.Field(default_factory=RevisionInformation)
    issues: Issues = pydantic.Field(default_factory=Issues)


# Maximum ratio of fix length to original length before discarding
# the fix as hallucinated content. Unslop should trim, not expand.
UNSLOP_MAX_LENGTH_RATIO = 1.25

# Maximum ratio of revision length to original length before discarding
# the rewrite as hallucinated content. Rewrites should stay close to the
# original length — the analysis template explicitly forbids expansion.
REWRITE_MAX_LENGTH_RATIO = 1.25

# Extra token headroom added on top of the draft's token count when sizing
# the response budget for revision prompts. Gives the model room for the
# analysis preamble before it emits the wrapped rewrite.
REVISION_RESPONSE_HEADROOM = 768


def _format_length_ratio(new_len: int, original_len: int) -> str:
    """
    Format a length ratio for log output, guarding against division by zero
    when the original text is empty.
    """
    if not original_len:
        return "inf"
    return f"{new_len / original_len:.2f}"


def _strip_character_prefix(
    text: str, character: "Character | None"
) -> tuple[str, bool]:
    """
    If ``text`` starts with ``"{character.name}: "``, return the stripped body
    and ``True``. Otherwise return the text unchanged and ``False``.

    Used by the revision methods to compare/rewrite the raw dialogue body
    without the speaker prefix, which would otherwise confuse the model.
    """
    if character and text.startswith(f"{character.name}: "):
        return text[len(character.name) + 2 :], True
    return text, False


def _reattach_character_prefix(
    text: str, character: "Character | None", had_prefix: bool
) -> str:
    """
    Re-add the ``"{character.name}: "`` prefix if it was originally present
    and is not already on the (possibly model-produced) ``text``. The
    idempotency guard protects against models that include the speaker
    prefix inside their own response.
    """
    if not had_prefix or not character:
        return text
    if text.startswith(f"{character.name}: "):
        return text
    return f"{character.name}: {text}"


def _revision_exceeds_max_length(
    method_name: str,
    original_text: str,
    revised_text: str,
    ratio: float,
) -> bool:
    """
    Return ``True`` if ``revised_text`` is longer than ``ratio`` times the
    length of ``original_text``. Emits a warning log entry that identifies
    which revision method tripped the guardrail.

    Revisions should stay close to the original length — the prompts
    explicitly forbid expansion — so anything past the ratio is almost
    always hallucinated content and should be discarded.
    """
    if len(revised_text) <= len(original_text) * ratio:
        return False
    log.warning(
        f"{method_name}: revision is too long, discarding",
        original_len=len(original_text),
        revised_len=len(revised_text),
        ratio=_format_length_ratio(len(revised_text), len(original_text)),
    )
    return True


## MIXIN


class RevisionMixin:
    """
    Editor agent mixin that handles editing of dialogue and narration based on criteria and instructions
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["revision"] = AgentAction(
            enabled=False,
            can_be_disabled=True,
            container=True,
            quick_toggle=True,
            label="Revision",
            icon="mdi-typewriter",
            description="Remove / rewrite content based on criteria and instructions.",
            config={
                "automatic_revision": AgentActionConfig(
                    type="bool",
                    label="Automatic revision",
                    description="Enable / Disable automatic revision.",
                    value=True,
                    quick_toggle=True,
                ),
                "automatic_revision_targets": AgentActionConfig(
                    type="flags",
                    label="Automatic revision targets",
                    condition=automatic_revision_condition,
                    description="Which types of messages to automatically revise.",
                    value=["character", "narrator"],
                    value_migration=lambda v: ["character", "narrator"]
                    if v is True
                    else []
                    if v is False
                    else v,
                    choices=sorted(
                        [
                            {
                                "label": "Character Messages",
                                "value": "character",
                                "help": "Automatically revise actor actions.",
                            },
                            {
                                "label": "Narration Messages",
                                "value": "narrator",
                                "help": "Automatically revise narrator actions.",
                            },
                            {
                                "label": "Context Investigations",
                                "value": "context_investigation",
                                "help": "Automatically revise context-investigation messages (look-at, query, examine, etc).",
                            },
                            {
                                "label": "Contextual generation",
                                "value": "contextual_generation",
                                "help": "Automatically revise generated context (character attributes, details, etc).",
                            },
                            {
                                "label": "Summarization",
                                "value": "summarization",
                                "help": "Automatically revise summarization.",
                            },
                        ],
                        key=lambda x: x["label"],
                    ),
                ),
                "revision_method": AgentActionConfig(
                    type="text",
                    label="Revision method",
                    description="The method to use to revise the text",
                    value="unslop",
                    choices=[
                        {"label": "Dedupe (Fast and dumb)", "value": "dedupe"},
                        {"label": "Unslop (AI assisted)", "value": "unslop"},
                        {"label": "Targeted Rewrite (AI assisted)", "value": "rewrite"},
                    ],
                    note_on_value={
                        "dedupe": AgentActionNote(
                            color="primary",
                            text="This will attempt to dedupe the text if repetition is detected. Will remove content without substituting it, so may cause sentence structure or logic issues.",
                        ),
                        "unslop": AgentActionNote(
                            color="primary",
                            text="This calls 1 additional prompt after a generation and will attempt to remove repetition, purple prose, unnatural dialogue, and over-description. May cause details to be lost.",
                        ),
                        "rewrite": AgentActionNote(
                            color="primary",
                            text="Each generation will be checked for repetition and unwanted prose. If issues are found, a rewrite of the problematic part(s) will be attempted. (+1 prompt)",
                        ),
                    },
                ),
                "split_on_comma": AgentActionConfig(
                    title="Preferences for rewriting",
                    type="bool",
                    label="Test parts of sentences, split on commas",
                    condition=rewrite_condition,
                    description="If a whole sentence does not trigger a revision issue, split the sentence on commas and test each comma individually.",
                    value=True,
                ),
                "min_issues": AgentActionConfig(
                    type="number",
                    label="Minimum issues",
                    condition=rewrite_condition,
                    description="The minimum number of issues to trigger a rewrite.",
                    value=1,
                    min=1,
                    max=10,
                    step=1,
                ),
                "detect_bad_prose": AgentActionConfig(
                    title="Unwanted prose",
                    type="bool",
                    label="Detect unwanted prose",
                    description="Enable / Disable unwanted prose detection. Will use the writing style's phrase detection to determine unwanted phrases. The scene MUST have a writing style selected.",
                    condition=rewrite_unslop_condition,
                    value=True,
                ),
                "detect_bad_prose_threshold": AgentActionConfig(
                    type="number",
                    label="Unwanted prose threshold",
                    condition=rewrite_unslop_condition,
                    description="The threshold for detecting unwanted prose when using semantic similarity.",
                    value=0.7,
                    min=0.4,
                    max=1.0,
                    step=0.01,
                ),
                "repetition_detection_method": AgentActionConfig(
                    title="Repetition",
                    type="text",
                    label="Repetition detection method",
                    description="The method to use to detect repetition",
                    value="semantic_similarity",
                    choices=[
                        # fuzzy matching (not ai assisted)
                        # semantic similarity (ai assisted, using memory agent embedding function)
                        {"label": "Fuzzy matching", "value": "fuzzy"},
                        {
                            "label": "Semantic similarity (embeddings)",
                            "value": "semantic_similarity",
                        },
                    ],
                    note_on_value={
                        "semantic_similarity": AgentActionNote(
                            color="warning",
                            text="Uses the memory agent's embedding function to compare the text. Will use batching when available, but has the potential to do A LOT of calls to the embedding model.",
                        )
                    },
                ),
                "repetition_threshold": AgentActionConfig(
                    type="number",
                    label="Similarity threshold",
                    description="The similarity threshold for detecting repetition. How similar the text needs to be to be considered repetition.",
                    value=85,
                    min=50,
                    max=100,
                    step=1,
                ),
                "repetition_range": AgentActionConfig(
                    type="number",
                    label="Repetition range",
                    description="Number of message in the history to check against when analyzing repetition.",
                    value=15,
                    min=1,
                    max=100,
                    step=1,
                ),
                "repetition_min_length": AgentActionConfig(
                    type="number",
                    label="Repetition min length",
                    description="The minimum length of a sentence to be considered for repetition checking. (characters, not tokens)",
                    value=15,
                    min=1,
                    max=100,
                    step=1,
                ),
                "repetition_handling": AgentActionConfig(
                    type="text",
                    label="Repetition handling",
                    description="What the AI-assisted revision should do with detected repetitions.",
                    condition=rewrite_unslop_condition,
                    value="remove",
                    choices=[
                        {"label": "Remove", "value": "remove"},
                        {"label": "Attempt rewrite", "value": "rewrite"},
                    ],
                    note_on_value={
                        "remove": AgentActionNote(
                            color="primary",
                            text="Flagged repetitions are deleted from the text. Safer choice for weaker models, which often struggle to substitute genuinely different content and end up rephrasing the same idea — re-introducing the very repetition the rule is meant to fix.",
                        ),
                        "rewrite": AgentActionNote(
                            color="primary",
                            text="The agent will attempt to rewrite flagged repetitions with genuinely different content. Because matches are semantic, simply rephrasing the same idea is not enough — the underlying beat must change, which weaker models tend to fail at. Best with stronger models. Falls back to removal only when no meaningful rewrite is possible.",
                        ),
                    },
                ),
            },
        )

    # config property helpers

    @property
    def revision_enabled(self):
        return self.resolve_enabled("revision")

    @property
    def revision_automatic_enabled(self) -> bool:
        return self.resolve_config("revision", "automatic_revision")

    @property
    def revision_automatic_targets(self) -> list[str]:
        return self.resolve_config("revision", "automatic_revision_targets")

    @property
    def revision_method(self):
        return self.resolve_config("revision", "revision_method")

    @property
    def revision_repetition_detection_method(self):
        return self.resolve_config("revision", "repetition_detection_method")

    @property
    def revision_repetition_threshold(self):
        return self.resolve_config("revision", "repetition_threshold")

    @property
    def revision_repetition_range(self):
        return self.resolve_config("revision", "repetition_range")

    @property
    def revision_repetition_min_length(self):
        return self.resolve_config("revision", "repetition_min_length")

    @property
    def revision_repetition_handling(self):
        return self.resolve_config("revision", "repetition_handling")

    @property
    def revision_split_on_comma(self):
        return self.resolve_config("revision", "split_on_comma")

    @property
    def revision_min_issues(self):
        return self.resolve_config("revision", "min_issues")

    @property
    def revision_detect_bad_prose_enabled(self):
        return self.resolve_config("revision", "detect_bad_prose")

    @property
    def revision_detect_bad_prose_threshold(self):
        return self.resolve_config("revision", "detect_bad_prose_threshold")

    # signal connect

    def connect(self, scene):
        async_signals.get("agent.creator.contextual_generate.after").connect(
            self.revision_on_generation
        )
        async_signals.get("agent.summarization.summarize.after").connect(
            self.revision_on_generation
        )
        async_signals.get("agent.summarization.layered_history.finalize").connect(
            self.revision_on_generation
        )
        # Character / narrator revision runs at push_history time so the
        # SceneMessage exists and the pre-revision text is naturally
        # preserved as the initial "original" entry of the version stack
        # when we append the revised version.
        async_signals.get("push_history").connect(self.revision_on_push)
        # connect to the super class AFTER so these run first.
        super().connect(scene)

    def _revision_automatic_target_enabled(self, target: str) -> bool:
        if not self.revision_enabled or not self.revision_automatic_enabled:
            return False
        return target in self.revision_automatic_targets

    def _revision_disabled_by_context(self) -> bool:
        try:
            return bool(revision_disabled_context.get())
        except LookupError:
            return False

    async def revision_on_generation(
        self,
        emission: ContextualGenerateEmission
        | SummarizeEmission
        | LayeredHistoryFinalizeEmission,
    ):
        """
        Auto-revision for non-SceneMessage emissions (contextual generation
        and summarization). Mutates ``emission.response`` in place because
        these flows have no SceneMessage to attach a mutation history to.

        Character / narrator emissions are handled separately at
        ``push_history`` time by ``revision_on_push``.
        """

        if not self.revision_enabled or not self.revision_automatic_enabled:
            return

        if (
            isinstance(emission, ContextualGenerateEmission)
            and "contextual_generation" not in self.revision_automatic_targets
        ):
            return

        if isinstance(emission, SummarizeEmission):
            if (
                emission.summarization_type == "dialogue"
                and "summarization" not in self.revision_automatic_targets
            ):
                return
            if emission.summarization_type == "events":
                # event summarization is very pragmatic and doesn't really benefit
                # from revision, so we skip it
                return

        if (
            isinstance(emission, LayeredHistoryFinalizeEmission)
            and "summarization" not in self.revision_automatic_targets
        ):
            return

        if self._revision_disabled_by_context():
            log.debug(
                "revision_on_generation: revision disabled through context",
                emission=emission,
            )
            return

        info = RevisionInformation(
            text=emission.response,
            character=getattr(emission, "character", None),
            context_type=getattr(emission, "context_type", None),
            context_name=getattr(emission, "context_name", None),
        )

        if isinstance(emission, (SummarizeEmission, LayeredHistoryFinalizeEmission)):
            info.summarization_history = emission.summarization_history or []

        if (
            isinstance(emission, ContextualGenerateEmission)
            and info.context_type not in CONTEXTUAL_GENERATION_TYPES
        ):
            return

        revised_text = await self.revision_revise(info)

        emission.response = revised_text
        log.info(
            "Revision done",
            type=type(emission).__name__,
            revised=revised_text,
            original=info.text,
        )

    async def maybe_revise_inplace(self, message: SceneMessage) -> bool:
        """
        Run auto-revision on a SceneMessage. If the configured revision
        method actually rewrote the text, a new ``"revision"`` version is
        appended to ``message.versions`` (which makes it the active
        canonical) and the call returns ``True``. Otherwise returns
        ``False`` and the stack is untouched.

        The pre-revision text is naturally preserved as whichever stack
        entry was active before — typically the "original" seeded at
        construction, but it could be a prior revision/regenerate if this
        message has already been rewritten.

        Gating mirrors ``revision_on_generation``: only fires for
        ``CharacterMessage`` / ``NarratorMessage`` / ``ContextInvestigationMessage``
        when the corresponding ``automatic_revision_targets`` flag is set
        and revision is enabled / automatic / not disabled by context.
        """
        if isinstance(message, CharacterMessage):
            target = "character"
        elif isinstance(message, NarratorMessage):
            target = "narrator"
        elif isinstance(message, ContextInvestigationMessage):
            target = "context_investigation"
        else:
            return False

        # Player-authored messages (character or narrator) must not be
        # auto-revised — the player's words are theirs, not ours to rewrite.
        if message.source == "player":
            return False

        if not self._revision_automatic_target_enabled(target):
            return False

        if self._revision_disabled_by_context():
            log.debug(
                "maybe_revise_inplace: revision disabled through context",
                message_id=message.id,
            )
            return False

        character = None
        if isinstance(message, CharacterMessage):
            character = self.scene.get_character(message.character_name)

        original = message.message
        info = RevisionInformation(text=original, character=character)
        revised = await self.revision_revise(info)

        if revised == original:
            return False

        log.info(
            "maybe_revise_inplace: revision applied",
            type=type(message).__name__,
            revised=revised,
            original=original,
        )
        message.append_version(revised, source="revision")
        return True

    async def revision_on_push(self, event: HistoryEvent):
        """
        Run auto-revision on the first CharacterMessage / NarratorMessage /
        ContextInvestigationMessage being pushed to scene history. When the
        revision rewrites the text, a new ``"revision"`` version is appended
        to the message's stack — the original is already at index 0 from
        construction, so the wire emit picks up both atomically when
        push_history returns.

        Only the first matching message is processed — push_history events
        rarely batch revisable messages, and revision is a single-target
        operation.

        Cancellation: the message is already committed to ``scene.history``
        by the time this fires, and callers emit the wire message *after*
        ``push_history`` returns. If a cancel escapes here, the trailing
        ``push_history.after`` listeners (e.g. the summarizer's
        ``build_archive``) would also re-raise off the still-set
        ``scene.cancel_requested`` flag, stripping the wire emit and
        leaving the message stranded in history but invisible in the UX.
        Contain the cancel here so the original message still reaches the
        UX — equivalent to "revision aborted, keep the original".
        """
        for message in event.messages:
            if not isinstance(
                message,
                (CharacterMessage, NarratorMessage, ContextInvestigationMessage),
            ):
                continue
            # The message is already in scene history by the time the
            # push_history signal fires, so scope the revision context to
            # it — otherwise the repetition range collects the message
            # itself and every sentence matches itself at 100%.
            try:
                with RevisionContext(message.id):
                    await self.maybe_revise_inplace(message)
            except GenerationCancelled:
                log.warning(
                    "revision_on_push: revision cancelled — keeping original",
                    message_id=message.id,
                )
            # revision_revise catches GenerationCancelled internally and
            # returns the original text, but the scene-level cancel flag
            # stays set (client's poll_interrupt doesn't reset it). Clear
            # it so push_history.after agent actions don't re-raise.
            if self.scene.cancel_requested:
                self.scene.cancel_requested = False
            return

    # helpers

    async def revision_collect_repetition_range(self) -> list[str]:
        """
        Collect the range of text to revise against by going through the scene's
        history and collecting narrator, character, and context-investigation
        messages. CIMs are included regardless of whether they're an
        automatic-revision target so the corpus reflects everything the player
        sees in the narrative flow.
        """

        scene: "Scene" = self.scene

        ctx = revision_context.get()

        messages = scene.collect_messages(
            typ=["narrator", "character", "context_investigation"],
            max_messages=self.revision_repetition_range,
            start_idx=scene.message_index(ctx.message_id) - 1
            if ctx.message_id
            else None,
        )

        return_messages = []

        for message in messages:
            if isinstance(message, CharacterMessage):
                return_messages.append(message.without_name)
            else:
                return_messages.append(message.message)

        return return_messages

    async def _emit_revision_diff(
        self,
        header: str,
        original: str,
        revised: str,
        issues: Issues,
        meta: dict,
        color: str = "highlight4",
    ) -> None:
        """
        Emit a UI-side ``agent_message`` diff showing the original text, the
        revision, and the issues that triggered the revision. Used by both
        ``revision_rewrite`` and ``revision_unslop`` to report their work.
        """
        diff = dmp_inline_diff(original, revised)
        await self.emit_message(
            header,
            message=[
                {"subtitle": "Issues", "content": issues.log},
                {"subtitle": "Original", "content": original},
                {"subtitle": "Changes", "content": diff, "process": "diff"},
            ],
            meta=meta,
            color=color,
        )

    # actions

    @set_processing
    async def revision_revise(
        self,
        info: RevisionInformation,
    ):
        """
        Revise the text based on the revision method
        """

        try:
            if self.revision_method == "dedupe":
                return await self.revision_dedupe(info)
            elif self.revision_method == "rewrite":
                return await self.revision_rewrite(info)
            elif self.revision_method == "unslop":
                return await self.revision_unslop(info)
        except GenerationCancelled:
            log.warning("revision_revise: generation cancelled", text=info.text)
            return info.text
        except Exception:
            import traceback

            log.error("revision_revise: error", error=traceback.format_exc())
            return info.text
        finally:
            info.loading_status.done()

    async def _revision_evaluate_semantic_similarity(
        self, text: str, character: "Character | None" = None
    ) -> list[SimilarityMatch]:
        """
        Detect repetition using semantic similarity
        """

        memory_agent = get_agent("memory")
        character_name_prefix = (
            text.startswith(f"{character.name}: ") if character else False
        )

        if character_name_prefix:
            text = text[len(character.name) + 2 :]

        compare_against: list[str] = await self.revision_collect_repetition_range()

        text_sentences = compile_text_to_sentences(text)

        history_sentences = []
        for sentence in compare_against:
            history_sentences.extend(compile_text_to_sentences(sentence))

        min_length = self.revision_repetition_min_length

        # strip min length sentences from both lists
        text_sentences = [i for i in text_sentences if len(i[1]) >= min_length]
        history_sentences = [i for i in history_sentences if len(i[1]) >= min_length]

        result_matrix = await memory_agent.compare_string_lists(
            [i[1] for i in text_sentences],
            [i[1] for i in history_sentences],
            similarity_threshold=self.revision_repetition_threshold / 100,
        )

        similarity_matches = []

        for match in result_matrix["similarity_matches"]:
            index_text = match[0]
            index_history = match[1]
            sentence = text_sentences[index_text][1]
            matched = history_sentences[index_history][1]
            similarity_matches.append(
                SimilarityMatch(
                    original=str(sentence),
                    matched=str(matched),
                    similarity=round(match[2] * 100, 2),
                    left_neighbor=text_sentences[index_text - 1][1]
                    if index_text > 0
                    else None,
                    right_neighbor=text_sentences[index_text + 1][1]
                    if index_text < len(text_sentences) - 1
                    else None,
                )
            )

        return list(set(similarity_matches))

    async def _revision_evaluate_fuzzy_similarity(
        self, text: str, character: "Character | None" = None
    ) -> list[SimilarityMatch]:
        """
        Detect repetition using fuzzy matching and dedupe

        Will return a tuple with the deduped text and the deduped text
        """

        compare_against: list[str] = await self.revision_collect_repetition_range()

        matches = []

        for old_text in compare_against:
            matches.extend(
                similarity_matches(
                    text,
                    old_text,
                    similarity_threshold=self.revision_repetition_threshold,
                    min_length=self.revision_repetition_min_length,
                    split_on_comma=self.revision_split_on_comma,
                )
            )

        return list(set(matches))

    async def revision_detect_bad_prose(self, text: str) -> list[dict]:
        """
        Detect bad prose in the text
        """
        try:
            sentences = compile_text_to_sentences(text)
            identified = []

            writing_style = self.scene.writing_style

            if not writing_style or not writing_style.phrases:
                return []

            if self.revision_split_on_comma:
                sentences = split_sentences_on_comma(
                    [sentence[0] for sentence in sentences]
                )

            # collect all phrases by method
            semantic_similarity_phrases = []
            regex_phrases = []

            for phrase in writing_style.phrases:
                if not phrase.phrase or not phrase.instructions or not phrase.active:
                    continue

                if phrase.match_method == "semantic_similarity":
                    semantic_similarity_phrases.append(phrase)
                elif phrase.match_method == "regex":
                    regex_phrases.append(phrase)

            # evaulate regex phrases first
            for phrase in regex_phrases:
                for sentence in sentences:
                    identified.extend(
                        await self._revision_detect_bad_prose_regex(sentence, phrase)
                    )

            # next evaulate semantic similarity phrases at once
            identified.extend(
                await self._revision_detect_bad_prose_semantic_similarity(
                    sentences, semantic_similarity_phrases
                )
            )
            return identified
        except Exception as e:
            log.error("revision_detect_bad_prose: error", error=e)
            return []

    async def _revision_detect_bad_prose_semantic_similarity(
        self, sentences: list[str], phrases: list[PhraseDetection]
    ) -> list[dict]:
        """
        Detect bad prose in the text using semantic similarity
        """

        memory_agent = get_agent("memory")

        if not memory_agent:
            return []

        """
        Compare two lists of strings using the current embedding function without touching the database.

        Returns a dictionary with:
            - 'cosine_similarity_matrix': np.ndarray of shape (len(list_a), len(list_b))
            - 'euclidean_distance_matrix': np.ndarray of shape (len(list_a), len(list_b))
            - 'similarity_matches': list of (i, j, score) (filtered if threshold set, otherwise all)
            - 'distance_matches': list of (i, j, distance) (filtered if threshold set, otherwise all)
        """
        threshold = self.revision_detect_bad_prose_threshold

        phrase_strings = [phrase.phrase for phrase in phrases]

        num_comparisons = len(sentences) * len(phrase_strings)

        log.debug(
            "revision_detect_bad_prose: comparing sentences to phrases",
            num_comparisons=num_comparisons,
        )

        result_matrix = await memory_agent.compare_string_lists(
            sentences, phrase_strings, similarity_threshold=threshold
        )

        result = []

        for match in result_matrix["similarity_matches"]:
            sentence = sentences[match[0]]
            phrase = phrases[match[1]]
            result.append(
                {
                    "phrase": sentence,
                    "instructions": phrase.instructions,
                    "reason": "Unwanted phrase found",
                    "matched": phrase.phrase,
                    "method": "semantic_similarity",
                    "similarity": match[2],
                }
            )

        return result

    async def _revision_detect_bad_prose_regex(
        self, sentence: str, phrase: PhraseDetection
    ) -> list[dict]:
        """
        Detect bad prose in the text using regex
        """
        if str(phrase.classification).lower() != "unwanted":
            return []

        pattern = re.compile(phrase.phrase)
        if not pattern.search(sentence, re.IGNORECASE):
            return []

        return [
            {
                "phrase": sentence,
                "instructions": phrase.instructions,
                "reason": "Unwanted phrase found",
                "matched": phrase.phrase,
                "method": "regex",
            }
        ]

    async def revision_collect_issues(
        self,
        text: str,
        character: "Character | None" = None,
        detect_bad_prose: bool = True,
    ) -> Issues:
        """
        Collect issues from the text
        """
        writing_style = self.scene.writing_style
        detect_bad_prose = (
            self.revision_detect_bad_prose_enabled
            and writing_style
            and detect_bad_prose
        )

        repetition_log = []
        bad_prose_log = []

        repetition = []
        bad_prose = []

        # Step 1 - Detect repetition
        if self.revision_repetition_detection_method == "fuzzy":
            repetition_matches = await self._revision_evaluate_fuzzy_similarity(
                text, character
            )
        elif self.revision_repetition_detection_method == "semantic_similarity":
            repetition_matches = await self._revision_evaluate_semantic_similarity(
                text, character
            )

        for match in repetition_matches:
            repetition.append(
                {
                    "text_a": match.original,
                    "text_b": match.matched,
                    "similarity": match.similarity,
                }
            )
            repetition_log.append(
                f"Repetition: `{match.original}` -> `{match.matched}` (similarity: {match.similarity})"
            )

        # Step 2 - Detect bad prose
        if detect_bad_prose:
            bad_prose = await self.revision_detect_bad_prose(text)
            for identified in bad_prose:
                bad_prose_log.append(
                    f"Bad prose: `{identified['phrase']}` (reason: {identified['reason']}, matched: {identified['matched']}, instructions: {identified['instructions']})"
                )

        return Issues(
            repetition=repetition,
            repetition_matches=repetition_matches,
            bad_prose=bad_prose,
            repetition_log=repetition_log,
            bad_prose_log=bad_prose_log,
        )

    async def revision_dedupe(
        self,
        info: RevisionInformation,
    ) -> str:
        """
        Revise the text by deduping
        """

        info.revision_method = "dedupe"

        original_text = info.text
        character = info.character

        text, had_character_prefix = _strip_character_prefix(original_text, character)

        original_length = len(text)

        issues = await self.revision_collect_issues(
            text, character, detect_bad_prose=False
        )

        if not issues.repetition_matches:
            return original_text

        emission = RevisionEmission(agent=self, info=info, issues=issues)

        await async_signals.get("agent.editor.revision-revise.before").send(emission)

        emission.response = dedupe_sentences_from_matches(
            text, issues.repetition_matches
        )

        await async_signals.get("agent.editor.revision-revise.after").send(emission)

        text = emission.response

        # remove empty quotes and asterisks
        text = text.replace('""', "").replace("**", "")

        deduped_length = len(text)

        # calculate reduction percentage
        reduction = round((original_length - deduped_length) / original_length * 100, 2)

        if reduction > 90:
            log.warning(
                "revision_dedupe: reduction is too high, reverting to original text",
                original_text=original_text,
                reduction=reduction,
            )
            emit(
                "agent_message",
                message="No text remained after dedupe, reverting to original text - similarity threshold is likely too low.",
                data={
                    "uuid": str(uuid.uuid4()),
                    "agent": "editor",
                    "header": "Aborted dedupe",
                    "color": "red",
                },
                meta={
                    "action": "revision_dedupe",
                    "threshold": self.revision_repetition_threshold,
                    "range": self.revision_repetition_range,
                },
                websocket_passthrough=True,
            )
            return original_text

        text = _reattach_character_prefix(text, character, had_character_prefix)

        for dedupe in issues.repetition:
            text_a = dedupe["text_a"]
            text_b = dedupe["text_b"]

            message = f"{text_a} -> {text_b}"
            emit(
                "agent_message",
                message=message,
                data={
                    "uuid": str(uuid.uuid4()),
                    "agent": "editor",
                    "header": "Removed repetition",
                    "color": "highlight4",
                },
                meta={
                    "action": "revision_dedupe",
                    "similarity": dedupe["similarity"],
                    "threshold": self.revision_repetition_threshold,
                    "range": self.revision_repetition_range,
                },
                websocket_passthrough=True,
            )

        return text

    async def revision_rewrite(
        self,
        info: RevisionInformation,
    ) -> str:
        """
        Revise the text by rewriting.

        Runs a single analysis+rewrite prompt and extracts the rewritten text
        from a ``<REVISION>...</REVISION>`` anchor. If the anchor is missing,
        or the rewrite balloons past ``REWRITE_MAX_LENGTH_RATIO``, the original
        text is returned unchanged.
        """

        original_text = info.text
        character = info.character
        loading_status = info.loading_status

        text, had_character_prefix = _strip_character_prefix(original_text, character)

        issues = await self.revision_collect_issues(text, character)

        num_issues = len(issues.log)

        if not num_issues:
            return original_text

        if num_issues < self.revision_min_issues:
            log.debug(
                "revision_rewrite: not enough issues found, returning original text",
                issues=num_issues,
                min_issues=self.revision_min_issues,
            )
            # Not enough issues found, return original text
            await self.emit_message(
                "Aborted rewrite",
                message=[
                    {"subtitle": "Issues", "content": issues.log},
                    {
                        "subtitle": "Message",
                        "content": f"Not enough issues found, returning original text - minimum issues is {self.revision_min_issues}. Found {num_issues} issues.",
                    },
                ],
                color="orange",
            )
            return original_text

        token_count = count_tokens(text)
        response_length = token_count + REVISION_RESPONSE_HEADROOM

        log.debug("revision_rewrite: token_count", token_count=token_count)

        if loading_status:
            loading_status("Editor - Issues identified, rewriting text...")

        emission = RevisionEmission(
            agent=self,
            info=info,
            issues=issues,
        )

        emission.template_vars = {
            "text": text,
            "character": character,
            "scene": self.scene,
            "response_length": response_length,
            "max_tokens": self.client.max_token_length,
            "repetition": issues.repetition,
            "repetition_handling": self.revision_repetition_handling,
            "bad_prose": issues.bad_prose,
            "dynamic_instructions": emission.dynamic_instructions,
            "context_type": info.context_type,
            "context_name": info.context_name,
        }

        await async_signals.get("agent.editor.revision-revise.before").send(emission)
        await async_signals.get("agent.editor.revision-analysis.before").send(emission)

        _, extracted = await Prompt.request(
            "editor.revision-rewrite",
            self.client,
            f"edit_{response_length}",
            vars=emission.template_vars,
            dedupe_enabled=False,
            response_spec=REWRITE_SPEC,
        )

        # The analysis-after signal is fired as a notification hook for
        # backward compatibility. Analysis and rewrite now share a single
        # prompt, so there is no separable analysis text to expose on the
        # emission — listeners that previously mutated `emission.response`
        # here will have no effect. See docs/user-guide/node-editor/reference/events.md.
        await async_signals.get("agent.editor.revision-analysis.after").send(emission)

        revision = extracted["revision"]
        if not revision:
            log.debug(
                "revision_rewrite: no <REVISION> content in response, keeping original"
            )
            return original_text

        # Guard: if the rewrite is substantially longer than the original,
        # the model likely expanded beyond the "do not make it longer"
        # instruction — discard it.
        if _revision_exceeds_max_length(
            "revision_rewrite",
            text,
            revision,
            REWRITE_MAX_LENGTH_RATIO,
        ):
            return original_text

        emission.response = revision
        await async_signals.get("agent.editor.revision-revise.after").send(emission)
        revision = emission.response

        await self._emit_revision_diff(
            "Rewrite",
            text,
            revision,
            issues,
            meta={
                "action": "revision_rewrite",
                "repetition_threshold": self.revision_repetition_threshold,
                "repetition_range": self.revision_repetition_range,
                "repetition_min_length": self.revision_repetition_min_length,
                "split_on_comma": self.revision_split_on_comma,
                "min_issues": self.revision_min_issues,
                "detect_bad_prose": self.revision_detect_bad_prose_enabled,
                "detect_bad_prose_threshold": self.revision_detect_bad_prose_threshold,
            },
        )

        return _reattach_character_prefix(revision, character, had_character_prefix)

    async def revision_unslop(
        self,
        info: RevisionInformation,
        response_length: int = REVISION_RESPONSE_HEADROOM,
    ) -> str:
        """
        Unslop the text
        """

        original_text = info.text
        character = info.character

        text, had_character_prefix = _strip_character_prefix(original_text, character)

        issues = await self.revision_collect_issues(text, character)

        summarizer = get_agent("summarizer")
        scene_analysis = await summarizer.get_cached_analysis(
            "conversation" if character else "narration"
        )

        template = "editor.unslop"
        if info.context_type:
            template = "editor.unslop-contextual-generation"
        elif info.summarization_history is not None:
            template = "editor.unslop-summarization"
        elif character is None:
            template = "editor.unslop-narration"

        log.debug("revision_unslop: issues", issues=issues, template=template)

        emission = RevisionEmission(
            agent=self,
            info=info,
            issues=issues,
        )

        response_length = count_tokens(text) + response_length

        emission.template_vars = {
            "text": text,
            "scene_analysis": scene_analysis,
            "character": character,
            "scene": self.scene,
            "response_length": response_length,
            "max_tokens": self.client.max_token_length,
            "repetition": issues.repetition,
            "repetition_handling": self.revision_repetition_handling,
            "bad_prose": issues.bad_prose,
            "dynamic_instructions": emission.dynamic_instructions,
            "context_type": info.context_type,
            "context_name": info.context_name,
            "summarization_history": info.summarization_history,
        }

        await async_signals.get("agent.editor.revision-revise.before").send(emission)

        response, extracted = await Prompt.request(
            template,
            self.client,
            f"edit_{response_length}",
            vars=emission.template_vars,
            dedupe_enabled=False,
            response_spec=FIX_SPEC,
        )

        fix = extracted["fix"]
        if not fix:
            log.debug(
                "revision_unslop: no <FIX> content in response", response=response
            )
            return original_text

        # Guard: if the fix is substantially longer than the original,
        # the model likely hallucinated extra content — discard it
        if _revision_exceeds_max_length(
            "revision_unslop",
            text,
            fix,
            UNSLOP_MAX_LENGTH_RATIO,
        ):
            return original_text

        emission.response = fix
        await async_signals.get("agent.editor.revision-revise.after").send(emission)
        fix = emission.response

        await self._emit_revision_diff(
            "Unslop",
            text,
            fix,
            issues,
            meta={"action": "revision_unslop"},
        )

        return _reattach_character_prefix(fix, character, had_character_prefix)

    def inject_prompt_paramters(
        self, prompt_param: dict, kind: str, agent_function_name: str
    ):
        super().inject_prompt_paramters(prompt_param, kind, agent_function_name)

        if agent_function_name == "revision_revise":
            if prompt_param.get("extra_stopping_strings") is None:
                prompt_param["extra_stopping_strings"] = []
