from contextvars import ContextVar
import structlog

__all__ = [
    "scene_is_loading",
    "rerun_context",
    "active_scene",
    "SceneIsLoading",
    "RerunContext",
    "ActiveScene",
]

log = structlog.get_logger(__name__)

scene_is_loading = ContextVar("scene_is_loading", default=None)
rerun_context = ContextVar("rerun_context", default=None)
active_scene = ContextVar("active_scene", default=None)

class SceneIsLoading:
    def __init__(self, scene):
        self.scene = scene

    def __enter__(self):
        self.token = scene_is_loading.set(self.scene)

    def __exit__(self, *args):
        scene_is_loading.reset(self.token)


class ActiveScene:
    def __init__(self, scene):
        self.scene = scene

    def __enter__(self):
        self.token = active_scene.set(self.scene)

    def __exit__(self, *args):
        active_scene.reset(self.token)

class RerunContext:
    def __init__(self, scene, direction=None, method="replace", message: str = None):
        self.scene = scene
        self.direction = direction
        self.method = method
        self.message = message
        log.debug(
            "RerunContext",
            scene=scene,
            direction=direction,
            method=method,
            message=message,
        )

    def __enter__(self):
        self.token = rerun_context.set(self)

    def __exit__(self, *args):
        rerun_context.reset(self.token)
