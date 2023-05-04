from dataclasses import dataclass


@dataclass
class ArchiveEntry:
    text: str
    start: int
    end: int
