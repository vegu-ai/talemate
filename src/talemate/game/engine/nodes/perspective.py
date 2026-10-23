from typing import TYPE_CHECKING

from talemate.character import character_name
from talemate.context import active_scene
from talemate.knowledge.message_views import edit_character_view, message_view
from talemate.knowledge.mode import character_knowledge_enabled

from .core import GraphState, InputValueError, Node, PropertyField
from .registry import register

if TYPE_CHECKING:
    from talemate.scene_message import SceneMessage
    from talemate.tale_mate import Scene

__all__ = [
    "GetMessageView",
    "SetMessageView",
]


class _MessageViewNode(Node):
    def setup(self):
        self.add_input("message", socket_type="message_object", optional=True)
        self.add_input("message_id", socket_type="int", optional=True)
        self.add_input("character", socket_type="str,character")
        self.set_property("message_id", 0)

    def resolve_message(self, scene: "Scene") -> "SceneMessage":
        message = self.normalized_input_value("message")
        if message is not None:
            return message
        message_id = self.normalized_input_value("message_id")
        message = scene.get_message(message_id) if message_id else None
        if message is None:
            raise InputValueError(
                self, "message_id", f"Message {message_id} is not in the history."
            )
        return message


@register("scene/perspective/GetMessageView")
class GetMessageView(_MessageViewNode):
    """
    One character's view of a message in a Character Perspectives scene:
    the account of the passage that character's memories and history use.
    Outside Character Perspectives the status is `unavailable`.

    Status values: ready, omitted (the character perceives nothing of it),
    pending, failed, unavailable, running (analysis runs now), deferred (an
    unkept version is shown), unsupported (the message type has no views),
    not_present.

    Inputs:

    - message: the message (or give message_id)
    - message_id: the message id (or give message)
    - character: character name or character

    Outputs:

    - message_id: the message id
    - character: the character name
    - status: the view status
    - text: the view text, or None
    - editable: True when Set Message View can replace it now
    - reason: why the view cannot be edited, or None
    """

    def __init__(self, title="Get Message View", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_output("message_id", socket_type="int")
        self.add_output("character", socket_type="str")
        self.add_output("status", socket_type="str")
        self.add_output("text", socket_type="str")
        self.add_output("editable", socket_type="bool")
        self.add_output("reason", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        message = self.resolve_message(scene)
        character = character_name(self.require_input("character"))
        view = message_view(scene, message, character)
        self.set_output_values(
            {
                "message_id": message.id,
                "character": character,
                "status": view.status,
                "text": view.text,
                "editable": view.editable,
                "reason": view.reason,
            }
        )


@register("scene/perspective/SetMessageView")
class SetMessageView(_MessageViewNode):
    """
    Replace one character's view of a message by hand, as the perspective
    panel does. Empty text means the character perceives nothing of it.
    Later views built on this one stay valid. Only in Character
    Perspectives scenes, and only while the view is editable (see Get
    Message View).

    Inputs:

    - state: graph state (passthrough)
    - message: the message (or give message_id)
    - message_id: the message id (or give message)
    - character: character name or character
    - text: the new view text

    Outputs:

    - state: graph state
    - changed: True when the stored view changed
    - status: the view status after the change
    - text: the view text after the change
    """

    class Fields:
        text = PropertyField(
            name="text",
            description="The new view text; empty omits the message for the character",
            type="text",
            default="",
        )

    def __init__(self, title="Set Message View", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        super().setup()
        self.add_input("text", socket_type="str", optional=True)
        self.set_property("text", "")
        self.add_output("state")
        self.add_output("changed", socket_type="bool")
        self.add_output("status", socket_type="str")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        if not character_knowledge_enabled(scene):
            raise InputValueError(
                self, "message", "Character perspectives are off in this scene."
            )
        message = self.resolve_message(scene)
        character = character_name(self.require_input("character"))
        text = self.normalized_input_value("text") or ""
        try:
            edit = await edit_character_view(scene, message, character, text)
        except ValueError as exc:
            raise InputValueError(self, "message", str(exc)) from exc
        if edit.changed:
            scene.emit_status()
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "changed": edit.changed,
                "status": edit.view.status,
                "text": edit.view.text,
            }
        )
