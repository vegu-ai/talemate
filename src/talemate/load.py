import json
import os

from dotenv import load_dotenv

import talemate.events as events
from talemate import Actor, Character, Player
from talemate.config import load_config
from talemate.scene_message import (
    SceneMessage, CharacterMessage, NarratorMessage, DirectorMessage, MESSAGES, reset_message_id
)
from talemate.world_state import WorldState
from talemate.game_state import GameState
from talemate.context import SceneIsLoading
from talemate.emit import emit
from talemate.status import set_loading, LoadingStatus
import talemate.instance as instance

import structlog

__all__ = [
    "load_scene",
    "load_conversation_log",
    "load_conversation_log_into_scene",
    "load_character_from_image",
    "load_character_from_json",
    "load_character_into_scene",
]

log = structlog.get_logger("talemate.load")

@set_loading("Loading scene...")
async def load_scene(scene, file_path, conv_client, reset: bool = False):
    """
    Load the scene data from the given file path.
    """

    try:
        with SceneIsLoading(scene):
            if file_path == "environment:creative":
                return await load_scene_from_data(
                    scene, creative_environment(), conv_client, reset=True
                )

            ext = os.path.splitext(file_path)[1].lower()

            if ext in [".jpg", ".png", ".jpeg", ".webp"]:
                return await load_scene_from_character_card(scene, file_path)

            with open(file_path, "r") as f:
                scene_data = json.load(f)

            return await load_scene_from_data(
                scene, scene_data, conv_client, reset, name=file_path
            )
    finally:
        await scene.add_to_recent_scenes()


async def load_scene_from_character_card(scene, file_path):
    """
    Load a character card (tavern etc.) from the given file path.
    """
    
    
    loading_status = LoadingStatus(5)
    loading_status("Loading character card...")

    file_ext = os.path.splitext(file_path)[1].lower()
    image_format = file_ext.lstrip(".")
    image = False
    if not scene.get_player_character():
        await scene.add_actor(default_player_character())
    # If a json file is found, use Character.load_from_json instead
    if file_ext == ".json":
        character = load_character_from_json(file_path)
    else:
        character = load_character_from_image(file_path, image_format)
        image = True

    conversation = scene.get_helper("conversation").agent
    creator = scene.get_helper("creator").agent
    memory = scene.get_helper("memory").agent

    actor = Actor(character, conversation)

    scene.name = character.name
    
    loading_status("Initializing long-term memory...")
    
    await memory.set_db()

    await scene.add_actor(actor)
    
    
    log.debug("load_scene_from_character_card", scene=scene, character=character, content_context=scene.context)
    
    loading_status("Determine character context...")
    
    if not scene.context:
        try:
            scene.context = await creator.determine_content_context_for_character(character)
            log.debug("content_context", content_context=scene.context)
        except Exception as e:
            log.error("determine_content_context_for_character", error=e)
    
    # attempt to convert to base attributes
    try:
        
        loading_status("Determine character attributes...")
        
        _, character.base_attributes = await creator.determine_character_attributes(character)
        # lowercase keys
        character.base_attributes = {k.lower(): v for k, v in character.base_attributes.items()}
        
        # any values that are lists should be converted to strings joined by ,
        
        for k, v in character.base_attributes.items():
            if isinstance(v, list):
                character.base_attributes[k] = ",".join(v)
        
        # transfer description to character
        if character.base_attributes.get("description"):
            character.description = character.base_attributes.pop("description")
                    
        await character.commit_to_memory(scene.get_helper("memory").agent)
            
        log.debug("base_attributes parsed", base_attributes=character.base_attributes)
    except Exception as e:
        log.warning("determine_character_attributes", error=e)
    
    scene.description = character.description
    
    if image:
        scene.assets.set_cover_image_from_file_path(file_path)
        character.cover_image = scene.assets.cover_image
    
    try:
        loading_status("Update world state ...")
        await scene.world_state.request_update(initial_only=True)  
    except Exception as e:
        log.error("world_state.request_update", error=e)

    scene.saved = False

    return scene


async def load_scene_from_data(
    scene, scene_data, conv_client, reset: bool = False, name=None
):
    loading_status = LoadingStatus(1)
    reset_message_id()
    
    memory = scene.get_helper("memory").agent
    
    scene.description = scene_data.get("description", "")
    scene.intro = scene_data.get("intro", "") or scene.description
    scene.name = scene_data.get("name", "Unknown Scene")
    scene.environment = scene_data.get("environment", "scene")
    scene.filename = None
    scene.goals = scene_data.get("goals", [])
    scene.immutable_save = scene_data.get("immutable_save", False)
    
    #reset = True
    
    if not reset:
        
        scene.goal = scene_data.get("goal", 0)
        scene.memory_id = scene_data.get("memory_id", scene.memory_id)
        scene.saved_memory_session_id = scene_data.get("saved_memory_session_id", None)
        scene.memory_session_id = scene_data.get("memory_session_id", None)
        scene.history = _load_history(scene_data["history"])
        scene.archived_history = scene_data["archived_history"]
        scene.character_states = scene_data.get("character_states", {})
        scene.world_state = WorldState(**scene_data.get("world_state", {}))
        scene.game_state = GameState(**scene_data.get("game_state", {}))
        scene.context = scene_data.get("context", "")
        scene.filename = os.path.basename(
            name or scene.name.lower().replace(" ", "_") + ".json"
        )
        scene.assets.cover_image = scene_data.get("assets", {}).get("cover_image", None)
        scene.assets.load_assets(scene_data.get("assets", {}).get("assets", {}))
        
        scene.sync_time()
        log.debug("scene time", ts=scene.ts)
    
    loading_status("Initializing long-term memory...")
    
    await memory.set_db()
    await memory.remove_unsaved_memory()
    
    await scene.world_state_manager.remove_all_empty_pins()
    
    if not scene.memory_session_id:
        scene.set_new_memory_session_id()
        
    for ah in scene.archived_history:
        if reset:
            break
        ts = ah.get("ts", "PT1S")
            
        if not ah.get("ts"):
            ah["ts"] = ts
        
        scene.signals["archive_add"].send(
            events.ArchiveEvent(scene=scene, event_type="archive_add", text=ah["text"], ts=ts)
        )

    for character_name, character_data in scene_data.get("inactive_characters", {}).items():
        scene.inactive_characters[character_name] = Character(**character_data)

    for character_name, cs in scene.character_states.items():
        scene.set_character_state(character_name, cs)

    for character_data in scene_data["characters"]:
        character = Character(**character_data)
        
        if character.name in scene.inactive_characters:
            scene.inactive_characters.pop(character.name)
        
        if not character.is_player:
            agent = instance.get_agent("conversation", client=conv_client)
            actor = Actor(character, agent)
        else:
            actor = Player(character, None)
        # Add the TestCharacter actor to the scene
        await scene.add_actor(actor)
            
    # the scene has been saved before (since we just loaded it), so we set the saved flag to True
    # as long as the scene has a memory_id.
    scene.saved = "memory_id" in scene_data

    return scene

async def load_character_into_scene(scene, scene_json_path, character_name):
    """
    Load a character from a scene json file and add it to the current scene.
    :param scene: The current scene.
    :param scene_json_path: Path to the scene json file.
    :param character_name: The name of the character to load.
    :return: The updated scene with the new character.
    """
    # Load the json file
    with open(scene_json_path, "r") as f:
        scene_data = json.load(f)
        
        
    agent = scene.get_helper("conversation").agent
        
    # Find the character in the characters list
    for character_data in scene_data["characters"]:
        if character_data["name"] == character_name:
            # Create a Character object from the character data
            character = Character(**character_data)

            # If the character is not a player, create a conversation agent for it
            if not character.is_player:
                actor = Actor(character, agent)
            else:
                actor = Player(character, None)

            # Add the character actor to the current scene
            await scene.add_actor(actor)
            break
    else:
        raise ValueError(f"Character '{character_name}' not found in the scene file '{scene_json_path}'")

    return scene


def load_conversation_log(file_path):
    """
    Load the conversation log from the given file path.
    :param file_path: Path to the conversation log file.
    :return: None
    """
    with open(file_path, "r") as f:
        conversation_log = json.load(f)

    for item in conversation_log:
        log.info(item)


def load_conversation_log_into_scene(file_path, scene):
    """
    Load the conversation log from the given file path into the given scene.
    :param file_path: Path to the conversation log file.
    :param scene: Scene to load the conversation log into.
    """
    with open(file_path, "r") as f:
        conversation_log = json.load(f)

    scene.history = conversation_log


def load_character_from_image(image_path: str, file_format: str) -> Character:
    """
    Load a character from the image file's metadata and return it.
    :param image_path: Path to the image file.
    :param file_format: Image file format ('png' or 'webp').
    :return: Character loaded from the image metadata.
    """
    character = Character("", "", "")
    character.load_from_image_metadata(image_path, file_format)
    return character


# New function to load a character from a json file
def load_character_from_json(json_path: str) -> Character:
    """
    Load a character from a json file and return it.
    :param json_path: Path to the json file.
    :return: Character loaded from the json file.
    """
    return Character.load(json_path)


def default_player_character():
    """
    Return a default player character.
    :return: Default player character.
    """
    default_player_character = (
        load_config().get("game", {}).get("default_player_character", {})
    )
    name = default_player_character.get("name")
    color = default_player_character.get("color", "cyan")
    description = default_player_character.get("description", "")

    return Player(
        Character(
            name,
            description=description,
            greeting_text="",
            color=color,
        ),
        None,
    )


def _load_history(history):
    
    _history = []
    
    for text in history:
        
        if isinstance(text, str):
            _history.append(_prepare_legacy_history(text))
            
        elif isinstance(text, dict):
            _history.append(_prepare_history(text))
        
    return _history

def _prepare_history(entry):
    typ = entry.pop("typ", "scene_message")
    entry.pop("id", None)
    
    if entry.get("source") == "":
        entry.pop("source")
    
    cls = MESSAGES.get(typ, SceneMessage)
    
    return cls(**entry)
    

def _prepare_legacy_history(entry):
    
    """
    Convers legacy history to new format
    
    Legacy: list<str>
    New: list<SceneMessage>
    """
    
    if entry.startswith("*"):
        cls = NarratorMessage
    elif entry.startswith("Director instructs"):
        cls = DirectorMessage
    else:
        cls = CharacterMessage
        
    return cls(entry)
    

def creative_environment():
    return {
        "description": "",
        "name": "New scenario",
        "environment": "creative",
        "history": [],
        "archived_history": [],
        "character_states": {},
        "characters": [
        ],
    }
