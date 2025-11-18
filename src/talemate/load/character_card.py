import enum
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import pydantic
import structlog

import talemate.instance as instance
from talemate import Actor, Character, Player
from talemate.character import activate_character
from talemate.exceptions import UnknownDataSpec
from talemate.status import LoadingStatus
from talemate.config import get_config
from talemate.util import extract_metadata, select_best_texts_by_keyword, count_tokens
from talemate.agents.base import DynamicInstruction
from talemate.game.engine.nodes.registry import import_scene_node_definitions
from talemate.scene_assets import (
    AssetTransfer,
    set_scene_cover_image,
    set_character_cover_image,
)
from talemate.world_state import ManualContext
from talemate.agents.visual.schema import VIS_TYPE
from talemate.shared_context import SharedContext

log = structlog.get_logger("talemate.load.character_card")


class RelevantCharacterInfo(pydantic.BaseModel):
    """Schema for relevant character information organized as dynamic instructions."""

    scene: DynamicInstruction | None = None  # Greeting text
    scenario: DynamicInstruction | None = None  # Card description
    character_info: DynamicInstruction | None = None  # Character book entries

    def to_dynamic_instructions(
        self,
        scenario: bool = True,
        character_info: bool = True,
        scene: bool = True,
    ) -> list[DynamicInstruction]:
        """Convert to list of dynamic instructions, filtering out None values.

        Args:
            scenario: Whether to include the scenario instruction
            character_info: Whether to include the character info instruction
            scene: Whether to include the scene instruction
        """
        instructions = []
        if self.scenario and scenario:
            instructions.append(self.scenario)
        if self.character_info and character_info:
            instructions.append(self.character_info)
        if self.scene and scene:
            instructions.append(self.scene)
        return instructions


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


class PlayerCharacterTemplate(pydantic.BaseModel):
    """Template for player character (name and description)."""

    name: str
    description: str = ""


class PlayerCharacterImport(pydantic.BaseModel):
    """Import player character from another scene."""

    scene_path: str
    name: str


class CharacterCardImportOptions(pydantic.BaseModel):
    """Options for importing a character card."""

    import_all_characters: bool = False
    import_character_book: bool = True
    import_character_book_meta: bool = True
    import_alternate_greetings: bool = True
    generate_episode_titles: bool = True
    setup_shared_context: bool = False
    selected_character_names: list[str] = pydantic.Field(default_factory=list)

    # Player character options (mutually exclusive)
    player_character_template: PlayerCharacterTemplate | None = None
    player_character_existing: str | None = None  # detected character name
    player_character_import: PlayerCharacterImport | None = None

    # Internal: track pending asset transfers (deferred until scene name is set)
    _pending_asset_transfers: list[AssetTransfer] = pydantic.PrivateAttr(
        default_factory=list
    )

    @pydantic.model_validator(mode="after")
    def validate_player_character_options(self):
        """Ensure only one player character option is set."""
        options_set = [
            self.player_character_template is not None,
            self.player_character_existing is not None,
            self.player_character_import is not None,
        ]
        if sum(options_set) > 1:
            raise ValueError("Only one player character option can be set at a time")
        return self


class CharacterCardAnalysis(pydantic.BaseModel):
    """Analysis results for a character card."""

    spec_version: str
    character_book_entry_count: int = 0
    alternate_greetings_count: int = 0
    detected_character_names: list[str] = pydantic.Field(default_factory=list)
    card_name: str | None = None


class ImportSpec(str, enum.Enum):
    talemate = "talemate"
    talemate_complete = "talemate_complete"
    chara_card_v0 = "chara_card_v0"
    chara_card_v2 = "chara_card_v2"
    chara_card_v1 = "chara_card_v1"
    chara_card_v3 = "chara_card_v3"


def identify_import_spec(data: dict) -> ImportSpec:
    """
    Identify the import spec from character card data.

    Args:
        data: Character card data dictionary

    Raises:
        ValueError: If data is not a dictionary or is invalid
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid character card data format: expected dictionary, got {type(data).__name__}. "
            f"The file may not contain valid character card metadata."
        )

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


def _setup_loading_status(
    num_characters: int = 1,
    has_character_book: bool = False,
    num_episodes: int = 0,
    generate_episode_titles: bool = False,
) -> LoadingStatus:
    """Set up and return loading status tracker.

    Args:
        num_characters: Number of characters being imported
        has_character_book: Whether character book entries will be loaded
        num_episodes: Number of episodes that will be added
        generate_episode_titles: Whether episode titles will be generated
    """
    director = instance.get_agent("director")
    # Base steps:
    # 1. Loading character card
    # 2. Initializing long-term memory
    # 3. Loading character book entries (conditional)
    # 4. Determine character context (first character only)
    # 5. Determine description (per character)
    # 6. Determine character attributes (per character)
    # 7. Determine dialogue examples (per character)
    # 8. Generating story intent
    # 9. Generating scene types (if auto_direct)
    # 10. Setting scene intent (if auto_direct)
    # 11. Generating episode titles (one per episode if enabled)
    loading_steps = 4  # Base: card, memory, context, story intent
    if has_character_book:
        loading_steps += 1  # Character book entries
    loading_steps += (
        num_characters * 3
    )  # Description + attributes + dialogue examples per character
    if director.auto_direct_enabled:
        loading_steps += 2  # Scene types + scene intent
    if generate_episode_titles and num_episodes > 0:
        loading_steps += num_episodes  # One step per episode title generation
    loading_status = LoadingStatus(loading_steps, cancellable=True)
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

        # Validate metadata before processing
        if not isinstance(metadata, dict):
            raise ValueError(
                f"Invalid character card: The image file does not contain valid character card metadata. "
                f"Expected dictionary data, got {type(metadata).__name__}. "
                f"The file may not be a valid character card image."
            )

        raw_data_or_metadata = metadata
        spec = identify_import_spec(metadata)
        if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
            character_book_data = metadata.get("data", {}).get("character_book")
            alternate_greetings = metadata.get("data", {}).get(
                "alternate_greetings", []
            )
        character = load_character_from_image(file_path, image_format)
        is_image = True

    return (
        character,
        character_book_data,
        alternate_greetings,
        is_image,
        raw_data_or_metadata,
    )


async def analyze_character_card(file_path: str) -> CharacterCardAnalysis:
    """
    Analyze a character card file and return analysis information.

    Args:
        file_path: Path to the character card file (JSON or image)

    Returns:
        CharacterCardAnalysis with detected information

    Raises:
        ValueError: If the character card spec cannot be parsed or is invalid
    """
    file_ext = os.path.splitext(file_path)[1].lower()

    # Extract character data from file
    try:
        character, character_book_data, alternate_greetings, _, raw_data_or_metadata = (
            _extract_character_data_from_file(file_path, file_ext)
        )
    except ValueError:
        # Re-raise ValueError as-is (these are already user-friendly messages)
        raise
    except UnknownDataSpec as e:
        raise ValueError(
            "Invalid character card: Unable to identify the character card format. "
            "The file may not be a valid character card or may be using an unsupported format."
        ) from e
    except json.JSONDecodeError as e:
        raise ValueError(
            "Invalid character card: Failed to parse JSON data. "
            "The file may be corrupted or not a valid JSON character card."
        ) from e
    except FileNotFoundError as e:
        raise ValueError(
            "Invalid character card: File not found. "
            "The file path may be incorrect or the file may have been moved."
        ) from e
    except Exception as e:
        # Catch any other parsing errors and provide a clear message
        error_msg = str(e)
        if (
            "'bool' object has no attribute 'get'" in error_msg
            or "'NoneType' object has no attribute 'get'" in error_msg
        ):
            raise ValueError(
                "Invalid character card: The file does not contain valid character card metadata. "
                "The file may not be a character card or may be corrupted."
            ) from e
        raise ValueError(
            f"Invalid character card: Failed to parse character card data during analysis. "
            f"{error_msg}"
        ) from e

    # Determine spec version
    spec = (
        identify_import_spec(raw_data_or_metadata)
        if raw_data_or_metadata
        else ImportSpec.talemate
    )
    spec_version = spec.value

    # Count character book entries
    character_book_entry_count = 0
    if character_book_data:
        if isinstance(character_book_data, dict):
            entries = character_book_data.get("entries", [])
            if isinstance(entries, list):
                character_book_entry_count = len(entries)
        elif isinstance(character_book_data, CharacterBook):
            character_book_entry_count = len(character_book_data.entries)

    # Count alternate greetings
    alternate_greetings_count = len(alternate_greetings) if alternate_greetings else 0

    # Detect character names from greeting texts
    all_texts = [character.greeting_text]
    if alternate_greetings:
        all_texts.extend(alternate_greetings)

    # Detect characters from texts
    detected_character_names = []
    try:
        director = instance.get_agent("director")
        if director:
            detected_character_names = await director.detect_characters_from_texts(
                texts=all_texts
            )
    except Exception as e:
        log.warning("Failed to detect characters from texts", error=str(e))

    # If no characters detected, use the character name from the card
    if not detected_character_names:
        detected_character_names = [character.name] if character.name else []

    # Extract card name from spec or character name
    card_name = None
    if raw_data_or_metadata:
        scene_name = _extract_scene_name_from_spec(raw_data_or_metadata)
        if scene_name:
            card_name = scene_name
        elif character.name:
            card_name = character.name

    return CharacterCardAnalysis(
        spec_version=spec_version,
        character_book_entry_count=character_book_entry_count,
        alternate_greetings_count=alternate_greetings_count,
        detected_character_names=detected_character_names,
        card_name=card_name,
    )


async def _initialize_scene_memory(
    scene,
    character_book_data: dict | None,
    loading_status: LoadingStatus,
    import_character_book: bool = True,
    import_character_book_meta: bool = True,
) -> None:
    """Initialize memory and load character book entries if present."""
    loading_status("Initializing long-term memory...")
    memory = instance.get_agent("memory")
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

    await scene.world_state.commit_to_memory(memory)


async def _determine_character_context(
    scene, character, loading_status: LoadingStatus
) -> None:
    """Determine and set character content context."""
    loading_status("Determine character context...")

    if not scene.context:
        try:
            creator = instance.get_agent("creator")
            scene.context = await creator.determine_content_context_for_character(
                character
            )
            log.debug("content_context", content_context=scene.context)
        except Exception as e:
            log.error("determine_content_context_for_character", error=e)


def _relevant_character_info(
    character,
    card_description: str = "",
    greeting_texts: list[str] | None = None,
    scene=None,
) -> RelevantCharacterInfo:
    """
    Collect relevant character information: card_description + N world entries + 1 greeting text.

    Returns a RelevantCharacterInfo schema with DynamicInstruction objects for:
    - scene: greeting text
    - scenario: card description
    - character_info: character book entries
    """
    creator = instance.get_agent("creator")
    # Select best greeting text (single best one)
    greeting_text = ""
    if greeting_texts:
        if len(greeting_texts) > 1:
            selected_texts = select_best_texts_by_keyword(
                greeting_texts,
                character.name,
                creator.client.max_token_length,
                chunk_size_ratio=1.0,
            )
            greeting_text = selected_texts[0] if selected_texts else greeting_texts[0]
        else:
            greeting_text = greeting_texts[0]

    # Get character book entries from scene if available
    character_book_texts = []
    if scene and scene.world_state:
        for entry_id, entry in scene.world_state.manual_context.items():
            if entry.meta.get("source") == "imported" and entry.text:
                character_book_texts.append(entry.text)

    # Calculate token budget (80% of max tokens)
    max_token_length = creator.client.max_token_length
    total_budget = int(max_token_length * 0.8)

    used_tokens = count_tokens(card_description) + count_tokens(greeting_text)
    available_tokens = max(0, total_budget - used_tokens)

    # Select best character book entries that fit within remaining budget
    selected_book_texts = []
    if character_book_texts and available_tokens > 0:
        # Score and sort entries by keyword occurrence
        scored_texts = select_best_texts_by_keyword(
            character_book_texts,
            character.name,
            available_tokens,
            chunk_size_ratio=1.0,
        )
        # Add entries until we run out of tokens
        for text in scored_texts:
            if available_tokens > 0:
                selected_book_texts.append(text)
                available_tokens -= count_tokens(text)
            else:
                break

    # Build DynamicInstruction objects
    scene_instruction = (
        DynamicInstruction(title="SCENE", content=greeting_text)
        if greeting_text
        else None
    )
    scenario_instruction = (
        DynamicInstruction(title="SCENARIO", content=card_description)
        if card_description
        else None
    )
    character_info_instruction = (
        DynamicInstruction(
            title="CHARACTER INFO", content="\n\n".join(selected_book_texts)
        )
        if selected_book_texts
        else None
    )

    return RelevantCharacterInfo(
        scene=scene_instruction,
        scenario=scenario_instruction,
        character_info=character_info_instruction,
    )


async def _determine_character_description(
    character,
    loading_status: LoadingStatus,
    relevant_info: RelevantCharacterInfo,
) -> None:
    """Determine and set character description."""
    loading_status(f"Determine description for {character.name}...")

    try:
        creator = instance.get_agent("creator")
        dynamic_instructions = relevant_info.to_dynamic_instructions(scenario=False)

        log.warning("dynamic_instructions", relevant_info=relevant_info)

        # needs to be empty here.
        character.description = ""

        character.description = await creator.determine_character_description(
            character,
            text=relevant_info.scenario.content if relevant_info.scenario else "",
            dynamic_instructions=dynamic_instructions,
        )
        log.debug(
            "character_description",
            character=character.name,
            description=character.description,
        )
    except Exception as e:
        log.warning("determine_character_description", error=e)


async def _determine_character_attributes(
    character,
    loading_status: LoadingStatus,
    relevant_info: RelevantCharacterInfo,
) -> None:
    """Determine and set character attributes and dialogue instructions."""
    loading_status("Determine character attributes...")

    try:
        world_state = instance.get_agent("world_state")
        creator = instance.get_agent("creator")
        character.base_attributes = await world_state.extract_character_sheet(
            name=character.name,
            dynamic_instructions=relevant_info.to_dynamic_instructions(scenario=False),
        )

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


async def _determine_character_dialogue_examples(
    character,
    loading_status: LoadingStatus,
    relevant_info: RelevantCharacterInfo,
    original_dialogue_examples_text: str = "",
    max_examples: int = 5,
) -> None:
    """Determine and set character dialogue examples from text.

    Args:
        character: The character to determine dialogue examples for
        loading_status: Loading status tracker for progress updates
        relevant_info: Relevant character information
        original_dialogue_examples_text: Original dialogue examples text from character card
        max_examples: Maximum number of dialogue examples to generate (default: 5)
    """
    loading_status(f"Determine dialogue examples for {character.name}...")

    try:
        creator = instance.get_agent("creator")

        # Only pass the original dialogue examples text
        # The relevant_info is already included via dynamic_instructions
        text = (
            original_dialogue_examples_text if original_dialogue_examples_text else ""
        )

        # Extract dialogue examples using the creator agent
        character.example_dialogue = (
            await creator.determine_character_dialogue_examples(
                character,
                text=text,
                dynamic_instructions=relevant_info.to_dynamic_instructions(
                    scenario=False
                ),
                max_examples=max_examples,
            )
        )

        log.debug(
            "determine_character_dialogue_examples",
            character=character.name,
            count=len(character.example_dialogue),
            examples=character.example_dialogue,
        )
    except Exception as e:
        log.warning("determine_character_dialogue_examples", error=e)


async def _setup_character_assets(
    scene, character, file_path: str, is_image: bool
) -> None:
    """Set up character and scene cover images if loading from image."""
    if is_image:
        asset = scene.assets.add_asset_from_file_path(file_path)
        asset.meta.vis_type = VIS_TYPE.CHARACTER_CARD
        asset.meta.character_name = character.name
        scene.assets.save_library()
        await set_scene_cover_image(scene, asset.id)
        await set_character_cover_image(scene, character, asset.id)


async def _generate_story_intent(scene, loading_status: LoadingStatus) -> None:
    """Generate story intent and scene types if auto-direct is enabled."""
    try:
        loading_status("Generating story intent...")
        creator = instance.get_agent("creator")
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


async def _process_pending_asset_transfers(
    scene, import_options: CharacterCardImportOptions
) -> None:
    """
    Process pending asset transfers for imported characters.

    This is called after the scene is saved and project_name is set,
    ensuring the asset directory is correctly resolved.
    """
    if not import_options._pending_asset_transfers:
        return

    for transfer in import_options._pending_asset_transfers:
        # Transfer the asset (this handles loading scene data)
        # The character's cover_image is already set, we just need to transfer the asset file
        await scene.assets.transfer_asset(transfer)


async def _setup_shared_context_for_import(
    scene,
    characters: list[Character],
    character_book_data: dict | None,
    import_options: CharacterCardImportOptions,
) -> None:
    """
    Setup shared context for character card import.

    Marks imported characters and world entries as shared, then creates
    a shared context file (world.json) and links it to the scene.

    Args:
        scene: The scene to setup shared context for
        characters: List of characters that were imported
        character_book_data: Character book data if present
        import_options: Import options containing flags for what was imported
    """
    # Mark all imported characters as shared
    for character in characters:
        await character.set_shared(True)

    # Mark player character as shared (may already be in characters list, but ensure it's marked)
    player_character = scene.get_player_character()
    if player_character:
        await player_character.set_shared(True)

    # Mark all imported world entries (character book entries) as shared
    if character_book_data and import_options.import_character_book:
        for entry_id in scene.world_state.manual_context.keys():
            entry = scene.world_state.manual_context[entry_id]
            # Only mark entries that came from character book import
            if entry.meta.get("source") == "imported":
                entry.shared = True

    # Create shared context file
    shared_dir = Path(scene.shared_context_dir)
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared_context_path = shared_dir / "world.json"

    # If world.json already exists, create a unique name
    if shared_context_path.exists():
        shared_context_path = shared_dir / f"world-{uuid.uuid4().hex[:8]}.json"

    shared_context = SharedContext(filepath=shared_context_path)
    await shared_context.init_from_scene(scene, write=True)
    scene.shared_context = shared_context
    log.info(
        "Created shared context for character card import",
        filepath=str(shared_context_path),
        characters=len(characters),
    )


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


def _parse_characters_from_greeting_text(greeting_text: str, scene) -> list[str]:
    """
    Parse character names from greeting text using name: pattern.

    Args:
        greeting_text: The greeting text to parse
        scene: Scene object to check for character matches

    Returns:
        List of character names found in the greeting text
    """
    # Pattern to match name: format (not {name}:)
    pattern = r"([^:\n]+):"
    matches = re.findall(pattern, greeting_text)
    potential_names = [name.strip() for name in matches if name.strip()]

    character_names = []

    npc_characters = list(scene.get_npc_characters())
    all_characters = list(scene.all_characters)

    # Validate matches against actual characters in the scene
    for name in potential_names:
        for character in all_characters:
            if character.name.lower() == name.lower():
                if character.name not in character_names:
                    character_names.append(character.name)
                break

    # If no characters detected, look for partial name matches in the text
    if not character_names:
        for character in npc_characters:
            # Check if character name appears anywhere in the text (case-insensitive)
            if character.name.lower() in greeting_text.lower():
                if character.name not in character_names:
                    character_names.append(character.name)

    # If still no characters detected, activate up to 2 NPCs (order doesn't matter)
    if not character_names:
        for character in npc_characters[:2]:
            character_names.append(character.name)

    return character_names


async def _add_episode(
    scene,
    greeting: str,
    loading_status: LoadingStatus,
    generate_title: bool = True,
) -> None:
    """Add an episode with optional AI-generated title.

    Args:
        scene: The scene to add the episode to
        greeting: The episode intro text
        loading_status: Loading status tracker for progress updates
        generate_title: Whether to generate a title using AI
    """
    title = None
    if generate_title:
        loading_status("Generating title for episode...")
        try:
            creator = instance.get_agent("creator")
            title = await creator.generate_title(greeting)
            # Strip whitespace and ensure it's not empty
            if title:
                title = title.strip()
            if not title:
                title = None
        except Exception as e:
            log.warning("Failed to generate episode title", error=str(e))
    scene.episodes.add_episode(intro=greeting, title=title)


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

    # Import here to avoid circular import
    from talemate.load import handle_no_player_character, transfer_character

    if import_options is None:
        import_options = CharacterCardImportOptions()

    file_ext = os.path.splitext(file_path)[1].lower()

    # Handle player character setup based on import options
    # This replaces the default handle_no_player_character call
    player_character_setup = False

    if import_options.player_character_template:
        # Create player character from template
        template = import_options.player_character_template
        config = get_config()

        # If config doesn't have a default character set up, update it with template values
        if not config.game.default_player_character.name:
            config.game.default_player_character.name = template.name
            config.game.default_player_character.description = (
                template.description or ""
            )
            await config.set_dirty()
            log.info(
                "Updated default player character config",
                name=template.name,
            )

        # Use color from config (schema default is "#3362bb")
        player_color = config.game.default_player_character.color

        player = Player(
            Character(
                name=template.name,
                description=template.description or "",
                greeting_text="",
                color=player_color,
            ),
            None,
        )
        await scene.add_actor(player)
        await activate_character(scene, player.character)
        player_character_setup = True
    elif import_options.player_character_existing:
        # Use one of the detected characters as player
        # This will be handled after characters are created
        player_character_setup = True
    elif import_options.player_character_import:
        # Import player character from another scene
        import_data = import_options.player_character_import
        # Transfer character but defer asset transfer until scene name is set
        await transfer_character(
            scene, import_data.scene_path, import_data.name, defer_asset_transfer=True
        )
        # Mark the imported character as player
        imported_char = scene.get_character(import_data.name)
        if imported_char:
            imported_char.is_player = True
            await activate_character(scene, imported_char)
            # Store pending asset transfer info if character has cover image
            if imported_char.cover_image:
                import_options._pending_asset_transfers.append(
                    AssetTransfer(
                        source_scene_path=import_data.scene_path,
                        asset_id=imported_char.cover_image,
                    )
                )
        player_character_setup = True

    # If no player character option was provided, use default behavior
    if not player_character_setup:
        await handle_no_player_character(scene)

    # Extract character data from file
    (
        original_character,
        character_book_data,
        alternate_greetings,
        is_image,
        raw_data_or_metadata,
    ) = _extract_character_data_from_file(file_path, file_ext)

    # Store original greeting text - this will be used for scene setup
    original_greeting_text = original_character.greeting_text

    # Store original card description - this will be used for scene description
    card_description = original_character.description

    # Extract original dialogue examples text from raw_data_or_metadata
    original_dialogue_examples_text = ""
    if raw_data_or_metadata:
        spec = identify_import_spec(raw_data_or_metadata)
        if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
            data_section = raw_data_or_metadata.get("data", {})
            if "mes_example" in data_section:
                original_dialogue_examples_text = data_section["mes_example"]
        elif spec == ImportSpec.chara_card_v0 or spec == ImportSpec.chara_card_v1:
            if "mes_example" in raw_data_or_metadata:
                original_dialogue_examples_text = raw_data_or_metadata["mes_example"]

    # Collect all greeting texts for character description determination
    all_greeting_texts = [original_greeting_text]
    if alternate_greetings:
        all_greeting_texts.extend(alternate_greetings)

    # Get selected character names from import options
    # If none provided, use the original character name as fallback
    selected_names = import_options.selected_character_names
    if not selected_names:
        selected_names = [original_character.name] if original_character.name else []

    # Guard: ensure we have at least one character name
    if not selected_names:
        raise ValueError("No character names provided in import options")

    # Create characters from selected names
    characters = []
    for char_name in selected_names:
        if char_name == original_character.name:
            # Use original character if name matches
            characters.append(original_character)
        else:
            # Create a copy of the original character with the new name
            # Note: example_dialogue will be regenerated later, so we don't copy it
            new_character = Character(
                name=char_name,
                description=original_character.description,
                greeting_text=original_character.greeting_text,
                color=original_character.color,
                is_player=original_character.is_player,
                dialogue_instructions=original_character.dialogue_instructions,
                example_dialogue=[],  # Will be regenerated
                base_attributes=original_character.base_attributes.copy(),
                details=original_character.details.copy(),
            )
            characters.append(new_character)

    # Set up loading status with accurate step count based on number of characters
    has_character_book = (
        character_book_data is not None and import_options.import_character_book
    )
    num_episodes = 0
    if import_options.import_alternate_greetings and alternate_greetings:
        num_episodes = len(alternate_greetings)
    loading_status = _setup_loading_status(
        num_characters=len(characters),
        has_character_book=has_character_book,
        num_episodes=num_episodes,
        generate_episode_titles=import_options.generate_episode_titles,
    )

    conversation = instance.get_agent("conversation")
    director = instance.get_agent("director")

    # Determine scene name according to spec
    scene_name = _extract_scene_name_from_spec(raw_data_or_metadata)
    first_character = characters[0]

    # Set scene name: use spec's name field if available, otherwise use first character name
    scene.name = scene_name if scene_name else first_character.name

    # Initialize memory and load character book entries (only once, for first character)
    await _initialize_scene_memory(
        scene,
        character_book_data,
        loading_status,
        import_character_book=import_options.import_character_book,
        import_character_book_meta=import_options.import_character_book_meta,
    )

    # Determine character context (only for first character)
    await _determine_character_context(scene, first_character, loading_status)

    # Handle player_character_existing option - mark selected character as player
    if import_options.player_character_existing:
        player_char_name = import_options.player_character_existing
        # Find the character in the characters list and mark as player
        for character in characters:
            if character.name == player_char_name:
                character.is_player = True
                break

    # Add all characters as actors
    for character in characters:
        # If this character is marked as player, create Player actor instead of Actor
        if character.is_player and import_options.player_character_existing:
            actor = Player(character, None)
        else:
            actor = Actor(character, conversation)
        await scene.add_actor(actor)

        log.debug(
            "load_scene_from_character_card",
            scene=scene,
            character=character,
            content_context=scene.context,
        )

        # gather relevant character info
        relevant_info = _relevant_character_info(
            character, character.description, all_greeting_texts, scene
        )

        # Determine character description
        await _determine_character_description(
            character,
            loading_status,
            relevant_info=relevant_info,
        )

        # Determine character attributes
        await _determine_character_attributes(
            character, loading_status, relevant_info=relevant_info
        )

        # Determine character dialogue examples
        # Clear existing examples that were directly copied, we'll regenerate them properly
        character.example_dialogue = []
        await _determine_character_dialogue_examples(
            character,
            loading_status,
            relevant_info=relevant_info,
            original_dialogue_examples_text=original_dialogue_examples_text,
        )

        # Activate character
        if character.is_player:
            await activate_character(scene, character)

        # Assign TTS voice to character
        await director.assign_voice_to_character(character)

    # Set scene description from card description (not character description)
    scene.description = card_description

    # Set intro from original greeting text (not modified)
    scene.intro = original_greeting_text

    # Parse greeting text for characters speaking (format: name:)
    # and activate them if they exist in the scene
    speaking_characters = _parse_characters_from_greeting_text(
        original_greeting_text, scene
    )
    for char_name in speaking_characters:
        existing_character = scene.get_character(char_name)
        if existing_character:
            await activate_character(scene, existing_character)
            log.debug(
                "load_scene_from_character_card",
                activated_from_greeting=char_name,
            )

    # Add alternate_greetings as episodes if present and flag is enabled
    if import_options.import_alternate_greetings and alternate_greetings:
        for greeting in alternate_greetings:
            await _add_episode(
                scene,
                greeting,
                loading_status,
                generate_title=import_options.generate_episode_titles,
            )

    # Set up character assets (use first character for cover image)
    await _setup_character_assets(scene, characters[0], file_path, is_image)

    # Generate story intent
    await _generate_story_intent(scene, loading_status)

    # Process pending asset transfers now that scene name/project_name is set
    # (similar to how _setup_character_assets works - it's called after scene name is set)
    await _process_pending_asset_transfers(scene, import_options)

    # Setup shared context if requested (before saving files)
    if import_options.setup_shared_context:
        await _setup_shared_context_for_import(
            scene, characters, character_book_data, import_options
        )

    # Save scene files (after shared context setup so changes are persisted)
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
