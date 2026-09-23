import re
from enum import Enum
from typing import Any, Union

import structlog
from pydantic import BaseModel, Field, PrivateAttr, model_serializer, model_validator

import talemate.instance as instance
from talemate.emit import emit
from talemate.prompts import Prompt
import talemate.game.focal.schema as focal_schema
from talemate.game.schema import ConditionGroup
from talemate.knowledge.schema import (
    EntryVisibility,
    KnowledgeEdge,
    ReinforcementEntry,
)
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.snapshot_models import SnapshotPerspectives
from talemate.knowledge.snapshots import snapshot_for
from talemate.scene_message import ReinforcementMessage
from talemate.knowledge.perspectives import source_reference, source_deleted
from talemate.knowledge.reinforcements import (
    reinforcement_context,
    entry_binding,
    reinforcement_entry_context,
    prepare_reinforcement_sources,
    prepare_reinforcement_source,
    write_reinforcement_entry,
)
from talemate.world_state.schema import (
    CharacterState,
    ObjectState,
    PlaceState,
)
from talemate.world_state.snapshot_revision import SnapshotProvenance, SnapshotRevision

__all__ = [
    "CharacterState",
    "ObjectState",
    "PlaceState",
    "WorldStateResponse",
    "WorldState",
    "Reinforcement",
    "ContextPin",
    "ManualContext",
    "Suggestion",
    "InsertionMode",
    "ANY_CHARACTER",
    "INTRO_ANCHOR_ID",
]

ANY_CHARACTER = "__any_character__"

# The anchor id of the scene intro, which is not a scene message. Message ids
# start at 1, so 0 is never taken and orders before every message — a later
# TimePassage cuts a snapshot anchored on the intro. The frontend mirrors it in
# talemate_frontend/src/components/EntityHighlightMixin.js.
INTRO_ANCHOR_ID = 0

log = structlog.get_logger("talemate")


class WorldStateResponse(BaseModel):
    """
    Result of WorldStateAgent.request_world_state.

    `world_state` is the raw parsed JSON payload from the LLM (or None if
    the agent short-circuited because nothing in the scene could be
    snapshotted). `anchor_message_ids` is the list of scene history message
    ids the snapshot was generated against — every one of them is a valid
    inline-highlight target. It holds `INTRO_ANCHOR_ID` when the scene intro
    was part of the current moment.

    `provenance` verifies the history supplied by the rendered template,
    which can extend beyond the focus after an asynchronous memory lookup.
    """

    world_state: Union[dict, None] = None
    anchor_message_ids: list[int] = Field(default_factory=list)
    audience_context: dict | None = Field(default=None, exclude=True)
    provenance: SnapshotProvenance | None = Field(default=None, exclude=True)


class InsertionMode(str, Enum):
    sequential = "sequential"
    conversation_context = "conversation-context"
    all_context = "all-context"
    never = "never"


class Reinforcement(BaseModel):
    question: str
    answer: Union[str, None] = None
    updated_ts: int | None = Field(
        default=None,
        description="Scene time when the answer was last set or confirmed.",
    )
    interval: int = 10
    due: int = 0
    character: Union[str, None] = None
    instructions: Union[str, None] = None
    insert: str = "sequential"
    require_active: bool = True
    perspective_source: ReinforcementMessage | None = None

    @model_serializer(mode="wrap")
    def serialize_perspective_source(self, handler):
        data = handler(self)
        if self.perspective_source is None:
            data.pop("perspective_source", None)
        if self.updated_ts is None:
            data.pop("updated_ts", None)
        return data

    def source_for(self, scene):
        if self.insert == "sequential":
            return next(
                (
                    message
                    for message in reversed(scene.history)
                    if isinstance(message, ReinforcementMessage)
                    and message.character_name == self.character
                    and message.question == self.question
                ),
                None,
            )
        return self.perspective_source

    def set_answer(self, scene, answer: str | None, *, confirmed: bool = True):
        if confirmed or answer != self.answer:
            self.updated_ts = scene.ts
        elif self.updated_ts is None:
            # A configuration change may replace the source that supplies this age.
            source = self.source_for(scene)
            if source and source.knowledge:
                self.updated_ts = source.knowledge.acquired.ts
        self.answer = answer

    def context_for(self, scene, viewer=None):
        return reinforcement_context(scene, self, viewer)

    @property
    def as_context_line(self) -> str:
        if self.character:
            if self.question.strip().endswith("?"):
                return f"{self.character}: {self.question} {self.answer}"
            else:
                return f"{self.character}'s {self.question}: {self.answer}"

        if self.question.strip().endswith("?"):
            return f"{self.question} {self.answer}"

        return f"{self.question}: {self.answer}"


class ManualContext(BaseModel):
    id: str
    text: str
    meta: dict[str, Any] = {}
    shared: bool = False
    visibility: EntryVisibility = Field(default_factory=EntryVisibility)
    reinforcement: ReinforcementEntry | None = None

    @model_serializer(mode="wrap")
    def serialize_reinforcement(self, handler):
        data = handler(self)
        if self.reinforcement is None:
            data.pop("reinforcement", None)
        return data


class ContextPin(BaseModel):
    entry_id: str
    condition: Union[str, None] = None
    condition_state: bool = False
    # If set, the pin becomes fully game-state controlled (no manual toggles, no decay).
    # Uses the same wire format as `src/talemate/game/schema.py`.
    gamestate_condition: list[ConditionGroup] | None = None
    active: bool = False
    # Optional decay configuration and countdown tracker
    # decay: how many condition-check cycles the pin stays active once activated
    # decay_due: the current remaining cycles before deactivation
    decay: Union[int, None] = None
    decay_due: Union[int, None] = None


class Suggestion(BaseModel):
    type: str
    name: str
    id: str
    proposals: list[focal_schema.Call] = Field(default_factory=list)

    def remove_proposal(self, uid: str):
        self.proposals = [
            proposal for proposal in self.proposals if proposal.uid != uid
        ]

    def merge(self, other: "Suggestion"):
        assert self.id == other.id, "Suggestion ids must match"

        # loop through proposals, and override existing proposals if ids match
        # otherwise append the new proposal
        for proposal in other.proposals:
            for idx, self_proposal in enumerate(self.proposals):
                if self_proposal.uid == proposal.uid:
                    self.proposals[idx] = proposal
                    break
            else:
                self.proposals.append(proposal)


class WorldState(BaseModel):
    # characters in the scene by name
    characters: dict[str, CharacterState] = {}

    # objects in the scene by name
    items: dict[str, ObjectState] = {}

    # places referenced in the scene by name (distinct from `location`)
    places: dict[str, PlaceState] = {}

    # location description
    location: Union[str, None] = None
    location_perspectives: SnapshotPerspectives | None = None

    @model_serializer(mode="wrap")
    def serialize_snapshot_perspectives(self, handler):
        data = handler(self)
        if self.location_perspectives is None:
            data.pop("location_perspectives", None)
        return data

    def snapshot_for(self, viewer=None):
        return snapshot_for(self.scene, viewer, world_state=self)

    def clear_snapshot_perspectives(self):
        self.location_perspectives = None
        for bucket in (self.characters, self.items, self.places):
            for entity in bucket.values():
                entity.perspectives = None

    def validate_snapshot_audiences(self, names):
        records = [self.location_perspectives]
        records.extend(
            entity.perspectives
            for bucket in (self.characters, self.items, self.places)
            for entity in bucket.values()
        )
        for record in records:
            if record and any(
                not set(view.audience) <= set(names) for view in record.views
            ):
                raise ValueError("Unresolved snapshot audience")

    # ids of the scene history messages the snapshot was generated against,
    # plus INTRO_ANCHOR_ID for the intro; each can render inline highlights.
    anchor_message_ids: list[int] = Field(default_factory=list)

    snapshot_provenance: SnapshotProvenance | None = None
    previous_snapshot: SnapshotRevision | None = None
    _snapshot_epoch: int = PrivateAttr(default=0)
    _snapshot_regenerating: bool = PrivateAttr(default=False)

    # reinforcers
    reinforce: list[Reinforcement] = []

    def prepare_reinforcement_perspectives(self):
        return prepare_reinforcement_sources(self.scene)

    def is_reinforcement_entry(self, entry_id):
        return entry_binding(self.scene, entry_id) is not None

    def reinforcement_entry_context(self, entry_id, viewer):
        return reinforcement_entry_context(self.scene, entry_id, viewer)

    # pins
    pins: dict[str, ContextPin] = {}

    # manual context
    manual_context: dict[str, ManualContext] = {}

    character_name_mappings: dict[str, list[str]] = {}

    suggestions: list[Suggestion] = Field(default_factory=list)

    # grant / revoke edges: the only per-character knowledge state that is stored
    knowledge: list[KnowledgeEdge] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_obsolete_fact_data(cls, data):
        """Development saves may carry the removed learned-facts store."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        fact_ids = set(data.pop("facts", {}) or {})
        for key in ("fact_counter", "topics", "topics_fact_count"):
            data.pop(key, None)
        edges = []
        for edge in data.get("knowledge", []):
            raw = edge.model_dump() if isinstance(edge, KnowledgeEdge) else edge
            if (
                raw.get("kind") != "unlearn"
                and raw.get("target") not in fact_ids
                and not raw.get("anchor")
            ):
                edges.append(edge)
        data["knowledge"] = edges
        return data

    @property
    def agent(self):
        return instance.get_agent("world_state")

    @property
    def scene(self):
        return self.agent.scene

    @property
    def pretty_json(self):
        return self.model_dump_json(indent=2)

    @property
    def as_list(self):
        return self.render().as_list

    def add_character_name_mappings(self, *names):
        self.character_name_mappings.extend([name.lower() for name in names])

    def normalize_name(self, name: str):
        """Normalizes item or character name away from variables style names

        Args:
            name (str): item or character name
        """
        name = name.lower().replace("_", " ").strip().title()
        # Fix possessive 's that title() capitalizes incorrectly (e.g., "John'S" -> "John's")
        name = re.sub(r"'S\b", "'s", name)
        return name

    def filter_reinforcements(
        self, character: str = ANY_CHARACTER, insert: list[str] = None
    ) -> list[Reinforcement]:
        """
        Returns a filtered list of Reinforcement objects based on character and insert criteria.

        Arguments:
        - character: The name of the character to filter reinforcements for. Use ANY_CHARACTER to include all.
        - insert: A list of insertion modes to filter reinforcements by.
        """
        """
        Returns a filtered set of results as list
        """

        result = []

        for reinforcement in self.reinforce:
            if not reinforcement.answer:
                continue

            if character != ANY_CHARACTER and reinforcement.character != character:
                continue

            if insert and reinforcement.insert not in insert:
                continue

            result.append(reinforcement)

        return result

    def reset(self):
        """
        Resets the WorldState instance to its initial state by clearing characters, items, places, location, and anchor.

        Arguments:
        - None
        """
        self.characters = {}
        self.items = {}
        self.places = {}
        self.location = None
        self.location_perspectives = None
        self.anchor_message_ids = []
        self.snapshot_provenance = None
        self.previous_snapshot = None
        self._snapshot_epoch += 1

    def emit(self, status="update"):
        """
        Emits the current world state with the given status.

        Arguments:
        - status: The status of the world state to emit, which influences the handling of the update event.
        """
        emit("world_state", status=status, data=self.model_dump())

    async def request_update(self, initial_only: bool = False, instructions: str = ""):
        """
        Public entry point for refreshing the world-state snapshot.

        Owns only the ``initial_only`` short-circuits; the generate-and-merge
        policy lives on the world_state agent
        (``WorldStateSnapshotMixin.apply_snapshot_update``), which this method
        delegates to.

        Arguments:
        - initial_only: When true, emit the current state without requesting a
          new one if characters already exist or automatic updates are off.
        - instructions: One-off guidance for this snapshot pass only.
        """

        if initial_only and self.characters:
            self.emit()
            return

        # if auto is true, we need to check if agent has automatic update enabled
        if initial_only and not self.agent.update_world_state_enabled:
            self.emit()
            return

        await self.agent.apply_snapshot_update(self, instructions=instructions)

    async def persist(self):
        """
        Persists the world state snapshots of characters and items into the memory agent.

        TODO: neeeds re-thinking.

        Its better to use state reinforcement to track states, persisting the small world
        state snapshots most of the time does not have enough context to be useful.

        Arguments:
        - None
        """

        memory = instance.get_agent("memory")

        # first we check if any of the characters were refered
        # to with an alias

        states = []
        scene = self.agent.scene

        for character_name in self.characters.keys():
            states.append(
                {
                    "text": f"{character_name}: {self.characters[character_name].snapshot}",
                    "id": f"{character_name}.world_state.snapshot",
                    "meta": {
                        "typ": "world_state",
                        "character": character_name,
                        "ts": scene.ts,
                    },
                }
            )

        for item_name in self.items.keys():
            states.append(
                {
                    "text": f"{item_name}: {self.items[item_name].snapshot}",
                    "id": f"{item_name}.world_state.snapshot",
                    "meta": {
                        "typ": "world_state",
                        "item": item_name,
                        "ts": scene.ts,
                    },
                }
            )

        log.debug("world_state.persist", states=states)

        if not states:
            return

        await memory.add_many(states)

    async def add_reinforcement(
        self,
        question: str,
        character: str = None,
        instructions: str = None,
        interval: int = 10,
        answer: str = "",
        insert: str = "sequential",
        require_active: bool = True,
        *,
        answer_confirmed: bool = True,
    ) -> Reinforcement:
        """
        Adds or updates a reinforcement in the world state. If a reinforcement with the same question and character exists, it is updated.

        Arguments:
        - question: The question or prompt associated with the reinforcement.
        - character: The character to whom the reinforcement is linked. If None, it applies globally.
        - instructions: Instructions related to the reinforcement.
        - interval: The interval for reinforcement repetition.
        - answer: The answer to the reinforcement question.
        - insert: The method of inserting the reinforcement into the context.
        - answer_confirmed: False for configuration-only saves; an unchanged answer keeps its age.
        """

        # if reinforcement already exists, update it

        idx, reinforcement = await self.find_reinforcement(question, character)

        if reinforcement:
            previous_source = reinforcement.source_for(self.scene)
            previous_reference = (
                source_reference(self.scene, "message", previous_source.id)
                if previous_source
                else None
            )
            # update the reinforcement object

            reinforcement.instructions = instructions
            reinforcement.interval = interval
            reinforcement.set_answer(self.scene, answer, confirmed=answer_confirmed)
            reinforcement.require_active = require_active

            old_insert_method = reinforcement.insert

            reinforcement.insert = insert
            if old_insert_method != insert and insert == "sequential":
                reinforcement.perspective_source = None
                source_deleted(self.scene, previous_reference)

            # find the reinforcement message i nthe scene history and update the answer
            if old_insert_method == "sequential":
                message = previous_source

                if old_insert_method != insert and message:
                    # if it used to be sequential we need to remove its ReinforcmentMessage
                    # from the scene history

                    self.scene.pop_history(
                        typ="reinforcement", meta_hash=message.meta_hash, all=True
                    )

                elif message:
                    message.message = answer
            elif insert == "sequential":
                # if it used to be something else and is now sequential, we need to run the state
                # next loop
                reinforcement.due = 0

            if character_knowledge_enabled(self.scene):
                source = prepare_reinforcement_source(self.scene, reinforcement)
                await write_reinforcement_entry(self.scene, reinforcement, source)
                self.emit()
                await instance.get_agent("summarizer").finalize_perceptions(
                    self.scene, []
                )
            elif character:
                character = self.agent.scene.get_character(character)
                await character.set_detail(question, answer)

            return reinforcement

        log.debug(
            "world_state.add_reinforcement",
            question=question,
            character=character,
            instructions=instructions,
            interval=interval,
            answer=answer,
            insert=insert,
        )

        reinforcement = Reinforcement(
            question=question,
            character=character,
            instructions=instructions,
            interval=interval,
            answer=answer,
            updated_ts=self.scene.ts if answer else None,
            insert=insert,
            require_active=require_active,
        )

        self.reinforce.append(reinforcement)

        self.emit()
        if answer and character_knowledge_enabled(self.scene):
            await instance.get_agent("summarizer").finalize_perceptions(self.scene, [])

        return reinforcement

    async def find_reinforcement(self, question: str, character: str = None):
        """
        Finds a reinforcement based on the question and character provided. Returns the index in the list and the reinforcement object.

        Arguments:
        - question: The question associated with the reinforcement to find.
        - character: The character to whom the reinforcement is linked. Use None for global reinforcements.
        """
        for idx, reinforcement in enumerate(self.reinforce):
            if (
                reinforcement.question == question
                and reinforcement.character == character
            ):
                return idx, reinforcement
        return None, None

    def reinforcements_for_character(self, character: str):
        """
        Returns a dictionary of reinforcements specifically for a given character.

        Arguments:
        - character: The name of the character for whom reinforcements should be retrieved.
        """
        reinforcements = {}

        for reinforcement in self.reinforce:
            if reinforcement.character == character:
                reinforcements[reinforcement.question] = reinforcement

        return reinforcements

    def reinforcements_for_world(self):
        """
        Returns a dictionary of global reinforcements not linked to any specific character.

        Arguments:
        - None
        """
        reinforcements = {}

        for reinforcement in self.reinforce:
            if not reinforcement.character:
                reinforcements[reinforcement.question] = reinforcement

        return reinforcements

    async def remove_reinforcement(self, idx: int):
        """
        Removes a reinforcement from the world state.

        Arguments:
        - idx: The index of the reinforcement to remove.
        """

        # find all instances of the reinforcement in the scene history
        # and remove them

        reinforcement = self.reinforce[idx]
        # Avoid the knowledge.memory / instance import cycle.
        from talemate.knowledge.memory import invalidate_memory_audiences

        direct_source = reinforcement.perspective_source
        direct_reference = (
            source_reference(self.scene, "message", direct_source.id)
            if direct_source
            else None
        )

        self.agent.scene.pop_history(
            typ="reinforcement",
            character_name=reinforcement.character,
            question=reinforcement.question,
            all=True,
        )

        # Clean up associated data created by update_reinforcement
        if reinforcement.character:
            character = self.agent.scene.get_character(reinforcement.character)
            if character:
                await character.set_detail(reinforcement.question, None)
        else:
            if reinforcement.question in self.manual_context:
                if character_knowledge_enabled(self.scene):
                    await self.scene.world_state_manager.delete_context_db_entry(
                        reinforcement.question
                    )
                else:
                    del self.manual_context[reinforcement.question]

        self.reinforce.pop(idx)
        source_deleted(self.scene, direct_reference)
        invalidate_memory_audiences(self.scene)

    def render(self):
        """
        Renders the world state as a string.
        """

        return Prompt.get(
            "world_state.render",
            vars={
                "characters": self.characters,
                "items": self.items,
                "location": self.location,
            },
        )

    async def commit_to_memory(self, memory_agent, entry_ids: set[str] | None = None):
        def is_simple_type(value):
            """Check if value is a simple type that memory database accepts."""
            return isinstance(value, (int, str, float, bool, type(None)))

        await memory_agent.add_many(
            [
                {
                    **manual_context.model_dump(),
                    "meta": {
                        k: v
                        for k, v in manual_context.meta.items()
                        if is_simple_type(v)
                    },
                }
                for manual_context in self.manual_context.values()
                if entry_ids is None or manual_context.id in entry_ids
            ]
        )

    def manual_context_for_world(self) -> dict[str, ManualContext]:
        """
        Returns all manual context entries where meta["typ"] == "world_state"
        """

        return {
            manual_context.id: manual_context
            for manual_context in self.manual_context.values()
            if manual_context.meta.get("typ") == "world_state"
        }

    def character_emotion(self, character_name: str) -> str:
        if character_name in self.characters:
            return self.characters[character_name].emotion

        return None
