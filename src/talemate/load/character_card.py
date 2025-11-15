import enum
import json
import os
import re
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


class CharacterCardImportOptions(pydantic.BaseModel):
    """Options for importing a character card."""

    import_all_characters: bool = False
    import_character_book: bool = True
    import_character_book_meta: bool = True
    import_alternate_greetings: bool = True


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


def _setup_loading_status() -> LoadingStatus:
    """Set up and return loading status tracker."""
    director = instance.get_agent("director")
    loading_steps = 6
    if director.auto_direct_enabled:
        loading_steps += 2
    loading_status = LoadingStatus(loading_steps)
    loading_status("Loading character card...")
    return loading_status


def _extract_scene_name_from_spec(raw_data_or_metadata: dict | None) -> str | None:
    """
    Extract scene name from character card spec according to chara_card_v2 specification.
    
    According to the spec:
    - For v2/v3: name is in data.name
    - For v0/v1: name is at top level
    
    Args:
        raw_data_or_metadata: Raw character card data (JSON dict or image metadata)
        
    Returns:
        Scene name from spec if available, None otherwise
    """
    if not raw_data_or_metadata or not isinstance(raw_data_or_metadata, dict):
        return None
    
    spec = identify_import_spec(raw_data_or_metadata)
    
    if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
        # V2/V3: name is in data.name
        data_section = raw_data_or_metadata.get("data", {})
        if "name" in data_section and data_section["name"]:
            return data_section["name"]
    elif spec == ImportSpec.chara_card_v0 or spec == ImportSpec.chara_card_v1:
        # V0/V1: name is at top level
        if "name" in raw_data_or_metadata and raw_data_or_metadata["name"]:
            return raw_data_or_metadata["name"]
    
    return None


def _extract_character_data_from_file(
    file_path: str, file_ext: str
) -> tuple[Character, dict | None, list[str], bool, dict | None]:
    """
    Extract character data from file (JSON or image).
    
    Returns:
        Tuple of (character, character_book_data, alternate_greetings, is_image, raw_data/metadata)
    """
    character_book_data = None
    alternate_greetings = []
    is_image = False
    raw_data_or_metadata = None
    
    if file_ext == ".json":
        with open(file_path, "r") as f:
            raw_data = json.load(f)
        raw_data_or_metadata = raw_data
        spec = identify_import_spec(raw_data)
        if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
            character_book_data = raw_data.get("data", {}).get("character_book")
            alternate_greetings = raw_data.get("data", {}).get(
                "alternate_greetings", []
            )
        character = load_character_from_json(file_path)
    else:
        image_format = file_ext.lstrip(".")
        metadata = extract_metadata(file_path, image_format)
        raw_data_or_metadata = metadata
        spec = identify_import_spec(metadata)
        if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
            character_book_data = metadata.get("data", {}).get("character_book")
            alternate_greetings = metadata.get("data", {}).get(
                "alternate_greetings", []
            )
        character = load_character_from_image(file_path, image_format)
        is_image = True
    
    return character, character_book_data, alternate_greetings, is_image, raw_data_or_metadata


async def _initialize_scene_memory(
    scene,
    memory,
    character_book_data: dict | None,
    loading_status: LoadingStatus,
    import_character_book: bool = True,
    import_character_book_meta: bool = True,
) -> None:
    """Initialize memory and load character book entries if present."""
    loading_status("Initializing long-term memory...")
    await memory.set_db()
    
    if character_book_data and import_character_book:
        loading_status("Loading character book entries...")
        try:
            manual_contexts = create_manual_context_from_character_book(
                character_book_data,
                import_meta=import_character_book_meta,
            )
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


async def _determine_character_context(
    scene, character, creator, loading_status: LoadingStatus
) -> None:
    """Determine and set character content context."""
    loading_status("Determine character context...")
    
    if not scene.context:
        try:
            scene.context = await creator.determine_content_context_for_character(
                character
            )
            log.debug("content_context", content_context=scene.context)
        except Exception as e:
            log.error("determine_content_context_for_character", error=e)


async def _determine_character_description(
    character,
    creator,
    loading_status: LoadingStatus,
    card_description: str = "",
    greeting_texts: list[str] | None = None,
) -> None:
    """Determine and set character description."""
    loading_status(f"Determine description for {character.name}...")
    
    try:
        # Combine greeting texts into a single text string
        greeting_text = ""
        if greeting_texts:
            greeting_text = "\n\n".join(greeting_texts)
        
        character.description = await creator.determine_character_description(
            character,
            text=greeting_text,
            information=card_description,
        )
        log.debug("character_description", character=character.name, description=character.description)
    except Exception as e:
        log.warning("determine_character_description", error=e)


async def _determine_character_attributes(
    character, creator, loading_status: LoadingStatus
) -> None:
    """Determine and set character attributes and dialogue instructions."""
    loading_status("Determine character attributes...")
    
    try:
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
        
        log.debug("base_attributes parsed", base_attributes=character.base_attributes)
    except Exception as e:
        log.warning("determine_character_attributes", error=e)


async def _setup_character_assets(
    scene, character, file_path: str, is_image: bool
) -> None:
    """Set up character and scene cover images if loading from image."""
    if is_image:
        asset = scene.assets.add_asset_from_file_path(file_path)
        await set_scene_cover_image(scene, asset.id)
        await set_character_cover_image(scene, character, asset.id)


async def _generate_story_intent(
    scene, loading_status: LoadingStatus
) -> None:
    """Generate story intent and scene types if auto-direct is enabled."""
    try:
        loading_status("Generating story intent...")
        creator = get_agent("creator")
        story_intent = await creator.contextual_generate_from_args(
            context="scene intent:overall",
            length=256,
        )
        scene.intent_state.intent = story_intent
        director = instance.get_agent("director")
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


def _generate_unique_filename(base_name: str, save_dir: Path) -> str:
    """Generate a unique filename if the base name already exists."""
    if os.path.exists(save_dir / base_name):
        uid = str(uuid.uuid4())[:8]
        name_parts = os.path.splitext(base_name)
        unique_name = f"{name_parts[0]}-{uid}{name_parts[1]}"
        log.warning(
            "File already exists, creating a new one",
            original=base_name,
            new=unique_name,
        )
        return unique_name
    return base_name


async def _save_scene_files(scene) -> None:
    """Save restore file and scene file with unique names if needed."""
    scene.saved = False
    
    restore_file = _generate_unique_filename("initial.json", Path(scene.save_dir))
    await scene.save_restore(restore_file)
    scene.restore_from = restore_file
    
    import_scene_node_definitions(scene)
    
    save_file = _generate_unique_filename(
        f"{scene.project_name}.json", Path(scene.save_dir)
    )
    await scene.save(
        save_as=True,
        auto=True,
        copy_name=save_file,
    )


def _parse_characters_from_greeting_text(greeting_text: str) -> list[str]:
    """
    Parse character names from greeting text using {name}: pattern.
    
    Args:
        greeting_text: The greeting text to parse
        
    Returns:
        List of character names found in the greeting text
    """
    # Pattern to match {name}: format
    pattern = r'\{([^}]+)\}:'
    matches = re.findall(pattern, greeting_text)
    return [name.strip() for name in matches if name.strip()]


async def _detect_and_select_characters(
    character: Character,
    greeting_text: str,
    alternate_greetings: list[str],
    import_all_characters: bool = False,
    loading_status: LoadingStatus | None = None,
) -> tuple[list[Character], list[str]]:
    """
    Detect multiple characters from greeting texts and optionally import all or select one.
    
    Args:
        character: The initial character loaded from the card
        greeting_text: The main greeting text
        alternate_greetings: List of alternate greeting texts to include in detection
        import_all_characters: If True, import all detected characters. If False, select the first one.
        loading_status: Optional loading status tracker
        
    Returns:
        Tuple of (list of characters to import, alternate_greetings)
    """
    if loading_status:
        loading_status("Detecting characters from texts...")
    
    # Collect all texts for detection
    all_texts = [greeting_text]
    if alternate_greetings:
        all_texts.extend(alternate_greetings)
    
    # Detect characters from texts
    director = instance.get_agent("director")
    detected_character_names = await director.detect_characters_from_texts(texts=all_texts)
    
    # If no characters detected or only one, use the original character
    if not detected_character_names or len(detected_character_names) == 1:
        log.debug(
            "detect_and_select_characters",
            detected_count=len(detected_character_names) if detected_character_names else 0,
            using_original=True,
        )
        return [character], alternate_greetings if alternate_greetings else []
    
    # Multiple characters detected
    if import_all_characters:
        # Create a character for each detected name
        characters = []
        for char_name in detected_character_names:
            # Create a copy of the original character with the new name
            new_character = Character(
                name=char_name,
                description=character.description,
                greeting_text=character.greeting_text,  # Keep original greeting text
                color=character.color,
                is_player=character.is_player,
                dialogue_instructions=character.dialogue_instructions,
                example_dialogue=character.example_dialogue.copy(),
                base_attributes=character.base_attributes.copy(),
                details=character.details.copy(),
            )
            characters.append(new_character)
        
        log.debug(
            "detect_and_select_characters",
            detected_count=len(detected_character_names),
            importing_all=True,
            characters=[c.name for c in characters],
        )
        return characters, alternate_greetings if alternate_greetings else []
    else:
        # Select first character
        character.name = detected_character_names[0]
        
        log.debug(
            "detect_and_select_characters",
            detected_count=len(detected_character_names),
            selected_character=character.name,
        )
        
        return [character], alternate_greetings if alternate_greetings else []


async def load_scene_from_character_card(
    scene,
    file_path,
    import_options: CharacterCardImportOptions | None = None,
):
    """
    Load a character card (tavern etc.) from the given file path.
    
    Args:
        scene: The scene to load the character into
        file_path: Path to the character card file
        import_options: Options for importing the character card. If None, uses default options.
    """
    if import_options is None:
        import_options = CharacterCardImportOptions()
    # Import here to avoid circular import
    from talemate.load import handle_no_player_character

    loading_status = _setup_loading_status()
    
    file_ext = os.path.splitext(file_path)[1].lower()
    
    await handle_no_player_character(scene)
    
    # Extract character data from file
    original_character, character_book_data, alternate_greetings, is_image, raw_data_or_metadata = (
        _extract_character_data_from_file(file_path, file_ext)
    )
    
    # Store original greeting text - this will be used for scene setup
    original_greeting_text = original_character.greeting_text
    
    # Store original card description - this will be used for scene description
    card_description = original_character.description
    
    # Collect all greeting texts for character description determination
    all_greeting_texts = [original_greeting_text]
    if alternate_greetings:
        all_greeting_texts.extend(alternate_greetings)
    
    # Filter alternate greetings based on import flag before detection
    # (preserve original list for later use in scene.intro_versions)
    greetings_for_detection = alternate_greetings if import_options.import_alternate_greetings else []
    
    # Detect and select characters from greetings if multiple are present
    characters, _ = await _detect_and_select_characters(
        character=original_character,
        greeting_text=original_character.greeting_text,
        alternate_greetings=greetings_for_detection,
        import_all_characters=import_options.import_all_characters,
        loading_status=loading_status,
    )
    
    # Guard: ensure we have at least one character
    if not characters:
        raise ValueError("No characters detected or loaded from character card")
    
    conversation = instance.get_agent("conversation")
    creator = instance.get_agent("creator")
    memory = instance.get_agent("memory")
    director = instance.get_agent("director")
    
    # Determine scene name according to spec
    scene_name = _extract_scene_name_from_spec(raw_data_or_metadata)
    first_character = characters[0]
    
    # Set scene name: use spec's name field if available, otherwise use first character name
    scene.name = scene_name if scene_name else first_character.name
    
    # Initialize memory and load character book entries (only once, for first character)
    await _initialize_scene_memory(
        scene,
        memory,
        character_book_data,
        loading_status,
        import_character_book=import_options.import_character_book,
        import_character_book_meta=import_options.import_character_book_meta,
    )
    
    # Determine character context (only for first character)
    await _determine_character_context(scene, first_character, creator, loading_status)
    
    # Add all characters as actors
    for character in characters:
        actor = Actor(character, conversation)
        await scene.add_actor(actor)
        
        log.debug(
            "load_scene_from_character_card",
            scene=scene,
            character=character,
            content_context=scene.context,
        )
        
        # Determine character description
        await _determine_character_description(
            character,
            creator,
            loading_status,
            card_description=card_description,
            greeting_texts=all_greeting_texts,
        )
        
        # Determine character attributes
        await _determine_character_attributes(character, creator, loading_status)
        
        # Activate character
        await activate_character(scene, character)
        
        # Assign TTS voice to character
        await director.assign_voice_to_character(character)
    
    # Set scene description from card description (not character description)
    scene.description = card_description
    
    # Set intro from original greeting text (not modified)
    scene.intro = original_greeting_text
    
    # Parse greeting text for characters speaking (format: {name}:)
    # and activate them if they exist in the scene
    speaking_characters = _parse_characters_from_greeting_text(original_greeting_text)
    for char_name in speaking_characters:
        existing_character = scene.get_character(char_name)
        if existing_character:
            await activate_character(scene, existing_character)
            log.debug(
                "load_scene_from_character_card",
                activated_from_greeting=char_name,
            )
    
    # Set intro_versions from alternate_greetings if present and flag is enabled
    if import_options.import_alternate_greetings and alternate_greetings:
        scene.intro_versions = alternate_greetings
    
    # Set up character assets (use first character for cover image)
    await _setup_character_assets(scene, characters[0], file_path, is_image)
    
    # Generate story intent
    await _generate_story_intent(scene, loading_status)
    
    # Save scene files
    await _save_scene_files(scene)
    
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
