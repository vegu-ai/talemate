from __future__ import annotations
from typing import TYPE_CHECKING, Any
import dataclasses

if TYPE_CHECKING:
    from talemate import Scene
    
import structlog

__all__ = ["AutomatedAction", "register", "initialize_for_scene"]

log = structlog.get_logger("talemate.automated_action")

AUTOMATED_ACTIONS = {}

def initialize_for_scene(scene:Scene):
    
    for uid, config in AUTOMATED_ACTIONS.items():
        scene.automated_actions[uid] = config.cls(
            scene,
            uid=uid,
            frequency=config.frequency,
            call_initially=config.call_initially,
            enabled=config.enabled
        )


@dataclasses.dataclass
class AutomatedActionConfig:
    uid:str
    cls:AutomatedAction
    frequency:int=5
    call_initially:bool=False
    enabled:bool=True
    
class register:
    
    def __init__(self, uid:str, frequency:int=5, call_initially:bool=False, enabled:bool=True):
        self.uid = uid
        self.frequency = frequency
        self.call_initially = call_initially
        self.enabled = enabled
        
    def __call__(self, action:AutomatedAction):
        AUTOMATED_ACTIONS[self.uid] = AutomatedActionConfig(
            self.uid, 
            action, 
            frequency=self.frequency, 
            call_initially=self.call_initially, 
            enabled=self.enabled
        )
        return action
    
class AutomatedAction:
    """
    An action that will be executed every n turns
    """
    
    def __init__(self, scene:Scene, frequency:int=5, call_initially:bool=False, uid:str=None, enabled:bool=True):
        self.scene = scene
        self.enabled = enabled
        self.frequency = frequency
        self.turns = 1
        self.uid = uid
        if call_initially:
            self.turns = frequency
        
    async def __call__(self):
        
        log.debug("automated_action", uid=self.uid, enabled=self.enabled, frequency=self.frequency, turns=self.turns)
        
        if not self.enabled:
            return False
        
        if self.turns % self.frequency == 0:
            result = await self.action()
            log.debug("automated_action", result=result)
            if result is False:
                # action could not be performed at this turn, we will try again next turn
                return False
        self.turns += 1
    
    
    async def action(self) -> Any:
        """
        Override this method to implement your action.
        """
        raise NotImplementedError()