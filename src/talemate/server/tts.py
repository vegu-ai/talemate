import structlog

import talemate.instance as instance

log = structlog.get_logger("talemate.server.tts")


class TTSPlugin:
    router = "tts"

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler
        self.tts = None

    async def handle(self, data: dict):
        action = data.get("action")

        if action == "test":
            return await self.handle_test(data)

    async def handle_test(self, data: dict):
        tts_agent = instance.get_agent("tts")

        await tts_agent.generate("Welcome to talemate!")
