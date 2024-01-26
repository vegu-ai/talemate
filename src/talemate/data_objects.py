from dataclasses import dataclass

__all__ = [
    "ArchiveEntry",
]


@dataclass
class ArchiveEntry:
    text: str
    start: int = None
    end: int = None
    ts: str = None
