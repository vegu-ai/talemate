import json
from typing import Any

import pydantic
import structlog
from talemate.agents.base import suppress_agent_busy_status
from talemate.client.base import ClientBase
from talemate.emit import emit
from talemate.instance import get_client
from talemate.path import LOGS_DIR
from talemate.game.state import (
    GameStatePathSettings,
    GameStatePinTarget,
    constrained_game_state_value,
    game_state_pin_paths,
    pin_game_state_path,
    replace_game_state_variables,
    set_game_state_path_settings,
    set_game_state_paths,
    set_game_state_value,
)
from talemate.scene.schema import SceneState
from talemate.scene.state_editor import SceneStateEditor
from talemate.server.websocket_plugin import Plugin
from talemate.util.path import get_path_parent, split_state_path

log = structlog.get_logger("talemate.server.devtools")

# the reply action and status message after a target's paths change
GAME_STATE_PIN_UPDATES: dict[GameStatePinTarget, tuple[str, str]] = {
    "debug": ("game_state_watch_paths_updated", "Game state watch paths updated"),
    "control": ("game_state_control_paths_updated", "Game state control paths updated"),
}


class TestPromptPayload(pydantic.BaseModel):
    prompt: str
    generation_parameters: dict
    client_name: str
    kind: str


class SetSceneStatePayload(pydantic.BaseModel):
    state: SceneState


class GameStateVariablesPayload(pydantic.BaseModel):
    variables: dict[str, Any] = pydantic.Field(default_factory=dict)


class GameStateVariablePayload(pydantic.BaseModel):
    path: str
    value: Any


class GameStatePathsPayload(pydantic.BaseModel):
    paths: list[str] = pydantic.Field(default_factory=list)


class GameStatePathTargetPayload(pydantic.BaseModel):
    path: str
    target: GameStatePinTarget
    enabled: bool
    settings: GameStatePathSettings | None = None


class GameStatePathSettingsPayload(pydantic.BaseModel):
    path: str
    settings: GameStatePathSettings = pydantic.Field(
        default_factory=GameStatePathSettings
    )


class DumpPromptLogPayload(pydantic.BaseModel):
    prompts: list[dict[str, Any]] = []


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
            await self.signal_operation_failed(
                "No active scene", failed_action="update_game_state"
            )
            return

        try:
            payload = GameStateVariablesPayload(**data)
        except Exception as exc:
            await self.signal_operation_failed(
                str(exc), failed_action="update_game_state"
            )
            return

        # Replace variables with provided structure (must be JSON-serializable)
        replace_game_state_variables(scene, payload.variables or {})

        # Re-evaluate gamestate-controlled pins
        with suppress_agent_busy_status():
            await scene.load_active_pins()
        await scene.attempt_auto_save()
        scene.emit_status()

        emit("status", message="Game state updated", status="success")

        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state_updated",
                "data": {"variables": scene.game_state.variables},
            }
        )

        await self.signal_operation_done(signal_only=True)

    async def handle_set_game_state_variable(self, data):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        try:
            payload = GameStateVariablePayload(**data)
            parts = split_state_path(payload.path)
            normalized_path = "/".join(parts)
            parent, _ = get_path_parent(scene.game_state.variables, parts, create=False)
            if parent is None:
                raise ValueError(f"Game state path does not exist: {payload.path}")
            value = constrained_game_state_value(scene, normalized_path, payload.value)
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        # game_state.changed goes out in a task: the websocket loop reads no
        # frame (Stop included) until a listener returns
        set_game_state_value(scene, normalized_path, value, create=False)
        with suppress_agent_busy_status():
            await scene.load_active_pins()
        await scene.attempt_auto_save()
        scene.emit_status()

        emit("status", message="Game state variable updated", status="success")
        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state_variable_updated",
                "data": {"path": normalized_path, "value": value},
            }
        )
        await self.signal_operation_done(signal_only=True)

    async def handle_get_game_state_watch_paths(self, data):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state_watch_paths",
                "data": {"paths": scene.game_state_watch_paths},
            }
        )

    async def _set_game_state_paths(self, data, *, target: GameStatePinTarget):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        try:
            payload = GameStatePathsPayload(**data)
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        set_game_state_paths(scene, target, payload.paths)
        await self._game_state_paths_updated(target)

    async def _game_state_paths_updated(self, target: GameStatePinTarget):
        scene = self.scene
        action, status_message = GAME_STATE_PIN_UPDATES[target]
        await scene.attempt_auto_save()
        scene.emit_status()

        emit("status", message=status_message, status="success")

        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": action,
                "data": {"paths": game_state_pin_paths(scene, target)},
            }
        )

        await self.signal_operation_done(signal_only=True)

    async def handle_set_game_state_watch_paths(self, data):
        await self._set_game_state_paths(data, target="debug")

    async def handle_set_game_state_control_paths(self, data):
        await self._set_game_state_paths(data, target="control")

    async def handle_set_game_state_path_target(self, data):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        try:
            payload = GameStatePathTargetPayload(**data)
            parts = split_state_path(payload.path)
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        pin_game_state_path(
            scene, "/".join(parts), payload.target, payload.enabled, payload.settings
        )
        await self._game_state_paths_updated(payload.target)

    async def handle_set_game_state_path_settings(self, data):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        try:
            payload = GameStatePathSettingsPayload(**data)
            normalized_path = "/".join(split_state_path(payload.path))
            if normalized_path not in scene.pinned_game_state_paths:
                raise ValueError(f"Game state path is not pinned: {normalized_path}")
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        settings = set_game_state_path_settings(
            scene, normalized_path, payload.settings
        )

        await scene.attempt_auto_save()
        scene.emit_status()
        emit("status", message="Game state path settings updated", status="success")
        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state_path_settings_updated",
                "data": {"path": normalized_path, "settings": settings},
            }
        )
        await self.signal_operation_done(signal_only=True)

    async def handle_dump_prompt_log(self, data):
        try:
            payload = DumpPromptLogPayload(**data)
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        if not payload.prompts:
            emit("status", message="No prompts to dump", status="warning")
            return

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = LOGS_DIR / "prompt_log.json"

        try:
            output_path.write_text(json.dumps(payload.prompts, indent=2, default=str))
        except Exception as exc:
            await self.signal_operation_failed(f"Failed to write prompt log: {exc}")
            return

        log.info("Prompt log dumped", path=str(output_path), count=len(payload.prompts))
        emit(
            "status",
            message=f"Prompt log dumped ({len(payload.prompts)} entries) to {output_path.name}",
            status="success",
        )
