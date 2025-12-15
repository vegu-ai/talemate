import re
import traceback
from enum import Enum
from typing import Any, Union

import structlog
from pydantic import BaseModel, Field

import talemate.instance as instance
from talemate.emit import emit
from talemate.prompts import Prompt
from talemate.exceptions import GenerationCancelled
import talemate.game.focal.schema as focal_schema
from talemate.game.schema import ConditionGroup

ANY_CHARACTER = "__any_character__"

log = structlog.get_logger("talemate")


class CharacterState(BaseModel):
    snapshot: Union[str, None] = None
    emotion: Union[str, None] = None


class ObjectState(BaseModel):
    snapshot: Union[str, None] = None


class InsertionMode(str, Enum):
    sequential = "sequential"
    conversation_context = "conversation-context"
    all_context = "all-context"
    never = "never"


class Reinforcement(BaseModel):
    question: str
    answer: Union[str, None] = None
    interval: int = 10
    due: int = 0
    character: Union[str, None] = None
    instructions: Union[str, None] = None
    insert: str = "sequential"
    require_active: bool = True

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

    # location description
    location: Union[str, None] = None

    # reinforcers
    reinforce: list[Reinforcement] = []

    # pins
    pins: dict[str, ContextPin] = {}

    # manual context
    manual_context: dict[str, ManualContext] = {}

    character_name_mappings: dict[str, list[str]] = {}

    suggestions: list[Suggestion] = Field(default_factory=list)

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
        Resets the WorldState instance to its initial state by clearing characters, items, and location.

        Arguments:
        - None
        """
        self.characters = {}
        self.items = {}
        self.location = None

    def emit(self, status="update"):
        """
        Emits the current world state with the given status.

        Arguments:
        - status: The status of the world state to emit, which influences the handling of the update event.
        """
        emit("world_state", status=status, data=self.model_dump())

    async def request_update(self, initial_only: bool = False):
        """
        Requests an update of the world state from the WorldState agent. If initial_only is true, emits current state without requesting if characters exist.

        Arguments:
        - initial_only: A boolean flag to determine if only the initial state should be emitted without requesting a new one.
        """

        if initial_only and self.characters:
            self.emit()
            return

        # if auto is true, we need to check if agent has automatic update enabled
        if initial_only and not self.agent.actions["update_world_state"].enabled:
            self.emit()
            return

        self.emit(status="requested")

        try:
            world_state = await self.agent.request_world_state()
        except GenerationCancelled:
            self.emit()
            return
        except Exception as e:
            self.emit()
            log.error(
                "world_state.request_update", error=e, traceback=traceback.format_exc()
            )
            return

        previous_characters = self.characters
        scene = self.agent.scene
        character_names = scene.character_names
        self.characters = {}
        self.items = {}

        # if characters is not set or empty, make sure its at least a dict
        if not world_state.get("characters"):
            world_state["characters"] = {}

        for character_name, character in world_state.get("characters", {}).items():
            character_name = self.normalize_name(character_name)
            # if character name is an alias, we need to convert it to the main name
            # if it exists in the mappings

            for main_name, synonyms in self.character_name_mappings.items():
                if character_name.lower() in synonyms:
                    log.debug(
                        "world_state adjusting character name (via mapping)",
                        from_name=character_name,
                        to_name=main_name,
                    )
                    character_name = main_name
                    break

            # character name may not always come back exactly as we have
            # it defined in the scene. We assign the correct name by checking occurences
            # of both names in each other.

            if character_name not in character_names:
                for _character_name in character_names:
                    if (
                        _character_name.lower() in character_name.lower()
                        or character_name.lower() in _character_name.lower()
                    ):
                        log.debug(
                            "world_state adjusting character name",
                            from_name=character_name,
                            to_name=_character_name,
                        )
                        character_name = _character_name
                        break

            if not character:
                continue

            # if emotion is not set, see if a previous state exists
            # and use that emotion

            if "emotion" not in character:
                log.debug(
                    "emotion not set",
                    character_name=character_name,
                    character=character,
                    characters=previous_characters,
                )
                if character_name in previous_characters:
                    character["emotion"] = previous_characters[character_name].emotion
            try:
                self.characters[character_name] = CharacterState(**character)
            except Exception as e:
                log.error(
                    "world_state.request_update",
                    error=e,
                    traceback=traceback.format_exc(),
                    character=character,
                )

            log.debug("world_state", character=character)

        # if items is not set or empty, make sure its at least a dict
        if not world_state.get("items"):
            world_state["items"] = {}

        for item_name, item in world_state.get("items", {}).items():
            item_name = self.normalize_name(item_name)
            if not item:
                continue
            try:
                self.items[item_name] = ObjectState(**item)
            except Exception as e:
                log.error(
                    "world_state.request_update",
                    error=e,
                    traceback=traceback.format_exc(),
                )
            log.debug("world_state", item=item)

        # deactivate persiting for now
        # await self.persist()
        self.emit()

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
        """

        # if reinforcement already exists, update it

        idx, reinforcement = await self.find_reinforcement(question, character)

        if reinforcement:
            # update the reinforcement object

            reinforcement.instructions = instructions
            reinforcement.interval = interval
            reinforcement.answer = answer
            reinforcement.require_active = require_active

            old_insert_method = reinforcement.insert

            reinforcement.insert = insert

            # find the reinforcement message i nthe scene history and update the answer
            if old_insert_method == "sequential":
                message = self.agent.scene.find_message(
                    typ="reinforcement",
                    character_name=character,
                    question=question,
                )

                if old_insert_method != insert and message:
                    # if it used to be sequential we need to remove its ReinforcmentMessage
                    # from the scene history

                    self.scene.pop_history(typ="reinforcement", source=message.source)

                elif message:
                    message.message = answer
            elif insert == "sequential":
                # if it used to be something else and is now sequential, we need to run the state
                # next loop
                reinforcement.due = 0

            # update the character detail if character name is specified
            if character:
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
            insert=insert,
            require_active=require_active,
        )

        self.reinforce.append(reinforcement)

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

        self.agent.scene.pop_history(
            typ="reinforcement",
            character_name=reinforcement.character,
            question=reinforcement.question,
            all=True,
        )

        # source = f"{self.reinforce[idx].question}:{self.reinforce[idx].character if self.reinforce[idx].character else ''}"
        # self.agent.scene.pop_history(typ="reinforcement", source=source, all=True)

        self.reinforce.pop(idx)

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

    async def commit_to_memory(self, memory_agent):
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
