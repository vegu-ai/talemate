from __future__ import annotations

import base64
import hashlib
import os
import enum
import io
from typing import TYPE_CHECKING

import pydantic
from PIL import Image

if TYPE_CHECKING:
    from talemate import Scene
    from talemate.character import Character

import structlog

from talemate.emit import emit
from talemate.agents.visual.schema import (
    VIS_TYPE,
    GEN_TYPE,
    FORMAT_TYPE,
    SamplerSettings,
    Resolution,
)

__all__ = [
    "Asset",
    "SceneAssets",
    "AssetMeta",
    "TAG_MATCH_MODE",
    "validate_image_data_url",
    "set_scene_cover_image_from_bytes",
    "set_scene_cover_image_from_image_data",
    "set_scene_cover_image_from_file_path",
    "set_scene_cover_image",
    "set_character_cover_image_from_bytes",
    "set_character_cover_image_from_image_data",
    "set_character_cover_image_from_file_path",
    "set_character_cover_image",
]

log = structlog.get_logger("talemate.scene_assets")


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


class TAG_MATCH_MODE(enum.StrEnum):
    """Tag matching modes for asset search."""

    ALL = "all"
    ANY = "any"
    NONE = "none"


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


class SceneAssets:
    def __init__(self, scene: Scene):
        self.scene = scene
        self.assets = {}
        self.cover_image = None

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
            log.error("asset_path", asset_id=asset_id, assets=self.assets)
            return None

    def dict(self, *args, **kwargs):
        return {
            "cover_image": self.cover_image,
            "assets": {asset.id: asset.model_dump() for asset in self.assets.values()},
        }

    def load_assets(self, assets_dict: dict):
        """
        Loads assets from a dictionary.
        """

        for asset_id, asset_dict in assets_dict.items():
            self.assets[asset_id] = Asset(**asset_dict)

    def transfer_asset(self, source: "SceneAssets", asset_id: str):
        """
        Will transfer another scenes asset into this scene on the same id
        """

        asset = source.assets[asset_id]

        asset_path = source.asset_path(asset_id)

        with open(asset_path, "rb") as f:
            asset_bytes = f.read()

        self.add_asset(asset_bytes, asset.file_type, asset.media_type)

    def add_asset(
        self, asset_bytes: bytes, file_extension: str, media_type: str
    ) -> Asset:
        """
        Takes the asset and stores it in the scene's assets folder.
        """

        # generate a hash for the asset using the content of the image
        # this will be used as the filename
        asset_id = hashlib.sha256(asset_bytes).hexdigest()

        # if the asset already exists, return the existing asset
        if asset_id in self.assets:
            return self.assets[asset_id]

        # create the asset path if it doesn't exist
        asset_path = self.asset_directory

        # create the asset file path
        asset_file_path = os.path.join(asset_path, f"{asset_id}.{file_extension}")

        # store the asset
        with open(asset_file_path, "wb") as f:
            f.write(asset_bytes)

        # create the asset object
        asset = Asset(id=asset_id, file_type=file_extension, media_type=media_type)

        self.assets[asset_id] = asset

        return asset

    def bytes_from_image_data(self, image_data: str) -> bytes:
        """
        Will decode the image data into bytes.
        """
        validate_image_data_url(image_data)
        image_bytes = base64.b64decode(image_data.split(",")[1])
        return image_bytes

    def add_asset_from_image_data(self, image_data: str) -> Asset:
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

        asset = self.add_asset(image_bytes, file_extension, media_type)

        # Get image dimensions and set them on meta
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                width, height = img.size
                asset.meta.set_dimensions(width, height)
        except Exception as e:
            log.warning("Failed to get image dimensions", error=str(e))

        return asset

    def add_asset_from_file_path(self, file_path: str) -> Asset:
        """
        Will add an asset from a file path, first loading the file into memory.
        and then calling add_asset
        """

        file_bytes = None
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_extension = os.path.splitext(file_path)[1]

        # guess media type from extension, currently only supports images
        # for png, jpg and webp

        if file_extension == ".png":
            media_type = "image/png"
        elif file_extension in [".jpg", ".jpeg"]:
            media_type = "image/jpeg"
        elif file_extension == ".webp":
            media_type = "image/webp"
        else:
            raise ValueError(f"Unsupported file extension: {file_extension}")

        return self.add_asset(file_bytes, file_extension, media_type)

    def get_asset(self, asset_id: str) -> Asset:
        """
        Returns the asset with the given id.
        """

        return self.assets[asset_id]

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
                character.cover_image = None
                cleaned = True

        return cleaned

    def remove_asset(self, asset_id: str):
        """
        Removes the asset with the given id.
        """

        asset = self.assets.pop(asset_id)

        asset_path = self.asset_directory

        asset_file_path = os.path.join(asset_path, f"{asset_id}.{asset.file_type}")
        try:
            os.remove(asset_file_path)
        except FileNotFoundError:
            # If the file is already missing on disk, we still consider the
            # in-memory removal successful.
            pass

        # Clean up cover images that may reference the removed asset
        if self.cleanup_cover_images():
            # Emit status update if any cover images were cleaned up
            self.scene.emit_status()

    def search_assets(
        self,
        vis_type: VIS_TYPE | None = None,
        character_name: str | None = None,
        tags: list[str] | None = None,
        tag_match_mode: TAG_MATCH_MODE = TAG_MATCH_MODE.ALL,
        reference_vis_types: list[VIS_TYPE] | None = None,
    ) -> list[str]:
        """
        Search assets by vis_type, character_name, tags, or reference vis_types.

        Args:
            vis_type: Visual type to filter by (exact match)
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

        for asset_id, asset in self.assets.items():
            meta = asset.meta
            matches = True

            # Filter by vis_type
            if vis_type is not None:
                if meta.vis_type != vis_type:
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


async def set_scene_cover_image_from_bytes(
    scene: "Scene", bytes: bytes, override: bool = False
) -> str:
    """
    Sets the scene cover image from bytes.
    """
    asset = scene.assets.add_asset(bytes, "png", "image/png")
    await set_scene_cover_image(scene, asset.id, override)
    return asset.id


async def set_scene_cover_image_from_image_data(
    scene: "Scene", image_data: str, override: bool = False
) -> str:
    """
    Sets the scene cover image from an image data.
    """
    asset = scene.assets.add_asset_from_image_data(image_data)
    await set_scene_cover_image(scene, asset.id, override)
    return asset.id


async def set_scene_cover_image_from_file_path(
    scene: "Scene", file_path: str, override: bool = False
) -> str:
    """
    Sets the scene cover image from a file path.
    """
    asset = scene.assets.add_asset_from_file_path(file_path)
    await set_scene_cover_image(scene, asset.id, override)
    return asset.id


async def set_scene_cover_image(
    scene: "Scene", asset_id: str, override: bool = False
) -> str:
    """
    Sets the scene cover image.
    """
    log.debug(
        "set_scene_cover_image", scene=scene, asset_id=asset_id, override=override
    )
    if not scene.assets.validate_asset_id(asset_id):
        log.error("Invalid asset id", asset_id=asset_id)
        return None
    if not override and scene.assets.cover_image:
        return scene.assets.cover_image
    scene.assets.cover_image = asset_id
    
    # Only emit status if scene is active, otherwise it will be emitted when scene starts
    if scene.active:
        scene.emit_status()

    # Emit event for websocket passthrough (always emit, even if scene isn't active yet)
    asset = scene.assets.get_asset(asset_id)
    emit(
        "scene_asset_scene_cover_image",
        scene=scene,
        websocket_passthrough=True,
        kwargs={
            "asset_id": asset_id,
            "asset": scene.assets.get_asset_bytes_as_base64(asset_id),
            "media_type": asset.media_type,
        },
    )

    return asset_id


async def set_character_cover_image_from_bytes(
    scene: "Scene", character: "Character", bytes: bytes, override: bool = False
) -> str:
    """
    Sets the character cover image from bytes.
    """
    asset = scene.assets.add_asset(bytes, "png", "image/png")
    await set_character_cover_image(scene, character, asset.id, override)
    return asset.id


async def set_character_cover_image_from_image_data(
    scene: "Scene", character: "Character", image_data: str, override: bool = False
) -> str:
    """
    Sets the character cover image from an image data.
    """
    asset = scene.assets.add_asset_from_image_data(image_data)
    await set_character_cover_image(scene, character, asset.id, override)
    return asset.id


async def set_character_cover_image_from_file_path(
    scene: "Scene", character: "Character", file_path: str, override: bool = False
) -> str:
    """
    Sets the character cover image from a file path.
    """
    asset = scene.assets.add_asset_from_file_path(file_path)
    await set_character_cover_image(scene, character, asset.id, override)
    return asset.id


async def set_character_cover_image(
    scene: "Scene", character: "Character", asset_id: str, override: bool = False
) -> str | None:
    """
    Sets the character cover image.
    """
    log.debug(
        "set_character_cover_image",
        scene=scene,
        character=character,
        asset_id=asset_id,
        override=override,
    )
    if not scene.assets.validate_asset_id(asset_id):
        log.error("Invalid asset id", asset_id=asset_id)
        return None
    if not override and character.cover_image:
        return character.cover_image
    character.cover_image = asset_id

    # Emit event for websocket passthrough
    asset = scene.assets.get_asset(asset_id)
    emit(
        "scene_asset_character_cover_image",
        scene=scene,
        websocket_passthrough=True,
        kwargs={
            "asset_id": asset_id,
            "asset": scene.assets.get_asset_bytes_as_base64(asset_id),
            "media_type": asset.media_type,
            "character": character.name,
        },
    )

    return asset_id
