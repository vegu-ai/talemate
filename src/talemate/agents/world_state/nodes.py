import re
import structlog
from typing import ClassVar, TYPE_CHECKING
from talemate.context import active_scene
from talemate.game.engine.nodes.core import (
    GraphState,
    InputValueError,
    Node,
    PropertyField,
    UNRESOLVED,
    TYPE_CHOICES,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode
from talemate.game.engine.nodes.prompt import GenerateResponse
import talemate.game.focal as focal
from talemate.util.time import coerce_ts
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


@register("agents/world_state/DetermineVisual")
class DetermineVisual(GenerateResponse):
    """
    Picks the existing portrait or scene background that fits a message.
    With World State → Character Portraits (or Scene Backgrounds) → Use
    Decision Model on, the decision model keeps the current one or picks
    another existing one when it is sure. Otherwise the supplied prompt runs
    through Generate Response.

    Inputs:

    - character: The character whose portrait is picked (portraits only)
    - content: The message to pick for
    - assets: The existing portraits or backgrounds to pick from

    Properties:

    - kind: portrait or background

    Other inputs and outputs match Generate Response. The extracted asset_id
    is the picked asset; an empty one from the usual request may ask for a
    new image. The other extracted values come from that request and are
    missing when the decision model decided. An extracted `references` text
    becomes the list of the given assets' ids it names.
    """

    class Fields(GenerateResponse.Fields):
        kind = PropertyField(
            name="kind",
            description="Pick a portrait or a scene background",
            type="str",
            default="portrait",
            choices=["portrait", "background"],
        )

    def __init__(self, title="Determine Visual", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("character", socket_type="character", optional=True)
        self.add_input("content", socket_type="str")
        self.add_input("assets", socket_type="list")
        self.set_property("kind", "portrait")

    async def run(self, state: GraphState):
        agent = self.require_input("agent")
        kind = self.get_property("kind")
        character = self.normalized_input_value("character")
        if kind == "portrait" and character is None:
            raise InputValueError(self, "character", "Portraits need a character.")
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "agent": agent,
                "prompt": self.require_input("prompt"),
                "response_spec": self.normalized_input_value("response_spec"),
                "response": "",
                "rendered_prompt": "",
                "captured_context": "",
                "data_obj": None,
            }
        )
        extracted = {}

        async def fallback(ids):
            await super(DetermineVisual, self).run(state)
            extracted.update(self.get_output_socket("extracted").value or {})
            return {ids[0]: extracted.get("asset_id")}

        assets = self.require_input("assets")
        asset_id = await agent.determine_visual_with_decisions(
            kind,
            self.require_input("content"),
            assets,
            fallback,
            character=character,
        )
        if isinstance(extracted.get("references"), str):
            ids = {asset.id for asset in assets}
            extracted["references"] = [
                ref
                for ref in re.split(r"[\s,`]+", extracted["references"])
                if ref in ids
            ]
        self.set_output_values({"extracted": {**extracted, "asset_id": asset_id}})


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

    - character_sheet: The extracted character sheet (dict, empty if the model produced nothing)
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
    Sets up (or updates) a tracked state reinforcement for a character or
    the world in general. Adds the reinforcement to the scene's world
    state, then immediately runs an update, producing a reinforcement
    message.

    Inputs:

    - state: The current state of the graph
    - query_or_detail: The question or detail to track
    - character: The character to track the state for (optional; when
      omitted the state is tracked for the world in general)
    - instructions: Additional instructions for the reinforcement (optional)

    Properties:

    - interval: How many rounds pass between automatic re-evaluations
    - insert_method: How the reinforcement is inserted into the context
    - reset: If the tracked state should be reset

    Outputs:

    - state: graph state
    - message: state reinforcement message
    - reinforcement: the reinforcement that was added or updated
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

        reinforcement = await scene.world_state.add_reinforcement(
            question=query_or_detail,
            character=character.name if character else None,
            instructions=instructions,
            interval=interval,
            insert=insert_method,
        )

        message = await self.agent.update_reinforcement(
            question=query_or_detail, character=character, reset=reset
        )

        self.set_output_values(
            {"state": state, "message": message, "reinforcement": reinforcement}
        )


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

    World State → Yes/No Queries → Use Decision Model answers confident queries
    with the configured decision model. Uncertain or failed decisions use the
    usual LLM request. With the option off or no decision model, only the LLM is used.

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


def snapshot_values(world_state) -> dict:
    return {
        "characters": {
            name: entry.model_dump() for name, entry in world_state.characters.items()
        },
        "items": {
            name: entry.model_dump() for name, entry in world_state.items.items()
        },
        "places": {
            name: entry.model_dump() for name, entry in world_state.places.items()
        },
        "location": world_state.location,
    }


@register("agents/world_state/AddSnapshotEntity")
class AddSnapshotEntity(AgentNode):
    """
    Add a person, object or place named in a message to the world snapshot
    and keep it tracked, as selecting text in a message and choosing Add to
    world state does. One analysis request; the model may find no distinct
    entity in the text, and then nothing is added. Like the UI add, it
    cancels a running snapshot refresh; run from a listener of the
    snapshot's own events, it adds without cancelling it.

    Inputs:

    - state: graph state (passthrough)
    - message: the message the text comes from (or give message_id)
    - message_id: the message id (or give message)
    - text: the text that names the entity

    Outputs:

    - state: graph state
    - resolved: True when an entity was added
    - name: the entity name
    - kind: character, item or place
    - in_moment: True when the message is in the snapshot's current moment
    - mentions: phrases of the message marked as the entity
    - waiting_for_regeneration: True when nothing ran because the snapshot is being regenerated
    """

    _agent_name: ClassVar[str] = "world_state"

    def __init__(self, title="Add Snapshot Entity", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("message", socket_type="message_object", optional=True)
        self.add_input("message_id", socket_type="int", optional=True)
        self.add_input("text", socket_type="str")
        self.set_property("message_id", 0)
        self.add_output("state")
        self.add_output("resolved", socket_type="bool")
        self.add_output("name", socket_type="str")
        self.add_output("kind", socket_type="str")
        self.add_output("in_moment", socket_type="bool")
        self.add_output("mentions", socket_type="list")
        self.add_output("waiting_for_regeneration", socket_type="bool")

    async def run(self, state: GraphState):
        if not self.agent.can_add_snapshot_entity:
            raise InputValueError(
                self,
                "text",
                "The world state agent cannot update the world snapshot now.",
            )
        message = self.normalized_input_value("message")
        message_id = (
            message.id
            if message is not None
            else self.normalized_input_value("message_id")
        )
        if not message_id:
            raise InputValueError(self, "message_id", "Give a message or a message_id.")
        try:
            result = await self.agent.add_snapshot_entity_in_slot(
                message_id, self.require_input("text")
            )
        except ValueError as exc:
            raise InputValueError(self, "text", str(exc)) from exc
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "resolved": result.resolved,
                "name": result.name or None,
                "kind": result.kind or None,
                "in_moment": result.in_moment,
                "mentions": list(result.mentions),
                "waiting_for_regeneration": result.waiting_for_regeneration,
            }
        )


@register("agents/world_state/GetSnapshot")
class GetSnapshot(Node):
    """
    The current world snapshot, as the World State panel shows it. Reads the
    stored snapshot; it does not refresh it.

    Outputs:

    - characters: name to state (snapshot, emotion, mentions) for each character
    - items: name to state (snapshot, mentions) for each item
    - places: name to state (snapshot, mentions) for each place
    - location: the location description, or None
    """

    def __init__(self, title="Get Snapshot", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("characters", socket_type="dict")
        self.add_output("items", socket_type="dict")
        self.add_output("places", socket_type="dict")
        self.add_output("location", socket_type="str")

    async def run(self, state: GraphState):
        self.set_output_values(snapshot_values(active_scene.get().world_state))


@register("agents/world_state/RequestWorldState")
class RequestWorldState(AgentNode):
    """
    Requests the current world state.

    Inputs:

    - state: The current state of the graph

    Outputs:

    - state: The current state
    - world_state: The world snapshot after the update: characters, items, places and location
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
        await scene.world_state.request_update()

        self.set_output_values(
            {"state": state, "world_state": snapshot_values(scene.world_state)}
        )


@register("agents/world_state/EmitWorldState")
class EmitWorldState(AgentNode):
    """
    Re-emits the scene's current world state to the frontend so the world
    state UI refreshes. Does not regenerate or update the world state.

    Inputs:

    - state: The graph state

    Outputs:

    - state: The state input, passed through
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
    Determines character development (new, updated or removed attributes,
    description updates) via the world_state agent and processes the
    resulting proposals. With as_suggestions enabled the proposals are
    added to the world state manager as suggestions for the user to
    review; otherwise they are applied to the character directly.

    Inputs:

    - state: The graph state
    - character: The character to progress
    - instructions: Instructions guiding the development (required at
      runtime despite the optional socket)

    Properties:

    - as_suggestions: Whether to store proposals as suggestions instead of
      applying them directly

    Outputs:

    - state: The state input, passed through
    - calls: The list of proposal calls that were generated
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
    Advances the scene time by the given number of seconds. Pushes a
    TimePassageMessage to the scene history, emits it to the UI and fires
    the time passage signal (which other agents may react to, e.g. to
    narrate the time passage using the narration instructions).

    Inputs:

    - state: The graph state
    - duration: The duration to advance in seconds (e.g. 3600 for an hour)
    - narration_instructions: Instructions for narrating the time passage
      (optional)
    - chapter_title: Names the chapter this time passage opens (optional)

    Outputs:

    - state: The state input, passed through
    - duration: The duration of the emitted message
    - narration_instructions: The narration instructions, passed through
    - message: The TimePassageMessage that was added to the history
    """

    _agent_name: ClassVar[str] = "world_state"  #

    class Fields:
        duration = PropertyField(
            name="duration",
            description="The duration to advance, in seconds",
            type="int",
            default=1,
            min=0,
            step=1,
        )
        narration_instructions = PropertyField(
            name="narration_instructions",
            description="The instructions for the narration",
            type="str",
            default="",
        )
        chapter_title = PropertyField(
            name="chapter_title",
            description="Names the chapter this time passage opens",
            type="str",
            default="",
        )

    def __init__(self, title="Advance Time", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("duration", socket_type="int")
        self.add_input("narration_instructions", socket_type="str", optional=True)
        self.add_input("chapter_title", socket_type="str", optional=True)

        self.set_property("narration_instructions", "")
        self.set_property("chapter_title", "")
        self.set_property("duration", 1)

        self.add_output("state")
        self.add_output("duration", socket_type="int")
        self.add_output("narration_instructions", socket_type="str")
        self.add_output("message", socket_type="message")

    async def run(self, state: GraphState):
        # saved graphs may still carry a legacy ISO8601 duration string
        duration: int = coerce_ts(self.normalized_input_value("duration"))
        narration_instructions: str = self.normalized_input_value(
            "narration_instructions"
        )
        chapter_title: str = self.normalized_input_value("chapter_title")
        message = await self.agent.advance_time(
            duration, narration_instructions, chapter_title or None
        )
        self.set_output_values(
            {
                "state": state,
                "duration": message.ts,
                "narration_instructions": narration_instructions,
                "message": message,
            }
        )
