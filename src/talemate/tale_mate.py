import asyncio
import json
import os
import random
import re
import traceback
import uuid
from typing import Dict, Generator, List, Callable

import isodate
import structlog
from blinker import signal

import talemate.agents as agents
import talemate.client as client
import talemate.commands as commands
import talemate.data_objects as data_objects
import talemate.emit.async_signals as async_signals
import talemate.events as events
import talemate.save as save
import talemate.util as util
import talemate.world_state.templates as world_state_templates
from talemate.agents.context import active_agent
from talemate.config import load_config
from talemate.context import interaction
from talemate.emit import Emitter, emit, wait_for_input
from talemate.emit.signals import handlers
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
    ReinforcementMessage,
    SceneMessage,
    TimePassageMessage,
    ContextInvestigationMessage,
    MESSAGES as MESSAGE_TYPES,
)
from talemate.util import count_tokens
from talemate.util.prompt import condensed
from talemate.world_state import WorldState
from talemate.world_state.manager import WorldStateManager
from talemate.game.engine.nodes.core import GraphState
from talemate.game.engine.nodes.layout import load_graph
from talemate.scene.intent import SceneIntent
        
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
async_signals.register("player_turn_start")


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

    def __repr__(self):
        return f"Character: {self.name}"

    def set_color(self, color: str = None):
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
            if isinstance(v, str):
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

        if agent:
            agent.character = character

        character.agent = agent
        character.actor = self

    @property
    def history(self):
        return self.scene.history

class Player(Actor):
    muted = 0
    ai_controlled = 0

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
        self.layered_history = []
        self.assets = SceneAssets(scene=self)
        self.description = ""
        self.intro = ""
        self.outline = ""
        self.title = ""
        self.writing_style_template = None

        self.experimental = False
        self.help = ""

        self.name = ""
        self.filename = ""
        self._nodes_filename = ""
        self._creative_nodes_filename = ""
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
        self.agent_state = {}
        self.intent_state = SceneIntent()
        self.ts = "PT0S"
        self.active = False
        self.Actor = Actor
        self.Player = Player
        self.Character = Character
        
        self.narrator_character_object = Character(name="__narrator__")

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
            "player_turn_start": async_signals.get("player_turn_start"),
        }

        self.setup_emitter(scene=self)

        self.world_state.emit()

    @property
    def main_character(self) -> Actor | None:
        try:
            return self.get_player_character().actor
        except AttributeError:
            return None

    @property
    def player_character_exists(self) -> bool:
        try:
            character = self.get_player_character()
            return character is not None and character.is_player
        except AttributeError:
            return False

    @property
    def characters(self):
        for actor in self.actors:
            yield actor.character

    @property
    def npcs(self):
        for actor in self.actors:
            if not actor.character.is_player:
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
    def project_name(self) -> str:
        return self.name.replace(" ", "-").replace("'", "").lower()

    @property
    def save_files(self) -> list[str]:
        """
        Returns list of save files for the current scene (*.json files
        in the save_dir)
        """
        if hasattr(self, "_save_files"):
            return self._save_files
        
        save_files = []
        
        for file in os.listdir(self.save_dir):
            if file.endswith(".json"):
                save_files.append(file)
                
        self._save_files = sorted(save_files)
        
        return self._save_files

    @property
    def num_history_entries(self):
        return len(self.history)

    @property
    def prev_actor(self) -> str:
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
    def nodes_dir(self):
        return os.path.join(self.save_dir, "nodes")
        
    @property
    def auto_save(self):
        return self.config.get("game", {}).get("general", {}).get("auto_save", True)

    @property
    def auto_progress(self):
        return self.config.get("game", {}).get("general", {}).get("auto_progress", True)

    @property
    def world_state_manager(self) -> WorldStateManager:
        return WorldStateManager(self)

    @property
    def conversation_format(self):
        return self.get_helper("conversation").agent.conversation_format

    @property
    def writing_style(self) -> world_state_templates.WritingStyle | None:
        
        if not self.writing_style_template:
            return None
        
        try:
            group_uid, template_uid = self.writing_style_template.split("__", 1)
            return self._world_state_templates.find_template(group_uid, template_uid)
        except ValueError:
            return None
    
    @property
    def max_backscroll(self):
        return self.config.get("game", {}).get("general", {}).get("max_backscroll", 512)    

    @property
    def nodes_filename(self):
        return self._nodes_filename or "scene-loop.json"

    @nodes_filename.setter
    def nodes_filename(self, value: str):
        self._nodes_filename = value or ""
        
    @property
    def nodes_filepath(self) -> str:
        return os.path.join(self.nodes_dir, self.nodes_filename)

    @property
    def creative_nodes_filename(self):
        return self._creative_nodes_filename or "creative-loop.json"
    
    @creative_nodes_filename.setter
    def creative_nodes_filename(self, value: str):
        self._creative_nodes_filename = value or ""
    
    @property
    def creative_nodes_filepath(self) -> str:
        return os.path.join(self.nodes_dir, self.creative_nodes_filename)

    @property
    def intent(self) -> dict:
        phase = self.intent_state.phase
        if not phase:
            return {}
        
        return {
            "name": self.intent_state.current_scene_type.name,
            "intent": phase.intent,
        }
    
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

    def pop_message(self, message: SceneMessage | int) -> bool:
        """
        Removes the last message from the history that matches the given message
        """
        if isinstance(message, SceneMessage):
            try:
                self.history.remove(message)
            except ValueError:
                return False
            return True
        elif isinstance(message, int):
            message = self.find_message(message)
            if message:
                self.history.remove(message)
                return True
            return False
        else:
            raise ValueError("Invalid message type")

    def pop_history(
        self,
        typ: str,
        source: str = None,
        all: bool = False,
        max_iterations: int = None,
        reverse: bool = False,
        meta_hash: int = None,
        **filters
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
            message = self.history[idx]
            
            if message.typ != typ:
                iterations += 1
                continue
                
            if source is not None and message.source != source:
                iterations += 1
                continue
                
            if meta_hash is not None and message.meta_hash != meta_hash:
                iterations += 1
                continue
            
            # Apply additional filters
            valid = True
            for filter_name, filter_value in filters.items():
                if getattr(message, filter_name, None) != filter_value:
                    valid = False
                    break
                    
            if valid:
                to_remove.append(message)
                if not all:
                    break
                    
            iterations += 1
            if max_iterations and iterations >= max_iterations:
                break

        for message in to_remove:
            self.history.remove(message)

    def find_message(self, typ: str, max_iterations: int = 100, **filters):
        """
        Finds the last message in the history that matches the given typ and source
        """
        iterations = 0
        for idx in range(len(self.history) - 1, -1, -1):
            message: SceneMessage = self.history[idx]
            
            iterations += 1
            if iterations >= max_iterations:
                return None
            
            if message.typ != typ:
                continue
            
            for filter_name, filter_value in filters.items():
                if getattr(message, filter_name, None) != filter_value:
                    continue
            
            return self.history[idx]



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
                
    def last_message_of_type(
        self, 
        typ: str | list[str], 
        source: str = None,
        max_iterations: int = None, 
        stop_on_time_passage: bool = False,
        on_iterate: Callable = None,
        **filters
    ) -> SceneMessage | None:
        """
        Returns the last message of the given type and source
        
        Arguments:
        - typ: str | list[str] - the type of message to find
        - source: str - the source of the message
        - max_iterations: int - the maximum number of iterations to search for the message
        - stop_on_time_passage: bool - if True, the search will stop when a TimePassageMessage is found
        - on_iterate: Callable - a function to call on each iteration of the search
        Keyword Arguments:
        Any additional keyword arguments will be used to filter the messages against their attributes
        """
        
        if not isinstance(typ, list):
            typ = [typ]
            
        num_iterations = 0
        
        for idx in range(len(self.history) - 1, -1, -1):
            
            if max_iterations is not None and num_iterations >= max_iterations:
                return None
            
            message = self.history[idx]
            
            if on_iterate:
                on_iterate(message)
            
            if isinstance(message, TimePassageMessage) and stop_on_time_passage:
                return None
            
            num_iterations += 1
            
            if message.typ not in typ or (source and message.source != source):
                continue
            
            valid = True
            
            for filter_name, filter_value in filters.items():
                message_value = getattr(message, filter_name, None)
                if message_value != filter_value:
                    valid = False
                    break
                
            if valid:
                return message

    def collect_messages(
        self, 
        typ: str | list[str] = None, 
        source: str = None,
        max_iterations: int = 100,
        max_messages: int | None = None,
        stop_on_time_passage: bool = False,
        start_idx: int | None = None,
    ):
        """
        Finds all messages in the history that match the given typ and source
        """

        if typ and not isinstance(typ, list):
            typ = [typ]

        messages = []
        iterations = 0
        collected = 0
        
        if start_idx is None:
            start_idx = len(self.history) - 1
        
        for idx in range(start_idx, -1, -1):
            message = self.history[idx]
            if (not typ or message.typ in typ) and (
                not source or message.source == source
            ):
                messages.append(message)
                collected += 1
                if max_messages is not None and collected >= max_messages:
                    break
            if isinstance(message, TimePassageMessage) and stop_on_time_passage:
                break

            iterations += 1
            if iterations >= max_iterations:
                break

        return messages

    def snapshot(
        self, 
        lines: int = 3, 
        ignore: list[str | SceneMessage] = None, 
        start: int = None,
        as_format: str = "movie_script",
    ) -> str:
        """
        Returns a snapshot of the scene history
        """

        if not ignore:
            ignore = [ReinforcementMessage, DirectorMessage, ContextInvestigationMessage]
        else:
            # ignore me also be a list of message type strings (e.g. 'director')
            # convert to class types
            _ignore = []
            for item in ignore:
                if isinstance(item, str):
                    _ignore.append(MESSAGE_TYPES.get(item)) 
                elif isinstance(item, SceneMessage):
                    _ignore.append(item)
                else:
                    raise ValueError("ignore must be a list of strings or SceneMessage types")
            ignore = _ignore

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

        return "\n".join([message.as_format(as_format) for message in collected])

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


    async def remove_character(self, character: Character):
        """
        Remove a character from the scene
        
        Class remove_actor if the character is active
        otherwise remove from inactive_characters.
        """
        
        for actor in self.actors:
            if actor.character == character:
                await self.remove_actor(actor)
        
        if character.name in self.inactive_characters:
            del self.inactive_characters[character.name]


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
        
        if character_name == "__narrator__":
            return self.narrator_character_object
        
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
            
        # No active player found, return the first NPC
        for actor in self.actors:
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

    def parse_characters_from_text(self, text: str, exclude_active:bool=False) -> list[Character]:
        """
        Parse characters from a block of text
        """

        characters = []
        text = condensed(text.lower())

        # active characters
        if not exclude_active:
            for actor in self.actors:
                # use regex with word boundaries to match whole words
                if re.search(rf"\b{actor.character.name.lower()}\b", text):
                    characters.append(actor.character)
                    
        # inactive characters
        for character in self.inactive_characters.values():
            if re.search(rf"\b{character.name.lower()}\b", text):
                characters.append(character)

        return sorted(characters, key=lambda x: len(x.name))

    def get_characters(self) -> Generator[Character, None, None]:
        """
        Returns a list of all characters in the scene
        """

        for actor in self.actors:
            yield actor.character

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
            
        editor = self.get_helper("editor").agent
            
        if editor.fix_exposition_enabled and editor.fix_exposition_narrator:
            if '"' not in intro and "*" not in intro:
                intro = f"*{intro}*"
            intro = editor.fix_exposition_in_text(intro)

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

    def context_history(
        self, budget: int = 8192, **kwargs
    ):
        parts_context = []
        parts_dialogue = []

        budget_context = int(0.5 * budget)
        budget_dialogue = int(0.5 * budget)
        
        keep_director = kwargs.get("keep_director", False)
        keep_context_investigation = kwargs.get("keep_context_investigation", True)
        show_hidden = kwargs.get("show_hidden", False)

        conversation_format = self.conversation_format
        actor_direction_mode = self.get_helper("director").agent.actor_direction_mode
        layered_history_enabled = self.get_helper("summarizer").agent.layered_history_enabled
        include_reinforcements = kwargs.get("include_reinforcements", True)
        assured_dialogue_num = kwargs.get("assured_dialogue_num", 5)
        
        chapter_labels = kwargs.get("chapter_labels", False)
        chapter_numbers = []

        history_len = len(self.history)


        # CONTEXT
        # collect context, ignore where end > len(history) - count
        if not self.layered_history or not layered_history_enabled or not self.layered_history[0]:
            
            # no layered history available

            for i in range(len(self.archived_history) - 1, -1, -1):
                archive_history_entry = self.archived_history[i]
                end = archive_history_entry.get("end")

                if end is None:
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
                
                text = condensed(text)
                
                parts_context.insert(0, text)
                    
        else:
            
            # layered history available
            # start with the last layer and work backwards
            
            next_layer_start = None
            num_layers = len(self.layered_history)
            
            for i in range(len(self.layered_history) - 1, -1, -1):
                
                log.debug("context_history - layered history", i=i, next_layer_start=next_layer_start)
                
                if not self.layered_history[i]:
                    continue
                
                k = next_layer_start if next_layer_start is not None else 0
                
                for layered_history_entry in self.layered_history[i][next_layer_start if next_layer_start is not None else 0:]:
                    
                    time_message_start = util.iso8601_diff_to_human(
                        layered_history_entry["ts_start"], self.ts
                    )
                    time_message_end = util.iso8601_diff_to_human(
                        layered_history_entry["ts_end"], self.ts
                    )
                    
                    if time_message_start == time_message_end:
                        time_message = time_message_start
                    else:
                        time_message = f"Start:{time_message_start}, End:{time_message_end}" if time_message_start != time_message_end else time_message_start
                    text = f"{time_message} {layered_history_entry['text']}"
                    
                    # prepend chapter labels
                    if chapter_labels:
                        chapter_number = f"{num_layers - i}.{k + 1}"
                        text = f"### Chapter {chapter_number}\n{text}"
                        chapter_numbers.append(chapter_number)
                    
                    parts_context.append(text)
                    
                    k += 1
                    
                next_layer_start = layered_history_entry["end"] + 1
            
            # collect archived history entries that have not yet been
            # summarized to the layered history
            base_layer_start = self.layered_history[0][-1]["end"] + 1 if self.layered_history[0] else None
            
            if base_layer_start is not None:
                i = 0
                
                # if chapter labels have been appanded, we need to
                # open a new section for the current scene
                
                if chapter_labels:
                    parts_context.append("### Current\n")
                
                for archive_history_entry in self.archived_history[base_layer_start:]:
                    time_message = util.iso8601_diff_to_human(
                        archive_history_entry["ts"], self.ts
                    )
                    
                    text = f"{time_message}: {archive_history_entry['text']}"
                    
                    text = condensed(text)
                    
                    parts_context.append(text)

                    i += 1

        # log.warn if parts_context token count > budget_context
        if count_tokens(parts_context) > budget_context:
            # chop off the top until it fits
            while count_tokens(parts_context) > budget_context:
                parts_context.pop(0)

        # DIALOGUE
        try:
            summarized_to = self.archived_history[-1]["end"] if self.archived_history else 0
        except KeyError:
            # only static archived history entries exist (pre-entered history
            # that doesnt have start and end timestamps)
            summarized_to = 0
        
        
        # if summarized_to somehow is bigger than the length of the history
        # since we have no way to determine where they sync up just put as much of
        # the dialogue as possible
        if summarized_to and summarized_to >= history_len:
            log.warning("context_history", message="summarized_to is greater than history length - may want to regenerate history")
            summarized_to = 0
            
        log.debug("context_history", summarized_to=summarized_to, history_len=history_len)
        
        dialogue_messages_collected = 0 
        
        #for message in self.history[summarized_to if summarized_to is not None else 0:]:
        for i in range(len(self.history) - 1, -1, -1):
            message = self.history[i]
            
            if i < summarized_to and dialogue_messages_collected >= assured_dialogue_num:
                break

            if message.hidden and not show_hidden:
                continue
            
            if isinstance(message, ReinforcementMessage) and not include_reinforcements:
                continue

            elif isinstance(message, DirectorMessage):
                if not keep_director:
                    continue

                if not message.character_name:
                    # skip director messages that are not character specific
                    # TODO: we may want to include these in the future
                    continue

                elif isinstance(keep_director, str) and message.character_name != keep_director:
                    continue
            
            elif isinstance(message, ContextInvestigationMessage) and not keep_context_investigation:
                continue


            if count_tokens(parts_dialogue) + count_tokens(message) > budget_dialogue:
                break
            
            parts_dialogue.insert(
                0, 
                message.as_format(conversation_format, mode=actor_direction_mode)
            )
            
            if isinstance(message, CharacterMessage):
                dialogue_messages_collected += 1
                    
            
        if count_tokens(parts_context) < 128:
            intro = self.get_intro()
            if intro:
                parts_context.insert(0, intro)
                

        active_agent_ctx = active_agent.get()
        if active_agent_ctx:
            active_agent_ctx.state["chapter_numbers"] = chapter_numbers

        return list(map(str, parts_context)) + list(map(str, parts_dialogue))

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

    def emit_status(self, restored: bool = False):
        player_character = self.get_player_character()
        emit(
            "scene_status",
            self.name,
            status="started",
            data={
                "path": self.full_path,
                "filename": self.filename,
                "prject_name": self.project_name,
                "nodes_filename": self.nodes_filename,
                "creative_nodes_filename": self.creative_nodes_filename,
                "save_files": self.save_files,
                "restore_from": self.restore_from,
                "restored": restored,
                "title": self.title or self.name,
                "environment": self.environment,
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
                "agent_state": self.agent_state,
                "active_pins": [pin.model_dump() for pin in self.active_pins],
                "experimental": self.experimental,
                "immutable_save": self.immutable_save,
                "description": self.description,
                "intro": self.intro,
                "help": self.help,
                "writing_style_template": self.writing_style_template,
                "intent": self.intent,
            },
        )

        self.log.debug(
            "scene_status",
            scene=self.name,
            scene_time=self.ts,
            human_ts=util.iso8601_duration_to_human(self.ts, suffix="") if self.ts else None,
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
        
    def fix_time(self):
        """
        New implementation of sync_time that will fix time across the board
        using the base history as the sole source of truth.
        
        This means first identifying the time jumps in the base history by
        looking for TimePassageMessages and then applying those time jumps
        
        to the archived history and the layered history based on their start and end
        indexes.
        """
        try:
            ts = self.ts
            self._fix_time()
        except Exception as e:
            log.exception("fix_time", exc=e)
            self.ts = ts
        
    def _fix_time(self):
        starting_time = "PT0S"
        
        for archived_entry in self.archived_history:
            if "ts" in archived_entry and "end" not in archived_entry:
                starting_time = archived_entry["ts"]
            elif "end" in archived_entry:
                break
        
        # store time jumps by index
        time_jumps = []
        
        for idx, message in enumerate(self.history):
            if isinstance(message, TimePassageMessage):
                time_jumps.append((idx, message.ts))
        
        # now make the timejumps cumulative, meaning that each time jump
        # will be the sum of all time jumps up to that point
        cumulative_time_jumps = []
        ts = starting_time
        for idx, ts_jump in time_jumps:
            ts = util.iso8601_add(ts, ts_jump)
            cumulative_time_jumps.append((idx, ts))
            
        try:
            ending_time = cumulative_time_jumps[-1][1]
        except IndexError:
            # no time jumps found
            ending_time = starting_time
            self.ts = ending_time
            return    
            
        # apply time jumps to the archived history
        ts = starting_time
        for _, entry in enumerate(self.archived_history):
            
            if "end" not in entry:
                continue
            
            # we need to find best_ts by comparing entry["end"]
            # index to time_jumps (find the closest time jump that is
            # smaller than entry["end"])
            
            best_ts = None
            for jump_idx, jump_ts in cumulative_time_jumps:
                if jump_idx < entry["end"]:
                    best_ts = jump_ts
                else:
                    break
            
            if best_ts:
                entry["ts"] = best_ts
                ts = entry["ts"]
            else:
                entry["ts"] = ts

        # finally set scene time to last entry in time_jumps
        log.debug("fix_time", ending_time=ending_time)
        self.ts = ending_time

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
                ts = util.iso8601_add(ts, message.ts)
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
        
    async def ensure_memory_db(self):
        memory = self.get_helper("memory").agent
        if not memory.db:
            await memory.set_db()

    async def emit_history(self):
        emit("clear_screen", "")        
        # this is mostly to support character cards
        # we introduce the main character to all such characters, replacing
        # the {{ user }} placeholder
        for npc in self.npcs:
            if npc.introduce_main_character:
                npc.introduce_main_character(self.main_character.character)
        
        # emit intro
        intro:str = self.get_intro()
        self.narrator_message(intro)
        
        
        # cycle npcs again and if they have a greeting_text
        # emit it
        for npc in self.npcs:
            
            if not npc.greeting_text:
                continue
            
            similar_to_intro, _, _ = util.similarity_score(npc.greeting_text, [intro])
            
            if similar_to_intro:
                continue
            emit("character", f"{npc.name}: {npc.greeting_text}", character=npc)
        
        # emit history
        for message in self.history[-self.max_backscroll:]:
            if isinstance(message, CharacterMessage):
                character = self.get_character(message.character_name)
            else:
                character = None
            emit(message.typ, message, character=character)

    async def start(self):
        """
        Start the scene
        """
        await self.ensure_memory_db()
        await self.load_active_pins()

        self.emit_status()

        first_loop = True

        while True:
            try:
                log.warning(f"Starting scene loop: {self.environment}")
                
                self.world_state.emit()
                
                if self.environment == "creative":
                    self.creative_node_graph, _ = load_graph(self.creative_nodes_filename, [self.save_dir])
                    await self._run_creative_loop(init=first_loop)
                else:
                    self.node_graph, _ = load_graph(self.nodes_filename, [self.save_dir])
                    await self._run_game_loop(init=first_loop)
            except ExitScene:
                break
            except RestartSceneLoop:
                pass
            except ResetScene:
                continue

            first_loop = False

            await asyncio.sleep(0.01)

    async def _game_startup(self):
        self.commands = command = commands.Manager(self)
        
        await self.signals["scene_init"].send(
            events.SceneStateEvent(scene=self, event_type="scene_init")
        )
        
        
    async def _run_game_loop(self, init: bool = True, node_graph = None):        
        if init:
            await self._game_startup()
            await self.emit_history()
            await self.world_state.request_update(initial_only=True)
        
        self.nodegraph_state = state = GraphState()
        state.data["continue_scene"] = True
        
        while state.data["continue_scene"] and self.active:
            try:
                await self.node_graph.execute(state)
            except GenerationCancelled:
                state.shared["signal_game_loop"] = False
                state.shared["skip_to_player"] = True
                self.cancel_requested = False
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
                state.shared["signal_game_loop"] = False
                state.shared["skip_to_player"] = True
            except Exception as e:
                self.log.error(
                    "game_loop",
                    error=e,
                    unhandled=True,
                    traceback=traceback.format_exc(),
                )
                emit("system", status="error", message=f"Unhandled Error: {e}")


    async def _run_creative_loop(self, init: bool = True):
        await self.emit_history()
        
        self.nodegraph_state = state = GraphState()
        state.data["continue_scene"] = True
        
        while state.data["continue_scene"] and self.active:
            try:
                await self.creative_node_graph.execute(state)
            except GenerationCancelled:
                self.cancel_requested = False
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

        return

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
        scene_data = self.serialize
        
        if not auto:
            emit("status", status="success", message="Saved scene")

        with open(filepath, "w") as f:
            json.dump(scene_data, f, indent=2, cls=save.SceneEncoder)

        self.saved = True

        if hasattr(self, "_save_files"):
            delattr(self, "_save_files")

        self.emit_status()

        # add this scene to recent scenes in config
        await self.add_to_recent_scenes()

    async def save_restore(self, filename:str):
        """
        Serializes the scene to a file.
        
        immutable_save will be set to True
        memory_sesion_id will be randomized
        """
        
        serialized = self.serialize
        serialized["immutable_save"] = True
        serialized["memory_session_id"] = str(uuid.uuid4())[:10]
        serialized["saved_memory_session_id"] = self.memory_session_id
        serialized["memory_id"] = str(uuid.uuid4())[:10]
        filepath = os.path.join(self.save_dir, filename)
        with open(filepath, "w") as f:
            json.dump(serialized, f, indent=2, cls=save.SceneEncoder)

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

    async def reset_memory(self):
        memory_agent = self.get_helper("memory").agent
        memory_agent.close_db(self)
        self.memory_id = str(uuid.uuid4())[:10]
        await self.commit_to_memory()

        self.set_new_memory_session_id()

    async def restore(self, save_as:str | None=None):
        try:
            self.log.info("Restoring", source=self.restore_from)

            restore_from = self.restore_from

            if not self.restore_from:
                self.log.error("No save file specified to restore from.")
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
            
            await self.reset_memory()
            
            if save_as:
                self.restore_from = restore_from
                await self.save(save_as=True, copy_name=save_as)
            else:
                self.filename = None
            self.emit_status(restored=True)
            
            interaction_state = interaction.get()
            
            if interaction_state:
                # Break and restart the game loop
                interaction_state.reset_requested = True
            
        except Exception as e:
            self.log.error("restore", error=e, traceback=traceback.format_exc())

    def sync_restore(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.restore())

    @property
    def serialize(self) -> dict:
        scene = self
        return {
            "description": scene.description,
            "intro": scene.intro,
            "name": scene.name,
            "title": scene.title,
            "history": scene.history,
            "environment": scene.environment,
            "archived_history": scene.archived_history,
            "layered_history": scene.layered_history,
            "characters": [actor.character.serialize for actor in scene.actors],
            "inactive_characters": {
                name: character.serialize
                for name, character in scene.inactive_characters.items()
            },
            "context": scene.context,
            "world_state": scene.world_state.model_dump(),
            "game_state": scene.game_state.model_dump(),
            "agent_state": scene.agent_state,
            "intent_state": scene.intent_state.model_dump(),
            "assets": scene.assets.dict(),
            "memory_id": scene.memory_id,
            "memory_session_id": scene.memory_session_id,
            "saved_memory_session_id": scene.saved_memory_session_id,
            "immutable_save": scene.immutable_save,
            "ts": scene.ts,
            "help": scene.help,
            "experimental": scene.experimental,
            "writing_style_template": scene.writing_style_template,
            "restore_from": scene.restore_from,
            "nodes_filename": scene._nodes_filename,
            "creative_nodes_filename": scene._creative_nodes_filename,
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