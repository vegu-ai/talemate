__all__ = [
    'NoPlayerCharacter',
    'UnknownAgentAction',
    'UnknownCharacter',
    'SceneInactive'
]

class NoPlayerCharacter(KeyError):
    pass

class UnknownAgentAction(KeyError):
    def __init__(self, agent_name:str, action_name:str):
        super().__init__(f"Unknown action '{action_name}' for agent '{agent_name}'")
    
class UnknownCharacter(KeyError):
    def __init__(self, character_name:str):
        super().__init__(f"Unknown character '{character_name}'")
        
class SceneInactive(IOError):
    def __init__(self):
        super().__init__("The scene is inactive")