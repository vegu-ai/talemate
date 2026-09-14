import uuid
from typing import Annotated, Literal

import pydantic

from talemate.knowledge.perspective_models import (
    Acquisition,
    SourceReference,
    AudienceRecord,
    PassageEvidence,
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
FactSource = Literal["summary", "manual", "offscreen", "perspective", "disclosure"]
FactsStatus = Literal["ok", "failed"]
KnownKind = Literal["witnessed", "told", "granted", "inferred"]
FactImportance = Annotated[int, pydantic.Field(strict=True, ge=1, le=3)]
# the opening of the scene is part of the first span but is not a message
INTRO_LINE = "intro"

FACT_SOURCE_LABELS: dict[FactSource, str] = {
    "summary": "history entry",
    "manual": "manual entry",
    "offscreen": "offscreen life",
    "perspective": "perception",
    "disclosure": "disclosure",
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
    message_id: int | None = None
    ts: int | None = None
    note: str | None = None


class ParsedFact(pydantic.BaseModel):
    """One item of the FACTS list the summary call returns."""

    text: str = pydantic.Field(min_length=1)
    importance: FactImportance = 2
    subjects: list[str] = pydantic.Field(default_factory=list)
    known_by: list[str] = pydantic.Field(default_factory=list)
    supersedes: str | None = None
    restates: str | None = None
    # the span line that establishes the fact; INTRO_LINE names the opening
    message_id: int | Literal["intro"] | None = None
    time_scope: str | None = None
    evidence_id: pydantic.StrictStr | None = None

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

    @pydantic.field_validator("supersedes", "restates", mode="before")
    @classmethod
    def _fact_link(cls, value):
        if value in (None, "", "none", "null", "None"):
            return None
        return str(value).strip()

    @pydantic.field_validator("message_id", mode="before")
    @classmethod
    def _message_id(cls, value):
        # an unreadable id is None: the caller drops the fact rather than guess
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        text = str(value).strip().strip("[]")
        if text.lower() == INTRO_LINE:
            return INTRO_LINE
        try:
            return int(text)
        except ValueError:
            return None


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
    importance: FactImportance = 2
    subjects: list[str] = pydantic.Field(default_factory=list)
    known: bool
    how: KnownKind | None = None
    source: str
    source_id: str | None = None
    ts: int | None = None
    time: str = "Time unknown"
    reason: str | None = None


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
    message_id: int | None = None
    time_scope: str | None = None
    supersedes: str | None = None
    evidence: PassageEvidence | None = None
    inferred_from: SourceReference | None = None
    citation_rejected: bool = False
    evidence_competitors: tuple[PassageEvidence, ...] = ()

    @pydantic.model_validator(mode="after")
    def concrete_view(self):
        if self.source.kind != "disclosure" and (
            self.source.view_id is None or self.source.view_revision is None
        ):
            raise ValueError(
                "Fact contributions require a specific source view revision"
            )
        if self.inferred_from is not None and (
            self.evidence is None
            or self.inferred_from.view_id is None
            or self.inferred_from.view_revision is None
            or self.inferred_from.key != self.source.key
        ):
            raise ValueError(
                "Inferred contributions require evidence and a donor view of the same source"
            )
        return self

    @property
    def identity(self):
        return self.source.key, self.source.view_id

    @property
    def equivalence_key(self):
        # A calendar date is a qualifier, not an occurrence identity.
        return (
            self.text,
            tuple(sorted(self.subjects)),
            self.source.key,
            self.time_scope,
        )


class FactRestatement(pydantic.BaseModel):
    """A later span's message that repeats an already recorded fact."""

    # None for a restatement by a static entry, which has no message
    message_id: int | None = None
    message_digest: str | None = None
    archive_id: str | None = None
    # the restating message's audience and scene time: a restatement can
    # become the origin, and the origin is always the earliest message
    present: list[str] | None = None
    ts: int | None = None


class Fact(pydantic.BaseModel):
    id: str
    text: str
    importance: FactImportance = 2
    # scene time at the source message; the entry's time when there is none
    ts: int | None = None
    # the base entry whose extraction recorded the fact
    archive_id: str | None = None
    # the message the fact came from; None for manual, offscreen, disclosure
    # and static-entry facts, which have no message by design
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
    # set by the author's editor, one per field it protects: the record's own
    # text or link then wins over what its contributions carry
    text_edited: bool = False
    link_edited: bool = False

    contributions: tuple[FactContribution, ...] = ()
    restated_by: tuple[FactRestatement, ...] = ()

    @pydantic.model_serializer(mode="wrap")
    def serialize_contributions(self, handler):
        data = handler(self)
        if not self.contributions:
            data.pop("contributions", None)
        if not self.restated_by:
            data.pop("restated_by", None)
        for key in ("text_edited", "link_edited"):
            if not getattr(self, key):
                data.pop(key, None)
        for key in ("message_id", "message_digest"):
            if data.get(key) is None:
                data.pop(key, None)
        return data
