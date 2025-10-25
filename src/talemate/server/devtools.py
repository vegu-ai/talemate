import pydantic
import structlog
from talemate.instance import get_client
from talemate.client.base import ClientBase
from talemate.scene.state_editor import SceneStateEditor
from talemate.scene.schema import SceneState
from talemate.server.websocket_plugin import Plugin
from talemate.emit import emit
from typing import Any

log = structlog.get_logger("talemate.server.devtools")


class TestPromptPayload(pydantic.BaseModel):
    prompt: str
    generation_parameters: dict
    client_name: str
    kind: str


class SetSceneStatePayload(pydantic.BaseModel):
    state: SceneState


class GameStateVariablesPayload(pydantic.BaseModel):
    variables: dict[str, Any] = {}


def ensure_number(v):
    """
    if v is a str but digit turn into into or float
    """

    if isinstance(v, str):
        if v.isdigit():
            return int(v)
        try:
            return float(v)
        except ValueError:
            return v
    return v


class DevToolsPlugin(Plugin):
    router = "devtools"

    async def handle_test_prompt(self, data):
        payload = TestPromptPayload(**data)
        client: ClientBase = get_client(payload.client_name)

        log.info(
            "Testing prompt",
            payload={
                k: ensure_number(v)
                for k, v in payload.generation_parameters.items()
                if k != "prompt"
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
                    "reasoning": client.reasoning_response,
                },
            }
        )

    async def handle_get_scene_state(self, data):
        scene = self.scene
        editor = SceneStateEditor(scene)
        state = editor.dump()

        self.websocket_handler.queue_put(
            {"type": "devtools", "action": "scene_state", "data": state}
        )

    async def handle_update_scene_state(self, data):
        scene = self.scene
        editor = SceneStateEditor(scene)

        try:
            payload = SetSceneStatePayload(**data)
            editor.load(payload.model_dump().get("state"))
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        emit("status", message="Scene state updated", status="success")

        self.websocket_handler.queue_put(
            {"type": "devtools", "action": "scene_state_updated", "data": editor.dump()}
        )

        await self.signal_operation_done()

    async def handle_get_game_state(self, data):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        game_state = scene.game_state.model_dump()
        variables = game_state.get("variables", {})

        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state",
                "data": {"variables": variables},
            }
        )

    async def handle_update_game_state(self, data):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        try:
            payload = GameStateVariablesPayload(**data)
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        # Replace variables with provided structure (must be JSON-serializable)
        scene.game_state.variables = payload.variables or {}

        emit("status", message="Game state updated", status="success")

        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state_updated",
                "data": {"variables": scene.game_state.variables},
            }
        )

        await self.signal_operation_done()
