import pydantic
import asyncio
import structlog

from talemate.instance import get_agent
from talemate.history import (
    history_with_relative_time,
    rebuild_history,
    HistoryEntry,
    update_history_entry,
    regenerate_history_entry,
    collect_source_entries,
    add_history_entry,
    delete_history_entry,
    compute_layer_stats,
    collect_time_passages,
)
from talemate.scene_message import TimePassageMessage
from talemate.server.world_state_manager import world_state_templates
from talemate.util.time import (
    amount_unit_to_iso8601_duration,
    iso8601_duration_to_human,
)

log = structlog.get_logger("talemate.server.world_state_manager.history")


class RegenerateHistoryPayload(pydantic.BaseModel):
    generation_options: world_state_templates.GenerationOptions | None = None


class HistoryEntryPayload(pydantic.BaseModel):
    entry: HistoryEntry


class AddHistoryEntryPayload(pydantic.BaseModel):
    text: str
    amount: int
    unit: str


class ResetLayeredHistoryPayload(pydantic.BaseModel):
    remove_layers: int | None = None


class UpdateTimePassagePayload(pydantic.BaseModel):
    history_index: int
    amount: int
    unit: str


class LayerStatsPayload(pydantic.BaseModel):
    layer: int


class HistoryMixin:
    """
    Handles history-related operations for the world state manager.
    """

    async def handle_request_scene_history(self, data):
        """
        Request the entire history for the scene.
        """

        history = history_with_relative_time(
            self.scene.archived_history, self.scene.ts, layer=0
        )

        layered_history = []

        summarizer = get_agent("summarizer")

        if summarizer.layered_history_enabled:
            for index, layer in enumerate(self.scene.layered_history):
                layered_history.append(
                    history_with_relative_time(layer, self.scene.ts, layer=index + 1)
                )

        time_passages = collect_time_passages(self.scene)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "scene_history",
                "data": {
                    "history": history,
                    "layered_history": layered_history,
                    "time_passages": time_passages,
                },
            }
        )

    async def handle_regenerate_history(self, data):
        """
        Regenerate the history for the scene.
        """

        payload = RegenerateHistoryPayload(**data)

        async def callback():
            self.scene.emit_status()
            await self.handle_request_scene_history(data)

        task = asyncio.create_task(
            rebuild_history(
                self.scene,
                callback=callback,
                generation_options=payload.generation_options,
            )
        )

        async def done():
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "history_regenerated",
                    "data": payload.model_dump(),
                }
            )

            await self.signal_operation_done()
            await self.handle_request_scene_history(data)

        # when task is done,  queue a message to the client
        task.add_done_callback(lambda _: asyncio.create_task(done()))

    async def handle_update_history_entry(self, data):
        payload = HistoryEntryPayload(**data)

        entry = await update_history_entry(self.scene, payload.entry)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "history_entry_updated",
                "data": entry.model_dump(),
            }
        )

        await self.signal_operation_done()

    async def handle_regenerate_history_entry(self, data):
        """
        Regenerate a single history entry.
        """

        payload = HistoryEntryPayload(**data)

        log.debug("regenerate_history_entry", payload=payload)

        try:
            entry = await regenerate_history_entry(self.scene, payload.entry)
        except Exception as e:
            log.error("regenerate_history_entry", error=e)
            await self.signal_operation_failed(str(e))
            return

        log.debug("regenerate_history_entry (done)", entry=entry)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "history_entry_regenerated",
                "data": entry.model_dump(),
            }
        )

        await self.signal_operation_done()

    async def handle_inspect_history_entry(self, data):
        """
        Inspect a single history entry.
        """

        payload = HistoryEntryPayload(**data)

        entries = collect_source_entries(self.scene, payload.entry)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "history_entry_source_entries",
                "data": {
                    "entries": [entry.model_dump() for entry in entries],
                    "entry": payload.entry.model_dump(),
                },
            }
        )

    async def handle_add_history_entry(self, data):
        """
        Add a new manual history entry to the base (archived) layer.
        """

        payload = AddHistoryEntryPayload(**data)

        try:
            iso_offset = amount_unit_to_iso8601_duration(
                int(payload.amount), payload.unit
            )
        except ValueError as e:
            await self.signal_operation_failed(str(e))
            return

        try:
            await add_history_entry(self.scene, payload.text, iso_offset)
        except Exception as e:
            log.error("add_history_entry", error=e)
            await self.signal_operation_failed(str(e))
            return

        # Send updated history to the client via existing handler
        await self.handle_request_scene_history({})

        await self.signal_operation_done()

    async def handle_delete_history_entry(self, data):
        """
        Delete a manual base-layer history entry (no start/end indices).
        """
        payload = HistoryEntryPayload(**data)

        try:
            await delete_history_entry(self.scene, payload.entry)
        except Exception as e:
            log.error("delete_history_entry", error=e)
            await self.signal_operation_failed(str(e))
            return

        # Send updated history to client
        await self.handle_request_scene_history({})

        await self.signal_operation_done()

    async def handle_update_time_passage(self, data):
        """
        Update the duration of a TimePassageMessage in scene.history,
        then recalculate all timestamps via fix_time.
        """

        payload = UpdateTimePassagePayload(**data)

        try:
            iso_duration = amount_unit_to_iso8601_duration(
                int(payload.amount), payload.unit
            )
        except ValueError as e:
            await self.signal_operation_failed(str(e))
            return

        if payload.history_index < 0 or payload.history_index >= len(
            self.scene.history
        ):
            await self.signal_operation_failed("Invalid history index")
            return

        message = self.scene.history[payload.history_index]
        if not isinstance(message, TimePassageMessage):
            await self.signal_operation_failed("Entry is not a time passage")
            return

        message.ts = iso_duration
        message.message = iso8601_duration_to_human(iso_duration, suffix=" later")

        self.scene.fix_time()
        self.scene.emit_status()

        # Re-emit scene history to update the main message screen
        await self.scene.emit_history()

        await self.handle_request_scene_history({})
        await self.signal_operation_done()

    async def handle_reset_layered_history(self, data):
        """
        Reset layered history and rebuild it from scratch.
        Optionally remove only the last N layers instead of all.
        """

        payload = ResetLayeredHistoryPayload(**data)
        summarizer = get_agent("summarizer")

        if payload.remove_layers is not None:
            n = payload.remove_layers
            if n > 0 and n <= len(self.scene.layered_history):
                self.scene.layered_history = self.scene.layered_history[:-n]
            else:
                self.scene.layered_history = []
        else:
            self.scene.layered_history = []

        task = asyncio.create_task(summarizer.summarize_to_layered_history())

        async def done():
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "layered_history_reset",
                    "data": {},
                }
            )
            await self.signal_operation_done()
            await self.handle_request_scene_history({})

        task.add_done_callback(lambda _: asyncio.create_task(done()))

    async def handle_request_layer_stats(self, data):
        """
        Compute on-demand compression statistics for a specific layer.
        """

        payload = LayerStatsPayload(**data)

        try:
            stats = compute_layer_stats(self.scene, payload.layer)
        except ValueError as e:
            await self.signal_operation_failed(str(e))
            return

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "layer_stats",
                "data": stats,
            }
        )
