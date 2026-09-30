import asyncio
import json
import os
import shutil
import tempfile
import uuid
import zipfile
import pydantic
import traceback
from pathlib import Path
from collections.abc import Awaitable, Callable

import structlog

import talemate.instance as instance
from talemate import Actor, Character, Player, Scene
from talemate.knowledge.intro import initialize_intro_audience
from talemate.knowledge.perspective_models import SourcePerspectives
from talemate.character import (
    deactivate_character,
    activate_character,
    NAME_EXISTS_MESSAGE,
    name_is_taken,
)
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
    advance_message_id,
    reset_message_id,
)
from talemate.status import LoadingStatus, set_loading
from talemate.world_state import WorldState
from talemate.game.engine.nodes.registry import import_scene_node_definitions
from talemate.scene.intent import SceneIntent
from talemate.game.state import load_game_state_path_settings
from talemate.scene.schema import ScenePerspectives
from talemate.scene.format import CURRENT_SCENE_FORMAT_VERSION, read_scene_format
from talemate.knowledge.reinforcements import reinforcement_source_keys
from talemate.knowledge.perspectives import (
    bind_perspective_sources,
    shift_direct_source_times,
    validate_saved_knowledge,
)
from talemate.history import legacy_start_ts, validate_history
from talemate.knowledge.timeline import (
    shift_knowledge_edge_times,
    shift_world_entry_times,
)
import talemate.agents.tts.voice_library as voice_library
from talemate.path import SCENES_DIR
from talemate.util.gpu import release_cuda_cache
from talemate.util.time import migrate_scene_time
from talemate.changelog import import_scene_revisions, resolve_scene_revision
from talemate.shared_context import SharedContext
from talemate.scene_agent_settings import AGENT_SETTINGS_DIRNAME, resolve_link_on_load
from talemate.load.character_card import CharacterCardImportOptions
from talemate.load.creation_agent_settings import CreationAgentSettings
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


def to_project_name(name: str) -> str:
    """Convert a scene name to a project directory name."""
    return name.replace(" ", "-").replace("'", "").lower()


def load_scene_perspectives(scene_data: dict) -> ScenePerspectives:
    """
    Resolve the scene's narrative perspectives from saved scene data.

    Prefers the nested `perspectives` object when present; otherwise migrates
    the legacy flat `perspective` string into `perspectives.default`.
    """
    perspectives_data = scene_data.get("perspectives")
    if perspectives_data:
        return ScenePerspectives(**perspectives_data)
    return ScenePerspectives(default=scene_data.get("perspective", "") or "")


class SceneInitialization(pydantic.BaseModel):
    agent_settings: dict[str, dict] | None = None
    character_knowledge: pydantic.StrictBool = False
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
    before_memory: Callable[[Scene], Awaitable[None]] | None = None,
    is_current: Callable[[], bool] = lambda: True,
):
    """
    Load the scene data from the given file path.
    """

    loaded_scene = None
    creation_settings = (
        CreationAgentSettings(scene_initialization.agent_settings, is_current)
        if scene_initialization and scene_initialization.agent_settings
        else None
    )

    # Release the previous scene's reserved GPU memory before loading the next.
    # Local CUDA work (embedding re-commits, TTS) leaves PyTorch's caching
    # allocator sitting on the high-water-mark of its largest batch, which only
    # frees on process exit; returning it here gives the upcoming scene's
    # re-embed maximum headroom — on native Linux, where CUDA has no sysmem
    # fallback, that headroom is the difference between loading and an OOM. Done
    # once per scene load (not per commit) so we don't thrash the allocator
    # cache during gameplay. No-op off CUDA, or when disabled in config.
    if get_config().game.general.release_gpu_cache_on_scene_load:
        await asyncio.to_thread(release_cuda_cache)

    try:
        with SceneIsLoading(scene):
            if file_path == "$NEW_SCENE$":
                if scene_initialization:
                    scene_data = new_scene(scene_initialization)
                else:
                    scene_data = new_scene()

                # If a project_name was provided, use it as the scene name
                # and normalize it for the project directory.
                # If no project_name, generate one for the directory but
                # leave the scene name/title blank.
                if scene_initialization and scene_initialization.project_name:
                    scene_data["name"] = scene_initialization.project_name
                    scene_data["project_name"] = to_project_name(
                        scene_initialization.project_name
                    )
                else:
                    generated_name = f"new-scene-{uuid.uuid4().hex[:6]}"
                    scene_data["project_name"] = generated_name
                    scene_data["name"] = ""

                scene = await load_scene_from_data(
                    scene,
                    scene_data,
                    reset=True,
                    empty=True,
                    creation_settings=creation_settings,
                )

                # Create the scene directory on disk so assets are
                # written to the correct location even before the
                # user manually saves.
                _ = scene.save_dir

                loaded_scene = scene
                return loaded_scene

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
                loaded_scene = await load_scene_from_character_card(
                    scene,
                    file_path,
                    import_options=import_options,
                    creation_settings=creation_settings,
                    character_knowledge=bool(
                        scene_initialization
                        and scene_initialization.character_knowledge
                    ),
                )
                return loaded_scene

            # a zip file was uploaded, extract and load complete scene
            if ext == ".zip":
                if creation_settings is not None:
                    raise ValueError(
                        "Creation settings require a new scene or character card"
                    )
                loaded_scene = await load_scene_from_zip(scene, file_path, reset)
                return loaded_scene

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
                loaded_scene = await load_scene_from_character_card(
                    scene,
                    file_path,
                    import_options=import_options,
                    creation_settings=creation_settings,
                    character_knowledge=bool(
                        scene_initialization
                        and scene_initialization.character_knowledge
                    ),
                )
                return loaded_scene

            if creation_settings is not None:
                raise ValueError(
                    "Creation settings require a new scene or character card"
                )

            # if it is a talemate scene, load it
            loaded_scene = await load_scene_from_data(
                scene, scene_data, reset, name=file_path
            )
            return loaded_scene
    except Exception as e:
        log.error("load_scene", error=traceback.format_exc())
        raise e
    finally:
        if loaded_scene is not None:
            if add_to_recent:
                await loaded_scene.add_to_recent_scenes()
            if before_memory is not None:
                await before_memory(loaded_scene)
            await loaded_scene.commit_to_memory()
            if creation_settings is not None:
                await creation_settings.persist(loaded_scene)


def prepare_scene_data(scene_data: dict) -> dict:
    read_scene_format(scene_data)
    validate_saved_knowledge(scene_data)
    migrate_character_data(scene_data)
    migrate_director_chat_state(scene_data)
    migrate_scene_time(scene_data)
    scene_data["format_version"] = CURRENT_SCENE_FORMAT_VERSION
    scene_data.setdefault("knowledge_eligibility", "legacy")
    return scene_data


async def _apply_shared_static_history(scene, start_from_shared_entries: bool):
    """
    The shared static entries in the scene's timeline. With
    `start_from_shared_entries` — a save and a shared file both written before
    `start_ts` existed — they keep their saved times and the newest static
    entry gives the scene start, as in that version. Otherwise each entry keeps
    its distance from the start of the scene that wrote it.
    """
    await scene.shared_context.apply_static_history(
        scene, relative=not start_from_shared_entries
    )
    if start_from_shared_entries:
        scene.start_ts = legacy_start_ts(scene.archived_history)


async def load_scene_from_data(
    scene,
    scene_data,
    reset: bool = False,
    name: str | None = None,
    empty: bool = False,
    creation_settings=None,
) -> Scene:
    scene_data = prepare_scene_data(scene_data)
    metadata = read_scene_format(scene_data)
    knowledge = validate_saved_knowledge(scene_data)
    if scene._changelog:
        await scene._changelog.__aexit__(None, None, None)
        scene._changelog = None
    loading_status = LoadingStatus(1)
    reset_message_id()
    config: Config = get_config()

    memory = instance.get_agent("memory")

    scene.knowledge_eligibility = metadata.knowledge_eligibility
    scene.description = scene_data.get("description", "")
    scene.intro = scene_data.get("intro", "") or scene.description
    scene.intro_present = None
    scene.intro_knowledge = None
    scene.name = scene_data.get("name", "Unknown Scene")
    scene.environment = scene_data.get("environment", "scene")
    scene.filename = None
    scene.immutable_save = scene_data.get("immutable_save", False)
    scene.experimental = scene_data.get("experimental", False)
    scene.hidden = scene_data.get("hidden", False)
    scene.deprecated = scene_data.get("deprecated", False)
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
    # a de-duplicated copy of the saved list: from here on the scene's own list
    # is maintained by add_actor / remove_actor, one entry per actor
    scene.active_characters = list(
        dict.fromkeys(scene_data.get("active_characters") or [])
    )
    scene.context = scene_data.get("context", "")
    scene.perspectives = load_scene_perspectives(scene_data)
    scene.project_name = scene_data.get("project_name")
    scene.intent_state = SceneIntent(**scene_data.get("intent_state", {}))
    scene.history = _load_history(scene_data["history"])
    scene.archived_history = scene_data["archived_history"]
    scene.layered_history = scene_data.get("layered_history", [])
    for entries in [scene.archived_history, *scene.layered_history]:
        for entry in entries:
            entry.pop("facts_status", None)
            if entry.get("knowledge") is not None:
                entry["knowledge"] = SourcePerspectives.model_validate(
                    entry["knowledge"]
                ).model_dump(mode="json")
    # a save from an older version has no start: its own static entries give it
    own_start_ts = scene_data.get("start_ts")
    if own_start_ts is None:
        own_start_ts = legacy_start_ts(scene.archived_history)
    scene.start_ts = own_start_ts
    # a save and a shared file both from an older version: the shared entries
    # keep their saved times and give the start, as in that version
    start_from_shared_entries = False
    scene.knowledge = knowledge
    if knowledge:
        advance_message_id(
            max(
                (item.message_id_boundary for item in knowledge.disclosures),
                default=0,
            )
        )

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
            start_from_shared_entries = (
                scene_data.get("start_ts") is None
                and scene.shared_context.start_ts is None
            )
            if not reset:
                await _apply_shared_static_history(scene, start_from_shared_entries)
                await scene.shared_context.apply_characters(scene)
    else:
        scene.shared_context = None

    await resolve_link_on_load(scene, scene_data)
    if creation_settings is not None:
        creation_settings.install(scene)

    import_scene_node_definitions(scene)

    # the shared static history can move the timeline before the saved
    # knowledge edges, reinforcement passages, world entries and intro
    # perspectives are loaded: they arrive on the old timeline and are moved
    # by the same amount
    late_shift = 0

    if not reset:
        scene.id = scene_data.get("id", scene.id)
        scene.playthrough_progress = scene_data.get("playthrough_progress")
        scene.memory_id = scene_data.get("memory_id", scene.memory_id)
        scene.saved_memory_session_id = scene_data.get("saved_memory_session_id", None)
        scene.memory_session_id = scene_data.get("memory_session_id", None)
        world_state_data = scene_data.get("world_state", {})
        scene.world_state = WorldState(**world_state_data)
        scene.world_state.validate_snapshot_audiences(scene.character_data)
        scene.game_state = GameState(**scene_data.get("game_state", {}))
        scene.agent_state = scene_data.get("agent_state", {})
        scene.game_state_watch_paths = scene_data.get("game_state_watch_paths", [])
        scene.game_state_knob_paths = scene_data.get("game_state_knob_paths", [])
        scene.game_state_path_settings = load_game_state_path_settings(
            scene_data.get("game_state_path_settings", {}),
            scene.pinned_game_state_paths,
        )
        scene.filename = os.path.basename(
            name or scene.name.lower().replace(" ", "_") + ".json"
        )
        if not start_from_shared_entries:
            late_shift = scene.start_ts - own_start_ts
            shift_knowledge_edge_times(scene, late_shift)
            shift_direct_source_times(scene, late_shift)
            shift_world_entry_times(scene, late_shift)
        if scene.shared_context:
            if scene.shared_context.format_version is None:
                await scene.shared_context.add_missing_world_entries(scene)
            # after late_shift: a shared entry keeps the time the writer stored
            await scene.shared_context.apply_world_entries(scene)
        scene.fix_time()
        log.debug("scene time", ts=scene.ts)
    else:
        scene.history = []
        scene.archived_history = []
        scene.layered_history = []
        scene.start_ts = 0
        if scene.shared_context:
            # the emptied archive would otherwise reach the shared file at the
            # first save and take the static history from every linked scene
            await _apply_shared_static_history(scene, start_from_shared_entries)
            await scene.shared_context.apply_characters(scene)
            await scene.shared_context.apply_world_entries(scene)
        # the shared static history can move the clock
        scene.sync_time()
        scene.knowledge = None
        scene.intent_state.reset()

    bind_perspective_sources(scene)
    # Orphaned entry associations must not attach to a future reused message ID.
    advance_message_id(
        max((key[1] for key in reinforcement_source_keys(scene)), default=0)
    )
    asset_data = scene_data.get("assets", {})
    scene.assets.cover_image = asset_data.get("cover_image", None)
    scene.assets.backdrop = asset_data.get("backdrop", None)
    scene.assets.backdrop_enabled = asset_data.get("backdrop_enabled", True)
    scene.assets.load_assets(asset_data.get("assets", {}))

    # Clean up cover images and message avatars that reference non-existent assets
    scene.assets.cleanup_cover_images()
    scene.assets.cleanup_message_avatars()

    loading_status("Initializing long-term memory...")

    await memory.set_db()
    # await memory.remove_unsaved_memory()

    if not scene.memory_session_id:
        scene.set_new_memory_session_id()

    if not reset:
        await validate_history(scene, commit_to_memory=False)

    # Activate active characters
    # Only activate characters that exist in character_data
    for character_name in list(scene.active_characters):
        if character_name not in scene.character_data:
            log.warning(
                "Character not found in character_data, skipping activation",
                character_name=character_name,
                available_characters=list(scene.character_data.keys()),
            )
            scene.active_characters.remove(character_name)
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

    await resolve_scene_revision(scene)
    log.debug("Loaded scene", rev=scene.rev)

    # Initialize intro and title for new scenes
    await _initialize_scene_intro(scene, scene_data, empty)

    initialize_intro_audience(scene, {} if reset else scene_data, shift=late_shift)

    await scene.world_state_manager.remove_pins_without_source()

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

            with zipf.open("scene.json") as scene_file:
                scene_data = json.load(scene_file)
            read_scene_format(scene_data)
            validate_saved_knowledge(scene_data)

            # Extract all files
            zipf.extractall(temp_path)
            log.debug("Extracted ZIP contents", files=len(zipf.namelist()))

        log.debug(
            "Loaded scene JSON from ZIP", scene_name=scene_data.get("name", "Unknown")
        )

        # Generate unique scene name for ZIP imports to avoid conflicts
        # The scene's save_dir is derived from its name, so we set the name
        base_scene_name = scene_data.get("name", "imported-scene")

        # Handle directory name conflicts by adding suffix to the scene name
        scene_name = base_scene_name
        counter = 1

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
        scene.project_name = to_project_name(scene_name)

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

        # Restore agent-settings if they exist in ZIP. Mirrors the export
        # side — without this the importing user's scene loses the per-scene
        # agent overlay referenced by `agent_settings_file`.
        agent_settings_source = temp_path / AGENT_SETTINGS_DIRNAME
        if agent_settings_source.exists():
            agent_settings_dest = Path(scene.save_dir) / AGENT_SETTINGS_DIRNAME
            shutil.copytree(agent_settings_source, agent_settings_dest)
            log.debug(
                "Loaded agent-settings directory",
                source=agent_settings_source,
                dest=agent_settings_dest,
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
        scene_data["name"] = scene.name
        scene_data["project_name"] = to_project_name(scene.name)

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

        scene.filename = (
            scene.filename
            if scene.filename.endswith(".json")
            else scene.filename + ".json"
        )
        if not reset:
            await import_scene_revisions(temp_path / "data.db", scene)

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

        # refuse before any asset is copied - add_actor would refuse anyway,
        # and the copy leaves the assets behind in the target scene
        if name_is_taken(scene, character.name):
            raise ValueError(NAME_EXISTS_MESSAGE.format(name=character.name))

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
        await deactivate_character(scene, character.name, record_transition=False)
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

    # the scene may already hold a character under the configured name - adopt
    # it instead of shadowing it with a blank default, but only when the scene
    # itself calls it the player: turning an NPC into one is written into the
    # next save and the user has to repair it by hand
    existing = name_is_taken(scene, player.name)
    if existing is not None:
        if not existing.is_player:
            log.warning("Default player character name is taken", name=player.name)
            return
        await activate_character(scene, existing)
        return

    await activate_character(scene, player)


def default_player_character() -> Character | None:
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

    return Character(
        name=name,
        description=description,
        greeting_text="",
        color=color,
        is_player=True,
    )


def _load_history(history):
    # Two passes: move the allocator past every persisted id first, so an
    # entry without an id (legacy/corrupt file) cannot take a counter id that
    # a later entry preserves.
    max_persisted_id = max(
        (
            entry["id"]
            for entry in history
            if isinstance(entry, dict)
            and isinstance(entry.get("id"), int)
            and not isinstance(entry.get("id"), bool)
        ),
        default=0,
    )
    if max_persisted_id:
        advance_message_id(max_persisted_id)

    _history = []

    for text in history:
        if isinstance(text, str):
            _history.append(_prepare_legacy_history(text))

        elif isinstance(text, dict):
            _history.append(_prepare_history(text))

    return _history


def _prepare_history(entry):
    typ = entry.pop("typ", "scene_message")
    persisted_id = entry.pop("id", None)

    # Message ids are message identity across save/load (the changelog chain
    # refers to them), so a persisted id is kept and the allocator moved past
    # it; anything else gets a fresh id from the counter.
    if isinstance(persisted_id, int) and not isinstance(persisted_id, bool):
        advance_message_id(persisted_id)
        entry["id"] = persisted_id

    if entry.get("source") == "":
        entry.pop("source")

    cls = MESSAGES.get(typ, SceneMessage)

    # Tolerate corrupt history entries (e.g. produced by changelog delta
    # reconstruction) that have lost their `message` field. Construction
    # would otherwise raise a pydantic ValidationError and abort the whole
    # scene load.
    if "message" not in entry:
        log.warning("history entry missing message; substituting empty", entry=entry)
        entry["message"] = ""

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
        scene_data.update(
            scene_initialization.model_dump(
                exclude_none=True, exclude={"character_knowledge"}
            )
        )
        if scene_initialization.character_knowledge:
            scene_data.update(
                format_version=CURRENT_SCENE_FORMAT_VERSION,
                knowledge_eligibility="perception",
            )

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


def migrate_director_chat_state(scene_data: dict):
    """Migrate old singleton director chat to multi-chat collection format."""
    director_state = scene_data.get("agent_state", {}).get("director", {})
    if not director_state:
        return
    # Already migrated
    if "chats" in director_state:
        return
    # Old format present
    old_chat = director_state.pop("chat", None)
    if old_chat:
        chat_id = old_chat.get("id", str(uuid.uuid4())[:10])
        old_chat["title"] = "Original Chat"
        if "created_at" not in old_chat:
            old_chat["created_at"] = 0
        director_state["chats"] = {chat_id: old_chat}
        director_state["last_active_chat_id"] = chat_id
        log.info(
            "Migrated singleton director chat to multi-chat format", chat_id=chat_id
        )
    else:
        director_state["chats"] = {}
