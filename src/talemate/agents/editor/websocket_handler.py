import pydantic
import structlog
from typing import TYPE_CHECKING

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.scene_message import CharacterMessage
from talemate.status import background_task
from talemate.agents.editor.revision import RevisionContext, RevisionInformation

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

    @background_task("Revising message")
    async def handle_request_revision(self, data: dict):
        """
        Generate clickable actions for the user
        """

        editor = self.editor
        scene: "Scene" = self.scene

        if not editor.revision_enabled:
            raise Exception("Revision is not enabled")

        payload = RevisionPayload(**data)
        message = scene.get_message(payload.message_id)

        character = None

        if isinstance(message, CharacterMessage):
            character = scene.get_character(message.character_name)

        if not message:
            raise Exception("Message not found")

        original = message.message

        with RevisionContext(message.id):
            info = RevisionInformation(
                text=original,
                character=character,
            )
            revised = await editor.revision_revise(info)
            if isinstance(message, CharacterMessage):
                revised = CharacterMessage.with_name_prefix(character.name, revised)

        # Append the revised text as a new version so the frontend's
        # navigator can step between the prior canonical and the revision.
        # No-op revisions don't touch the message and surface a status so
        # the user knows the action completed without effect.
        #
        # Either way, post an `operation_done` envelope so the frontend can
        # clear the per-message "regenerating" spinner — the happy path also
        # clears on the `message_edited` echo, but the no-op path has no
        # other completion signal.
        if revised != original:
            scene.append_message_version(message.id, revised, source="revision")
            await self.signal_operation_done(signal_only=True)
        else:
            await self.signal_operation_done(
                signal_only=True,
                emit_status_message={
                    "message": "Editor revision produced no changes",
                    "status": "info",
                },
            )
