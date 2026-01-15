import json
import os
import shutil
import tempfile
import uuid
import zipfile
import pydantic
import traceback
from pathlib import Path

import structlog

import talemate.instance as instance
from talemate import Actor, Character, Player, Scene
from talemate.character import deactivate_character, activate_character
from talemate.config import get_config, Config
from talemate.config.schema import GamePlayerCharacter
from talemate.context import SceneIsLoading
from talemate.game.state import GameState
from talemate.scene_message import (
    MESSAGES,
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
    SceneMessage,
    reset_message_id,
)
from talemate.status import LoadingStatus, set_loading
from talemate.world_state import WorldState
from talemate.game.engine.nodes.registry import import_scene_node_definitions
from talemate.scene.intent import SceneIntent
from talemate.history import validate_history
import talemate.agents.tts.voice_library as voice_library
from talemate.path import SCENES_DIR
from talemate.changelog import _get_overall_latest_revision
from talemate.shared_context import SharedContext
from talemate.load.character_card import CharacterCardImportOptions
from talemate.scene_assets import AssetTransfer

# Import character card functions
from talemate.load.character_card import (
    ImportSpec,
    identify_import_spec,
    load_scene_from_character_card,
    load_character_from_image,
    load_character_from_json,
)

__all__ = [
    "load_scene",
    "load_scene_from_zip",
    "load_character_from_image",
    "load_character_from_json",
    "transfer_character",
    "scene_stub",
    "ImportSpec",
    "identify_import_spec",
    "load_scene_from_character_card",
]

log = structlog.get_logger("talemate.load")


class SceneInitialization(pydantic.BaseModel):
    project_name: str | None = None
    content_classification: str | None = None
    agent_persona_templates: dict[str, str | None] | None = None
    writing_style_template: str | None = None
    shared_context: str | None = None
    active_characters: list[str] | None = None
    character_data: dict | None = None
    intro_instructions: str | None = None
    intro: str | None = None
    assets: dict | None = None
    intent_state: SceneIntent | None = None
    character_card_import_options: CharacterCardImportOptions | None = None

    @pydantic.computed_field(description="Content classification")
    @property
    def context(self) -> str | None:
        return self.content_classification


async def _initialize_scene_intro(scene: Scene, scene_data: dict, empty: bool):
    """
    Initialize scene intro and title for new scenes.

    Sets intro from scene_data if provided, otherwise generates from instructions.
    Also generates a title if the scene is empty, doesn't have one, and has content
    (intro or intro_instructions), indicating it's not a blank scene.
    """
    try:
        if empty:
            has_intro_content = False

            if scene_data.get("intro"):
                # Use provided intro directly
                scene.intro = scene_data.get("intro")
                has_intro_content = True
            elif scene_data.get("intro_instructions"):
                # Generate intro from instructions
                creator = instance.get_agent("creator")
                intro_text = await creator.contextual_generate_from_args(
                    context="scene intro:scene intro",
                    instructions=scene_data.get("intro_instructions", ""),
                    length=312,
                    uid="load.new_scene_intro",
                )
                scene.intro = intro_text
                has_intro_content = True

            # Only generate title if there's actual content (not a blank scene)
            if empty and not scene.title and has_intro_content:
                creator = instance.get_agent("creator")
                title = await creator.generate_scene_title()
                scene.title = title
    except Exception as e:
        log.error("generate intro during load", error=e)


def scene_stub(scene_path: str, scene_data: dict | None = None) -> Scene:
    """
    Create a minimal Scene object stub from a scene file path.

    This is useful for accessing scene assets without fully loading the scene.
    The scene's save_dir will point to the correct directory, allowing assets
    to be loaded from library.json.

    Args:
        scene_path: Path to the scene JSON file
        scene_data: Optional scene data dict (if not provided, will be loaded from file)

    Returns:
        A Scene object with filename, name, and project_name set
    """
    if scene_data is None:
        with open(scene_path, "r") as f:
            scene_data = json.load(f)

    scene_dir = os.path.dirname(scene_path)
    project_name = os.path.basename(scene_dir)

    scene = Scene()
    scene.filename = os.path.basename(scene_path)
    scene.name = scene_data.get("name")
    scene.project_name = project_name

    return scene


@set_loading("Loading scene...")
async def load_scene(
    scene: Scene,
    file_path: str,
    reset: bool = False,
    add_to_recent: bool = True,
    scene_initialization: SceneInitialization | None = None,
):
    """
    Load the scene data from the given file path.
    """

    exc = None
    try:
        with SceneIsLoading(scene):
            if file_path == "$NEW_SCENE$":
                if scene_initialization:
                    scene_data = new_scene(scene_initialization)
                else:
                    scene_data = new_scene()

                return await load_scene_from_data(
                    scene, scene_data, reset=True, empty=True
                )

            ext = os.path.splitext(file_path)[1].lower()

            # Character card import options from scene_initialization
            if (
                scene_initialization
                and scene_initialization.character_card_import_options
            ):
                import_options = scene_initialization.character_card_import_options
            else:
                import_options = CharacterCardImportOptions()

            # an image was uploaded, we don't have the scene data yet
            # go directly to loading a character card
            if ext in [".jpg", ".png", ".jpeg", ".webp"]:
                return await load_scene_from_character_card(
                    scene,
                    file_path,
                    import_options=import_options,
                )

            # a zip file was uploaded, extract and load complete scene
            if ext == ".zip":
                return await load_scene_from_zip(scene, file_path, reset)

            # a json file was uploaded, load the scene data
            with open(file_path, "r") as f:
                scene_data = json.load(f)

            # check if the data is a character card
            # this will also raise an exception if the data is not recognized
            spec = identify_import_spec(scene_data)

            # if it is a character card, load it
            if spec in [
                ImportSpec.chara_card_v1,
                ImportSpec.chara_card_v2,
                ImportSpec.chara_card_v3,
            ]:
                return await load_scene_from_character_card(
                    scene,
                    file_path,
                    import_options=import_options,
                )

            # if it is a talemate scene, load it
            return await load_scene_from_data(scene, scene_data, reset, name=file_path)
    except Exception as e:
        exc = e
        log.error("load_scene", error=traceback.format_exc())
        raise e
    finally:
        if add_to_recent and not exc:
            await scene.add_to_recent_scenes()
        if not exc:
            await scene.commit_to_memory()


async def load_scene_from_data(
    scene,
    scene_data,
    reset: bool = False,
    name: str | None = None,
    empty: bool = False,
) -> Scene:
    loading_status = LoadingStatus(1)
    reset_message_id()
    config: Config = get_config()

    memory = instance.get_agent("memory")

    migrate_character_data(scene_data)

    scene.description = scene_data.get("description", "")
    scene.intro = scene_data.get("intro", "") or scene.description
    scene.name = scene_data.get("name", "Unknown Scene")
    scene.environment = scene_data.get("environment", "scene")
    scene.filename = None
    scene.immutable_save = scene_data.get("immutable_save", False)
    scene.experimental = scene_data.get("experimental", False)
    scene.help = scene_data.get("help", "")
    scene.restore_from = scene_data.get("restore_from", "")
    scene.title = scene_data.get("title", "")
    scene.writing_style_template = scene_data.get("writing_style_template", "")
    scene.agent_persona_templates = scene_data.get("agent_persona_templates", {})
    scene.visual_style_template = scene_data.get("visual_style_template", "")
    scene.nodes_filename = scene_data.get("nodes_filename", "")
    scene.creative_nodes_filename = scene_data.get("creative_nodes_filename", "")
    scene.character_data = {
        name: Character(**character_data)
        for name, character_data in scene_data.get("character_data", {}).items()
    }
    scene.active_characters = scene_data.get("active_characters", [])
    scene.context = scene_data.get("context", "")
    scene.project_name = scene_data.get("project_name")
    scene.intent_state = SceneIntent(**scene_data.get("intent_state", {}))
    scene.history = _load_history(scene_data["history"])
    scene.archived_history = scene_data["archived_history"]
    scene.layered_history = scene_data.get("layered_history", [])

    # load shared context
    shared_context_file = scene_data.get("shared_context", "")
    if shared_context_file:
        log.info(
            "Loading shared context from file", shared_context_file=shared_context_file
        )
        path = Path(scene.shared_context_dir) / shared_context_file
        if not path.exists():
            log.warning(
                "Shared context file not found", shared_context_file=shared_context_file
            )
            scene.shared_context = None
        else:
            scene.shared_context = SharedContext(filepath=path)
            await scene.shared_context.init_from_file()
            await scene.shared_context.update_to_scene(scene)
    else:
        scene.shared_context = None

    import_scene_node_definitions(scene)

    if not reset:
        scene.id = scene_data.get("id", scene.id)
        scene.memory_id = scene_data.get("memory_id", scene.memory_id)
        scene.saved_memory_session_id = scene_data.get("saved_memory_session_id", None)
        scene.memory_session_id = scene_data.get("memory_session_id", None)
        scene.world_state = WorldState(**scene_data.get("world_state", {}))
        scene.game_state = GameState(**scene_data.get("game_state", {}))
        scene.agent_state = scene_data.get("agent_state", {})
        scene.game_state_watch_paths = scene_data.get("game_state_watch_paths", [])
        scene.filename = os.path.basename(
            name or scene.name.lower().replace(" ", "_") + ".json"
        )
        scene.fix_time()
        log.debug("scene time", ts=scene.ts)
    else:
        scene.history = []
        scene.archived_history = []
        scene.layered_history = []
        scene.intent_state.reset()

    scene.assets.cover_image = scene_data.get("assets", {}).get("cover_image", None)
    scene.assets.load_assets(scene_data.get("assets", {}).get("assets", {}))

    # Clean up cover images and message avatars that reference non-existent assets
    scene.assets.cleanup_cover_images()
    scene.assets.cleanup_message_avatars()

    loading_status("Initializing long-term memory...")

    await memory.set_db()
    # await memory.remove_unsaved_memory()

    await scene.world_state_manager.remove_all_empty_pins()

    if not scene.memory_session_id:
        scene.set_new_memory_session_id()

    if not reset:
        await validate_history(scene, commit_to_memory=False)

    # Activate active characters
    # Only activate characters that exist in character_data
    for character_name in scene_data["active_characters"]:
        if character_name not in scene.character_data:
            log.warning(
                "Character not found in character_data, skipping activation",
                character_name=character_name,
                available_characters=list(scene.character_data.keys()),
            )
            continue

        character = scene.character_data[character_name]

        if not character.is_player:
            agent = instance.get_agent("conversation")
            actor = Actor(character=character, agent=agent)
        else:
            actor = Player(character=character, agent=None)
        await scene.add_actor(actor, commit_to_memory=False)

    # if there is no player character, add the default player character
    await handle_no_player_character(
        scene,
        add_default_character=config.game.general.add_default_character,
        reset=reset,
    )

    # the scene has been saved before (since we just loaded it), so we set the saved flag to True
    # as long as the scene has a memory_id.
    scene.saved = "memory_id" in scene_data

    # load the scene voice library
    scene.voice_library = await voice_library.load_scene_voice_library(scene)
    log.debug("scene voice library", voice_library=scene.voice_library)

    scene.rev = _get_overall_latest_revision(scene)
    log.debug("Loaded scene", rev=scene.rev)

    # Initialize intro and title for new scenes
    await _initialize_scene_intro(scene, scene_data, empty)

    return scene


@set_loading("Importing scene archive...")
async def load_scene_from_zip(scene, zip_path, reset: bool = False):
    """
    Load a complete scene from a ZIP file containing scene.json and all assets/nodes/info/templates
    """
    log.info("Loading complete scene from ZIP", zip_path=zip_path, reset=reset)

    # Verify ZIP file
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"File is not a valid ZIP archive: {zip_path}")

    # Extract ZIP to temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        log.debug("Extracting ZIP archive", zip_path=zip_path, temp_dir=temp_dir)

        with zipfile.ZipFile(zip_path, "r") as zipf:
            # Check if scene.json exists in ZIP
            if "scene.json" not in zipf.namelist():
                raise ValueError(
                    "ZIP archive does not contain required scene.json file"
                )

            # Extract all files
            zipf.extractall(temp_path)
            log.debug("Extracted ZIP contents", files=len(zipf.namelist()))

        # Load scene.json
        scene_json_path = temp_path / "scene.json"
        with open(scene_json_path, "r", encoding="utf-8") as f:
            scene_data = json.load(f)

        log.debug(
            "Loaded scene JSON from ZIP", scene_name=scene_data.get("name", "Unknown")
        )

        # Generate unique scene name for ZIP imports to avoid conflicts
        # The scene's save_dir is derived from its name, so we set the name
        base_scene_name = scene_data.get("name", "imported-scene")

        # Handle directory name conflicts by adding suffix to the scene name
        scene_name = base_scene_name
        counter = 1

        # Convert scene name to project name format (same as Scene.project_name property)
        def to_project_name(name):
            return name.replace(" ", "-").replace("'", "").lower()

        potential_dir = os.path.join(str(SCENES_DIR), to_project_name(scene_name))

        while os.path.exists(potential_dir):
            scene_name = f"{base_scene_name}-{counter}"
            potential_dir = os.path.join(str(SCENES_DIR), to_project_name(scene_name))
            counter += 1
            if counter > 100:  # Safety limit
                scene_name = f"{base_scene_name}-{uuid.uuid4().hex[:8]}"
                potential_dir = os.path.join(
                    str(SCENES_DIR), to_project_name(scene_name)
                )
                break

        # Set the scene name (which will determine save_dir via the property)
        scene.name = scene_name

        log.debug(
            "Generated unique scene name for ZIP import",
            original_name=base_scene_name,
            final_name=scene_name,
            project_name=to_project_name(scene_name),
            save_dir=scene.save_dir,
        )

        # Create scene save directory (this happens automatically via the save_dir property)
        # but we explicitly access it to trigger directory creation
        actual_save_dir = scene.save_dir  # This triggers directory creation
        log.debug("Scene save directory prepared", save_dir=actual_save_dir)

        # Restore assets if they exist in ZIP
        assets_source = temp_path / "assets"
        if assets_source.exists():
            assets_dest = Path(scene.save_dir) / "assets"
            shutil.copytree(assets_source, assets_dest)
            log.debug("Loaded assets directory", source=assets_source, dest=assets_dest)

        # Restore nodes if they exist in ZIP
        nodes_source = temp_path / "nodes"
        if nodes_source.exists():
            nodes_dest = Path(scene.save_dir) / "nodes"
            shutil.copytree(nodes_source, nodes_dest)
            log.debug("Loaded nodes directory", source=nodes_source, dest=nodes_dest)

        # Restore info if it exists in ZIP
        info_source = temp_path / "info"
        if info_source.exists():
            info_dest = Path(scene.save_dir) / "info"
            shutil.copytree(info_source, info_dest)
            log.debug("Loaded info directory", source=info_source, dest=info_dest)

        # Restore templates if they exist in ZIP
        templates_source = temp_path / "templates"
        if templates_source.exists():
            templates_dest = Path(scene.save_dir) / "templates"
            shutil.copytree(templates_source, templates_dest)
            log.debug(
                "Loaded templates directory",
                source=templates_source,
                dest=templates_dest,
            )

        # Restore restore file if it exists in ZIP and is referenced in scene_data
        restore_filename = scene_data.get("restore_from")
        if restore_filename:
            restore_source = temp_path / restore_filename
            if restore_source.exists():
                restore_dest = Path(scene.save_dir) / restore_filename
                shutil.copy2(restore_source, restore_dest)
                log.debug(
                    "Restored restore file",
                    source=restore_source,
                    dest=restore_dest,
                    filename=restore_filename,
                )
            else:
                log.warning(
                    "Restore file referenced in scene data but not found in ZIP, unsetting restore_from",
                    filename=restore_filename,
                )
                scene.restore_from = None

        # Update scene_data with the conflict-resolved name so saves go to the right directory
        scene_data = scene_data.copy()  # Don't modify the original
        scene_data["name"] = scene.name  # Use the conflict-resolved name

        log.info(
            "Complete scene import finished",
            final_scene_name=scene.name,
            save_dir=scene.save_dir,
        )

        # Load the scene data with the updated name
        # Use the scene name (without .zip extension) for the filename
        zip_basename = os.path.basename(zip_path)
        clean_name = (
            zip_basename.replace(".zip", "")
            if zip_basename.endswith(".zip")
            else zip_basename
        )
        result = await load_scene_from_data(scene, scene_data, reset, name=clean_name)

        # If no restore_from is set, set it to the initial.json file
        if not scene.restore_from:
            scene.restore_from = "initial.json"
            await scene.save_restore("initial.json")
            log.debug(
                "Set restore_from to initial.json", restore_from=scene.restore_from
            )

        # Save the scene to ensure the JSON file is written to the correct directory
        # This ensures both the assets and the scene JSON are in the same place
        await scene.save(auto=False, force=True)
        log.debug(
            "Saved imported scene to directory",
            save_dir=scene.save_dir,
            filename=scene.filename,
        )

        return result


async def _transfer_asset(
    scene: Scene, source_scene: Scene, source_asset_id: str
) -> str | None:
    """
    Transfer an asset from another scene to the current scene.

    Args:
        scene: The destination scene
        source_scene: The source scene containing the asset
        source_asset_id: The asset ID in the source scene

    Returns:
        The asset ID in the destination scene, or None if transfer failed
    """
    # Create transfer object
    transfer = AssetTransfer(
        source_scene_path=os.path.join(source_scene.save_dir, source_scene.filename),
        asset_id=source_asset_id,
    )

    # Transfer the asset
    success = await scene.assets.transfer_asset(transfer)
    if not success:
        return None

    # Verify the asset exists in the destination scene
    if not scene.assets.validate_asset_id(source_asset_id):
        log.warning(
            "_transfer_asset",
            message="Asset ID validation failed after transfer",
            asset_id=source_asset_id,
        )
        return None

    return source_asset_id


async def transfer_character_cover_image(
    scene: Scene, source_scene: Scene, character: Character, source_asset_id: str
) -> str | None:
    """
    Transfer a character's cover image asset from another scene to the current scene.

    Args:
        scene: The destination scene
        source_scene: The source scene containing the asset
        character: The character whose cover image is being transferred
        source_asset_id: The asset ID in the source scene

    Returns:
        The new asset ID in the destination scene, or None if transfer failed
    """
    asset_id = await _transfer_asset(scene, source_scene, source_asset_id)
    if not asset_id:
        return None

    # Set the character's cover image
    await scene.assets.set_character_cover_image(
        character, source_asset_id, override=True
    )

    return source_asset_id


async def transfer_character_avatar_assets(
    scene: Scene, source_scene: Scene, character: Character
) -> None:
    """
    Transfer a character's avatar assets (avatar and current_avatar) from another scene.

    Args:
        scene: The destination scene
        source_scene: The source scene containing the assets
        character: The character whose avatar assets are being transferred
    """
    # Transfer default avatar
    if character.avatar:
        asset_id = await _transfer_asset(scene, source_scene, character.avatar)
        if asset_id:
            await scene.assets.set_character_avatar(character, asset_id, override=True)
        else:
            # Asset couldn't be transferred, clear the reference
            character.avatar = None
            log.debug(
                "transfer_character_avatar_assets",
                message="Cleared avatar - asset not found in source",
                character=character.name,
            )

    # Transfer current avatar
    if character.current_avatar:
        asset_id = await _transfer_asset(scene, source_scene, character.current_avatar)
        if asset_id:
            await scene.assets.set_character_current_avatar(
                character, asset_id, override=True
            )
        else:
            # Asset couldn't be transferred, clear the reference
            character.current_avatar = None
            log.debug(
                "transfer_character_avatar_assets",
                message="Cleared current_avatar - asset not found in source",
                character=character.name,
            )


async def transfer_character(
    scene, scene_json_path, character_name, defer_asset_transfer: bool = False
):
    """
    Load a character from a scene json file and add it to the current scene.
    :param scene: The current scene.
    :param scene_json_path: Path to the scene json file.
    :param character_name: The name of the character to load.
    :param defer_asset_transfer: If True, skip asset transfer (caller will handle it later).
    :return: The updated scene with the new character.
    """
    # Load the json file
    with open(scene_json_path, "r") as f:
        scene_data = json.load(f)

    # Migrate to new character_data format if needed
    migrate_character_data(scene_data)

    agent = instance.get_agent("conversation")

    # Find the character in character_data dictionary (new format)
    character_data = scene_data.get("character_data", {}).get(character_name)

    if character_data:
        # Create a Character object from the character data
        character = Character(**character_data)

        # Store original asset IDs before we potentially modify them
        original_cover_image = character.cover_image
        has_avatar_assets = character.avatar or character.current_avatar

        # If character has assets and not deferring, transfer them
        if (original_cover_image or has_avatar_assets) and not defer_asset_transfer:
            # Create a temporary scene object to load the source scene's assets
            source_scene = scene_stub(scene_json_path, scene_data)
            # Assets will be loaded automatically from library.json via the assets property
            # The save_dir property will now point to the source scene's directory

            # Transfer the cover image asset
            if original_cover_image:
                await transfer_character_cover_image(
                    scene, source_scene, character, original_cover_image
                )

            # Transfer avatar assets (avatar and current_avatar)
            if has_avatar_assets:
                await transfer_character_avatar_assets(scene, source_scene, character)

        # If the character is not a player, create a conversation agent for it
        if not character.is_player:
            actor = Actor(character, agent)
        else:
            actor = Player(character, None)

        # Add the character actor to the current scene
        await scene.add_actor(actor)

        # deactivate the character
        await deactivate_character(scene, character.name)
    else:
        raise ValueError(
            f"Character '{character_name}' not found in the scene file '{scene_json_path}'"
        )

    return scene


async def handle_no_player_character(
    scene: Scene, add_default_character: bool = True, reset: bool = False
) -> None:
    """
    Handle the case where there is no player character in the scene.
    """

    existing_player = scene.get_player_character()

    if existing_player:
        await activate_character(scene, existing_player)
        return

    # no active character in scene, if reset is True, check if
    # there is a default player character in the scenes character data
    if reset:
        for character in scene.character_data.values():
            if character.is_player:
                await activate_character(scene, character)
                return

    if add_default_character:
        player = default_player_character()
    else:
        player = None

    if not player:
        log.warning("No player character found")
        return

    await scene.add_actor(player)
    await activate_character(scene, player.character)


def default_player_character() -> Player | None:
    """
    Return a default player character.
    :return: Default player character.
    """
    config: Config = get_config()
    default_player_character: GamePlayerCharacter = config.game.default_player_character
    name = default_player_character.name

    if not name:
        # We don't have a valid default player character, so we return None
        return None

    color = default_player_character.color
    description = default_player_character.description

    return Player(
        Character(
            name=name,
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

    msg = cls(**entry)

    if isinstance(msg, (NarratorMessage, ReinforcementMessage)):
        msg = msg.migrate_source_to_meta()
    elif isinstance(msg, DirectorMessage):
        msg = msg.migrate_message_to_meta()

    return msg


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


def new_scene(
    scene_initialization: SceneInitialization | None = None,
):
    """
    Create a new scene with optional inherited attributes.
    """
    scene_data = {
        "description": "",
        "name": "New scenario",
        "environment": "scene",
        "history": [],
        "archived_history": [],
        "character_data": {},
        "active_characters": [],
    }

    if scene_initialization:
        scene_data.update(scene_initialization.model_dump(exclude_none=True))

    return scene_data


def migrate_character_data(scene_data: dict):
    if "character_data" in scene_data:
        return

    log.info("Migrating to new character data storage format")

    scene_data["character_data"] = {}
    scene_data["active_characters"] = []

    for character_name, character in scene_data.get("inactive_characters", {}).items():
        scene_data["character_data"][character_name] = character

    for character in scene_data.get("characters", []):
        scene_data["character_data"][character["name"]] = character
        scene_data["active_characters"].append(character["name"])
