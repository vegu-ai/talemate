from typing import TYPE_CHECKING, Union
import pydantic
import structlog
import random
import re
import traceback

import talemate.util as util
import talemate.instance as instance
import talemate.scene_message as scene_message
import talemate.agents.base as agent_base

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Actor

__all__ = [
    "Character",
    "CharacterVoice",
    "deactivate_character",
    "activate_character",
]

log = structlog.get_logger("talemate.character")


class CharacterVoice(pydantic.BaseModel):
    # arbitrary voice label to allow a human to easily identify the voice
    label: str

    # voice provider, this would be the TTS api in the voice
    provider: str | None = None

    # voice id as known to the voice provider
    provider_id: str | None = None

    # allows to also override to a specific model
    provider_model: str | None = None


class Character(pydantic.BaseModel):
    # core character information
    name: str
    description: str = ""
    greeting_text: str = ""
    color: str = "#fff"
    is_player: bool = False
    memory_dirty: bool = False
    cover_image: str | None = None
    voice: CharacterVoice | None = None

    # dialogue instructions and examples
    dialogue_instructions: str | None = None
    example_dialogue: list[str] = pydantic.Field(default_factory=list)

    # attribute and detail storage
    base_attributes: dict[str, str | int | float | bool] = pydantic.Field(
        default_factory=dict
    )
    details: dict[str, str] = pydantic.Field(default_factory=dict)

    # helpful references
    agent: agent_base.Agent | None = pydantic.Field(default=None, exclude=True)
    actor: "Actor | None" = pydantic.Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    @property
    def gender(self) -> str:
        return self.base_attributes.get("gender", "")

    @property
    def sheet(self) -> str:
        sheet = self.base_attributes or {
            "name": self.name,
            "description": self.description,
        }

        sheet_list = []

        for key, value in sheet.items():
            sheet_list.append(f"{key}: {value}")

        return "\n".join(sheet_list)

    @property
    def random_dialogue_example(self):
        """
        Get a random example dialogue line for this character.

        Returns:
        str: The random example dialogue line.
        """
        if not self.example_dialogue:
            return ""

        return random.choice(self.example_dialogue)

    def __str__(self):
        return f"Character: {self.name}"

    def __repr__(self):
        return str(self)

    def set_color(self, color: str | None = None):
        # if no color provided, chose a random color

        if color is None:
            color = util.random_color()
        self.color = color

    def set_cover_image(self, asset_id: str, initial_only: bool = False):
        if self.cover_image and initial_only:
            return

        self.cover_image = asset_id

    def sheet_filtered(self, *exclude):
        sheet = self.base_attributes or {
            "name": self.name,
            "gender": self.gender,
            "description": self.description,
        }

        sheet_list = []

        for key, value in sheet.items():
            if key not in exclude:
                sheet_list.append(f"{key}: {value}")

        return "\n".join(sheet_list)

    def random_dialogue_examples(
        self,
        scene: "Scene",
        num: int = 3,
        strip_name: bool = False,
        max_backlog: int = 250,
        max_length: int = 192,
    ) -> list[str]:
        """
        Get multiple random example dialogue lines for this character.

        Will return up to `num` examples and not have any duplicates.
        """

        history_examples = self._random_dialogue_examples_from_history(
            scene, num, max_backlog
        )

        if len(history_examples) < num:
            random_examples = self._random_dialogue_examples(
                num - len(history_examples), strip_name
            )

            for example in random_examples:
                history_examples.append(example)

        # ensure sane example lengths

        history_examples = [
            util.strip_partial_sentences(example[:max_length])
            for example in history_examples
        ]

        log.debug("random_dialogue_examples", history_examples=history_examples)
        return history_examples

    def _random_dialogue_examples_from_history(
        self, scene: "Scene", num: int = 3, max_backlog: int = 250
    ) -> list[str]:
        """
        Get multiple random example dialogue lines for this character from the scene's history.

        Will checks the last `max_backlog` messages in the scene's history and returns up to `num` examples.
        """

        history = scene.history[-max_backlog:]

        examples = []

        for message in history:
            if not isinstance(message, scene_message.CharacterMessage):
                continue

            if message.character_name != self.name:
                continue

            examples.append(message.without_name.strip())

        if not examples:
            return []

        return random.sample(examples, min(num, len(examples)))

    def _random_dialogue_examples(
        self, num: int = 3, strip_name: bool = False
    ) -> list[str]:
        """
        Get multiple random example dialogue lines for this character.

        Will return up to `num` examples and not have any duplicates.
        """

        if not self.example_dialogue:
            return []

        # create copy of example_dialogue so we dont modify the original

        examples = self.example_dialogue.copy()

        # shuffle the examples so we get a random order

        random.shuffle(examples)

        # now pop examples until we have `num` examples or we run out of examples

        if strip_name:
            examples = [example.split(":", 1)[1].strip() for example in examples]

        return [examples.pop() for _ in range(min(num, len(examples)))]

    def filtered_sheet(self, attributes: list[str]):
        """
        Same as sheet but only returns the attributes in the given list

        Attributes that dont exist will be ignored
        """

        sheet_list = []

        for key, value in self.base_attributes.items():
            if key.lower() not in attributes:
                continue
            sheet_list.append(f"{key}: {value}")

        return "\n".join(sheet_list)

    def rename(self, new_name: str):
        """
        Rename the character.

        Args:
        new_name (str): The new name of the character.

        Returns:
        None
        """

        orig_name = self.name
        self.name = new_name

        if orig_name.lower() == "you":
            # we dont want to replace "you" in the description
            # or anywhere else so we can just return here
            return

        if self.description:
            self.description = self.description.replace(f"{orig_name}", self.name)
        for k, v in self.base_attributes.items():
            if isinstance(v, str):
                self.base_attributes[k] = v.replace(f"{orig_name}", self.name)
        for i, v in list(self.details.items()):
            if isinstance(v, str):
                self.details[i] = v.replace(f"{orig_name}", self.name)
        self.memory_dirty = True

    def introduce_main_character(self, character: "Character"):
        """
        Makes this character aware of the main character's name in the scene.

        This will replace all occurrences of {{user}} (case-insensitive) in all of the character's properties
        with the main character's name.
        """

        properties = ["description", "greeting_text"]

        pattern = re.compile(re.escape("{{user}}"), re.IGNORECASE)

        for prop in properties:
            prop_value = getattr(self, prop)

            try:
                updated_prop_value = pattern.sub(character.name, prop_value)
            except Exception as e:
                log.error(
                    "introduce_main_character",
                    error=e,
                    traceback=traceback.format_exc(),
                )
                updated_prop_value = prop_value
            setattr(self, prop, updated_prop_value)

        # also replace in all example dialogue

        for i, dialogue in enumerate(self.example_dialogue):
            self.example_dialogue[i] = pattern.sub(character.name, dialogue)

    def update(self, **kwargs):
        """
        Update character properties with given key-value pairs.
        """

        for key, value in kwargs.items():
            setattr(self, key, value)

        self.memory_dirty = True

    async def purge_from_memory(self):
        """
        Purges this character's details from memory.
        """
        memory_agent = instance.get_agent("memory")
        await memory_agent.delete({"character": self.name})
        log.info("purged character from memory", character=self.name)

    async def commit_to_memory(self, memory_agent):
        """
        Commits this character's details to the memory agent. (vectordb)
        """

        items = []

        if not self.base_attributes or "description" not in self.base_attributes:
            if not self.description:
                self.description = ""
            description_chunks = [
                chunk.strip() for chunk in self.description.split("\n") if chunk.strip()
            ]

            for idx in range(len(description_chunks)):
                chunk = description_chunks[idx]

                items.append(
                    {
                        "text": f"{self.name}: {chunk}",
                        "id": f"{self.name}.description.{idx}",
                        "meta": {
                            "character": self.name,
                            "attr": "description",
                            "typ": "base_attribute",
                        },
                    }
                )

        seen_attributes = set()

        for attr, value in self.base_attributes.items():
            if attr.startswith("_"):
                continue

            if attr.lower() in ["name", "scenario_context", "_prompt", "_template"]:
                continue

            seen_attributes.add(attr)

            items.append(
                {
                    "text": f"{self.name}'s {attr}: {value}",
                    "id": f"{self.name}.{attr}",
                    "meta": {
                        "character": self.name,
                        "attr": attr,
                        "typ": "base_attribute",
                    },
                }
            )

        for key, detail in self.details.items():
            # if colliding with attribute name, prefix with detail_
            if key in seen_attributes:
                key = f"detail_{key}"

            items.append(
                {
                    "text": f"{self.name} - {key}: {detail}",
                    "id": f"{self.name}.{key}",
                    "meta": {
                        "character": self.name,
                        "typ": "details",
                        "detail": key,
                    },
                }
            )

        if items:
            await memory_agent.add_many(items)

        self.memory_dirty = False

    async def commit_single_attribute_to_memory(
        self, memory_agent, attribute: str, value: str
    ):
        """
        Commits a single attribute to memory
        """

        items = []

        # remove old attribute if it exists

        await memory_agent.delete(
            {"character": self.name, "typ": "base_attribute", "attr": attribute}
        )

        self.base_attributes[attribute] = value

        items.append(
            {
                "text": f"{self.name}'s {attribute}: {self.base_attributes[attribute]}",
                "id": f"{self.name}.{attribute}",
                "meta": {
                    "character": self.name,
                    "attr": attribute,
                    "typ": "base_attribute",
                },
            }
        )

        log.debug("commit_single_attribute_to_memory", items=items)

        await memory_agent.add_many(items)

    async def commit_single_detail_to_memory(
        self, memory_agent, detail: str, value: str
    ):
        """
        Commits a single detail to memory
        """

        items = []

        # remove old detail if it exists

        await memory_agent.delete(
            {"character": self.name, "typ": "details", "detail": detail}
        )

        self.details[detail] = value

        items.append(
            {
                "text": f"{self.name} - {detail}: {value}",
                "id": f"{self.name}.{detail}",
                "meta": {
                    "character": self.name,
                    "typ": "details",
                    "detail": detail,
                },
            }
        )

        log.debug("commit_single_detail_to_memory", items=items)

        await memory_agent.add_many(items)

    async def set_detail(self, name: str, value):
        memory_agent = instance.get_agent("memory")
        if not value:
            try:
                del self.details[name]
                await memory_agent.delete(
                    {"character": self.name, "typ": "details", "detail": name}
                )
            except KeyError:
                pass
        else:
            self.details[name] = value
            await self.commit_single_detail_to_memory(memory_agent, name, value)

    def set_detail_defer(self, name: str, value):
        self.details[name] = value
        self.memory_dirty = True

    def get_detail(self, name: str):
        return self.details.get(name)

    async def set_base_attribute(self, name: str, value):
        memory_agent = instance.get_agent("memory")

        if not value:
            try:
                del self.base_attributes[name]
                await memory_agent.delete(
                    {"character": self.name, "typ": "base_attribute", "attr": name}
                )
            except KeyError:
                pass
        else:
            self.base_attributes[name] = value
            await self.commit_single_attribute_to_memory(memory_agent, name, value)

    def set_base_attribute_defer(self, name: str, value):
        self.base_attributes[name] = value
        self.memory_dirty = True

    def get_base_attribute(self, name: str):
        return self.base_attributes.get(name)

    async def set_description(self, description: str):
        memory_agent = instance.get_agent("memory")
        self.description = description

        items = []

        await memory_agent.delete(
            {"character": self.name, "typ": "base_attribute", "attr": "description"}
        )

        description_chunks = [
            chunk.strip() for chunk in self.description.split("\n") if chunk.strip()
        ]

        for idx in range(len(description_chunks)):
            chunk = description_chunks[idx]

            items.append(
                {
                    "text": f"{self.name}: {chunk}",
                    "id": f"{self.name}.description.{idx}",
                    "meta": {
                        "character": self.name,
                        "attr": "description",
                        "typ": "base_attribute",
                    },
                }
            )

        await memory_agent.add_many(items)


async def deactivate_character(scene: "Scene", character: Union[str, "Character"]):
    """
    Deactivates a character

    Arguments:

    - `scene`: The scene to deactivate the character from
    - `character`: The character to deactivate. Can be a string (the character's name) or a Character object
    """

    if isinstance(character, str):
        character = scene.get_character(character)

    if character.name in scene.inactive_characters:
        # already deactivated
        return False

    await scene.remove_actor(character.actor)
    scene.inactive_characters[character.name] = character


async def activate_character(scene: "Scene", character: Union[str, "Character"]):
    """
    Activates a character

    Arguments:

    - `scene`: The scene to activate the character in
    - `character`: The character to activate. Can be a string (the character's name) or a Character object
    """

    if isinstance(character, str):
        character = scene.get_character(character)

    if character.name not in scene.inactive_characters:
        # already activated
        return False

    if not character.is_player:
        actor = scene.Actor(character, instance.get_agent("conversation"))
    else:
        actor = scene.Player(character, None)

    await scene.add_actor(actor)
    del scene.inactive_characters[character.name]
