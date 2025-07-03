from typing import TYPE_CHECKING

from talemate.world_state.templates.base import Template, register

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["SceneType"]


@register("scene_type")
class SceneType(Template):
    """
    Template for scene types.

    This template simply provides a way to store scene type definitions
    that can be directly applied to a scene without AI generation.
    """

    name: str
    description: str
    instructions: str | None = None
    template_type: str = "scene_type"

    def to_scene_type_dict(self):
        """Convert the template to a scene type dictionary format"""
        scene_type_id = self.name.lower().replace(" ", "_")

        return {
            "id": scene_type_id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
        }

    def apply_to_scene(self, scene: "Scene") -> dict:
        """
        Apply this template to create a scene type in the scene

        Returns the created scene type dict
        """
        scene_type = self.to_scene_type_dict()

        if scene and hasattr(scene, "scene_intent") and scene.scene_intent:
            scene.scene_intent.scene_types[scene_type["id"]] = scene_type

        return scene_type
