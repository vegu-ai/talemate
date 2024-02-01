from typing import TYPE_CHECKING, Any, Union

import pydantic
import structlog

from talemate.config import StateReinforcementTemplate, WorldStateTemplates, save_config
from talemate.instance import get_agent
from talemate.world_state import ContextPin, InsertionMode, ManualContext, Reinforcement

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.server.world_state_manager")


class CharacterSelect(pydantic.BaseModel):
    name: str
    active: bool = True
    is_player: bool = False


class ContextDBEntry(pydantic.BaseModel):
    text: str
    meta: dict
    id: Any


class ContextDB(pydantic.BaseModel):
    entries: list[ContextDBEntry] = []


class CharacterActor(pydantic.BaseModel):
    dialogue_examples: list[str] = pydantic.Field(default_factory=list)
    dialogue_instructions: Union[str, None] = None

class CharacterDetails(pydantic.BaseModel):
    name: str
    active: bool = True
    is_player: bool = False
    description: str = ""
    base_attributes: dict[str, str] = {}
    details: dict[str, str] = {}
    reinforcements: dict[str, Reinforcement] = {}
    actor: CharacterActor = pydantic.Field(default_factory=CharacterActor)


class World(pydantic.BaseModel):
    entries: dict[str, ManualContext] = {}
    reinforcements: dict[str, Reinforcement] = {}


class CharacterList(pydantic.BaseModel):
    characters: dict[str, CharacterSelect] = {}


class HistoryEntry(pydantic.BaseModel):
    text: str
    start: int = None
    end: int = None
    ts: str = None


class History(pydantic.BaseModel):
    history: list[HistoryEntry] = []


class AnnotatedContextPin(pydantic.BaseModel):
    pin: ContextPin
    text: str
    time_aware_text: str


class ContextPins(pydantic.BaseModel):
    pins: dict[str, AnnotatedContextPin] = []


class WorldStateManager:
    @property
    def memory_agent(self):
        """
        Retrieves the memory agent instance.

        Returns:
            The memory agent instance responsible for managing memory-related operations.
        """
        return get_agent("memory")

    def __init__(self, scene: "Scene"):
        """
        Initializes the WorldStateManager with a given scene.

        Arguments:
            scene: The current scene containing characters and world details.
        """
        self.scene = scene
        self.world_state = scene.world_state

    async def get_character_list(self) -> CharacterList:
        """
        Retrieves a list of characters from the current scene.

        Returns:
            A CharacterList object containing the characters with their select properties from the scene.
        """

        characters = CharacterList()

        for character in self.scene.get_characters():
            characters.characters[character.name] = CharacterSelect(
                name=character.name, active=True, is_player=character.is_player
            )

        for character in self.scene.inactive_characters.values():
            characters.characters[character.name] = CharacterSelect(
                name=character.name, active=False, is_player=character.is_player
            )

        return characters

    async def get_character_details(self, character_name: str) -> CharacterDetails:
        """
        Fetches and returns the details for a specific character by name.

        Arguments:
            character_name: A string representing the unique name of the character.

        Returns:
            A CharacterDetails object containing the character's details, attributes, and reinforcements.
        """

        character = self.scene.get_character(character_name)

        details = CharacterDetails(
            name=character.name,
            active=True,
            description=character.description,
            is_player=character.is_player,
            actor=CharacterActor(
                dialogue_examples=character.example_dialogue,
                dialogue_instructions=character.dialogue_instructions,
            ),
        )

        for key, value in character.base_attributes.items():
            details.base_attributes[key] = value

        for key, value in character.details.items():
            details.details[key] = value

        details.reinforcements = self.world_state.reinforcements_for_character(
            character_name
        )

        return details

    async def get_world(self) -> World:
        """
        Retrieves the current state of the world, including entries and reinforcements.

        Returns:
            A World object with the current state of the world.
        """
        return World(
            entries=self.world_state.manual_context_for_world(),
            reinforcements=self.world_state.reinforcements_for_world(),
        )

    async def get_context_db_entries(
        self, query: str, limit: int = 20, **meta
    ) -> ContextDB:
        """
        Retrieves entries from the context database based on a query and metadata.

        Arguments:
            query: The query string to search for.
            limit: The maximum number of entries to return; defaults to 20.
            **meta: Additional metadata parameters used for filtering results.

        Returns:
            A ContextDB object containing the found entries.
        """

        if query.startswith("id:"):
            _entries = await self.memory_agent.get_document(id=query[3:])
            _entries = list(_entries.values())
        else:
            _entries = await self.memory_agent.multi_query(
                [query], iterate=limit, max_tokens=9999999, **meta
            )

        entries = []
        for entry in _entries:
            entries.append(ContextDBEntry(text=entry.raw, meta=entry.meta, id=entry.id))

        context_db = ContextDB(entries=entries)

        return context_db

    async def get_pins(self, active: bool = None) -> ContextPins:
        """
        Retrieves context pins that meet the specified activity condition.

        Arguments:
            active: Optional boolean flag to filter pins based on their active state; defaults to None which returns all pins.

        Returns:
            A ContextPins object containing the matching annotated context pins.
        """

        pins = self.world_state.pins

        candidates = [
            pin for pin in pins.values() if pin.active == active or active is None
        ]

        _ids = [pin.entry_id for pin in candidates]
        _pins = {}
        documents = await self.memory_agent.get_document(id=_ids)

        for pin in sorted(candidates, key=lambda x: x.active, reverse=True):
            if pin.entry_id not in documents:
                text = ""
                time_aware_text = ""
            else:
                text = documents[pin.entry_id].raw
                time_aware_text = str(documents[pin.entry_id])

            annotated_pin = AnnotatedContextPin(
                pin=pin, text=text, time_aware_text=time_aware_text
            )

            _pins[pin.entry_id] = annotated_pin

        return ContextPins(pins=_pins)

    async def update_character_attribute(
        self, character_name: str, attribute: str, value: str
    ):
        """
        Updates the attribute of a character to a new value.

        Arguments:
            character_name: The name of the character to be updated.
            attribute: The attribute of the character that needs to be updated.
            value: The new value to assign to the character's attribute.
        """
        character = self.scene.get_character(character_name)
        await character.set_base_attribute(attribute, value)

    async def update_character_detail(
        self, character_name: str, detail: str, value: str
    ):
        """
        Updates a specific detail of a character to a new value.

        Arguments:
            character_name: The name of the character whose detail is to be updated.
            detail: The detail key that needs to be updated.
            value: The new value to be set for the detail.
        """
        character = self.scene.get_character(character_name)
        await character.set_detail(detail, value)

    async def update_character_description(self, character_name: str, description: str):
        """
        Updates the description of a character to a new value.

        Arguments:
            character_name: The name of the character whose description is to be updated.
            description: The new description text for the character.
        """
        character = self.scene.get_character(character_name)
        await character.set_description(description)


    async def update_character_actor(self, character_name: str, dialogue_instructions:str=None, example_dialogue:list[str]=None):
        """
        Sets the actor for a character.

        Arguments:
            character_name: The name of the character whose actor is to be set.
            dialogue_instructions: The dialogue instructions for the character.
            example_dialogue: A list of example dialogue for the character.
        """
        log.debug("update_character_actor", character_name=character_name, dialogue_instructions=dialogue_instructions, example_dialogue=example_dialogue)
        character = self.scene.get_character(character_name)
        character.dialogue_instructions = dialogue_instructions
        
        # make sure every example dialogue starts with {character_name}:
        
        if example_dialogue:
            for idx, example in enumerate(example_dialogue):
                if not example.startswith(f"{character_name}:"):
                    example_dialogue[idx] = f"{character_name}: {example}"
        
        character.example_dialogue = example_dialogue

    async def add_detail_reinforcement(
        self,
        character_name: str,
        question: str,
        instructions: str = None,
        interval: int = 10,
        answer: str = "",
        insert: str = "sequential",
        run_immediately: bool = False,
    ) -> Reinforcement:
        """
        Adds a detail reinforcement for a character with specified parameters.

        Arguments:
            character_name: The name of the character to which the reinforcement is related.
            question: The query/question to be reinforced.
            instructions: Optional instructions related to the reinforcement.
            interval: The frequency at which the reinforcement is applied.
            answer: The expected answer for the question; defaults to an empty string.
            insert: The insertion mode for the reinforcement; defaults to 'sequential'.
            run_immediately: A flag to run the reinforcement immediately; defaults to False.

        Returns:
            A Reinforcement object representing the newly added detail reinforcement.
        """
        if character_name:
            self.scene.get_character(character_name)
        world_state_agent = get_agent("world_state")
        reinforcement = await self.world_state.add_reinforcement(
            question, character_name, instructions, interval, answer, insert
        )

        if run_immediately:
            await world_state_agent.update_reinforcement(question, character_name)
        else:
            # if not running immediately, we need to emit the world state manually
            self.world_state.emit()

        return reinforcement

    async def run_detail_reinforcement(
        self, character_name: str, question: str, reset: bool = False
    ):
        """
        Executes the detail reinforcement for a specific character and question.

        Arguments:
            character_name: The name of the character to run the reinforcement for.
            question: The query/question that the reinforcement corresponds to.
        """
        world_state_agent = get_agent("world_state")
        await world_state_agent.update_reinforcement(
            question, character_name, reset=reset
        )

    async def delete_detail_reinforcement(self, character_name: str, question: str):
        """
        Deletes a detail reinforcement for a specified character and question.

        Arguments:
            character_name: The name of the character whose reinforcement is to be deleted.
            question: The query/question of the reinforcement to be deleted.
        """

        idx, reinforcement = await self.world_state.find_reinforcement(
            question, character_name
        )
        if idx is not None:
            await self.world_state.remove_reinforcement(idx)
        self.world_state.emit()

    async def save_world_entry(self, entry_id: str, text: str, meta: dict):
        """
        Saves a manual world entry with specified text and metadata.

        Arguments:
            entry_id: The identifier of the world entry to be saved.
            text: The text content of the world entry.
            meta: A dictionary containing metadata for the world entry.
        """
        meta["source"] = "manual"
        meta["typ"] = "world_state"
        await self.update_context_db_entry(entry_id, text, meta)

    async def update_context_db_entry(self, entry_id: str, text: str, meta: dict):
        """
        Updates an entry in the context database with new text and metadata.

        Arguments:
            entry_id: The identifier of the world entry to be updated.
            text: The new text content for the world entry.
            meta: A dictionary containing updated metadata for the world entry.
        """

        if meta.get("source") == "manual":
            # manual context needs to be updated in the world state
            self.world_state.manual_context[entry_id] = ManualContext(
                text=text, meta=meta, id=entry_id
            )
        elif meta.get("typ") == "details":
            # character detail needs to be mirrored to the
            # character object in the scene
            character_name = meta.get("character")
            character = self.scene.get_character(character_name)
            character.details[meta.get("detail")] = text

        await self.memory_agent.add_many([{"id": entry_id, "text": text, "meta": meta}])

    async def delete_context_db_entry(self, entry_id: str):
        """
        Deletes a specific entry from the context database using its identifier.

        Arguments:
            entry_id: The identifier of the world entry to be deleted.
        """
        await self.memory_agent.delete({"ids": entry_id})

        if entry_id in self.world_state.manual_context:
            del self.world_state.manual_context[entry_id]

        await self.remove_pin(entry_id)

    async def set_pin(
        self,
        entry_id: str,
        condition: str = None,
        condition_state: bool = False,
        active: bool = False,
    ):
        """
        Creates or updates a pin on a context entry with conditional activation.

        Arguments:
            entry_id: The identifier of the context entry to be pinned.
            condition: The conditional expression to determine when the pin should be active; defaults to None.
            condition_state: The boolean state that enables the pin; defaults to False.
            active: A flag indicating whether the pin should be active; defaults to False.
        """

        if not condition:
            condition = None
            condition_state = False

        pin = ContextPin(
            entry_id=entry_id,
            condition=condition,
            condition_state=condition_state,
            active=active,
        )

        self.world_state.pins[entry_id] = pin

    async def remove_all_empty_pins(self):
        """
        Removes all pins that come back with empty `text` attributes from get_pins.
        """

        pins = await self.get_pins()

        for pin in pins.pins.values():
            if not pin.text:
                await self.remove_pin(pin.pin.entry_id)

    async def remove_pin(self, entry_id: str):
        """
        Removes an existing pin from a context entry using its identifier.

        Arguments:
            entry_id: The identifier of the context entry pin to be removed.
        """
        if entry_id in self.world_state.pins:
            del self.world_state.pins[entry_id]

    async def get_templates(self) -> WorldStateTemplates:
        """
        Retrieves the current world state templates from scene configuration.

        Returns:
            A WorldStateTemplates object containing state reinforcement templates.
        """
        templates = self.scene.config["game"]["world_state"]["templates"]
        world_state_templates = WorldStateTemplates(**templates)
        return world_state_templates

    async def save_template(self, template: StateReinforcementTemplate):
        """
        Saves a state reinforcement template to the scene configuration.

        Arguments:
            template: The StateReinforcementTemplate object representing the template to be saved.

        Note:
            If the template is set to auto-create, it will be applied immediately.
        """
        config = self.scene.config

        template_type = template.type

        config["game"]["world_state"]["templates"][template_type][
            template.name
        ] = template.model_dump()

        save_config(self.scene.config)

        if template.auto_create:
            await self.auto_apply_template(template)

    async def remove_template(self, template_type: str, template_name: str):
        """
        Removes a specific state reinforcement template from scene configuration.

        Arguments:
            template_type: The type of the template to be removed.
            template_name: The name of the template to be removed.

        Note:
            If the specified template is not found, logs a warning.
        """
        config = self.scene.config

        try:
            del config["game"]["world_state"]["templates"][template_type][template_name]
            save_config(self.scene.config)
        except KeyError:
            log.warning(
                "world state template not found",
                template_type=template_type,
                template_name=template_name,
            )
            pass

    async def apply_all_auto_create_templates(self):
        """
        Applies all auto-create state reinforcement templates.

        This method goes through the scene configuration, identifies templates set for auto-creation,
        and applies them.
        """
        templates = self.scene.config["game"]["world_state"]["templates"]
        world_state_templates = WorldStateTemplates(**templates)

        candidates = []

        for template in world_state_templates.state_reinforcement.values():
            if template.auto_create:
                candidates.append(template)

        for template in candidates:
            log.info("applying template", template=template)
            await self.auto_apply_template(template)

    async def auto_apply_template(self, template: StateReinforcementTemplate):
        """
        Automatically applies a state reinforcement template based on its type.

        Arguments:
            template: The StateReinforcementTemplate object to be auto-applied.

        Note:
            This function delegates to a specific apply function based on the template type.
        """
        fn = getattr(self, f"auto_apply_template_{template.type}")
        await fn(template)

    async def auto_apply_template_state_reinforcement(
        self, template: StateReinforcementTemplate
    ):
        """
        Applies a state reinforcement template to characters based on the template's state type.

        Arguments:
            template: The StateReinforcementTemplate object with the state reinforcement details.

        Note:
            The characters to apply the template to are determined by the state_type in the template.
        """

        characters = []

        if template.state_type == "npc":
            characters = [
                character.name for character in self.scene.get_npc_characters()
            ]
        elif template.state_type == "character":
            characters = [character.name for character in self.scene.get_characters()]
        elif template.state_type == "player":
            characters = [self.scene.get_player_character().name]

        for character_name in characters:
            await self.apply_template_state_reinforcement(template, character_name)

    async def apply_template_state_reinforcement(
        self,
        template: StateReinforcementTemplate,
        character_name: str = None,
        run_immediately: bool = False,
    ) -> Reinforcement:
        """
        Applies a state reinforcement template to a specific character, if provided.

        Arguments:
            template: The StateReinforcementTemplate object defining the reinforcement details.
            character_name: Optional; the name of the character to apply the template to.
            run_immediately: Whether to run the reinforcement immediately after applying.

        Returns:
            A Reinforcement object if the template is applied, or None if the reinforcement already exists.

        Raises:
            ValueError: If a character name is required but not provided.
        """

        if not character_name and template.state_type in ["npc", "character", "player"]:
            raise ValueError("Character name required for this template type.")

        player_name = self.scene.get_player_character().name

        formatted_query = template.query.format(
            character_name=character_name, player_name=player_name
        )
        formatted_instructions = (
            template.instructions.format(
                character_name=character_name, player_name=player_name
            )
            if template.instructions
            else None
        )

        if character_name:
            details = await self.get_character_details(character_name)

            # if reinforcement already exists, skip
            if formatted_query in details.reinforcements:
                return None

        return await self.add_detail_reinforcement(
            character_name,
            formatted_query,
            formatted_instructions,
            template.interval,
            insert=template.insert,
            run_immediately=run_immediately,
        )
