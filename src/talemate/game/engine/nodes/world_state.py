import structlog
from typing import TYPE_CHECKING
from .core import Node, GraphState, UNRESOLVED, PropertyField, TYPE_CHOICES
from .registry import register
from talemate.context import active_scene
from talemate.world_state.manager import WorldStateManager
import talemate.world_state.templates.content as content

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.nodes.scene")

# extend TYPE_CHOICES with GenerationOptions
TYPE_CHOICES.extend(["generation_options", "spices", "writing_style"])


class WorldStateManagerNode(Node):
    """
    Base class for world state manager nodes
    """

    @property
    def world_state_manager(self) -> WorldStateManager:
        scene: "Scene" = active_scene.get()
        return scene.world_state_manager


@register("scene/worldstate/SaveWorldEntry")
class SaveWorldEntry(WorldStateManagerNode):
    """
    Saves the world entry

    Inputs:

    - entry_id: The id of the world entry
    - text: The text of the world entry
    - meta: The meta of the world entry

    Properties:

    - create_pin: Whether to create a pin for the entry

    Outputs:

    - entry_id: The id of the world entry
    - text: The text of the world entry
    - meta: The meta of the world entry
    """

    class Fields:
        entry_id = PropertyField(
            name="entry_id",
            description="The id of the world entry",
            type="str",
            default=UNRESOLVED,
        )

        text = PropertyField(
            name="text",
            description="The text of the world entry",
            type="text",
            default=UNRESOLVED,
        )

        meta = PropertyField(
            name="meta",
            description="The meta of the world entry",
            type="dict",
            default={},
        )

        create_pin = PropertyField(
            name="create_pin",
            description="Whether to create a pin for the entry",
            type="bool",
            default=False,
        )

    def __init__(self, title="Save World Entry", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("entry_id", socket_type="str", optional=True)
        self.add_input("text", socket_type="str", optional=True)
        self.add_input("meta", socket_type="dict", optional=True)

        self.set_property("entry_id", UNRESOLVED)
        self.set_property("text", UNRESOLVED)
        self.set_property("meta", {})
        self.set_property("create_pin", False)

        self.add_output("entry_id", socket_type="str")
        self.add_output("text", socket_type="str")
        self.add_output("meta", socket_type="dict")

    async def run(self, state: GraphState):
        entry_id = self.require_input("entry_id")
        text = self.require_input("text")
        meta = self.get_input_value("meta")
        create_pin = self.get_property("create_pin")

        await self.world_state_manager.save_world_entry(
            entry_id, text, meta, create_pin
        )

        self.set_output_values({"entry_id": entry_id, "text": text, "meta": meta})


# WORLD STATE TEMPLATES


@register("scene/worldstate/templates/Spices")
class Spices(Node):
    """
    Node that returns a Spices object

    Inputs:

    - spice_values: list of strings

    Outputs:

    - spices: list of strings
    """

    class Fields:
        spice_values = PropertyField(
            name="spice_values",
            description="The list of spices",
            type="list",
            default=[],
        )

    def __init__(self, title="Spices", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("spice_values", socket_type="list", optional=True)

        self.set_property("spice_values", [])

        self.add_output("spices", socket_type="list")

    async def run(self, state: GraphState):
        spice_values = self.get_input_value("spice_values")

        spices = content.Spices(spices=spice_values)

        self.set_output_values({"spices": spices})


@register("scene/worldstate/templates/WritingStyle")
class WritingStyle(Node):
    """
    Node that returns a WritingStyle object

    Inputs:

    - instructions: Writing style instructions

    Outputs:

    - writing_style: The writing style to apply to the generation options
    """

    class Fields:
        instructions = PropertyField(
            name="instructions",
            description="Writing style instructions",
            type="text",
            default=UNRESOLVED,
        )

    def __init__(self, title="Writing Style", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("instructions", socket_type="str", optional=True)

        self.set_property("instructions", "")

        self.add_output("writing_style", socket_type="writing_style")

    async def run(self, state: GraphState):
        instructions = self.require_input("instructions")

        writing_style = content.WritingStyle(instructions=instructions)

        self.set_output_values({"writing_style": writing_style})


@register("scene/worldstate/templates/GenerationOptions")
class GenerationOptions(Node):
    """
    Node that returns a GenerationOptions object

    Inputs:

    - spices: The spices to apply to the generation options
    - spice_level: The spice level to apply to the generation options
    - writing_style: The writing style to apply to the generation options

    Properties:

    - spice_level: The spice level to apply to the generation options
    - writing_style: The writing style to apply to the generation options

    Outputs:

    - generation_options: The generation options
    """

    class Fields:
        spices = PropertyField(
            name="spices",
            description="The spices to apply to the generation options",
            type="spices",
            default=UNRESOLVED,
        )

        spice_level = PropertyField(
            name="spice_level",
            description="The spice level to apply to the generation options",
            type="number",
            default=0.0,
            min=0.0,
            max=1.0,
            step=0.1,
        )

        writing_style = PropertyField(
            name="writing_style",
            description="The writing style to apply to the generation options",
            type="writing_style",
            default=UNRESOLVED,
        )

    def __init__(self, title="Generation Options", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("spices", socket_type="generation_options", optional=True)
        self.add_input("spice_level", socket_type="number", optional=True)
        self.add_input("writing_style", socket_type="writing_style", optional=True)

        self.set_property("spice_level", 0.0)
        self.set_property("writing_style", "")

        self.add_output("generation_options", socket_type="generation_options")

    async def run(self, state: GraphState):
        spices = self.normalized_input_value("spices")
        spice_level = self.normalized_input_value("spice_level")
        writing_style = self.normalized_input_value("writing_style")

        generation_options = content.GenerationOptions(
            spices=spices, spice_level=spice_level, writing_style=writing_style
        )

        self.set_output_values({"generation_options": generation_options})
