import pydantic
import re
from typing import Callable, Literal

from talemate.ux.schema import Note, Field

MAX_TAG_LENGTH: int = 64  # Maximum number of characters per tag (configurable)
MAX_TAGS_PER_VOICE: int = 10  # Maximum number of tags per voice (configurable)

__all__ = [
    "APIStatus",
    "Chunk",
    "GenerationContext",
    "VoiceProvider",
    "Voice",
    "VoiceLibrary",
    "VoiceWeight",
    "VoiceMixer",
    "VoiceGenerationEmission",
]


class VoiceProvider(pydantic.BaseModel):
    name: str
    voice_parameters: list[Field] = pydantic.Field(default_factory=list)
    allow_model_override: bool = True


class VoiceWeight(pydantic.BaseModel):
    id: str
    weight: float


class VoiceMixer(pydantic.BaseModel):
    voices: list[VoiceWeight]


class Voice(pydantic.BaseModel):
    # arbitrary voice label to allow a human to easily identify the voice
    label: str

    # voice provider, this would be the TTS api in the voice
    provider: str

    # voice id as known to the voice provider
    provider_id: str

    # allows to also override to a specific model
    provider_model: str | None = None

    # free-form tags for categorizing the voice (e.g. "male", "energetic")
    tags: list[str] = pydantic.Field(default_factory=list)

    # provider specific parameters for the voice
    parameters: dict[str, str | float | int | bool] = pydantic.Field(
        default_factory=dict
    )

    @pydantic.field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: list[str]):
        """Validate tag list length and individual tag length."""
        if len(v) > MAX_TAGS_PER_VOICE:
            raise ValueError(
                f"Too many tags – maximum {MAX_TAGS_PER_VOICE} tags are allowed per voice"
            )
        for tag in v:
            if len(tag) > MAX_TAG_LENGTH:
                raise ValueError(
                    f"Tag '{tag}' exceeds maximum length of {MAX_TAG_LENGTH} characters"
                )
        return v

    model_config = pydantic.ConfigDict(validate_assignment=True, exclude_none=True)

    @pydantic.computed_field(description="The unique identifier for the voice")
    @property
    def id(self) -> str:
        return f"{self.provider}:{self.provider_id}"


class VoiceLibrary(pydantic.BaseModel):
    version: int = 1
    voices: dict[str, Voice] = pydantic.Field(default_factory=dict)

    def get_voice(self, voice_id: str) -> Voice | None:
        return self.voices.get(voice_id)


class Chunk(pydantic.BaseModel):
    text: list[str] = pydantic.Field(default_factory=list)
    type: Literal["dialogue", "exposition"]
    character_name: str | None = None
    api: str | None = None
    voice: Voice | None = None
    model: str | None = None
    generate_fn: Callable[[str], bytes] | None = None

    @property
    def cleaned_text(self) -> str:
        cleaned: str = self.text[0].replace("*", "").replace('"', "")

        # troublemakers
        cleaned = cleaned.replace("—", " - ").replace("…", "...")

        # replace any grouped up whitespace with a single space
        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip().strip(",").strip()

    @property
    def sub_chunks(self) -> list["Chunk"]:
        if len(self.text) == 1:
            return [self]

        return [
            Chunk(
                text=[text],
                type=self.type,
                character_name=self.character_name,
                api=self.api,
                voice=self.voice,
                model=self.model,
                generate_fn=self.generate_fn,
            )
            for text in self.text
        ]


class GenerationContext(pydantic.BaseModel):
    chunks: list[Chunk] = pydantic.Field(default_factory=list)


class VoiceGenerationEmission(pydantic.BaseModel):
    context: GenerationContext
    wav_bytes: bytes | None = None


class ModelChoice(pydantic.BaseModel):
    label: str
    value: str


class APIStatus(pydantic.BaseModel):
    """Status of an API."""

    api: str
    enabled: bool
    ready: bool
    configured: bool
    provider: VoiceProvider
    messages: list[Note] = pydantic.Field(default_factory=list)
    supports_mixing: bool = False

    default_model: str | None = None
    model_choices: list[ModelChoice] = pydantic.Field(default_factory=list)
