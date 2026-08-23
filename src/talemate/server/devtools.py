import json
from typing import Any, Literal

import pydantic
import structlog
from talemate.client.base import ClientBase
from talemate.emit import emit
from talemate.instance import get_client
from talemate.path import LOGS_DIR
from talemate.scene.schema import SceneState
from talemate.scene.state_editor import SceneStateEditor
from talemate.server.websocket_plugin import Plugin
from talemate.util.path import get_path_parent, split_state_path

log = structlog.get_logger("talemate.server.devtools")


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
    target: Literal["debug", "knob"]
    enabled: bool
    label: str | None = None


class GameStatePathLabelPayload(pydantic.BaseModel):
    path: str
    label: str | None = None


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

    def _set_game_state_path_label(self, path: str, label: str | None) -> str:
        label = (label or "").strip()
        if label:
            self.scene.game_state_path_labels[path] = label
        else:
            self.scene.game_state_path_labels.pop(path, None)
        return label

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

        # Re-evaluate gamestate-controlled pins
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
            parent, leaf_key = get_path_parent(
                scene.game_state.variables, parts, create=False
            )
            if parent is None:
                raise ValueError(f"Game state path does not exist: {payload.path}")
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        parent[leaf_key] = payload.value
        await scene.load_active_pins()
        await scene.attempt_auto_save()
        scene.emit_status()

        emit("status", message="Game state variable updated", status="success")
        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state_variable_updated",
                "data": {"path": payload.path, "value": payload.value},
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

    async def _set_game_state_paths(
        self,
        data,
        *,
        attribute: str,
        action: str,
        status_message: str,
    ):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        try:
            payload = GameStatePathsPayload(**data)
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        sanitized_paths = sorted(set(filter(None, payload.paths)))
        setattr(scene, attribute, sanitized_paths)
        scene.game_state_path_labels = {
            path: label
            for path, label in scene.game_state_path_labels.items()
            if path in scene.pinned_game_state_paths
        }
        await scene.attempt_auto_save()
        scene.emit_status()

        emit("status", message=status_message, status="success")

        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": action,
                "data": {"paths": getattr(scene, attribute)},
            }
        )

        await self.signal_operation_done(signal_only=True)

    async def handle_set_game_state_watch_paths(self, data):
        await self._set_game_state_paths(
            data,
            attribute="game_state_watch_paths",
            action="game_state_watch_paths_updated",
            status_message="Game state watch paths updated",
        )

    async def handle_set_game_state_knob_paths(self, data):
        await self._set_game_state_paths(
            data,
            attribute="game_state_knob_paths",
            action="game_state_knob_paths_updated",
            status_message="Game state knob paths updated",
        )

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

        target = {
            "debug": (
                "game_state_watch_paths",
                "game_state_watch_paths_updated",
                "Game state watch paths updated",
            ),
            "knob": (
                "game_state_knob_paths",
                "game_state_knob_paths_updated",
                "Game state knob paths updated",
            ),
        }[payload.target]
        attribute, action, status_message = target
        paths = set(getattr(scene, attribute))
        normalized_path = "/".join(parts)
        if payload.enabled:
            paths.add(normalized_path)
        else:
            paths.discard(normalized_path)

        if "label" in payload.model_fields_set:
            self._set_game_state_path_label(normalized_path, payload.label)

        await self._set_game_state_paths(
            {"paths": list(paths)},
            attribute=attribute,
            action=action,
            status_message=status_message,
        )

    async def handle_set_game_state_path_label(self, data):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No active scene")
            return

        try:
            payload = GameStatePathLabelPayload(**data)
            normalized_path = "/".join(split_state_path(payload.path))
            if normalized_path not in scene.pinned_game_state_paths:
                raise ValueError(f"Game state path is not pinned: {normalized_path}")
        except Exception as exc:
            await self.signal_operation_failed(str(exc))
            return

        label = self._set_game_state_path_label(normalized_path, payload.label)

        await scene.attempt_auto_save()
        scene.emit_status()
        emit("status", message="Game state path label updated", status="success")
        self.websocket_handler.queue_put(
            {
                "type": "devtools",
                "action": "game_state_path_label_updated",
                "data": {"path": normalized_path, "label": label or None},
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
