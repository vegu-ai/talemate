"""
Scoped API for emitting signals

- status(status:str, message:str, as_scene_message:bool=False): emits a status message to the user
"""

from talemate.game.engine.api.base import ScopedAPI
import talemate.game.engine.api.schema as schema
from talemate.emit import emit

__all__ = [
    "create"
]

def create() -> "ScopedAPI":
    class API(ScopedAPI):
        
        def status(self, status:str, message:str, as_scene_message:bool=False):
            """ 
            Emits a status message to the scene
            
            Arguments:
            
            - status: str - The status of the message
            - message: str - The message to send
            - as_scene_message: bool - Whether the message should be displayed as a scene message. If false
                a little popup will be displayed on top of the scene
            """
            
            validated = schema.StatusEmission(status=status, message=message, as_scene_message=as_scene_message)
            emit(
                "status",
                message=validated.message,
                status=validated.status,
                data={"as_scene_message": validated.as_scene_message}
            )
            
    return API()