import contextvars
from typing import TYPE_CHECKING

import nest_asyncio
import structlog

import talemate.game.engine.api as scoped_api
from talemate.client.base import ClientBase
from talemate.emit import emit
from talemate.instance import get_agent
from talemate.exceptions import GenerationCancelled

if TYPE_CHECKING:
    from talemate.agents.director import DirectorAgent
    from talemate.tale_mate import Scene

__all__ = [
    "GameInstructionScope",
    "OpenScopedContext",
    "scoped_context",
]

nest_asyncio.apply()

log = structlog.get_logger("talemate.game.scope")


class ScopedContext:
    def __init__(self, scene: "Scene" = None, client: ClientBase = None):
        self.scene = scene
        self.client = client


scoped_context = contextvars.ContextVar("scoped_context", default=ScopedContext())


class OpenScopedContext:
    def __init__(self, scene: "Scene", client: ClientBase):
        self.scene = scene
        self.context = ScopedContext(scene=scene, client=client)

    def __enter__(self):
        self.token = scoped_context.set(self.context)

    def __exit__(self, *args):
        scoped_context.reset(self.token)


class GameInstructionScope:

    def __init__(
        self,
        director: "DirectorAgent",
        log: object,
        scene: "Scene",
        module_function: callable,
        on_generation_cancelled: callable = None,
    ):
        client = director.client

        def assert_scene_active():
            if not scene.active:
                raise RuntimeError("Scene is not active")

        self.agents = type("", (), {})()
        self.game_state = scoped_api.game_state.create(scene.game_state)
        self.log = scoped_api.log.create(log)
        self.scene = scoped_api.scene.create(scene)
        self.prompt = scoped_api.prompt.create(scene, client)
        self.signals = scoped_api.signals.create()

        self.agents.creator = scoped_api.agent_creator.create(scene)
        self.agents.director = scoped_api.agent_director.create(scene)
        self.agents.narrator = scoped_api.agent_narrator.create(scene)
        self.agents.world_state = scoped_api.agent_world_state.create(scene)
        self.agents.visual = scoped_api.agent_visual.create(scene)
        self.module_function = module_function
        self.on_generation_cancelled = on_generation_cancelled

        # set assert_scene_active as a method on all scoped api objects

        self.game_state.assert_scene_active = assert_scene_active
        self.log.assert_scene_active = assert_scene_active
        self.scene.assert_scene_active = assert_scene_active
        self.prompt.assert_scene_active = assert_scene_active
        self.signals.assert_scene_active = assert_scene_active

        self.agents.creator.assert_scene_active = assert_scene_active
        self.agents.director.assert_scene_active = assert_scene_active
        self.agents.narrator.assert_scene_active = assert_scene_active
        self.agents.world_state.assert_scene_active = assert_scene_active
        self.agents.visual.assert_scene_active = assert_scene_active

    def __call__(self):
        try:
            self.module_function(self)
        except GenerationCancelled as exc:
            if callable(self.on_generation_cancelled):
                self.on_generation_cancelled(self, exc)

    def emit_status(self, status: str, message: str, **kwargs):
        if kwargs:
            emit("status", status=status, message=message, data=kwargs)
        else:
            emit("status", status=status, message=message)
