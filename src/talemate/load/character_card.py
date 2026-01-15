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
from talemate import Character, Player
from talemate.character import activate_character
from talemate.exceptions import UnknownDataSpec
from talemate.status import LoadingStatus
from talemate.config import get_config
from talemate.util import extract_metadata, select_best_texts_by_keyword, count_tokens
from talemate.util.colors import unique_random_colors
from talemate.agents.base import DynamicInstruction
from talemate.game.engine.nodes.registry import import_scene_node_definitions
from talemate.scene_assets import AssetTransfer
from talemate.world_state import ManualContext
from talemate.agents.visual.schema import VIS_TYPE
from talemate.shared_context import SharedContext

log = structlog.get_logger("talemate.load.character_card")

__all__ = [
    # Classes
    "RelevantCharacterInfo",
    "CharacterBookEntry",
    "CharacterBook",
    "CharacterBookMeta",
    "PlayerCharacterTemplate",
    "PlayerCharacterImport",
    "CharacterCardImportOptions",
    "CharacterCardAnalysis",
    "ImportSpec",
    # Functions
    "identify_import_spec",
    "analyze_character_card",
    "load_scene_from_character_card",
    "load_character_from_image",
    "load_character_from_json",
    "character_from_chara_data",
    "load_from_image_metadata",
    "create_manual_context_from_character_book",
]


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
    use_asset_as_reference: bool = True
    selected_character_names: list[str] = pydantic.Field(default_factory=list)

    # Player character options (mutually exclusive)
    player_character_template: PlayerCharacterTemplate | None = None
    player_character_existing: str | None = None  # detected character name
    player_character_import: PlayerCharacterImport | None = None

    # Scene settings
    writing_style_template: str | None = None  # Format: "group__template_uid"

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
    icon_asset_data_url: str | None = None


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
        loading_steps += 1
    loading_steps += (
        num_characters * 3
    )  # Description + attributes + dialogue examples per character
    if director.auto_direct_enabled:
        loading_steps += 2
    if generate_episode_titles and num_episodes > 0:
        loading_steps += num_episodes
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

    spec = (
        identify_import_spec(raw_data_or_metadata)
        if raw_data_or_metadata
        else ImportSpec.talemate
    )
    spec_version = spec.value

    character_book_entry_count = 0
    if character_book_data:
        if isinstance(character_book_data, dict):
            entries = character_book_data.get("entries", [])
            if isinstance(entries, list):
                character_book_entry_count = len(entries)
        elif isinstance(character_book_data, CharacterBook):
            character_book_entry_count = len(character_book_data.entries)

    alternate_greetings_count = len(alternate_greetings) if alternate_greetings else 0

    all_texts = [character.greeting_text]
    if alternate_greetings:
        all_texts.extend(alternate_greetings)

    detected_character_names = []
    try:
        director = instance.get_agent("director")
        if director:
            detected_character_names = await director.detect_characters_from_texts(
                texts=all_texts
            )
    except Exception as e:
        log.warning("Failed to detect characters from texts", error=str(e))

    if not detected_character_names:
        detected_character_names = [character.name] if character.name else []

    card_name = None
    if raw_data_or_metadata:
        scene_name = _extract_scene_name_from_spec(raw_data_or_metadata)
        if scene_name:
            card_name = scene_name
        elif character.name:
            card_name = character.name

    # Extract icon asset data URL for preview (JSON cards)
    # PNG cards will use the file itself as preview via request_file_image_data
    icon_asset_data_url = None
    try:
        icon_asset_data_url = _extract_icon_asset_from_character_card(
            raw_data_or_metadata
        )
        log.debug(
            "icon_asset_data_url",
            icon_asset_data_url_found=(icon_asset_data_url is not None),
        )
    except Exception as e:
        log.debug(
            "extract_icon_preview_failed",
            error=str(e),
            msg="Failed to extract icon asset preview, continuing without preview",
        )

    return CharacterCardAnalysis(
        spec_version=spec_version,
        character_book_entry_count=character_book_entry_count,
        alternate_greetings_count=alternate_greetings_count,
        detected_character_names=detected_character_names,
        card_name=card_name,
        icon_asset_data_url=icon_asset_data_url,
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

    selected_book_texts = []
    if character_book_texts and available_tokens > 0:
        scored_texts = select_best_texts_by_keyword(
            character_book_texts,
            character.name,
            available_tokens,
            chunk_size_ratio=1.0,
        )
        for text in scored_texts:
            if available_tokens > 0:
                selected_book_texts.append(text)
                available_tokens -= count_tokens(text)
            else:
                break

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


def _extract_icon_asset_from_character_card(
    raw_data_or_metadata: dict | None,
) -> str | None:
    """
    Extract the icon-type asset that is a data URL from character card data.
    Prefers the "main" icon if present, otherwise uses the first icon found.

    Works with character cards loaded from:
    - PNG files with ccv3 chunk (v3 spec)
    - PNG files with chara chunk (v2/v1/v0 spec)
    - JSON files (v3/v2/v1/v0 spec)

    Note: The assets field is only present in v3 cards. For v2/v1/v0 cards,
    this function will return None, which is handled gracefully.

    Args:
        raw_data_or_metadata: Raw character card data (JSON dict or image metadata)
            This is the parsed structure returned by extract_metadata, which handles
            both ccv3 and chara chunks correctly.

    Returns:
        Data URL string of the icon asset found, or None if not found
    """
    if not raw_data_or_metadata or not isinstance(raw_data_or_metadata, dict):
        return None

    try:
        # Check if this is a v2/v3 card (has "data" field)
        # extract_metadata already handles ccv3 vs chara chunks and returns
        # the same structure regardless of source chunk type
        data_section = raw_data_or_metadata.get("data", {})
        if not data_section:
            # Might be v0/v1 format, check top level
            data_section = raw_data_or_metadata

        # Get assets array (v3 only - v2/v1/v0 don't have this field)
        assets = data_section.get("assets", [])
        if not assets or not isinstance(assets, list):
            return None

        # First, try to find the "main" icon asset
        main_icon_uri = None
        first_icon_uri = None

        for asset in assets:
            if not isinstance(asset, dict):
                continue

            asset_type = asset.get("type", "")
            asset_uri = asset.get("uri", "")
            asset_name = asset.get("name", "")

            # Check if it's an icon type and a data URL
            if (
                asset_type == "icon"
                and isinstance(asset_uri, str)
                and asset_uri.startswith("data:image/")
            ):
                # Prefer "main" icon
                if asset_name == "main":
                    main_icon_uri = asset_uri
                # Otherwise, remember the first icon found
                elif first_icon_uri is None:
                    first_icon_uri = asset_uri

        # Return main icon if found, otherwise first icon
        return main_icon_uri or first_icon_uri
    except Exception as e:
        log.warning(
            "extract_icon_asset_failed",
            error=str(e),
            msg="Failed to extract icon asset from character card",
        )
        return None


async def _setup_character_assets_from_icon_data_url(
    scene,
    character,
    raw_data_or_metadata: dict | None,
    use_asset_as_reference: bool = True,
) -> bool:
    """
    Set up character and scene cover images from icon asset data URL if present.

    Args:
        scene: The scene to set up assets for
        character: The character to set cover image for
        raw_data_or_metadata: Raw character card data
        use_asset_as_reference: Whether to mark the asset as usable for image generation reference

    Returns:
        True if an icon asset was found and set, False otherwise
    """
    try:
        icon_data_url = _extract_icon_asset_from_character_card(raw_data_or_metadata)
        if not icon_data_url:
            return False

        # Add asset from data URL
        asset = await scene.assets.add_asset_from_image_data(icon_data_url)
        asset.meta.vis_type = VIS_TYPE.CHARACTER_CARD
        asset.meta.character_name = character.name
        if use_asset_as_reference:
            asset.meta.reference = [
                VIS_TYPE.CHARACTER_PORTRAIT,
                VIS_TYPE.CHARACTER_CARD,
                VIS_TYPE.SCENE_CARD,
                VIS_TYPE.SCENE_ILLUSTRATION,
            ]
        scene.assets.save_library()

        # Set as cover images
        await scene.assets.set_scene_cover_image(asset.id)
        await scene.assets.set_character_cover_image(character, asset.id)

        log.info(
            "icon_asset_set",
            character_name=character.name,
            asset_id=asset.id,
            msg="Set character cover image from icon asset data URL",
        )
        return True
    except Exception as e:
        log.warning(
            "setup_icon_asset_failed",
            error=str(e),
            character_name=character.name if character else None,
            msg="Failed to set up icon asset from character card, continuing import",
        )
        return False


async def _setup_character_assets(
    scene,
    character,
    file_path: str,
    is_image: bool,
    use_asset_as_reference: bool = True,
) -> None:
    """Set up character and scene cover images if loading from image.

    Args:
        scene: The scene to set up assets for
        character: The character to set cover image for
        file_path: Path to the character card file
        is_image: Whether the file is an image
        use_asset_as_reference: Whether to mark the asset as usable for image generation reference
    """
    if is_image:
        asset = await scene.assets.add_asset_from_file_path(file_path)
        asset.meta.vis_type = VIS_TYPE.CHARACTER_CARD
        asset.meta.character_name = character.name
        if use_asset_as_reference:
            asset.meta.reference = [
                VIS_TYPE.CHARACTER_PORTRAIT,
                VIS_TYPE.CHARACTER_CARD,
                VIS_TYPE.SCENE_CARD,
                VIS_TYPE.SCENE_ILLUSTRATION,
            ]
        scene.assets.save_library()
        await scene.assets.set_scene_cover_image(asset.id)
        await scene.assets.set_character_cover_image(character, asset.id)


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
        scene.emit_scene_intent()
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
    for character in characters:
        await character.set_shared(True)

    player_character = scene.get_player_character()
    if player_character:
        await player_character.set_shared(True)

    if character_book_data and import_options.import_character_book:
        for entry_id in scene.world_state.manual_context.keys():
            entry = scene.world_state.manual_context[entry_id]
            # Only mark entries that came from character book import
            if entry.meta.get("source") == "imported":
                entry.shared = True

    shared_dir = Path(scene.shared_context_dir)
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared_context_path = shared_dir / "world.json"

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

    # Use character_data instead of actors - characters may not be activated yet
    all_characters = list(scene.character_data.values())
    npc_characters = [c for c in all_characters if not c.is_player]

    for name in potential_names:
        for character in all_characters:
            if character.name.lower() == name.lower():
                if character.name not in character_names:
                    character_names.append(character.name)
                break

    if not character_names:
        for character in npc_characters:
            if character.name.lower() in greeting_text.lower():
                if character.name not in character_names:
                    character_names.append(character.name)

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
            if title:
                title = title.strip()
            if not title:
                title = None
        except Exception as e:
            log.warning("Failed to generate episode title", error=str(e))
    scene.episodes.add_episode(intro=greeting, title=title)


async def _setup_player_character_from_options(
    scene,
    import_options: CharacterCardImportOptions,
) -> bool:
    """Setup player character based on import options.

    Args:
        scene: The scene to add the player character to
        import_options: Import options containing player character configuration

    Returns:
        True if player character was set up, False otherwise
    """
    from talemate.load import handle_no_player_character, transfer_character

    if import_options.player_character_template:
        template = import_options.player_character_template
        config = get_config()

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
        return True
    elif import_options.player_character_existing:
        return True
    elif import_options.player_character_import:
        import_data = import_options.player_character_import
        await transfer_character(
            scene, import_data.scene_path, import_data.name, defer_asset_transfer=True
        )
        imported_char = scene.get_character(import_data.name)
        if imported_char:
            imported_char.is_player = True
            await activate_character(scene, imported_char)
            # Queue asset transfers for cover_image and avatar assets
            for asset_id in [
                imported_char.cover_image,
                imported_char.avatar,
                imported_char.current_avatar,
            ]:
                if asset_id:
                    import_options._pending_asset_transfers.append(
                        AssetTransfer(
                            source_scene_path=import_data.scene_path,
                            asset_id=asset_id,
                        )
                    )
        return True

    await handle_no_player_character(scene)
    return False


def _extract_dialogue_examples_from_metadata(
    raw_data_or_metadata: dict | None,
) -> str:
    """Extract original dialogue examples text from character card metadata.

    Args:
        raw_data_or_metadata: Raw character card data or metadata

    Returns:
        Original dialogue examples text, empty string if not found
    """
    if not raw_data_or_metadata:
        return ""

    spec = identify_import_spec(raw_data_or_metadata)
    if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
        data_section = raw_data_or_metadata.get("data", {})
        if "mes_example" in data_section:
            return data_section["mes_example"]
    elif spec == ImportSpec.chara_card_v0 or spec == ImportSpec.chara_card_v1:
        if "mes_example" in raw_data_or_metadata:
            return raw_data_or_metadata["mes_example"]

    return ""


def _create_characters_from_names(
    selected_names: list[str],
    original_character: Character,
) -> list[Character]:
    """Create character objects from selected names, assigning unique colors.

    Args:
        selected_names: List of character names to create
        original_character: Original character to use as template

    Returns:
        List of Character objects
    """
    if not selected_names:
        raise ValueError("No character names provided")

    assigned_colors = unique_random_colors(len(selected_names))

    characters = []
    for idx, char_name in enumerate(selected_names):
        assigned_color = assigned_colors[idx]
        if char_name == original_character.name:
            original_character.color = assigned_color
            characters.append(original_character)
        else:
            new_character = Character(
                name=char_name,
                description=original_character.description,
                greeting_text=original_character.greeting_text,
                color=assigned_color,
                is_player=original_character.is_player,
                dialogue_instructions=original_character.dialogue_instructions,
                example_dialogue=[],
                base_attributes=original_character.base_attributes.copy(),
                details=original_character.details.copy(),
            )
            characters.append(new_character)

    return characters


async def _process_characters_for_import(
    scene,
    characters: list[Character],
    all_greeting_texts: list[str],
    original_dialogue_examples_text: str,
    loading_status: LoadingStatus,
    import_options: CharacterCardImportOptions,
) -> None:
    """Process each character: add actors and determine attributes.

    Args:
        scene: The scene to add characters to
        characters: List of characters to process
        all_greeting_texts: All greeting texts for character info gathering
        original_dialogue_examples_text: Original dialogue examples text
        loading_status: Loading status tracker
        import_options: Import options
    """
    director = instance.get_agent("director")

    for character in characters:
        # Add character to character_data without activating
        # Characters will be activated later by _activate_characters_from_greeting
        # based on whether they appear in the greeting text
        scene.character_data[character.name] = character

        log.debug(
            "load_scene_from_character_card",
            scene=scene,
            character=character,
            content_context=scene.context,
        )

        relevant_info = _relevant_character_info(
            character, character.description, all_greeting_texts, scene
        )

        await _determine_character_description(
            character,
            loading_status,
            relevant_info=relevant_info,
        )

        await _determine_character_attributes(
            character, loading_status, relevant_info=relevant_info
        )

        character.example_dialogue = []
        await _determine_character_dialogue_examples(
            character,
            loading_status,
            relevant_info=relevant_info,
            original_dialogue_examples_text=original_dialogue_examples_text,
        )

        if character.is_player:
            await activate_character(scene, character)

        await director.assign_voice_to_character(character)


async def _activate_characters_from_greeting(
    scene,
    greeting_text: str,
) -> None:
    """Activate characters that appear in the greeting text.

    Args:
        scene: The scene containing the characters
        greeting_text: The greeting text to parse for character names
    """
    speaking_characters = _parse_characters_from_greeting_text(greeting_text, scene)
    for char_name in speaking_characters:
        existing_character = scene.get_character(char_name)
        if existing_character:
            await activate_character(scene, existing_character)
            log.debug(
                "load_scene_from_character_card",
                activated_from_greeting=char_name,
            )


async def _finalize_character_card_import(
    scene,
    characters: list[Character],
    character_book_data: dict | None,
    file_path: str,
    is_image: bool,
    loading_status: LoadingStatus,
    import_options: CharacterCardImportOptions,
    raw_data_or_metadata: dict | None = None,
) -> None:
    """Finalize the import: set up assets, generate intent, and save files.

    Args:
        scene: The scene being imported
        characters: List of imported characters
        character_book_data: Character book data if present
        file_path: Path to the character card file
        is_image: Whether the file is an image
        loading_status: Loading status tracker
        import_options: Import options
        raw_data_or_metadata: Raw character card data
    """
    # Try to set up icon asset from character card data first (takes priority)
    icon_asset_set = False
    if raw_data_or_metadata and characters:
        icon_asset_set = await _setup_character_assets_from_icon_data_url(
            scene,
            characters[0],
            raw_data_or_metadata,
            use_asset_as_reference=import_options.use_asset_as_reference,
        )

    # Fall back to file-based asset if no icon asset was found
    if not icon_asset_set:
        await _setup_character_assets(
            scene,
            characters[0],
            file_path,
            is_image,
            use_asset_as_reference=import_options.use_asset_as_reference,
        )

    await _generate_story_intent(scene, loading_status)
    await _process_pending_asset_transfers(scene, import_options)

    if import_options.setup_shared_context:
        await _setup_shared_context_for_import(
            scene, characters, character_book_data, import_options
        )

    await _save_scene_files(scene)


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

    # Setup and Initialization

    if import_options is None:
        import_options = CharacterCardImportOptions()

    file_ext = os.path.splitext(file_path)[1].lower()

    # Player Character Setup

    await _setup_player_character_from_options(scene, import_options)

    # Extract Character Data from File

    (
        original_character,
        character_book_data,
        alternate_greetings,
        is_image,
        raw_data_or_metadata,
    ) = _extract_character_data_from_file(file_path, file_ext)

    original_greeting_text = original_character.greeting_text
    card_description = original_character.description
    original_dialogue_examples_text = _extract_dialogue_examples_from_metadata(
        raw_data_or_metadata
    )

    all_greeting_texts = [original_greeting_text]
    if alternate_greetings:
        all_greeting_texts.extend(alternate_greetings)

    # Prepare Character Names and Create Character Objects

    selected_names = import_options.selected_character_names
    if not selected_names:
        selected_names = [original_character.name] if original_character.name else []

    characters = _create_characters_from_names(selected_names, original_character)

    # Initialize Loading Status and Scene Setup

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

    scene_name = _extract_scene_name_from_spec(raw_data_or_metadata)
    first_character = characters[0]

    scene.name = scene_name if scene_name else first_character.name

    if import_options.writing_style_template:
        scene.writing_style_template = import_options.writing_style_template

    # Initialize Memory and Character Context

    await _initialize_scene_memory(
        scene,
        character_book_data,
        loading_status,
        import_character_book=import_options.import_character_book,
        import_character_book_meta=import_options.import_character_book_meta,
    )

    await _determine_character_context(scene, first_character, loading_status)

    # Handle Player Character Existing Option

    if import_options.player_character_existing:
        player_char_name = import_options.player_character_existing
        for character in characters:
            if character.name == player_char_name:
                character.is_player = True
                break

    # Process Each Character: Add Actors and Determine Attributes

    await _process_characters_for_import(
        scene,
        characters,
        all_greeting_texts,
        original_dialogue_examples_text,
        loading_status,
        import_options,
    )

    # Set Scene Metadata

    scene.description = card_description
    scene.intro = original_greeting_text

    # Activate Characters from Greeting Text

    await _activate_characters_from_greeting(scene, original_greeting_text)

    # Add Alternate Greetings as Episodes

    if import_options.import_alternate_greetings and alternate_greetings:
        for greeting in alternate_greetings:
            await _add_episode(
                scene,
                greeting,
                loading_status,
                generate_title=import_options.generate_episode_titles,
            )

    # Finalize Import: Assets, Story Intent, and Save

    await _finalize_character_card_import(
        scene,
        characters,
        character_book_data,
        file_path,
        is_image,
        loading_status,
        import_options,
        raw_data_or_metadata=raw_data_or_metadata,
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

    if spec == ImportSpec.chara_card_v2 or spec == ImportSpec.chara_card_v3:
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

    if (
        metadata.get("spec") == "chara_card_v2"
        or metadata.get("spec") == "chara_card_v3"
    ):
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
