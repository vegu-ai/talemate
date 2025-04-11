from typing import TYPE_CHECKING
import pydantic

from talemate.world_state import WorldState
from talemate.game.state import GameState

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


__all__ = [
    'SceneType',
    'ScenePhase',
    'SceneIntent',
    'SceneState'
]

def make_default_types() -> list["SceneType"]:
    return {
        "roleplay": SceneType(
            id="roleplay",
            name="Roleplay",
            description="Freeform dialogue between one or more characters with occasional narration.",
        )
    }
    
def make_default_phase() -> "ScenePhase":
    default_type = make_default_types().get("roleplay")
    return ScenePhase(
        scene_type=default_type.id
    )
    
class SceneType(pydantic.BaseModel):
    id: str
    name: str
    description: str
    instructions: str | None = None

class ScenePhase(pydantic.BaseModel):
    scene_type: str
    intent: str | None = None
    
class SceneIntent(pydantic.BaseModel):
    scene_types: dict[str, SceneType] | None = pydantic.Field(default_factory=make_default_types)
    intent: str | None = None
    phase: ScenePhase | None = pydantic.Field(default_factory=make_default_phase)
    start: int = 0
    
    @property
    def current_scene_type(self) -> SceneType:
        return self.scene_types[self.phase.scene_type]
    
    @property
    def active(self) -> bool:
        return (self.intent or self.phase)
    
    def get_scene_type(self, scene_type_id: str) -> SceneType:
        return self.scene_types[scene_type_id]
    
    def set_phase(self, scene:"Scene", scene_type_id: str, intent: str = None) -> ScenePhase:
        
        if scene_type_id not in self.scene_types:
            raise ValueError(f"Invalid scene type: {scene_type_id}")
        
        self.phase = ScenePhase(
            scene_type=scene_type_id, 
            intent=intent,
            start=scene.history[-1].id if scene.history else 0
        )
        return self.phase
    
class SceneState(pydantic.BaseModel):
    world_state: "WorldState | None" = None
    game_state: "GameState | None" = None
    agent_state: dict | None = None
    intent_state: SceneIntent | None = None
    
    def model_dump(self, **kwargs):
        return super().model_dump(exclude_none=True)   