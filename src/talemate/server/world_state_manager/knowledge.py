import pydantic
import structlog

from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge

log = structlog.get_logger("talemate.server.world_state_manager.knowledge")


class CharacterKnowledgePayload(pydantic.BaseModel):
    name: str


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


class KnowledgeMixin:
    async def _send_character_knowledge(self, name: str):
        knowledge = await self.world_state_manager.get_character_knowledge(name)
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_knowledge",
                "data": knowledge.model_dump(),
            }
        )

    async def handle_get_character_knowledge(self, data):
        payload = CharacterKnowledgePayload(**data)
        await self._send_character_knowledge(payload.name)

    async def handle_set_knowledge_edge(self, data):
        payload = KnowledgeEdgePayload(**data)
        edge = await self.world_state_manager.set_knowledge_edge(payload.edge)
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
