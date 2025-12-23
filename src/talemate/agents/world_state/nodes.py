import structlog
from typing import ClassVar, TYPE_CHECKING
from talemate.context import active_scene
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
    UNRESOLVED,
    TYPE_CHOICES,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode
import talemate.game.focal as focal
from talemate.world_state import InsertionMode
from talemate.world_state.manager import WorldStateManager

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

TYPE_CHOICES.extend(
    [
        "world_state/reinforcement",
    ]
)

log = structlog.get_logger("talemate.game.engine.nodes.agents.world_state")


@register("agents/world_state/Settings")
class WorldstateSettings(AgentSettingsNode):
    """
    Base node to render world_state agent settings.
    """

    _agent_name: ClassVar[str] = "world_state"

    def __init__(self, title="Worldstate Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/world_state/ExtractCharacterSheet")
class ExtractCharacterSheet(AgentNode):
    """
    Attempts to extract an attribute based character sheet
    from a given context for a specific character.

    Additionally alteration instructions can be given to
    modify the character's existing sheet.

    Inputs:

    - state: The current state of the graph
    - character_name: The name of the character to extract the sheet for
    - context: The context to extract the sheet from
    - alteration_instructions: Instructions to alter the character's sheet

    Outputs:

    - character_sheet: The extracted character sheet (dict)
    """

    _agent_name: ClassVar[str] = "world_state"

    def __init__(self, title="Extract Character Sheet", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character_name", socket_type="str")
        self.add_input("context", socket_type="str")
        self.add_input("alteration_instructions", socket_type="str", optional=True)

        self.add_output("character_sheet", socket_type="dict")

    async def run(self, state: GraphState):
        context = self.require_input("context")
        character_name = self.require_input("character_name")
        alteration_instructions = self.get_input_value("alteration_instructions")

        sheet = await self.agent.extract_character_sheet(
            name=character_name,
            text=context,
            alteration_instructions=alteration_instructions,
        )

        self.set_output_values({"character_sheet": sheet})


@register("agents/world_state/StateReinforcement")
class StateReinforcement(AgentNode):
    """
    Reinforces the a tracked state of a character or the world in general.

    Inputs:

    - state: The current state of the graph
    - query_or_detail: The query or instruction to reinforce
    - character: The character to reinforce the state for (optional)

    Properties

    - reset: If the state should be reset

    Outputs:

    - state: graph state
    - message: state reinforcement message
    """

    _agent_name: ClassVar[str] = "world_state"

    class Fields:
        query_or_detail = PropertyField(
            name="query_or_detail",
            description="Query or detail to reinforce",
            type="str",
            default=UNRESOLVED,
        )

        instructions = PropertyField(
            name="instructions",
            description="Instructions for the reinforcement",
            type="text",
            default="",
        )

        interval = PropertyField(
            name="interval",
            description="Interval for reinforcement",
            type="int",
            default=10,
            min=1,
            step=1,
        )

        insert_method = PropertyField(
            name="insert_method",
            description="Method to insert reinforcement",
            type="str",
            default="sequential",
            choices=[mode.value for mode in InsertionMode],
        )

        reset = PropertyField(
            name="reset",
            description="If the state should be reset",
            type="bool",
            default=False,
        )

    def __init__(self, title="State Reinforcement", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("query_or_detail", socket_type="str")
        self.add_input("character", socket_type="character", optional=True)
        self.add_input("instructions", socket_type="str", optional=True)

        self.set_property("query_or_detail", "")
        self.set_property("instructions", "")
        self.set_property("interval", 10)
        self.set_property("insert_method", "sequential")
        self.set_property("reset", False)

        self.add_output("state")
        self.add_output("message", socket_type="message")
        self.add_output("reinforcement", socket_type="world_state/reinforcement")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        query_or_detail = self.require_input("query_or_detail")
        character = self.normalized_input_value("character")
        reset = self.get_property("reset")
        interval = self.require_number_input("interval")
        instructions = self.normalized_input_value("instructions")
        insert_method = self.get_property("insert_method")

        await scene.world_state.add_reinforcement(
            question=query_or_detail,
            character=character.name if character else None,
            instructions=instructions,
            interval=interval,
            insert=insert_method,
        )

        message = await self.agent.update_reinforcement(
            question=query_or_detail, character=character, reset=reset
        )

        self.set_output_values({"state": state, "message": message})


@register("agents/world_state/DeactivateCharacter")
class DeactivateCharacter(AgentNode):
    """
    Deactivates a character from the world state.

    Inputs:

    - state: The current state of the graph
    - character: The character to deactivate

    Outputs:

    - state: The updated state
    """

    _agent_name: ClassVar[str] = "world_state"

    def __init__(self, title="Deactivate Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")

        self.add_output("state")

    async def run(self, state: GraphState):
        character: "Character" = self.require_input("character")
        scene: "Scene" = active_scene.get()

        manager: WorldStateManager = scene.world_state_manager

        manager.deactivate_character(character.name)

        self.set_output_values({"state": state})


@register("agents/world_state/DetermineCharacterPresence")
class DetermineCharacterPresence(AgentNode):
    """
    Determines whether a character is present (and active) or leaving the current scene.

    Mode is controlled via the `check` property:
    - present: calls world_state.is_character_present(character.name)
    - leaving: calls world_state.is_character_leaving(character.name)

    Inputs:
    - state: The current graph state
    - character: The character to check

    Outputs:
    - yes: True if the condition is met
    - no: True if the condition is not met
    """

    _agent_name: ClassVar[str] = "world_state"

    class Fields:
        check = PropertyField(
            name="check",
            description="Which condition to check",
            type="str",
            default="present",
            choices=["present", "leaving"],
        )

    def __init__(self, title="Determine Character Presence", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")

        self.set_property("check", "present")

        self.add_output("yes", socket_type="bool")
        self.add_output("no", socket_type="bool")

    async def run(self, state: GraphState):
        character: "Character" = self.require_input("character")
        check: str = self.get_property("check")

        if check == "present":
            result = await self.agent.is_character_present(character.name)
        elif check == "leaving":
            result = await self.agent.is_character_leaving(character.name)
        else:
            raise ValueError(f"Unknown check: {check}")

        # Deactivate the inactive output socket
        self.get_output_socket("yes").deactivated = not result
        self.get_output_socket("no").deactivated = result

        self.set_output_values(
            {
                "yes": True if result else UNRESOLVED,
                "no": True if not result else UNRESOLVED,
            }
        )


@register("agents/world_state/EvaluateQuery")
class EvaluateQuery(AgentNode):
    """
    Evaluates a query on the world state.

    Inputs:

    - state: The current state of the graph
    - query: The query to evaluate
    - context: The context to evaluate the query in

    Outputs:

    - state: The current state
    - result: The result of the query
    """

    _agent_name: ClassVar[str] = "world_state"

    class Fields:
        query = PropertyField(
            name="query",
            description="The query to evaluate",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Evaluate Query", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("query", socket_type="str")
        self.add_input("context", socket_type="str")

        self.set_property("query", UNRESOLVED)

        self.add_output("state")
        self.add_output("result", socket_type="bool")

    async def run(self, state: GraphState):
        query = self.require_input("query")
        context = self.require_input("context")

        result = await self.agent.answer_query_true_or_false(query=query, text=context)

        self.set_output_values({"state": state, "result": result})


@register("agents/world_state/RequestWorldState")
class RequestWorldState(AgentNode):
    """
    Requests the current world state.

    Inputs:

    - state: The current state of the graph

    Outputs:

    - state: The current state
    - world_state: The current world state
    """

    _agent_name: ClassVar[str] = "world_state"

    def __init__(self, title="Request World State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")

        self.add_output("state")
        self.add_output("world_state", socket_type="dict")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        world_state = await scene.world_state.request_update()

        self.set_output_values({"state": state, "world_state": world_state})


@register("agents/world_state/EmitWorldState")
class EmitWorldState(AgentNode):
    """
    Emits the current world state.
    """

    _agent_name: ClassVar[str] = "world_state"

    def __init__(self, title="Emit World State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")

        self.add_output("state")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        scene.world_state.emit()

        self.set_output_values({"state": self.get_input_value("state")})


@register("agents/world_state/CharacterProgression")
class CharacterProgression(AgentNode):
    """
    Character progression
    """

    _agent_name: ClassVar[str] = "world_state"

    class Fields:
        as_suggestions = PropertyField(
            name="as_suggestions",
            description="Whether to return the result as suggestions",
            type="bool",
            default=False,
        )
        instructions = PropertyField(
            name="instructions",
            description="Instructions for the character progression",
            type="text",
            default="",
        )

    def __init__(self, title="Character Progression", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("instructions", socket_type="str", optional=True)

        self.set_property("as_suggestions", False)

        self.add_output("state")
        self.add_output("calls", socket_type="list")

    async def run(self, state: GraphState):
        character: "Character" = self.require_input("character")
        instructions: str = self.require_input("instructions")

        calls: list[focal.Call] = await self.agent.determine_character_development(
            character=character,
            instructions=instructions,
        )

        await self.agent.character_progression_process_calls(
            character=character,
            calls=calls,
            as_suggestions=self.get_property("as_suggestions"),
        )

        self.set_output_values({"state": state, "calls": calls})


@register("agents/world_state/AdvanceTime")
class AdvanceTime(AgentNode):
    """
    Advances the time of the world state.
    """

    _agent_name: ClassVar[str] = "world_state"  #

    class Fields:
        duration = PropertyField(
            name="duration",
            description="The duration to advance",
            type="str",
            default="P0T1S",
        )
        narration_instructions = PropertyField(
            name="narration_instructions",
            description="The instructions for the narration",
            type="str",
            default="",
        )

    def __init__(self, title="Advance Time", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("duration", socket_type="str")
        self.add_input("narration_instructions", socket_type="str", optional=True)

        self.set_property("narration_instructions", "")
        self.set_property("duration", "P0T1S")

        self.add_output("state")
        self.add_output("duration", socket_type="str")
        self.add_output("narration_instructions", socket_type="str")
        self.add_output("message", socket_type="message")

    async def run(self, state: GraphState):
        duration: str = self.normalized_input_value("duration")
        narration_instructions: str = self.normalized_input_value(
            "narration_instructions"
        )
        message = await self.agent.advance_time(duration, narration_instructions)
        self.set_output_values(
            {
                "state": state,
                "duration": message.ts,
                "narration_instructions": narration_instructions,
                "message": message,
            }
        )
