from typing import TYPE_CHECKING, get_args

from .core import (
    Node,
    GraphState,
    InputValueError,
    UNRESOLVED,
    PropertyField,
)
from .registry import register
import talemate.scene_message as scene_message

if TYPE_CHECKING:
    from talemate.character import Character


@register("scene/message/CharacterMessage")
class CharacterMessage(Node):
    """
    Creates a character message from a character and a message

    Inputs:

    - character: The character object
    - message: The message to send
    - source: The source of the message - player or ai, so whether the message is result of user input or AI generated
    - from_choice: For player messages this indicates that the message was generated from a choice selection, for ai sourced messages this indicates the instruction that was followed

    Properties:

    - source: The source of the message

    Outputs:

    - message: The message object (this is a scene_message.CharacterMessage instance)
    """

    class Fields:
        source = PropertyField(
            name="source",
            description="The source of the message",
            type="str",
            default="player",
            choices=[
                "player",
                "ai",
            ],
        )

    def __init__(self, title="Character Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("from_choice", socket_type="str", optional=True)

        self.set_property("source", "player")

        self.add_output("message", socket_type="message_object")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        message = self.get_input_value("message")
        source = self.get_input_value("source")
        from_choice = self.get_input_value("from_choice")

        extra = {}

        if isinstance(from_choice, str):
            extra["from_choice"] = from_choice

        # Capture the character's current avatar at message creation time
        # (not default avatar - messages only use current_avatar if set)
        if character.current_avatar:
            extra["asset_id"] = character.current_avatar
            extra["asset_type"] = "avatar"

        message = scene_message.CharacterMessage(
            scene_message.CharacterMessage.with_name_prefix(character.name, message),
            source=source,
            **extra,
        )

        self.set_output_values({"message": message})


@register("scene/message/NarratorMessage")
class NarratorMessage(Node):
    """
    Creates a narrator message

    Inputs:

    - message: The message to send
    - source: The source of the message - player or ai, so whether the message is result of user input or AI generated
    - meta: A dictionary of meta information to attach to the message. This will generally be arguments and function name that was called on the narrator agent to generate the message and will be used when regenerating the message.

    Properties:

    - source: The source of the message

    Outputs:

    - message: The message object (this is a scene_message.NarratorMessage instance)
    """

    class Fields:
        source = PropertyField(
            name="source",
            description="The source of the message",
            type="str",
            default="ai",
            choices=[
                "player",
                "ai",
            ],
        )

    def __init__(self, title="Narrator Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("meta", socket_type="dict", optional=True)

        self.set_property("source", "ai")

        self.add_output("message", socket_type="message_object")

    async def run(self, state: GraphState):
        message = self.get_input_value("message")
        source = self.get_input_value("source")
        meta = self.get_input_value("meta")

        extra = {}

        if meta and isinstance(meta, dict):
            extra["meta"] = meta

        message = scene_message.NarratorMessage(message, source=source, **extra)

        self.set_output_values({"message": message})


@register("scene/message/DirectorMessage")
class DirectorMessage(Node):
    """
    Creates a director message

    Inputs:

    - message: The message to send
    - source: The source of the message - player or ai, so whether the message is result of user input or AI generated
    - meta: A dictionary of meta information to attach to the message. Can hold the character name that the message is related to.
    - character: The character object that the message is related to

    Properties:

    - source: The source of the message
    - action: Describes the director action

    Outputs:

    - message: The message object (this is a scene_message.DirectorMessage instance)
    """

    class Fields:
        source = PropertyField(
            name="source",
            description="The source of the message",
            type="str",
            default="ai",
            choices=[
                "player",
                "ai",
            ],
        )

        action = PropertyField(
            name="action",
            description="Describes the director action",
            type="str",
            default="actor_instruction",
            choices=[
                "actor_instruction",
                "user_direction",
            ],
        )

        subtype = PropertyField(
            name="subtype",
            description="The subtype of the director message, used for further categorization of the message",
            type="str",
            default=UNRESOLVED,
            choices=[
                "function_call",
                "user_direction",
            ],
        )

    def __init__(self, title="Director Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("meta", socket_type="dict", optional=True)
        self.add_input("character", socket_type="character", optional=True)
        self.add_input("action", socket_type="str", optional=True)
        self.add_input("subtype", socket_type="str", optional=True)

        self.set_property("source", "ai")
        self.set_property("action", "actor_instruction")
        self.set_property("subtype", UNRESOLVED)

        self.add_output("message", socket_type="message_object")
        self.add_output("source", socket_type="str")
        self.add_output("meta", socket_type="dict")
        self.add_output("character", socket_type="character")
        self.add_output("action", socket_type="str")
        self.add_output("subtype", socket_type="str")

    async def run(self, state: GraphState):
        message = self.normalized_input_value("message")
        source = self.normalized_input_value("source")
        action = self.normalized_input_value("action")
        meta = self.normalized_input_value("meta")
        subtype = self.normalized_input_value("subtype")
        character: "Character" = self.normalized_input_value("character")

        extra = {}

        if meta and isinstance(meta, dict):
            extra["meta"] = meta

        message = scene_message.DirectorMessage(
            message, source=source, action=action, subtype=subtype, **extra
        )

        if character is not None:
            message.set_meta(character=character.name)

        self.set_output_values(
            {
                "message": message,
                "source": source,
                "meta": meta,
                "character": character,
                "action": action,
                "subtype": subtype,
            }
        )


@register("scene/message/UnpackMeta")
class UnpackMessageMeta(Node):
    """
    Unpacks a message meta dictionary
    into arguments

    Inputs:

    - meta: The meta dictionary

    Outputs:

    - agent_name: The agent name
    - function_name: The function name
    - arguments: The arguments dictionary
    """

    def __init__(self, title="Unpack Message Meta", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("meta", socket_type="dict")
        self.add_output("agent_name", socket_type="str")
        self.add_output("function_name", socket_type="str")
        self.add_output("arguments", socket_type="dict")

    async def run(self, state: GraphState):
        meta = self.get_input_value("meta")

        self.set_output_values(
            {
                "agent_name": meta["agent"],
                "function_name": meta["function"],
                "arguments": meta.get("arguments", {}).copy(),
            }
        )


@register("scene/message/AddMessageVersion")
class AddMessageVersion(Node):
    """
    Append a new version to a message's revision stack and make it the
    active canonical.

    Typical use: hook ``game_loop_new_message`` (or ``push_history``),
    rewrite the message body, and have the prior canonical preserved on
    the stack so the user can navigate back to it via the revision
    arrows in chat. The prior version stays at its existing index with
    its own source/reason intact — this node only appends and shifts
    the active pointer.

    Only valid for message types the revision UI can walk:
    ``CharacterMessage``, ``NarratorMessage``,
    ``ContextInvestigationMessage`` (i.e. anything with
    ``_supports_versions = True``). Anything else raises
    ``InputValueError`` — filter the message type before reaching this
    node.

    For ``CharacterMessage``, ``new_text`` is auto-prefixed with
    ``"Name: "`` if missing, matching the convention in
    ``scene/message/CharacterMessage``.

    Inputs:

    - message: The SceneMessage to append a version to (required)
    - new_text: The new canonical text (required)
    - source: Version source label (optional, overrides property)
    - reason: Free-form annotation rendered alongside the source badge (optional)

    Properties:

    - source: Version source label
    - reason: Default reason if no input is connected

    Outputs:

    - message: The same SceneMessage instance (post-append)
    - new_text: Passthrough of new_text
    - source: Passthrough of source actually used
    - reason: Passthrough of reason actually used
    - version: The MessageVersion instance that was appended
    """

    class Fields:
        source = PropertyField(
            name="source",
            description="The source label attached to the new version entry",
            type="str",
            default="custom",
            choices=list(get_args(scene_message.VersionSource)),
        )

        reason = PropertyField(
            name="reason",
            description="Free-form annotation rendered alongside the source badge in the revision navigator",
            type="str",
            default="",
        )

    def __init__(self, title="Add Message Version", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("message", socket_type="message_object")
        self.add_input("new_text", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("reason", socket_type="str", optional=True)

        self.set_property("source", "custom")
        self.set_property("reason", "")

        self.add_output("state")
        self.add_output("message", socket_type="message_object")
        self.add_output("new_text", socket_type="str")
        self.add_output("source", socket_type="str")
        self.add_output("reason", socket_type="str")
        self.add_output("version", socket_type="any")

    async def run(self, state: GraphState):
        state_in = self.get_input_value("state")
        message = self.require_input("message")
        new_text = self.require_input("new_text")
        source = self.normalized_input_value("source")
        reason = self.normalized_input_value("reason")

        if not isinstance(message, scene_message.SceneMessage):
            raise InputValueError(
                self, "message", "Input is not a SceneMessage instance"
            )

        if not message._supports_versions:
            raise InputValueError(
                self,
                "message",
                f"Versions are only supported for character, narrator, and context_investigation messages — got {type(message).__name__}",
            )

        # Empty / whitespace-only reason → drop to None so the frontend
        # renders just the source badge without a trailing separator.
        reason_value = (reason.strip() or None) if isinstance(reason, str) else None

        if (
            isinstance(message, scene_message.CharacterMessage)
            and message.character_name
        ):
            new_text = scene_message.CharacterMessage.with_name_prefix(
                message.character_name, new_text
            )

        version = message.append_version(new_text, source=source, reason=reason_value)

        self.set_output_values(
            {
                "state": state_in,
                "message": message,
                "new_text": new_text,
                "source": source,
                "reason": reason_value,
                "version": version,
            }
        )


@register("scene/message/ToggleMessageContextVisibility")
class ToggleMessageContextVisibility(Node):
    """
    Hide or show a message. Hidden messages are not displayed to the AI.

    Inputs:

    - message: The message object

    Properties:

    - hidden: Whether the message is hidden

    Outputs:

    - message: The message object
    """

    class Fields:
        hidden = PropertyField(
            name="hidden",
            description="Whether the message is hidden",
            type="bool",
            default=False,
        )

    def __init__(self, title="Toggle Message Context Visibility", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message", socket_type="message_object")

        self.set_property("hidden", False)

        self.add_output("message", socket_type="message_object")

    async def run(self, state: GraphState):
        message = self.require_input("message")
        hidden = self.get_property("hidden")

        if hidden:
            message.hide()
        else:
            message.unhide()

        self.set_output_values({"message": message})
