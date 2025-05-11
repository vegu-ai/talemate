import pydantic
import structlog
from typing import TYPE_CHECKING

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.status import set_loading
from talemate.scene_message import CharacterMessage
from talemate.agents.editor.revision import RevisionContext

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "EditorWebsocketHandler",
]

log = structlog.get_logger("talemate.server.editor")

class RevisionPayload(pydantic.BaseModel):
    message_id: int

class EditorWebsocketHandler(Plugin):
    """
    Handles editor actions
    """
    
    router = "editor"
    
    @property
    def editor(self):
        return get_agent("editor")
    
    async def handle_request_revision(self, data: dict):
        """
        Generate clickable actions for the user
        """
        
        editor = self.editor
        scene:"Scene" = self.scene
        
        if not editor.revision_enabled:
            raise Exception("Revision is not enabled")
        
        payload = RevisionPayload(**data)
        message = scene.get_message(payload.message_id)
        
        character = None
        
        if isinstance(message, CharacterMessage):
            character = scene.get_character(message.character_name)
        
        if not message:
            raise Exception("Message not found")
        
        with RevisionContext(message.id):
            revised = await editor.revision_revise(message.message, character=character)
        
        scene.edit_message(message.id, revised)