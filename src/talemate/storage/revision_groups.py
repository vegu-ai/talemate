import json
import sqlite3
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import blobs
from .changelog import (
    Manifest,
    MessageChunk,
    RevisionEntry,
    RevisionMissingError,
    SnapshotStore,
    _ancestry_cte,
    _at_revision,
    _revision,
    _save,
)

SNIPPET_LENGTH = 300

SpanRule = Callable[[dict], bool]


class RevisionGroupQuery(BaseModel):
    span: int = Field(default=1, ge=1, le=1000)
    limit: int = Field(default=50, ge=1, le=200)
    before_rev: int | None = Field(default=None, ge=0)
    since_ts: int | None = None
    until_ts: int | None = None
    search: str = ""
    include_rev: int | None = Field(default=None, ge=0)

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value: str) -> str:
        return value.strip().casefold()


class GroupMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    typ: str
    text: str
    hidden: bool


class RevisionGroup(BaseModel):
    first_message: int
    last_message: int
    message: GroupMessage | None = None
    damaged: bool = False
    revisions: list[RevisionEntry]


class RevisionGroupPage(BaseModel):
    groups: list[RevisionGroup]
    next_before_rev: int | None
    total_revisions: int
    latest_rev: int | None = None


class _SpanMessage(BaseModel):
    """A counted message, or a placeholder for content that cannot be read."""

    model_config = ConfigDict(frozen=True)

    key: tuple[int | str, str]
    message: GroupMessage | None = None
    search_text: str = ""

    @classmethod
    def damaged(cls, digest: str) -> "_SpanMessage":
        return cls(key=("damaged", digest))


def _content(data: dict, text: str) -> str:
    if data.get("typ") == "character" and ":" in text:
        return text.split(":", 1)[1]
    return text


class _Story(BaseModel):
    """The counted messages of one revision, kept per history chunk."""

    chunks: list[str]
    parts: list[tuple[_SpanMessage, ...]]
    # A placeholder counts as one message, so the counted numbers are not reliable.
    uncertain: bool = False

    @property
    def counted(self) -> int:
        return sum(len(part) for part in self.parts)

    def messages_from(self, index: int) -> list[_SpanMessage]:
        return [message for part in self.parts[index:] for message in part]

    def tail(self, count: int) -> list[_SpanMessage]:
        messages = []
        for part in reversed(self.parts):
            if len(messages) >= count:
                break
            messages[:0] = part
        return messages[len(messages) - count :] if count else []

    def newest(self) -> _SpanMessage | None:
        for part in reversed(self.parts):
            if part:
                return part[-1]
        return None

    def continues_into(self, newer: "_Story") -> bool:
        """True when this story is an unchanged prefix of the newer one."""
        index = 0
        for own, other in zip(self.chunks, newer.chunks):
            if own != other:
                break
            index += 1
        own = [message.key for message in self.messages_from(index)]
        other = [message.key for message in newer.messages_from(index)]
        return other[: len(own)] == own


class _StoryReader:
    """Reads counted messages by digest; a digest's content never changes."""

    def __init__(self, connection: sqlite3.Connection, counts: SpanRule):
        self.connection = connection
        self.counts = counts
        self.chunk_parts: dict[str, tuple[_SpanMessage, ...]] = {}
        self.damaged_chunks: set[str] = set()
        self.messages: dict[str, _SpanMessage | None] = {}

    def _message(self, digest: str) -> _SpanMessage | None:
        """The counted message, or None when it does not count."""
        if digest not in self.messages:
            try:
                data = json.loads(blobs.get(self.connection, digest).data)
                if not self.counts(data):
                    self.messages[digest] = None
                else:
                    text = str(data.get("message") or "")
                    self.messages[digest] = _SpanMessage(
                        key=(data["id"], text),
                        message=GroupMessage(
                            id=data["id"],
                            typ=data.get("typ") or "scene",
                            text=text[:SNIPPET_LENGTH],
                            hidden=bool(int(data.get("flags") or 0) & 1),
                        ),
                        search_text=_content(data, text).casefold(),
                    )
            except (blobs.BlobCorruptedError, ValueError, KeyError, TypeError):
                self.messages[digest] = _SpanMessage.damaged(digest)
        return self.messages[digest]

    def _chunk(self, digest: str) -> tuple[_SpanMessage, ...]:
        if digest not in self.chunk_parts:
            try:
                digests = MessageChunk.model_validate_json(
                    blobs.get(self.connection, digest).data
                ).messages
            except (blobs.BlobCorruptedError, ValidationError):
                self.chunk_parts[digest] = (_SpanMessage.damaged(digest),)
                self.damaged_chunks.add(digest)
            else:
                messages = [self._message(message) for message in digests]
                self.chunk_parts[digest] = tuple(m for m in messages if m)
                if any(m and m.message is None for m in messages):
                    self.damaged_chunks.add(digest)
        return self.chunk_parts[digest]

    def story(self, manifest: Manifest) -> _Story:
        chunks = manifest.history_chunks or []
        # The parts hold validated messages; validation would walk every message of every revision.
        parts = [self._chunk(digest) for digest in chunks]
        return _Story.model_construct(
            chunks=chunks,
            parts=parts,
            uncertain=any(digest in self.damaged_chunks for digest in chunks),
        )


class _OpenGroup(BaseModel):
    bucket: int
    story: _Story
    revisions: list[RevisionEntry]

    def matches(self, search: str, span: int) -> bool:
        if not search:
            return True
        if self.bucket == 0:
            return False
        messages = self.story.tail(self.story.counted - (self.bucket - 1) * span)
        return any(search in message.search_text for message in messages)

    def close(self, span: int) -> RevisionGroup:
        counted = self.story.counted
        newest = self.story.newest()
        numbered = self.bucket and not self.story.uncertain
        return RevisionGroup(
            first_message=(self.bucket - 1) * span + 1 if numbered else 0,
            last_message=min(self.bucket * span, counted) if numbered else 0,
            message=newest.message if newest else None,
            damaged=newest is not None and newest.message is None,
            revisions=self.revisions,
        )


def _bucket(counted: int, span: int) -> int:
    return -(-counted // span)


def _included_rev(
    connection: sqlite3.Connection, filename: str, query: RevisionGroupQuery
) -> int | None:
    """The revision a page must reach, when the date range keeps it."""
    if query.include_rev is None:
        return None
    try:
        ts = _at_revision(connection, filename, query.include_rev).ts
    except RevisionMissingError:
        return None
    if (query.since_ts is not None and ts < query.since_ts) or (
        query.until_ts is not None and ts > query.until_ts
    ):
        return None
    return query.include_rev


def _read_groups(
    connection: sqlite3.Connection,
    filename: str,
    query: RevisionGroupQuery,
    counts: SpanRule,
) -> RevisionGroupPage:
    save = _save(connection, filename)
    if save is None:
        return RevisionGroupPage(groups=[], next_before_rev=None, total_revisions=0)
    ancestry = _ancestry_cte()
    total = connection.execute(
        ancestry + "SELECT COUNT(*) FROM ancestry", {"head": save.head_id}
    ).fetchone()[0]
    rows = connection.execute(
        ancestry + "SELECT r.id, r.parent_id, r.rev, r.ts, r.origin, r.origin_id, "
        "r.manifest, (SELECT c.origin_id FROM changelog_revisions c "
        "JOIN ancestry ca ON c.id=ca.id WHERE c.parent_id=r.id) AS child_origin "
        "FROM changelog_revisions r JOIN ancestry a ON r.id=a.id "
        "WHERE (:before IS NULL OR r.rev < :before) "
        "AND (:since IS NULL OR r.ts >= :since) "
        "AND (:until IS NULL OR r.ts <= :until) ORDER BY r.rev DESC",
        {
            "head": save.head_id,
            "before": query.before_rev,
            "since": query.since_ts,
            "until": query.until_ts,
        },
    )
    latest = _revision(connection, save.head_id).rev
    include = _included_rev(connection, filename, query)
    reader = _StoryReader(connection, counts)
    groups: list[RevisionGroup] = []
    current: _OpenGroup | None = None
    previous: _Story | None = None

    def finish(group: _OpenGroup):
        if group.matches(query.search, query.span):
            groups.append(group.close(query.span))

    def result(next_before_rev: int | None) -> RevisionGroupPage:
        kept = groups
        if len(groups) > query.limit and not any(
            entry.rev == include for group in groups for entry in group.revisions
        ):
            # The extension to reach `include` was in vain: a filter hid its row.
            kept = groups[: query.limit]
            next_before_rev = kept[-1].revisions[-1].rev
        return RevisionGroupPage(
            groups=kept,
            next_before_rev=next_before_rev,
            total_revisions=total,
            latest_rev=latest,
        )

    def page_full(group: _OpenGroup) -> bool:
        oldest = group.revisions[-1].rev
        return len(groups) >= query.limit and (include is None or oldest <= include)

    for row in rows:
        manifest = Manifest.model_validate_json(row["manifest"])
        story = reader.story(manifest)
        bucket = _bucket(story.counted, query.span)
        entry = RevisionEntry(
            message_count=manifest.message_count,
            rev=row["rev"],
            ts=row["ts"],
            origin=row["origin"],
            inherited=row["origin_id"] != save.id,
            is_base=row["parent_id"] is None,
            is_fork=row["id"] == save.fork_id
            or (
                row["child_origin"] is not None
                and row["child_origin"] != row["origin_id"]
            ),
        )
        follows = previous is not None and story.continues_into(previous)
        previous = story
        if current is not None and bucket == current.bucket and follows:
            current.revisions.append(entry)
            continue
        if current is not None:
            finish(current)
            if page_full(current):
                return result(current.revisions[-1].rev)
        current = _OpenGroup(bucket=bucket, story=story, revisions=[entry])
    if current is not None:
        finish(current)
    return result(None)


async def revision_groups(
    store: SnapshotStore, filename: str, query: RevisionGroupQuery, counts: SpanRule
) -> RevisionGroupPage:
    if not store.db.path.exists():
        return RevisionGroupPage(groups=[], next_before_rev=None, total_revisions=0)
    return await store.db.read(
        lambda connection: _read_groups(connection, filename, query, counts)
    )
