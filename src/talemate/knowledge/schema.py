import uuid
from typing import Literal

import pydantic

__all__ = [
    "EntryVisibility",
    "KnowledgeEdge",
    "VisibilityMode",
    "EdgeKind",
    "EdgeSource",
]

VisibilityMode = Literal["everyone", "owner", "list"]
EdgeKind = Literal["grant", "revoke"]
EdgeSource = Literal["told", "granted", "inferred", "manual", "director"]


def is_memory_attribute(name: str) -> bool:
    """Whether an attribute has an authored memory/visibility entry."""
    return not name.startswith("_") and name.lower() not in ("name", "scenario_context")


class EntryVisibility(pydantic.BaseModel):
    mode: VisibilityMode = "everyone"
    characters: list[str] = pydantic.Field(default_factory=list)

    def allows(self, character: str, owner: str | None) -> bool:
        if self.mode == "everyone":
            return True
        if character == owner:
            return True
        if self.mode == "list":
            return character in self.characters
        return False


class ReinforcementEntry(pydantic.BaseModel):
    """A generated entry's passage; None records that no passage is available."""

    source_id: pydantic.PositiveInt | None = None


class KnowledgeEdge(pydantic.BaseModel):
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:8])
    character: str
    target: str
    kind: EdgeKind = "grant"
    source: EdgeSource = "manual"
    message_id: int | None = None
    ts: int | None = None
    note: str | None = None
