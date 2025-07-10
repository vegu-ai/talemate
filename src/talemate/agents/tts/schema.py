import pydantic
from typing import Callable, Literal

__all__ = [
    "GenerationContext",
    "Voice",
    "VoiceLibrary",
]


class Chunk(pydantic.BaseModel):
    text: list[str] = pydantic.Field(default_factory=list)
    type: Literal["dialogue", "exposition"]
    character_name: str | None = None
    api: str | None = None
    voice_id: str | None = None
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
                voice_id=self.voice_id,
                model=self.model,
                generate_fn=self.generate_fn,
            )
            for text in self.text
        ]


class GenerationContext(pydantic.BaseModel):
    chunks: list[Chunk] = pydantic.Field(default_factory=list)


class Voice(pydantic.BaseModel):
    value: str
    label: str


class VoiceLibrary(pydantic.BaseModel):
    api: str
    voices: list[Voice] = pydantic.Field(default_factory=list)
    last_synced: float = None
