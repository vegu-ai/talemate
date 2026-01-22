import asyncio
import json
import os
import re
import traceback
import uuid
from typing import Generator, Callable

import isodate
import structlog
from blinker import signal

import talemate.agents as agents
import talemate.client as client
import talemate.commands as commands
import talemate.emit.async_signals as async_signals
import talemate.events as events
import talemate.save as save
import talemate.util as util
import talemate.world_state.templates as world_state_templates
from talemate.agents.context import active_agent
from talemate.config import Config, get_config
from talemate.context import interaction
from talemate.emit import Emitter, emit
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
from talemate.scene_assets import SceneAssets
from talemate.scene.episodes import EpisodesManager
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
from talemate.game.engine.nodes.packaging import initialize_packages
from talemate.scene.intent import SceneIntent
from talemate.history import emit_archive_add, ArchiveEntry
from talemate.character import Character
from talemate.game.engine.context_id.character import (
    CharacterContext,
    CharacterContextItem,
)
from talemate.agents.tts.schema import VoiceLibrary
from talemate.instance import get_agent
from talemate.changelog import InMemoryChangelog
from talemate.shared_context import SharedContext

__all__ = [
    "Character",
    "Actor",
    "Scene",
    "Player",
]


log = structlog.get_logger("talemate")

async_signals.register(
    "scene_init",
    "scene_init_after",
    "game_loop_start",
    "game_loop",
    "game_loop_actor_iter",
    "game_loop_new_message",
    "player_turn_start",
    "push_history",
    "push_history.after",
)


class Actor:
    """
    links a character to an agent
    """

    def __init__(self, character: Character, agent: agents.Agent):
        # TODO: all of that is horrible, need to refactor this
        # Do we even need a middleman actor class?
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
        self.character_data = {}
        self.active_characters = []
        self.layered_history = []
        # When set, any active wait-for-input loop will raise RestartSceneLoop,
        # allowing websocket-triggered environment switches to restart the scene loop.
        self.restart_scene_loop_requested = False
        self.shared_context: SharedContext | None = None
        self.assets = SceneAssets(scene=self)
        self.voice_library: VoiceLibrary = VoiceLibrary()
        self.description = ""
        self.intro = ""
        self.outline = ""
        self.title = ""
        self.writing_style_template = None
        # map of agent_name -> world-state template uid (group__template)
        self.agent_persona_templates: dict[str, str] = {}
        self.visual_style_template = None
        self.id = str(uuid.uuid4())[:10]
        self.rev = 0

        self.experimental = False
        self.help = ""

        self.name = ""
        self.filename = ""
        self._project_name = ""
        self._nodes_filename = ""
        self._creative_nodes_filename = ""
        self.memory_id = str(uuid.uuid4())[:10]
        self.saved_memory_session_id = None
        self.memory_session_id = str(uuid.uuid4())[:10]
        self.restore_from = None
        self._changelog = None

        # has scene been saved before?
        self.saved = False

        # if immutable_save is True, save will always
        # happen as save-as and not overwrite the original
        self.immutable_save = False

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

        self.nodegraph_state: GraphState | None = None

        self.narrator_character_object = Character(name="__narrator__")

        self.active_pins = []
        # Add an attribute to store the most recent AI Actor
        self.most_recent_ai_actor = None

        # List of game state paths to watch in debug tools
        self.game_state_watch_paths: list[str] = []

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
            "push_history": async_signals.get("push_history"),
            "push_history.after": async_signals.get("push_history.after"),
            "game_loop": async_signals.get("game_loop"),
            "game_loop_start": async_signals.get("game_loop_start"),
            "game_loop_actor_iter": async_signals.get("game_loop_actor_iter"),
            "game_loop_new_message": async_signals.get("game_loop_new_message"),
            "scene_init": async_signals.get("scene_init"),
            "player_turn_start": async_signals.get("player_turn_start"),
            "config.changed": async_signals.get("config.changed"),
        }

        self.setup_emitter(scene=self)

        self.world_state.emit()

        # Debounce tracking for emit_status
        self._emit_status_debounce_task: asyncio.Task | None = None

    @property
    def config(self) -> Config:
        return get_config()

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
    def characters(self) -> Generator[Character, None, None]:
        """
        Returns all active characters in the scene
        """

        for actor in self.actors:
            yield actor.character

    @property
    def all_characters(self) -> Generator[Character, None, None]:
        """
        Returns all characters in the scene, including inactive characters
        """
        for character in self.character_data.values():
            yield character

    @property
    def inactive_characters(self) -> dict[str, Character]:
        """
        Returns all inactive characters in the scene
        """
        inactive = {}
        for character in self.character_data.values():
            if character.name not in self.active_characters:
                inactive[character.name] = character
        return inactive

    @property
    def all_character_names(self):
        return [character.name for character in self.all_characters]

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
        if self._project_name:
            return self._project_name
        return self.name.replace(" ", "-").replace("'", "").lower()

    @project_name.setter
    def project_name(self, value: str):
        self._project_name = value

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
    def info_dir(self):
        return os.path.join(self.save_dir, "info")

    @property
    def backups_dir(self):
        return os.path.join(self.save_dir, "backups")

    @property
    def changelog_dir(self):
        return os.path.join(self.save_dir, "changelog")

    @property
    def shared_context_dir(self):
        return os.path.join(self.save_dir, "shared-context")

    @property
    def auto_save(self) -> bool:
        return self.config.game.general.auto_save

    @property
    def auto_backup(self) -> bool:
        # deprecated; always False for compatibility
        return False

    @property
    def auto_progress(self) -> bool:
        return self.config.game.general.auto_progress

    @property
    def world_state_manager(self) -> WorldStateManager:
        return WorldStateManager(self)

    @property
    def episodes(self) -> EpisodesManager:
        return EpisodesManager(self)

    @property
    def conversation_format(self):
        return get_agent("conversation").conversation_format

    @property
    def writing_style(self) -> world_state_templates.WritingStyle | None:
        if not self.writing_style_template:
            return None

        try:
            group_uid, template_uid = self.writing_style_template.split("__", 1)
            # Ensure template collection is initialized via manager
            return self.world_state_manager.template_collection.find_template(
                group_uid, template_uid
            )
        except ValueError:
            return None

    def agent_persona(self, agent_name: str):
        """
        Resolve AgentPersona template for the given agent name from
        self.agent_persona_templates. Returns template instance or None.
        """
        uid = (self.agent_persona_templates or {}).get(agent_name)
        if not uid:
            return None
        try:
            group_uid, template_uid = uid.split("__", 1)
        except ValueError:
            return None
        # Ensure template collection is initialized via manager
        return self.world_state_manager.template_collection.find_template(
            group_uid, template_uid
        )

    @property
    def agent_persona_names(self) -> dict[str, str]:
        """
        Helper that returns a map of agent_name -> persona template name, if resolved.
        """
        names: dict[str, str] = {}
        try:
            for agent_name in self.agent_persona_templates or {}:
                tpl = None
                try:
                    tpl = self.agent_persona(agent_name)
                except Exception:
                    tpl = None
                if tpl and getattr(tpl, "name", None):
                    names[agent_name] = tpl.name
        except Exception:
            pass

        return names

    @property
    def agent_personas(self) -> dict[str, world_state_templates.AgentPersona]:
        """
        Helper that returns a map of agent_name -> persona template, if resolved.
        """
        personas: dict[str, world_state_templates.AgentPersona] = {}
        for agent_name in self.agent_persona_templates or {}:
            tpl = None
            try:
                tpl = self.agent_persona(agent_name)
            except Exception:
                tpl = None
            if tpl:
                personas[agent_name] = tpl
        return personas

    @property
    def max_backscroll(self):
        return self.config.game.general.max_backscroll

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
    def story_intent(self) -> str:
        return self.intent_state.intent

    @property
    def intent(self) -> dict:
        phase = self.intent_state.phase
        if not phase:
            return {}

        return {
            "name": self.intent_state.current_scene_type.name,
            "intent": phase.intent,
        }

    @property
    def active_node_graph(self):
        return getattr(self, "node_graph", getattr(self, "creative_node_graph", None))

    def set_intro(self, intro: str):
        self.intro = intro

    def set_name(self, name: str):
        self.name = name

    def set_title(self, title: str):
        self.title = title

    def connect(self):
        """
        connect scenes to signals
        """
        self.signals["config.changed"].connect(self.on_config_changed)

    def disconnect(self):
        """
        disconnect scenes from signals
        """
        self.signals["config.changed"].disconnect(self.on_config_changed)

    def __del__(self):
        self.disconnect()

    async def on_config_changed(self, event):
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

    async def push_history(self, messages: list[SceneMessage]):
        """
        Adds one or more messages to the scene history
        """

        if isinstance(messages, SceneMessage):
            messages = [messages]

        # there can only ever be one director message in the history
        # so if there is a new DirectorMessage in messages we remove the old one
        # from the history

        # Filter out empty director messages and collect valid ones
        valid_messages = []

        for message in messages:
            if not message.rev and self._changelog:
                message.rev = self._changelog.next_revision

            if isinstance(message, DirectorMessage):
                # Ignore empty director messages
                if not message.message or not message.message.strip():
                    log.debug(
                        "push_history: ignoring empty DirectorMessage",
                        source=message.source,
                        meta=message.meta,
                    )
                    continue
                for idx in range(len(self.history) - 1, -1, -1):
                    if (
                        isinstance(self.history[idx], DirectorMessage)
                        and self.history[idx].source == message.source
                    ):
                        self.history.pop(idx)
                        break

            elif isinstance(message, TimePassageMessage):
                self.advance_time(message.ts)

            valid_messages.append(message)

        self.history.extend(valid_messages)

        event: events.HistoryEvent = events.HistoryEvent(
            scene=self,
            event_type="push_history",
            messages=valid_messages,
        )

        await self.signals["push_history"].send(event)

        loop = asyncio.get_event_loop()
        for message in valid_messages:
            loop.run_until_complete(
                self.signals["game_loop_new_message"].send(
                    events.GameLoopNewMessageEvent(
                        scene=self, event_type="game_loop_new_message", message=message
                    )
                )
            )

        await self.signals["push_history.after"].send(event)

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
        **filters,
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

    def last_message_by_character(self, character_name: str) -> SceneMessage:
        """
        Returns the last message from the given character
        """
        for idx in range(len(self.history) - 1, -1, -1):
            if isinstance(self.history[idx], CharacterMessage):
                if self.history[idx].character_name == character_name:
                    return self.history[idx]

    def count_character_messages_since_director(
        self,
        character_name: str,
        max_iterations: int = 20,
        stop_on_time_passage: bool = True,
    ) -> int:
        """
        Counts how many messages from the given character have occurred since
        the last director message for that character.

        This is useful for determining if a character has already started acting
        on a director instruction (stickiness scenario).

        Returns 0 if no director message is found within max_iterations.
        """
        count = 0
        for idx in range(len(self.history) - 1, -1, -1):
            if max_iterations is not None and idx < len(self.history) - max_iterations:
                break

            message = self.history[idx]

            if isinstance(message, TimePassageMessage) and stop_on_time_passage:
                break

            if isinstance(message, DirectorMessage):
                if message.character_name == character_name:
                    return count

            if isinstance(message, CharacterMessage):
                if message.character_name == character_name:
                    count += 1

        return 0  # No director message found

    def last_message_of_type(
        self,
        typ: str | list[str],
        source: str = None,
        max_iterations: int = None,
        stop_on_time_passage: bool = False,
        on_iterate: Callable = None,
        count_only_types: list[str] = None,
        **filters,
    ) -> SceneMessage | None:
        """
        Returns the last message of the given type and source

        Arguments:
        - typ: str | list[str] - the type of message to find
        - source: str - the source of the message
        - max_iterations: int - the maximum number of iterations to search for the message
        - stop_on_time_passage: bool - if True, the search will stop when a TimePassageMessage is found
        - on_iterate: Callable - a function to call on each iteration of the search
        - count_only_types: list[str] - only count messages of these types toward max_iterations
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

            # Only count specific message types toward max_iterations if count_only_types is set
            if count_only_types is None or message.typ in count_only_types:
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
            ignore = [
                ReinforcementMessage,
                DirectorMessage,
                ContextInvestigationMessage,
            ]
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
                    raise ValueError(
                        "ignore must be a list of strings or SceneMessage types"
                    )
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

    async def push_archive(self, entry: ArchiveEntry):
        """
        Adds an entry to the archive history.

        The archive history is a list of summarized history entries.
        """

        self.archived_history.append(entry.model_dump(exclude_none=True))
        await emit_archive_add(self, entry)
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
                self.log.info("Message edited", message=message, id=message_id)
                return

    async def add_actor(self, actor: Actor, commit_to_memory: bool = True):
        """
        Add an actor to the scene
        """

        # if actor with character already exists, remove it
        for _actor in list(self.actors):
            if _actor.character == actor.character:
                self.actors.remove(_actor)

        self.actors.append(actor)
        actor.scene = self

        if isinstance(actor, Player):
            actor.character.is_player = True

        if actor.character.name not in self.character_data:
            self.character_data[actor.character.name] = actor.character

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

        memory = get_agent("memory")
        if commit_to_memory:
            await actor.character.commit_to_memory(memory)

    async def remove_character(
        self, character: Character, purge_from_memory: bool = True
    ):
        """
        Remove a character from the scene
        """

        for actor in self.actors:
            if actor.character == character:
                await self.remove_actor(actor)

        if character.name in self.character_data:
            del self.character_data[character.name]

        if character.name in self.active_characters:
            self.active_characters.remove(character.name)

        if purge_from_memory:
            await character.purge_from_memory()

    async def remove_actor(self, actor: Actor):
        """
        Remove an actor from the scene
        """

        for _actor in self.actors:
            if _actor == actor:
                self.actors.remove(_actor)

        actor.character = None

    def character_is_active(self, character: "Character | str") -> bool:
        if isinstance(character, str):
            character = self.get_character(character)

        return character.name in self.character_names

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

    def get_explicit_player_character(self) -> Character | None:
        for actor in self.actors:
            if isinstance(actor, Player):
                return actor.character
        return None

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

    def parse_characters_from_text(
        self, text: str, exclude_active: bool = False
    ) -> list[Character]:
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

    def get_intro(self, intro: str = None) -> str:
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

        editor = get_agent("editor")

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

    def context_history(self, budget: int = 8192, **kwargs):
        parts_context = []
        parts_dialogue = []

        budget_context = int(0.5 * budget)
        budget_dialogue = int(0.5 * budget)

        keep_director = kwargs.get("keep_director", False)
        keep_context_investigation = kwargs.get("keep_context_investigation", True)
        show_hidden = kwargs.get("show_hidden", False)

        conversation_format = self.conversation_format
        actor_direction_mode = get_agent("director").actor_direction_mode
        layered_history_enabled = get_agent("summarizer").layered_history_enabled
        include_reinforcements = kwargs.get("include_reinforcements", True)
        assured_dialogue_num = kwargs.get("assured_dialogue_num", 5)

        chapter_labels = kwargs.get("chapter_labels", False)
        chapter_numbers = []

        history_len = len(self.history)

        # CONTEXT
        # collect context, ignore where end > len(history) - count
        if (
            not self.layered_history
            or not layered_history_enabled
            or not self.layered_history[0]
        ):
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
                    log.error(
                        "context_history", error=e, traceback=traceback.format_exc()
                    )
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
                log.debug(
                    "context_history - layered history",
                    i=i,
                    next_layer_start=next_layer_start,
                )

                if not self.layered_history[i]:
                    continue

                k = next_layer_start if next_layer_start is not None else 0

                for layered_history_entry in self.layered_history[i][
                    next_layer_start if next_layer_start is not None else 0 :
                ]:
                    time_message_start = util.iso8601_diff_to_human(
                        layered_history_entry["ts_start"], self.ts
                    )
                    time_message_end = util.iso8601_diff_to_human(
                        layered_history_entry["ts_end"], self.ts
                    )

                    if time_message_start == time_message_end:
                        time_message = time_message_start
                    else:
                        time_message = (
                            f"Start:{time_message_start}, End:{time_message_end}"
                            if time_message_start != time_message_end
                            else time_message_start
                        )
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
            base_layer_start = (
                self.layered_history[0][-1]["end"] + 1
                if self.layered_history[0]
                else None
            )

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
            while parts_context and count_tokens(parts_context) > budget_context:
                parts_context.pop(0)

        # DIALOGUE
        try:
            summarized_to = (
                self.archived_history[-1]["end"] if self.archived_history else 0
            )
        except KeyError:
            # only static archived history entries exist (pre-entered history
            # that doesnt have start and end timestamps)
            summarized_to = 0

        # if summarized_to somehow is bigger than the length of the history
        # since we have no way to determine where they sync up just put as much of
        # the dialogue as possible
        if summarized_to and summarized_to >= history_len:
            log.warning(
                "context_history",
                message="summarized_to is greater than history length - may want to regenerate history",
            )
            summarized_to = 0

        log.debug(
            "context_history", summarized_to=summarized_to, history_len=history_len
        )

        dialogue_messages_collected = 0

        # for message in self.history[summarized_to if summarized_to is not None else 0:]:
        for i in range(len(self.history) - 1, -1, -1):
            message = self.history[i]

            if (
                i < summarized_to
                and dialogue_messages_collected >= assured_dialogue_num
            ):
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

                elif (
                    isinstance(keep_director, str)
                    and message.character_name != keep_director
                ):
                    continue

            elif (
                isinstance(message, ContextInvestigationMessage)
                and not keep_context_investigation
            ):
                continue

            if count_tokens(parts_dialogue) + count_tokens(message) > budget_dialogue:
                break

            parts_dialogue.insert(
                0, message.as_format(conversation_format, mode=actor_direction_mode)
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

    def _do_emit_status(self, restored: bool = False):
        """Internal method that performs the actual emission"""
        if not self.active:
            return

        player_character = self.get_player_character()
        emit(
            "scene_status",
            self.name,
            status="started",
            data={
                "path": self.full_path,
                "filename": self.filename,
                "project_name": self.project_name,
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
                "explicit_player_character": self.player_character_exists,
                "inactive_characters": list(self.inactive_characters.keys()),
                "context": self.context,
                "assets": self.assets.dict(),
                "characters": [actor.character.model_dump() for actor in self.actors],
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
                "agent_persona_templates": self.agent_persona_templates,
                "visual_style_template": self.visual_style_template,
                "agent_persona_names": self.agent_persona_names,
                "intent": self.intent,
                "story_intent": self.story_intent,
                "id": self.id,
                "rev": self.rev,
                "shared_context": self.shared_context.filename
                if self.shared_context
                else None,
                "game_state_watch_paths": self.game_state_watch_paths,
            },
        )

    async def _debounced_emit_status(self, restored: bool = False):
        """Internal method for debounced emission"""
        await asyncio.sleep(0.025)  # 25ms debounce
        self._emit_status_debounce_task = None
        self._do_emit_status(restored)

        self.log.debug(
            "scene_status",
            scene=self.name,
            scene_time=self.ts,
            human_ts=util.iso8601_duration_to_human(self.ts, suffix="")
            if self.ts
            else None,
            saved=self.saved,
        )

    def emit_status(self, restored: bool = False):
        """Emit scene status with debouncing"""
        loop = asyncio.get_running_loop()

        # Cancel and replace any existing debounce task
        if (
            self._emit_status_debounce_task
            and not self._emit_status_debounce_task.done()
        ):
            self._emit_status_debounce_task.cancel()

        self._emit_status_debounce_task = loop.create_task(
            self._debounced_emit_status(restored)
        )

        log.debug("emit_status", debounce_task=self._emit_status_debounce_task)

    def emit_scene_intent(self):
        """
        Emit the current scene intent state to the UX.

        Uses websocket passthrough so the websocket server doesn't need a
        dedicated handler for this message type.
        """
        if not self.active:
            return

        try:
            self.emit(
                "scene_intent",
                message="",
                data=self.intent_state.model_dump(),
                websocket_passthrough=True,
                kwargs={
                    "action": "updated",
                    "scene_id": self.id,
                    "scene_rev": self.rev,
                },
            )
        except Exception as e:
            # Best-effort; don't break scene flow due to websocket issues.
            self.log.error("emit_scene_intent failed", error=e)

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

        self.log.debug("sync_time", ts=self.ts)

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
        except Exception:
            log.error("fix_time", exc=traceback.format_exc())
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
        memory = get_agent("memory")
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
        intro: str = self.get_intro()
        self.narrator_message(intro)

        # emit history
        for message in self.history[-self.max_backscroll :]:
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
                log.debug(f"Starting scene loop: {self.environment}")

                self.world_state.emit()
                async with InMemoryChangelog(self) as changelog:
                    self._changelog = changelog
                    if self.environment == "creative":
                        self.creative_node_graph, _ = load_graph(
                            self.creative_nodes_filename, [self.save_dir]
                        )
                        await initialize_packages(self, self.creative_node_graph)
                        await self._run_creative_loop(init=first_loop)
                    else:
                        self.node_graph, _ = load_graph(
                            self.nodes_filename, [self.save_dir]
                        )
                        await initialize_packages(self, self.node_graph)
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
        self.commands = commands.Manager(self)

        await self.signals["scene_init"].send(
            events.SceneStateEvent(scene=self, event_type="scene_init")
        )

    async def _run_game_loop(self, init: bool = True, node_graph=None):
        if init:
            await self._game_startup()
            await self.emit_history()

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

    async def attempt_auto_save(self):
        """
        Attempts to auto save the scene if auto save is enabled.
        If auto save is not enabled, it will set saved to False and emit the status.
        """
        if self.auto_save:
            await self.save(auto=True)
        else:
            self.saved = False
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

        if self.immutable_save and not save_as and not force:
            save_as = True

        if copy_name:
            save_as = True

        if save_as:
            self.filename = copy_name

        if not self.name and not auto:
            raise TalemateError("Scene has no name, cannot save")

        elif not self.filename and not auto:
            self.filename = str(uuid.uuid4())[:10]
            self.filename = self.filename.replace(" ", "-").lower() + ".json"

        if self.filename and not self.filename.endswith(".json"):
            self.filename = f"{self.filename}.json"

        elif not self.filename or not self.name and auto:
            # scene has never been saved, don't auto save
            return

        if save_as:
            self.immutable_save = False
            memory_agent = get_agent("memory")
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

        # update changelog
        if self._changelog:
            await self._changelog.append_delta()
            if self.shared_context:
                await self.shared_context.commit_changes(self)
            await self._changelog.commit()

    async def save_restore(self, filename: str):
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
        config = get_config()
        config.recent_scenes.push(self)
        await config.set_dirty()

    async def commit_to_memory(self):
        # will recommit scene to long term memory

        memory = get_agent("memory")
        memory.drop_db()
        await memory.set_db()

        archive_entries = []

        for ah in self.archived_history:
            ts = ah.get("ts", "PT1S")

            if not ah.get("ts"):
                ah["ts"] = ts

            if not ah.get("text"):
                continue

            entry = ArchiveEntry(**ah)

            # await emit_archive_add(self, entry)
            archive_entries.append(
                {
                    "id": entry.id,
                    "text": entry.text,
                    "meta": {
                        "ts": entry.ts,
                        "typ": "history",
                    },
                }
            )

        if archive_entries:
            await memory.add_many(archive_entries)

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
        memory_agent = get_agent("memory")
        memory_agent.close_db(self)
        self.memory_id = str(uuid.uuid4())[:10]
        await self.commit_to_memory()

        self.set_new_memory_session_id()

    async def restore(
        self,
        save_as: str | None = None,
        from_rev: int | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ):
        try:
            self.log.info(
                "Restoring",
                source=self.restore_from,
                from_rev=from_rev,
                from_date=from_date,
                to_date=to_date,
            )

            restore_from = self.restore_from

            if not self.restore_from:
                self.log.error("No save file specified to restore from.")
                return

            self.reset()
            self.active_characters = []
            await self.remove_all_actors()

            from talemate.load import load_scene

            # If a changelog rev/date-range is provided, reconstruct first
            if from_rev is not None or from_date is not None or to_date is not None:
                from talemate.changelog import reconstruct_scene_data

                target_rev = from_rev
                # For now, date range selection is not implemented; default to latest if not provided
                reconstructed = await reconstruct_scene_data(self, to_rev=target_rev)
                temp_name = f"{os.path.splitext(self.filename or 'scene.json')[0]}-restored.json"
                temp_path = os.path.join(self.save_dir, temp_name)
                with open(temp_path, "w") as f:
                    json.dump(reconstructed, f, indent=2, cls=save.SceneEncoder)
                await load_scene(
                    self,
                    temp_path,
                    get_agent("conversation").client,
                )
            else:
                await load_scene(
                    self,
                    os.path.join(self.save_dir, self.restore_from),
                    get_agent("conversation").client,
                )
                if not self.restore_from:
                    self.restore_from = restore_from

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
            "id": scene.id,
            "description": scene.description,
            "intro": scene.intro,
            "name": scene.name,
            "project_name": scene.project_name,
            "title": scene.title,
            "history": scene.history,
            "environment": scene.environment,
            "archived_history": scene.archived_history,
            "layered_history": scene.layered_history,
            "character_data": {
                name: character.model_dump()
                for name, character in scene.character_data.items()
            },
            "active_characters": scene.active_characters,
            "context": scene.context,
            "world_state": scene.world_state.model_dump(),
            "game_state": scene.game_state.model_dump(),
            "agent_state": scene.agent_state,
            "intent_state": scene.intent_state.model_dump(),
            "assets": scene.assets.scene_info(),
            "memory_id": scene.memory_id,
            "memory_session_id": scene.memory_session_id,
            "saved_memory_session_id": scene.saved_memory_session_id,
            "immutable_save": scene.immutable_save,
            "ts": scene.ts,
            "help": scene.help,
            "experimental": scene.experimental,
            "writing_style_template": scene.writing_style_template,
            "agent_persona_templates": scene.agent_persona_templates,
            "visual_style_template": scene.visual_style_template,
            "restore_from": scene.restore_from,
            "nodes_filename": scene._nodes_filename,
            "creative_nodes_filename": scene._creative_nodes_filename,
            "shared_context": scene.shared_context.filename
            if scene.shared_context
            else None,
            "game_state_watch_paths": scene.game_state_watch_paths,
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


Character.model_rebuild()
CharacterContextItem.model_rebuild()
CharacterContext.model_rebuild()
