"""
Allows the in-memory editing of a scene's states.

- world state
- agent state
- game state
- intent state
"""
from typing import TYPE_CHECKING

from .schema import SceneState

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "SceneStateEditor"
]

class SceneStateEditor:
    
    def __init__(self, scene: "Scene"):
        self.scene = scene
        
    def dump(self) -> dict:
        scene: "Scene" = self.scene
        self.state = SceneState(
            world_state=scene.world_state,
            game_state=scene.game_state,
            agent_state=scene.agent_state,
            intent_state=scene.intent_state
        )
        return self.state.model_dump()
    
    def load(self, data: dict):
        state: SceneState = SceneState(**data)
        scene: "Scene" = self.scene
        
        if "world_state" in data:
            scene.world_state = state.world_state
            
        if "game_state" in data:
            scene.game_state = state.game_state
            
        if "agent_state" in data:
            scene.agent_state.update(state.agent_state)
            
        if "intent_state" in data:
            scene.intent_state = state.intent_state