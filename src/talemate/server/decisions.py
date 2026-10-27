from talemate.decisions import decision_service
from talemate.server.websocket_plugin import Plugin

# An action change also updates the invocation entry and every associated request
# entry, and both carry the complete action trace.
FORWARDED = {"request", "invocation", "removed"}


class DecisionsPlugin(Plugin):
    router = "decisions"

    def connect(self):
        self.unsubscribe = decision_service.log.subscribe(self.forward)

    def disconnect(self):
        self.unsubscribe()

    def forward(self, payload: dict):
        if payload["event"] in FORWARDED:
            self.websocket_handler.queue_put({"type": self.router, **payload})

    async def handle_snapshot(self, data: dict):
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "event": "snapshot",
                **decision_service.log.snapshot(),
            }
        )

    async def handle_clear(self, data: dict):
        decision_service.log.clear_finished()
