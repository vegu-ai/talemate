from typing import Callable
from contextvars import ContextVar

import pydantic
import structlog

from talemate.exceptions import SceneInactiveError, GenerationCancelled

__all__ = [
    "assert_active_scene",
    "scene_is_loading",
    "regeneration_context",
    "active_scene",
    "interaction",
    "SceneIsLoading",
    "RegenerationContext",
    "ActiveScene",
    "Interaction",
    "handle_generation_cancelled",
]

log = structlog.get_logger(__name__)


class InteractionState(pydantic.BaseModel):
    act_as: str | None = None
    from_choice: str | None = None
    input: str | None = None
    reset_requested: bool = False
    reset_side_effect: Callable | None = None


scene_is_loading = ContextVar("scene_is_loading", default=None)
regeneration_context = ContextVar("regeneration_context", default=None)
active_scene = ContextVar("active_scene", default=None)
interaction = ContextVar("interaction", default=InteractionState())


def handle_generation_cancelled(exc: GenerationCancelled, *, scene=None):
    from talemate.emit import emit

    scene = scene if scene is not None else active_scene.get()
    if scene is None:
        return
    exc.by_user = exc.by_user or scene.cancel_requested
    scene.cancel_requested = False
    if exc.by_user or exc.reported:
        return
    exc.reported = True
    reason = str(exc) or "Generation stopped before completion."
    details = {
        key: value
        for key, value in {
            "message_id": exc.message_id,
            "view_status": exc.view_status,
            "character": exc.character,
        }.items()
        if value is not None
    }
    log.warning("Generation aborted", reason=reason, **details)
    emit("status", status="warning", message=reason, data=details)


class SceneIsLoading:
    def __init__(self, scene):
        self.scene = scene

    def __enter__(self):
        self.scene.loading = True
        self.token = scene_is_loading.set(self.scene)

    def __exit__(self, *args):
        scene_is_loading.reset(self.token)
        self.scene.loading = False


class ActiveScene:
    def __init__(self, scene):
        self.scene = scene

    def __enter__(self):
        self.token = active_scene.set(self.scene)

    def __exit__(self, *args):
        active_scene.reset(self.token)


class RegenerationContext:
    def __init__(self, scene, direction=None, method="replace", message: str = None):
        self.scene = scene
        self.direction = direction
        self.method = method
        self.message = message
        log.debug(
            "RegenerationContext",
            scene=scene,
            direction=direction,
            method=method,
            message=message,
        )

    def __enter__(self):
        self.token = regeneration_context.set(self)

    def __exit__(self, *args):
        regeneration_context.reset(self.token)


class Interaction:
    def __init__(self, **kwargs):
        self.state = InteractionState(**kwargs)

    def __enter__(self) -> InteractionState:
        self.token = interaction.set(self.state)
        return self.state

    def __exit__(self, *args):
        interaction.reset(self.token)


def assert_active_scene(scene: object):
    if not active_scene.get():
        raise SceneInactiveError("Scene is not active")

    if active_scene.get() != scene:
        raise SceneInactiveError("Scene has changed")
