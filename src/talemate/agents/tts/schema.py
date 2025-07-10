import pydantic
from typing import Callable

__all__ = [
    "GenerationContext",
    "Voice",
    "VoiceLibrary",
]

class GenerationContext(pydantic.BaseModel):
    voice_id: str
    voice_id_overridden: bool = False
    model: str | None = None
    chunks: list[str] = pydantic.Field(default_factory=list)
    generate_fn: Callable[[str], bytes] | None = None

class Voice(pydantic.BaseModel):
    value: str
    label: str


class VoiceLibrary(pydantic.BaseModel):
    api: str
    voices: list[Voice] = pydantic.Field(default_factory=list)
    last_synced: float = None
