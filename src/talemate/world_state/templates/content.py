from typing import TYPE_CHECKING
from talemate.world_state.templates.base import Template, register, log
import random

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    
__all__ = [
    "Spices",
    "WritingStyle"
]
    
@register("spices")
class Spices(Template):
    spices: list[str]
    description: str | None = None
    
    def render(self, scene: "Scene", character_name: str):
        spice = random.choice(self.spices)
        
        return self.formatted(
            "instructions", scene, character_name, spice=spice
        )
    
@register("writing_style")
class WritingStyle(Template):
    description: str | None = None
    
    def render(self, scene: "Scene", character_name: str):
        return self.formatted(
            "instructions", scene, character_name
        )