import uuid
from typing import Annotated, Literal

import pydantic

from talemate.knowledge.perspective_models import (
    Acquisition,
    SourceReference,
    AudienceRecord,
)

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
FactSource = Literal[
    "summary", "manual", "offscreen", "perspective", "disclosure", "dialogue"
]
FactsStatus = Literal["ok", "failed"]
KnownKind = Literal["witnessed", "told", "granted", "inferred"]
FactImportance = Annotated[int, pydantic.Field(strict=True, ge=1, le=3)]

FACT_SOURCE_LABELS: dict[FactSource, str] = {
    "summary": "history entry",
    "manual": "manual entry",
    "offscreen": "offscreen life",
    "perspective": "perception",
    "disclosure": "disclosure",
    "dialogue": "dialogue",
}


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
    ts: int | None = None
    note: str | None = None


class ParsedFact(pydantic.BaseModel):
    """One item of the FACTS list the summary call returns."""

    text: str = pydantic.Field(min_length=1)
    importance: FactImportance = 2
    subjects: list[str] = pydantic.Field(default_factory=list)
    known_by: list[str] = pydantic.Field(default_factory=list)
    supersedes: str | None = None
    time_scope: str | None = None

    @pydantic.model_serializer(mode="wrap")
    def serialize_time_scope(self, handler):
        data = handler(self)
        if self.time_scope is None:
            data.pop("time_scope", None)
        return data

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


class Topic(pydantic.BaseModel):
    """A cluster of facts; centroids live on the memory agent, not here."""

    id: str
    name: str
    # False when no subject named the topic and `name` is a placeholder
    named: bool = True
    fact_ids: list[str] = pydantic.Field(default_factory=list)


class KnownFact(pydantic.BaseModel):
    """One fact a character knows, as the World State knowledge hub lists it."""

    id: str
    text: str
    topic: str | None = None
    ts: int | None = None
    last_seen_ts: int | None = None
    time: str = "Time unknown"


class TopicFact(pydantic.BaseModel):
    id: str
    text: str
    known: bool
    how: KnownKind | None = None
    source: str
    source_id: str | None = None
    ts: int | None = None
    time: str = "Time unknown"


class TopicCoverage(pydantic.BaseModel):
    """How much of one topic a character knows."""

    id: str
    name: str
    total: int
    known: int

    @property
    def share(self) -> float:
        return self.known / self.total if self.total else 0.0


class FactContribution(AudienceRecord):
    source: SourceReference
    acquired: Acquisition
    text: str = pydantic.Field(min_length=1)
    importance: FactImportance = 2
    subjects: tuple[str, ...] = ()
    time_scope: str | None = None
    supersedes: str | None = None

    @pydantic.model_validator(mode="after")
    def concrete_view(self):
        if self.source.kind != "disclosure" and (
            self.source.view_id is None or self.source.view_revision is None
        ):
            raise ValueError(
                "Fact contributions require a specific source view revision"
            )
        return self

    @property
    def identity(self):
        return self.source.key, self.source.view_id

    @property
    def equivalence_key(self):
        # A calendar date is a qualifier, not an occurrence identity.
        return self.text, tuple(sorted(self.subjects)), self.source.key, self.time_scope


class Fact(pydantic.BaseModel):
    id: str
    text: str
    importance: FactImportance = 2
    ts: int | None = None
    archive_id: str | None = None
    message_id: int | None = None
    message_digest: str | None = None
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

    contributions: tuple[FactContribution, ...] = ()

    @pydantic.model_serializer(mode="wrap")
    def serialize_contributions(self, handler):
        data = handler(self)
        if not self.contributions:
            data.pop("contributions", None)
        for key in ("message_id", "message_digest"):
            if data.get(key) is None:
                data.pop(key, None)
        return data
