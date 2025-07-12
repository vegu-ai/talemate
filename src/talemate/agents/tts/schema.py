import pydantic
from typing import Callable, Literal

__all__ = [
    "Chunk",
    "GenerationContext",
    "Voice",
    "VoiceLibrary",
    "VoiceGenerationEmission",
]


class Voice(pydantic.BaseModel):
    # arbitrary voice label to allow a human to easily identify the voice
    label: str

    # voice provider, this would be the TTS api in the voice
    provider: str

    # voice id as known to the voice provider
    provider_id: str

    # allows to also override to a specific model
    provider_model: str | None = None

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
        # remove em-dashes
        cleaned = cleaned.replace("—", "")
        return cleaned.strip()

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
