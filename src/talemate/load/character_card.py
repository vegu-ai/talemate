import enum
import json
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pydantic
import structlog

import talemate.instance as instance
from talemate import Actor, Character
from talemate.instance import get_agent
from talemate.character import activate_character
from talemate.exceptions import UnknownDataSpec
from talemate.status import LoadingStatus
from talemate.util import extract_metadata
from talemate.game.engine.nodes.registry import import_scene_node_definitions
from talemate.scene_assets import (
    set_scene_cover_image,
    set_character_cover_image,
)
from talemate.world_state import ManualContext

if TYPE_CHECKING:
    from talemate.agents.director import DirectorAgent

log = structlog.get_logger("talemate.load.character_card")


class CharacterBookEntry(pydantic.BaseModel):
    """Represents a single entry in a character book."""

    keys: list[str]
    content: str
    extensions: dict[str, Any] = pydantic.Field(default_factory=dict)
    enabled: bool = True
    insertion_order: int = 0
    case_sensitive: bool = False
    name: str | None = None
    priority: int | None = None
    id: int | None = None
    comment: str | None = None
    selective: bool = False
    secondary_keys: list[str] = pydantic.Field(default_factory=list)
    constant: bool = False
    position: str | None = None  # 'before_char' | 'after_char'


class CharacterBook(pydantic.BaseModel):
    """Represents a character book from a V2 character card."""

    name: str | None = None
    description: str | None = None
    scan_depth: int | None = None
    token_budget: int | None = None
    recursive_scanning: bool = False
    extensions: dict[str, Any] = pydantic.Field(default_factory=dict)
    entries: list[CharacterBookEntry] = pydantic.Field(default_factory=list)


class CharacterBookMeta(pydantic.BaseModel):
    """Metadata for a character book entry stored in ManualContext."""

    character_book_name: str = ""
    keys: list[str]
    insertion_order: int = 0
    case_sensitive: bool = False
    entry_name: str | None = None
    priority: int | None = None
    selective: bool = False
    secondary_keys: list[str] = pydantic.Field(default_factory=list)
    constant: bool = False
    position: str | None = None
    extensions: dict[str, Any] = pydantic.Field(default_factory=dict)


class ImportSpec(str, enum.Enum):
    talemate = "talemate"
    talemate_complete = "talemate_complete"
    chara_card_v0 = "chara_card_v0"
    chara_card_v2 = "chara_card_v2"
    chara_card_v1 = "chara_card_v1"
    chara_card_v3 = "chara_card_v3"


def identify_import_spec(data: dict) -> ImportSpec:
    if data.get("spec") == "chara_card_v3":
        return ImportSpec.chara_card_v3

    if data.get("spec") == "chara_card_v2":
        return ImportSpec.chara_card_v2

    if data.get("spec") == "chara_card_v1":
        return ImportSpec.chara_card_v1

    if "first_mes" in data:
        # original chara card didnt specify a spec,
        # if the first_mes key exists, we can assume it's a v0 chara card
        return ImportSpec.chara_card_v0

    if "first_mes" in data.get("data", {}):
        # this can also serve as a fallback for future chara card versions
        # as they are supposed to be backwards compatible
        return ImportSpec.chara_card_v3

    # TODO: probably should actually check for valid talemate scene data
    return ImportSpec.talemate


async def load_scene_from_character_card(scene, file_path):
    """
    Load a character card (tavern etc.) from the given file path.
    """
    # Import here to avoid circular import
    from talemate.load import handle_no_player_character

    director: "DirectorAgent" = get_agent("director")
    LOADING_STEPS = 6
    if director.auto_direct_enabled:
        LOADING_STEPS += 2

    loading_status = LoadingStatus(LOADING_STEPS)
    loading_status("Loading character card...")

    file_ext = os.path.splitext(file_path)[1].lower()
    image_format = file_ext.lstrip(".")
    image = False

    await handle_no_player_character(scene)

    # Extract raw metadata to get character_book and alternate_greetings if present
    character_book_data = None
    alternate_greetings = []
    # If a json file is found, use Character.load_from_json instead
    if file_ext == ".json":
        with open(file_path, "r") as f:
            raw_data = json.load(f)
        spec = identify_import_spec(raw_data)
        if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
            character_book_data = raw_data.get("data", {}).get("character_book")
            alternate_greetings = raw_data.get("data", {}).get(
                "alternate_greetings", []
            )
        character = load_character_from_json(file_path)
    else:
        metadata = extract_metadata(file_path, image_format)
        spec = identify_import_spec(metadata)
        if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
            character_book_data = metadata.get("data", {}).get("character_book")
            alternate_greetings = metadata.get("data", {}).get(
                "alternate_greetings", []
            )
        character = load_character_from_image(file_path, image_format)
        image = True

    conversation = instance.get_agent("conversation")
    creator = instance.get_agent("creator")
    memory = instance.get_agent("memory")

    actor = Actor(character, conversation)

    scene.name = character.name

    loading_status("Initializing long-term memory...")

    await memory.set_db()

    # Load character book entries into world state if present
    if character_book_data:
        loading_status("Loading character book entries...")
        try:
            manual_contexts = create_manual_context_from_character_book(
                character_book_data
            )
            # Add entries to scene's world state
            # They will be committed to memory when scene.save() is called
            for entry_id, manual_context in manual_contexts.items():
                scene.world_state.manual_context[entry_id] = manual_context
            log.debug(
                "Loaded character book entries",
                count=len(manual_contexts),
            )
        except Exception as e:
            log.warning(
                "Failed to load character book entries",
                error=str(e),
            )

    await scene.add_actor(actor)

    log.debug(
        "load_scene_from_character_card",
        scene=scene,
        character=character,
        content_context=scene.context,
    )

    loading_status("Determine character context...")

    if not scene.context:
        try:
            scene.context = await creator.determine_content_context_for_character(
                character
            )
            log.debug("content_context", content_context=scene.context)
        except Exception as e:
            log.error("determine_content_context_for_character", error=e)

    # attempt to convert to base attributes
    try:
        loading_status("Determine character attributes...")

        _, character.base_attributes = await creator.determine_character_attributes(
            character
        )
        # lowercase keys
        character.base_attributes = {
            k.lower(): v for k, v in character.base_attributes.items()
        }

        character.dialogue_instructions = (
            await creator.determine_character_dialogue_instructions(character)
        )

        # any values that are lists should be converted to strings joined by ,

        for k, v in character.base_attributes.items():
            if isinstance(v, list):
                character.base_attributes[k] = ",".join(v)

        # transfer description to character
        if character.base_attributes.get("description"):
            character.description = character.base_attributes.pop("description")

        log.debug("base_attributes parsed", base_attributes=character.base_attributes)
    except Exception as e:
        log.warning("determine_character_attributes", error=e)

    await activate_character(scene, character)

    scene.description = character.description

    # Set intro_versions from alternate_greetings if present
    if alternate_greetings:
        scene.intro_versions = alternate_greetings

    if image:
        # Add the asset once and set both scene and character cover images
        asset = scene.assets.add_asset_from_file_path(file_path)
        await set_scene_cover_image(scene, asset.id)
        await set_character_cover_image(scene, character, asset.id)

    # assign tts voice to character
    await director.assign_voice_to_character(character)

    # if auto direct is enabled, generate a story intent
    # and then set the scene intent
    try:
        loading_status("Generating story intent...")
        creator = get_agent("creator")
        story_intent = await creator.contextual_generate_from_args(
            context="scene intent:overall",
            length=256,
        )
        scene.intent_state.intent = story_intent
        if director.auto_direct_enabled:
            loading_status("Generating scene types...")
            await director.auto_direct_generate_scene_types(
                instructions=story_intent,
                max_scene_types=2,
            )
            loading_status("Setting scene intent...")
            await director.auto_direct_set_scene_intent(require=True)
    except Exception as e:
        log.error("generate story intent", error=e)

    scene.saved = False

    restore_file = "initial.json"

    # check if restore_file exists already
    if os.path.exists(Path(scene.save_dir) / restore_file):
        uid = str(uuid.uuid4())[:8]
        restore_file = f"initial-{uid}.json"
        log.warning(
            "Restore file already exists, creating a new one",
            restore_file=restore_file,
        )

    await scene.save_restore(restore_file)
    scene.restore_from = restore_file

    import_scene_node_definitions(scene)

    save_file = f"{scene.project_name}.json"

    # check if save_file exists already
    if os.path.exists(Path(scene.save_dir) / save_file):
        uid = str(uuid.uuid4())[:8]
        save_file = f"{scene.project_name}-{uid}.json"
        log.warning(
            "Save file already exists, creating a new one",
            save_file=save_file,
        )
    await scene.save(
        save_as=True,
        auto=True,
        copy_name=save_file,
    )

    return scene


def load_character_from_image(image_path: str, file_format: str) -> Character:
    """
    Load a character from the image file's metadata and return it.
    :param image_path: Path to the image file.
    :param file_format: Image file format ('png' or 'webp').
    :return: Character loaded from the image metadata.
    """
    metadata = extract_metadata(image_path, file_format)
    spec = identify_import_spec(metadata)

    log.debug("load_character_from_image", spec=spec)

    if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
        return character_from_chara_data(metadata["data"])
    elif spec == ImportSpec.chara_card_v1 or spec == ImportSpec.chara_card_v0:
        return character_from_chara_data(metadata)

    raise UnknownDataSpec(metadata)


def load_character_from_json(json_path: str) -> Character:
    """
    Load a character from a json file and return it.
    :param json_path: Path to the json file.
    :return: Character loaded from the json file.
    """

    with open(json_path, "r") as f:
        data = json.load(f)

    spec = identify_import_spec(data)

    if spec == ImportSpec.chara_card_v2:
        return character_from_chara_data(data["data"])
    elif spec == ImportSpec.chara_card_v1:
        return character_from_chara_data(data)

    raise UnknownDataSpec(data)


def character_from_chara_data(data: dict) -> Character:
    """
    Generates a barebones character from a character card data dictionary.
    """

    character = Character(
        name="UNKNOWN",
        description="",
        greeting_text="",
    )

    if "name" in data:
        character.name = data["name"]

    # loop through the metadata and set the character name everywhere {{char}}
    # occurs

    for key in data:
        if isinstance(data[key], str):
            data[key] = data[key].replace("{{char}}", character.name)

    if "description" in data:
        character.description = data["description"]
    if "scenario" in data:
        character.description += "\n" + data["scenario"]
    if "first_mes" in data:
        character.greeting_text = data["first_mes"]
    if "gender" in data:
        character.gender = data["gender"]
    if "color" in data:
        character.color = data["color"]
    if "mes_example" in data:
        new_line_match = "\r\n" if "\r\n" in data["mes_example"] else "\n"
        for message in data["mes_example"].split("<START>"):
            if message.strip(new_line_match):
                character.example_dialogue.extend(
                    [m for m in message.split(new_line_match) if m]
                )

    return character


def load_from_image_metadata(image_path: str, file_format: str):
    """
    Load character data from an image file's metadata using the extract_metadata function.

    Args:
    image_path (str): The path to the image file.
    file_format (str): The image file format ('png' or 'webp').

    Returns:
    None
    """

    metadata = extract_metadata(image_path, file_format)

    if metadata.get("spec") == "chara_card_v2":
        metadata = metadata["data"]

    return character_from_chara_data(metadata)


def create_manual_context_from_character_book(
    character_book: CharacterBook | dict[str, Any] | None,
    skip_disabled: bool = True,
    import_meta: bool = True,
) -> dict[str, ManualContext]:
    """
    Creates ManualContext entries from a character card's character_book.

    Args:
        character_book: The character_book data, either as a CharacterBook model,
                       a dict, or None if not present.
        skip_disabled: If True, skip entries where enabled=False. Defaults to True.
        import_meta: If True, include character book metadata in the 'chara' sub-dictionary.
                    Defaults to True.

    Returns:
        A dictionary mapping entry IDs to ManualContext objects.
    """
    if character_book is None:
        return {}

    # Convert dict to CharacterBook model if needed
    if isinstance(character_book, dict):
        try:
            character_book = CharacterBook(**character_book)
        except Exception as e:
            log.warning(
                "Failed to parse character_book",
                error=str(e),
                character_book=character_book,
            )
            return {}

    manual_contexts = {}

    for entry in character_book.entries:
        # Skip disabled entries if requested
        if skip_disabled and not entry.enabled:
            continue

        # Generate a unique ID for the entry
        # Priority: entry_name > entry.id > UUID fallback
        if entry.name:
            entry_id = entry.name
        elif entry.id is not None:
            entry_id = f"character_book_{entry.id}"
        else:
            # Generate a UUID-based ID
            entry_id = f"character_book_{uuid.uuid4().hex[:10]}"

        # Build metadata - talemate-known fields at top level
        meta = {
            "source": "imported",
            "typ": "world_state",
        }

        # Character book specific fields go in 'chara' sub-dictionary (if requested)
        if import_meta:
            chara_meta = CharacterBookMeta(
                character_book_name=character_book.name or "",
                keys=entry.keys,
                insertion_order=entry.insertion_order,
                case_sensitive=entry.case_sensitive,
                entry_name=entry.name,
                priority=entry.priority,
                selective=entry.selective,
                secondary_keys=entry.secondary_keys,
                constant=entry.constant,
                position=entry.position,
                extensions=entry.extensions,
            )

            meta["chara"] = chara_meta.model_dump(exclude_none=False)

        # Create ManualContext
        manual_context = ManualContext(
            id=entry_id,
            text=entry.content,
            meta=meta,
            shared=False,
        )

        manual_contexts[entry_id] = manual_context

    return manual_contexts
