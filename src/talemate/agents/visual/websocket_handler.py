from typing import Union

import pydantic
import structlog

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

from .context import VisualContext, VisualContextState

__all__ = [
    "VisualWebsocketHandler",
]

log = structlog.get_logger("talemate.server.visual")


class SetCoverImagePayload(pydantic.BaseModel):
    base64: str
    context: Union[VisualContextState, None] = None


class RegeneratePayload(pydantic.BaseModel):
    context: Union[VisualContextState, None] = None


class GeneratePayload(pydantic.BaseModel):
    context: Union[VisualContextState, None] = None


class VisualWebsocketHandler(Plugin):
    router = "visual"

    async def handle_regenerate(self, data: dict):
        """
        Regenerate the image based on the context.
        """

        payload = RegeneratePayload(**data)

        context = payload.context

        visual = get_agent("visual")

        with VisualContext(**context.model_dump()):
            await visual.generate(format="")

    async def handle_cover_image(self, data: dict):
        """
        Sets the cover image for a character and the scene.
        """

        payload = SetCoverImagePayload(**data)

        context = payload.context
        scene = self.scene

        if context and context.character_name:
            character = scene.get_character(context.character_name)

            if not character:
                log.error("character not found", character_name=context.character_name)
                return

            asset = scene.assets.add_asset_from_image_data(payload.base64)

            scene.assets.cover_image = asset.id

            log.info(
                "setting character cover image", character_name=context.character_name
            )
            character.cover_image = asset.id

            scene.emit_status()
            self.websocket_handler.request_scene_assets([asset.id])

            self.websocket_handler.queue_put(
                {
                    "type": "scene_asset_character_cover_image",
                    "asset_id": asset.id,
                    "asset": self.scene.assets.get_asset_bytes_as_base64(asset.id),
                    "media_type": asset.media_type,
                    "character": character.name,
                }
            )
            return

    async def handle_visualize_character(self, data: dict):
        payload = GeneratePayload(**data)
        visual = get_agent("visual")
        await visual.generate_character_portrait(
            payload.context.character_name,
            payload.context.instructions,
            replace=payload.context.replace,
            prompt_only=payload.context.prompt_only,
        )

    async def handle_visualize_environment(self, data: dict):
        payload = GeneratePayload(**data)
        visual = get_agent("visual")
        await visual.generate_environment_background(
            instructions=payload.context.instructions,
            prompt_only=payload.context.prompt_only,
        )
