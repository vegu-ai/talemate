import base64
import io

import pydantic
import structlog
from PIL import Image

from talemate.server.websocket_plugin import Plugin
from talemate.scene_assets import (
    AssetMeta,
    set_scene_cover_image,
    set_character_cover_image,
)
from talemate.agents.visual.schema import VIS_TYPE, GEN_TYPE

log = structlog.get_logger("talemate.server.scene_assets")


class DeleteAssetPayload(pydantic.BaseModel):
    asset_id: str


class AddAssetPayload(pydantic.BaseModel):
    content: str  # data URL
    vis_type: str | None = None
    character_name: str | None = None


class EditAssetMetaPayload(pydantic.BaseModel):
    asset_id: str
    name: str | None = None
    vis_type: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    character_name: str | None = None
    tags: list[str] | None = None
    reference: list[str] | None = None
    analysis: str | None = None


class SetSceneCoverImagePayload(pydantic.BaseModel):
    asset_id: str


class SetCharacterCoverImagePayload(pydantic.BaseModel):
    asset_id: str
    character_name: str


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
            asset = self.scene.assets.add_asset_from_image_data(payload.content)

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
            self.scene.assets.assets[asset.id].meta = meta

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
        if payload.analysis is not None:
            meta.analysis = payload.analysis

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
        self.scene.assets.assets[asset_id].meta = meta

        # Notify
        await self.scene.attempt_auto_save()
        await self.signal_operation_done()

    async def handle_set_scene_cover_image(self, data: dict):
        payload = SetSceneCoverImagePayload(**data)
        asset_id = payload.asset_id

        try:
            if not self.scene.assets.validate_asset_id(asset_id):
                await self.signal_operation_failed("Invalid asset_id")
                return

            await set_scene_cover_image(self.scene, asset_id, override=True)

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

            await set_character_cover_image(
                self.scene, character, asset_id, override=True
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
