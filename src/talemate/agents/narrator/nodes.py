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
    Generate a progress narration message
    """

    _action_name: ClassVar[str] = "progress_story"
    _title: ClassVar[str] = "Generate Progress Narration"


@register("agents/narrator/GenerateSceneNarration")
class GenerateSceneNarration(GenerateNarrationBase):
    """
    Generate a scene narration message
    """

    _action_name: ClassVar[str] = "narrate_scene"
    _title: ClassVar[str] = "Generate Scene Narration"


@register("agents/narrator/GenerateAfterDialogNarration")
class GenerateAfterDialogNarration(GenerateNarrationBase):
    """
    Generate an after dialog narration message
    """

    _action_name: ClassVar[str] = "narrate_after_dialogue"
    _title: ClassVar[str] = "Generate After Dialog Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/GenerateEnvironmentNarration")
class GenerateEnvironmentNarration(GenerateNarrationBase):
    """
    Generate an environment narration message
    """

    _action_name: ClassVar[str] = "narrate_environment"
    _title: ClassVar[str] = "Generate Environment Narration"


@register("agents/narrator/GenerateQueryNarration")
class GenerateQueryNarration(GenerateNarrationBase):
    """
    Generate a query narration message
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
    Generate a character narration message
    """

    _action_name: ClassVar[str] = "narrate_character"
    _title: ClassVar[str] = "Generate Character Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/GenerateTimeNarration")
class GenerateTimeNarration(GenerateNarrationBase):
    """
    Generate a time narration message
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
    Generate a character entry narration message
    """

    _action_name: ClassVar[str] = "narrate_character_entry"
    _title: ClassVar[str] = "Generate Character Entry Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/GenerateCharacterExitNarration")
class GenerateCharacterExitNarration(GenerateNarrationBase):
    """
    Generate a character exit narration message
    """

    _action_name: ClassVar[str] = "narrate_character_exit"
    _title: ClassVar[str] = "Generate Character Exit Narration"

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character")


@register("agents/narrator/UnpackSource")
class UnpackSource(AgentNode):
    """
    Unpacks a narration message source string
    into action name and arguments
    DEPRECATED
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
