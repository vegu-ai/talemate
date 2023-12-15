
import os
from typing import TYPE_CHECKING, Any
import pydantic
import structlog

from talemate.prompts.base import Prompt, PrependTemplateDirectories
from talemate.instance import get_agent
from talemate.agents.director import DirectorAgent
if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("game_state")

class Goal(pydantic.BaseModel):
    description: str
    id: int
    status: bool = False
    
class Instructions(pydantic.BaseModel):
    character: dict[str, str] = pydantic.Field(default_factory=dict)
    
class GameState(pydantic.BaseModel):
    variables: dict[str,Any] = pydantic.Field(default_factory=dict)
    goals: list[Goal] = pydantic.Field(default_factory=list)
    instructions: Instructions = pydantic.Field(default_factory=Instructions)
    
    @property
    def director(self) -> DirectorAgent:
        return get_agent('director')
    
    @property
    def scene(self) -> 'Scene':
        return self.director.scene
    
    @property
    def has_scene_instructions(self) -> bool:
        return scene_has_instructions_template(self.scene)
    
    @property
    def game_won(self) -> bool:
        return self.variables.get("__game_won__") == True
    
    @property
    def scene_instructions(self) -> str:
        scene = self.scene
        director = self.director
        client = director.client
        game_state = self
        if scene_has_instructions_template(self.scene):
            with PrependTemplateDirectories([scene.template_dir]):
                prompt = Prompt.get('instructions', {
                    'scene': scene,
                    'max_tokens': client.max_token_length,
                    'game_state': game_state
                })
                
                prompt.client = client
                instructions = prompt.render().strip()
                log.info("Initialized game state instructions", scene=scene, instructions=instructions)
                return instructions
    
    def init(self, scene: 'Scene') -> 'GameState':
        return self
    
    def set_var(self, key: str, value: Any):
        self.variables[key] = value
        
    def has_var(self, key: str) -> bool:
        return key in self.variables
    
    def get_var(self, key: str) -> Any:
        return self.variables[key]
    
    def get_or_set_var(self, key: str, value: Any) -> Any:
        if not self.has_var(key):
            self.set_var(key, value)
        return self.get_var(key)

def scene_has_game_template(scene: 'Scene') -> bool:
    """Returns True if the scene has a game template."""
    game_template_path = os.path.join(scene.template_dir, 'game.jinja2')
    return os.path.exists(game_template_path)

def scene_has_instructions_template(scene: 'Scene') -> bool:
    """Returns True if the scene has an instructions template."""
    instructions_template_path = os.path.join(scene.template_dir, 'instructions.jinja2')
    return os.path.exists(instructions_template_path)
