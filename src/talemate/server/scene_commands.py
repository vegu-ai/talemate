"""
Websocket plugin for the scene tools command menu.

Exposes the command modules registered by the active scene loop:

- ``request_catalog``: the current command catalog, on demand.
- ``run``: run a command by name with its arguments.

The catalog is also pushed unprompted whenever the scene loop (re)registers
its commands, so the menu stays in sync with node module edits.
"""

import pydantic
import structlog

import talemate.emit.async_signals as async_signals
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphState, NodeBase
from talemate.game.engine.nodes.scene import (
    SceneCommandsCatalogEvent,
    resolve_node_command,
)
from talemate.server.websocket_plugin import Plugin
from talemate.status import background_task

log = structlog.get_logger("talemate.server.scene_commands")

__all__ = ["SceneCommandsPlugin"]


class RunPayload(pydantic.BaseModel):
    name: str
    args: dict = pydantic.Field(default_factory=dict)
    request_id: str | None = None


class SceneCommandsPlugin(Plugin):
    router = "scene_commands"

    def connect(self):
        async_signals.get("scene_commands_catalog").connect(self.handle_catalog_event)

    def disconnect(self):
        async_signals.get("scene_commands_catalog").disconnect(
            self.handle_catalog_event
        )

    @property
    def loop_state(self) -> GraphState | None:
        scene = self.scene
        if not scene:
            return None
        # the graph of the environment we are in - `active_node_graph` would
        # keep serving a stale game loop after a switch to creative
        if scene.environment == "creative":
            graph = getattr(scene, "creative_node_graph", None)
        else:
            graph = getattr(scene, "node_graph", None)
        return getattr(graph, "_state", None)

    def send_catalog(self, catalog: list[dict]):
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "catalog",
                "data": {"commands": catalog},
            }
        )

    async def handle_catalog_event(self, event: SceneCommandsCatalogEvent):
        self.send_catalog(event.catalog)

    async def handle_request_catalog(self, data: dict):
        state = self.loop_state
        self.send_catalog(state.data.get("_command_catalog") or [] if state else [])

    async def handle_run(self, data: dict):
        # refusals stay out of the background task: its success path emits an
        # idle status clear that would wipe the error snackbar on arrival
        payload = RunPayload(**data)

        if not self.websocket_handler.waiting_for_input:
            return await self.signal_operation_failed(
                "Scene is not waiting for input",
                request_id=payload.request_id,
                failed_action="run",
            )

        state = self.loop_state

        if not state:
            return await self.signal_operation_failed(
                "No active scene loop",
                request_id=payload.request_id,
                failed_action="run",
            )

        # resolving a module reads the scene's node definitions, so this needs
        # the scene context just like the execution does
        with ActiveScene(self.scene):
            command_node = resolve_node_command(state, payload.name)

        if not command_node:
            return await self.signal_operation_failed(
                f"Unknown command: {payload.name}",
                request_id=payload.request_id,
                failed_action="run",
            )

        # the task is returned so `Plugin.handle` can attach its
        # error/cancel envelope callback
        return await self._execute(command_node, state, payload)

    @background_task("Running command")
    async def _execute(
        self, command_node: type[NodeBase], state: GraphState, payload: RunPayload
    ):
        # own the scene context instead of inheriting whatever the dispatching
        # frame happened to have set
        with ActiveScene(self.scene):
            await command_node().execute_command(state, **(payload.args or {}))

            # the command is awaited inside the background task - this
            # acknowledges completion, not dispatch
            await self.signal_operation_done(
                signal_only=True, request_id=payload.request_id
            )
