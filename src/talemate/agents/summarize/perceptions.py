from talemate.knowledge.processing import evidence_writer
import asyncio
import json
import re
from copy import deepcopy
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
from talemate.client.presets import make_kind
from talemate.util import count_tokens
from talemate.prompts.response import CodeBlockExtractorMixin
from talemate.status import background_task
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.readiness import emit_perception_status, perception_readiness
from talemate.knowledge.evidence import passage_spans
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
    message_sources,
    can_cite_view,
    select_character_view,
    set_source_perspectives,
    source_reference,
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


class PerceptionAnalysis(PerspectiveOutput):
    knowledge_ids: tuple[StrictStr, ...]
    passage_ids: tuple[StrictInt, ...]


class PerceptionValidationError(ValueError):
    def __init__(self, reason: str, views: tuple[PerceptionAnalysis, ...] = ()):
        super().__init__(reason)
        self.views = views


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
                evidence_spans=perception_citations(item, "evidence_spans", int, name),
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


def perception_results_current(scene, message, *, read=None) -> bool:
    """Verify exact selected-source results for every currently required audience."""
    if message.knowledge is None:
        return False
    if message.knowledge.content_digest != content_digest(message.perception_text):
        return False
    read = read or PerspectiveReadContext(scene)
    reference = source_reference(scene, "message", message.id, read=read)
    return reference is not None and all(
        select_character_view(scene, reference, name, read=read).status
        in ("ready", "omitted")
        for name in relevant_audiences(scene, message)
    )


def passage_provenance(message: SceneMessage) -> PassageProvenance:
    return PassageProvenance(
        message_id=message.id,
        content_digest=content_digest(message.perception_text),
        revision=message.knowledge.revision if message.knowledge else None,
    )


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
                "established_knowledge": known,
            }
        )
    return {
        "shared_scene_description": scene.description,
        "shared_story_intention": scene.intent_state.intent,
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
            "evidence_spans": [
                {"id": index, "text": text}
                for index, text in enumerate(passage_spans(message.perception_text))
            ],
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
                evidence_spans=output.evidence_spans,
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

    def _perception_status(
        self,
        scene: "Scene",
        message: SceneMessage,
        status: Literal["pending", "failed"],
    ) -> None:
        previous = message.knowledge
        read = PerspectiveReadContext(scene)
        reference = source_reference(scene, "message", message.id, read=read)
        outputs = []
        covered = set()
        for view in previous.views if previous else ():
            covered.update(view.audience)
            values = view.model_dump(exclude={"revision"})
            if any(
                select_character_view(scene, reference, name, read=read).status
                not in ("ready", "omitted")
                for name in view.audience
            ):
                values.update(
                    status=status,
                    text=None,
                    sources=(),
                    passage_provenance=(),
                    evidence_spans=(),
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
        await self.ensure_perceptions(scene, still_current=still_current)
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

    @evidence_writer
    async def ensure_perceptions(
        self,
        scene: "Scene",
        *,
        before_message_id: int | None = None,
        still_current=None,
    ) -> None:
        if not character_knowledge_enabled(scene):
            return
        if self.scene is not scene:
            raise GenerationCancelled("Perception scene changed")
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
        lock = self._perception_locks.setdefault(scene, asyncio.Lock())
        failures = self._perception_failures.setdefault(scene, {})
        failure_snapshot = failures.copy()
        cancelled_by_user = self._perception_cancelled_by_user.setdefault(scene, {})
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
            while True:
                if still_current is not None and not still_current():
                    raise GenerationCancelled(
                        "The selected version changed during analysis"
                    )
                if self.scene is not scene or not character_knowledge_enabled(scene):
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
                    return
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

    def _perception_current(
        self,
        scene: "Scene",
        message: SceneMessage,
        knowledge: SourcePerspectives,
        context: dict,
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
            and perception_context(scene, message) == context
        )

    async def _perception_attempt(
        self, scene, message, knowledge, context, requested, answer_budget, feedback
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
        if not self._perception_current(scene, message, knowledge, context):
            log.info("discarding stale perception response", source_id=message.id)
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
        except (GenerationCancelled, asyncio.CancelledError):
            if self._perception_current(scene, message, knowledge, context):
                self._mark_perceptions_failed(
                    scene, message, knowledge, outputs, preserved
                )
            raise
        except Exception as exc:
            if not self._perception_current(scene, message, knowledge, context):
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
