import asyncio
import json
import structlog
import os
import random
import traceback
import re
import isodate
from typing import Dict, List, Optional, Union

from blinker import signal

import talemate.agents as agents
import talemate.client as client
import talemate.commands as commands
import talemate.data_objects as data_objects
import talemate.events as events
import talemate.util as util
import talemate.save as save
from talemate.emit import Emitter, emit, wait_for_input
from talemate.util import colored_text, count_tokens, extract_metadata, wrap_text
from talemate.scene_message import SceneMessage, CharacterMessage, DirectorMessage, NarratorMessage, TimePassageMessage
from talemate.exceptions import ExitScene, RestartSceneLoop, ResetScene, TalemateError, TalemateInterrupt, LLMAccuracyError
from talemate.world_state import WorldState
from talemate.config import SceneConfig
from talemate.scene_assets import SceneAssets
from talemate.client.context import ClientContext, ConversationContext
import talemate.automated_action as automated_action


__all__ = [
    "Character",
    "TestCharacter",
    "Actor",
    "Scene",
    "Helper",
    "Player",
]


log = structlog.get_logger("talemate")


class Character:
    """
    A character for the AI to roleplay, with a name, description, and greeting text.
    """

    def __init__(
        self,
        name: str,
        description: str,
        greeting_text: str,
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

    @property
    def pronoun(self):
        if self.gender.lower() == "female":
            return "her"
        elif self.gender.lower() == "male":
            return "his"
        elif self.gender.lower() == "neutral":
            return "their"
        else:
            return "its"

    @property
    def pronoun_2(self):
        if self.gender.lower() == "female":
            return "she"
        if self.gender.lower() == "male":
            return "he"
        if self.gender.lower() == "neutral":
            return "they"
        else:
            return "it"

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
        }

    @property
    def sheet(self):
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

    def save(self, file_path: str):
        """
        Save this Character instance properties to a json file at the given file path.

        Args:
        file_path (str): The path to the output json file.

        Returns:
        None
        """

        with open(file_path, "w") as output_file:
            json.dump(self.serialize, output_file, indent=2)

    @classmethod
    def load(cls, file_path: str) -> "Character":
        """
        Load a Character instance properties from a json file at the given file path.

        Args:
        file_path (str): The path to the input json file.

        Returns:
        Character: The loaded Character instance.
        """

        with open(file_path, "r") as input_file:
            character_dict = json.load(input_file)

        character = cls(
            name=character_dict["name"],
            description=character_dict["description"],
            greeting_text=character_dict["greeting_text"],
            gender=character_dict["gender"],
            color=character_dict["color"],
        )

        character.example_dialogue = character_dict["example_dialogue"]

        return character

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
        if self.description:
            self.description = self.description.replace(f"{orig_name}", self.name)
        for k, v in self.base_attributes.items():
            self.base_attributes[k] = v.replace(f"{orig_name}", self.name)
        for i, v in enumerate(self.details):
            self.details[i] = v.replace(f"{orig_name}", self.name)

    def load_from_image_metadata(self, image_path: str, file_format: str):
        """
        Load character data from an image file's metadata using the extract_metadata function.

        Args:
        image_path (str): The path to the image file.
        file_format (str): The image file format ('png' or 'webp').

        Returns:
        None
        """

        metadata = extract_metadata(image_path, file_format)

        # check if v2 card spec
        
        if metadata.get("spec") == "chara_card_v2":
            metadata = metadata["data"]

        self.color = "red"
        if "name" in metadata:
            self.name = metadata["name"]

        # loop through the metadata and set the character name everywhere {{char}}
        # occurs

        for key in metadata:
            if isinstance(metadata[key], str):
                metadata[key] = metadata[key].replace("{{char}}", self.name)

        if "description" in metadata:
            self.description = metadata["description"]
        if "scenario" in metadata:
            self.description += "\n" + metadata["scenario"]
        if "first_mes" in metadata:
            self.greeting_text = metadata["first_mes"]
        if "gender" in metadata:
            self.gender = metadata["gender"]
        if "color" in metadata:
            self.color = metadata["color"]
        if "mes_example" in metadata:
            for message in metadata["mes_example"].split("<START>"):
                if message.strip("\r\n"):
                    self.example_dialogue.extend(
                        [m for m in message.split("\r\n") if m]
                    )


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
                log.error("introduce_main_character", error=e, traceback=traceback.format_exc())
                updated_prop_value = prop_value
            setattr(self, prop, updated_prop_value)

        # also replace in all example dialogue

        for i, dialogue in enumerate(self.example_dialogue):
            self.example_dialogue[i] = pattern.sub(character.name, dialogue)

    async def commit_to_memory(self, memory_agent):
        """
        Commits this character's details to the memory agent. (vectordb)
        """
        
        items = []

        if not self.base_attributes or "description" not in self.base_attributes:
            
            if not self.description:
                self.description = ""
            description_chunks = [chunk.strip() for chunk in self.description.split("\n") if chunk.strip()]
            
            for idx in range(len(description_chunks)):
                chunk = description_chunks[idx]

                items.append({
                    "text": f"{self.name}: {chunk}",
                    "id": f"{self.name}.description.{idx}",
                    "meta": {
                        "character": self.name,
                        "attr": "description",
                        "typ": "base_attribute",
                    }
                })

        for attr, value in self.base_attributes.items():
            
            if attr.startswith("_"):
                continue
            
            items.append({
                "text": f"{self.name}'s {attr}: {value}",
                "id": f"{self.name}.{attr}",
                "meta": {
                    "character": self.name,
                    "attr": attr,
                    "typ": "base_attribute",
                }
            })
            
        for key, detail in self.details.items():
            items.append({
                "text": f"{self.name} - {key}: {detail}",
                "meta": {
                    "character": self.name,
                    "typ": "details",
                }
            })
            
            #await memory_agent.add(detail, None)

        for history_event in self.history_events:
            if not history_event or not history_event["summary"]:
                continue
            
            items.append({
                "text": history_event["summary"],
                "meta": {
                    "character": self.name,
                    "typ": "history_event",
                }
            })
           
            #await memory_agent.add(history_event["summary"], None)
            
        if items:
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


class TestCharacter(Character):
    """
    A test character with a name, description, and greeting text.
    """

    def __init__(self):
        super().__init__(
            name="Magical Fairy",
            description="A female magical Fairy. About as big as a human hand. She is not very powerful, but she is very mischievous.",
            color="magenta",
            greeting_text="*winking* I am a magical fairy and i am contractually bound to grant you 3 wishes. Tee hee! What is your desire?",
        )

        self.example_dialogue = [
            "*giggling* Oh, dear human, I see you've misplaced your keys again! Would you like a little hint, or should I let you search just a bit longer? Tee-hee!",
            "*fluttering around playfully* Why, hello there! I couldn't help but notice you're feeling a bit glum. How about I cheer you up by turning those frowns into flowers? But be warned, they may tickle!",
            "*twirling her wand* A touch of magic, a sprinkle of mischief, and voilà! You'll find your shoes swapped with your neighbor's. Don't worry, it's all in good fun!",
            "*winking* Shall we play a little game, my human friend? I'll hide three enchanted acorns in your garden, and if you find them all, I'll grant you a single wish. But beware, my hiding spots can be quite tricky!",
            "*fluttering her wings* Oh, what a lovely day for a bit of harmless pranking! How about we turn this plain old rock into a singing stone? Your friends won't know what hit them when it starts belting out tunes!",
        ]


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

    async def talk(self, editor: Optional[Helper] = None):
        """
        Set the message to be sent to the AI
        """
        
        if self.script:
            return CharacterMessage(self.script.pop(0))
        
        self.agent.character = self.character
        
        conversation_context = ConversationContext(
            talking_character=self.character.name,
            other_characters=[actor.character.name for actor in self.scene.actors if actor != self],
        )
        
        with ClientContext(conversation=conversation_context):
            messages = await self.agent.converse(self, editor=editor)
            
        return messages


class Player(Actor):

    muted = 0
    ai_controlled = 0
    
    async def talk(
        self, message: Union[str, None] = None, editor: Optional[Helper] = None
    ):
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
            
            return await super().talk(editor=editor)
        
        if not message:
            # Display scene history length before the player character name
            history_length = self.scene.history_length()

            name = colored_text(self.character.name + ": ", self.character.color)
            message = await wait_for_input(
                f"[{history_length}] {name}", character=self.character
            )
            

        if not message:
            return

        if not commands.Manager.is_command(message):
            
            self.message = message
            
            self.scene.push_history(
                CharacterMessage(f"{self.character.name}: {message}", source="player")
            )
            emit("character", self.history[-1], character=self.character)
            
        return message
    
    

class Scene(Emitter):
    """
    A scene containing one ore more AI driven actors to interact with.
    """

    ExitScene = ExitScene

    def __init__(self):
        self.actors = []
        self.helpers = []
        self.history = []
        self.archived_history = []
        self.goals = []
        self.character_states = {}
        self.assets = SceneAssets(scene=self)
        self.description = ""
        self.intro  = ""
        self.outline = ""
        self.main_character = None
        self.static_tokens = 0
        self.max_tokens = 2048
        
        self.name = ""
        self.filename = ""
        
        self.context = ""
        self.commands = commands.Manager(self)
        self.environment = "scene"
        self.goal = None
        self.world_state = WorldState()
        self.ts = "PT0S"
        
        self.automated_actions = {}

        self.summary_pins = []
        # Add an attribute to store the most recent AI Actor
        self.most_recent_ai_actor = None

        self.signals = {
            "ai_message": signal("ai_message"),
            "player_message": signal("player_message"),
            "history_add": signal("history_add"),
            "archive_add": signal("archive_add"),
            "character_state": signal("character_state"),
        }

        self.setup_emitter(scene=self)
        
        self.world_state.emit()

    @property
    def characters(self):
        for actor in self.actors:
            yield actor.character

    @property
    def log(self):
        return log
    
    @property
    def scene_config(self):
        return SceneConfig(
            automated_actions={action.uid: action.enabled for action in self.automated_actions.values()}
        ).dict()
        
    @property
    def project_name(self):
        return self.name.replace(" ", "-").replace("'","").lower()
        
    def apply_scene_config(self, scene_config:dict):
        scene_config = SceneConfig(**scene_config)
        
        for action, enabled in scene_config.automated_actions.items():
            self.toggle_automated_action(action, enabled)

    async def call_automated_actions(self):
        for action in self.automated_actions.values():
            await action()
            
    def toggle_automated_action(self, action_uid:str, enabled:bool):
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

    def set_character_state(self, character_name: str, state: str):
        self.character_states[character_name] = state
        self.signals["character_state"].send(
            events.CharacterStateEvent(
                scene=self,
                event_type="character_state",
                state=state,
                character_name=character_name,
            )
        )

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
                    if isinstance(self.history[idx], DirectorMessage):
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
        emit("archived_history", data={
            "history":[archived_history["text"] for archived_history in self.archived_history]
        })

    def edit_message(self, message_id:int, message:str):
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
            
            if not self.context and actor.character.base_attributes.get("scenario_context"):
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
                
    def num_npc_characters(self):
        return len(list(self.get_npc_characters()))

    def get_characters(self):
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
        
    def get_intro(self):
        """
        Returns the intro text of the scene
        """
        try:
            player_name=self.get_player_character().name
            return self.intro.replace("{{user}}", player_name).replace("{{char}}", player_name)
        except AttributeError:
            return self.intro

    def history_length(self):
        """
        Calculate and return the length of all strings in the history added together.
        """
        return count_tokens(self.history)
    
    async def summarized_dialogue_history(
        self,
        budget: int = 1024,
        min_dialogue: int = 50,
        keep_director:bool=False,
        add_archieved_history:bool = False,
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
        self, 
        budget: int = 1024,
        min_dialogue: int = 10,
        keep_director:bool=False,
        insert_bot_token:int = None,
        add_archieved_history:bool = True,
        dialogue_negative_offset:int = 0,
        sections=True,
        max_dialogue: int = None,
        **kwargs
    ):
        """
        Return a list of messages from the history that are within the budget.
        """

        # we check if there is archived history
        # we take the last entry and find the end index
        # we then take the history from the end index to the end of the history

        if self.archived_history:
            end = self.archived_history[-1].get("end", 0)
        else:
            end = 0

        history_length = len(self.history)

        # we then take the history from the end index to the end of the history

        if history_length - end < min_dialogue:
            end = max(0, history_length - min_dialogue)
            
        if not dialogue_negative_offset:
            dialogue = self.history[end:]
        else:
            dialogue = self.history[end:-dialogue_negative_offset]

        if not keep_director:
            dialogue = [line for line in dialogue if not isinstance(line, DirectorMessage)]
            
        if max_dialogue:
            dialogue = dialogue[-max_dialogue:]

        if dialogue and insert_bot_token is not None:
            dialogue.insert(-insert_bot_token, "<|BOT|>")

        if dialogue:
            context_history = ["<|SECTION:DIALOGUE|>","\n".join(map(str, dialogue)), "<|CLOSE_SECTION|>"]
        else:
            context_history = []
            
        if not sections and context_history:
            context_history = [context_history[1]]

        # if we dont have lots of archived history, we can also include the scene
        # description at tbe beginning of the context history

        archive_insert_idx = 0
        
        # iterate backwards through archived history and count how many entries
        # there are that have an end index
        num_archived_entries = 0
        if add_archieved_history:
            for i in range(len(self.archived_history) - 1, -1, -1):
                if self.archived_history[i].get("end") is None:
                    break
                num_archived_entries += 1

        if num_archived_entries <= 2 and add_archieved_history:
            

            for character in self.characters:
                if character.greeting_text and character.greeting_text != self.get_intro():
                    context_history.insert(0, character.greeting_text)
                    archive_insert_idx += 1

            context_history.insert(0, "")
            context_history.insert(0, self.get_intro())
            archive_insert_idx += 2

        # see how many tokens are in the dialogue

        used_budget = count_tokens(context_history)

        history_budget = budget - used_budget

        if history_budget <= 0:
            return context_history

        # we then iterate through the archived history from the end to the beginning
        # until we reach the budget

        i = len(self.archived_history) - 1
        limit = 5
        
        
        if sections:
            context_history.insert(archive_insert_idx, "<|CLOSE_SECTION|>")
        
        while i >= 0 and limit > 0 and add_archieved_history:
            
            # we skip predefined history, that should be joined in through
            # long term memory queries
            
            if self.archived_history[i].get("end") is None:
                break
            
            text = self.archived_history[i]["text"]
            if count_tokens(context_history) + count_tokens(text) > budget:
                break
            context_history.insert(archive_insert_idx, text)
            i -= 1
            limit -= 1

        if sections:
            context_history.insert(0, "<|SECTION:HISTORY|>")

        return context_history

    async def rerun(self, editor: Optional[Helper] = None):
        """
        Rerun the most recent AI response, remove their previous message from the history,
        and call talk() for the most recent AI Character.
        """
        # Remove AI's last response and player's last message from the history
        
        try:
            message = self.history[-1]
        except IndexError:
            return
        
        log.debug(f"Rerunning message: {message} [{message.id}]")
        
        if message.source == "player":
            return
        
        if isinstance(message, CharacterMessage):
            self.history.pop()
            await self._rerun_character_message(message, editor=editor)
        elif isinstance(message, NarratorMessage):
            self.history.pop()
            await self._rerun_narrator_message(message)
        elif isinstance(message, DirectorMessage):
            self.history.pop()
            await self._rerun_director_message(message)
        else:
            return
            
        
    async def _rerun_narrator_message(self, message):
        
        emit("remove_message", "", id=message.id)
        source, arg = message.source.split(":") if message.source and ":" in message.source else (message.source, None)
        
        log.debug(f"Rerunning narrator message: {source} [{message.id}]")
        
        
        narrator = self.get_helper("narrator")
        if source == "progress_story":
            new_message = await narrator.agent.progress_story()
        elif source == "narrate_scene":
            new_message = await narrator.agent.narrate_scene()
        elif source == "narrate_character" and arg:
            character = self.get_character(arg)
            new_message = await narrator.agent.narrate_character(character)
        elif source == "narrate_query":
            new_message = await narrator.agent.narrate_query(arg)
        else:
            return
        
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
        
        response = await director.agent.direct(character)

        if not response:
            log.info("Director returned no response")
            return
        
        if response is True:
            log.info("Director returned True")
            return        

        new_message = DirectorMessage(response, source=source)
        self.push_history(new_message)
        emit("director", new_message, character=character) 
        
    async def _rerun_character_message(self, message, editor=None):

        character_name = message.split(":")[0]

        character = self.get_character(character_name)

        if character.is_player:
            emit("system", "Cannot rerun player's message")
            return

        emit("remove_message", "", id=message.id)

        # Call talk() for the most recent AI Actor with the same editor parameter
        new_messages = await self.most_recent_ai_actor.talk(editor=editor)

        # Print the new messages
        for item in new_messages:
            character = self.most_recent_ai_actor.agent.character

            emit("character", item, character=character)

        await asyncio.sleep(0)

        return new_messages
    

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

    def emit_status(self):
       emit(
            "scene_status",
            self.name,
            status="started",
            data={
                "environment": self.environment,
                "scene_config": self.scene_config,
                "assets": self.assets.dict(),
                "characters": [actor.character.serialize for actor in self.actors],
                "scene_time": util.iso8601_duration_to_human(self.ts, suffix="") if self.ts else None,
            },
        )    

    def set_environment(self, environment: str):
        """
        Set the environment of the scene
        """
        self.environment = environment
        self.emit_status()
        
    def advance_time(self, ts: str):
        """
        Accepts an iso6801 duration string and advances the scene's world state by that amount
        """
        
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
        
        for message in self.history:
            if isinstance(message, TimePassageMessage):
                self.advance_time(message.ts)
                
        
        self.log.info("sync_time", ts=self.ts)
        
        # TODO: need to adjust archived_history ts as well
        # but removal also probably means the history needs to be regenerated
        # anyway.
    
    def calc_time(self, start_idx:int=0, end_idx:int=None):
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
    
    async def start(self):
        """
        Start the scene
        """
        automated_action.initialize_for_scene(self)
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


    async def _run_game_loop(self, init: bool = True):


        if init:
            emit("clear_screen", "")
            self.narrator_message(self.get_intro())

            for actor in self.actors:
                if (
                    not isinstance(actor, Player)
                    and actor.character.introduce_main_character
                ):
                    actor.character.introduce_main_character(self.main_character.character)

                if actor.character.greeting_text and actor.character.greeting_text != self.get_intro():
                    item = f"{actor.character.name}: {actor.character.greeting_text}"
                    emit("character", item, character=actor.character)

        continue_scene = True
        self.commands = command = commands.Manager(self)

        if init and self.history:
            # history is not empty, so we are continuing a scene
            # need to emit current messages
            for item in self.history:
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
                    
        # sort self.actors by actor.character.is_player, making is_player the first element
        self.actors.sort(key=lambda x: x.character.is_player, reverse=True)
        self.active_actor = None
        while continue_scene:
            
            try:
            
                for actor in self.actors:
                    
                    self.active_actor = actor
                    
                    if not actor.character.is_player:
                        await self.call_automated_actions()
                    
                    message = await actor.talk()
                    
                    if not message:
                        continue

                    if isinstance(actor, Player) and type(message) != list:
                        # Don't append message to the history if it's "rerun"
                        if await command.execute(message):
                            break
                        await self.call_automated_actions()
                        continue

                    # Store the most recent AI Actor
                    self.most_recent_ai_actor = actor

                    for item in message:
                        emit(
                            "character", item, character=actor.character
                        )
            except TalemateInterrupt:
                raise
            except LLMAccuracyError as e:
                self.log.error("game_loop", error=e)
                emit("system", status="error", message=f"LLM Accuracy Error - The model returned an unexpected response, this may mean this specific model is not suitable for Talemate: {e}")
            except TalemateError as e:
                self.log.error("game_loop", error=e)
            except Exception as e:
                self.log.error("game_loop", error=e, unhandled=True, traceback=traceback.format_exc())
                emit("system", status="error", message=f"Unhandled Error: {e}")

        
    async def _run_creative_loop(self, init: bool = True):

        self.system_message("Creative mode")
        if init:
            emit("clear_screen", "")
            self.narrator_message(self.description)

        continue_scene = True
        self.commands = command = commands.Manager(self)

        while continue_scene:
            try:
                message = await wait_for_input("Enter command: ")
                
                if not message:
                    continue
                
                await command.execute(message)
            except TalemateInterrupt:
                raise
            except LLMAccuracyError as e:
                self.log.error("creative_loop", error=e)
                emit("system", status="error", message=f"LLM Accuracy Error - The model returned an unexpected response, this may mean this specific model is not suitable for Talemate: {e}")
            except TalemateError as e:
                self.log.error("creative_loop", error=e)
            except Exception as e:
                self.log.error("creative_loop", error=e, unhandled=True, traceback=traceback.format_exc())
                emit("system", status="error", message=f"Unhandled Error: {e}")

    @property
    def save_dir(self):
        saves_dir = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "..",
            "..",
            "scenes",
            self.project_name,
        )
        
        if not os.path.exists(saves_dir):
            os.makedirs(saves_dir)
        
        return saves_dir
            
    async def save(self):
        """
        Saves the scene data, conversation history, archived history, and characters to a json file.
        """
        scene = self


        if not self.name:
            self.name = await wait_for_input("Enter scenario name: ")
            self.filename = "base.json"

        elif not self.filename:
            self.filename = await wait_for_input("Enter save name: ")
            self.filename = self.filename.replace(" ", "-").lower()+".json"

        saves_dir = self.save_dir
        
        log.info(f"Saving to: {saves_dir}")
        
        # Generate filename with date and normalized character name
        filepath = os.path.join(saves_dir, self.filename)

        # Create a dictionary to store the scene data
        scene_data = {
            "description": scene.description,
            "intro": scene.intro,
            "name": scene.name,
            "history": scene.history,
            "environment": scene.environment,
            "archived_history": scene.archived_history,
            "character_states": scene.character_states,
            "characters": [actor.character.serialize for actor in scene.actors],
            "goal": scene.goal,
            "goals": scene.goals,
            "context": scene.context,
            "world_state": scene.world_state.dict(),
            "assets": scene.assets.dict(),
            "ts": scene.ts,
        }

        emit("system", "Saving scene data to: " + filepath)

        with open(filepath, "w") as f:
            json.dump(scene_data, f, indent=2, cls=save.SceneEncoder)

        await asyncio.sleep(0)

    def reset(self):
        self.history = []
        self.archived_history = []
        self.filename = ""
        self.goal = None
    