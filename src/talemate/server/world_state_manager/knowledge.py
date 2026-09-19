import pydantic

from talemate.instance import get_agent
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge
from talemate.status import background_task


class CharacterKnowledgePayload(pydantic.BaseModel):
    name: str


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


class KnowledgeMixin:
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
        await get_agent("memory").ensure_audience_index(scene)
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
