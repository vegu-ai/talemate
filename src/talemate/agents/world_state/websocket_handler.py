import pydantic

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.scene_message import ContextInvestigationMessage
from talemate.server.websocket_plugin import Plugin
from talemate.status import LoadingLabel, set_loading

from talemate.agents.world_state.snapshot import (
    SNAPSHOT_ENTITY_SELECTION_MAX,
    normalize_snapshot_selection,
)

__all__ = [
    "WorldStateWebsocketHandler",
]


class RequestUpdatePayload(pydantic.BaseModel):
    reset: bool = False
    instructions: str = ""


class SummarizeAndPinPayload(pydantic.BaseModel):
    message_id: int | None = None
    num_messages: int = 5


class ExamineEntityPayload(pydantic.BaseModel):
    entity_name: str
    entity_kind: str
    snapshot_text: str


class AddSnapshotEntityPayload(pydantic.BaseModel):
    message_id: int
    text: str


def _summarize_and_pin_label(handler, data: dict) -> LoadingLabel:
    return LoadingLabel(
        "Summarizing {} messages and pinning",
        SummarizeAndPinPayload(**data).num_messages,
    )


def _examine_label(handler, data: dict) -> LoadingLabel | str:
    entity = ExamineEntityPayload(**data).entity_name
    return LoadingLabel("Examining {}", entity) if entity else "Examining"


class WorldStateWebsocketHandler(Plugin):
    router = "world_state_agent"

    @property
    def agent(self):
        return get_agent("world_state")

    async def handle_request_update(self, data: dict):
        payload = RequestUpdatePayload(**data)

        if payload.reset:
            self.scene.world_state.reset()

        # Run the snapshot as a background task (status "busy_bg") so the manual
        # refresh doesn't lock the UI. cancel_in_flight=True so the user's
        # explicit refresh — especially a reset — takes priority over any
        # in-progress automatic snapshot.
        await self.agent.dispatch_world_state_update(
            cancel_in_flight=True, instructions=payload.instructions
        )
        await self.signal_operation_done(allow_auto_save=False)

    async def handle_add_snapshot_entity(self, data: dict):
        payload = AddSnapshotEntityPayload(**data)
        selection = normalize_snapshot_selection(payload.text)

        agent = self.agent
        if not agent.enabled or not agent.update_world_state_enabled:
            await self.signal_operation_failed(
                "Turn on the World State agent and its Update world state action "
                "to add entities by hand."
            )
            return

        if not agent.client:
            await self.signal_operation_failed(
                "The World State agent has no client assigned."
            )
            return

        if not selection:
            await self.signal_operation_failed(
                "Select some text in a scene message first."
            )
            return

        if len(selection) > SNAPSHOT_ENTITY_SELECTION_MAX:
            await self.signal_operation_failed(
                f"That selection is too long — select up to "
                f"{SNAPSHOT_ENTITY_SELECTION_MAX} characters."
            )
            return

        # Same background slot as the refresh: the panel's spinner shows it and
        # its cancel button cancels it.
        await self.agent.dispatch_add_snapshot_entity(payload.message_id, selection)
        await self.signal_operation_done(allow_auto_save=False)

    async def handle_cancel_request_update(self, data: dict):
        self.agent.cancel_world_state_update()
        await self.signal_operation_done(allow_auto_save=False)

    @set_loading(_summarize_and_pin_label, cancellable=True, as_async=True)
    async def handle_summarize_and_pin(self, data: dict):
        payload = SummarizeAndPinPayload(**data)

        if not self.scene.history:
            raise ValueError("No history to summarize.")

        message_id = payload.message_id or self.scene.history[-1].id
        await self.agent.summarize_and_pin(
            message_id, num_messages=payload.num_messages
        )
        await self.signal_operation_done(allow_auto_save=False)

    @set_loading(_examine_label, cancellable=True, as_async=True)
    async def handle_examine_entity(self, data: dict):
        payload = ExamineEntityPayload(**data)
        examine_text = await self.agent.examine_entity(
            entity_name=payload.entity_name,
            entity_kind=payload.entity_kind,
            snapshot_text=payload.snapshot_text,
        )
        message: ContextInvestigationMessage = ContextInvestigationMessage(
            examine_text, sub_type="examine"
        )
        # Freeze the snapshot rather than re-deriving from current world_state
        # at regenerate time — preserves "same inputs, different output" if a
        # newer request_world_state has overwritten this entity since the click.
        message.set_source("world_state", "examine_entity", **payload.model_dump())
        await self.scene.push_history(message)
        emit("context_investigation", message=message)
        await self.signal_operation_done(allow_auto_save=False)
