import pydantic
import structlog

from talemate.history import HistoryEntry
from talemate.instance import get_agent
from talemate.knowledge.catalog import FactQuery, list_facts
from talemate.knowledge.facts import UNSET, fact_memory_document, update_fact
from talemate.knowledge.chronology import fact_display
from talemate.knowledge.perspectives import source_reference
from talemate.knowledge.topics import refresh_topics
from talemate.knowledge.schema import EntryVisibility, FactImportance, KnowledgeEdge
from talemate.status import background_task

log = structlog.get_logger("talemate.server.world_state_manager.knowledge")


class CharacterKnowledgePayload(pydantic.BaseModel):
    name: str


class TopicFactsPayload(pydantic.BaseModel):
    name: str
    topic_ids: list[str] = pydantic.Field(min_length=1)


class DisclosurePayload(pydantic.BaseModel):
    name: str
    target: str
    information: str | None = None
    whole_entry: pydantic.StrictBool = False


class KnowledgeEdgePayload(pydantic.BaseModel):
    edge: KnowledgeEdge


class RemoveKnowledgeEdgePayload(pydantic.BaseModel):
    name: str
    edge_id: str


class CharacterEntryVisibilityPayload(pydantic.BaseModel):
    name: str
    key: str
    visibility: EntryVisibility


class WorldEntryVisibilityPayload(pydantic.BaseModel):
    entry_id: str
    visibility: EntryVisibility


class UpdateFactPayload(pydantic.BaseModel):
    """A patch: a field that is present is authored, an absent one is left alone."""

    fact_id: str
    text: str | None = None
    importance: FactImportance | None = None
    false: pydantic.StrictBool | None = None
    supersedes: str | None = None

    @pydantic.field_validator("text")
    @classmethod
    def _text(cls, value):
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("Fact text must not be empty")
        return value


class FactIdPayload(pydantic.BaseModel):
    fact_id: str


class FactIdsPayload(pydantic.BaseModel):
    fact_ids: list[str] = pydantic.Field(min_length=1)


class FactsFalsePayload(FactIdsPayload):
    false: pydantic.StrictBool


class GrantFactsPayload(FactIdsPayload):
    name: str


class RegenerateFactsPayload(pydantic.BaseModel):
    entry: HistoryEntry


class KnowledgeMixin:
    async def handle_get_fact_source(self, data):
        payload = FactIdPayload(**data)
        fact = self.scene.world_state.facts.get(payload.fact_id)
        message = (
            self.scene.get_message(fact.message_id)
            if fact and fact.message_id is not None
            else None
        )
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "fact_source",
                "data": {
                    "fact_id": payload.fact_id,
                    "message_id": message.id if message is not None else None,
                    "text": str(message) if message is not None else None,
                },
            }
        )

    async def _send_character_knowledge(
        self, name: str, *, request_id: str | None = None
    ):
        knowledge = await self.world_state_manager.get_character_knowledge(name)
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_knowledge",
                **({"request_id": request_id} if request_id is not None else {}),
                "data": knowledge.model_dump(),
            }
        )

    async def handle_get_character_knowledge(self, data):
        payload = CharacterKnowledgePayload(**data)
        await self._send_character_knowledge(payload.name)

    async def handle_get_topic_facts(self, data):
        payload = TopicFactsPayload(**data)
        rows = self.world_state_manager.get_topics_facts(
            payload.name, payload.topic_ids
        )
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "topic_facts",
                "data": {
                    "name": payload.name,
                    "topics": {
                        topic_id: [fact.model_dump() for fact in facts]
                        for topic_id, facts in rows.items()
                    },
                },
            }
        )

    @background_task("Recording character disclosure")
    async def handle_grant_disclosure(self, data):
        scene = self.scene
        try:
            payload = DisclosurePayload(**data)
            disclosure = self.world_state_manager.grant_character_disclosure(
                payload.name,
                payload.target,
                text=payload.information,
                whole_entry=payload.whole_entry,
            )
        except ValueError as exc:
            await self.signal_operation_failed(
                str(exc),
                failed_action="grant_disclosure",
                request_id=data.get("request_id"),
                extra={"data": {"name": data.get("name")}},
            )
            return
        await self._send_character_knowledge(
            payload.name, request_id=data.get("request_id")
        )
        await self.signal_operation_done(allow_auto_save=False)
        status = await get_agent("summarizer").rebuild_supported_facts(
            scene, [source_reference(scene, "disclosure", disclosure.id)]
        )
        if self.scene is scene:
            await self._send_character_knowledge(
                payload.name, request_id=data.get("request_id")
            )
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "disclosure_indexed",
                    "data": {
                        "name": payload.name,
                        "id": disclosure.id,
                        "facts_status": status,
                    },
                }
            )
            await self.signal_operation_done()

    async def handle_set_knowledge_edge(self, data):
        payload = KnowledgeEdgePayload(**data)
        try:
            edge = await self.world_state_manager.set_knowledge_edge(payload.edge)
        except ValueError as exc:
            await self.signal_operation_failed(
                str(exc), failed_action="set_knowledge_edge"
            )
            return
        await self._send_character_knowledge(edge.character)
        await self.signal_operation_done()

    async def handle_remove_knowledge_edge(self, data):
        payload = RemoveKnowledgeEdgePayload(**data)
        await self.world_state_manager.remove_knowledge_edge(payload.edge_id)
        await self._send_character_knowledge(payload.name)
        await self.signal_operation_done()

    async def handle_set_character_entry_visibility(self, data):
        payload = CharacterEntryVisibilityPayload(**data)
        await self.world_state_manager.set_character_entry_visibility(
            payload.name, payload.key, payload.visibility
        )
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_set_world_entry_visibility(self, data):
        payload = WorldEntryVisibilityPayload(**data)
        await self.world_state_manager.set_world_entry_visibility(
            payload.entry_id, payload.visibility
        )
        await self.handle_get_world({})
        await self.signal_operation_done()

    def _emit_fact(self, action, fact):
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": action,
                "data": fact_display(self.scene, fact),
            }
        )

    async def handle_list_facts(self, data):
        query = FactQuery(**{k: v for k, v in data.items() if k != "request_id"})
        page = list_facts(self.scene, query)
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "facts",
                **(
                    {"request_id": data["request_id"]}
                    if data.get("request_id") is not None
                    else {}
                ),
                "data": page.model_dump(),
            }
        )

    async def handle_update_fact(self, data):
        payload = UpdateFactPayload(**data)
        try:
            fact = await update_fact(
                self.scene,
                payload.fact_id,
                text=payload.text if payload.text is not None else UNSET,
                importance=payload.importance
                if payload.importance is not None
                else UNSET,
                false=payload.false if payload.false is not None else UNSET,
                supersedes=payload.supersedes
                if "supersedes" in payload.model_fields_set
                else UNSET,
            )
        except ValueError as exc:
            await self.signal_operation_failed(str(exc), failed_action="update_fact")
            return
        if fact is None:
            log.warning("update_fact: unknown fact id", fact_id=payload.fact_id)
            await self.signal_operation_done()
            return
        await refresh_topics(self.scene, force=True)
        self._emit_fact("fact_updated", fact)
        await self.signal_operation_done()

    def _remove_fact(self, fact_id):
        world_state = self.scene.world_state
        fact = world_state.facts.pop(fact_id, None)
        if fact is None:
            return None
        world_state.knowledge = [
            edge for edge in world_state.knowledge if edge.target != fact.id
        ]
        for other in world_state.facts.values():
            if other.supersedes == fact.id:
                other.supersedes = None
        return fact

    async def _finish_deleting(self, removed):
        await get_agent("memory").delete({"ids": [fact.id for fact in removed]})
        await refresh_topics(self.scene, force=True)
        for fact in removed:
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "fact_deleted",
                    "data": {"fact_id": fact.id, "archive_id": fact.archive_id},
                }
            )
        await self.signal_operation_done()

    async def handle_delete_fact(self, data):
        payload = FactIdPayload(**data)
        fact = self._remove_fact(payload.fact_id)
        if fact is None:
            await self.signal_operation_done()
            return
        await self._finish_deleting([fact])

    async def handle_delete_facts(self, data):
        payload = FactIdsPayload(**data)
        removed = [
            fact
            for fact in (self._remove_fact(fact_id) for fact_id in payload.fact_ids)
            if fact is not None
        ]
        if not removed:
            await self.signal_operation_done()
            return
        await self._finish_deleting(removed)

    async def handle_set_facts_false(self, data):
        payload = FactsFalsePayload(**data)
        facts = self.scene.world_state.facts
        changed = [facts[fact_id] for fact_id in payload.fact_ids if fact_id in facts]
        for fact in changed:
            fact.false = payload.false
        if changed:
            await get_agent("memory").add_many(
                [fact_memory_document(fact) for fact in changed]
            )
        for fact in changed:
            self._emit_fact("fact_updated", fact)
        await self.signal_operation_done()

    async def handle_grant_facts(self, data):
        payload = GrantFactsPayload(**data)
        try:
            self.world_state_manager.grant_facts(payload.name, payload.fact_ids)
        except ValueError as exc:
            await self.signal_operation_failed(str(exc), failed_action="grant_facts")
            return
        await self._send_character_knowledge(payload.name)
        await self.signal_operation_done()

    @background_task("Regenerating facts")
    async def handle_regenerate_facts(self, data):
        payload = RegenerateFactsPayload(**data)
        summarizer = get_agent("summarizer")
        status = await summarizer.regenerate_facts(payload.entry)
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "facts_regenerated",
                "data": {"entry_id": payload.entry.id, "facts_status": status},
            }
        )
        await self.signal_operation_done()
        await self.handle_request_scene_history({})
