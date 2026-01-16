import base64
import io
from typing import Literal

import pydantic
import structlog
from PIL import Image

from talemate.server.websocket_plugin import Plugin
from talemate.scene_assets import (
    AssetMeta,
    CoverBBox,
    TAG_MATCH_MODE,
)
from talemate.agents.visual.schema import VIS_TYPE, GEN_TYPE

log = structlog.get_logger("talemate.server.scene_assets")


class DeleteAssetPayload(pydantic.BaseModel):
    asset_id: str


class AddAssetPayload(pydantic.BaseModel):
    content: str  # data URL
    vis_type: str | None = None
    character_name: str | None = None
    name: str | None = None


class EditAssetMetaPayload(pydantic.BaseModel):
    asset_id: str
    name: str | None = None
    vis_type: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    character_name: str | None = None
    tags: list[str] | None = None
    reference: list[str] | None = None
    reference_assets: list[str] | None = None
    analysis: str | None = None
    cover_bbox: CoverBBox = pydantic.Field(default_factory=CoverBBox)


class SetSceneCoverImagePayload(pydantic.BaseModel):
    asset_id: str


class SetCharacterCoverImagePayload(pydantic.BaseModel):
    asset_id: str
    character_name: str


class SetCharacterAvatarPayload(pydantic.BaseModel):
    asset_id: str
    character_name: str
    avatar_type: Literal["default", "current"] = "default"


class SearchAssetsPayload(pydantic.BaseModel):
    vis_type: str | None = None
    character_name: str | None = None
    tags: list[str] | None = None
    reference_vis_types: list[str] | None = None


class UpdateMessageAssetPayload(pydantic.BaseModel):
    asset_id: str
    message_id: int
    character_name: str | None = None


class ClearMessageAssetPayload(pydantic.BaseModel):
    message_id: int


class SceneAssetsPlugin(Plugin):
    router = "scene_assets"

    async def handle_delete(self, data: dict):
        payload = DeleteAssetPayload(**data)
        asset_id = payload.asset_id

        if not asset_id:
            await self.signal_operation_failed("Missing asset_id")
            return

        try:
            self.scene.assets.remove_asset(asset_id)
            # notify frontend
            await self.scene.attempt_auto_save()
            await self.signal_operation_done()
        except Exception as e:
            log.error("delete_asset_failed", error=e)
            await self.signal_operation_failed(f"Failed to delete asset: {e}")

    async def handle_add(self, data: dict):
        payload = AddAssetPayload(**data)

        try:
            # Add asset from data URL
            asset = await self.scene.assets.add_asset_from_image_data(payload.content)

            # Decode image to get resolution
            b64 = payload.content.split(",", 1)[1]
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            width, height = img.size

            vis_type_value = payload.vis_type or VIS_TYPE.UNSPECIFIED.value
            try:
                vis = VIS_TYPE(vis_type_value)
            except Exception:
                vis = VIS_TYPE.UNSPECIFIED

            meta = AssetMeta(
                name=payload.name,
                vis_type=vis,
                gen_type=GEN_TYPE.UPLOAD,
                character_name=payload.character_name,
                prompt=None,
                negative_prompt=None,
                format=AssetMeta.determine_format(width, height),
                resolution=AssetMeta.resolution_from_size(width, height),
                sampler_settings=None,
            )

            # Assign meta and emit
            self.scene.assets.update_asset_meta(asset.id, meta)

            # notify frontend
            await self.scene.attempt_auto_save()
            self.websocket_handler.request_scene_assets([asset.id])
            await self.signal_operation_done()
        except Exception as e:
            log.error("add_asset_failed", error=e)
            await self.signal_operation_failed(f"Failed to add asset: {e}")

    async def handle_edit_meta(self, data: dict):
        payload = EditAssetMetaPayload(**data)
        asset_id = payload.asset_id

        try:
            asset = self.scene.assets.get_asset(asset_id)
        except Exception as e:
            await self.signal_operation_failed(f"Asset not found: {e}")
            return

        meta = asset.meta or AssetMeta()

        # Update meta fields if provided
        if payload.name is not None:
            meta.name = payload.name
        if payload.vis_type is not None:
            try:
                meta.vis_type = VIS_TYPE(payload.vis_type)
            except Exception:
                meta.vis_type = VIS_TYPE.UNSPECIFIED
        if payload.prompt is not None:
            meta.prompt = payload.prompt
        if payload.negative_prompt is not None:
            meta.negative_prompt = payload.negative_prompt
        if payload.character_name is not None:
            meta.character_name = payload.character_name
        if payload.tags is not None:
            meta.tags = payload.tags
        if payload.reference is not None:
            # Convert list of strings to list of VIS_TYPE enums
            try:
                meta.reference = [VIS_TYPE(ref) for ref in payload.reference if ref]
            except (ValueError, TypeError) as e:
                log.warning(
                    "Invalid reference vis_types",
                    error=str(e),
                    reference=payload.reference,
                )
                meta.reference = []
        if payload.reference_assets is not None:
            meta.reference_assets = payload.reference_assets
        if payload.analysis is not None:
            meta.analysis = payload.analysis
        meta.cover_bbox = payload.cover_bbox

        # Re-evaluate format and resolution based on actual image bytes
        try:
            asset_bytes = self.scene.assets.get_asset_bytes(asset_id)
            if asset_bytes:
                img = Image.open(io.BytesIO(asset_bytes))
                width, height = img.size
                meta.format = AssetMeta.determine_format(width, height)
                meta.resolution = AssetMeta.resolution_from_size(width, height)
        except Exception as e:
            log.error("reevaluate_format_failed", error=e)

        # Assign back
        self.scene.assets.update_asset_meta(asset_id, meta)

        # Notify - emit status to update frontend, but don't save scene file
        # (asset metadata is stored in library.json, not in the scene file)
        self.scene.emit_status()
        await self.signal_operation_done(signal_only=True)

    async def handle_set_scene_cover_image(self, data: dict):
        payload = SetSceneCoverImagePayload(**data)
        asset_id = payload.asset_id

        try:
            if not self.scene.assets.validate_asset_id(asset_id):
                await self.signal_operation_failed("Invalid asset_id")
                return

            await self.scene.assets.set_scene_cover_image(asset_id, override=True)

            # Request the asset for frontend
            self.websocket_handler.request_scene_assets([asset_id])

            await self.scene.attempt_auto_save()
            await self.signal_operation_done()
        except Exception as e:
            log.error("set_scene_cover_image_failed", error=e)
            await self.signal_operation_failed(f"Failed to set scene cover image: {e}")

    async def handle_set_character_cover_image(self, data: dict):
        payload = SetCharacterCoverImagePayload(**data)
        asset_id = payload.asset_id
        character_name = payload.character_name

        try:
            if not self.scene.assets.validate_asset_id(asset_id):
                await self.signal_operation_failed("Invalid asset_id")
                return

            character = self.scene.get_character(character_name)
            if not character:
                await self.signal_operation_failed(
                    f"Character not found: {character_name}"
                )
                return

            await self.scene.assets.set_character_cover_image(
                character, asset_id, override=True
            )

            # Request the asset for frontend
            self.websocket_handler.request_scene_assets([asset_id])

            await self.scene.attempt_auto_save()
            await self.signal_operation_done()
        except Exception as e:
            log.error("set_character_cover_image_failed", error=e)
            await self.signal_operation_failed(
                f"Failed to set character cover image: {e}"
            )

    async def handle_set_character_avatar(self, data: dict):
        payload = SetCharacterAvatarPayload(**data)
        asset_id = payload.asset_id
        character_name = payload.character_name
        avatar_type = payload.avatar_type

        try:
            if not self.scene.assets.validate_asset_id(asset_id):
                await self.signal_operation_failed("Invalid asset_id")
                return

            character = self.scene.get_character(character_name)
            if not character:
                await self.signal_operation_failed(
                    f"Character not found: {character_name}"
                )
                return

            if avatar_type == "current":
                await self.scene.assets.set_character_current_avatar(
                    character, asset_id, override=True
                )
            else:
                await self.scene.assets.set_character_avatar(
                    character, asset_id, override=True
                )

            # Request the asset for frontend
            self.websocket_handler.request_scene_assets([asset_id])

            await self.scene.attempt_auto_save()
            await self.signal_operation_done()
        except Exception as e:
            log.error("set_character_avatar_failed", error=e, avatar_type=avatar_type)
            await self.signal_operation_failed(
                f"Failed to set character {avatar_type} avatar: {e}"
            )

    async def handle_search(self, data: dict):
        """
        Search assets by vis_type, character_name, tags, or reference vis_types.
        Returns asset IDs that match the criteria.
        """
        payload = SearchAssetsPayload(**data)

        try:
            # Convert string vis_type to VIS_TYPE enum if provided
            vis_type_enum = None
            if payload.vis_type:
                try:
                    vis_type_enum = VIS_TYPE(payload.vis_type)
                except ValueError:
                    log.warning(
                        "search_assets", error=f"Invalid vis_type: {payload.vis_type}"
                    )
                    vis_type_enum = None

            # Convert reference_vis_types strings to VIS_TYPE enums if provided
            reference_vis_types_enums = None
            if payload.reference_vis_types:
                try:
                    reference_vis_types_enums = [
                        VIS_TYPE(rt) for rt in payload.reference_vis_types
                    ]
                except ValueError as e:
                    log.warning(
                        "search_assets", error=f"Invalid reference_vis_types: {e}"
                    )
                    reference_vis_types_enums = None

            matching_asset_ids = self.scene.assets.search_assets(
                vis_type=vis_type_enum,
                character_name=payload.character_name,
                tags=payload.tags,
                tag_match_mode=TAG_MATCH_MODE.ALL,
                reference_vis_types=reference_vis_types_enums,
            )

            self.websocket_handler.queue_put(
                {
                    "type": "asset_search_results",
                    "asset_ids": matching_asset_ids,
                    "vis_type": payload.vis_type,
                    "character_name": payload.character_name,
                    "tags": payload.tags,
                    "reference_vis_types": payload.reference_vis_types,
                }
            )
        except Exception as e:
            log.error("search_assets", error=str(e))
            self.websocket_handler.queue_put(
                {
                    "type": "asset_search_results",
                    "asset_ids": [],
                    "error": str(e),
                }
            )

    async def handle_update_message_asset(self, data: dict):
        """
        Update a message's asset.

        If character_name is provided, also updates the character's current avatar.
        This handles both avatar selection (with character_name) and generic asset
        selection for scene illustrations and cards (without character_name).
        """
        payload = UpdateMessageAssetPayload(**data)
        asset_id = payload.asset_id
        message_id = payload.message_id
        character_name = payload.character_name

        try:
            # Validate asset exists
            if not self.scene.assets.validate_asset_id(asset_id):
                await self.signal_operation_failed("Invalid asset_id")
                return

            # If character_name is provided, get the character and validate it
            character = None
            if character_name:
                character = self.scene.get_character(character_name)
                if not character:
                    await self.signal_operation_failed(
                        f"Character not found: {character_name}"
                    )
                    return

            # Update the message's asset
            message = await self.scene.assets.update_message_asset(message_id, asset_id)
            if message is None:
                await self.signal_operation_failed(
                    f"Message not found or invalid: {message_id}"
                )
                return

            # If we have a character and the asset is a portrait, set the character's current avatar
            if character:
                asset = self.scene.assets.get_asset(asset_id)
                if asset.meta.vis_type == VIS_TYPE.CHARACTER_PORTRAIT:
                    await self.scene.assets.set_character_current_avatar(
                        character, asset_id, override=True
                    )

            # Request the asset for frontend
            self.websocket_handler.request_scene_assets([asset_id])

            await self.scene.attempt_auto_save()
            await self.signal_operation_done()
        except Exception as e:
            log.error("update_message_asset_failed", error=e)
            await self.signal_operation_failed(f"Failed to update message asset: {e}")

    async def handle_clear_message_asset(self, data: dict):
        """
        Clear a message's asset.
        """
        payload = ClearMessageAssetPayload(**data)
        message_id = payload.message_id

        try:
            # Clear the message's asset
            message = await self.scene.assets.clear_message_asset(message_id)
            if message is None:
                await self.signal_operation_failed(
                    f"Message not found or invalid: {message_id}"
                )
                return

            await self.scene.attempt_auto_save()
            await self.signal_operation_done()
        except Exception as e:
            log.error("clear_message_asset_failed", error=e)
            await self.signal_operation_failed(f"Failed to clear message asset: {e}")
