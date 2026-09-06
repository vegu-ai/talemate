import asyncio
import json
import re
from copy import deepcopy
from typing import TYPE_CHECKING, Literal

from pydantic import StrictInt, StrictStr
from weakref import WeakKeyDictionary

import structlog

from talemate.agents.base import set_processing
from talemate.exceptions import GenerationCancelled
from talemate.client.presets import make_kind
from talemate.util import count_tokens
from talemate.prompts.response import CodeBlockExtractorMixin
from talemate.status import background_task
from talemate.knowledge.context import history_prefix
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import (
    KnowledgeRecord,
    PerspectiveOutput,
    PassageProvenance,
    SourceReference,
    SourcePerspectives,
    content_digest,
)
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    can_cite_view,
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage, SceneMessage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger(__name__)
CONTEXT_PASSAGES = 12


class PerceptionAnalysis(PerspectiveOutput):
    knowledge_ids: tuple[StrictStr, ...]
    passage_ids: tuple[StrictInt, ...]


class PerceptionResponse(KnowledgeRecord):
    views: tuple[PerceptionAnalysis, ...]


class PerceptionExtractor(CodeBlockExtractorMixin):
    validate_structured = True

    def _extract_code_block_from_content(self, content: str) -> str | None:
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
        raise ValueError("No structured perception response found")
    parsed = PerceptionResponse.model_validate_json(extracted)
    names = []
    for view in parsed.views:
        if (
            view.status not in ("ready", "omitted")
            or len(view.audience) != 1
            or view.id is not None
            or view.sources
            or view.passage_provenance
        ):
            raise ValueError(
                "Expected one final perspective per audience, without IDs or sources"
            )
        names.extend(view.audience)
    if len(names) != len(set(names)) or set(names) != set(audiences):
        raise ValueError(
            "Perception audiences must cover the requested cast exactly once"
        )
    return parsed.views


def eligible_passage(message: SceneMessage) -> bool:
    return isinstance(message, (CharacterMessage, NarratorMessage))


def relevant_audiences(scene: "Scene", message: SceneMessage) -> tuple[str, ...]:
    names = set(scene.active_characters) | set(message.present or ())
    return tuple(
        character.name
        for character in scene.character_data.values()
        if character.name in names
    )


def passage_provenance(message: SceneMessage) -> PassageProvenance:
    return PassageProvenance(
        message_id=message.id,
        content_digest=content_digest(message.message),
        revision=message.knowledge.revision if message.knowledge else None,
    )


def perception_context(scene: "Scene", message: SceneMessage) -> dict:
    read = PerspectiveReadContext(scene)
    previous = []
    for entry in scene.history:
        if entry is message:
            break
        if eligible_passage(entry):
            previous.append(entry)
    previous = previous[-CONTEXT_PASSAGES:]
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
                "authored_details": character.details,
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
                "text": entry.message,
                "present": entry.present,
                "provenance": passage_provenance(entry).model_dump(),
            }
            for entry in previous
        ],
        "passage": {
            "provenance": passage_provenance(message).model_dump(),
            "text": message.message,
            "kind": message.typ,
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
    for output in outputs:
        offered = knowledge[output.audience[0]]
        if (
            set(output.knowledge_ids) - offered.keys()
            or set(output.passage_ids) - physical.keys()
        ):
            raise ValueError(
                "Perception cites analytical inputs that were not offered to its audience"
            )
        resolved.append(
            PerspectiveOutput(
                audience=output.audience,
                status=output.status,
                text=output.text,
                sources=tuple(
                    SourceReference.model_validate(offered[key])
                    for key in dict.fromkeys(output.knowledge_ids)
                ),
                passage_provenance=(
                    PassageProvenance.model_validate(context["passage"]["provenance"]),
                    *(
                        PassageProvenance.model_validate(physical[key])
                        for key in dict.fromkeys(output.passage_ids)
                    ),
                ),
            )
        )
    return resolved


class PerceptionMixin:
    def init_perceptions(self) -> None:
        self._perception_locks = WeakKeyDictionary()
        self._perception_deferred = WeakKeyDictionary()
        self._perception_failures = WeakKeyDictionary()

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
                    status=status, text=None, sources=(), passage_provenance=()
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
        read = read or PerspectiveReadContext(scene)
        reference = source_reference(scene, "message", message.id, read=read)
        return message.knowledge.content_digest != content_digest(
            message.message
        ) or any(
            select_character_view(scene, reference, name, read=read).status
            not in ("ready", "omitted")
            for view in message.knowledge.views
            for name in view.audience
        )

    async def finalize_perceptions(
        self, scene: "Scene", messages: list[SceneMessage]
    ) -> None:
        if not character_knowledge_enabled(scene):
            return
        for message in messages:
            if eligible_passage(message) and message.knowledge is None:
                if not relevant_audiences(scene, message):
                    self._perception_deferred.setdefault(scene, {})[message.id] = (
                        message
                    )
                    continue
                self._perception_status(scene, message, "pending")
        await self.ensure_perceptions(scene)
        await self.schedule_audience_summaries(scene)
        if any(
            eligible_passage(message)
            and (
                not any(entry is message for entry in scene.history)
                or (message.knowledge is None and relevant_audiences(scene, message))
            )
            for message in messages
        ):
            raise GenerationCancelled(
                "Finalized perception source was removed or reset"
            )

    @background_task("Updating character perceptions")
    async def rebuild_perceptions(self, scene: "Scene") -> None:
        await self.ensure_perceptions(scene)
        await self.repair_summary_views(scene)
        if self.scene is scene:
            await scene.attempt_auto_save()

    async def ensure_perceptions(
        self, scene: "Scene", *, before_message_id: int | None = None
    ) -> None:
        if not character_knowledge_enabled(scene):
            return
        prefix_ids = {
            message.id for message in history_prefix(scene, before_message_id)
        }
        deferred = self._perception_deferred.get(scene, {})
        for identity, message in list(deferred.items()):
            if not any(entry is message for entry in scene.history):
                del deferred[identity]
            elif identity in prefix_ids and relevant_audiences(scene, message):
                if message.knowledge is None:
                    self._perception_status(scene, message, "pending")
                del deferred[identity]
        lock = self._perception_locks.setdefault(scene, asyncio.Lock())
        failures = self._perception_failures.setdefault(scene, {})
        failure_snapshot = failures.copy()
        async with lock:
            # A prefix revision can be queued behind unrelated later cancellations.
            prefix_ids = (
                {entry.id for entry in history_prefix(scene, before_message_id)}
                if before_message_id is not None
                else None
            )
            if any(
                count != failure_snapshot.get(message_id, 0)
                for message_id, count in failures.items()
                if prefix_ids is None or message_id in prefix_ids
            ):
                raise GenerationCancelled(
                    "Prerequisite perception analysis was cancelled"
                )
            while True:
                if self.scene is not scene or not character_knowledge_enabled(scene):
                    raise GenerationCancelled("Perception scene changed")
                read = PerspectiveReadContext(scene)
                message = next(
                    (
                        entry
                        for entry in history_prefix(scene, before_message_id)
                        if self._perception_needed(scene, entry, read=read)
                    ),
                    None,
                )
                if message is None:
                    return
                try:
                    await self.analyze_perceptions(scene, message)
                except (GenerationCancelled, asyncio.CancelledError):
                    failures[message.id] = failures.get(message.id, 0) + 1
                    raise

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
            and any(entry is message for entry in scene.history)
            and message.knowledge is knowledge
            and knowledge.content_digest == content_digest(message.message)
            and perception_context(scene, message) == context
        )

    @set_processing
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
            2048, len(audiences) * (count_tokens(message.message) + 256)
        )
        try:
            _, extracted = await Prompt.request(
                "summarizer.perceptions",
                self.client,
                make_kind("analyze", answer_budget),
                vars={"scene": scene, "context": context},
            )
            if not self._perception_current(scene, message, knowledge, context):
                log.info("discarding stale perception response", source_id=message.id)
                return
            outputs = parse_perceptions(extracted["response"], audiences)
            outputs = resolve_perception_inputs(outputs, context)
        except (GenerationCancelled, asyncio.CancelledError):
            if self._perception_current(scene, message, knowledge, context):
                self._perception_status(scene, message, "failed")
            raise
        except Exception as exc:
            if not self._perception_current(scene, message, knowledge, context):
                return
            self._perception_status(scene, message, "failed")
            log.warning(
                "perception analysis failed", source_id=message.id, error=str(exc)
            )
            action = await self.client._prompt_generation_error(
                f"Perception analysis failed for passage {message.id}. "
                "Dependent generation is stopped. Retry to analyze this passage again; "
                "Cancel or Ignore stops generation without using reader text."
            )
            if action != "retry":
                raise GenerationCancelled(
                    "Perception analysis requires a successful retry"
                )
            return
        preserved = [
            PerspectiveOutput(**view.model_dump(exclude={"revision"}))
            for view in knowledge.views
            if view.status in ("ready", "omitted")
        ]
        preserved_names = {name for view in preserved for name in view.audience}
        outputs = [
            output for output in outputs if output.audience[0] not in preserved_names
        ]
        set_source_perspectives(scene, "message", message.id, [*preserved, *outputs])
