import structlog
import asyncio
from typing import TYPE_CHECKING, ClassVar
from .core import (
    Loop,
    Node,
    GraphState,
    UNRESOLVED,
    LoopBreak,
    LoopContinue,
    NodeVerbosity,
    InputValueError,
    PropertyField,
    Trigger,
)
import dataclasses
from .registry import register, get_nodes_by_base_type, get_node
from .event import connect_listeners, disconnect_listeners
import talemate.events as events
from talemate.emit import wait_for_input
from talemate.exceptions import ActedAsCharacter, AbortWaitForInput, GenerationCancelled
from talemate.context import active_scene, InteractionState
from talemate.instance import get_agent, AGENTS
from talemate.character import (
    activate_character,
    deactivate_character,
    Character,
)
import talemate.scene_message as scene_message
import talemate.emit.async_signals as async_signals
from talemate.util.colors import random_color


if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.nodes.scene")

async_signals.register(
    "scene_loop_start_cycle",
    "scene_loop_end_cycle",
    "scene_loop_error",
    "scene_loop_init",
    "scene_loop_init_after",
)


@dataclasses.dataclass
class SceneLoopEvent(events.Event):
    scene: "Scene"
    event_type: str


@register("scene/GetSceneState")
class GetSceneState(Node):
    """
    Gets some basic information about the scene

    Outputs:

    - characters: A list of characters in the scene
    - active: Whether the scene is active
    - auto_save: Whether auto save is enabled
    - auto_backup: Whether auto backup is enabled
    - auto_progress: Whether auto progress is enabled
    - scene: The scene instance
    """

    def __init__(self, title="Get Scene State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        # scene state
        self.add_output("characters", socket_type="list")

        # scene settings
        self.add_output("active", socket_type="bool")
        self.add_output("auto_save", socket_type="bool")
        self.add_output("auto_progress", socket_type="bool")
        self.add_output("scene", socket_type="scene")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        self.set_output_values(
            {
                "characters": scene.characters,
                "active": scene.active,
                "auto_save": scene.auto_save,
                "auto_progress": scene.auto_progress,
                "scene": scene,
            }
        )


@register("scene/MakeCharacter")
class MakeCharacter(Node):
    """
    Make a character

    Inputs:

    - name: The name of the character
    - description: The description of the character
    - color: The color of the character name
    - base_attributes: The base attributes of the character
    - is_player: Whether the character is the player character
    - add_to_scene: Whether to add the character to the scene
    - is_active: Whether the character is active

    Properties:

    - name: The name of the character
    - description: The description of the character
    - color: The color of the character name
    - base_attributes: The base attributes of the character
    - is_player: Whether the character is the player character
    - add_to_scene: Whether to add the character to the scene
    - is_active: Whether the character is active

    Outputs:

    - character: The character object
    - actor: The actor object
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the character",
            type="str",
            default=UNRESOLVED,
        )

        description = PropertyField(
            name="description",
            description="The description of the character",
            type="text",
            default="",
        )

        color = PropertyField(
            name="color",
            description="The color of the character name",
            type="color",
            default=UNRESOLVED,
        )

        base_attributes = PropertyField(
            name="base_attributes",
            description="The base attributes of the character",
            type="dict",
            default=UNRESOLVED,
        )

        is_player = PropertyField(
            name="is_player",
            description="Whether the character is the player character",
            type="bool",
            default=False,
        )

        add_to_scene = PropertyField(
            name="add_to_scene",
            description="Whether to add the character to the scene",
            type="bool",
            default=True,
        )

        is_active = PropertyField(
            name="is_active",
            description="Whether the character is active",
            type="bool",
            default=True,
        )

    def __init__(self, title="Make Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("name", socket_type="str")
        self.add_input("description", socket_type="text", optional=True)
        self.add_input("color", socket_type="color", optional=True)
        self.add_input("base_attributes", socket_type="dict", optional=True)
        self.add_input("is_player", socket_type="bool", optional=True)
        self.add_input("add_to_scene", socket_type="bool", optional=True)
        self.add_input("is_active", socket_type="bool", optional=True)

        self.set_property("name", UNRESOLVED)
        self.set_property("description", "")
        self.set_property("color", UNRESOLVED)
        self.set_property("base_attributes", UNRESOLVED)
        self.set_property("is_player", False)
        self.set_property("add_to_scene", True)
        self.set_property("is_active", True)

        self.add_output("character", socket_type="character")
        self.add_output("actor", socket_type="actor")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        name = self.require_input("name")
        description = self.normalized_input_value("description")
        color = self.normalized_input_value("color")
        base_attributes = self.normalized_input_value("base_attributes")
        is_player = self.normalized_input_value("is_player")
        add_to_scene = self.normalized_input_value("add_to_scene")
        is_active = self.normalized_input_value("is_active")

        if not color:
            color = random_color()

        character = scene.Character(
            name=name,
            description=description,
            color=color,
            base_attributes=base_attributes,
            is_player=is_player,
        )

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Make character", character=character)

        self.set_output_values({"character": character})

        if is_player:
            ActorCls = scene.Player
        else:
            ActorCls = scene.Actor

        actor = ActorCls(character, get_agent("conversation"))

        log.warning(
            "Make character",
            character=character,
            add_to_scene=add_to_scene,
            is_active=is_active,
        )
        if add_to_scene:
            await scene.add_actor(actor)
            if is_active:
                await activate_character(scene, character)
        self.set_output_values({"actor": actor, "character": character})


@register("scene/GetCharacter")
class GetCharacter(Node):
    """
    Returns a character object from the scene by name

    Inputs:

    - character_name: The name of the character

    Outputs:

    - character: The character object
    """

    class Fields:
        partial = PropertyField(
            name="partial",
            description="Whether to  match on partial name",
            type="bool",
            default=False,
        )

    def __init__(self, title="Get Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character_name", socket_type="str")
        self.add_output("character", socket_type="character")
        self.set_property("partial", False)

    async def run(self, state: GraphState):
        character_name = self.get_input_value("character_name")
        partial = self.normalized_input_value("partial")
        scene: "Scene" = active_scene.get()

        character = scene.get_character(character_name, partial=partial)

        self.set_output_values({"character": character})


@register("scene/ListCharacters")
class ListCharacters(Node):
    """
    Returns a list of all characters in the scene
    """

    class Fields:
        character_status = PropertyField(
            name="character_status",
            description="The status of the character",
            type="str",
            default="all",
            choices=["active", "inactive", "all"],
        )

    def __init__(self, title="List Characters", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character_status", socket_type="str", optional=True)
        self.add_output("characters", socket_type="list")
        self.set_property("character_status", "all")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        character_status = self.normalized_input_value("character_status")
        if character_status == "active":
            characters = list(scene.characters)
        elif character_status == "inactive":
            characters = list(scene.inactive_characters.values())
        else:
            characters = list(scene.all_characters)
        self.set_output_values({"characters": characters})


@register("scene/IsActiveCharacter")
class IsActiveCharacter(Node):
    """
    Returns whether a character is active
    """

    def __init__(self, title="Is Active Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_output("active", socket_type="bool")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        scene: "Scene" = active_scene.get()
        self.set_output_values({"active": scene.character_is_active(character)})


@register("scene/IsPlayerCharacter")
class IsPlayerCharacter(Node):
    """
    Returns whether a character is the player character

    Inputs:

    - character: The character object

    Outputs:

    - yes: True if the character is the player character
    - no: True if the character is not the player character
    - character: The character object
    """

    def __init__(self, title="Is Player Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_output("yes", socket_type="bool")
        self.add_output("no", socket_type="bool")
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        self.outputs[0].deactivated = not character.is_player
        self.outputs[1].deactivated = character.is_player

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug(
                "Is player character",
                character=character,
                is_player=character.is_player,
            )

        self.set_output_values(
            {
                "yes": True if character.is_player else UNRESOLVED,
                "no": True if not character.is_player else UNRESOLVED,
                "character": character,
            }
        )


@register("scene/GetPlayerCharacter")
class GetPlayerCharacter(Node):
    """
    Get the main player character from the scene

    Outputs:

    - character: The player character
    """

    def __init__(self, title="Get Player Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        character = scene.get_player_character()

        self.set_output_values({"character": character})


@register("scene/UpdateCharacterData")
class UpdateCharacterData(Node):
    """
    Update the data of a character

    Inputs:

    - character: The character object
    - base_attributes: The base attributes dictionary
    - details: The details dictionary
    - description: The description string
    - color: The color of the character name

    Outputs:

    - character: The updated character object
    """

    class Fields:
        description = PropertyField(
            name="description",
            description="The character description",
            type="str",
            default=UNRESOLVED,
        )

        name = PropertyField(
            name="name",
            description="The character name",
            type="str",
            default=UNRESOLVED,
        )

        color = PropertyField(
            name="color",
            description="The color of the character name",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Update Character Data", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_input("base_attributes", socket_type="dict", optional=True)
        self.add_input("details", socket_type="dict", optional=True)
        self.add_input("description", socket_type="str", optional=True)
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("color", socket_type="str", optional=True)
        self.set_property("description", UNRESOLVED)
        self.set_property("name", UNRESOLVED)
        self.set_property("color", UNRESOLVED)
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        color = self.get_input_value("color")
        base_attributes = self.get_input_value("base_attributes")
        details = self.get_input_value("details")
        description = self.get_input_value("description")
        name = self.get_input_value("name")

        if self.is_set(base_attributes):
            character.update(base_attributes=base_attributes)
        if self.is_set(details):
            character.update(details=details)
        if self.is_set(description):
            character.update(description=description)
        if self.is_set(name):
            character.rename(name)
        if self.is_set(color):
            character.color = color

        self.set_output_values({"character": character})


@register("scene/GetCharacterAttribute")
class GetCharacterAttribute(Node):
    """
    Get an attribute from a character
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the attribute",
            type="str",
            default="",
        )

    def __init__(self, title="Get Character Attribute", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_input("name", socket_type="str", optional=True)
        self.add_output("character", socket_type="character")
        self.add_output("name", socket_type="str")
        self.add_output("value", socket_type="str")
        self.add_output("context_id", socket_type="context_id")

        self.set_property("name", "")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        name = self.normalized_input_value("name")
        attribute = character.context.get_attribute(name)

        value = attribute.value if attribute else None
        context_id = attribute.context_id if attribute else None

        self.set_output_values(
            {
                "character": character,
                "name": name,
                "value": value,
                "context_id": context_id,
            }
        )


@register("scene/SetCharacterAttribute")
class SetCharacterAttribute(Node):
    """
    Set an attribute on a character
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the attribute",
            type="str",
            default="",
        )
        value = PropertyField(
            name="value",
            description="The value of the attribute",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Set Character Attribute", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("value", socket_type="str", optional=True)
        self.add_output("state")
        self.add_output("character", socket_type="character")
        self.add_output("name", socket_type="str")
        self.add_output("value", socket_type="str")
        self.set_property("name", "")
        self.set_property("value", UNRESOLVED)

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        name = self.normalized_input_value("name")
        value = self.get_input_value("value")
        await character.set_base_attribute(name, value)
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "character": character,
                "name": name,
                "value": value,
            }
        )


@register("scene/GetCharacterDetail")
class GetCharacterDetail(Node):
    """
    Get the details of a character
    """

    class Fields:
        detail = PropertyField(
            name="name",
            description="The name of the detail",
            type="str",
            default="",
        )

    def __init__(self, title="Get Character Detail", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_input("name", socket_type="str", optional=True)
        self.set_property("name", "")
        self.add_output("character", socket_type="character")
        self.add_output("name", socket_type="str")
        self.add_output("detail", socket_type="str")
        self.add_output("context_id", socket_type="context_id")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        detail_name = self.normalized_input_value("name")
        detail = character.context.get_detail(detail_name)

        value = detail.value if detail else None
        context_id = detail.context_id if detail else None

        self.set_output_values(
            {
                "character": character,
                "name": detail_name,
                "detail": value,
                "context_id": context_id,
            }
        )


@register("scene/SetCharacterDetail")
class SetCharacterDetail(Node):
    """
    Set the details of a character
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the detail",
            type="str",
            default="",
        )
        value = PropertyField(
            name="value",
            description="The content of the detail",
            type="text",
            default=UNRESOLVED,
        )

    def __init__(self, title="Set Character Detail", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("value", socket_type="str", optional=True)
        self.add_output("state")
        self.add_output("character", socket_type="character")
        self.add_output("name", socket_type="str")
        self.add_output("value", socket_type="str")
        self.set_property("name", "")
        self.set_property("value", UNRESOLVED)

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        detail_name = self.normalized_input_value("name")
        detail_value = self.get_input_value("value")
        await character.set_detail(detail_name, detail_value)
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "character": character,
                "name": detail_name,
                "value": detail_value,
            }
        )


@register("scene/GetCharacterDescription")
class GetCharacterDescription(Node):
    """
    Get the description of a character
    """

    def __init__(self, title="Get Character Description", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_output("character", socket_type="character")
        self.add_output("description", socket_type="str")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        description = character.description
        self.set_output_values({"character": character, "description": description})


@register("scene/SetCharacterDescription")
class SetCharacterDescription(Node):
    """
    Set the description of a character
    """

    class Fields:
        description = PropertyField(
            name="description",
            description="The description of the character",
            type="text",
            default="",
        )

    def __init__(self, title="Set Character Description", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("description", socket_type="str", optional=True)
        self.add_output("state")
        self.add_output("character", socket_type="character")
        self.add_output("description", socket_type="str")
        self.set_property("description", "")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        description = self.normalized_input_value("description") or ""
        character.description = description
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "character": character,
                "description": description,
            }
        )


@register("scene/UnpackInteractionState")
class UnpackInteractionState(Node):
    """
    Will take an interaction state and unpack it into the individual fields

    Inputs
    - interaction_state `interaction_state`

    Outputs
    - act_as `str`
    - from_choice `str`
    - input `str`
    - reset_requested `bool`
    """

    def __init__(self, title="Unpack Interaction State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("interaction_state", socket_type="interaction_state")
        self.add_output("act_as", socket_type="str")
        self.add_output("from_choice", socket_type="str")
        self.add_output("input", socket_type="str")
        self.add_output("reset_requested", socket_type="bool")

    async def run(self, state: GraphState):
        interaction_state: InteractionState = self.get_input_value("interaction_state")

        if not isinstance(interaction_state, InteractionState):
            raise InputValueError(
                self, "interaction_state", "Input is not an InteractionState instance"
            )

        self.set_output_values(
            {
                "act_as": interaction_state.act_as,
                "from_choice": interaction_state.from_choice,
                "input": interaction_state.input,
                "reset_requested": interaction_state.reset_requested,
            }
        )


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

        # prefix name: if not already prefixed
        if not message.startswith(f"{character.name}: "):
            message = f"{character.name}: {message}"

        message = scene_message.CharacterMessage(message, source=source, **extra)

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
        )

    def __init__(self, title="Director Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("meta", socket_type="dict", optional=True)
        self.add_input("character", socket_type="character", optional=True)
        self.add_input("action", socket_type="str", optional=True)

        self.set_property("source", "ai")
        self.set_property("action", "actor_instruction")

        self.add_output("message", socket_type="message_object")

    async def run(self, state: GraphState):
        message = self.get_input_value("message")
        source = self.get_input_value("source")
        action = self.get_input_value("action")
        meta = self.get_input_value("meta")
        character: "Character" = self.get_input_value("character")

        extra = {}

        if meta and isinstance(meta, dict):
            extra["meta"] = meta

        message = scene_message.DirectorMessage(
            message, source=source, action=action, **extra
        )

        if character and character is not UNRESOLVED:
            message.set_meta(character=character.name)

        self.set_output_values({"message": message})


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
            message.show()

        self.set_output_values({"message": message})


@register("input/WaitForInput")
class WaitForInput(Node):
    """
    Get input from the user to interact with the scene.

    This node will wait for the user to input a message, and then return the message
    for processing.

    Inputs:

    - state: The current graph state
    - player_character: The player character
    - reason: The reason for the input
    - prefix: The prefix for the input message (similar to a cli prompt)
    - abort_condition: A condition to abort the input loop

    Properties

    - allow_commands: Allow commands to be executed, using the ! prefix

    Outputs:

    - input: The input message
    - interaction_state: The interaction state
    - character: The character object

    Abort Conditions:

    The chain of nodes connected to the abort_condition socket will be executed
    on each iteration of the input loop. If the chain resolves to a boolean value,
    the input loop will be aborted.

    You can use this to check for conditions that should abort the input loop.
    """

    class Fields:
        allow_commands = PropertyField(
            name="allow_commands",
            description="Allow commands to be executed, using the ! prefix",
            type="bool",
            default=True,
        )
        prefix = PropertyField(
            name="prefix",
            description="The prefix for the input message (similar to a cli prompt)",
            type="str",
            default="",
        )
        reason = PropertyField(
            name="reason",
            description="The reason for the input",
            type="str",
            default="talk",
        )

    def __init__(self, title="Get Input", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("player_character", optional=True, socket_type="character")
        self.add_input("reason", optional=True, socket_type="str")
        self.add_input("prefix", optional=True, socket_type="str")
        self.add_input("abort_condition", optional=True, socket_type="any")

        self.set_property("reason", "talk")
        self.set_property("prefix", "")
        self.set_property("allow_commands", True)

        self.add_output("input", socket_type="str")
        self.add_output("interaction_state", socket_type="interaction_state")
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        player_character: "Character" = self.get_input_value("player_character")
        allow_commands = self.get_property("allow_commands")

        async def _abort_condition() -> bool:
            """
            Logic that checks on whether the node connected to the abort_condition socket
            resolves.

            Once it does resolve, the input loop will be aborted, and an AbortWaitForInput
            exception will be propagated to a LoopContinue exception.
            """

            socket = self.get_input_socket("abort_condition")

            # nothing connected, so return False
            if not socket.source:
                return False

            # run a new state of the graph to get the value of the connected node
            # this only runs the node connected to the abort_condition socket and any
            # ascending nodes it depends on
            inner_state: GraphState = await state.graph.execute_to_node(
                socket.source.node, state
            )

            # get the value of the connected node
            rv = inner_state.get_node_socket_value(
                socket.source.node, socket.source.name
            )

            # if the value is a boolean, return it as is
            if isinstance(rv, bool):
                return rv

            # if the value is not None and not UNRESOLVED, return True (abort)
            return rv is not None and rv != UNRESOLVED

        # prepare the kwargs for wait_for_input
        wait_for_input_kwargs = {
            "abort_condition": _abort_condition
            if self.get_input_socket("abort_condition").source
            else None,
        }

        # if the verbosity is verbose, set the sleep time to 1 so that the input loop
        # doesn't spam the console
        if state.verbosity == NodeVerbosity.VERBOSE:
            wait_for_input_kwargs["sleep_time"] = 1

        is_game_loop = not state.shared.get("creative_mode") or state.shared.get(
            "nested_scene_loop", False
        )

        try:
            if player_character and is_game_loop:
                await async_signals.get("player_turn_start").send(
                    events.PlayerTurnStartEvent(
                        scene=scene,
                        event_type="player_turn_start",
                    )
                )

            input = await wait_for_input(
                self.get_input_value("prefix"),
                character=player_character
                if player_character is not UNRESOLVED
                else None,
                scene=scene,
                data={"reason": self.get_property("reason")},
                return_struct=True,
                **wait_for_input_kwargs,
            )
        except AbortWaitForInput:
            raise LoopContinue()

        text_message = input["message"]
        interaction_state = input["interaction"]

        state.shared["skip_to_player"] = False

        if not text_message:
            # input was empty, so continue the loop
            raise LoopContinue()

        if allow_commands and text_message.startswith("!"):
            command_state = {}
            node_cmd_executed = False
            await scene.commands.execute(
                text_message, emit_on_unknown=False, state=command_state
            )
            # no talemate command was executed, see if a matching node command exists

            talemate_cmd_executed = command_state.get("_commands_executed")

            if not talemate_cmd_executed:
                node_cmd_executed = await self.execute_node_command(state, text_message)

            if not node_cmd_executed and not talemate_cmd_executed:
                scene.commands.system_message(f"Unknown command: {text_message}")
            state.shared["signal_game_loop"] = False
            state.shared["skip_to_player"] = True
            raise LoopBreak()

        log.debug(
            "Wait for input",
            text_message=text_message,
            interaction_state=interaction_state,
        )

        self.set_output_values(
            {
                "input": text_message,
                "interaction_state": interaction_state,
                "character": player_character,
            }
        )

    async def execute_node_command(self, state: GraphState, command_name: str) -> bool:
        """
        Get a command node from the scene
        """
        # command name needs to be split by : and then ;
        try:
            command_name, arg_str = command_name.split(":", 1)
        except ValueError:
            command_name = command_name.strip()
            arg_str = ""

        args = arg_str.split(";", 1)

        # remove leading and trailing spaces from the command name
        command_name = command_name.strip()

        # remove ! from the command name
        command_name = command_name.lstrip("!")

        # get the command node from the scene
        registry_name: str | None = state.data["_commands"].get(command_name)

        if not registry_name:
            return False

        # turn args into dict with arg_{N} keys
        args_dict = {f"arg_{i}": arg for i, arg in enumerate(args)}

        command_node = get_node(registry_name)
        if not command_node:
            log.error(
                "Command node not found",
                command_name=command_name,
                registry_name=registry_name,
            )
            return False

        # create task
        asyncio.create_task(command_node().execute_command(state, **args_dict))

        # wait command_node().execute_command(state, **args_dict)
        return True


@register("scene/event/trigger/GameLoopActorIter")
class TriggerGameLoopActorIter(Trigger):
    """
    Trigger the game loop actor iteration event.

    In a most basic setup you will trigger this everytime an actor has had a turn.

    Inputs:

    - actor: The actor that has had a turn
    """

    class Fields:
        pass

    @property
    def signal_name(self) -> str:
        return "game_loop_actor_iter"

    def __init__(self, title="Game Loop Actor Iteration", **kwargs):
        super().__init__(title=title, **kwargs)

    def make_event_object(self, state: GraphState) -> events.GameLoopActorIterEvent:
        return events.GameLoopActorIterEvent(
            scene=active_scene.get(),
            event_type="game_loop_actor_iter",
            actor=self.get_input_value("actor"),
            game_loop=state.shared["game_loop"],
        )

    def setup_required_inputs(self):
        super().setup_required_inputs()
        self.add_input("actor", socket_type="actor")

    def setup_optional_inputs(self):
        return

    def setup_properties(self):
        return

    async def after(self, state: GraphState, event: events.GameLoopActorIterEvent):
        new_event = events.GameLoopCharacterIterEvent(
            scene=active_scene.get(),
            event_type="game_loop_player_character_iter",
            character=event.actor.character,
            game_loop=state.shared["game_loop"],
        )

        if event.actor.character.is_player:
            await self.signals.get("game_loop_player_character_iter").send(new_event)
        else:
            await self.signals.get("game_loop_ai_character_iter").send(new_event)


@register("scene/UnpackCharacter")
class UnpackCharacter(Node):
    """
    Unpack a character into its individual fields

    Inputs:

    - character: The character object

    Outputs:

    - name: The name of the character
    - is_player: Whether the character is the player character
    - description: The character description
    - base_attributes: The character base attributes dictionary
    - details: The character details dictionary
    - color: The character name color
    - actor: The actor instance tied to the character
    """

    def __init__(self, title="Unpack Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")

        self.add_output("name", socket_type="str")
        self.add_output("is_player", socket_type="bool")
        self.add_output("description", socket_type="str")
        self.add_output("base_attributes", socket_type="dict")
        self.add_output("details", socket_type="dict")
        self.add_output("color", socket_type="str")
        self.add_output("actor", socket_type="actor")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")

        self.set_output_values(
            {
                "name": character.name,
                "is_player": character.is_player,
                "actor": character.actor,
                "description": character.description,
                "base_attributes": character.base_attributes,
                "details": character.details,
                "color": character.color,
            }
        )


@register("scene/ActivateCharacter")
class ActivateCharacter(Node):
    """
    Activate a character

    Inputs:

    - character: The character to activate

    Outputs:

    - character: The activated character
    """

    def __init__(self, title="Activate Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")

        await activate_character(active_scene.get(), character)

        self.set_output_values({"character": character})


@register("scene/DeactivateCharacter")
class DeactivateCharacter(Node):
    """
    Deactivate a character

    Inputs:

    - character: The character to deactivate

    Outputs:

    - character: The deactivated character
    """

    def __init__(self, title="Deactivate Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")

        await deactivate_character(active_scene.get(), character)

        self.set_output_values({"character": character})


@register("scene/RemoveAllCharacters")
class RemoveAllCharacters(Node):
    """
    Remove all characters from the scene

    Inputs:

    - state: The graph state

    Outputs:

    - state: The graph state
    """

    def __init__(self, title="Remove All Characters", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        characters = list(scene.characters)

        for character in characters:
            await scene.remove_character(character)

        self.set_output_values({"state": state})


@register("scene/RemoveCharacter")
class RemoveCharacter(Node):
    """
    Remove a character from the scene

    Inputs:

    - state: The graph state
    - character: The character to remove

    Outputs:

    - state: The graph state
    """

    def __init__(self, title="Remove Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_output("state")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        character: "Character" = self.get_input_value("character")

        await scene.remove_character(character)

        self.set_output_values({"state": state})


# get the current scene loop state
@register("scene/GetSceneLoopState")
class GetSceneLoopState(Node):
    """
    Returns the current scene loop states

    Outputs:

    - state: The current node state, this is the state of the graph currently being processed
    - parent: The parent node state, this is the state of the graph that contains the current graph
    - shared: The shared state, this is the state shared between all graphs
    """

    def __init__(self, title="Get Scene Loop State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("state", socket_type="dict")
        self.add_output("parent", socket_type="dict")
        self.add_output("shared", socket_type="dict")

    async def run(self, state: GraphState):
        self.set_output_values(
            {
                "state": state.data,
                "parent": state.outer.data if getattr(state, "outer", None) else {},
                "shared": state.shared,
            }
        )


@register("scene/Restore")
class RestoreScene(Node):
    """
    Restore the scene to its resore point

    Inputs:

    - state: The graph state

    Outputs:

    - state: The graph state
    """

    def __init__(self, title="Restore Scene", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        await scene.restore()

        self.set_output_values({"state": state})


@register("scene/GetTitle")
class GetTitle(Node):
    """
    Get the title text for the scene
    """

    def __init__(self, title="Get Story Title", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("title", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        self.set_output_values({"title": scene.title or scene.name or ""})


@register("scene/SetTitle")
class SetTitle(Node):
    """
    Set the title text for the scene
    """

    class Fields:
        stroy_title = PropertyField(
            name="new_title",
            description="The title text",
            type="str",
            default="",
        )

    def __init__(self, title="Set Story Title", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("new_title", socket_type="str")
        self.set_property("new_title", "")
        self.add_output("state")
        self.add_output("new_title", socket_type="str")
        self.add_output("old_title", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        old_title = scene.title or scene.name or ""

        new_title = self.normalized_input_value("new_title")

        if not new_title:
            raise InputValueError(self, "new_title", "Title is required")

        scene.title = new_title
        self.set_output_values(
            {"state": state, "new_title": new_title, "old_title": old_title}
        )


@register("scene/GetDescription")
class GetDescription(Node):
    """
    Get the description text for the scene
    """

    def __init__(self, title="Get Story Description", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("description", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        self.set_output_values({"description": scene.description})


@register("scene/SetDescription")
class SetDescription(Node):
    """
    Set the description text for the scene
    """

    class Fields:
        description = PropertyField(
            name="description",
            description="The description text",
            type="text",
            default="",
        )

    def __init__(self, title="Set Story Description", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("description", socket_type="str")
        self.set_property("description", "")
        self.add_output("state")
        self.add_output("description", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        description = self.normalized_input_value("description")
        scene.description = description
        self.set_output_values({"state": state, "description": description})


@register("scene/GetContentClassification")
class GetContentClassification(Node):
    """
    Get the content classification text for the scene
    """

    def __init__(self, title="Get Content Classification", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("content_classification", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        self.set_output_values({"content_classification": scene.context})


@register("scene/SetContentClassification")
class SetContentClassification(Node):
    """
    Set the content classification text for the scene
    """

    class Fields:
        content_classification = PropertyField(
            name="content_classification",
            description="The content classification text",
            type="str",
            default="",
        )
        max_length = PropertyField(
            name="max_length",
            description="The maximum length of the content classification text (characters, NOT tokens)",
            type="int",
            default=75,
        )

    def __init__(self, title="Set Content Classification", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("content_classification", socket_type="str")
        self.set_property("content_classification", "")
        self.set_property("max_length", 75)
        self.add_output("state")
        self.add_output("content_classification", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        content_classification = self.normalized_input_value("content_classification")
        max_length = self.normalized_input_value("max_length")

        if content_classification and len(content_classification) > max_length:
            raise InputValueError(
                self,
                "content_classification",
                f"Content classification is too long, max length is {max_length} characters.",
            )

        scene.context = content_classification
        self.set_output_values(
            {"state": state, "content_classification": content_classification}
        )


@register("scene/GetIntroduction")
class GetIntroduction(Node):
    """
    Get the introduction text for the scene
    """

    def __init__(self, title="Get Story Introduction", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("introduction", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        self.set_output_values({"introduction": scene.get_intro()})


@register("scene/SetIntroduction")
class SetIntroduction(Node):
    """
    Set the introduction text for the scene

    Inputs:

    - state: The graph state
    - introduction: The introduction text

    Properties:

    - introduction: The introduction text
    - emit_history: Whether to re-emit the entire history of the scene

    Outputs:

    - state: The graph state
    """

    class Fields:
        introduction = PropertyField(
            name="introduction",
            description="The introduction text",
            type="text",
            default=UNRESOLVED,
        )

        emit_history = PropertyField(
            name="emit_history",
            description="Whether to re-emit the entire history of the scene",
            type="bool",
            default=True,
        )

    def __init__(self, title="Set Introduction", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("introduction", socket_type="str")
        self.set_property("introduction", UNRESOLVED)
        self.set_property("emit_history", True)
        self.add_output("state")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        introduction = self.require_input("introduction")
        emit_history = self.get_input_value("emit_history")

        scene.set_intro(introduction)

        if emit_history:
            await scene.emit_history()

        self.set_output_values({"state": self.get_input_value("state")})


@register("scene/SceneLoop", as_base_type=True)
class SceneLoop(Loop):
    """
    The main scene loop node

    It will loop through the scene graph until the loop is broken.

    Properties:

    - trigger_game_loop: Whether to trigger the game loop event
    """

    class Fields:
        trigger_game_loop = PropertyField(
            name="trigger_game_loop",
            description="Trigger the game loop event",
            type="bool",
            default=True,
        )

    _export_definition: ClassVar[bool] = False

    @property
    def scene_loop_event(self) -> SceneLoopEvent:
        return SceneLoopEvent(scene=active_scene.get(), event_type="scene_loop")

    def __init__(self, title="Scene Loop", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("trigger_game_loop", True)

    async def on_loop_start(self, state: GraphState):
        self._state = state

        scene: "Scene" = state.outer.data["scene"]
        await scene.ensure_memory_db()
        await scene.load_active_pins()

        connect_listeners(self, state, disconnect=True)

        if not state.data.get("_scene_loop_init"):
            state.data["_scene_loop_init"] = True
            await self.register_commands(scene, state)
            await self.init_agent_nodes(scene, state)
            await async_signals.get("scene_loop_init").send(self.scene_loop_event)
            await async_signals.get("scene_loop_init_after").send(self.scene_loop_event)

        trigger_game_loop = self.get_property("trigger_game_loop")

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug(
                "TRIGGER GAME LOOP",
                id=self.id,
                trigger_game_loop=trigger_game_loop,
                signal_game_loop=state.shared.get("signal_game_loop"),
                skip_to_player=state.shared.get("skip_to_player"),
            )

        if trigger_game_loop:
            # Re-evaluate gamestate-controlled pins before the game loop
            await scene.load_active_pins()
            game_loop = events.GameLoopEvent(
                scene=self, event_type="game_loop", had_passive_narration=False
            )
            state.shared["game_loop"] = game_loop
        if state.shared.get("signal_game_loop", True) and trigger_game_loop:
            await scene.signals["game_loop"].send(game_loop)

        if "scene_loop" in state.shared:
            _iteration = state.shared["scene_loop"].get("_iteration", 0)
        else:
            _iteration = 0

        state.shared["signal_game_loop"] = True
        state.shared["scene_loop"] = {"_iteration": _iteration + 1}
        state.shared["creative_mode"] = scene.environment == "creative"

        await async_signals.get("scene_loop_start_cycle").send(self.scene_loop_event)

    async def on_loop_end(self, state: GraphState):
        scene: "Scene" = state.outer.data["scene"]
        if scene.auto_save:
            await scene.save(auto=True)

        if scene._changelog:
            await scene._changelog.append_delta()

        scene.emit_status()

        await async_signals.get("scene_loop_end_cycle").send(self.scene_loop_event)

    async def execute(self, outer_state: GraphState):
        """
        Execute the scene loop
        """
        try:
            outer_state.data["scene"] = active_scene.get()
            await super().execute(outer_state)
        finally:
            disconnect_listeners(self, outer_state)

    async def on_loop_error(self, state: GraphState, exc: Exception):
        scene: "Scene" = state.outer.data["scene"]
        if isinstance(exc, ActedAsCharacter):
            state.shared["signal_game_loop"] = False
            state.shared["acted_as_character"] = scene.get_character(exc.character_name)
            raise LoopBreak()

        elif isinstance(exc, GenerationCancelled):
            state.shared["skip_to_player"] = True
            state.shared["signal_game_loop"] = False
            raise LoopBreak()

        await async_signals.get("scene_loop_error").send(self.scene_loop_event)

    async def register_commands(self, scene: "Scene", state: GraphState):
        """
        Will check the scene._NODE_DEFINITIONS for any command/Command nodes
        and register them as commands in the scene.

        This is used to register commands that are defined in the scene
        nodes directory.
        """
        state.data["_commands"] = {}

        for node_cls in get_nodes_by_base_type("command/Command"):
            _node = node_cls()
            command_name = _node.get_property("name")
            state.data["_commands"][command_name] = _node.registry
            log.info(
                "Registered command", command=f"!{command_name}", module=_node.registry
            )

    async def init_agent_nodes(self, scene: "Scene", state: GraphState):
        """
        Will check the scene._NODE_DEFINITIONS for any agent/DirectorChatAction nodes
        and register them as actions in the scene.
        """

        for agent_name, agent in AGENTS.items():
            init_fn = getattr(agent, "init_nodes", None)
            log.debug("init_agent_nodes.agent", agent_name=agent_name, init_fn=init_fn)
            if init_fn:
                await init_fn(scene, state)
