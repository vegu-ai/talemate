import pydantic
import structlog

log = structlog.get_logger("talemate.server.devtools")


class TestPromptPayload(pydantic.BaseModel):
    prompt: str
    generation_parameters: dict
    client_name: str
    kind: str


class DevToolsPlugin:
    router = "devtools"

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    async def handle(self, data: dict):
        log.info("Config action", action=data.get("action"))

        fn = getattr(self, f"handle_{data.get('action')}", None)

        if fn is None:
            return

        await fn(data)

    async def handle_test_prompt(self, data):
        payload = TestPromptPayload(**data)
        client = self.websocket_handler.llm_clients[payload.client_name]["client"]

        log.info(
            "Testing prompt",
            payload={
                k: v for k, v in payload.generation_parameters.items() if k != "prompt"
            },
        )

        response = await client.generate(
            payload.prompt,
            payload.generation_parameters,
            payload.kind,
        )

        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "test_prompt_response",
                "data": {
                    "prompt": payload.prompt,
                    "generation_parameters": payload.generation_parameters,
                    "client_name": payload.client_name,
                    "kind": payload.kind,
                    "response": response,
                },
            }
        )
