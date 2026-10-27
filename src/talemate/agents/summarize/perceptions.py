import asyncio
import json
import re
from collections.abc import Collection
from copy import deepcopy
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, StrictInt, StrictStr, ValidationError
from weakref import WeakKeyDictionary

import structlog

import talemate.emit.async_signals as async_signals
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    AgentEmission,
    set_processing,
)
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.emit import emit
from talemate.client.presets import make_kind
from talemate.util import count_tokens
from talemate.knowledge.backlog import record_cancel
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.formatting import (
    passage_metadata,
    perception_body,
    perception_speaker,
)
from talemate.knowledge.readiness import emit_perception_status, perception_readiness
from talemate.knowledge.revision_scope import hold_for_step, in_revision_phase
from talemate.knowledge.presence import relevant_audiences
from talemate.knowledge.timeline import record_time
from talemate.knowledge.reinforcements import prepare_reinforcement_source
from talemate.knowledge.perspective_models import (
    PerspectiveOutput,
    PerspectiveStatus,
    PerspectiveView,
    PassageProvenance,
    SourceReference,
    SourcePerspectives,
    content_digest,
)
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    Staleness,
    message_sources,
    can_cite_view,
    select_character_view,
    set_source_perspectives,
    source_reference,
    view_staleness,
)
from talemate.prompts import Prompt
from talemate.agents.summarize.response_specs import PERCEPTIONS_SPEC
from talemate.scene_message import SceneMessage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger(__name__)


async_signals.register(
    "agent.summarization.perceptions.after",
    "agent.summarization.perceptions.failed",
)


class PerceptionView(BaseModel):
    character: str
    status: PerspectiveStatus
    text: str | None = None


class PerceptionsAfterEmission(AgentEmission):
    """The stored views of one passage, sent once the analysis pass has ended."""

    message_id: int
    views: list[PerceptionView]
    analyzed: list[str]
    verbatim: list[str]


class PerceptionsFailedEmission(AgentEmission):
    """A passage whose analysis failed, sent once the analysis pass has ended."""

    message_id: int
    characters: list[str]
    error: str


CONTEXT_PASSAGES = 12
SENTENCE_CLOSERS = "\"'”’)]}»*_"
SENTENCE_END = re.compile(rf"[.!?…]+[{re.escape(SENTENCE_CLOSERS)}]*(?=\s|$)|\n+")


class PerceptionAnalysis(PerspectiveOutput):
    knowledge_ids: tuple[StrictStr, ...]
    passage_ids: tuple[StrictInt, ...]


class PerceptionValidationError(ValueError):
    def __init__(self, reason: str, views: tuple[PerceptionAnalysis, ...] = ()):
        super().__init__(reason)
        self.views = views


class PerceptionInputsChanged(Exception):
    def __init__(self, *, invalidate: bool = True):
        self.invalidate = invalidate
        super().__init__("Perception inputs changed")


def warn_perception_regeneration(message: SceneMessage) -> None:
    warning = (
        "Perception inputs changed during analysis; regenerating perception analysis."
    )
    log.warning(warning, source_id=message.id)
    emit("status", status="warning", message=warning, data={"message_id": message.id})


def passage_sentences(passage: str) -> list[tuple[int, int]]:
    bounds, start = [], 0
    for match in SENTENCE_END.finditer(passage):
        following = passage[match.end() :].lstrip(" \t")
        if match.group().strip("\n") and following[:1].islower():
            # A lowercase continuation never starts a new sentence, which keeps a
            # speech tag with its quote: '"Run!" she hissed.'
            continue
        bounds.append((start, match.end()))
        start = match.end()
    bounds.append((start, len(passage)))
    sentences = []
    for begin, end in bounds:
        piece = passage[begin:end]
        if piece.strip():
            sentences.append(
                (
                    begin + len(piece) - len(piece.lstrip()),
                    begin + len(piece.rstrip()),
                )
            )
    return sentences


def span_starts(passage: str, span: str) -> list[int]:
    starts, index = [], passage.find(span)
    while index >= 0:
        starts.append(index)
        index = passage.find(span, index + 1)
    return starts


class PerceptionExclusion(BaseModel):
    span: StrictStr
    reason: StrictStr
    forbidden: list[StrictStr]
    trace: StrictStr | None = None


class PerceptionRewriteRegion(BaseModel):
    start: int
    end: int
    partial: bool


def perception_exclusions(item: dict) -> tuple[PerceptionExclusion, ...]:
    values = item.get("exclusions")
    if not isinstance(values, list):
        raise ValueError("exclusions must be an explicit array")
    try:
        exclusions = tuple(
            PerceptionExclusion.model_validate(value) for value in values
        )
    except ValidationError as exc:
        raise ValueError(
            "invalid exclusion: "
            + "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                for error in exc.errors(include_input=False)
            )
        ) from exc
    for exclusion in exclusions:
        if not exclusion.span.strip():
            raise ValueError("each exclusion needs a nonempty span")
        if any(not token.strip() for token in exclusion.forbidden):
            raise ValueError("forbidden words and phrases must be nonempty")
        if exclusion.trace is not None and not exclusion.trace.strip():
            raise ValueError(
                "a trace must be nonempty; omit it when there is no observable effect"
            )
    return exclusions


def rewrite_regions(
    passage: str, spans: tuple[tuple[int, int], ...]
) -> tuple[PerceptionRewriteRegion, ...]:
    sentences = passage_sentences(passage)
    touched = {
        index
        for index, (start, end) in enumerate(sentences)
        if any(span_start < end and start < span_end for span_start, span_end in spans)
    }
    partial = {
        index
        for index in touched
        if any(
            not passage[position].isspace()
            and not any(start <= position < end for start, end in spans)
            for position in range(*sentences[index])
        )
    }
    editable = sorted(
        {
            neighbor
            for index in touched
            for neighbor in (index - 1, index, index + 1)
            if 0 <= neighbor < len(sentences)
        }
    )
    regions = []
    for index in editable:
        start = sentences[index - 1][1] if index else 0
        end = sentences[index + 1][0] if index + 1 < len(sentences) else len(passage)
        if regions and start <= regions[-1].end:
            regions[-1].end = end
            regions[-1].partial |= index in partial
        else:
            regions.append(
                PerceptionRewriteRegion(start=start, end=end, partial=index in partial)
            )
    return tuple(regions)


def forbidden_in_text(text: str, token: str) -> bool:
    phrase = r"\s+".join(re.escape(part) for part in token.split())
    return re.search(rf"(?<!\w){phrase}(?!\w)", text, re.IGNORECASE) is not None


def alignment_excerpt(expected: str, actual: str | None = None) -> str:
    context = 40
    if len(expected) <= 2 * context + 1:
        return expected
    start, end = 0, 2 * context + 1
    if actual is not None:
        difference = next(
            (index for index, (a, b) in enumerate(zip(expected, actual)) if a != b),
            min(len(expected), len(actual)),
        )
        start, end = max(0, difference - context), difference + context + 1
    return (
        ("…" if start else "")
        + expected[start:end]
        + ("…" if end < len(expected) else "")
    )


def exclusion_errors(
    passage: str, exclusions: tuple[PerceptionExclusion, ...], text: str
) -> list[str]:
    errors = []
    spans = []
    for exclusion in exclusions:
        starts = span_starts(passage, exclusion.span)
        if not starts:
            errors.append(f"exclusion span is not in the passage: {exclusion.span!r}")
            continue
        if len(starts) > 1:
            errors.append(
                f"exclusion span occurs {len(starts)} times in the passage; quote "
                f"enough surrounding text to make it unique: {exclusion.span!r}"
            )
            continue
        spans.append((starts[0], starts[0] + len(exclusion.span)))
        if exclusion.span in text:
            errors.append(f"excluded span is still in the text: {exclusion.span!r}")
    if errors:
        return errors
    regions = rewrite_regions(passage, tuple(spans))
    outside_error = (
        "text outside rewrite regions is missing or changed, or text was added; "
        "expected unchanged source fragment"
    )
    if not regions:
        return (
            []
            if text == passage
            else [f"{outside_error}: {alignment_excerpt(passage, text)!r}"]
        )
    prefix = passage[: regions[0].start]
    if not text.startswith(prefix):
        return [f"{outside_error}: {alignment_excerpt(prefix, text)!r}"]
    forbidden = {token for exclusion in exclusions for token in exclusion.forbidden}
    positions = {len(prefix)}
    for index, region in enumerate(regions):
        end = regions[index + 1].start if index + 1 < len(regions) else len(passage)
        anchor = passage[region.end : end]
        ends = span_starts(text, anchor) if anchor else [len(text)]
        following = set()
        failures = set()
        has_kept_text = any(
            not passage[position].isspace()
            and not any(start <= position < end for start, end in spans)
            for position in range(region.start, region.end)
        )
        # Repeated unchanged text can delimit more than one valid alignment.
        for position in positions:
            for found in ends:
                if found < position:
                    continue
                if index + 1 == len(regions) and found + len(anchor) != len(text):
                    continue
                rewritten = text[position:found]
                if region.partial and not rewritten.strip():
                    failures.add(
                        "a partially excluded sentence needs a nonempty rewrite region"
                    )
                    continue
                if has_kept_text and not rewritten.strip():
                    failures.add(
                        "a rewrite region with unexcluded source text must be nonempty"
                    )
                    continue
                leaked = [
                    token
                    for token in sorted(forbidden)
                    if forbidden_in_text(rewritten, token)
                ]
                if leaked:
                    failures.add(f"forbidden content in rewrite region: {leaked!r}")
                    continue
                following.add(found + len(anchor))
        if not following:
            return sorted(failures) or [
                f"{outside_error}: {alignment_excerpt(anchor)!r}"
            ]
        positions = following
    return []


def parse_perceptions(
    data: str | None,
    audiences: tuple[str, ...],
    passage: str,
    block: str | None = None,
) -> tuple[PerceptionAnalysis, ...]:
    """`data` is the extracted JSON; without it, the raw `block` is decoded so
    a cut-off or invalid answer reports its JSON error."""
    if data is None:
        if block is None:
            raise PerceptionValidationError("No <PERCEPTIONS> block found")
        data = block
    try:
        parsed = json.loads(data)
    except (TypeError, ValueError) as exc:
        raise PerceptionValidationError(f"Invalid perception JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("views"), list):
        raise PerceptionValidationError(
            "Expected a perception object with a views array"
        )
    views = {}
    reasons = []
    for index, item in enumerate(parsed["views"]):
        audience = item.get("audience") if isinstance(item, dict) else None
        if (
            not isinstance(audience, list)
            or len(audience) != 1
            or not isinstance(audience[0], str)
        ):
            reasons.append(f"View {index} must name one audience")
            log.warning("dropping invalid perception audience", view_index=index)
            continue
        name = audience[0]
        if name not in audiences:
            log.warning("dropping unrequested perception audience", audience=name)
            continue
        if name in views:
            log.warning("dropping duplicate perception view", audience=name)
            continue
        try:
            if item.get("status") not in ("ready", "omitted"):
                raise ValueError("Expected ready or omitted status")
            view = PerceptionAnalysis(
                audience=(name,),
                status=item["status"],
                text=item.get("text"),
                knowledge_ids=perception_citations(item, "knowledge_ids", str, name),
                passage_ids=perception_citations(item, "passage_ids", int, name),
            )
            if view.status == "ready":
                errors = exclusion_errors(
                    passage, perception_exclusions(item), view.text
                )
                if errors:
                    raise ValueError(
                        "text does not match its exclusions: " + "; ".join(errors)
                    )
        except (ValueError, ValidationError) as exc:
            reason = (
                "; ".join(error["msg"] for error in exc.errors(include_input=False))
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            reasons.append(f"{name}: {reason}")
            log.warning("dropping invalid perception view", audience=name, error=reason)
            continue
        views[name] = view
    missing = [name for name in audiences if name not in views]
    outputs = tuple(views[name] for name in audiences if name in views)
    if missing:
        reason = f"Missing valid perceptions for: {', '.join(missing)}"
        if reasons:
            reason += ". " + "; ".join(reasons)
        raise PerceptionValidationError(reason, outputs)
    return outputs


def perception_citations(item: dict, field: str, typ: type, audience: str) -> tuple:
    values = item.get(field)
    if not isinstance(values, list):
        log.warning(
            "invalid perception citations",
            audience=audience,
            field=field,
            citation=values,
        )
        raise ValueError(f"{field} must be an explicit array")
    valid = []
    invalid = False
    for value in values:
        if type(value) is typ:
            valid.append(value)
        else:
            log.warning(
                "invalid perception citation",
                audience=audience,
                field=field,
                citation=value,
            )
            invalid = True
    if invalid:
        raise ValueError(f"{field} contains an unreadable citation")
    return tuple(valid)


def eligible_passage(message: SceneMessage) -> bool:
    return message.supports_perceptions


def filter_analysis_audiences(
    scene: "Scene", names: Collection[str], *, speaker: str | None = None
) -> tuple[str, ...]:
    analyze_player = get_agent("summarizer").resolve_config(
        "perceptions", "analyze_player"
    )
    return tuple(
        character.name
        for character in scene.character_data.values()
        if character.name in names
        and character.name != speaker
        and (analyze_player or not character.is_player)
    )


def analysis_audiences(scene: "Scene", message: SceneMessage) -> tuple[str, ...]:
    if not perception_body(message).strip():
        return ()
    return filter_analysis_audiences(
        scene,
        relevant_audiences(scene, message),
        speaker=perception_speaker(message),
    )


def perception_passages(scene: "Scene") -> list[SceneMessage]:
    return sorted(message_sources(scene), key=lambda entry: entry.id)


def perception_prefix(
    scene: "Scene", before_message_id: int | None = None
) -> list[SceneMessage]:
    passages = perception_passages(scene)
    if before_message_id is None:
        return passages
    for index, passage in enumerate(passages):
        if passage.id == before_message_id:
            return passages[:index]
    raise GenerationCancelled(f"History boundary {before_message_id} was removed")


def perception_staleness(
    scene, message, *, read=None, inherited=True
) -> Staleness | None:
    """
    The first check that keeps the passage's stored results from being current.
    Without `inherited`, only the passage's own analysis counts, not the
    out-of-sync knowledge it was built on.
    """
    audiences = relevant_audiences(scene, message)
    if not audiences:
        return None
    if message.knowledge is None:
        return Staleness(check="no_record")
    if message.knowledge.content_digest != content_digest(message.perception_text):
        return Staleness(check="content_digest")
    read = read or PerspectiveReadContext(scene)
    reference = source_reference(scene, "message", message.id, read=read)
    if reference is None:
        return Staleness(check="no_record")
    for name in audiences:
        stale = view_staleness(scene, reference, name, read=read, inherited=inherited)
        if stale is not None:
            return stale
    return None


def perception_results_current(scene, message, *, read=None, inherited=True) -> bool:
    """Verify exact selected-source results for every currently required audience."""
    return perception_staleness(scene, message, read=read, inherited=inherited) is None


def never_analyzed(message: SceneMessage) -> bool:
    """
    No view of the passage has been built or has failed yet: a new line, which
    the turn's knowledge step analyzes. Anything else waits for a repair.
    Registration gives a new line a view per audience, so one with no views
    lost them (its only audience was removed) and is not new.
    """
    return (
        message.knowledge is not None
        and bool(message.knowledge.views)
        and all(view.status == "pending" for view in message.knowledge.views)
    )


def _stored_view_current(scene, reference, view: PerspectiveView, *, read) -> bool:
    """Check the stored view before preserving it or counting its dependents."""
    if reference is None:
        return False
    # An absent audience's implicit omission is only a reading rule. Pin the
    # stored view so stale evidence cannot be copied into the next write.
    reference = reference.model_copy(
        update={"view_id": view.id, "view_revision": view.revision}
    )
    return all(
        view_staleness(scene, reference, name, read=read) is None
        for name in view.audience
    )


def passage_provenance(message: SceneMessage) -> PassageProvenance:
    return PassageProvenance(
        message_id=message.id,
        content_digest=content_digest(message.perception_text),
        revision=message.knowledge.revision if message.knowledge else None,
    )


def perception_intention(scene: "Scene") -> tuple[str | None, str | None, str | None]:
    intention = scene.intent_state
    return (
        intention.intent,
        intention.phase.intent if intention.phase else None,
        intention.current_scene_type.description if intention.phase else None,
    )


def tracked_character_states(scene: "Scene", name: str) -> dict[str, str]:
    states = {}
    for reinforcement in scene.world_state.reinforcements_for_character(name).values():
        if not reinforcement.answer:
            continue
        timestamp = reinforcement.updated_ts
        if timestamp is None:
            source = reinforcement.source_for(scene)
            timestamp = (
                source.knowledge.acquired.ts if source and source.knowledge else None
            )
        age = record_time(scene, timestamp)
        states[reinforcement.question] = f"({age}) {reinforcement.answer}"
    return states


def perception_context(
    scene: "Scene", message: SceneMessage, *, audiences: tuple[str, ...] | None = None
) -> dict:
    read = PerspectiveReadContext(scene)
    previous = [
        entry
        for entry in perception_passages(scene)
        if entry.id < message.id and eligible_passage(entry)
    ][-CONTEXT_PASSAGES:]
    cast = []
    for name in relevant_audiences(scene, message) if audiences is None else audiences:
        character = scene.character_data[name]
        known = []
        for entry in previous:
            reference = source_reference(scene, "message", entry.id, read=read)
            if reference is None:
                continue
            view = select_character_view(scene, reference, character.name, read=read)
            if view.status == "ready" and can_cite_view(
                scene, view.source, character.name, read=read
            ):
                known.append(
                    {
                        "source": view.source.model_dump(),
                        "text": view.text,
                        **passage_metadata(entry),
                    }
                )
        if scene.knowledge and message.knowledge:
            for disclosure in scene.knowledge.disclosures:
                if character.name in disclosure.audience and (
                    message.id > disclosure.message_id_boundary
                    and message.knowledge.acquired.order > disclosure.acquired.order
                ):
                    known.append(
                        {
                            "source": source_reference(
                                scene, "disclosure", disclosure.id, read=read
                            ).model_dump(),
                            "text": disclosure.text,
                        }
                    )
        for index, item in enumerate(known):
            item["id"] = f"K{len(cast)}-{index}"
        cast.append(
            {
                "name": character.name,
                "authored_description": character.description,
                "authored_attributes": character.base_attributes,
                "authored_details": {
                    key: value
                    for key, value in character.details.items()
                    if key not in character.reinforcement_entries
                },
                "tracked_states": tracked_character_states(scene, character.name),
                "established_knowledge": known,
            }
        )
    return {
        "cast": cast,
        "prior_physical_context": [
            {
                "id": entry.id,
                "text": perception_body(entry),
                **passage_metadata(entry),
                "present": entry.present,
                "provenance": passage_provenance(entry).model_dump(),
            }
            for entry in previous
        ],
        "passage": {
            "provenance": passage_provenance(message).model_dump(),
            "text": perception_body(message),
            **passage_metadata(message),
            "present": message.present,
        },
    }


def resolve_perception_inputs(
    outputs: tuple[PerceptionAnalysis, ...], context: dict
) -> list[PerspectiveOutput]:
    physical = {
        item["id"]: item["provenance"] for item in context["prior_physical_context"]
    }
    knowledge = {
        character["name"]: {
            item["id"]: item["source"] for item in character["established_knowledge"]
        }
        for character in context["cast"]
    }
    resolved = []
    current = context["passage"]["provenance"]
    for output in outputs:
        kept = {}
        offered = knowledge[output.audience[0]]
        for field, ids, allowed in (
            ("knowledge_ids", output.knowledge_ids, offered),
            ("passage_ids", output.passage_ids, physical),
        ):
            kept[field] = []
            for identity in dict.fromkeys(ids):
                if field == "passage_ids" and identity == current["message_id"]:
                    continue
                if identity not in allowed:
                    log.warning(
                        "dropping unoffered perception citation",
                        source_id=current["message_id"],
                        audience=output.audience[0],
                        field=field,
                        citation=identity,
                    )
                else:
                    kept[field].append(identity)
        resolved.append(
            PerspectiveOutput(
                audience=output.audience,
                status=output.status,
                text=output.text,
                sources=tuple(
                    SourceReference.model_validate(offered[key])
                    for key in kept["knowledge_ids"]
                ),
                passage_provenance=(
                    PassageProvenance.model_validate(current),
                    *(
                        PassageProvenance.model_validate(physical[key])
                        for key in kept["passage_ids"]
                    ),
                ),
            )
        )
    return resolved


class PerceptionMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["perceptions"] = AgentAction(
            enabled=True,
            container=True,
            label="Character Perspectives",
            description="Analyze passages from each character's perspective and repair incomplete analysis.",
            icon="mdi-eye-outline",
            config={
                "analyze_player": AgentActionConfig(
                    type="bool",
                    label="Analyze player perspective",
                    description="Enable a perspective-limited view of the story for the player character. When off, the player character receives the full passage. Adds perception analysis for the player character; their own messages always stay verbatim.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="Includes the player in perception analysis. Adds a Summarizer request when no other audience needs analysis; the player's own messages stay verbatim.",
                        ),
                    },
                ),
                "automatic_repair": AgentActionConfig(
                    type="bool",
                    label="Automatically repair analysis",
                    description="Try once to repair missing or invalid character views before showing the generation error dialog.",
                    value=True,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="One more Summarizer request when a character view is missing or invalid.",
                        ),
                    },
                ),
                "rewrite_hidden_traces": AgentActionConfig(
                    type="bool",
                    label="Rewrite hidden acts as observable traces",
                    description="Keep an ambiguous sensory effect of a hidden act when the character can perceive it, without revealing the hidden object or act. Applies to new analysis; existing valid views are kept.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="Uses the same Summarizer request, but can increase reasoning, output tokens and response time. Invalid views can still trigger automatic repair.",
                        ),
                    },
                ),
            },
        )

    def init_perceptions(self) -> None:
        self._perception_deferred = WeakKeyDictionary()
        self._perception_running = WeakKeyDictionary()

    def _perception_status(
        self,
        scene: "Scene",
        message: SceneMessage,
        status: Literal["pending", "failed"],
        *,
        invalidate: bool = False,
        add_missing: bool = True,
    ) -> None:
        """
        A failed view stays failed: only an analysis result or an edit of the
        passage replaces it. `add_missing` gives each relevant audience
        without a view one with `status`.
        """
        previous = message.knowledge
        read = PerspectiveReadContext(scene)
        reference = source_reference(scene, "message", message.id, read=read)
        outputs = []
        covered = set()
        for view in previous.views if previous else ():
            covered.update(view.audience)
            values = view.model_dump(exclude={"revision"})
            if invalidate or not _stored_view_current(
                scene, reference, view, read=read
            ):
                if view.status in ("ready", "omitted"):
                    # the last text stays readable until an analysis replaces it
                    values["stale"] = True
                else:
                    values.update(
                        status="failed" if view.status == "failed" else status,
                        text=None,
                        sources=(),
                        passage_provenance=(),
                    )
            outputs.append(PerspectiveOutput(**values))
        if add_missing:
            outputs.extend(
                PerspectiveOutput(audience=(name,), status=status)
                for name in relevant_audiences(scene, message)
                if name not in covered
            )
        set_source_perspectives(
            scene,
            "message",
            message.id,
            outputs,
        )

    def _perception_needed(
        self,
        scene: "Scene",
        message: SceneMessage,
        *,
        read: PerspectiveReadContext | None = None,
        inherited: bool = True,
    ) -> bool:
        if not eligible_passage(message) or message.knowledge is None:
            return False
        return not perception_results_current(
            scene, message, read=read, inherited=inherited
        )

    def register_perception_sources(
        self, scene: "Scene", messages: list[SceneMessage]
    ) -> None:
        for message in messages:
            if eligible_passage(message) and message.knowledge is None:
                if not relevant_audiences(scene, message):
                    self._perception_deferred.setdefault(scene, {})[message.id] = (
                        message
                    )
                    continue
                self._perception_status(scene, message, "pending")

    def _prepare_perception_sources(
        self, scene: "Scene", before_message_id: int | None
    ) -> None:
        self.register_perception_sources(
            scene, scene.world_state.prepare_reinforcement_perspectives()
        )
        prefix_ids = {
            message.id for message in perception_prefix(scene, before_message_id)
        }
        deferred = self._perception_deferred.get(scene, {})
        for identity, message in list(deferred.items()):
            if not any(entry is message for entry in message_sources(scene)):
                del deferred[identity]
            elif identity in prefix_ids and relevant_audiences(scene, message):
                if message.knowledge is None:
                    self._perception_status(scene, message, "pending")
                del deferred[identity]

    def _queue_perception_event(self, scene: "Scene", name: str, emission) -> None:
        if not hold_for_step(name, emission):
            async_signals.send_soon(name, emission)

    async def ensure_perceptions(
        self,
        scene: "Scene",
        *,
        before_message_id: int | None = None,
        still_current=None,
        repair: bool = False,
        progress=None,
        targets: Collection[int] = (),
        in_repair: bool = False,
        attempted: set[int] | None = None,
    ) -> None:
        """
        Analyze the passages that were never analyzed, or only `targets`; with
        `repair`, every passage whose views are not current. A passage is
        analyzed once per call, unless the user retries it; `attempted` is the
        step's own record, so a passage done or ignored earlier in the step is
        not analyzed again, except as a target.
        """
        if not character_knowledge_enabled(scene):
            return
        if self.scene is not scene:
            raise GenerationCancelled("Perception scene changed")
        self._prepare_perception_sources(scene, before_message_id)
        cancel_sequence = scene.cancel_sequence
        # failed passages the user chose to retry in this step
        retrying = set()
        # a passage built on out-of-sync knowledge stays out of sync after its
        # analysis, by inheritance
        done = set()
        attempted = done if attempted is None else attempted
        while True:
            if scene.cancel_requested or scene.cancel_sequence != cancel_sequence:
                raise GenerationCancelled("Generation cancelled", by_user=True)
            if still_current is not None and not still_current():
                raise GenerationCancelled(
                    "The selected version changed during analysis"
                )
            if self.scene is not scene or not character_knowledge_enabled(scene):
                raise GenerationCancelled("Perception scene changed")
            read = PerspectiveReadContext(scene)
            refreshing = in_revision_phase(scene)
            due = (
                entry
                for entry in perception_prefix(scene, before_message_id)
                # a pending revision is analyzed by its own refresh
                if (
                    refreshing
                    or entry.revision_state is None
                    or entry.revision_matches_baseline
                )
                and entry.id not in done
                and (entry.id in targets or entry.id not in attempted)
                # a revision's own analysis; the lines after it wait, so they
                # are analyzed once, after what they build on
                and (not targets or entry.id in targets)
                and (
                    self._perception_needed(scene, entry, read=read)
                    if repair
                    else (
                        never_analyzed(entry)
                        or entry.id in retrying
                        or entry.id in targets
                    )
                    # done once its own analysis is current
                    and self._perception_needed(
                        scene, entry, read=read, inherited=False
                    )
                )
            )
            message = next(due, None)
            if message is None:
                return
            if progress is not None:
                progress.max_steps = progress.current_step + 1 + sum(1 for _ in due)
                progress("Repairing character perspectives")
            stale = perception_staleness(scene, message, read=read)
            log.info(
                "perception analysis needed",
                message_id=message.id,
                check=stale.check if stale else None,
                character=stale.character if stale else None,
                cited=stale.cited if stale else None,
            )
            reinforcement = next(
                (
                    item
                    for item in scene.world_state.reinforce
                    if item.perspective_source is message
                ),
                None,
            )
            try:
                running = self._perception_running.setdefault(scene, set())
                running.add(message.id)
                emit_perception_status(scene, message, "running")
                done.add(message.id)
                attempted.add(message.id)
                if await self.analyze_perceptions(
                    scene, message, in_repair=repair or in_repair
                ):
                    retrying.add(message.id)
                    done.discard(message.id)
                    attempted.discard(message.id)
            except PerceptionInputsChanged as exc:
                if scene.cancel_requested or scene.cancel_sequence != cancel_sequence:
                    raise GenerationCancelled("Generation cancelled", by_user=True)
                if still_current is not None and not still_current():
                    raise GenerationCancelled(
                        "The selected version changed during analysis"
                    )
                done.discard(message.id)
                attempted.discard(message.id)
                self._perception_status(
                    scene, message, "pending", invalidate=exc.invalidate
                )
                if exc.invalidate:
                    warn_perception_regeneration(message)
                continue
            except (GenerationCancelled, asyncio.CancelledError) as exc:
                if getattr(exc, "by_user", False):
                    record_cancel(scene)
                running.discard(message.id)
                readiness = perception_readiness(scene, message)
                if readiness != "running":
                    emit_perception_status(scene, message, readiness)
                raise
            else:
                running.discard(message.id)
                readiness = perception_readiness(scene, message)
                if readiness != "running":
                    emit_perception_status(scene, message, readiness)
            finally:
                running.discard(message.id)
            if (
                reinforcement is not None
                and reinforcement in scene.world_state.reinforce
            ):
                current = prepare_reinforcement_source(scene, reinforcement)
                if current is not None and current is not message:
                    self.register_perception_sources(scene, [current])

    def _perception_source_current(
        self,
        scene: "Scene",
        message: SceneMessage,
        knowledge: SourcePerspectives,
    ) -> bool:
        return (
            character_knowledge_enabled(scene)
            and self.scene is scene
            and any(entry is message for entry in message_sources(scene))
            and message.knowledge is knowledge
            and knowledge.content_digest == content_digest(message.perception_text)
            and all(
                reinforcement.perspective_source is not message
                or (
                    reinforcement.answer == message.message
                    and reinforcement.question == message.question
                    and reinforcement.character == message.character_name
                )
                for reinforcement in scene.world_state.reinforce
            )
        )

    def _perception_current(
        self,
        scene: "Scene",
        message: SceneMessage,
        knowledge: SourcePerspectives,
        context: dict,
        intention: tuple[str | None, str | None, str | None],
    ) -> bool:
        return (
            self._perception_source_current(scene, message, knowledge)
            and perception_context(
                scene, message, audiences=analysis_audiences(scene, message)
            )
            == context
            and perception_intention(scene) == intention
        )

    def _perception_retry_error(self, scene, message, context, intention):
        # An audience-only change leaves the already published views current.
        same_inputs = (
            perception_intention(scene) == intention
            and all(entry["name"] in scene.character_data for entry in context["cast"])
            and perception_context(
                scene,
                message,
                audiences=tuple(entry["name"] for entry in context["cast"]),
            )
            == context
        )
        return PerceptionInputsChanged(invalidate=not same_inputs)

    async def _perception_attempt(
        self,
        scene,
        message,
        knowledge,
        context,
        intention,
        requested,
        answer_budget,
        feedback,
    ):
        rewrite_hidden_traces = self.resolve_config(
            "perceptions", "rewrite_hidden_traces"
        )
        request_context = {
            **context,
            "cast": [entry for entry in context["cast"] if entry["name"] in requested],
        }
        _, extracted = await Prompt.request(
            "summarizer.perceptions",
            self.client,
            make_kind("analyze", answer_budget),
            vars={
                "scene": scene,
                "context": request_context,
                "validation_error": feedback,
                "rewrite_hidden_traces": rewrite_hidden_traces,
            },
            response_spec=PERCEPTIONS_SPEC,
        )
        if not self._perception_current(scene, message, knowledge, context, intention):
            log.info("discarding stale perception response", source_id=message.id)
            if self._perception_source_current(scene, message, knowledge):
                raise self._perception_retry_error(scene, message, context, intention)
            return None
        error = None
        try:
            parsed = parse_perceptions(
                extracted.get("perceptions"),
                requested,
                context["passage"]["text"],
                block=extracted.get("block"),
            )
        except PerceptionValidationError as exc:
            parsed, error = exc.views, exc
        return resolve_perception_inputs(parsed, context), error

    def _mark_perceptions_failed(self, scene, message, knowledge, outputs, preserved):
        preserved_names = {name for view in preserved for name in view.audience}
        if outputs:
            covered = set(outputs) | preserved_names
            remaining = [
                PerspectiveOutput(**view.model_dump(exclude={"revision"}))
                for view in knowledge.views
                if not covered.intersection(view.audience)
            ]
            set_source_perspectives(
                scene,
                "message",
                message.id,
                [*remaining, *outputs.values(), *preserved],
            )
        self._perception_status(scene, message, "failed")

    @set_processing
    async def analyze_perceptions(
        self, scene: "Scene", message: SceneMessage, *, in_repair: bool = False
    ) -> bool:
        """
        Analyze one passage; True when the user asked to retry a failure. In a
        Repair, Ignore leaves the passage out of sync and the Repair goes on.
        """
        if not relevant_audiences(scene, message):
            raise GenerationCancelled(
                "No relevant audience is available for perception analysis"
            )
        # the views stay as they are until the analysis ends, so a Stop leaves
        # nothing to undo: a new line stays new, a failed one stays failed
        self._perception_status(scene, message, "pending", add_missing=False)
        knowledge = message.knowledge
        analyzed = analysis_audiences(scene, message)
        context = deepcopy(perception_context(scene, message, audiences=analyzed))
        intention = perception_intention(scene)
        audiences = relevant_audiences(scene, message)
        answer_budget = max(
            2048, len(analyzed) * (count_tokens(context["passage"]["text"]) + 256)
        )
        outputs = {}
        preserved = [
            PerspectiveOutput(**view.model_dump(exclude={"revision"}))
            for view in knowledge.views
            if (view.status in ("ready", "omitted") and not view.stale)
            or not set(audiences).intersection(view.audience)
        ]
        preserved_names = {name for view in preserved for name in view.audience}
        body = context["passage"]["text"]
        outputs.update(
            {
                name: PerspectiveOutput(
                    audience=(name,),
                    status="ready" if body.strip() else "omitted",
                    text=body if body.strip() else None,
                    passage_provenance=(passage_provenance(message),),
                )
                for name in audiences
                if name not in analyzed and name not in preserved_names
            }
        )

        try:
            repair = self.resolve_config("perceptions", "automatic_repair")
            requested = tuple(name for name in analyzed if name not in preserved_names)
            feedback = ""
            for attempt in range(2 if repair else 1):
                if not requested:
                    break
                attempt_result = await self._perception_attempt(
                    scene,
                    message,
                    knowledge,
                    context,
                    intention,
                    requested,
                    answer_budget,
                    feedback,
                )
                if attempt_result is None:
                    return
                resolved, error = attempt_result
                outputs.update(
                    {
                        output.audience[0]: output
                        for output in resolved
                        if output.audience[0] not in preserved_names
                    }
                )
                requested = tuple(
                    name
                    for name in audiences
                    if name not in outputs and name not in preserved_names
                )
                if not requested:
                    break
                if not repair or attempt:
                    raise error or PerceptionValidationError(
                        f"Missing valid perceptions for: {', '.join(requested)}"
                    )
                feedback = str(error)
                log.warning(
                    "repairing perception analysis",
                    source_id=message.id,
                    audiences=requested,
                    error=feedback,
                )
        except (PerceptionInputsChanged, GenerationCancelled, asyncio.CancelledError):
            raise
        except Exception as exc:
            if not self._perception_current(
                scene, message, knowledge, context, intention
            ):
                if self._perception_source_current(scene, message, knowledge):
                    raise self._perception_retry_error(
                        scene, message, context, intention
                    ) from exc
                return
            self._mark_perceptions_failed(scene, message, knowledge, outputs, preserved)
            log.warning(
                "perception analysis failed", source_id=message.id, error=str(exc)
            )
            self._queue_perception_event(
                scene,
                "agent.summarization.perceptions.failed",
                PerceptionsFailedEmission(
                    agent=self,
                    message_id=message.id,
                    characters=list(analyzed),
                    error=str(exc),
                ),
            )
            action = await self.client._prompt_generation_error(
                f"Perception analysis failed for passage {message.id}. "
                f"Reason: {exc}\n\n"
                + (
                    "Retry to analyze this passage again. Ignore leaves it out of "
                    "sync and goes on with the Repair; Cancel stops the Repair."
                    if in_repair
                    else "Dependent generation is stopped. Retry to analyze this "
                    "passage again; Cancel or Ignore stops generation without using "
                    "reader text."
                )
            )
            if action == "retry":
                return True
            if in_repair and action == "ignore":
                return False
            raise GenerationCancelled(
                "Perception analysis requires a successful retry",
                by_user=True,
                message_id=message.id,
                view_status="failed",
            )
        stored = [*preserved, *outputs.values()]
        set_source_perspectives(scene, "message", message.id, stored)
        # Every required audience completed successfully. Retained pending views
        # for absent audiences do not prevent this version's analysis receipt.
        message.mark_revision_feature("perceptions")
        self._queue_perception_event(
            scene,
            "agent.summarization.perceptions.after",
            PerceptionsAfterEmission(
                agent=self,
                message_id=message.id,
                views=[
                    PerceptionView(character=name, status=view.status, text=view.text)
                    for view in stored
                    for name in view.audience
                ],
                analyzed=list(analyzed),
                verbatim=[
                    name
                    for name in audiences
                    if name not in analyzed and name not in preserved_names
                ],
            ),
        )
