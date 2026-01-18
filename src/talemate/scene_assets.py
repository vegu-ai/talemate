from __future__ import annotations

import base64
import hashlib
import os
import enum
import io
import json
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pydantic
from PIL import Image

if TYPE_CHECKING:
    from talemate import Scene
    from talemate.character import Character
    from talemate.agents.visual.schema import GenerationResponse

import structlog

from talemate.emit import emit
import talemate.emit.async_signals as async_signals
from talemate.config import get_config, Config
import talemate.scene_message as scene_message
from talemate.agents.visual.schema import (
    VIS_TYPE,
    GEN_TYPE,
    FORMAT_TYPE,
    SamplerSettings,
    Resolution,
    AssetAttachmentContext,
)
from talemate.path import SCENES_DIR

async_signals.register("asset_saved")

__all__ = [
    "Asset",
    "AssetTransfer",
    "AssetSavedPayload",
    "SceneAssets",
    "AssetMeta",
    "AssetSelectionContext",
    "CoverBBox",
    "TAG_MATCH_MODE",
    "validate_image_data_url",
    "get_media_type_from_file_path",
    "get_media_type_from_extension",
    "migrate_scene_assets_to_library",
]

log = structlog.get_logger("talemate.scene_assets")

VIS_TYPE_TO_ASSET_TYPE = {
    VIS_TYPE.CHARACTER_PORTRAIT: "avatar",
    VIS_TYPE.CHARACTER_CARD: "card",
    VIS_TYPE.SCENE_CARD: "card",
    VIS_TYPE.SCENE_BACKGROUND: "scene_illustration",
    VIS_TYPE.SCENE_ILLUSTRATION: "scene_illustration",
    VIS_TYPE.UNSPECIFIED: None,
}


def validate_image_data_url(image_data: str) -> None:
    """
    Validate that image_data is a properly formatted base64 data URL.

    Args:
        image_data: The image data URL string to validate

    Raises:
        ValueError: If the image_data format is invalid
    """
    try:
        media_type = image_data.split(";")[0].split(":")[1]
        base64_data = image_data.split(",", 1)[1]

        if not media_type.startswith("image/"):
            raise ValueError(
                f"Unsupported media type: {media_type}. Only image types are supported (e.g., image/png, image/jpeg, image/webp)"
            )

        if not base64_data:
            raise ValueError(
                "image_data must include base64 encoded data after the comma"
            )
    except IndexError:
        raise ValueError(
            "Invalid image_data format. Expected format: 'data:image/<type>;base64,<base64_data>'"
        )


def get_media_type_from_extension(file_extension: str) -> str:
    """
    Get the media type (MIME type) from a file extension.

    Args:
        file_extension: File extension with or without leading dot (e.g., ".png" or "png")

    Returns:
        Media type string (e.g., "image/png")

    Raises:
        ValueError: If the file extension is not supported
    """
    # Normalize extension to lowercase and ensure it starts with a dot
    ext = file_extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"

    if ext == ".png":
        return "image/png"
    elif ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    elif ext == ".webp":
        return "image/webp"
    elif ext == ".json":
        return "application/json"
    else:
        raise ValueError(f"Unsupported file extension: {ext}")


def get_media_type_from_file_path(file_path: str) -> str:
    """
    Get the media type (MIME type) from a file path by examining its extension.

    Args:
        file_path: Path to the file

    Returns:
        Media type string (e.g., "image/png")

    Raises:
        ValueError: If the file extension is not supported
    """
    file_extension = os.path.splitext(file_path)[1]
    return get_media_type_from_extension(file_extension)


class TAG_MATCH_MODE(enum.StrEnum):
    """Tag matching modes for asset search."""

    ALL = "all"
    ANY = "any"
    NONE = "none"


class AssetSelectionContext(pydantic.BaseModel):
    """
    Context for chaining asset selection operations.

    Tracks selection state and accumulated results for priority-based selection.

    Modes:
    - noop: Once a selection is made, subsequent selections pass through the previous selection
    - prioritize: All selections contribute, results sorted by priority (earlier selections first)
    """

    mode: str = "noop"  # "noop" or "prioritize"
    selected: bool = False
    selected_asset_ids: list[str] = pydantic.Field(default_factory=list)
    original_asset_ids: list[str] = pydantic.Field(default_factory=list)

    @property
    def has_selection(self) -> bool:
        """Alias for selected - indicates if any selection has been made."""
        return self.selected

    @property
    def asset_count(self) -> int:
        """Number of selected assets."""
        return len(self.selected_asset_ids)

    def should_skip(self) -> bool:
        """
        Check if selection should be skipped (noop mode with existing selection).
        """
        return self.mode == "noop" and self.selected

    def filter_already_selected(self, asset_ids: list[str]) -> list[str]:
        """
        Filter out asset IDs that have already been selected (for prioritize mode).

        Args:
            asset_ids: List of asset IDs to filter

        Returns:
            List of asset IDs not already in selected_asset_ids
        """
        if self.mode != "prioritize":
            return asset_ids
        return [aid for aid in asset_ids if aid not in self.selected_asset_ids]

    def update_with_matches(
        self, matched_asset_ids: list[str]
    ) -> "AssetSelectionContext":
        """
        Create a new context updated with matched asset IDs.

        Args:
            matched_asset_ids: List of newly matched asset IDs

        Returns:
            New AssetSelectionContext with updated state
        """
        if self.mode == "prioritize":
            new_selected = self.selected_asset_ids + matched_asset_ids
            return AssetSelectionContext(
                mode="prioritize",
                selected=len(new_selected) > 0,
                selected_asset_ids=new_selected,
                original_asset_ids=self.original_asset_ids,
            )
        else:
            # noop mode - only update if we have matches
            if matched_asset_ids:
                return AssetSelectionContext(
                    mode="noop",
                    selected=True,
                    selected_asset_ids=matched_asset_ids,
                    original_asset_ids=self.original_asset_ids,
                )
            return self

    def get_output_asset_ids(self, matched_asset_ids: list[str]) -> list[str]:
        """
        Get the asset IDs to output based on mode.

        Args:
            matched_asset_ids: List of newly matched asset IDs

        Returns:
            The appropriate list of asset IDs for output
        """
        if self.mode == "prioritize":
            return self.selected_asset_ids + matched_asset_ids
        return matched_asset_ids


class CoverBBox(pydantic.BaseModel):
    """
    Normalized bounding box within an image.

    Coordinates are normalized floats in [0..1], relative to the original image,
    with a top-left origin:
    - x, y: top-left corner
    - w, h: width/height
    """

    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0

    @pydantic.model_validator(mode="after")
    def _validate_bounds(self) -> "CoverBBox":
        if not (0.0 <= self.x < 1.0):
            raise ValueError("x must be in [0, 1)")
        if not (0.0 <= self.y < 1.0):
            raise ValueError("y must be in [0, 1)")
        if not (self.w > 0.0):
            raise ValueError("w must be > 0")
        if not (self.h > 0.0):
            raise ValueError("h must be > 0")
        if self.x + self.w > 1.0:
            raise ValueError("x + w must be <= 1")
        if self.y + self.h > 1.0:
            raise ValueError("y + h must be <= 1")
        return self


class AssetMeta(pydantic.BaseModel):
    name: str | None = None
    vis_type: VIS_TYPE = VIS_TYPE.UNSPECIFIED
    gen_type: GEN_TYPE = GEN_TYPE.TEXT_TO_IMAGE
    character_name: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    format: FORMAT_TYPE = FORMAT_TYPE.PORTRAIT
    resolution: Resolution | None = None
    sampler_settings: SamplerSettings | None = None
    reference_assets: list[str] = pydantic.Field(default_factory=list)
    tags: list[str] = pydantic.Field(default_factory=list)
    reference: list[VIS_TYPE] = pydantic.Field(default_factory=list)
    analysis: str | None = None
    cover_bbox: CoverBBox = pydantic.Field(default_factory=CoverBBox)

    @staticmethod
    def determine_format(width: int, height: int) -> FORMAT_TYPE:
        if width == height:
            return FORMAT_TYPE.SQUARE
        return FORMAT_TYPE.PORTRAIT if height > width else FORMAT_TYPE.LANDSCAPE

    @staticmethod
    def resolution_from_size(width: int, height: int) -> Resolution:
        return Resolution(width=width, height=height)

    def set_dimensions(self, width: int, height: int):
        self.format = self.determine_format(width, height)
        self.resolution = self.resolution_from_size(width, height)


class AssetTransfer(pydantic.BaseModel):
    """Describes an asset transfer from another scene."""

    source_scene_path: str
    asset_id: str


class Asset(pydantic.BaseModel):
    id: str
    file_type: str
    media_type: str
    meta: AssetMeta = pydantic.Field(default=AssetMeta())

    def to_base64(self, asset_directory: str) -> str:
        """
        Returns the asset as a base64 encoded string.
        """

        asset_path = os.path.join(asset_directory, f"{self.id}.{self.file_type}")

        with open(asset_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")


class AssetSavedPayload(pydantic.BaseModel):
    """Payload for the asset_saved signal."""

    asset: Asset
    new_asset: bool
    asset_attachment_context: AssetAttachmentContext = pydantic.Field(
        default=AssetAttachmentContext()
    )


async def _handle_asset_saved(payload: AssetSavedPayload):
    """
    Module-level handler for the asset_saved signal.
    Auto-attaches new assets to the most recent compatible message.
    """

    from talemate.context import active_scene

    scene: "Scene" = active_scene.get()

    if not scene:
        return

    asset_attachment_context: AssetAttachmentContext = payload.asset_attachment_context
    asset: Asset = payload.asset

    log.debug(
        "asset_saved signal received",
        asset_id=asset.id,
        new_asset=payload.new_asset,
        asset_attachment_context=payload.asset_attachment_context,
    )

    config: Config = get_config()

    # message attachment

    if config.appearance.scene.auto_attach_assets and payload.new_asset:
        if payload.asset_attachment_context.allow_auto_attach:
            await scene.assets.smart_attach_asset(
                asset.id,
                allow_override=asset_attachment_context.allow_override,
                delete_old=asset_attachment_context.delete_old,
                message_ids=asset_attachment_context.message_ids,
            )

    # cover image (scene and character)

    if asset_attachment_context.scene_cover:
        await scene.assets.set_scene_cover_image(
            asset.id, override=asset_attachment_context.override_scene_cover
        )

    if asset_attachment_context.character_cover:
        character = (
            scene.character_data.get(asset.meta.character_name)
            if asset.meta.character_name
            else None
        )
        if character:
            await scene.assets.set_character_cover_image(
                character,
                asset.id,
                override=asset_attachment_context.override_character_cover,
            )

    # character avatar / portrait

    if asset_attachment_context.default_avatar:
        character = (
            scene.character_data.get(asset.meta.character_name)
            if asset.meta.character_name
            else None
        )
        if character:
            await scene.assets.set_character_avatar(
                character,
                asset.id,
                override=asset_attachment_context.override_default_avatar,
            )

    if asset_attachment_context.current_avatar:
        character = (
            scene.character_data.get(asset.meta.character_name)
            if asset.meta.character_name
            else None
        )
        if character:
            await scene.assets.set_character_current_avatar(
                character,
                asset.id,
                override=asset_attachment_context.override_current_avatar,
            )

    # emit scene status here so visual library is reloaded on the frontend

    scene.emit_status()


async_signals.get("asset_saved").connect(_handle_asset_saved)


class SceneAssets:
    def __init__(self, scene: Scene):
        self.scene = scene
        self._assets_cache = None
        self.cover_image = None

    def _signal_asset_saved(
        self,
        asset: Asset,
        new_asset: bool,
        asset_attachment_context: AssetAttachmentContext | None = None,
    ):
        """
        Fires the asset_saved signal.

        Args:
            asset: The asset that was saved
            new_asset: True if this is a newly created asset, False if it already existed
        """
        try:
            payload = AssetSavedPayload(
                asset=asset,
                new_asset=new_asset,
            )
            if asset_attachment_context:
                payload.asset_attachment_context = asset_attachment_context
            asyncio.create_task(async_signals.get("asset_saved").send(payload))
        except Exception as e:
            log.error("Failed to fire asset_saved signal", error=str(e))

    @property
    def asset_directory(self) -> str:
        """
        Returns the scene's asset path
        """

        scene_save_dir = self.scene.save_dir

        if not os.path.exists(scene_save_dir):
            raise FileNotFoundError(
                f"Scene save directory does not exist: {scene_save_dir}"
            )

        asset_path = os.path.join(scene_save_dir, "assets")

        if not os.path.exists(asset_path):
            os.makedirs(asset_path)

        return asset_path

    @property
    def _library_path(self) -> str:
        """
        Returns the path to the unified library.json file.
        """
        return os.path.join(self.asset_directory, "library.json")

    def _load_library(self) -> dict:
        """
        Loads the asset library from library.json.
        Returns an empty dict if the file doesn't exist.
        """
        library_path = self._library_path
        if not os.path.exists(library_path):
            return {}

        try:
            with open(library_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("assets", {})
        except (json.JSONDecodeError, IOError) as e:
            log.warning("Failed to load asset library", error=str(e), path=library_path)
            return {}

    def _save_library(self, assets_dict: dict):
        """
        Saves the asset library to library.json.
        """
        library_path = self._library_path
        # Ensure directory exists
        os.makedirs(os.path.dirname(library_path), exist_ok=True)

        try:
            with open(library_path, "w", encoding="utf-8") as f:
                json.dump({"assets": assets_dict}, f, indent=2, default=str)
        except IOError as e:
            log.error("Failed to save asset library", error=str(e), path=library_path)
            raise

    @property
    def assets(self) -> dict:
        """
        Returns the assets dictionary, loading from library.json if needed.
        """
        if self._assets_cache is None:
            assets_dict = self._load_library()
            self._assets_cache = {
                asset_id: Asset(**asset_dict)
                for asset_id, asset_dict in assets_dict.items()
            }
        return self._assets_cache

    @assets.setter
    def assets(self, value: dict):
        """
        Sets the assets dictionary and saves to library.json.
        """
        self._assets_cache = value
        assets_dict = {
            asset_id: asset.model_dump() for asset_id, asset in value.items()
        }
        self._save_library(assets_dict)

    def save_library(self):
        """
        Saves the library to library.json.
        """
        assets_dict = {
            asset_id: asset.model_dump() for asset_id, asset in self.assets.items()
        }
        self._save_library(assets_dict)

    def save_asset(self, asset: Asset):
        """
        Saves an asset to library.json.
        """
        current_assets = self.assets
        current_assets[asset.id] = asset
        self.assets = current_assets

    def _invalidate_cache(self):
        """
        Invalidates the assets cache, forcing a reload from library.json.
        """
        self._assets_cache = None

    def validate_asset_id(self, asset_id: str) -> bool:
        """
        Validates that the asset id is a valid asset id.
        """
        return asset_id in self.assets

    def asset_path(self, asset_id: str) -> str:
        """
        Returns the path to the asset with the given id.
        """
        try:
            return os.path.join(
                self.asset_directory, f"{asset_id}.{self.assets[asset_id].file_type}"
            )
        except KeyError:
            log.debug("asset_path not found", asset_id=asset_id)
            return None

    def dict(self, *args, **kwargs):
        return {
            "cover_image": self.cover_image,
            "assets": {asset.id: asset.model_dump() for asset in self.assets.values()},
        }

    def scene_info(self) -> dict:
        return {
            "cover_image": self.cover_image,
        }

    def load_assets(self, assets_dict: dict):
        """
        Legacy method kept for API compatibility.
        Assets are now loaded from library.json automatically via the assets property.
        Migration handles moving assets from scene files to library.json.
        This method is a no-op since migration runs on server startup.
        """
        # No-op: assets are loaded from library.json via the assets property
        # Migration handles moving assets from scene files to library.json
        pass

    async def transfer_asset(self, transfer: AssetTransfer, source_scene=None) -> bool:
        """
        Transfer an asset from another scene to this scene.

        This method handles loading the source scene data, creating the source Scene object,
        and transferring the asset file.

        Args:
            transfer: AssetTransfer model describing the transfer

        Returns:
            True if transfer was successful, False otherwise
        """
        # Import here to avoid circular import
        from talemate.load import migrate_character_data, scene_stub

        try:
            # Load source scene data
            with open(transfer.source_scene_path, "r") as f:
                source_scene_data = json.load(f)

            migrate_character_data(source_scene_data)

            if not source_scene:
                source_scene = scene_stub(transfer.source_scene_path, source_scene_data)

            # Get the asset from source scene
            if transfer.asset_id not in source_scene.assets.assets:
                log.warning(
                    "transfer_asset",
                    message="Asset not found in source scene",
                    asset_id=transfer.asset_id,
                    source_scene_path=transfer.source_scene_path,
                )
                return False

            source_asset = source_scene.assets.get_asset(transfer.asset_id)

            # Get asset file path from source scene
            asset_path = source_scene.assets.asset_path(transfer.asset_id)

            if not asset_path or not os.path.exists(asset_path):
                log.warning(
                    "transfer_asset",
                    message="Asset file not found in source scene",
                    asset_id=transfer.asset_id,
                    asset_path=asset_path,
                )
                return False

            # Read asset bytes
            with open(asset_path, "rb") as f:
                asset_bytes = f.read()

            # Transfer asset to destination scene
            # add_asset will return existing asset if it already exists (same hash)
            transferred_asset = await self.add_asset(
                asset_bytes, source_asset.file_type, source_asset.media_type
            )

            # Copy meta if present and asset was newly created
            if source_asset.meta and transfer.asset_id == transferred_asset.id:
                transferred_asset.meta = source_asset.meta
                transferred_asset.meta.reference_assets = []

                # Update assets dict to save meta
                current_assets = self.assets
                current_assets[transfer.asset_id] = transferred_asset
                self.assets = current_assets

            return True

        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            log.warning(
                "transfer_asset",
                message="Failed to transfer asset",
                asset_id=transfer.asset_id,
                source_scene_path=transfer.source_scene_path,
                error=str(e),
            )
            return False

    async def add_asset(
        self,
        asset_bytes: bytes,
        file_extension: str,
        media_type: str,
        meta: AssetMeta | None = None,
        asset_attachment_context: AssetAttachmentContext | None = None,
    ) -> Asset:
        """
        Takes the asset and stores it in the scene's assets folder.
        """

        # generate a hash for the asset using the content of the image
        # this will be used as the filename
        asset_id = hashlib.sha256(asset_bytes).hexdigest()

        # if the asset already exists, return the existing asset
        if asset_id in self.assets:
            existing_asset = self.assets[asset_id]
            return existing_asset

        # create the asset path if it doesn't exist
        asset_path = self.asset_directory

        # create the asset file path
        asset_file_path = os.path.join(asset_path, f"{asset_id}.{file_extension}")

        # store the asset
        with open(asset_file_path, "wb") as f:
            f.write(asset_bytes)

        if not meta:
            meta = AssetMeta()

        # create the asset object
        asset = Asset(
            id=asset_id, file_type=file_extension, media_type=media_type, meta=meta
        )

        # Add to assets (this will save to library.json)
        current_assets = self.assets
        current_assets[asset_id] = asset
        self.assets = current_assets

        # Fire signal for new asset
        self._signal_asset_saved(
            asset, new_asset=True, asset_attachment_context=asset_attachment_context
        )

        return asset

    def bytes_from_image_data(self, image_data: str) -> bytes:
        """
        Will decode the image data into bytes.
        """
        validate_image_data_url(image_data)
        image_bytes = base64.b64decode(image_data.split(",")[1])
        return image_bytes

    async def add_asset_from_image_data(
        self,
        image_data: str,
        meta: AssetMeta | None = None,
        asset_attachment_context: AssetAttachmentContext | None = None,
    ) -> Asset:
        """
        Will add an asset from an image data, extracting media type from the
        data url and then decoding the base64 encoded data.

        Will call add_asset and automatically set dimensions on the asset's meta.

        Raises:
            ValueError: If the image_data format is invalid
        """
        validate_image_data_url(image_data)

        media_type = image_data.split(";")[0].split(":")[1]
        image_bytes = base64.b64decode(image_data.split(",")[1])
        file_extension = media_type.split("/")[1]

        asset = await self.add_asset(
            image_bytes, file_extension, media_type, meta, asset_attachment_context
        )

        # Get image dimensions and set them on meta
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                width, height = img.size
                asset.meta.set_dimensions(width, height)
        except Exception as e:
            log.warning("Failed to get image dimensions", error=str(e))

        return asset

    async def add_asset_from_file_path(
        self, file_path: str, meta: AssetMeta | None = None
    ) -> Asset:
        """
        Will add an asset from a file path, first loading the file into memory.
        and then calling add_asset
        """

        file_bytes = None
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_extension = os.path.splitext(file_path)[1]
        media_type = get_media_type_from_extension(file_extension)

        return await self.add_asset(file_bytes, file_extension, media_type, meta)

    async def add_asset_from_generation_response(
        self, response: "GenerationResponse"
    ) -> Asset:
        """
        Add an asset from a completed GenerationResponse.

        This helper method extracts the generated image bytes and metadata from
        a GenerationResponse and saves it as an asset in the scene.

        Args:
            response: The GenerationResponse containing the generated image and request metadata

        Returns:
            The added Asset object

        Raises:
            ValueError: If the response doesn't contain generated image data
        """
        if not response.generated:
            raise ValueError("GenerationResponse does not contain generated image data")

        if not response.request:
            raise ValueError(
                "GenerationResponse does not have a reference to the request"
            )

        request = response.request

        # Create AssetMeta from the request data
        meta = AssetMeta(
            vis_type=request.vis_type,
            gen_type=request.gen_type,
            character_name=request.character_name,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            format=request.format,
            resolution=request.resolution,
            sampler_settings=request.sampler_settings,
            reference_assets=request.reference_assets,
        )

        if request.asset_attachment_context.asset_name:
            meta.name = request.asset_attachment_context.asset_name

        if request.asset_attachment_context.tags:
            meta.tags = request.asset_attachment_context.tags

        # Save the asset (assumes PNG format for generated images)
        asset = await self.add_asset(
            response.generated,
            file_extension="png",
            media_type="image/png",
            meta=meta,
            asset_attachment_context=request.asset_attachment_context,
        )

        # Get image dimensions and set them on meta
        try:
            with Image.open(io.BytesIO(response.generated)) as img:
                width, height = img.size
                asset.meta.set_dimensions(width, height)
                # Save the updated asset with dimensions
                self.save_asset(asset)
        except Exception as e:
            log.warning("Failed to get image dimensions", error=str(e))

        log.debug(
            "added_asset_from_generation_response",
            asset_id=asset.id,
            vis_type=request.vis_type,
            character_name=request.character_name,
        )

        return asset

    def get_asset(self, asset_id: str) -> Asset:
        """
        Returns the asset with the given id.
        """

        return self.assets[asset_id]

    def update_asset_meta(self, asset_id: str, meta: AssetMeta):
        """
        Updates the metadata for an asset and saves to library.json.

        Args:
            asset_id: The ID of the asset to update
            meta: The new metadata to set
        """
        current_assets = self.assets
        if asset_id not in current_assets:
            raise KeyError(f"Asset {asset_id} not found")
        current_assets[asset_id].meta = meta
        self.assets = current_assets  # Save to library.json

    def get_asset_bytes(self, asset_id: str) -> bytes | None:
        """
        Returns the bytes of the asset with the given id.
        """

        asset_path = self.asset_path(asset_id)

        if not asset_path:
            log.debug("asset_path not found", asset_id=asset_id)
            return None

        with open(asset_path, "rb") as f:
            return f.read()

    def get_asset_bytes_many(self, asset_ids: list[str]) -> list[bytes]:
        """
        Returns the bytes of the assets with the given ids.
        """

        result = [self.get_asset_bytes(asset_id) for asset_id in asset_ids]
        # remove None values
        result = [bytes for bytes in result if bytes is not None]
        return result

    def get_asset_bytes_as_base64_many(self, asset_ids: list[str]) -> list[str]:
        """
        Returns the bytes of the assets with the given ids as a base64 encoded string.
        """

        result = [self.get_asset_bytes_as_base64(asset_id) for asset_id in asset_ids]
        # remove None values
        result = [base64 for base64 in result if base64 is not None]
        return result

    def get_asset_bytes_as_base64(self, asset_id: str) -> str | None:
        """
        Returns the bytes of the asset with the given id as a base64 encoded string.
        """

        bytes = self.get_asset_bytes(asset_id)

        if not bytes:
            return None

        return base64.b64encode(bytes).decode("utf-8")

    def cleanup_cover_images(self) -> bool:
        """
        Checks character cover images and the scene cover image and if they
        no longer exist as assets, unsets them.

        Returns True if any cover images were cleaned up, False otherwise.
        """
        cleaned = False

        # Check scene cover image
        if self.cover_image and not self.validate_asset_id(self.cover_image):
            log.debug(
                "Cleaning up scene cover image",
                asset_id=self.cover_image,
            )
            self.cover_image = None
            cleaned = True

            # Emit message to frontend that scene cover image was unset
            emit(
                "scene_asset_scene_cover_image",
                scene=self.scene,
                websocket_passthrough=True,
                kwargs={
                    "asset_id": None,
                    "asset": None,
                    "media_type": None,
                },
            )

        # Check character cover images
        for character in self.scene.character_data.values():
            if character.cover_image and not self.validate_asset_id(
                character.cover_image
            ):
                log.debug(
                    "Cleaning up character cover image",
                    character=character.name,
                    asset_id=character.cover_image,
                )
                character_name = character.name
                character.cover_image = None
                cleaned = True

                # Emit message to frontend that cover image was unset
                emit(
                    "scene_asset_character_cover_image",
                    scene=self.scene,
                    websocket_passthrough=True,
                    kwargs={
                        "asset_id": None,
                        "asset": None,
                        "media_type": None,
                        "character": character_name,
                    },
                )

        return cleaned

    def cleanup_message_avatars(self) -> bool:
        """
        Checks message avatars in scene history and if they no longer exist as assets, unsets them.

        Returns True if any message avatars were cleaned up, False otherwise.
        """
        cleaned = False

        # Check message avatars in history
        for message in self.scene.history:
            if (
                hasattr(message, "asset_id")
                and message.asset_id
                and not self.validate_asset_id(message.asset_id)
            ):
                log.debug(
                    "Cleaning up message avatar",
                    message_id=message.id,
                    asset_id=message.asset_id,
                )
                message.asset_id = None
                message.asset_type = None
                cleaned = True

                # Emit signal to notify frontend
                emit(
                    "message_asset_update",
                    "",
                    websocket_passthrough=True,
                    kwargs={
                        "message_id": message.id,
                        "asset_id": None,
                        "asset_type": None,
                    },
                )

        return cleaned

    def cleanup_character_avatars(self) -> bool:
        """
        Checks character avatars (default and current) and if they no longer exist as assets, unsets them.

        Returns True if any character avatars were cleaned up, False otherwise.
        """
        cleaned = False

        # Check character avatars
        for character in self.scene.character_data.values():
            # Check default avatar
            if character.avatar and not self.validate_asset_id(character.avatar):
                log.debug(
                    "Cleaning up character default avatar",
                    character=character.name,
                    asset_id=character.avatar,
                )
                character_name = character.name
                character.avatar = None
                cleaned = True

                # Emit message to frontend that default avatar was unset
                emit(
                    "scene_asset_character_avatar",
                    scene=self.scene,
                    websocket_passthrough=True,
                    kwargs={
                        "asset_id": None,
                        "asset": None,
                        "media_type": None,
                        "character": character_name,
                    },
                )

            # Check current avatar
            if character.current_avatar and not self.validate_asset_id(
                character.current_avatar
            ):
                log.debug(
                    "Cleaning up character current avatar",
                    character=character.name,
                    asset_id=character.current_avatar,
                )
                character_name = character.name
                character.current_avatar = None
                cleaned = True

                # Emit message to frontend that current avatar was unset
                emit(
                    "scene_asset_character_current_avatar",
                    scene=self.scene,
                    websocket_passthrough=True,
                    kwargs={
                        "asset_id": None,
                        "asset": None,
                        "media_type": None,
                        "character": character_name,
                    },
                )

        return cleaned

    def remove_asset(self, asset_id: str):
        """
        Removes the asset with the given id.
        """

        current_assets = self.assets
        asset = current_assets.pop(asset_id)

        # Save updated library
        self.assets = current_assets

        asset_path = self.asset_directory

        asset_file_path = os.path.join(asset_path, f"{asset_id}.{asset.file_type}")
        try:
            os.remove(asset_file_path)
        except FileNotFoundError:
            # If the file is already missing on disk, we still consider the
            # in-memory removal successful.
            pass

        # Clean up cover images, character avatars, and message avatars that may reference the removed asset
        self.cleanup_cover_images()
        self.cleanup_character_avatars()
        self.cleanup_message_avatars()

        self.scene.emit_status()

    def search_assets(
        self,
        vis_type: VIS_TYPE | list[VIS_TYPE] | None = None,
        character_name: str | None = None,
        tags: list[str] | None = None,
        tag_match_mode: TAG_MATCH_MODE = TAG_MATCH_MODE.ALL,
        reference_vis_types: list[VIS_TYPE] | None = None,
    ) -> list[str]:
        """
        Search assets by vis_type, character_name, tags, or reference vis_types.

        Args:
            vis_type: Visual type(s) to filter by. Can be a single VIS_TYPE or a list of VIS_TYPE values.
                     If a list, asset must match any of the provided types.
            character_name: Character name to filter by (case insensitive substring match)
            tags: List of tags to filter by (case insensitive)
            tag_match_mode: How to match tags - TAG_MATCH_MODE.ALL (asset must have all tags),
                          TAG_MATCH_MODE.ANY (asset must have at least one tag),
                          TAG_MATCH_MODE.NONE (asset must not have any tags)
            reference_vis_types: List of vis_types to filter by. Asset must have at least one
                                matching vis_type in its reference list, or if None, no filter is applied.

        Returns:
            List of asset IDs that match all provided criteria
        """
        matching_asset_ids = []

        # Normalize vis_type to a list for consistent handling
        vis_type_list: list[VIS_TYPE] | None = None
        if vis_type is not None:
            if isinstance(vis_type, list):
                vis_type_list = vis_type
            else:
                vis_type_list = [vis_type]

        for asset_id, asset in self.assets.items():
            meta = asset.meta
            matches = True

            # Filter by vis_type (match any in list)
            if vis_type_list:
                if meta.vis_type not in vis_type_list:
                    matches = False
                    continue

            # Filter by character_name (case insensitive)
            if character_name:
                asset_char_name = meta.character_name or ""
                if character_name.lower() not in asset_char_name.lower():
                    matches = False
                    continue

            # Filter by tags (case insensitive)
            if tags:
                asset_tags_lower = [tag.lower() for tag in (meta.tags or [])]
                filter_tags_lower = [tag.lower() for tag in tags if tag]

                if filter_tags_lower:
                    tag_matches = False

                    if tag_match_mode == TAG_MATCH_MODE.ALL:
                        # Asset must have all tags
                        tag_matches = all(
                            tag in asset_tags_lower for tag in filter_tags_lower
                        )
                    elif tag_match_mode == TAG_MATCH_MODE.ANY:
                        # Asset must have at least one tag
                        tag_matches = any(
                            tag in asset_tags_lower for tag in filter_tags_lower
                        )
                    elif tag_match_mode == TAG_MATCH_MODE.NONE:
                        # Asset must not have any tags
                        tag_matches = not any(
                            tag in asset_tags_lower for tag in filter_tags_lower
                        )
                    else:
                        raise ValueError(
                            f"Invalid tag_match_mode: {tag_match_mode}. Must be TAG_MATCH_MODE.ALL, TAG_MATCH_MODE.ANY, or TAG_MATCH_MODE.NONE"
                        )

                    if not tag_matches:
                        matches = False
                        continue

            # Filter by reference vis_types
            if reference_vis_types:
                asset_reference_types = meta.reference or []
                # Asset must have at least one matching vis_type in its reference list
                if not any(
                    ref_type in asset_reference_types
                    for ref_type in reference_vis_types
                ):
                    matches = False
                    continue

            if matches:
                matching_asset_ids.append(asset_id)

        return matching_asset_ids

    def select_assets(
        self,
        asset_ids: list[str],
        vis_types: list[VIS_TYPE] | None = None,
        reference_vis_types: list[VIS_TYPE] | None = None,
    ) -> list[str]:
        """
        Filter a list of asset IDs by vis_types and/or reference_vis_types.

        This is similar to search_assets but operates on a provided list of asset IDs
        rather than searching all assets.

        Args:
            asset_ids: List of asset IDs to filter
            vis_types: List of vis_types to match (asset must match any)
            reference_vis_types: List of reference vis_types to match
                                (asset must have any in its reference list)

        Returns:
            List of asset IDs that match the criteria
        """
        matched_asset_ids: list[str] = []

        for asset_id in asset_ids:
            try:
                asset = self.get_asset(asset_id)
                meta = asset.meta
                matches = True

                # Filter by vis_types (must match any)
                if vis_types:
                    if meta.vis_type not in vis_types:
                        matches = False

                # Filter by reference_vis_types (must have any in reference list)
                if matches and reference_vis_types:
                    asset_references = meta.reference or []
                    if not any(rvt in asset_references for rvt in reference_vis_types):
                        matches = False

                if matches:
                    matched_asset_ids.append(asset_id)

            except KeyError:
                # Skip missing assets
                log.debug("Asset not found, skipping", asset_id=asset_id)

        return matched_asset_ids

    async def set_character_avatar(
        self, character: "Character", asset_id: str, override: bool = False
    ) -> str | None:
        """
        Sets the character's default avatar.
        """
        log.debug(
            "set_character_avatar",
            character=character,
            asset_id=asset_id,
            override=override,
        )
        if not self.validate_asset_id(asset_id):
            log.error("Invalid asset id", asset_id=asset_id)
            return None
        if not override and character.avatar:
            return character.avatar
        character.avatar = asset_id

        # Emit event for websocket passthrough
        asset = self.get_asset(asset_id)
        emit(
            "scene_asset_character_avatar",
            scene=self.scene,
            websocket_passthrough=True,
            kwargs={
                "asset_id": asset_id,
                "asset": self.get_asset_bytes_as_base64(asset_id),
                "media_type": asset.media_type,
                "character": character.name,
            },
        )

        return asset_id

    async def set_character_current_avatar(
        self, character: "Character", asset_id: str, override: bool = False
    ) -> str | None:
        """
        Sets the character's current avatar (used to set message.asset_id).
        """
        log.debug(
            "set_character_current_avatar",
            character=character,
            asset_id=asset_id,
            override=override,
        )
        if not self.validate_asset_id(asset_id):
            log.error("Invalid asset id", asset_id=asset_id)
            return None
        if not override and character.current_avatar:
            return character.current_avatar
        character.current_avatar = asset_id

        # Emit event for websocket passthrough
        asset = self.get_asset(asset_id)
        emit(
            "scene_asset_character_current_avatar",
            scene=self.scene,
            websocket_passthrough=True,
            kwargs={
                "asset_id": asset_id,
                "asset": self.get_asset_bytes_as_base64(asset_id),
                "media_type": asset.media_type,
                "character": character.name,
            },
        )

        return asset_id

    async def smart_attach_asset(
        self,
        asset_id: str,
        allow_override: bool = False,
        delete_old: bool = False,
        message_ids: list[int] | None = None,
    ) -> list[scene_message.SceneMessage] | None:
        """
        Smartly attach an asset to the most recent message in the history.

        Args:
            asset_id: The asset to attach
            allow_override: Whether to override existing message assets
            delete_old: Whether to delete the old asset when replacing (requires allow_override=True)
            message_ids: Specific message IDs to attach to (None = auto-detect)
        """
        asset = self.get_asset(asset_id)
        if asset is None:
            log.error("Asset not found", asset_id=asset_id)
            return None

        candidate_types = ["character", "narrator", "context_investigation"]

        messages = []

        if not message_ids:
            best_candidate_message = self.scene.last_message_of_type(
                candidate_types,
                max_iterations=10,
            )

            if not best_candidate_message:
                return None

            messages = [best_candidate_message]
        else:
            for message_id in message_ids:
                message = self.scene.get_message(message_id)
                if message:
                    messages.append(message)
                else:
                    log.warning(
                        "smart_attach_asset - Message not found", message_id=message_id
                    )

        if not messages:
            return None

        log.debug(
            "smart_attach_asset - Attaching asset to messages",
            asset_id=asset_id,
            messages=[message.id for message in messages],
            delete_old=delete_old,
        )

        for message in messages:
            if not allow_override and message.asset_id:
                continue

            # CHARACTER_PORTRAIT are only attachable to CHARACTER messages
            if asset.meta.vis_type == VIS_TYPE.CHARACTER_PORTRAIT:
                character = self.scene.get_character(asset.meta.character_name)
                message_character_name = getattr(message, "character_name", None)
                if character and character.name != message_character_name:
                    continue

            # Delete the old asset if requested and there is one
            if delete_old and allow_override and message.asset_id:
                old_asset_id = message.asset_id
                log.debug(
                    "smart_attach_asset - Deleting old asset",
                    old_asset_id=old_asset_id,
                    message_id=message.id,
                )
                self.remove_asset(old_asset_id)

            await self.update_message_asset(message.id, asset_id)

        return messages

    async def clear_message_asset(
        self, message_id: int
    ) -> scene_message.SceneMessage | None:
        """
        Clear the asset_id and asset_type of a message in the scene history.

        Args:
            message_id: The ID of the message to update

        Returns:
            The updated message object, or None if message not found
        """
        log.debug(
            "clear_message_asset",
            message_id=message_id,
        )

        # Get the message
        message = self.scene.get_message(message_id)

        if message is None:
            log.error("Message not found", message_id=message_id)
            return None

        # Validate that the message supports assets
        if not isinstance(
            message,
            (
                scene_message.CharacterMessage,
                scene_message.NarratorMessage,
                scene_message.ContextInvestigationMessage,
            ),
        ):
            log.warning(
                f"Message type '{message.typ}' does not support assets. "
                f"Only CharacterMessage, NarratorMessage and ContextInvestigationMessage support assets."
            )
            return None

        # Update the message's asset properties
        message.asset_id = None
        message.asset_type = None

        # Emit signal with websocket_passthrough
        emit(
            "message_asset_update",
            "",
            websocket_passthrough=True,
            kwargs={
                "message_id": message_id,
                "asset_id": None,
                "asset_type": None,
            },
        )

        log.debug(
            "Message asset cleared",
            message_id=message_id,
        )

        return message

    async def update_message_asset(
        self,
        message_id: int,
        asset_id: str,
    ) -> scene_message.SceneMessage | None:
        """
        Update the asset_id and asset_type of a message in the scene history.

        Args:
            message_id: The ID of the message to update
            asset_id: The new asset ID

        Returns:
            The updated message object, or None if message not found

        Raises:
            ValueError: If the asset_id is invalid or message type doesn't support assets
        """
        log.debug(
            "update_message_asset",
            message_id=message_id,
            asset_id=asset_id,
        )

        # Get the message
        message = self.scene.get_message(message_id)

        if message is None:
            log.error("Message not found", message_id=message_id)
            return None

        # Validate that the message supports assets
        if not isinstance(
            message,
            (
                scene_message.CharacterMessage,
                scene_message.NarratorMessage,
                scene_message.ContextInvestigationMessage,
            ),
        ):
            raise ValueError(
                f"Message type '{message.typ}' does not support assets. "
                f"Only CharacterMessage, NarratorMessage and ContextInvestigationMessage support assets."
            )

        # Validate asset_id
        if not self.validate_asset_id(asset_id):
            raise ValueError(f"Invalid asset_id: {asset_id}")

        asset = self.get_asset(asset_id)
        asset_type = VIS_TYPE_TO_ASSET_TYPE.get(asset.meta.vis_type, None)

        if asset_type is None:
            raise ValueError(
                f"Asset type not valid for message attachement: {asset_id}"
            )

        # Update the message's asset properties
        message.asset_id = asset_id
        message.asset_type = asset_type

        # Emit signal with websocket_passthrough
        emit(
            "message_asset_update",
            "",
            websocket_passthrough=True,
            kwargs={
                "message_id": message_id,
                "asset_id": asset_id,
                "asset_type": asset_type,
            },
        )

        log.debug(
            "Message asset updated",
            message_id=message_id,
            asset_id=asset_id,
            asset_type=asset_type,
        )

        return message

    async def set_scene_cover_image_from_bytes(
        self, bytes: bytes, override: bool = False
    ) -> str:
        """
        Sets the scene cover image from bytes.
        """
        asset = await self.add_asset(bytes, "png", "image/png")
        await self.set_scene_cover_image(asset.id, override)
        return asset.id

    async def set_scene_cover_image_from_image_data(
        self, image_data: str, override: bool = False
    ) -> str:
        """
        Sets the scene cover image from an image data.
        """
        asset = await self.add_asset_from_image_data(image_data)
        await self.set_scene_cover_image(asset.id, override)
        return asset.id

    async def set_scene_cover_image_from_file_path(
        self, file_path: str, override: bool = False
    ) -> str:
        """
        Sets the scene cover image from a file path.
        """
        asset = await self.add_asset_from_file_path(file_path)
        await self.set_scene_cover_image(asset.id, override)
        return asset.id

    async def set_scene_cover_image(
        self, asset_id: str, override: bool = False
    ) -> str | None:
        """
        Sets the scene cover image.
        """
        log.debug("set_scene_cover_image", asset_id=asset_id, override=override)
        if not self.validate_asset_id(asset_id):
            log.error("Invalid asset id", asset_id=asset_id)
            return None
        if not override and self.cover_image:
            return self.cover_image
        self.cover_image = asset_id

        # Only emit status if scene is active, otherwise it will be emitted when scene starts
        if self.scene.active:
            self.scene.emit_status()

        # Emit event for websocket passthrough (always emit, even if scene isn't active yet)
        asset = self.get_asset(asset_id)
        emit(
            "scene_asset_scene_cover_image",
            scene=self.scene,
            websocket_passthrough=True,
            kwargs={
                "asset_id": asset_id,
                "media_type": asset.media_type,
            },
        )

        return asset_id

    async def set_character_cover_image_from_bytes(
        self, character: "Character", bytes: bytes, override: bool = False
    ) -> str:
        """
        Sets the character cover image from bytes.
        """
        asset = await self.add_asset(bytes, "png", "image/png")
        await self.set_character_cover_image(character, asset.id, override)
        return asset.id

    async def set_character_cover_image_from_image_data(
        self, character: "Character", image_data: str, override: bool = False
    ) -> str:
        """
        Sets the character cover image from an image data.
        """
        asset = await self.add_asset_from_image_data(image_data)
        await self.set_character_cover_image(character, asset.id, override)
        return asset.id

    async def set_character_cover_image_from_file_path(
        self, character: "Character", file_path: str, override: bool = False
    ) -> str:
        """
        Sets the character cover image from a file path.
        """
        asset = await self.add_asset_from_file_path(file_path)
        await self.set_character_cover_image(character, asset.id, override)
        return asset.id

    async def set_character_cover_image(
        self, character: "Character", asset_id: str, override: bool = False
    ) -> str | None:
        """
        Sets the character cover image.
        """
        log.debug(
            "set_character_cover_image",
            character=character,
            asset_id=asset_id,
            override=override,
        )
        if not self.validate_asset_id(asset_id):
            log.error("Invalid asset id", asset_id=asset_id)
            return None
        if not override and character.cover_image:
            return character.cover_image
        character.cover_image = asset_id

        # Emit event for websocket passthrough
        asset = self.get_asset(asset_id)
        emit(
            "scene_asset_character_cover_image",
            scene=self.scene,
            websocket_passthrough=True,
            kwargs={
                "asset_id": asset_id,
                "media_type": asset.media_type,
                "character": character.name,
            },
        )

        return asset_id


def migrate_scene_assets_to_library(root: Path | str | None = None) -> None:
    """
    Migrates scene assets from individual scene files to a unified library.json file.

    This function scans all scene JSON files in each project directory and collects
    all assets into a single library.json file located at assets/library.json within
    each project directory. This migration does not modify the scene files themselves.

    Args:
        root: Optional path to the root scenes directory. If None, uses SCENES_DIR.
    """
    scenes_root = Path(root) if root else SCENES_DIR

    if not scenes_root.is_dir():
        log.warning("scenes_root_not_found", root=str(scenes_root))
        return

    processed_projects = 0
    processed_scenes = 0
    total_assets = 0

    try:
        # Iterate through all project directories
        for project_path in sorted(
            (p for p in scenes_root.iterdir() if p.is_dir()), key=lambda p: p.name
        ):
            # Find all scene JSON files in this project
            scene_files = [
                p for p in project_path.iterdir() if p.is_file() and p.suffix == ".json"
            ]

            if not scene_files:
                continue

            # Collect all assets from all scene files
            all_assets = {}

            for scene_file in scene_files:
                try:
                    with open(scene_file, "r", encoding="utf-8") as f:
                        scene_data = json.load(f)

                    # Extract assets from scene data
                    assets_data = scene_data.get("assets", {}).get("assets", {})
                    if assets_data:
                        # Merge assets into the unified collection
                        # Later scenes will override earlier ones if same asset_id exists
                        all_assets.update(assets_data)
                        processed_scenes += 1
                except (json.JSONDecodeError, IOError) as e:
                    log.warning(
                        "migrate_scene_assets_failed_to_read",
                        scene_file=str(scene_file),
                        error=str(e),
                    )
                    continue

            # If we found any assets, create the library.json file
            if all_assets:
                assets_dir = project_path / "assets"
                assets_dir.mkdir(exist_ok=True)
                library_path = assets_dir / "library.json"

                # Only create if it doesn't exist (idempotent migration)
                if not library_path.exists():
                    try:
                        with open(library_path, "w", encoding="utf-8") as f:
                            json.dump({"assets": all_assets}, f, indent=2, default=str)

                        processed_projects += 1
                        total_assets += len(all_assets)

                        log.debug(
                            "migrated_scene_assets_to_library",
                            project=str(project_path.name),
                            assets_count=len(all_assets),
                            library_path=str(library_path),
                        )
                    except IOError as e:
                        log.error(
                            "migrate_scene_assets_failed_to_write",
                            library_path=str(library_path),
                            error=str(e),
                        )

    except Exception as e:
        log.error("migrate_scene_assets_to_library_failed", error=str(e))

    if processed_projects > 0:
        log.info(
            "migration_complete",
            projects_processed=processed_projects,
            scenes_processed=processed_scenes,
            total_assets=total_assets,
        )
