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
EdgeSource = Literal["told", "granted", "inferred", "manual"]


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


class KnowledgeEdge(pydantic.BaseModel):
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:8])
    character: str
    target: str
    kind: EdgeKind = "grant"
    source: EdgeSource = "manual"
    ts: int | None = None
    note: str | None = None
