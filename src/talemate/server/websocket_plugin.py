import structlog

__all__ = [
    "Plugin",
]

log = structlog.get_logger("talemate.server.visual")


class Plugin:
    router = "router"

    @property
    def scene(self):
        return self.websocket_handler.scene

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    async def handle(self, data: dict):
        log.info(f"{self.router} action", action=data.get("action"))
        fn = getattr(self, f"handle_{data.get('action')}", None)
        if fn is None:
            return

        await fn(data)
