from typing import TYPE_CHECKING, Any, Callable, Union

import pydantic
import structlog

import talemate.world_state.templates as world_state_templates
from talemate.agents.tts.util import get_voice
from talemate.character import activate_character, deactivate_character, set_voice
from talemate.instance import get_agent
from talemate.emit import emit
from talemate.world_state import (
    ContextPin,
    ManualContext,
    Reinforcement,
    Suggestion,
)
from talemate.game.schema import ConditionGroup, condition_groups_match
from talemate.game.engine.context_id.base import ContextIDItem
from talemate.agents.tts.schema import Voice
from talemate.game.engine.context_id import ContextID

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

log = structlog.get_logger("talemate.server.world_state_manager")

_UNSET = object()


class CharacterSelect(pydantic.BaseModel):
    name: str
    active: bool = True
    is_player: bool = False
    shared: bool = False
    avatar: str | None = None


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
    cover_image: Union[str, None] = None
    avatar: Union[str, None] = None  # default avatar
    current_avatar: Union[str, None] = None  # current avatar
    visual_rules: Union[str, None] = None
    color: Union[str, None] = None
    voice: Union[Voice, None] = None
    shared: bool = False
    shared_attributes: list[str] = []
    shared_details: list[str] = []


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
    is_active: bool = False
    text: str
    time_aware_text: str
    title: str | None = None
    context_id: ContextID | None = None


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

    @property
    def template_collection(self) -> world_state_templates.Collection:
        scene = self.scene
        if not hasattr(scene, "_world_state_templates"):
            scene._world_state_templates = world_state_templates.Collection.load()
        return scene._world_state_templates

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
                name=character.name,
                active=True,
                is_player=character.is_player,
                shared=character.shared,
                avatar=character.avatar,
            )

        for character in self.scene.inactive_characters.values():
            characters.characters[character.name] = CharacterSelect(
                name=character.name,
                active=False,
                is_player=character.is_player,
                shared=character.shared,
                avatar=character.avatar,
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

        if not character:
            log.warning("character not found", character_name=character_name)
            return None

        details = CharacterDetails(
            name=character.name,
            active=(character.name not in self.scene.inactive_characters),
            description=character.description,
            is_player=character.is_player,
            actor=CharacterActor(
                dialogue_examples=character.example_dialogue,
                dialogue_instructions=character.dialogue_instructions,
            ),
            cover_image=character.cover_image,
            avatar=character.avatar,
            current_avatar=character.current_avatar,
            visual_rules=character.visual_rules,
            color=character.color,
            voice=character.voice,
            shared=character.shared,
            shared_attributes=character.shared_attributes,
            shared_details=character.shared_details,
        )

        # sorted base attributes
        for key in sorted(character.base_attributes.keys()):
            if key.startswith("_"):
                continue
            details.base_attributes[key] = character.base_attributes[key]

        # sorted details
        for key in sorted(character.details.keys()):
            details.details[key] = character.details[key]

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

        def _pin_is_active(pin: ContextPin) -> bool:
            # Effective pinning:
            # - if gamestate_condition is set, evaluate it against scene.game_state
            # - else use manual `active`
            if pin.gamestate_condition:
                return condition_groups_match(
                    pin.gamestate_condition, self.scene.game_state
                )
            return pin.active

        candidates = [
            pin
            for pin in pins.values()
            if _pin_is_active(pin) == active or active is None
        ]

        _ids = [pin.entry_id for pin in candidates]
        _pins = {}
        documents = await self.memory_agent.get_document(id=_ids)

        for pin in sorted(candidates, key=_pin_is_active, reverse=True):
            if pin.entry_id not in documents:
                text = ""
                time_aware_text = ""
                context_id = None
            else:
                text = documents[pin.entry_id].raw
                time_aware_text = str(documents[pin.entry_id])
                context_id = documents[pin.entry_id].context_id

            title = pin.entry_id.replace(".", " - ")

            annotated_pin = AnnotatedContextPin(
                pin=pin,
                is_active=_pin_is_active(pin),
                text=text,
                time_aware_text=time_aware_text,
                title=title,
                context_id=context_id,
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

    async def update_character_color(self, character_name: str, color: str):
        """
        Updates the color of a character to a new value.

        Arguments:
            character_name: The name of the character whose color is to be updated.
            color: The new color value for the character.
        """
        character = self.scene.get_character(character_name)

        if not character:
            log.error("character not found", character_name=character_name)
            return

        character.set_color(color)

    async def update_character_voice(self, character_name: str, voice_id: str | None):
        """Assign or clear a voice for the given character.

        Args:
            character_name: Name of the character to update.
            voice_id: The unique id of the voice in the voice library ("provider:voice_id").
                       If *None* or empty string, the character voice assignment is cleared.
        """
        character = self.scene.get_character(character_name)
        if not character:
            log.error("character not found", character_name=character_name)
            return

        if voice_id:
            voice = get_voice(self.scene, voice_id)
            if not voice:
                log.warning("voice not found in library", voice_id=voice_id)

            await set_voice(character, voice)
        else:
            # Clear voice assignment
            await set_voice(character, None)

    async def update_character_visual_rules(
        self, character_name: str, visual_rules: str | None
    ):
        """
        Updates the visual rules for a character.

        Arguments:
            character_name: The name of the character to be updated.
            visual_rules: The new visual rules for the character.
        """
        character = self.scene.get_character(character_name)
        if not character:
            log.error("character not found", character_name=character_name)
            return

        character.visual_rules = visual_rules or None
        character.memory_dirty = True

    async def update_character_actor(
        self,
        character_name: str,
        dialogue_instructions: str = None,
        example_dialogue: list[str] = None,
    ):
        """
        Sets the actor for a character.

        Arguments:
            character_name: The name of the character whose actor is to be set.
            dialogue_instructions: The dialogue instructions for the character.
            example_dialogue: A list of example dialogue for the character.
        """
        log.debug(
            "update_character_actor",
            character_name=character_name,
            dialogue_instructions=dialogue_instructions,
            example_dialogue=example_dialogue,
        )
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
        require_active: bool = True,
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
            question,
            character_name,
            instructions,
            interval,
            answer,
            insert,
            require_active,
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

    async def save_world_entry(
        self, entry_id: str, text: str, meta: dict, pin: bool = False
    ):
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

        if pin:
            await self.set_pin(entry_id, active=True)

    async def set_world_entry_shared(self, entry_id: str, shared: bool):
        """
        Sets the shared flag for a world entry.
        """
        self.world_state.manual_context[entry_id].shared = shared

    async def update_context_db_entry(self, entry_id: str, text: str, meta: dict):
        """
        Updates an entry in the context database with new text and metadata.

        Arguments:
            entry_id: The identifier of the world entry to be updated.
            text: The new text content for the world entry.
            meta: A dictionary containing updated metadata for the world entry.
        """

        if meta.get("source") in ["manual", "imported"]:
            existing = self.world_state.manual_context.get(entry_id)

            # manual context needs to be updated in the world state
            self.world_state.manual_context[entry_id] = ManualContext(
                text=text,
                meta=meta,
                id=entry_id,
                shared=existing.shared if existing else False,
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
        entry_id: str | ContextIDItem,
        condition: str = None,
        condition_state: bool = False,
        active: bool = False,
        decay: int | None = None,
        gamestate_condition: list[ConditionGroup] | None | object = _UNSET,
    ):
        """
        Creates or updates a pin on a context entry with conditional activation.

        Arguments:
            entry_id: The identifier of the context entry to be pinned. (direct or context id path)
            condition: The conditional expression to determine when the pin should be active; defaults to None.
            condition_state: The boolean state that enables the pin; defaults to False.
            active: A flag indicating whether the pin should be active; defaults to False.
        """

        if isinstance(entry_id, ContextIDItem):
            entry_id = entry_id.memory_id
            if not entry_id:
                raise ValueError(f"Context ID item {entry_id} cannot be pinned.")

        # Normalize empty condition string
        if not condition:
            condition = None
            condition_state = False

        # Normalize empty game-state condition list
        if gamestate_condition is not _UNSET and not gamestate_condition:
            gamestate_condition = None

        # If pin already exists, update in-place to preserve decay_due when appropriate
        if entry_id in self.world_state.pins:
            pin = self.world_state.pins[entry_id]
            pin.condition = condition
            pin.condition_state = condition_state
            pin.active = active
            pin.decay = decay if decay is not None else pin.decay

            # Apply game-state condition if provided
            if gamestate_condition is not _UNSET:
                pin.gamestate_condition = gamestate_condition

            # Initialize countdown when activating with decay and no current countdown
            if pin.active and pin.decay and not pin.decay_due:
                pin.decay_due = pin.decay
        else:
            initial_gamestate_condition = (
                None if gamestate_condition is _UNSET else gamestate_condition
            )

            pin = ContextPin(
                entry_id=entry_id,
                condition=condition,
                condition_state=condition_state,
                gamestate_condition=initial_gamestate_condition,
                active=active,
                decay=decay,
                decay_due=decay if (active and decay) else None,
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

    async def remove_pin(self, entry_id: str | ContextIDItem):
        """
        Removes an existing pin from a context entry using its identifier.

        Arguments:
            entry_id: The identifier of the context entry pin to be removed.
        """
        if isinstance(entry_id, ContextIDItem):
            entry_id = entry_id.memory_id
            if not entry_id:
                raise ValueError(f"Context ID item {entry_id} cannot be pinned.")

        if entry_id in self.world_state.pins:
            del self.world_state.pins[entry_id]

    async def is_pin_active(self, entry_id: str | ContextIDItem) -> bool:
        """
        Checks if a pin is active.
        """
        if isinstance(entry_id, ContextIDItem):
            entry_id = entry_id.memory_id
            if not entry_id:
                raise ValueError(f"Context ID item {entry_id} cannot be pinned.")
        return entry_id in self.world_state.pins
        return self.world_state.pins[entry_id].active

    async def get_templates(
        self, types: list[str] = None
    ) -> world_state_templates.TypedCollection:
        """
        Retrieves the current world state templates from scene configuration.

        Returns:
            A WorldStateTemplates object containing state reinforcement templates.
        """

        collection = self.template_collection
        return collection.typed(types=types)

    async def save_template_group(self, group: world_state_templates.Group):
        """
        Adds / Updates a new template group to the scene configuration.

        Arguments:
            group: The Group object to be added.
        """
        exists = self.template_collection.find(group.uid)
        if not exists:
            self.template_collection.groups.append(group)
            group.save()
        else:
            exists.update(group)

    async def remove_template_group(self, group: world_state_templates.Group):
        """
        Removes a template group from the scene configuration.

        Arguments:
            group: The Group object to be removed.
        """
        self.template_collection.remove(group)

    async def save_template(self, template: world_state_templates.AnnotatedTemplate):
        """
        Saves a state reinforcement template to the scene configuration.

        Note:
            If the template is set to auto-create, it will be applied immediately.
        """
        group = self.template_collection.find(template.group)
        group.update_template(template)
        if getattr(template, "auto_create", False):
            await self.auto_apply_template(template)

    async def remove_template(self, template: world_state_templates.AnnotatedTemplate):
        """
        Removes a specific state reinforcement template from scene configuration.
        """
        group = self.template_collection.find(template.group)
        group.delete_template(template)

    async def apply_all_auto_create_templates(self):
        """
        Applies all auto-create state reinforcement templates.

        This method goes through the scene configuration, identifies templates set for auto-creation,
        and applies them.
        """

        collection = self.template_collection
        flat_collection = collection.flat(types=["state_reinforcement"])

        candidates = []

        for template in flat_collection.templates.values():
            if template.auto_create:
                candidates.append(template)

        for template in candidates:
            log.info("applying template", template=template)
            await self.auto_apply_template(template)

    async def auto_apply_template(
        self, template: world_state_templates.AnnotatedTemplate
    ):
        """
        Automatically applies a state reinforcement template based on its type.

        Arguments:
            template: The StateReinforcementTemplate object to be auto-applied.

        Note:
            This function delegates to a specific apply function based on the template type.
        """
        fn = getattr(self, f"auto_apply_template_{template.template_type}", None)

        if not fn:
            log.error(
                "unsupported template type for auto-application", template=template
            )
            return

        await fn(template)

    async def auto_apply_template_state_reinforcement(
        self, template: world_state_templates.StateReinforcement
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

    async def apply_templates(
        self,
        templates: list[world_state_templates.AnnotatedTemplate],
        callback_start: Callable | None = None,
        callback_done: Callable | None = None,
        **kwargs,
    ):
        """
        Applies a list of state reinforcement templates to the scene.

        Arguments:
            templates: A list of StateReinforcementTemplate objects to be applied.
            template_callback: A callback function to apply the templates.
        """

        # sort templates by template.priorty descending
        templates = sorted(templates, key=lambda x: x.priority, reverse=True)

        for template in templates:
            is_last_template = template == templates[-1]
            if callback_start:
                callback_start(template, is_last_template)
            result = await self.apply_template(template, **kwargs)
            if result and callback_done:
                callback_done(template, result, is_last_template)

    async def apply_template(
        self, template: world_state_templates.AnnotatedTemplate, **kwargs
    ):
        """
        Applies a state reinforcement template to the scene.

        Arguments:
            template: The StateReinforcementTemplate object to be applied.
        """

        fn = getattr(self, f"apply_template_{template.template_type}", None)

        if not fn:
            log.error("unsupported template type for application", template=template)
            return

        log.debug("applying template", template=template, kwargs=kwargs)

        return await fn(template, **kwargs)

    async def apply_template_state_reinforcement(
        self,
        template: Union[str, world_state_templates.StateReinforcement],
        character_name: str = None,
        run_immediately: bool = False,
        **kwargs,
    ) -> Reinforcement:
        """
        Applies a state reinforcement template to a specific character, if provided.

        Arguments:
            template: The StateReinforcementTemplate object defining the reinforcement details. Can also be a string representing the template name.
            character_name: Optional; the name of the character to apply the template to.
            run_immediately: Whether to run the reinforcement immediately after applying.

        Returns:
            A Reinforcement object if the template is applied, or None if the reinforcement already exists.

        Raises:
            ValueError: If a character name is required but not provided.
        """

        if isinstance(template, str):
            template_uid = template
            template = self.template_collection.flat(
                types=["state_reinforcement"]
            ).templates.get(template_uid)
            if not template:
                log.error(
                    "apply_template_state_reinforcement: template not found",
                    template=template_uid,
                )
                return

        return (
            await template.generate(self.scene, character_name, run_immediately)
        ).reinforcement

    async def apply_template_character_attribute(
        self,
        template: str | world_state_templates.character.Attribute,
        character_name: str,
        run_immediately: bool = False,
        **kwargs,
    ) -> str:
        if isinstance(template, str):
            template_uid = template
            template = self.template_collection.flat(
                types=["character_attribute"]
            ).templates.get(template_uid)
            if not template:
                log.error(
                    "apply_template_character_attribute: template not found",
                    template=template_uid,
                )
                return

        return await template.generate(self.scene, character_name, **kwargs)

    async def apply_template_character_detail(
        self,
        template: str | world_state_templates.character.Detail,
        character_name: str,
        **kwargs,
    ) -> str:
        if isinstance(template, str):
            template_uid = template
            template = self.template_collection.flat(
                types=["character_detail"]
            ).templates.get(template_uid)
            if not template:
                log.error(
                    "apply_template_character_detail: template not found",
                    template=template_uid,
                )
                return

        return await template.generate(self.scene, character_name, **kwargs)

    async def activate_character(self, character_name: str):
        """
        Activates a character in the scene.

        Arguments:
            character_name: The name of the character to activate.
        """
        await activate_character(self.scene, character_name)

    async def deactivate_character(self, character_name: str):
        """
        Deactivates a character in the scene.

        Arguments:
            character_name: The name of the character to deactivate.
        """
        await deactivate_character(self.scene, character_name)

    async def create_character(
        self,
        generate: bool = True,
        instructions: str = None,
        name: str = None,
        is_player: bool = False,
        description: str = "",
        active: bool = False,
        generate_attributes: bool = True,
        generation_options: world_state_templates.GenerationOptions | None = None,
    ) -> "Character":
        """
        Creates a new character in the scene.

        DEPRECATED: Use the director agent's persist_character method instead.

        Arguments:
            generate: Whether to generate name and description if they are not specified; defaults to True.
            instructions: Optional instructions for the character creation.
            name: Optional name for the new character.
            is_player: Whether the new character is a player character; defaults to False.
            description: Optional description for the new character.

        Returns:
            The name of the newly created character.
        """

        if not name and not generate:
            raise ValueError("You need to specify a name for the character.")

        creator = get_agent("creator")
        world_state = get_agent("world_state")

        if not generation_options:
            generation_options = world_state_templates.GenerationOptions()

        if not name and generate:
            tries = 2
            while not name and tries > 0:
                name = await creator.contextual_generate_from_args(
                    context="character attribute:name",
                    instructions=f"You are creating: {instructions if instructions else 'A new character'}. Only respond with the character's name.",
                    length=25,
                    uid="wsm.create_character",
                    character="the character",
                )
                tries -= 1

        if not name:
            raise ValueError("Failed to generate a name for the character.")

        if name in self.scene.all_character_names:
            raise ValueError(f'Name "{name}" already exists.')

        if not description and generate:
            description = await creator.contextual_generate_from_args(
                context="character detail:description",
                instructions=instructions,
                length=100,
                uid="wsm.create_character",
                character=name,
                **generation_options.model_dump(),
            )

        # create character instance
        character: "Character" = self.scene.Character(
            name=name,
            description=description,
            base_attributes={},
            is_player=is_player,
        )

        # set random color for their name
        character.set_color()

        if is_player:
            ActorCls = self.scene.Player
        else:
            ActorCls = self.scene.Actor

        actor = ActorCls(character, get_agent("conversation"))

        await self.scene.add_actor(actor)

        try:
            if generate_attributes:
                base_attributes = await world_state.extract_character_sheet(
                    name=name, text=description
                )
                character.update(base_attributes=base_attributes)

            if active:
                await activate_character(self.scene, name)
        except Exception as e:
            await self.scene.remove_actor(actor)
            raise e

        return character

    async def update_scene_outline(
        self,
        title: str,
        description: str | None = None,
        intro: str | None = None,
        context: str | None = None,
    ) -> "Scene":
        scene = self.scene
        scene.title = title
        scene.description = description
        scene.intro = intro
        scene.context = context

        return scene

    async def update_scene_settings(
        self,
        immutable_save: bool = False,
        experimental: bool = False,
        writing_style_template: str | None = None,
        agent_persona_templates: dict[str, str] | None = None,
        visual_style_template: str | None = None,
        restore_from: str | None = None,
    ) -> "Scene":
        scene = self.scene
        scene.immutable_save = immutable_save
        scene.experimental = experimental
        scene.writing_style_template = writing_style_template
        scene.visual_style_template = visual_style_template
        if agent_persona_templates is not None:
            scene.agent_persona_templates = agent_persona_templates or {}

        if restore_from and restore_from not in scene.save_files:
            raise ValueError(
                f"Restore file {restore_from} not found in scene save files."
            )

        scene.restore_from = restore_from

        return scene

    # suggestions

    async def clear_suggestions(self):
        """
        Clears all suggestions from the scene.
        """
        self.scene.world_state.suggestions = []
        self.scene.world_state.emit()

    async def add_suggestion(self, suggestion: Suggestion):
        """
        Adds a suggestion to the scene.
        """

        existing: Suggestion = await self.get_suggestion_by_id(suggestion.id)

        log.debug(
            "WorldStateManager.add_suggestion", suggestion=suggestion, existing=existing
        )

        if existing:
            existing.merge(suggestion)
        else:
            self.scene.world_state.suggestions.append(suggestion)

        # changes will be emitted to the world editor as proposals for the character
        for proposal in suggestion.proposals:
            emit(
                "world_state_manager",
                data=proposal.model_dump(),
                websocket_passthrough=True,
                kwargs={
                    "action": "suggest",
                    "suggestion_type": suggestion.type,
                    "name": suggestion.name,
                    "id": suggestion.id,
                },
            )

        self.scene.world_state.emit()

    async def get_suggestion_by_id(self, id: str) -> Suggestion:
        """
        Retrieves a suggestion from the scene by its id.
        """

        for s in self.scene.world_state.suggestions:
            if s.id == id:
                return s

        self.scene.world_state.emit()

    async def remove_suggestion(self, suggestion: str | Suggestion):
        """
        Removes a suggestion from the scene by its id.
        """
        if isinstance(suggestion, str):
            suggestion = await self.get_suggestion_by_id(suggestion)

        if not suggestion:
            return

        self.scene.world_state.suggestions.remove(suggestion)
        self.scene.world_state.emit()

    async def remove_suggestion_proposal(self, suggestion_id: str, proposal_uid: str):
        """
        Removes a proposal from a suggestion by its uid.
        """

        suggestion: Suggestion = await self.get_suggestion_by_id(suggestion_id)

        if not suggestion:
            return

        suggestion.remove_proposal(proposal_uid)

        # if suggestion is empty, remove it
        if not suggestion.proposals:
            await self.remove_suggestion(suggestion)
        self.scene.world_state.emit()
