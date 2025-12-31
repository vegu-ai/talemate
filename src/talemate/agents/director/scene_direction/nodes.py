from typing import ClassVar
import pydantic
import structlog
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
    NodeStyle,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentNode
from talemate.agents.director.scene_direction.schema import (
    SceneDirectionActionResultMessage,
)

log = structlog.get_logger("talemate.agents.director.scene_direction")


@register("agents/director/SceneDirection")
class SceneDirection(AgentNode):
    """
    Executes an autonomous scene direction turn (game master mode).

    The director analyzes the scene and takes multiple sequential actions
    until satisfied or hitting the max actions limit, without user interaction.

    Inputs:
    - state: Required state to trigger execution
    - max_actions: Optional override for max actions per turn
    - always_on: Optional override to always execute (ignores agent enabled config)

    Outputs:
    - state: The input state passed through
    - actions_taken: List of actions executed during the turn
    - yield_to_user: Whether the director wants to yield to the player
    - action_count: Number of actions taken
    """

    _agent_name: ClassVar[str] = "director"

    class Fields:
        max_actions = PropertyField(
            name="max_actions",
            type="int",
            description="Maximum actions per turn (0 = use agent default)",
            default=0,
            min=0,
            max=20,
            step=1,
        )
        always_on = PropertyField(
            name="always_on",
            type="bool",
            description="Override agent config and always execute scene direction (ignores enabled setting)",
            default=False,
        )
        is_first_turn = PropertyField(
            name="is_first_turn",
            type="bool",
            description="Is this the first turn of the scene?",
            default=False,
        )
        run_immediately = PropertyField(
            name="run_immediately",
            type="bool",
            description="Run immediately (do not yield first turn)",
            default=False,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#412416",
            title_color="#913612",
            icon="F04CB",  # movie-open
            auto_title="Scene Direction",
        )

    def __init__(self, title="Scene Direction", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("max_actions", socket_type="number", optional=True)
        self.add_input("is_first_turn", socket_type="bool", optional=True)
        self.add_input("always_on", socket_type="bool", optional=True)
        self.add_input("run_immediately", socket_type="bool", optional=True)

        self.set_property("max_actions", 0)
        self.set_property("always_on", False)
        self.set_property("run_immediately", False)

        self.add_output("state")
        self.add_output("actions_taken", socket_type="list")
        self.add_output("yield_to_user", socket_type="bool")
        self.add_output("action_count", socket_type="number")

    async def run(self, state: GraphState):
        input_state = self.get_input_value("state")
        max_actions_override = self.normalized_input_value("max_actions")
        always_on_input = self.normalized_input_value("always_on") or False
        is_first_turn = self.normalized_input_value("is_first_turn") or False
        run_immediately_input = self.normalized_input_value("run_immediately") or False

        # Use inputs directly
        always_on_override = always_on_input
        run_immediately = run_immediately_input

        if is_first_turn and not run_immediately:
            log.debug(
                "Scene Direction - skipping first turn because it's not run immediately",
                is_first_turn=is_first_turn,
                run_immediately=run_immediately,
            )
            return

        if not self.agent.direction_enabled and not always_on_override:
            return

        # Convert max_actions_override to int if provided and > 0, otherwise None
        max_actions_param = (
            int(max_actions_override)
            if max_actions_override and max_actions_override > 0
            else None
        )

        # Collect action results
        action_results: list[SceneDirectionActionResultMessage] = []

        async def on_action_complete(result: SceneDirectionActionResultMessage):
            action_results.append(result)

        actions_taken, yield_to_user = await self.agent.direction_execute_turn(
            on_action_complete=on_action_complete,
            always_on=always_on_override,
            max_actions=max_actions_param,
        )

        # Convert action results to serializable format
        actions_list = [
            {
                "name": action.name,
                "instructions": action.instructions,
                "result": action.result,
                "status": action.status,
            }
            for action in actions_taken
        ]

        self.set_output_values(
            {
                "state": input_state,
                "actions_taken": actions_list,
                "yield_to_user": yield_to_user,
                "action_count": len(actions_taken),
            }
        )
