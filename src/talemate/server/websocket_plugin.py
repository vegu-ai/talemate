import structlog
from typing import TYPE_CHECKING
from talemate.emit import emit
import traceback

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "Plugin",
]

log = structlog.get_logger("talemate.server.visual")


class Plugin:
    router: str = "router"

    @property
    def scene(self) -> "Scene | None":
        return self.websocket_handler.scene

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler
        self.connect()

    def connect(self):
        pass

    def disconnect(self):
        pass

    async def signal_operation_failed(self, message: str, emit_status: bool = True):
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "operation_done",
                "error": {"message": message},
            }
        )
        if emit_status:
            emit("status", message=message, status="error")

    async def signal_operation_done(
        self, signal_only: bool = False, allow_auto_save: bool = True
    ):
        self.websocket_handler.queue_put(
            {"type": self.router, "action": "operation_done", "data": {}}
        )

        if signal_only:
            return

        if self.scene.auto_save and allow_auto_save:
            await self.scene.save(auto=True)
        else:
            self.scene.saved = False
            self.scene.emit_status()

    async def handle(self, data: dict):
        log.info(f"{self.router} action", action=data.get("action"))
        fn = getattr(self, f"handle_{data.get('action')}", None)
        if fn is None:
            return

        try:
            await fn(data)
        except Exception as e:
            action_name = data.get("action")    
            log.error("Error handling action", action=action_name, error=e, traceback=traceback.format_exc())
            await self.signal_operation_failed(f"Error during {action_name}: {e}")