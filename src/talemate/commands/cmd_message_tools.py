from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register

__all__ = ["CmdFixContinuityErrors"]


@register
class CmdFixContinuityErrors(TalemateCommand):
    """
    Calls the editor agent's `check_continuity_errors` method to fix continuity errors in the
    specified message (by id).

    Will replace the message and re-emit the message.
    """

    name = "fixmsg_continuity_errors"
    description = "Fixes continuity errors in the specified message"
    aliases = ["fixmsg_ce"]

    async def run(self):

        message_id = int(self.args[0]) if self.args else None

        if not message_id:
            self.system_message("No message id specified")
            return True

        message = self.scene.get_message(message_id)

        if not message:
            self.system_message(f"Message not found: {message_id}")
            return True

        editor = self.scene.get_helper("editor").agent

        if hasattr(message, "character_name"):
            character = self.scene.get_character(message.character_name)
        else:
            character = None

        fixed_message = await editor.check_continuity_errors(
            str(message), character, force=True
        )

        self.scene.edit_message(message_id, fixed_message)
