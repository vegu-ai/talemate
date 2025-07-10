import pydantic

__all__ = [
    "Voice",
    "VoiceLibrary",
]


class Voice(pydantic.BaseModel):
    value: str
    label: str


class VoiceLibrary(pydantic.BaseModel):
    api: str
    voices: list[Voice] = pydantic.Field(default_factory=list)
    last_synced: float = None
