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
FactSource = Literal["summary", "manual", "offscreen"]
FactsStatus = Literal["ok", "failed"]


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


class ParsedFact(pydantic.BaseModel):
    """One item of the FACTS list the summary call returns."""

    text: str = pydantic.Field(min_length=1)
    subjects: list[str] = pydantic.Field(default_factory=list)
    known_by: list[str] = pydantic.Field(default_factory=list)
    supersedes: str | None = None

    @pydantic.field_validator("subjects", "known_by", mode="before")
    @classmethod
    def _names(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [str(v).strip() for v in value if str(v).strip()]

    @pydantic.field_validator("supersedes", mode="before")
    @classmethod
    def _supersedes(cls, value):
        if value in (None, "", "none", "null", "None"):
            return None
        return str(value).strip()


class Fact(pydantic.BaseModel):
    id: str
    text: str
    ts: int | None = None
    archive_id: str | None = None
    present: list[str] | None = None
    subjects: list[str] = pydantic.Field(default_factory=list)
    # never "witnessed": that is derived from `present`
    known_by: dict[str, Literal["told", "granted", "inferred"]] = pydantic.Field(
        default_factory=dict
    )
    supersedes: str | None = None
    false: bool = False
    restatements: int = 0
    last_seen_ts: int | None = None
    source: FactSource = "summary"
