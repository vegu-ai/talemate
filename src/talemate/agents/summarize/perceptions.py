from talemate.knowledge.processing import evidence_writer
import asyncio
import json
import re
import traceback
import uuid
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import StrictInt, StrictStr, ValidationError
from weakref import WeakKeyDictionary

import structlog

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    set_processing,
)
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.emit import emit
from talemate.client.presets import make_kind
from talemate.util import count_tokens
from talemate.prompts.response import CodeBlockExtractorMixin
from talemate.status import background_task
from talemate.knowledge.backlog import (
    cancels_at_start,
    cancelled_since,
    pushed_count,
    record_cancel,
)
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.readiness import emit_perception_status, perception_readiness
from talemate.knowledge.timeline import record_time
from talemate.knowledge.reinforcements import prepare_reinforcement_source
from talemate.knowledge.perspective_models import (
    PerspectiveOutput,
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
    has_stored_views,
    keep_stored_views,
    select_character_view,
    set_source_perspectives,
    source_reference,
    view_staleness,
)
from talemate.prompts import Prompt
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    SceneMessage,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger(__name__)
CONTEXT_PASSAGES = 12
PERCEPTION_BACKLOG_THRESHOLD = 3

PerceptionBacklogDecision = Literal["analyze", "keep", "cancel"]

_perception_backlog_futures: dict[str, asyncio.Future] = {}


def resolve_perception_backlog(
    request_id: str, decision: PerceptionBacklogDecision
) -> None:
    future = _perception_backlog_futures.get(request_id)
    if future and not future.done():
        future.set_result(decision)


class PerceptionAnalysis(PerspectiveOutput):
    knowledge_ids: tuple[StrictStr, ...]
    passage_ids: tuple[StrictInt, ...]


class PerceptionValidationError(ValueError):
    def __init__(self, reason: str, views: tuple[PerceptionAnalysis, ...] = ()):
        super().__init__(reason)
        self.views = views


class PerceptionInputsChanged(Exception):
    pass


def warn_perception_regeneration(message: SceneMessage) -> None:
    warning = (
        "Perception inputs changed during analysis; regenerating perception analysis."
    )
    log.warning(warning, source_id=message.id)
    emit("status", status="warning", message=warning, data={"message_id": message.id})


class PerceptionExtractor(CodeBlockExtractorMixin):
    validate_structured = True

    def _extract_code_block_from_content(self, content: str) -> str | None:
        if not isinstance(content, str) or not content.strip():
            return None
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
        opening = re.search(r"```(?:json)?\s*(?=\{)", content, re.IGNORECASE)
        if opening:
            candidate = content[opening.end() :]
            try:
                _, end = json.JSONDecoder().raw_decode(candidate)
                suffix = candidate[end:].lstrip()
                if not suffix or suffix.startswith("```"):
                    return candidate[:end]
            except json.JSONDecodeError:
                pass
        return super()._extract_code_block_from_content(content)


def parse_perceptions(
    response: str, audiences: tuple[str, ...]
) -> tuple[PerceptionAnalysis, ...]:
    extracted = PerceptionExtractor()._extract_code_block_from_content(response)
    if extracted is None:
        raise PerceptionValidationError("No structured perception response found")
    try:
        parsed = json.loads(extracted)
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


def relevant_audiences(scene: "Scene", message: SceneMessage) -> tuple[str, ...]:
    names = set(scene.active_characters) | set(message.present or ())
    return tuple(
        character.name
        for character in scene.character_data.values()
        if character.name in names
    )


def perception_staleness(scene, message, *, read=None) -> Staleness | None:
    """The first check that keeps the passage's stored results from being current."""
    if message.knowledge is None:
        return Staleness("no_record")
    if message.knowledge.content_digest != content_digest(message.perception_text):
        return Staleness("content_digest")
    read = read or PerspectiveReadContext(scene)
    reference = source_reference(scene, "message", message.id, read=read)
    if reference is None:
        return Staleness("no_record")
    for name in relevant_audiences(scene, message):
        stale = view_staleness(scene, reference, name, read=read)
        if stale is not None:
            return stale
    return None


def perception_results_current(scene, message, *, read=None) -> bool:
    """Verify exact selected-source results for every currently required audience."""
    return perception_staleness(scene, message, read=read) is None


@dataclass(frozen=True)
class PerceptionBacklog:
    """The passages a perception run analyzes, counted without a request."""

    # every required character has a stored ready or omitted view
    keepable: tuple[SceneMessage, ...]
    empty: tuple[SceneMessage, ...]
    at_risk: tuple[SceneMessage, ...]
    # what an analysis of `empty` alone can invalidate, after a Keep
    empty_at_risk: tuple[SceneMessage, ...]
    staleness: dict[int, Staleness]

    @property
    def needed(self) -> int:
        return len(self.keepable) + len(self.empty)

    @property
    def total(self) -> int:
        return self.needed + len(self.at_risk)

    @property
    def keep_total(self) -> int:
        return len(self.empty) + len(self.empty_at_risk)

    def checks(self) -> dict[str, int]:
        return dict(Counter(stale.check for stale in self.staleness.values()))

    def ids(self) -> set[int]:
        return {message.id for message in (*self.keepable, *self.empty, *self.at_risk)}

    def without(self, ids: set[int]) -> "PerceptionBacklog":
        def rest(messages):
            return tuple(message for message in messages if message.id not in ids)

        return PerceptionBacklog(
            keepable=rest(self.keepable),
            empty=rest(self.empty),
            at_risk=rest(self.at_risk),
            empty_at_risk=rest(self.empty_at_risk),
            staleness={
                key: value for key, value in self.staleness.items() if key not in ids
            },
        )

    def frame(self, *, attempts: int, new: set[int], upcoming: int) -> dict:
        """
        `attempts` is the number of requests one analysis can make; `upcoming`
        counts the passages a generation adds, which the backlog cannot see.
        """
        needed = self.needed + upcoming
        total = needed + len(self.at_risk)
        keep_total = self.keep_total + upcoming
        return {
            "needed": needed,
            "keepable": len(self.keepable),
            "empty": len(self.empty),
            "new": upcoming
            + sum(message.id in new for message in (*self.keepable, *self.empty)),
            "at_risk": len(self.at_risk),
            "total": total,
            "requests": total * attempts,
            "keep_total": keep_total,
            "keep_requests": keep_total * attempts,
        }


def analysis_dependents(
    scene: "Scene",
    passages: list[SceneMessage],
    roots: list[SceneMessage],
    *,
    read: PerspectiveReadContext,
) -> tuple[SceneMessage, ...]:
    """
    Passages whose stored views an analysis of `roots` can invalidate. The
    analysis rewrites the views of a root that are not current, and every
    view of a root whose text changed since its analysis. A rewritten view
    invalidates the views that cite it, transitively; a changed text also
    invalidates the views that name the passage as physical context.
    """
    rewritten = set()
    affected = set()
    for root in roots:
        if root.knowledge.content_digest != content_digest(root.perception_text):
            rewritten.add(root.id)
            continue
        reference = source_reference(scene, "message", root.id, read=read)
        for view in root.knowledge.views:
            if reference is None or any(
                select_character_view(scene, reference, name, read=read).status
                not in ("ready", "omitted")
                for name in view.audience
            ):
                affected.add((root.id, view.id))
    touched = {root.id for root in roots}

    def invalidated(view) -> bool:
        return any(
            dependency.kind == "message"
            and (
                dependency.id in rewritten
                or (dependency.id, dependency.view_id) in affected
                or (dependency.view_id is None and dependency.id in touched)
            )
            for dependency in view.sources
        ) or any(item.message_id in rewritten for item in view.passage_provenance)

    skip = {root.id for root in roots}
    dependents = []
    grew = True
    while grew:
        grew = False
        for message in passages:
            if (
                message.id in skip
                or message.knowledge is None
                or not eligible_passage(message)
            ):
                continue
            views = [view for view in message.knowledge.views if invalidated(view)]
            if views:
                skip.add(message.id)
                dependents.append(message)
                affected.update((message.id, view.id) for view in views)
                touched.add(message.id)
                grew = True
    return tuple(sorted(dependents, key=lambda message: message.id))


def perception_backlog(
    scene: "Scene", passages: list[SceneMessage], *, read=None
) -> PerceptionBacklog:
    read = read or PerspectiveReadContext(scene)
    keepable, empty, staleness = [], [], {}
    for message in passages:
        if not eligible_passage(message) or message.knowledge is None:
            continue
        stale = perception_staleness(scene, message, read=read)
        if stale is None:
            continue
        staleness[message.id] = stale
        if has_stored_views(message.knowledge, relevant_audiences(scene, message)):
            keepable.append(message)
        else:
            empty.append(message)
    return PerceptionBacklog(
        keepable=tuple(keepable),
        empty=tuple(empty),
        at_risk=analysis_dependents(scene, passages, [*keepable, *empty], read=read),
        empty_at_risk=analysis_dependents(scene, passages, empty, read=read),
        staleness=staleness,
    )


def keep_stored_perceptions(scene: "Scene", messages: list[SceneMessage]) -> None:
    """Accept the stored ready and omitted views of `messages` as current, in history order."""
    kept = [
        message
        for message in sorted(messages, key=lambda entry: entry.id)
        if keep_stored_views(scene, message.id)
    ]
    # Keep changes no revision and sends no invalidation, so the audience
    # index would keep serving the views it left out while they were stale.
    get_agent("memory").invalidate_audience_sources(
        scene, {("message", message.id, 0) for message in kept}
    )
    read = PerspectiveReadContext(scene)
    remaining = {}
    for message in messages:
        stale = perception_staleness(scene, message, read=read)
        if stale is None:
            emit_perception_status(scene, message, perception_readiness(scene, message))
        else:
            remaining[message.id] = stale.check
    log.info(
        "kept stored perceptions",
        passages=len(messages),
        still_needed=len(remaining),
        still_needed_checks=dict(Counter(remaining.values())),
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


def perception_context(scene: "Scene", message: SceneMessage) -> dict:
    read = PerspectiveReadContext(scene)
    previous = [
        entry
        for entry in perception_passages(scene)
        if entry.id < message.id and eligible_passage(entry)
    ][-CONTEXT_PASSAGES:]
    cast = []
    for name in relevant_audiences(scene, message):
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
                known.append({"source": view.source.model_dump(), "text": view.text})
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
                "text": entry.perception_text,
                "present": entry.present,
                "provenance": passage_provenance(entry).model_dump(),
            }
            for entry in previous
        ],
        "passage": {
            "provenance": passage_provenance(message).model_dump(),
            "text": message.perception_text,
            "kind": message.typ,
            "sub_type": message.sub_type
            if isinstance(message, ContextInvestigationMessage)
            else None,
            "subject_character": message.source_arguments.get("character")
            if isinstance(message, ContextInvestigationMessage)
            else None,
            "speaker": message.character_name
            if isinstance(message, CharacterMessage)
            else None,
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
            },
        )

    def init_perceptions(self) -> None:
        self._perception_locks = WeakKeyDictionary()
        self._perception_deferred = WeakKeyDictionary()
        self._perception_failures = WeakKeyDictionary()
        self._perception_cancelled_by_user = WeakKeyDictionary()
        self._perception_running = WeakKeyDictionary()
        # (cancel sequence, passage ids) that an answer or the threshold approved
        self._perception_approved = WeakKeyDictionary()
        # the event loop keeps only a weak reference to a task
        self._perception_reviews = WeakKeyDictionary()

    def _perception_status(
        self,
        scene: "Scene",
        message: SceneMessage,
        status: Literal["pending", "failed"],
        *,
        invalidate: bool = False,
    ) -> None:
        previous = message.knowledge
        read = PerspectiveReadContext(scene)
        reference = source_reference(scene, "message", message.id, read=read)
        outputs = []
        covered = set()
        for view in previous.views if previous else ():
            covered.update(view.audience)
            values = view.model_dump(exclude={"revision"})
            if invalidate or any(
                select_character_view(scene, reference, name, read=read).status
                not in ("ready", "omitted")
                for name in view.audience
            ):
                values.update(
                    status=status,
                    text=None,
                    sources=(),
                    passage_provenance=(),
                )
            outputs.append(PerspectiveOutput(**values))
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
    ) -> bool:
        if not eligible_passage(message) or message.knowledge is None:
            return False
        return not perception_results_current(scene, message, read=read)

    def _register_perception_sources(
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

    @evidence_writer
    async def finalize_perceptions(
        self, scene: "Scene", messages: list[SceneMessage]
    ) -> None:
        if not character_knowledge_enabled(scene):
            return
        if self.scene is not scene:
            raise GenerationCancelled("Perception scene changed")
        self._register_perception_sources(scene, messages)
        from talemate.knowledge.revision_refresh import refresh_revision

        def selection(message):
            return (
                message.revision_digest(),
                message.active_version,
                message.revision_state.serial if message.revision_state else 0,
            )

        accepted = [(message, selection(message)) for message in messages]

        def still_current():
            sources = {id(entry) for entry in message_sources(scene)}
            if any(id(message) not in sources for message, _ in accepted):
                raise GenerationCancelled(
                    "Finalized perception source was removed or reset"
                )
            return all(selection(message) == selected for message, selected in accepted)

        # Revision hooks have already installed the final accepted text. Use the
        # shared job to publish its results and baseline under the same ownership.
        for message in messages:
            if (
                message.revision_state is not None
                and not message.revision_matches_baseline
            ):
                await refresh_revision(scene, message)
        # Keep ownership through the handoff out of the revision job as well:
        # a manual save there must not be picked up by this automatic finalizer.
        await self.ensure_perceptions(
            scene, still_current=still_current, finalized=messages
        )
        await self.schedule_audience_summaries(scene)
        if any(
            eligible_passage(message)
            and (
                not any(entry is message for entry in message_sources(scene))
                or (message.knowledge is None and relevant_audiences(scene, message))
            )
            for message in messages
        ):
            raise GenerationCancelled(
                "Finalized perception source was removed or reset"
            )

    @evidence_writer
    @background_task("Updating character perceptions")
    async def rebuild_perceptions(self, scene: "Scene") -> None:
        await self.ensure_perceptions(scene)
        await self.repair_summary_views(scene)
        if self.scene is scene:
            await scene.attempt_auto_save()

    def check_perception_backlog(self, scene: "Scene") -> asyncio.Task | None:
        """After a scene load, ask about a large backlog; run only what the user confirms."""
        if not character_knowledge_enabled(scene) or (
            perception_backlog(scene, perception_passages(scene)).total
            <= PERCEPTION_BACKLOG_THRESHOLD
        ):
            return None
        task = asyncio.create_task(self._review_perception_backlog(scene))
        self._perception_reviews[scene] = task
        return task

    async def _review_perception_backlog(self, scene: "Scene") -> None:
        try:
            await self.ensure_perceptions(scene, ask_first=True)
            if self.scene is scene:
                await scene.attempt_auto_save()
        except GenerationCancelled:
            pass
        except Exception:
            log.error("perception backlog review failed", error=traceback.format_exc())

    async def _ask_perception_backlog(
        self, scene: "Scene", frame: dict, cancel_sequence: int
    ) -> PerceptionBacklogDecision:
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        _perception_backlog_futures[request_id] = future
        emit(
            "perception_backlog",
            message="",
            websocket_passthrough=True,
            data={"request_id": request_id, **frame},
        )
        try:
            while not future.done():
                if scene.cancel_requested or scene.cancel_sequence != cancel_sequence:
                    raise GenerationCancelled("Generation cancelled", by_user=True)
                if self.scene is not scene:
                    raise GenerationCancelled("Perception scene changed")
                # a cancel and a scene release both go through Scene.interrupt
                await asyncio.wait(
                    (future, scene.interrupt_signal),
                    return_when=asyncio.FIRST_COMPLETED,
                )
            return future.result()
        finally:
            _perception_backlog_futures.pop(request_id, None)
            if not future.done():
                future.cancel()
                emit(
                    "perception_backlog_closed",
                    message="",
                    websocket_passthrough=True,
                    data={"request_id": request_id},
                )

    @staticmethod
    def _backlog_passages(
        scene: "Scene", before_message_id: int | None, following: list[SceneMessage]
    ) -> list[SceneMessage]:
        passages = perception_prefix(scene, before_message_id)
        counted = {message.id for message in passages}
        return [
            *passages,
            *(
                message
                for message in following
                if message.id not in counted
                and any(entry is message for entry in message_sources(scene))
            ),
        ]

    def _approved(self, scene: "Scene") -> set[int]:
        """The approved passages; a Stop (a new cancel sequence) ends the approval."""
        sequence, approved = self._perception_approved.get(scene, (None, None))
        if sequence != scene.cancel_sequence:
            approved = set()
            self._perception_approved[scene] = (scene.cancel_sequence, approved)
        return approved

    def _unapproved_backlog(
        self, scene: "Scene", passages: list[SceneMessage]
    ) -> PerceptionBacklog:
        return perception_backlog(scene, passages).without(self._approved(scene))

    async def _approve_perception_backlog(
        self,
        scene: "Scene",
        passages: list[SceneMessage],
        *,
        cancel_sequence: int,
        cancels_at_entry: int,
        new: set[int] = frozenset(),
        upcoming: int = 0,
        ask_first: bool = False,
    ) -> bool:
        """
        Approve the analyses of `passages` that no answer approved yet: up to
        the threshold without a question, otherwise as the user decides.
        `upcoming` counts the passages the caller is about to write; a running
        push adds the passages it appends.
        `cancels_at_entry` is the Cancel count when the call started. False when
        `ask_first` finds nothing to ask.
        """
        approved = self._approved(scene)
        backlog = self._unapproved_backlog(scene, passages)
        upcoming += pushed_count(scene)
        if backlog.total + upcoming <= PERCEPTION_BACKLOG_THRESHOLD:
            if ask_first:
                return False
            approved.update(backlog.ids())
            return True
        if cancelled_since(scene, cancels_at_entry):
            raise GenerationCancelled(
                "Perception analysis was not confirmed", by_user=True
            )
        attempts = 2 if self.resolve_config("perceptions", "automatic_repair") else 1
        frame = backlog.frame(attempts=attempts, new=new, upcoming=upcoming)
        for message_id, stale in backlog.staleness.items():
            log.info(
                "perception backlog passage",
                message_id=message_id,
                check=stale.check,
                character=stale.character,
                cited=stale.cited,
            )
        log.info("perception backlog", checks=backlog.checks(), **frame)
        decision = await self._ask_perception_backlog(scene, frame, cancel_sequence)
        log.info("perception backlog decision", decision=decision)
        approved = self._approved(scene)
        if decision == "analyze":
            approved.update(backlog.ids())
            return True
        if decision == "keep":
            current = self._unapproved_backlog(scene, passages)
            keep_stored_perceptions(scene, [*current.keepable, *current.empty])
            approved.update(
                message.id for message in (*current.empty, *current.empty_at_risk)
            )
            return True
        record_cancel(scene)
        raise GenerationCancelled("Perception analysis was not confirmed", by_user=True)

    async def confirm_perception_backlog(
        self, scene: "Scene", *, upcoming: int
    ) -> None:
        """
        Before a generation that writes `upcoming` passages: ask about the
        backlog with those passages counted, before the generation request.
        """
        if not character_knowledge_enabled(scene):
            return
        if self.scene is not scene:
            raise GenerationCancelled("Perception scene changed")
        cancels_at_entry = cancels_at_start(scene)
        self._prepare_perception_sources(scene, None)
        lock = self._perception_locks.setdefault(scene, asyncio.Lock())
        async with lock:
            await self._approve_perception_backlog(
                scene,
                perception_passages(scene),
                cancel_sequence=scene.cancel_sequence,
                cancels_at_entry=cancels_at_entry,
                upcoming=upcoming,
            )

    def _prepare_perception_sources(
        self, scene: "Scene", before_message_id: int | None
    ) -> None:
        self._register_perception_sources(
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

    @evidence_writer
    async def ensure_perceptions(
        self,
        scene: "Scene",
        *,
        before_message_id: int | None = None,
        still_current=None,
        ask_first: bool = False,
        finalized: list[SceneMessage] = (),
        counting: list[SceneMessage] = (),
    ) -> None:
        """
        `finalized` are new passages of this turn, `counting` a revised passage
        whose refresh follows; both count in a question beyond the prefix.
        """
        if not character_knowledge_enabled(scene):
            return
        if self.scene is not scene:
            raise GenerationCancelled("Perception scene changed")
        cancels_at_entry = cancels_at_start(scene)
        self._prepare_perception_sources(scene, before_message_id)
        lock = self._perception_locks.setdefault(scene, asyncio.Lock())
        failures = self._perception_failures.setdefault(scene, {})
        failure_snapshot = failures.copy()
        cancelled_by_user = self._perception_cancelled_by_user.setdefault(scene, {})
        cancel_sequence = scene.cancel_sequence
        async with lock:
            # A prefix revision can be queued behind unrelated later cancellations.
            prefix_ids = (
                {entry.id for entry in perception_prefix(scene, before_message_id)}
                if before_message_id is not None
                else None
            )
            if any(
                count != failure_snapshot.get(message_id, 0)
                for message_id, count in failures.items()
                if prefix_ids is None or message_id in prefix_ids
            ):
                raise GenerationCancelled(
                    "Prerequisite perception analysis was cancelled",
                    by_user=any(
                        cancelled_by_user.get(message_id, False)
                        for message_id, count in failures.items()
                        if count != failure_snapshot.get(message_id, 0)
                        and (prefix_ids is None or message_id in prefix_ids)
                    ),
                )
            try:
                while True:
                    if (
                        scene.cancel_requested
                        or scene.cancel_sequence != cancel_sequence
                    ):
                        raise GenerationCancelled("Generation cancelled", by_user=True)
                    if still_current is not None and not still_current():
                        raise GenerationCancelled(
                            "The selected version changed during analysis"
                        )
                    if self.scene is not scene or not character_knowledge_enabled(
                        scene
                    ):
                        raise GenerationCancelled("Perception scene changed")
                    read = PerspectiveReadContext(scene)
                    message = next(
                        (
                            entry
                            for entry in perception_prefix(scene, before_message_id)
                            if self._perception_needed(scene, entry, read=read)
                        ),
                        None,
                    )
                    if message is None:
                        if before_message_id is None:
                            self._perception_approved.pop(scene, None)
                        return
                    if message.id not in self._approved(scene):
                        if not await self._approve_perception_backlog(
                            scene,
                            self._backlog_passages(
                                scene, before_message_id, [*finalized, *counting]
                            ),
                            cancel_sequence=cancel_sequence,
                            cancels_at_entry=cancels_at_entry,
                            new={entry.id for entry in finalized},
                            ask_first=ask_first,
                        ):
                            return
                        ask_first = False
                        continue
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
                        await self.analyze_perceptions(scene, message)
                    except PerceptionInputsChanged:
                        if (
                            scene.cancel_requested
                            or scene.cancel_sequence != cancel_sequence
                        ):
                            raise GenerationCancelled(
                                "Generation cancelled", by_user=True
                            )
                        if still_current is not None and not still_current():
                            raise GenerationCancelled(
                                "The selected version changed during analysis"
                            )
                        self._perception_status(
                            scene, message, "pending", invalidate=True
                        )
                        warn_perception_regeneration(message)
                        continue
                    except (GenerationCancelled, asyncio.CancelledError) as exc:
                        failures[message.id] = failures.get(message.id, 0) + 1
                        cancelled_by_user[message.id] = getattr(exc, "by_user", False)
                        running.discard(message.id)
                        readiness = perception_readiness(scene, message, "failed")
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
                            self._register_perception_sources(scene, [current])
            except BaseException:
                self._perception_approved.pop(scene, None)
                raise

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
            and perception_context(scene, message) == context
            and perception_intention(scene) == intention
        )

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
            },
        )
        if not self._perception_current(scene, message, knowledge, context, intention):
            log.info("discarding stale perception response", source_id=message.id)
            if self._perception_source_current(scene, message, knowledge):
                raise PerceptionInputsChanged
            return None
        error = None
        try:
            parsed = parse_perceptions(extracted.get("response"), requested)
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
    @evidence_writer
    async def analyze_perceptions(self, scene: "Scene", message: SceneMessage) -> None:
        if not relevant_audiences(scene, message):
            raise GenerationCancelled(
                "No relevant audience is available for perception analysis"
            )
        self._perception_status(scene, message, "pending")
        knowledge = message.knowledge
        context = deepcopy(perception_context(scene, message))
        intention = perception_intention(scene)
        audiences = relevant_audiences(scene, message)
        answer_budget = max(
            2048, len(audiences) * (count_tokens(message.perception_text) + 256)
        )
        outputs = {}
        preserved = [
            PerspectiveOutput(**view.model_dump(exclude={"revision"}))
            for view in knowledge.views
            if view.status in ("ready", "omitted")
        ]
        preserved_names = {name for view in preserved for name in view.audience}

        try:
            repair = self.resolve_config("perceptions", "automatic_repair")
            requested = audiences
            feedback = ""
            for attempt in range(2 if repair else 1):
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
        except PerceptionInputsChanged:
            raise
        except (GenerationCancelled, asyncio.CancelledError):
            if self._perception_current(scene, message, knowledge, context, intention):
                self._mark_perceptions_failed(
                    scene, message, knowledge, outputs, preserved
                )
            raise
        except Exception as exc:
            if not self._perception_current(
                scene, message, knowledge, context, intention
            ):
                if self._perception_source_current(scene, message, knowledge):
                    raise PerceptionInputsChanged from exc
                return
            self._mark_perceptions_failed(scene, message, knowledge, outputs, preserved)
            log.warning(
                "perception analysis failed", source_id=message.id, error=str(exc)
            )
            action = await self.client._prompt_generation_error(
                f"Perception analysis failed for passage {message.id}. "
                f"Reason: {exc}\n\n"
                "Dependent generation is stopped. Retry to analyze this passage again; "
                "Cancel or Ignore stops generation without using reader text."
            )
            if action != "retry":
                raise GenerationCancelled(
                    "Perception analysis requires a successful retry", by_user=True
                )
            return
        set_source_perspectives(
            scene, "message", message.id, [*preserved, *outputs.values()]
        )
