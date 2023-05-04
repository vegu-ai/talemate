import json

from talemate.scene_message import SceneMessage

class SceneEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, SceneMessage):
            return obj.__dict__()
        return super().default(obj)
    
    

