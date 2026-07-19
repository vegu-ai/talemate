import structlog
from typing import TYPE_CHECKING
from talemate.game.engine.nodes.core import (
    Node,
    register,
    GraphState,
    PropertyField,
    InputValueError,
)
from talemate.agents.base import DynamicInstruction
from talemate.context import active_scene
from talemate.game.engine.context_id import (
    ContextIDItem,
    ContextIDScanResult,
    ContextIDMeta,
    context_id_item_from_string,
    compress_name,
    get_meta_groups,
    scan_text_for_context_ids,
)
from talemate.prompts import Prompt

if TYPE_CHECKING:
    from talemate.character import Character
    from talemate.tale_mate import Scene
    from talemate.world_state.manager import WorldStateManager

log = structlog.get_logger("talemate.game.engine.nodes.context_id")


@register("context_id/RenderContextIDs")
class RenderContextIDs(Node):
    """
    Render a list of context ID items to prompt-ready text using the
    `common.context_id_items` prompt template.

    A single item may be passed instead of a list and will be wrapped
    automatically.

    Inputs:

    - items: List of context ID items to render (a single item is also accepted)

    Properties:

    - display_mode: How to format the rendered items (compact, subsection, or normal)

    Outputs:

    - items: The list of items that was rendered
    - rendered: The rendered text
    """

    class Fields:
        display_mode = PropertyField(
            name="display_mode",
            description="Display mode",
            type="str",
            default="compact",
            choices=["compact", "subsection", "normal"],
        )

    def __init__(self, title="Render Context IDs", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("items", socket_type="list,context_id_item")
        self.set_property("display_mode", "compact")
        self.add_output("items", socket_type="list")
        self.add_output("rendered", socket_type="str")

    async def run(self, state: GraphState):
        items = self.require_input("items")
        display_mode = self.get_property("display_mode")

        if not isinstance(items, list):
            items = [items]

        prompt = Prompt.get(
            "common.context_id_items",
            vars={"items": items, "display_mode": display_mode},
        )
        prompt.dedupe_enabled = False
        rendered = prompt.render()

        self.set_output_values({"items": items, "rendered": rendered})


@register("context_id/CharacterContextIDs")
class CharacterContext(Node):
    """
    Unpack a character into context ID items for its various context entries
    (attributes, details, description, acting instructions and example dialogue).

    Inputs:

    - character: The character to get context ID items for

    Outputs:

    - character: The character input, passed through
    - attributes: List of context ID items for the character's attributes
    - details: List of context ID items for the character's details
    - description: Context ID item for the character's description
    - acting_instructions: Context ID item for the character's acting instructions
    - example_dialogue: List of context ID items for the character's example dialogue
    """

    def __init__(self, title="Character Context IDs", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_output("character", socket_type="character")
        self.add_output("attributes", socket_type="list")
        self.add_output("details", socket_type="list")
        self.add_output("description", socket_type="context_id_item")
        self.add_output("acting_instructions", socket_type="context_id_item")
        self.add_output("example_dialogue", socket_type="list")

    async def run(self, state: GraphState):
        character: "Character" = self.require_input("character")
        attributes = list(character.context.attributes)
        details = list(character.context.details)
        description = character.context.description
        acting_instructions = character.context.acting_instructions
        example_dialogue = list(character.context.example_dialogue_items)
        self.set_output_values(
            {
                "character": character,
                "attributes": attributes,
                "details": details,
                "description": description,
                "acting_instructions": acting_instructions,
                "example_dialogue": example_dialogue,
            }
        )


@register("context_id/ScanContextIDs")
class ScanContextIDs(Node):
    """
    Scan text for context ID references, resolve them against the active scene
    and return the results in various formats.

    Resolved items are rendered through the `common.context_id_items` prompt
    template and also wrapped in a dynamic instruction that can be injected
    into agent prompts.

    Inputs:

    - text: The text to scan for context IDs

    Properties:

    - header: The header (title) of the generated dynamic instruction
    - display_mode: How to format the rendered items (compact, subsection, or normal)

    Outputs:

    - dynamic_instruction: Dynamic instruction containing the rendered context items
    - rendered: The rendered text of the resolved items
    - context_id_items: List of resolved context ID items
    - unresolved: List of context ID references that could not be resolved
    """

    class Fields:
        header = PropertyField(
            name="header",
            description="The header of the dynamic instruction",
            type="str",
            default="Relevant Context",
        )
        display_mode = PropertyField(
            name="display_mode",
            description="The display mode of the dynamic instruction",
            type="str",
            default="compact",
            choices=["compact", "subsection", "normal"],
        )

    def __init__(self, title="Scan Context IDs", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("text", socket_type="str")
        self.set_property("header", "Relevant Context")
        self.set_property("display_mode", "compact")
        self.add_output("dynamic_instruction", socket_type="dynamic_instruction")
        self.add_output("rendered", socket_type="str")
        self.add_output("context_id_items", socket_type="list")
        self.add_output("unresolved", socket_type="list")

    async def run(self, state: GraphState):
        text = self.require_input("text")
        scene: "Scene" = active_scene.get()
        result: ContextIDScanResult = await scan_text_for_context_ids(text, scene)
        display_mode = self.get_property("display_mode")

        prompt = Prompt.get(
            "common.context_id_items",
            vars={"items": result.resolved, "display_mode": display_mode},
        )
        prompt.dedupe_enabled = False
        rendered = prompt.render()

        dynamic_instruction = DynamicInstruction(
            title=self.get_property("header"),
            content=rendered,
        )

        self.set_output_values(
            {
                "context_id_items": result.resolved,
                "unresolved": result.unresolved,
                "dynamic_instruction": dynamic_instruction,
                "rendered": rendered,
            }
        )


@register("context_id/CompressContextIDPart")
class CompressContextIDPart(Node):
    """
    Compress a context ID part name into the short hash identifier used inside
    context IDs (truncated SHA256).

    Inputs:

    - part: The part name to compress

    Outputs:

    - uncompressed: Intended to carry the original part; currently emits the compressed value as well
    - compressed: The compressed part
    """

    def __init__(self, title="Compress Context ID Part", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("part", socket_type="str")
        self.add_output("uncompressed", socket_type="str")
        self.add_output("compressed", socket_type="str")

    async def run(self, state: GraphState):
        part = self.require_input("part")
        part = compress_name(part)
        self.set_output_values({"uncompressed": part, "compressed": part})


@register("context_id/PathToContextID")
class PathToContextID(Node):
    """
    Resolve a context ID path string into a context ID item and retrieve its
    current value from the active scene.

    Inputs:

    - path: The context ID path to resolve

    Outputs:

    - context_id: The resolved context ID (None if the path could not be resolved)
    - context_id_item: The resolved context ID item (None if the path could not be resolved)
    - human_id: Human readable identifier of the resolved item
    - as_dict: The resolved item as a dictionary (empty if not resolved)
    - name: The name of the resolved item
    - value: The current value stored at the context ID
    - exists: Whether the path resolved to an existing context ID item
    - context_type: The context type of the resolved item
    - path: The path input, passed through
    """

    class Fields:
        path = PropertyField(
            name="path",
            description="The path to convert to a context ID",
            type="str",
            default="",
        )

    def __init__(self, title="Path to Context ID", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("path", socket_type="str")
        self.set_property("path", "")
        self.add_output("context_id", socket_type="context_id")
        self.add_output("context_id_item", socket_type="context_id_item")
        self.add_output("human_id", socket_type="str")
        self.add_output("as_dict", socket_type="dict")
        self.add_output("name", socket_type="str")
        self.add_output("value", socket_type="any")
        self.add_output("exists", socket_type="bool")
        self.add_output("context_type", socket_type="str")
        self.add_output("path", socket_type="str")

    async def run(self, state: GraphState):
        path = self.normalized_input_value("path")
        scene: "Scene" = active_scene.get()
        context_id_item: ContextIDItem | None = await context_id_item_from_string(
            path, scene
        )
        context_id = None
        return_dict = {}
        exists = False

        if context_id_item:
            return_dict = context_id_item.model_dump()
            value = await context_id_item.get(scene)
            context_id = context_id_item.context_id
            exists = True
        else:
            return_dict = {}
            value = None

        self.set_output_values(
            {
                "context_id": context_id,
                "context_id_item": context_id_item,
                "human_id": context_id_item.human_id if context_id_item else None,
                "as_dict": return_dict,
                "name": context_id_item.name if context_id_item else None,
                "value": value,
                "exists": exists,
                "path": path,
                "context_type": context_id_item.context_type
                if context_id_item
                else None,
            }
        )


@register("context_id/ContextIDMetaEntries")
class ContextIDMetaEntries(Node):
    """
    Get all defined context ID meta entries for the active scene, sorted by
    context ID.

    Properties:

    - filter_creative: If true, only include meta entries flagged as creative

    Outputs:

    - meta_entries: List of context ID meta entries
    - context_id_types: List of unique context ID types found in the entries
    """

    class Fields:
        filter_creative = PropertyField(
            name="filter_creative",
            description="Filter creative context ID meta entries",
            type="bool",
            default=False,
        )

    def __init__(self, title="Context ID Meta Entries", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("meta_entries", socket_type="list")
        self.set_property("filter_creative", False)
        self.add_output("context_id_types", socket_type="list")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        filter_creative = self.get_property("filter_creative")

        def filter_fn(meta: ContextIDMeta):
            if filter_creative:
                return meta.creative
            return True

        meta_groups = await get_meta_groups(scene, filter_fn)
        meta_entries = []
        context_id_types = set()
        for group in meta_groups.values():
            for entry in group:
                meta_entries.append(entry)
                context_id_types.add(entry.context_id.split(":")[0])

        # sort by context_id
        meta_entries.sort(key=lambda x: str(x.context_id))

        self.set_output_values(
            {"meta_entries": meta_entries, "context_id_types": list(context_id_types)}
        )


@register("context_id/ContextIDGetValue")
class ContextIDGetValue(Node):
    """
    Get the value of a context ID
    """

    def __init__(self, title="Context ID Get Value", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("context_id_item", socket_type="context_id_item")
        self.add_output("context_id_item", socket_type="context_id_item")
        self.add_output("value", socket_type="any")

    async def run(self, state: GraphState):
        context_id_item: ContextIDItem = self.require_input("context_id_item")
        value = await context_id_item.get(active_scene.get())
        self.set_output_values({"context_id_item": context_id_item, "value": value})


class ContextIDActionBase(Node):
    """
    A base node for actions on a context ID
    """

    class Fields:
        path = PropertyField(
            name="path",
            description="The path to the context ID item",
            type="str",
            default="",
        )

    @property
    def world_state_manager(self) -> "WorldStateManager":
        return active_scene.get().world_state_manager

    def setup(self):
        self.add_input("state")
        self.add_input(
            "context_id_item",
            socket_type="context_id_item",
            optional=True,
            group="context_id_item",
        )
        self.add_input(
            "path", socket_type="str", optional=True, group="context_id_item"
        )
        self.set_property("path", "")
        self.add_output("state")
        self.add_output("context_id_item", socket_type="context_id_item")
        self.add_output("path", socket_type="str")

    async def validate_context_id_item(self) -> ContextIDItem | None:
        context_id_item: ContextIDItem | None = self.normalized_input_value(
            "context_id_item"
        )
        path = self.normalized_input_value("path")
        if not context_id_item and not path:
            raise InputValueError(
                self, "context_id_item", "Either context_id_item or path must be set"
            )
        if not context_id_item:
            context_id_item = await context_id_item_from_string(
                path, active_scene.get()
            )
        return context_id_item

    async def run(self, state: GraphState):
        path = self.normalized_input_value("path")
        context_id_item: ContextIDItem | None = await self.validate_context_id_item()
        self.set_output_values(
            {"state": state, "context_id_item": context_id_item, "path": path}
        )


@register("context_id/ContextIDSetValue")
class ContextIDSetValue(ContextIDActionBase):
    """
    Set the value of a context ID entry in the active scene.

    The target entry can be given either as a context ID item or as a path
    string (one of the two must be set). Raises an error if the entry cannot
    be resolved.

    Inputs:

    - state: The graph state
    - context_id_item: The context ID item to set the value for (optional)
    - path: The context ID path to set the value for (optional)
    - value: The value to set

    Outputs:

    - state: The state input, passed through
    - context_id_item: The context ID item that was set
    - path: The path input, passed through
    - value: The value that was set
    """

    class Fields:
        path = PropertyField(
            name="path",
            description="The path to set the value for",
            type="str",
            default="",
        )

    def __init__(self, title="Context ID Set Value", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("value", socket_type="any")
        self.add_output("value", socket_type="any")

    async def run(self, state: GraphState):
        await super().run(state)
        context_id_item: ContextIDItem | None = await self.validate_context_id_item()
        value = self.require_input("value")
        scene: "Scene" = active_scene.get()
        path = self.normalized_input_value("path")

        if not context_id_item:
            raise InputValueError(
                self,
                "context_id_item",
                f"Context ID item `{path}` not found / unobtainable",
            )

        await context_id_item.set(scene, value)

        self.set_output_values(
            {
                "context_id_item": context_id_item,
                "value": value,
                "state": self.get_input_value("state"),
                "path": path,
            }
        )


@register("context_id/SetPin")
class SetPin(ContextIDActionBase):
    """
    Create or update a world state pin for a context entry, pinning it into the
    AI context. The target entry can be given either as a context ID item or as
    a path (one of the two must be set).

    Inputs:

    - state: The graph state
    - context_id_item: The context ID item to pin (optional)
    - path: The context ID path to pin (optional)
    - condition: AI-evaluated condition that determines whether the pin is active (optional)
    - condition_state: The current evaluation state of the condition (optional)
    - active: Whether the pin is active (optional)
    - decay: Number of cycles the pin remains active once set, 0 for no decay (optional)

    Outputs:

    - state: The state input, passed through
    - context_id_item: The context ID item that was pinned
    - path: The path input, passed through
    - condition: The condition that was set
    - condition_state: The condition state that was set
    - active: The active state that was set
    - decay: The decay that was set
    """

    class Fields(ContextIDActionBase.Fields):
        condition = PropertyField(
            name="condition",
            description="The condition to set the pin",
            type="str",
            default="",
        )
        condition_state = PropertyField(
            name="condition_state",
            description="The condition state to set the pin",
            type="bool",
            default=False,
        )
        active = PropertyField(
            name="active",
            description="The active state to set the pin",
            type="bool",
            default=False,
        )
        decay = PropertyField(
            name="decay",
            description="Number of cycles the pin remains active once set",
            type="int",
            default=0,
        )

    def __init__(self, title="Set Pin", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("condition", socket_type="str", optional=True)
        self.add_input("condition_state", socket_type="bool", optional=True)
        self.add_input("active", socket_type="bool", optional=True)
        self.add_input("decay", socket_type="int", optional=True)

        self.set_property("condition", "")
        self.set_property("condition_state", False)
        self.set_property("active", False)
        self.set_property("decay", 0)

        self.add_output("condition", socket_type="str")
        self.add_output("condition_state", socket_type="bool")
        self.add_output("active", socket_type="bool")
        self.add_output("decay", socket_type="int")

    async def run(self, state: GraphState):
        await super().run(state)

        context_id_item: ContextIDItem | None = await self.validate_context_id_item()
        condition: str | None = self.normalized_input_value("condition")
        condition_state: bool | None = self.normalized_input_value("condition_state")
        active: bool | None = self.normalized_input_value("active")
        decay: int | None = self.normalized_input_value("decay")
        scene: "Scene" = active_scene.get()

        manage: "WorldStateManager" = scene.world_state_manager
        await manage.set_pin(
            entry_id=context_id_item,
            condition=condition,
            condition_state=condition_state,
            active=active,
            decay=(decay if decay and decay > 0 else None),
        )

        await scene.load_active_pins()

        self.set_output_values(
            {
                "state": state,
                "context_id_item": context_id_item,
                "condition": condition,
                "condition_state": condition_state,
                "active": active,
                "decay": decay,
            }
        )


@register("context_id/RemovePin")
class RemovePin(ContextIDActionBase):
    """
    Remove the world state pin for a context entry and reload the scene's
    active pins.

    The target entry can be given either as a context ID item or as a path
    string (one of the two must be set).

    Inputs:

    - state: The graph state
    - context_id_item: The context ID item to unpin (optional)
    - path: The context ID path to unpin (optional)

    Outputs:

    - state: The state input, passed through
    - context_id_item: The context ID item that was unpinned
    - path: The path input, passed through
    """

    def __init__(self, title="Remove Pin", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        await super().run(state)
        path = self.normalized_input_value("path")
        context_id_item: ContextIDItem | None = await self.validate_context_id_item()
        world_state_manager: "WorldStateManager" = self.world_state_manager
        scene: "Scene" = active_scene.get()
        await world_state_manager.remove_pin(context_id_item.memory_id)
        await scene.load_active_pins()

        self.set_output_values(
            {"state": state, "context_id_item": context_id_item, "path": path}
        )


@register("context_id/IsPinActive")
class IsPinActive(ContextIDActionBase):
    """
    Check whether the world state pin for a context entry is currently active.

    The target entry can be given either as a context ID item or as a path
    string (one of the two must be set).

    Inputs:

    - state: The graph state
    - context_id_item: The context ID item to check (optional)
    - path: The context ID path to check (optional)

    Outputs:

    - state: The state input, passed through
    - context_id_item: The context ID item that was checked
    - path: The path input, passed through
    - active: Whether the pin is active
    """

    def __init__(self, title="Is Pin Active", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_output("active", socket_type="bool")

    async def run(self, state: GraphState):
        await super().run(state)
        context_id_item: ContextIDItem | None = await self.validate_context_id_item()
        world_state_manager: "WorldStateManager" = self.world_state_manager
        is_active = await world_state_manager.is_pin_active(context_id_item.memory_id)
        self.set_output_values(
            {"state": state, "context_id_item": context_id_item, "active": is_active}
        )
