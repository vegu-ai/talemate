import structlog
from typing import TYPE_CHECKING
from .core import (
    Node,
    GraphState,
    UNRESOLVED,
    InputValueError,
    PropertyField,
    TYPE_CHOICES,
)
from .registry import register
from talemate.emit import emit
from talemate.context import active_scene
from talemate.scene_message import MESSAGES
from talemate.game.engine.context_id import (
    StaticHistoryEntryContextID,
    DynamicHistoryEntryContextID,
)
import talemate.scene_message as scene_message
from talemate.history import (
    character_activity,
    HistoryEntry,
    history_with_relative_time,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.nodes.history")

TYPE_CHOICES.append("history/archive_entry")


@register("scene/history/Push")
class PushHistory(Node):
    """
    Push a message to the scene history at the lowest (e.g., dialogue) layer

    This will emit the message to the the sreen as part of the ongoing scene

     Inputs:

    - message: The message to push

    Properties:

    - emit_message: Whether to emit the message to the screen

    Outputs:

    - message: The message object
    """

    class Fields:
        emit_message = PropertyField(
            name="emit_message",
            description="Emit the message to the screen",
            type="bool",
            default=True,
        )

    def __init__(self, title="Push History", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message", socket_type="message_object")

        self.set_property("emit_message", True)

        self.add_output("message", socket_type="message_object")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        message = self.get_input_value("message")
        emit_message = self.get_property("emit_message")

        if not isinstance(message, scene_message.SceneMessage):
            raise InputValueError(
                self, "message", "Input is not a SceneMessage instance"
            )

        scene.push_history(message)

        if emit_message:
            if isinstance(message, scene_message.CharacterMessage):
                emit(
                    "character",
                    message,
                    character=scene.get_character(message.character_name),
                )
            elif isinstance(message, scene_message.NarratorMessage):
                emit("narrator", message)
            elif isinstance(message, scene_message.ContextInvestigationMessage):
                emit("context_investigation", message)
            elif isinstance(message, scene_message.DirectorMessage):
                emit(
                    "director",
                    message,
                    character=scene.get_character(message.character_name)
                    if message.character_name
                    else None,
                )

        self.set_output_values({"message": message})


@register("scene/history/Pop")
class PopHistory(Node):
    """
    Pop a message from the scene history

    Inputs:

    - message: The message to pop

    Properties:

    - emit_removal: Whether to emit the removal of the message

    Outputs:

    - message: The message object
    """

    class Fields:
        emit_removal = PropertyField(
            name="emit_removal",
            description="Emit the removal of the message",
            type="bool",
            default=True,
        )

    def __init__(self, title="Pop History", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message", socket_type="message_object")

        self.set_property("emit_removal", True)

        self.add_output("message", socket_type="message_object")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        emit_removal = self.get_property("emit_removal")
        message = self.get_input_value("message")

        if not isinstance(message, scene_message.SceneMessage):
            raise InputValueError(
                self, "message", "Input is not a SceneMessage instance"
            )

        scene.pop_message(message)

        if emit_removal:
            emit("remove_message", "", id=message.id)

        self.set_output_values({"message": message})


@register("scene/history/HasHistory")
class HasHistory(Node):
    """
    Check if the scene has history
    """

    def __init__(self, title="Scene Has History", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("has_history", socket_type="bool")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        messages: scene_message.SceneMessage | None = scene.last_message_of_type(
            ["character", "narrator", "context_investigation"],
            max_iterations=100,
        )

        self.set_output_values({"has_history": messages is not None})


@register("scene/history/LastMessageOfType")
class LastMessageOfType(Node):
    """
    Get the last message of a certain type from the history with
    some basic filtering.

    Inputs:

    - message_type: The type of message to get (or a list of types)
    - filters: filter the messages by property values

    Properties:

    - message_type: The type of message to get (or a list of types)
    - max_iterations: The maximum number of iterations to go back
    - filters: filter the messages by property values
    - stop_on_time_passage: Stop when a time passage message is encountered

    Outputs:

    - message: The message object
    """

    class Fields:
        max_iterations = PropertyField(
            name="max_iterations",
            description="The maximum number of iterations to go back",
            type="int",
            default=100,
        )

        filters = PropertyField(
            name="filters",
            description="Filter the messages by property values",
            type="dict",
            default={},
        )

        stop_on_time_passage = PropertyField(
            name="stop_on_time_passage",
            description="Stop when a time passage message is encountered",
            type="bool",
            default=False,
        )

        message_type = PropertyField(
            name="message_type",
            description="The type of message to get (or a list of types)",
            type="str",
            default="character",
            choices=list(MESSAGES.keys()),
        )

    def __init__(self, title="Last Message of Type", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message_type", socket_type="str,list")
        self.add_input("filters", socket_type="dict", optional=True)

        self.set_property("message_type", UNRESOLVED)
        self.set_property("max_iterations", 100)
        self.set_property("stop_on_time_passage", False)
        self.set_property("filters", {})

        self.add_output("message", socket_type="message_object")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        message_type = self.get_input_value("message_type")

        if not isinstance(message_type, list):
            message_type = [message_type]

        # validate message types against MESSAGE keys
        for mt in message_type:
            if mt not in MESSAGES:
                raise InputValueError(
                    self, "message_type", f"Message type {mt} is not valid"
                )

        max_iterations = self.get_property("max_iterations")
        filters = self.get_input_value("filters")
        stop_on_time_passage = self.get_property("stop_on_time_passage")

        if not filters or filters is UNRESOLVED:
            filters = {}

        message = scene.last_message_of_type(
            message_type,
            max_iterations=max_iterations,
            stop_on_time_passage=stop_on_time_passage,
            **filters,
        )

        self.set_output_values({"message": message})


@register("scene/history/UnpackArchiveEntry")
class UnpackArchiveEntry(Node):
    """
    Unpack an archive entry
    """

    def __init__(self, title="Unpack Archive Entry", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("entry", socket_type="history/archive_entry")
        self.add_output("entry", socket_type="history/archive_entry")
        self.add_output("id", socket_type="str")
        self.add_output("text", socket_type="str")
        self.add_output("index", socket_type="int")
        self.add_output("layer", socket_type="int")
        self.add_output("start", socket_type="int")
        self.add_output("end", socket_type="int")
        self.add_output("ts_start", socket_type="str")
        self.add_output("ts_end", socket_type="str")
        self.add_output("ts", socket_type="str")
        self.add_output("time", socket_type="str")
        self.add_output("time_start", socket_type="str")
        self.add_output("time_end", socket_type="str")
        self.add_output("context_id", socket_type="context_id")

    async def run(self, state: GraphState):
        entry = self.get_input_value("entry")

        if entry.end is None:
            context_id = StaticHistoryEntryContextID.make(entry)
        else:
            context_id = DynamicHistoryEntryContextID.make(entry)

        self.set_output_values(
            {"entry": entry, **entry.model_dump(), "context_id": context_id}
        )


@register("scene/history/StaticArchiveEntries")
class StaticArchiveEntries(Node):
    """
    Get the static scene history entries
    """

    def __init__(self, title="Static Archive Entries", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("entries", socket_type="list")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        entries = []

        for history_entry in scene.archived_history:
            if history_entry.get("end") is None:
                entries.append(history_entry)
            else:
                break

        entries = history_with_relative_time(entries, scene.ts)

        log.warning("StaticArchiveEntries", entries=entries)

        self.set_output_values(
            {"entries": [HistoryEntry(**entry) for entry in entries]}
        )


@register("scene/history/ContextHistory")
class ContextHistory(Node):
    """
    Compiles history for inclusion in a prompt context.

    Inputs:

    - budget: The budget for the history (number of tokens, defaults to 8192)

    Properties:

    - keep_direcctor_messages: Whether to keep director messages
    - keep_investigation_messages: Whether to keep investigation messages
    - keep_reinforcment_messages: Whether to keep reinforcement messages
    - show_hidden: Whether to show hidden messages
    - min_dialogue_length: The minimum length of dialogue to keep, this will ensure that there are always N dialogue messages in the history regardless of whether they are covered by summarization. (default 5)
    - label_chapters: Whether to label chapters in the summarized history

    Outputs:

    - messages: list of messages
    - compiled: compiled message
    """

    class Fields:
        budget = PropertyField(
            name="budget",
            description="The budget for the history (number of tokens, defaults to 8192)",
            type="int",
            default=8192,
            step=128,
            min=0,
        )

        keep_director_messages = PropertyField(
            name="keep_director_messages",
            description="Whether to keep director messages",
            type="bool",
            default=False,
        )

        keep_investigation_messages = PropertyField(
            name="keep_investigation_messages",
            description="Whether to keep investigation messages",
            type="bool",
            default=True,
        )

        keep_reinforcement_messages = PropertyField(
            name="keep_reinforcement_messages",
            description="Whether to keep reinforcement messages",
            type="bool",
            default=True,
        )

        show_hidden = PropertyField(
            name="show_hidden",
            description="Whether to show hidden messages",
            type="bool",
            default=False,
        )

        min_dialogue_length = PropertyField(
            name="min_dialogue_length",
            description="The minimum length of dialogue to keep, this will ensure that there are always N dialogue messages in the history regardless of whether they are covered by summarization",
            type="int",
            default=5,
            min=0,
            step=1,
        )

        label_chapters = PropertyField(
            name="label_chapters",
            description="Whether to label chapters in the summarized history",
            type="bool",
            default=False,
        )

    def __init__(self, title="Context History", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("budget", socket_type="int", optional=True)

        self.set_property("budget", 8192)
        self.set_property("keep_director_messages", False)
        self.set_property("keep_investigation_messages", False)
        self.set_property("keep_reinforcement_messages", False)
        self.set_property("show_hidden", False)
        self.set_property("min_dialogue_length", 5)
        self.set_property("label_chapters", False)

        self.add_output("messages", socket_type="list")
        self.add_output("compiled", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        budget = self.require_number_input("budget", types=(int,))

        keep_director_messages = self.get_property("keep_director_messages")
        keep_investigation_messages = self.get_property("keep_investigation_messages")
        keep_reinforcement_messages = self.get_property("keep_reinforcement_messages")
        show_hidden = self.get_property("show_hidden")
        min_dialogue_length = self.require_number_input(
            "min_dialogue_length", types=(int,)
        )
        label_chapters = self.get_property("label_chapters")

        messages = scene.context_history(
            budget=budget,
            keep_director=keep_director_messages,
            keep_context_investigation=keep_investigation_messages,
            include_reinforcements=keep_reinforcement_messages,
            show_hidden=show_hidden,
            assured_dialogue_num=min_dialogue_length,
            chapter_labels=label_chapters,
        )

        self.set_output_values({"messages": messages, "compiled": "\n".join(messages)})


@register("scene/history/ActiveCharacterActivity")
class ActiveCharacterActivity(Node):
    """
    Returns a list of all active characters sorted by which were last active

    The most recently active character is first in the list.

    Properties:

    - since_time_passage: Only include characters that have acted since the last time passage message

    Outputs:

    - characters: list of characters
    - none_have_acted: whether no characters have acted
    """

    class Fields:
        since_time_passage = PropertyField(
            name="since_time_passage",
            description="Only include characters that have acted since the last time passage message",
            type="bool",
            default=False,
        )

    def __init__(self, title="Character Activity", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("since_time_passage", False)
        self.add_output("none_have_acted", socket_type="bool")
        self.add_output("characters", socket_type="list")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        since_time_passage = self.normalized_input_value("since_time_passage")

        activity = await character_activity(
            scene, since_time_passage=since_time_passage
        )

        self.set_output_values(
            {
                "characters": activity.characters,
                "none_have_acted": activity.none_have_acted,
            }
        )
