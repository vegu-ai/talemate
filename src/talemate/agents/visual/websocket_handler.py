import pydantic
import structlog

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.scene_assets import AssetMeta
from talemate.world_state.manager import WorldStateManager

from .schema import GenerationRequest, AnalysisRequest, VIS_TYPE

__all__ = [
    "VisualWebsocketHandler",
]

log = structlog.get_logger("talemate.server.visual")


class SetCoverImagePayload(pydantic.BaseModel):
    base64: str


class RegeneratePayload(pydantic.BaseModel):
    generation_request: GenerationRequest


class GeneratePayload(pydantic.BaseModel):
    generation_request: GenerationRequest


class SaveImagePayload(pydantic.BaseModel):
    base64: str
    generation_request: GenerationRequest
    name: str | None = None
    reference: list[VIS_TYPE] | None = None


class AnalyzeAssetPayload(pydantic.BaseModel):
    asset_id: str
    prompt: str
    save: bool = False


class UpdateArtStylePayload(pydantic.BaseModel):
    visual_style_template: str | None = None


class VisualWebsocketHandler(Plugin):
    router = "visual"

    async def handle_regenerate(self, data: dict):
        """
        Regenerate the image based on the context.
        """

        payload = RegeneratePayload(**data)
        visual = get_agent("visual")
        await visual.generate(payload.generation_request)

    async def handle_generate(self, data: dict):
        """
        Generate an image from a GenerationRequest.
        """
        payload = GeneratePayload(**data)
        visual = get_agent("visual")
        await visual.generate(payload.generation_request)

    async def handle_cover_image(self, data: dict):
        """
        Sets the cover image for a character and the scene.
        """

        payload = SetCoverImagePayload(**data)
        scene = self.scene
        # Legacy endpoint kept for backward compatibility (not used by new UI)
        asset = await scene.assets.add_asset_from_image_data(payload.base64)
        scene.assets.cover_image = asset.id
        scene.emit_status()
        self.websocket_handler.request_scene_assets([asset.id])
        return

    async def handle_save_image(self, data: dict):
        """
        Saves the provided base64 image as a scene asset and assigns AssetMeta from the GenerationRequest.
        """
        payload = SaveImagePayload(**data)
        scene = self.scene

        asset = await scene.assets.add_asset_from_image_data(payload.base64)

        # Populate AssetMeta from GenerationRequest
        meta = AssetMeta(
            name=payload.name,
            vis_type=payload.generation_request.vis_type,
            gen_type=payload.generation_request.gen_type,
            character_name=payload.generation_request.character_name,
            prompt=payload.generation_request.prompt,
            negative_prompt=payload.generation_request.negative_prompt,
            format=payload.generation_request.format,
            resolution=payload.generation_request.resolution,
            sampler_settings=payload.generation_request.sampler_settings,
            reference_assets=payload.generation_request.reference_assets,
        )

        # Set reference field if provided (e.g., for first generated cover/avatar)
        if payload.reference:
            meta.reference = payload.reference

        # Update asset meta and save to library.json
        scene.assets.update_asset_meta(asset.id, meta)

        # Notify frontend and update scene status
        scene.emit_status()
        self.websocket_handler.request_scene_assets([asset.id])
        await self.signal_operation_done(signal_only=True)

    async def handle_analyze_asset(self, data: dict):
        """
        Analyzes an existing asset using the image analysis backend.
        """
        payload = AnalyzeAssetPayload(**data)
        visual = get_agent("visual")

        request = AnalysisRequest(
            prompt=payload.prompt,
            asset_id=payload.asset_id,
            save=payload.save,
        )

        await visual.analyze(request)

    async def handle_cancel_generation(self, data: dict):
        """
        Cancels the current image generation task.
        """
        visual = get_agent("visual")
        await visual.cancel_generation()

    async def handle_cancel_analysis(self, data: dict):
        """
        Cancels the current image analysis task.
        """
        visual = get_agent("visual")
        await visual.cancel_analysis()

    async def handle_update_art_style(self, data: dict):
        """
        Updates the visual style template in scene settings.
        """
        payload = UpdateArtStylePayload(**data)
        scene = self.scene
        manager = WorldStateManager(scene)

        await manager.update_scene_settings(
            visual_style_template=payload.visual_style_template
        )

        # Emit status to update the UI
        scene.emit_status()
        visual = get_agent("visual")
        if visual:
            await visual.emit_status()
