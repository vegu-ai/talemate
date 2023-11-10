from contextvars import ContextVar

__all__ = [
    "scene_is_loading",
    "SceneIsLoading",
]

scene_is_loading = ContextVar("scene_is_loading", default=None)

class SceneIsLoading:
    
    def __init__(self, scene):
        self.scene = scene
    
    def __enter__(self):
        self.token = scene_is_loading.set(self.scene)
    
    def __exit__(self, *args):
        scene_is_loading.reset(self.token)
        