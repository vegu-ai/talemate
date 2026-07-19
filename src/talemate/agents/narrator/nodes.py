import structlog
from typing import ClassVar
from talemate.game.engine.nodes.core import GraphState, PropertyField, InputValueError
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentNode, AgentSettingsNode
from talemate.scene_message import NarratorMessage
from talemate.util import iso8601_duration_to_human

log = structlog.get_logger("talemate.game.engine.nodes.agents.narrator")


@register("agents/narrator/Settings")
class NarratorSettings(AgentSettingsNode):
    """
    Settings for the narrator agent
    """

    _agent_name: ClassVar[str] = "narrator"
    _title: ClassVar[str] = "Narrator Settings"

    def __init__(self, title="Narrator Settings", **kwargs):
        super().__init__(title=title, **kwargs)


class GenerateNarrationBase(AgentNode):
    """
    Generate a narration message
    """

    _agent_name: ClassVar[str] = "narrator"
    _action_name: ClassVar[str] = ""
    _title: ClassVar[str] = "Generate Narration"

    class Fields:
        narrative_direction = PropertyField(
            name="narrative_direction",
            description="Narrative directions",
            default="",
            type="str",
        )

        response_length = PropertyField(
            name="response_length",
            description="Response length (0 for default)",
            default=0,
            type="int",
        )

    def __init__(self, **kwargs):
        if "title" not in kwargs:
            kwargs["title"] = self._title

        super().__init__(**kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("narrative_direction", socket_type="str", optional=True)
        self.add_input("response_length", socket_type="int", optional=True)

        self.set_property("response_length", 0)

        self.add_output("generated", socket_type="str")
        self.add_output("message", socket_type="message_object")

    async def prepare_input_values(self) -> dict:
        input_values = self.get_input_values()
        input_values.pop("state", None)
        return input_values

    async def run(self, state: GraphState):
        input_values = await self.prepare_input_values()
        try:
            agent_fn = getattr(self.agent, self._action_name)
        except AttributeError:
            raise InputValueError(
                self,
                "_action_name",
                f"Agent does not have a function named {self._action_name}",
            )

        narration = await agent_fn(**input_values)

        message = NarratorMessage(
            message=narration,
            meta=self.agent.action_to_meta(self._action_name, input_values),
        )

        self.set_output_values({"generated": narration, "message": message})


@register("agents/narrator/GenerateProgress")
class GenerateProgressNarration(GenerateNarrationBase):
    """
    Generates narration that moves the story forward, via the narrator
    agent's progress_story action. If no narrative direction is given the
    narrator will attempt to subtly move the story forward on its own.

    The generated message is not added to the scene history by this node.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "progress_story"
    _title: ClassVar[str] = "Generate Progress Narration"


@register("agents/narrator/GenerateSceneNarration")
class GenerateSceneNarration(GenerateNarrationBase):
    """
    Generates narration describing the current scene, via the narrator
    agent's narrate_scene action.

    The generated message is not added to the scene history by this node.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_scene"
    _title: ClassVar[str] = "Generate Scene Narration"


@register("agents/narrator/GenerateAfterDialogNarration")
class GenerateAfterDialogNarration(GenerateNarrationBase):
    """
    Generates narration reacting to the most recent line of dialogue, from
    the perspective of the given character, via the narrator agent's
    narrate_after_dialogue action.

    The generated message is not added to the scene history by this node.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)
    - character: The character whose dialogue the narration follows

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_after_dialogue"
    _title: ClassVar[str] = "Generate After Dialog Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/GenerateEnvironmentNarration")
class GenerateEnvironmentNarration(GenerateNarrationBase):
    """
    Generates narration describing the current environment, via the
    narrator agent's narrate_environment action (which narrates from the
    player character's perspective).

    The generated message is not added to the scene history by this node.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_environment"
    _title: ClassVar[str] = "Generate Environment Narration"


@register("agents/narrator/GenerateQueryNarration")
class GenerateQueryNarration(GenerateNarrationBase):
    """
    Generates narration answering a specific question about the scene, via
    the narrator agent's narrate_query action.

    The generated message is not added to the scene history by this node.

    Inputs:

    - state: The graph state
    - response_length: Optional response length in tokens (0 for default)
    - query: The question to answer through narration
    - extra_context: Optional additional context to inform the answer

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_query"
    _title: ClassVar[str] = "Generate Query Narration"

    def setup(self):
        super().setup()
        self.add_input("query", socket_type="str")
        self.add_input("extra_context", socket_type="str", optional=True)
        self.remove_input("narrative_direction")


@register("agents/narrator/GenerateCharacterNarration")
class GenerateCharacterNarration(GenerateNarrationBase):
    """
    Generates narration describing a specific character, via the narrator
    agent's narrate_character action.

    The generated message is not added to the scene history by this node.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)
    - character: The character to narrate

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_character"
    _title: ClassVar[str] = "Generate Character Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/GenerateTimeNarration")
class GenerateTimeNarration(GenerateNarrationBase):
    """
    Generates narration for a passage of time, via the narrator agent's
    narrate_time_passage action. The ISO 8601 duration is converted to a
    human readable string before being handed to the narrator.

    The generated message is not added to the scene history by this node,
    nor does the node advance the scene time.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)
    - duration: The time passed as an ISO 8601 duration (e.g. "PT30M")

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_time_passage"
    _title: ClassVar[str] = "Generate Time Narration"

    def setup(self):
        super().setup()
        self.add_input("duration", socket_type="str")
        self.set_property("duration", "P0T1S")

    async def prepare_input_values(self) -> dict:
        input_values = await super().prepare_input_values()
        input_values["time_passed"] = iso8601_duration_to_human(
            input_values["duration"]
        )
        return input_values


@register("agents/narrator/GenerateCharacterEntryNarration")
class GenerateCharacterEntryNarration(GenerateNarrationBase):
    """
    Generates narration for a character entering the scene, via the
    narrator agent's narrate_character_entry action. The node does not
    activate the character or add the message to the scene history.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)
    - character: The character entering the scene

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_character_entry"
    _title: ClassVar[str] = "Generate Character Entry Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/GenerateCharacterExitNarration")
class GenerateCharacterExitNarration(GenerateNarrationBase):
    """
    Generates narration for a character exiting the scene, via the
    narrator agent's narrate_character_exit action. The node does not
    deactivate the character or add the message to the scene history.

    Inputs:

    - state: The graph state
    - narrative_direction: Optional direction the narrative should take
    - response_length: Optional response length in tokens (0 for default)
    - character: The character exiting the scene

    Outputs:

    - generated: The generated narration text
    - message: The generated NarratorMessage object
    """

    _action_name: ClassVar[str] = "narrate_character_exit"
    _title: ClassVar[str] = "Generate Character Exit Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/UnpackSource")
class UnpackSource(AgentNode):
    """
    DEPRECATED - narration messages no longer encode their action in a
    source string. This node always outputs an empty action name and an
    empty arguments dict.

    Inputs:

    - source: The narration message source string

    Outputs:

    - action_name: Always an empty string
    - arguments: Always an empty dict
    """

    _agent_name: ClassVar[str] = "narrator"

    def __init__(self, title="Unpack Source", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("source", socket_type="str")
        self.add_output("action_name", socket_type="str")
        self.add_output("arguments", socket_type="dict")

    async def run(self, state: GraphState):
        action_name = ""
        arguments = {}

        self.set_output_values({"action_name": action_name, "arguments": arguments})
