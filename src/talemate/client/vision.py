import base64

import pydantic
import structlog

from .base import FieldGroup, ExtraField


log = structlog.get_logger("talemate.client.vision")

__all__ = [
    "VisionConfig",
    "VisionGroup",
    "vision_extra_fields",
    "OpenAIVisionMixin",
]


class VisionGroup(FieldGroup):
    name: str = "vision"
    label: str = "Vision"
    description: str = (
        "Configure vision / image analysis capabilities.\n\n"
        "Enable this if your model supports multimodal vision input. "
        "When enabled, this client can be used by the visual agent "
        "for image analysis."
    )
    icon: str = "mdi-eye"


def vision_extra_fields():
    return {
        "vision_enabled": ExtraField(
            name="vision_enabled",
            type="bool",
            label="Enable Vision",
            required=False,
            description=(
                "Enable vision/image analysis capabilities for this client. "
                "Only enable if the loaded model supports multimodal vision input."
            ),
            group=VisionGroup(),
        ),
    }


class VisionConfig(pydantic.BaseModel):
    vision_enabled: bool = False


class OpenAIVisionMixin:
    """
    Mixin for OpenAI-compatible clients that support multimodal vision.

    Provides analyze_image() which sends image bytes + text prompt
    via the /v1/chat/completions endpoint with multimodal content.

    Requires the host class to have:
    - make_client() -> AsyncOpenAI
    - model_name property -> str
    """

    @property
    def vision_capable(self) -> bool:
        return True

    @property
    def vision_enabled(self) -> bool:
        return getattr(self.client_config, "vision_enabled", False)

    @property
    def supports_vision(self) -> bool:
        return self.vision_capable and self.vision_enabled

    async def analyze_image(self, image_bytes: bytes, prompt: str) -> str:
        """
        Analyze an image using the OpenAI-compatible chat/completions endpoint
        with multimodal content blocks.

        Args:
            image_bytes: Raw image bytes (PNG, JPEG, etc.)
            prompt: Text prompt describing what to analyze

        Returns:
            The model's text analysis response.
        """
        client = self.make_client()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        self.emit_status(processing=True)
        try:
            result = await client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                },
                            },
                        ],
                    }
                ],
            )

            if not result.choices or not result.choices[0].message.content:
                raise ValueError("Vision analysis response missing content")

            return result.choices[0].message.content
        finally:
            self.emit_status(processing=False)
