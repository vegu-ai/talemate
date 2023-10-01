from dataclasses import dataclass, field
import isodate

_message_id = 0

def get_message_id():
    global _message_id
    _message_id += 1
    return _message_id

def reset_message_id():
    global _message_id
    _message_id = 0


@dataclass
class SceneMessage:
    
    """
    Base class for all messages that are sent to the scene.
    """
    
    # the mesage itself
    message: str
    
    # the id of the message
    id: int = field(default_factory=get_message_id)
    
    # the source of the message (e.g. "ai", "progress_story", "director")
    source: str = ""
    
    
    def __str__(self):
        return self.message
    
    def __int__(self):
        return self.id
    
    def __len__(self):
        return len(self.message)
    
    def __in__(self, other):
        return (other in self.message)
    
    def __contains__(self, other):
        return (self.message in other)
    
    def __dict__(self):
        return {
            "message": self.message,
            "id": self.id,
            "typ": self.typ,
            "source": self.source,
        }
    
    def __iter__(self):
        return iter(self.message)
        
    def split(self, *args, **kwargs):
        return self.message.split(*args, **kwargs)
    
    def startswith(self, *args, **kwargs):
        return self.message.startswith(*args, **kwargs)
    
    def endswith(self, *args, **kwargs):
        return self.message.endswith(*args, **kwargs)
    
@dataclass
class CharacterMessage(SceneMessage):
    typ = "character"
    source: str = "ai"
    
    def __str__(self):
        return self.message
    
@dataclass
class NarratorMessage(SceneMessage):
    source: str = "progress_story"
    typ = "narrator"
    
@dataclass
class DirectorMessage(SceneMessage):
    typ = "director"


    def __str__(self):
        """
        The director message is a special case and needs to be transformed
        from "Director instructs {charname}:" to "*{charname} inner monologue:"
        """
        
        transformed_message = self.message.replace("Director instructs ", "")
        char_name, message = transformed_message.split(":", 1)
        
        return f"[Story progression instructions for {char_name}: {message}]"
        
@dataclass
class TimePassageMessage(SceneMessage):
    ts: str = "PT0S"
    source: str = "manual"    
    typ = "time"
    
    def __dict__(self):
        return {
            "message": self.message,
            "id": self.id,
            "typ": "time",
            "source": self.source,
            "ts": self.ts,
        }
    
MESSAGES = {
    "scene": SceneMessage,
    "character": CharacterMessage,
    "narrator": NarratorMessage,
    "director": DirectorMessage,
    "time": TimePassageMessage,
}