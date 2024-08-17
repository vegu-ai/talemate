import asyncio
import json
import os
import random
import re
import traceback
import uuid
from typing import Dict, Generator, List, Union

import isodate
import pydantic
import structlog
from blinker import signal

import talemate.agents as agents
import talemate.automated_action as automated_action
import talemate.client as client
import talemate.commands as commands
import talemate.data_objects as data_objects
import talemate.emit.async_signals as async_signals
import talemate.events as events
import talemate.save as save
import talemate.util as util
from talemate.client.context import ClientContext, ConversationContext
from talemate.config import Config, SceneConfig, load_config
from talemate.context import interaction, rerun_context
from talemate.emit import Emission, Emitter, emit, wait_for_input
from talemate.emit.signals import ConfigSaved, ImageGenerated, handlers
from talemate.exceptions import (
    ExitScene,
    LLMAccuracyError,
    ResetScene,
    RestartSceneLoop,
    TalemateError,
    TalemateInterrupt,
    GenerationCancelled,
)
from talemate.game.state import GameState
from talemate.instance import get_agent
from talemate.scene_assets import SceneAssets
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
    SceneMessage,
    TimePassageMessage,
)
from talemate.util import colored_text, count_tokens, extract_metadata, wrap_text
from talemate.util.prompt import condensed
from talemate.world_state import WorldState
from talemate.world_state.manager import WorldStateManager

__all__ = [
    "Character",
    "Actor",
    "Scene",
    "Helper",
    "Player",
]


log = structlog.get_logger("talemate")

async_signals.register("scene_init")
async_signals.register("game_loop_start")
async_signals.register("game_loop")
async_signals.register("game_loop_actor_iter")
async_signals.register("game_loop_new_message")


class ActedAsCharacter(Exception):
    """
    Raised when the user acts as another character
    than the main player character
    """

    pass


class Character:
    """
    A character for the AI to roleplay, with a name, description, and greeting text.
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        greeting_text: str = "",
        gender: str = "female",
        color: str = "cyan",
        example_dialogue: List[str] = [],
        is_player: bool = False,
        history_events: list[dict] = None,
        base_attributes: dict = None,
        details: dict[str, str] = None,
        **kwargs,
    ):
        self.name = name
        self.description = description
        self.greeting_text = greeting_text
        self.example_dialogue = example_dialogue
        self.gender = gender
        self.color = color
        self.is_player = is_player
        self.history_events = history_events or []
        self.base_attributes = base_attributes or {}
        self.details = details or {}
        self.cover_image = kwargs.get("cover_image")
        self.dialogue_instructions = kwargs.get("dialogue_instructions")

        self.memory_dirty = False

    @property
    def persona(self):
        return self.description

    @property
    def serialize(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "greeting_text": self.greeting_text,
            "base_attributes": self.base_attributes,
            "details": self.details,
            "gender": self.gender,
            "color": self.color,
            "example_dialogue": self.example_dialogue,
            "history_events": self.history_events,
            "is_player": self.is_player,
            "cover_image": self.cover_image,
            "dialogue_instructions": self.dialogue_instructions,
        }

    @property
    def sheet(self) -> str:
        sheet = self.base_attributes or {
            "name": self.name,
            "gender": self.gender,
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

    def set_color(self, color: str = None):
        # if no color provided, chose a random color

        if color is None:
            color = random.choice(
                [
                    "#F08080",
                    "#FFD700",
                    "#90EE90",
                    "#ADD8E6",
                    "#DDA0DD",
                    "#FFB6C1",
                    "#FAFAD2",
                    "#D3D3D3",
                    "#B0E0E6",
                    "#FFDEAD",
                ]
            )
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

    def random_dialogue_examples(self, num: int = 3):
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
            self.details[i] = v.replace(f"{orig_name}", self.name)
        self.memory_dirty = True

    def introduce_main_character(self, character):
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

        for attr, value in self.base_attributes.items():
            if attr.startswith("_"):
                continue

            if attr.lower() in ["name", "scenario_context", "_prompt", "_template"]:
                continue

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

            # await memory_agent.add(detail, None)

        for history_event in self.history_events:
            if not history_event or not history_event["summary"]:
                continue

            items.append(
                {
                    "text": history_event["summary"],
                    "meta": {
                        "character": self.name,
                        "typ": "history_event",
                    },
                }
            )

            # await memory_agent.add(history_event["summary"], None)

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

        log.info("commit_single_attribute_to_memory", items=items)

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

        log.info("commit_single_detail_to_memory", items=items)

        await memory_agent.add_many(items)

    async def set_detail(self, name: str, value):
        memory_agent = get_agent("memory")
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
        memory_agent = get_agent("memory")

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
        memory_agent = get_agent("memory")
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


class Helper:
    """
    Wrapper for non-conversational agents, such as summarization agents
    """

    def __init__(self, agent: agents.Agent, **options):
        self.agent = agent
        self.options = options

    @property
    def agent_type(self):
        return self.agent.agent_type


class Actor:
    """
    links a character to an agent
    """

    def __init__(self, character: Character, agent: agents.Agent):
        self.character = character
        self.agent = agent
        self.scene = None
        self.script = []

        if agent:
            agent.character = character

        character.agent = agent
        character.actor = self

    @property
    def history(self):
        return self.scene.history

    async def talk(self):
        """
        Set the message to be sent to the AI
        """

        if self.script:
            return CharacterMessage(self.script.pop(0))

        self.agent.character = self.character

        conversation_context = ConversationContext(
            talking_character=self.character.name,
            other_characters=[
                actor.character.name for actor in self.scene.actors if actor != self
            ],
        )

        with ClientContext(conversation=conversation_context):
            messages = await self.agent.converse(self)

        return messages


class Player(Actor):
    muted = 0
    ai_controlled = 0

    async def talk(self, message: Union[str, None] = None):
        """
        Set the message to be sent to the AI
        """

        if self.muted > 0:
            self.muted -= 1
            return

        if self.ai_controlled > 0:
            self.ai_controlled -= 1

            if not self.agent:
                self.agent = self.scene.get_helper("conversation").agent

            return await super().talk()

        act_as = None

        if not message:
            # Display scene history length before the player character name
            history_length = self.scene.history_length()

            name = colored_text(self.character.name + ": ", self.character.color)
            input = await wait_for_input(
                f"[{history_length}] {name}",
                character=self.character,
                data={"reason": "talk"},
                return_struct=True,
            )
            message = input["message"]
            act_as = input["interaction"].act_as

        if not message:
            return

        if not commands.Manager.is_command(message):
            if '"' not in message and "*" not in message:
                message = f'"{message}"'

            message = util.ensure_dialog_format(message)

            log.warning("player_message", message=message, act_as=act_as)

            if act_as == "$narrator":
                # acting as the narrator
                message = NarratorMessage(message, source="player")
                self.scene.push_history(message)
                self.scene.narrator_message(message)
                raise ActedAsCharacter()
            elif act_as:
                # acting as another character
                character = self.scene.get_character(act_as)
                if not character:
                    raise TalemateError(f"Character {act_as} not found")
                character_message = CharacterMessage(f"{character.name}: {message}")
                self.scene.push_history(character_message)
                self.scene.process_npc_dialogue(character.actor, [character_message])
                raise ActedAsCharacter()
            else:
                # acting as the main player character
                self.message = message

                self.scene.push_history(
                    CharacterMessage(
                        f"{self.character.name}: {message}", source="player"
                    )
                )
                emit("character", self.history[-1], character=self.character)

        return message


class Scene(Emitter):
    """
    A scene containing one ore more AI driven actors to interact with.
    """

    ExitScene = ExitScene

    @classmethod
    def scenes_dir(cls):
        relative_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "..",
            "..",
            "scenes",
        )
        return os.path.abspath(relative_path)

    def __init__(self):
        self.actors = []
        self.helpers = []
        self.history = []
        self.archived_history = []
        self.inactive_characters = {}
        self.assets = SceneAssets(scene=self)
        self.description = ""
        self.intro = ""
        self.outline = ""
        self.main_character = None
        self.static_tokens = 0
        self.max_tokens = 2048
        self.next_actor = None
        self.title = ""

        self.experimental = False
        self.help = ""

        self.name = ""
        self.filename = ""
        self.memory_id = str(uuid.uuid4())[:10]
        self.saved_memory_session_id = None
        self.memory_session_id = str(uuid.uuid4())[:10]
        self.restore_from = None

        # has scene been saved before?
        self.saved = False

        # if immutable_save is True, save will always
        # happen as save-as and not overwrite the original
        self.immutable_save = False

        self.config = load_config()

        self.context = ""
        self.commands = commands.Manager(self)
        self.environment = "scene"
        self.world_state = WorldState()
        self.game_state = GameState()
        self.ts = "PT0S"
        self.active = False

        self.Actor = Actor
        self.Player = Player
        self.Character = Character

        # TODO: deprecate
        self.automated_actions = {}

        self.active_pins = []
        # Add an attribute to store the most recent AI Actor
        self.most_recent_ai_actor = None
        
        # if the user has requested to cancel the current action
        # or series of agent actions this will be true
        #
        # A check to self.continue_actions() will be made
        #
        # if self.cancel_requested is True self.continue_actions() will raise
        # a GenerationCancelled exception
        self.cancel_requested = False

        self.signals = {
            "ai_message": signal("ai_message"),
            "player_message": signal("player_message"),
            "history_add": signal("history_add"),
            "archive_add": signal("archive_add"),
            "game_loop": async_signals.get("game_loop"),
            "game_loop_start": async_signals.get("game_loop_start"),
            "game_loop_actor_iter": async_signals.get("game_loop_actor_iter"),
            "game_loop_new_message": async_signals.get("game_loop_new_message"),
            "scene_init": async_signals.get("scene_init"),
        }

        self.setup_emitter(scene=self)

        self.world_state.emit()

    @property
    def characters(self):
        for actor in self.actors:
            yield actor.character

    @property
    def character_names(self):
        return [character.name for character in self.characters]

    @property
    def npc_character_names(self):
        return [character.name for character in self.get_npc_characters()]

    @property
    def has_active_npcs(self):
        return bool(list(self.get_npc_characters()))

    @property
    def log(self):
        return log

    @property
    def scene_config(self):
        return SceneConfig(
            automated_actions={
                action.uid: action.enabled for action in self.automated_actions.values()
            }
        ).model_dump()

    @property
    def project_name(self):
        return self.name.replace(" ", "-").replace("'", "").lower()

    @property
    def num_history_entries(self):
        return len(self.history)

    @property
    def prev_actor(self):
        # will find the first CharacterMessage in history going from the end
        # and return the character name attached to it to determine the actor
        # that most recently spoke

        for idx in range(len(self.history) - 1, -1, -1):
            if isinstance(self.history[idx], CharacterMessage):
                return self.history[idx].character_name

    @property
    def save_dir(self):
        saves_dir = os.path.join(
            self.scenes_dir(),
            self.project_name,
        )

        if not os.path.exists(saves_dir):
            os.makedirs(saves_dir)

        return saves_dir

    @property
    def full_path(self):
        if not self.filename:
            return None

        return os.path.join(self.save_dir, self.filename)

    @property
    def template_dir(self):
        return os.path.join(self.save_dir, "templates")

    @property
    def auto_save(self):
        return self.config.get("game", {}).get("general", {}).get("auto_save", True)

    @property
    def auto_progress(self):
        return self.config.get("game", {}).get("general", {}).get("auto_progress", True)

    @property
    def world_state_manager(self):
        return WorldStateManager(self)

    @property
    def conversation_format(self):
        return self.get_helper("conversation").agent.conversation_format

    def set_description(self, description: str):
        self.description = description

    def set_intro(self, intro: str):
        self.intro = intro

    def set_name(self, name: str):
        self.name = name

    def set_title(self, title: str):
        self.title = title

    def set_content_context(self, content_context: str):
        self.context = content_context

    def connect(self):
        """
        connect scenes to signals
        """
        handlers["config_saved"].connect(self.on_config_saved)

    def disconnect(self):
        """
        disconnect scenes from signals
        """
        handlers["config_saved"].disconnect(self.on_config_saved)

    def __del__(self):
        self.disconnect()

    def on_config_saved(self, event):
        self.config = event.data
        self.emit_status()

    def apply_scene_config(self, scene_config: dict):
        scene_config = SceneConfig(**scene_config)

        for action, enabled in scene_config.automated_actions.items():
            self.toggle_automated_action(action, enabled)

    async def call_automated_actions(self):
        for action in self.automated_actions.values():
            await action()

    def toggle_automated_action(self, action_uid: str, enabled: bool):
        for action in self.automated_actions.values():
            if action.uid == action_uid:
                action.enabled = enabled
                return

    def recent_history(self, max_tokens: int = 2048):
        scene = self
        history_legnth = len(scene.history)
        num = 0
        idx = history_legnth - 1
        recent_history = []
        total_tokens = 0

        while idx > -1:
            recent_history.insert(0, scene.history[idx])

            total_tokens += util.count_tokens(scene.history[idx])

            num += 1
            idx -= 1

            if total_tokens >= max_tokens:
                break

        return recent_history

    def push_history(self, messages: list[SceneMessage]):
        """
        Adds one or more messages to the scene history
        """

        if isinstance(messages, SceneMessage):
            messages = [messages]

        # there can only ever be one director message in the history
        # so if there is a new DirectorMessage in messages we remove the old one
        # from the history

        for message in messages:
            if isinstance(message, DirectorMessage):
                for idx in range(len(self.history) - 1, -1, -1):
                    if (
                        isinstance(self.history[idx], DirectorMessage)
                        and self.history[idx].source == message.source
                    ):
                        self.history.pop(idx)
                        break

            elif isinstance(message, TimePassageMessage):
                self.advance_time(message.ts)

        self.history.extend(messages)
        self.signals["history_add"].send(
            events.HistoryEvent(
                scene=self,
                event_type="history_add",
                messages=messages,
            )
        )

        loop = asyncio.get_event_loop()
        for message in messages:
            loop.run_until_complete(
                self.signals["game_loop_new_message"].send(
                    events.GameLoopNewMessageEvent(
                        scene=self, event_type="game_loop_new_message", message=message
                    )
                )
            )

    def pop_history(
        self,
        typ: str,
        source: str = None,
        all: bool = False,
        max_iterations: int = None,
        reverse: bool = False,
    ):
        """
        Removes the last message from the history that matches the given typ and source
        """
        iterations = 0

        if not reverse:
            iter_range = range(len(self.history) - 1, -1, -1)
        else:
            iter_range = range(len(self.history))

        to_remove = []

        for idx in iter_range:
            if self.history[idx].typ == typ and (
                self.history[idx].source == source or source is None
            ):
                to_remove.append(self.history[idx])
                if not all:
                    break
            iterations += 1
            if max_iterations and iterations >= max_iterations:
                break

        for message in to_remove:
            self.history.remove(message)

    def find_message(self, typ: str, source: str, max_iterations: int = 100):
        """
        Finds the last message in the history that matches the given typ and source
        """
        iterations = 0
        for idx in range(len(self.history) - 1, -1, -1):
            if self.history[idx].typ == typ and self.history[idx].source == source:
                return self.history[idx]

            iterations += 1
            if iterations >= max_iterations:
                return None

    def message_index(self, message_id: int) -> int:
        """
        Returns the index of the given message in the history
        """
        for idx in range(len(self.history) - 1, -1, -1):
            if self.history[idx].id == message_id:
                return idx
        return -1

    def get_message(self, message_id: int) -> SceneMessage:
        """
        Returns the message in the history with the given id
        """
        for idx in range(len(self.history) - 1, -1, -1):
            if self.history[idx].id == message_id:
                return self.history[idx]

    def last_player_message(self) -> str:
        """
        Returns the last message from the player
        """
        for idx in range(len(self.history) - 1, -1, -1):
            if isinstance(self.history[idx], CharacterMessage):
                if self.history[idx].source == "player":
                    return self.history[idx]

    def collect_messages(
        self, typ: str = None, source: str = None, max_iterations: int = 100
    ):
        """
        Finds all messages in the history that match the given typ and source
        """

        messages = []
        iterations = 0
        for idx in range(len(self.history) - 1, -1, -1):
            if (not typ or self.history[idx].typ == typ) and (
                not source or self.history[idx].source == source
            ):
                messages.append(self.history[idx])

            iterations += 1
            if iterations >= max_iterations:
                break

        return messages

    def snapshot(self, lines: int = 3, ignore: list = None, start: int = None) -> str:
        """
        Returns a snapshot of the scene history
        """

        if not ignore:
            ignore = [ReinforcementMessage, DirectorMessage]

        collected = []

        segment = (
            self.history[-lines:] if not start else self.history[: start + 1][-lines:]
        )

        for idx in range(len(segment) - 1, -1, -1):
            if isinstance(segment[idx], tuple(ignore)):
                continue
            collected.insert(0, segment[idx])
            if len(collected) >= lines:
                break

        return "\n".join([str(message) for message in collected])

    def push_archive(self, entry: data_objects.ArchiveEntry):
        """
        Adds an entry to the archive history.

        The archive history is a list of summarized history entries.
        """

        self.archived_history.append(entry.__dict__)
        self.signals["archive_add"].send(
            events.ArchiveEvent(
                scene=self,
                event_type="archive_add",
                text=entry.text,
                ts=entry.ts,
            )
        )
        emit(
            "archived_history",
            data={
                "history": [
                    archived_history for archived_history in self.archived_history
                ]
            },
        )

    def edit_message(self, message_id: int, message: str):
        """
        Finds the message in `history` by its id and will update its contents
        """

        for i, _message in enumerate(self.history):
            if _message.id == message_id:
                self.history[i].message = message
                emit("message_edited", self.history[i], id=message_id)
                self.log.info("message_edited", message=message, id=message_id)
                return

    async def add_actor(self, actor: Actor):
        """
        Add an actor to the scene
        """
        self.actors.append(actor)
        actor.scene = self

        if isinstance(actor, Player):
            self.main_character = actor
            actor.character.is_player = True

        for actor in self.actors:
            if (
                not isinstance(actor, Player)
                and self.main_character
                and actor.character.introduce_main_character
            ):
                actor.character.introduce_main_character(self.main_character.character)

        if not isinstance(actor, Player):
            if not self.context and actor.character.base_attributes.get(
                "scenario_context"
            ):
                self.context = actor.character.base_attributes["scenario_context"]

            if actor.character.greeting_text and not self.intro:
                self.intro = actor.character.greeting_text
            if not self.name or self.name.lower() == "new scenario":
                self.name = actor.character.name
                self.emit_status()
            if actor.character.base_attributes.get("scenario overview"):
                self.description = actor.character.base_attributes["scenario overview"]

        memory_helper = self.get_helper("memory")
        if memory_helper:
            await actor.character.commit_to_memory(memory_helper.agent)

    async def remove_actor(self, actor: Actor):
        """
        Remove an actor from the scene
        """

        for _actor in self.actors:
            if _actor == actor:
                self.actors.remove(_actor)

        actor.character = None

    def add_helper(self, helper: Helper):
        """
        Add a helper to the scene
        """
        self.helpers.append(helper)
        helper.agent.connect(self)

    def get_helper(self, agent_type):
        """
        Returns the helper of the given agent class if it exists
        """

        for helper in self.helpers:
            if helper.agent_type == agent_type:
                return helper

    def get_character(self, character_name: str, partial: bool = False):
        """
        Returns the character with the given name if it exists
        """

        if not character_name:
            return

        if character_name in self.inactive_characters:
            return self.inactive_characters[character_name]

        for actor in self.actors:
            if not partial and actor.character.name.lower() == character_name.lower():
                return actor.character
            elif partial and character_name.lower() in actor.character.name.lower():
                return actor.character
            elif partial and actor.character.name.lower() in character_name.lower():
                return actor.character

    def get_player_character(self):
        for actor in self.actors:
            if isinstance(actor, Player):
                return actor.character

    def get_npc_characters(self):
        for actor in self.actors:
            if not isinstance(actor, Player):
                yield actor.character

    def num_npc_characters(self) -> int:
        return len(list(self.get_npc_characters()))

    def parse_character_from_line(self, line: str) -> Character:
        """
        Parse a character from a line of text
        """

        for actor in self.actors:
            if actor.character.name.lower() in line.lower():
                return actor.character

    def get_characters(self) -> Generator[Character, None, None]:
        """
        Returns a list of all characters in the scene
        """

        for actor in self.actors:
            yield actor.character

    def process_npc_dialogue(self, actor: Actor, message: str):
        self.saved = False

        # Store the most recent AI Actor
        self.most_recent_ai_actor = actor

        for item in message:
            emit("character", item, character=actor.character)

    def set_description(self, description: str):
        """
        Sets the description of the scene

        Overview of the scenario.
        """
        self.description = description

    def get_intro(self, intro:str = None) -> str:
        """
        Returns the intro text of the scene
        """
        
        if not intro:
            intro = self.intro
        
        try:
            player_name = self.get_player_character().name
            intro = intro.replace("{{user}}", player_name).replace(
                "{{char}}", player_name
            )
        except AttributeError:
            intro = self.intro
            
        if '"' not in intro and "*" not in intro:
            intro = f"*{intro}*"
            
        intro = util.ensure_dialog_format(intro)

        return intro

    def history_length(self):
        """
        Calculate and return the length of all strings in the history added together.
        """
        return count_tokens(self.history)

    def count_messages(self, message_type: str = None, source: str = None) -> int:
        """
        Counts the number of messages in the history that match the given message_type and source
        If no message_type or source is given, will return the total number of messages in the history
        """

        count = 0

        for message in self.history:
            if message_type and message.typ != message_type:
                continue
            if (
                source
                and message.source != source
                and message.secondary_source != source
            ):
                continue
            count += 1

        return count

    def count_character_messages(self, character: Character) -> int:
        return self.count_messages(message_type="character", source=character.name)

    async def summarized_dialogue_history(
        self,
        budget: int = 1024,
        min_dialogue: int = 50,
        keep_director: bool = False,
        add_archieved_history: bool = False,
    ):
        # Will first run context_history and then use the summarizer agent
        # to summarize the history and return the summary

        history = self.context_history(
            budget=budget,
            min_dialogue=min_dialogue,
            keep_director=keep_director,
            sections=False,
            add_archieved_history=add_archieved_history,
        )

        summarizer = self.get_helper("summarizer")

        if not summarizer:
            return ""

        summary = await summarizer.agent.summarize("\n".join(history))

        return summary

    def context_history(
        self, budget: int = 2048, keep_director: Union[bool, str] = False, **kwargs
    ):
        parts_context = []
        parts_dialogue = []

        budget_context = int(0.5 * budget)
        budget_dialogue = int(0.5 * budget)

        conversation_format = self.conversation_format
        actor_direction_mode = self.get_helper("director").agent.actor_direction_mode

        history_offset = kwargs.get("history_offset", 0)
        message_id = kwargs.get("message_id")
        include_reinfocements = kwargs.get("include_reinfocements", True)

        # if message id is provided, find the message in the history
        if message_id:

            if history_offset:
                log.warning(
                    "context_history",
                    message="history_offset is ignored when message_id is provided",
                )

            message_index = self.message_index(message_id)
            history_start = message_index - 1
        else:
            history_start = len(self.history) - (1 + history_offset)

        # collect dialogue

        count = 0

        for i in range(history_start, -1, -1):
            count += 1

            message = self.history[i]

            if message.hidden:
                continue

            if isinstance(message, ReinforcementMessage) and not include_reinfocements:
                continue

            if isinstance(message, DirectorMessage):
                if not keep_director:
                    continue

                if not message.character_name:
                    # skip director messages that are not character specific
                    # TODO: we may want to include these in the future
                    continue

                elif isinstance(keep_director, str) and message.source != keep_director:
                    continue

            if count_tokens(parts_dialogue) + count_tokens(message) > budget_dialogue:
                break

            parts_dialogue.insert(
                0, message.as_format(conversation_format, mode=actor_direction_mode)
            )

        # collect context, ignore where end > len(history) - count

        for i in range(len(self.archived_history) - 1, -1, -1):
            archive_history_entry = self.archived_history[i]
            end = archive_history_entry.get("end")
            start = archive_history_entry.get("start")

            if end is None:
                continue

            if start > len(self.history) - count:
                continue

            try:
                time_message = util.iso8601_diff_to_human(
                    archive_history_entry["ts"], self.ts
                )
                text = f"{time_message}: {archive_history_entry['text']}"
            except Exception as e:
                log.error("context_history", error=e, traceback=traceback.format_exc())
                text = archive_history_entry["text"]

            if count_tokens(parts_context) + count_tokens(text) > budget_context:
                break

            parts_context.insert(0, condensed(text))

        if count_tokens(parts_context + parts_dialogue) < 1024:
            intro = self.get_intro()
            if intro:
                parts_context.insert(0, intro)

        return list(map(str, parts_context)) + list(map(str, parts_dialogue))

    async def rerun(self):
        """
        Rerun the most recent AI response, remove their previous message from the history,
        and call talk() for the most recent AI Character.
        """
        # Remove AI's last response and player's last message from the history
        idx = -1
        try:
            message = self.history[idx]
        except IndexError:
            return

        # while message type is ReinforcementMessage, keep going back in history
        # until we find a message that is not a ReinforcementMessage
        #
        # we need to pop the ReinforcementMessage from the history because
        # previous messages may have contributed to the answer that the AI gave
        # for the reinforcement message

        popped_reinforcement_messages = []

        while isinstance(message, ReinforcementMessage):
            popped_reinforcement_messages.append(self.history.pop())
            message = self.history[idx]

        log.debug(f"Rerunning message: {message} [{message.id}]")

        if message.source == "player":
            return

        current_rerun_context = rerun_context.get()
        if current_rerun_context:
            current_rerun_context.message = message.message

        if isinstance(message, CharacterMessage):
            self.history.pop()
            await self._rerun_character_message(message)
        elif isinstance(message, NarratorMessage) and message.source != "player":
            self.history.pop()
            await self._rerun_narrator_message(message)
        elif isinstance(message, DirectorMessage):
            self.history.pop()
            await self._rerun_director_message(message)
        else:
            return

        for message in popped_reinforcement_messages:
            await self._rerun_reinforcement_message(message)

    async def _rerun_narrator_message(self, message):
        emit("remove_message", "", id=message.id)
        source, arg = (
            message.source.split(":", 1)
            if message.source and ":" in message.source
            else (message.source, None)
        )

        log.debug(f"Rerunning narrator message: {source} - {arg} [{message.id}]")

        narrator = self.get_helper("narrator")
        if source.startswith("progress_story"):
            new_message = await narrator.agent.progress_story(arg)
        elif source == "narrate_scene":
            new_message = await narrator.agent.narrate_scene()
        elif source == "narrate_character" and arg:
            character = self.get_character(arg)
            new_message = await narrator.agent.narrate_character(character)
        elif source == "narrate_query":
            new_message = await narrator.agent.narrate_query(arg)
        elif source == "narrate_dialogue":
            character = self.get_character(arg)
            new_message = await narrator.agent.narrate_after_dialogue(character)
        elif source == "narrate_character_entry":
            character = self.get_character(arg)
            new_message = await narrator.agent.narrate_character_entry(character)
        elif source == "__director__":
            director = self.get_helper("director").agent
            await director.direct_scene(None, None)
            return
        elif source == "paraphrase":
            new_message = await narrator.agent.paraphrase(arg)
        else:
            fn = getattr(narrator.agent, source, None)
            if not fn:
                return
            args = arg.split(";") if arg else []
            new_message = await fn(narrator.agent, *args)

        save_source = f"{source}:{arg}" if arg else source

        new_message = NarratorMessage(new_message, source=save_source)
        self.push_history(new_message)
        emit("narrator", new_message)

        return new_message

    async def _rerun_director_message(self, message):
        emit("remove_message", "", id=message.id)

        source = message.source

        if not source:
            character = list(self.get_npc_characters())[0]
        else:
            character = self.get_character(source)

        if not character:
            log.error("Could not find character for director message")
            return

        log.debug(f"Rerunning director message: {character.name} {message.id}")

        director = self.get_helper("director")

        response = await director.agent.direct_scene(character)
        if not response:
            log.info("Director returned no response")
            return

        if response is True:
            log.info("Director returned True")
            return

        new_message = DirectorMessage(response, source=source)
        self.push_history(new_message)
        emit("director", new_message, character=character)

    async def _rerun_character_message(self, message):
        character_name = message.split(":")[0]

        character = self.get_character(character_name)

        if character.is_player:
            emit("system", "Cannot rerun player's message")
            return

        emit("remove_message", "", id=message.id)

        # Call talk() for the most recent AI Actor
        actor = character.actor

        new_messages = await actor.talk()

        # Print the new messages
        for item in new_messages:
            emit("character", item, character=character)

        await asyncio.sleep(0)

        return new_messages

    async def _rerun_reinforcement_message(self, message):
        log.info(f"Rerunning reinforcement message: {message} [{message.id}]")
        world_state_agent = self.get_helper("world_state").agent

        question, character_name = message.source.split(":")

        await world_state_agent.update_reinforcement(question, character_name)

    def delete_message(self, message_id: int):
        """
        Delete a message from the history
        """
        log.debug(f"Deleting message {message_id}")
        for i, message in enumerate(self.history):
            if message.id == message_id:
                self.history.pop(i)
                log.info(f"Deleted message {message_id}")
                emit("remove_message", "", id=message_id)

                if isinstance(message, TimePassageMessage):
                    self.sync_time()
                    self.emit_status()

                break

    def can_auto_save(self):
        """
        A scene can be autosaved if it has a filename set and is not immutable_save
        """

        return self.filename and not self.immutable_save

    def emit_status(self):
        player_character = self.get_player_character()
        emit(
            "scene_status",
            self.name,
            status="started",
            data={
                "path": self.full_path,
                "filename": self.filename,
                "title": self.title or self.name,
                "environment": self.environment,
                "scene_config": self.scene_config,
                "player_character_name": (
                    player_character.name if player_character else None
                ),
                "inactive_characters": list(self.inactive_characters.keys()),
                "context": self.context,
                "assets": self.assets.dict(),
                "characters": [actor.character.serialize for actor in self.actors],
                "character_colors": {
                    character.name: character.color
                    for character in self.get_characters()
                },
                "scene_time": (
                    util.iso8601_duration_to_human(self.ts, suffix="")
                    if self.ts
                    else None
                ),
                "saved": self.saved,
                "auto_save": self.auto_save,
                "auto_progress": self.auto_progress,
                "can_auto_save": self.can_auto_save(),
                "game_state": self.game_state.model_dump(),
                "active_pins": [pin.model_dump() for pin in self.active_pins],
                "experimental": self.experimental,
                "immutable_save": self.immutable_save,
                "description": self.description,
                "intro": self.intro,
                "help": self.help,
            },
        )

        self.log.debug(
            "scene_status",
            scene=self.name,
            scene_time=self.ts,
            human_ts=util.iso8601_duration_to_human(self.ts, suffix=""),
            saved=self.saved,
        )

    def set_environment(self, environment: str):
        """
        Set the environment of the scene
        """
        self.environment = environment
        self.emit_status()

    def set_content_context(self, context: str):
        """
        Updates the content context of the scene
        """
        self.context = context
        self.emit_status()

    def advance_time(self, ts: str):
        """
        Accepts an iso6801 duration string and advances the scene's world state by that amount
        """
        log.debug(
            "advance_time",
            ts=ts,
            scene_ts=self.ts,
            duration=isodate.parse_duration(ts),
            scene_duration=isodate.parse_duration(self.ts),
        )

        self.ts = isodate.duration_isoformat(
            isodate.parse_duration(self.ts) + isodate.parse_duration(ts)
        )

    def sync_time(self):
        """
        Loops through self.history looking for TimePassageMessage and will
        advance the world state by the amount of time passed for each
        """
        # reset time
        self.ts = "PT0S"

        # archived history (if "ts" is set) should provide the base line
        # find the first archived_history entry from the back that has a ts
        # and set that as the base line

        if self.archived_history:
            for i in range(len(self.archived_history) - 1, -1, -1):
                if self.archived_history[i].get("ts"):
                    self.ts = self.archived_history[i]["ts"]
                    break

            end = self.archived_history[-1].get("end", 0)
        else:
            end = 0

        for message in self.history[end:]:
            if isinstance(message, TimePassageMessage):
                self.advance_time(message.ts)

        self.log.info("sync_time", ts=self.ts)

        # TODO: need to adjust archived_history ts as well
        # but removal also probably means the history needs to be regenerated
        # anyway.

    def calc_time(self, start_idx: int = 0, end_idx: int = None):
        """
        Loops through self.history looking for TimePassageMessage and will
        return the sum iso8601 duration string

        Defines start and end indexes
        """

        ts = "PT0S"
        found = False

        for message in self.history[start_idx:end_idx]:
            if isinstance(message, TimePassageMessage):
                util.iso8601_add(ts, message.ts)
                found = True

        if not found:
            return None

        return ts

    async def load_active_pins(self):
        """
        Loads active pins from the world state manager
        """

        _active_pins = await self.world_state_manager.get_pins(active=True)
        self.active_pins = list(_active_pins.pins.values())

    async def start(self):
        """
        Start the scene
        """
        automated_action.initialize_for_scene(self)

        await self.ensure_memory_db()
        await self.load_active_pins()

        self.emit_status()

        first_loop = True

        while True:
            try:
                if self.environment == "creative":
                    await self._run_creative_loop(init=first_loop)
                else:
                    await self._run_game_loop(init=first_loop)
            except ExitScene:
                break
            except RestartSceneLoop:
                pass
            except ResetScene:
                continue

            first_loop = False

            await asyncio.sleep(0.01)

    async def ensure_memory_db(self):
        memory = self.get_helper("memory").agent
        if not memory.db:
            await memory.set_db()

    async def emit_history(self):
        emit("clear_screen", "")

        self.game_state.init(self)

        await self.signals["scene_init"].send(
            events.SceneStateEvent(scene=self, event_type="scene_init")
        )
        self.narrator_message(self.get_intro())

        for actor in self.actors:
            if (
                not isinstance(actor, Player)
                and actor.character.introduce_main_character
            ):
                actor.character.introduce_main_character(self.main_character.character)

            if (
                actor.character.greeting_text
                and actor.character.greeting_text != self.get_intro()
            ):
                item = f"{actor.character.name}: {actor.character.greeting_text}"
                emit("character", item, character=actor.character)

    async def _run_game_loop(self, init: bool = True):

        await self.ensure_memory_db()

        if init:
            emit("clear_screen", "")

            self.game_state.init(self)

            await self.signals["scene_init"].send(
                events.SceneStateEvent(scene=self, event_type="scene_init")
            )
            self.narrator_message(self.get_intro())

            for actor in self.actors:
                if (
                    not isinstance(actor, Player)
                    and actor.character.introduce_main_character
                ):
                    actor.character.introduce_main_character(
                        self.main_character.character
                    )

                if (
                    actor.character.greeting_text
                    and self.get_intro(actor.character.greeting_text) != self.get_intro()
                ):
                    item = f"{actor.character.name}: {actor.character.greeting_text}"
                    emit("character", item, character=actor.character)

        continue_scene = True
        self.commands = command = commands.Manager(self)

        max_backscroll = (
            self.config.get("game", {}).get("general", {}).get("max_backscroll", 512)
        )

        if init and self.history:
            # history is not empty, so we are continuing a scene
            # need to emit current messages
            for item in self.history[-max_backscroll:]:
                char_name = item.split(":")[0]
                try:
                    actor = self.get_character(char_name).actor
                except AttributeError:
                    # If the character is not an actor, then it is the narrator
                    emit(item.typ, item)
                    continue
                emit("character", item, character=actor.character)
                if not actor.character.is_player:
                    self.most_recent_ai_actor = actor
            self.world_state.emit()
        elif init:
            await self.world_state.request_update(initial_only=True)

        # sort self.actors by actor.character.is_player, making is_player the first element
        self.actors.sort(key=lambda x: x.character.is_player, reverse=True)

        self.active_actor = None
        self.next_actor = None
        signal_game_loop = True

        await self.signals["game_loop_start"].send(
            events.GameLoopStartEvent(scene=self, event_type="game_loop_start")
        )

        await self.world_state_manager.apply_all_auto_create_templates()

        # if loop sets this to True, we skip to the player
        skip_to_player = False

        while continue_scene and self.active:
            log.debug(
                "game loop", auto_save=self.auto_save, auto_progress=self.auto_progress
            )
            try:
                await self.ensure_memory_db()
                await self.load_active_pins()
                game_loop = events.GameLoopEvent(
                    scene=self, event_type="game_loop", had_passive_narration=False
                )
                if signal_game_loop:
                    await self.signals["game_loop"].send(game_loop)

                signal_game_loop = True

                for actor in self.actors:

                    if skip_to_player and not isinstance(actor, Player):
                        continue

                    skip_to_player = False

                    if not actor.character:
                        self.log.warning("Actor has no character", actor=actor)
                        continue

                    if actor.character.memory_dirty:
                        await actor.character.commit_to_memory(
                            self.get_helper("memory").agent
                        )

                    if not self.auto_progress and not actor.character.is_player:
                        # auto progress is disabled, so NPCs don't get automatic turns
                        continue

                    if (
                        self.next_actor
                        and actor.character.name != self.next_actor
                        and self.auto_progress
                    ):
                        self.log.debug(
                            f"Skipping actor",
                            actor=actor.character.name,
                            next_actor=self.next_actor,
                        )
                        continue

                    self.active_actor = actor

                    if not actor.character.is_player:
                        await self.call_automated_actions()

                    try:
                        message = await actor.talk()
                    except ActedAsCharacter:
                        signal_game_loop = False
                        break

                    if not message:
                        continue

                    if isinstance(actor, Player) and type(message) != list:
                        # Don't append message to the history if it's "rerun"
                        if await command.execute(message):
                            signal_game_loop = False
                            break
                        await self.call_automated_actions()

                        await self.signals["game_loop_actor_iter"].send(
                            events.GameLoopActorIterEvent(
                                scene=self,
                                event_type="game_loop_actor_iter",
                                actor=actor,
                                game_loop=game_loop,
                            )
                        )
                        continue

                    self.process_npc_dialogue(actor, message)

                    await self.signals["game_loop_actor_iter"].send(
                        events.GameLoopActorIterEvent(
                            scene=self,
                            event_type="game_loop_actor_iter",
                            actor=actor,
                            game_loop=game_loop,
                        )
                    )

                if self.auto_save:
                    await self.save(auto=True)

                self.emit_status()
            except GenerationCancelled:
                signal_game_loop = False
                skip_to_player = True
                self.next_actor = None
                self.log.warning("Generation cancelled, skipping to player")
            except TalemateInterrupt:
                raise
            except LLMAccuracyError as e:
                self.log.error("game_loop", error=e)
                emit(
                    "system",
                    status="error",
                    message=f"LLM Accuracy Error - The model returned an unexpected response, this may mean this specific model is not suitable for Talemate: {e}",
                )
            except TalemateError as e:
                self.log.error("game_loop", error=e)
            except client.ClientDisabledError as e:
                self.log.error("game_loop", error=e)
                emit(
                    "status",
                    status="error",
                    message=f"{e.client.name} is disabled and cannot be used.",
                )
                signal_game_loop = False
                skip_to_player = True
            except Exception as e:
                self.log.error(
                    "game_loop",
                    error=e,
                    unhandled=True,
                    traceback=traceback.format_exc(),
                )
                emit("system", status="error", message=f"Unhandled Error: {e}")

    async def _run_creative_loop(self, init: bool = True):
        emit("status", message="Switched to scene editor", status="info")

        await self.emit_history()

        continue_scene = True
        self.commands = command = commands.Manager(self)

        while continue_scene:
            try:
                message = await wait_for_input("Enter command: ")

                if not message:
                    continue

                await command.execute(message)

                self.saved = False
                self.emit_status()
            except GenerationCancelled:
                continue
            except TalemateInterrupt:
                raise
            except LLMAccuracyError as e:
                self.log.error("creative_loop", error=e)
                emit(
                    "system",
                    status="error",
                    message=f"LLM Accuracy Error - The model returned an unexpected response, this may mean this specific model is not suitable for Talemate: {e}",
                )
            except TalemateError as e:
                self.log.error("creative_loop", error=e)
            except Exception as e:
                self.log.error(
                    "creative_loop",
                    error=e,
                    unhandled=True,
                    traceback=traceback.format_exc(),
                )
                emit("system", status="error", message=f"Unhandled Error: {e}")

    def set_new_memory_session_id(self):
        self.saved_memory_session_id = self.memory_session_id
        self.memory_session_id = str(uuid.uuid4())[:10]
        log.debug(
            "set_new_memory_session_id",
            saved_memory_session_id=self.saved_memory_session_id,
            memory_session_id=self.memory_session_id,
        )
        self.emit_status()

    async def save(
        self,
        save_as: bool = False,
        auto: bool = False,
        force: bool = False,
        copy_name: str = None,
    ):
        """
        Saves the scene data, conversation history, archived history, and characters to a json file.
        """
        scene = self

        if self.immutable_save and not save_as and not force:
            save_as = True

        if copy_name:
            save_as = True

        if save_as:
            self.filename = copy_name

        if not self.name and not auto:
            self.name = await wait_for_input("Enter scenario name: ")
            self.filename = "base.json"

        elif not self.filename and not auto:
            self.filename = await wait_for_input("Enter save name: ")
            self.filename = self.filename.replace(" ", "-").lower() + ".json"

        if self.filename and not self.filename.endswith(".json"):
            self.filename = f"{self.filename}.json"

        elif not self.filename or not self.name and auto:
            # scene has never been saved, don't auto save
            return

        if save_as:
            self.immutable_save = False
            memory_agent = self.get_helper("memory").agent
            memory_agent.close_db(self)
            self.memory_id = str(uuid.uuid4())[:10]
            await self.commit_to_memory()

        self.set_new_memory_session_id()

        saves_dir = self.save_dir

        log.info("Saving", filename=self.filename, saves_dir=saves_dir, auto=auto)

        # Generate filename with date and normalized character name
        filepath = os.path.join(saves_dir, self.filename)

        # Create a dictionary to store the scene data
        scene_data = {
            "description": scene.description,
            "intro": scene.intro,
            "name": scene.name,
            "title": scene.title,
            "history": scene.history,
            "environment": scene.environment,
            "archived_history": scene.archived_history,
            "characters": [actor.character.serialize for actor in scene.actors],
            "inactive_characters": {
                name: character.serialize
                for name, character in scene.inactive_characters.items()
            },
            "context": scene.context,
            "world_state": scene.world_state.model_dump(),
            "game_state": scene.game_state.model_dump(),
            "assets": scene.assets.dict(),
            "memory_id": scene.memory_id,
            "memory_session_id": scene.memory_session_id,
            "saved_memory_session_id": scene.saved_memory_session_id,
            "immutable_save": scene.immutable_save,
            "ts": scene.ts,
            "help": scene.help,
            "experimental": scene.experimental,
        }

        if not auto:
            emit("status", status="success", message="Saved scene")

        with open(filepath, "w") as f:
            json.dump(scene_data, f, indent=2, cls=save.SceneEncoder)

        self.saved = True

        self.emit_status()

        # add this scene to recent scenes in config
        await self.add_to_recent_scenes()

    async def add_to_recent_scenes(self):
        log.debug("add_to_recent_scenes", filename=self.filename)
        config = load_config(as_model=True)
        config.recent_scenes.push(self)
        config.save()

    async def commit_to_memory(self):
        # will recommit scene to long term memory

        memory = self.get_helper("memory").agent
        memory.drop_db()
        await memory.set_db()

        for ah in self.archived_history:
            ts = ah.get("ts", "PT1S")

            if not ah.get("ts"):
                ah["ts"] = ts

            self.signals["archive_add"].send(
                events.ArchiveEvent(
                    scene=self, event_type="archive_add", text=ah["text"], ts=ts
                )
            )
            await asyncio.sleep(0)

        for character in self.characters:
            await character.commit_to_memory(memory)

        await self.world_state.commit_to_memory(memory)

    def reset(self):
        # remove messages
        self.history = []

        # clear out archived history, but keep pre-established history
        self.archived_history = [
            ah for ah in self.archived_history if ah.get("end") is None
        ]

        self.world_state.reset()

        self.filename = ""

    async def remove_all_actors(self):
        for actor in self.actors:
            actor.character = None

        self.actors = []

    async def restore(self):
        try:
            self.log.info("Restoring", source=self.restore_from)

            if not self.restore_from:
                self.log.error("No restore_from set")
                return

            self.reset()
            self.inactive_characters = {}
            await self.remove_all_actors()

            from talemate.load import load_scene

            await load_scene(
                self,
                os.path.join(self.save_dir, self.restore_from),
                self.get_helper("conversation").agent.client,
            )

            self.emit_status()
        except Exception as e:
            self.log.error("restore", error=e, traceback=traceback.format_exc())

    def sync_restore(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.restore())

    @property
    def serialize(self):
        scene = self
        return {
            "description": scene.description,
            "intro": scene.intro,
            "name": scene.name,
            "history": scene.history,
            "environment": scene.environment,
            "archived_history": scene.archived_history,
            "characters": [actor.character.serialize for actor in scene.actors],
            "inactive_characters": {
                name: character.serialize
                for name, character in scene.inactive_characters.items()
            },
            "context": scene.context,
            "world_state": scene.world_state.model_dump(),
            "game_state": scene.game_state.model_dump(),
            "assets": scene.assets.dict(),
            "memory_id": scene.memory_id,
            "memory_session_id": scene.memory_session_id,
            "saved_memory_session_id": scene.saved_memory_session_id,
            "immutable_save": scene.immutable_save,
            "ts": scene.ts,
            "help": scene.help,
            "experimental": scene.experimental,
            "restore_from": scene.restore_from,
        }

    @property
    def json(self):
        return json.dumps(self.serialize, indent=2, cls=save.SceneEncoder)


    def interrupt(self):
        self.cancel_requested = True

    def continue_actions(self):
        if self.cancel_requested:
            self.cancel_requested = False
            raise GenerationCancelled("action cancelled")