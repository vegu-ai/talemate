import structlog
from typing import ClassVar
from talemate.game.engine.nodes.core import GraphState, PropertyField
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentNode
from talemate.scene.schema import ScenePhase

log = structlog.get_logger("talemate.game.engine.nodes.agents.director")


@register("agents/director/auto-direct/Candidates")
class AutoDirectCandidates(AgentNode):
    """
    Returns a list of characters that are valid for doing the
    next action, based on the director's auto-direct settings and
    the recent scene history.
    """

    _agent_name: ClassVar[str] = "director"

    def __init__(self, title="Auto Direct Candidates [DEPRECATED]", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("characters", socket_type="list")

    async def run(self, state: GraphState):
        candidates = self.agent.auto_direct_candidates()
        self.set_output_values({"characters": candidates})


@register("agents/director/auto-direct/DetermineSceneIntent")
class DetermineSceneIntent(AgentNode):
    """
    Determines the scene intent based on the current scene state.
    """

    _agent_name: ClassVar[str] = "director"

    def __init__(self, title="Determine Scene Intent", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        self.add_output("scene_phase", socket_type="scene_intent/scene_phase")

    async def run(self, state: GraphState):
        phase: ScenePhase = await self.agent.auto_direct_set_scene_intent()

        self.set_output_values({"state": state, "scene_phase": phase})


@register("agents/director/auto-direct/GenerateSceneTypes")
class GenerateSceneTypes(AgentNode):
    """
    Generates scene types based on the current scene state.
    """

    _agent_name: ClassVar[str] = "director"

    class Fields:
        instructions = PropertyField(
            name="instructions",
            type="text",
            description="The instructions for the scene types",
            default="",
        )

        max_scene_types = PropertyField(
            name="max_scene_types",
            type="int",
            description="The maximum number of scene types to generate",
            default=1,
        )

    def __init__(self, title="Generate Scene Types", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("max_scene_types", socket_type="int", optional=True)
        self.set_property("instructions", "")
        self.set_property("max_scene_types", 1)
        self.add_output("state")

    async def run(self, state: GraphState):
        instructions = self.normalized_input_value("instructions")
        max_scene_types = self.normalized_input_value("max_scene_types")

        scene_types = await self.agent.auto_direct_generate_scene_types(
            instructions=instructions, max_scene_types=max_scene_types
        )

        self.set_output_values({"state": state, "scene_types": scene_types})


@register("agents/director/auto-direct/IsDueForInstruction")
class IsDueForInstruction(AgentNode):
    """
    Checks if the actor is due for instruction based on the auto-direct settings.
    """

    _agent_name: ClassVar[str] = "director"

    class Fields:
        actor_name = PropertyField(
            name="actor_name",
            type="str",
            description="The name of the actor to check instruction timing for",
            default="",
        )

    def __init__(self, title="Is Due For Instruction [DEPRECATED]", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("actor_name", socket_type="str")

        self.set_property("actor_name", "")

        self.add_output("is_due", socket_type="bool")
        self.add_output("actor_name", socket_type="str")

    async def run(self, state: GraphState):
        actor_name = self.require_input("actor_name")

        is_due = self.agent.auto_direct_is_due_for_instruction(actor_name)

        self.set_output_values({"is_due": is_due, "actor_name": actor_name})
