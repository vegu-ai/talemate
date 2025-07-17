from .schema import VoiceProvider
from typing import Generator

__all__ = ["register", "provider", "providers"]

PROVIDERS = {}


class register:
    def __call__(self, cls: type[VoiceProvider]):
        PROVIDERS[cls().name] = cls
        return cls


def provider(name: str) -> VoiceProvider:
    cls = PROVIDERS.get(name)
    if not cls:
        return VoiceProvider(name=name)
    return cls()


def providers() -> Generator[VoiceProvider, None, None]:
    for cls in PROVIDERS.values():
        yield cls()
