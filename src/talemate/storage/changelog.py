import copy
import json
import time
import uuid
from pathlib import Path
from typing import Annotated

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator

from . import Database, Migration, Namespace
from . import blobs

MESSAGE_CHUNK_SIZE = 256
log = structlog.get_logger("talemate.storage.changelog")

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

NAMESPACE = Namespace(
    name="changelog",
    migrations=(
        Migration(
            version=1,
            statements=(
                "CREATE TABLE changelog_revisions (id TEXT PRIMARY KEY, "
                "parent_id TEXT REFERENCES changelog_revisions(id), rev INTEGER NOT NULL, "
                "ts INTEGER NOT NULL, origin TEXT NOT NULL, origin_id TEXT NOT NULL, manifest TEXT NOT NULL)",
                "CREATE TABLE changelog_saves (filename TEXT PRIMARY KEY, id TEXT NOT NULL, "
                "head_id TEXT NOT NULL REFERENCES changelog_revisions(id), "
                "fork_id TEXT REFERENCES changelog_revisions(id))",
                "CREATE INDEX changelog_revisions_parent ON changelog_revisions(parent_id)",
            ),
        ),
    ),
)


class RevisionMissingError(ValueError):
    pass


class ConcurrentSaveError(ValueError):
    pass


class Manifest(BaseModel):
    sections: dict[str, Digest]
    history_chunks: list[Digest] | None = None
    message_count: int = Field(default=0, ge=0)

    def digests(self) -> set[str]:
        return set(self.sections.values()) | set(self.history_chunks or [])


class MessageChunk(BaseModel):
    messages: list[Digest] = Field(max_length=MESSAGE_CHUNK_SIZE)


class Revision(BaseModel):
    id: str
    parent_id: str | None
    rev: int = Field(ge=0)
    ts: int
    origin: str
    origin_id: str
    manifest: Manifest

    @field_validator("manifest", mode="before")
    @classmethod
    def decode_json(cls, value):
        return json.loads(value) if isinstance(value, str) else value


class Save(BaseModel):
    id: str
    filename: str
    head_id: str
    fork_id: str | None = None


class RevisionEntry(BaseModel):
    message_count: int
    rev: int
    ts: int
    origin: str
    inherited: bool
    is_base: bool
    is_fork: bool


class RevisionBundle(BaseModel):
    save: Save
    revisions: list[Revision]
    blobs: list[blobs.Blob]


def _save(connection, filename: str) -> Save | None:
    row = connection.execute(
        "SELECT * FROM changelog_saves WHERE filename = ?", (filename,)
    ).fetchone()
    return Save(**dict(row)) if row else None


def _revision(connection, revision_id: str) -> Revision:
    row = connection.execute(
        "SELECT * FROM changelog_revisions WHERE id = ?", (revision_id,)
    ).fetchone()
    if row is None:
        raise RevisionMissingError("The saved revision is missing")
    return Revision(**dict(row))


def _ancestry_cte(seed: str = "SELECT :head") -> str:
    """`ancestry(id)`: the revisions `seed` selects and all of their ancestors."""
    return (
        f"WITH RECURSIVE ancestry(id) AS ({seed} UNION "
        "SELECT r.parent_id FROM changelog_revisions r JOIN ancestry a ON r.id=a.id "
        "WHERE r.parent_id IS NOT NULL) "
    )


def _ancestry(connection, head_id: str) -> list[Revision]:
    rows = connection.execute(
        _ancestry_cte()
        + "SELECT r.* FROM changelog_revisions r JOIN ancestry a ON r.id=a.id ORDER BY r.rev",
        {"head": head_id},
    ).fetchall()
    return [Revision(**dict(row)) for row in rows]


def _at_revision(connection, filename: str, rev: int | None) -> Revision:
    save = _save(connection, filename)
    if save is None:
        raise RevisionMissingError("This save has no recorded revisions yet")
    if rev is None:
        return _revision(connection, save.head_id)
    row = connection.execute(
        _ancestry_cte()
        + "SELECT r.* FROM changelog_revisions r JOIN ancestry a ON r.id=a.id WHERE r.rev=:rev",
        {"head": save.head_id, "rev": rev},
    ).fetchone()
    if row:
        return Revision(**dict(row))
    raise RevisionMissingError(f"Revision {rev} does not exist in this save")


def _insert_revision(connection, revision: Revision):
    connection.execute(
        "INSERT INTO changelog_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            revision.id,
            revision.parent_id,
            revision.rev,
            revision.ts,
            revision.origin,
            revision.origin_id,
            revision.manifest.model_dump_json(),
        ),
    )


def _put_content(connection, blob: blobs.Blob):
    blobs.put(connection, blob)
    # Manifests own their references. One namespace pin per digest protects
    # content from generic collection without duplicating every message's
    # reference row on every autosave; _collect marks the remaining manifests.
    blobs.reference(
        connection,
        blobs.BlobReference(
            namespace=NAMESPACE.name,
            owner=blob.digest,
            slot="",
            digest=blob.digest,
        ),
    )


def _message_digests(
    connection, manifest: Manifest, chunks: dict | None = None
) -> list[str]:
    chunks = {} if chunks is None else chunks
    messages = []
    for digest in manifest.history_chunks or []:
        if digest not in chunks:
            chunks[digest] = MessageChunk.model_validate_json(
                blobs.get(connection, digest).data
            ).messages
        messages.extend(chunks[digest])
    return messages


def _assemble(connection, revision: Revision) -> dict:
    manifest = revision.manifest
    messages = _message_digests(connection, manifest)
    values = {
        digest: json.loads(blobs.get(connection, digest).data)
        for digest in set(manifest.sections.values()) | set(messages)
    }
    data = {
        key: copy.deepcopy(values[digest]) for key, digest in manifest.sections.items()
    }
    if manifest.history_chunks is not None:
        data["history"] = [copy.deepcopy(values[digest]) for digest in messages]
    return data


def _collect(connection) -> dict[str, int]:
    live = (
        _ancestry_cte("SELECT head_id FROM changelog_saves") + "SELECT id FROM ancestry"
    )
    removed = connection.execute(
        "DELETE FROM changelog_revisions WHERE id NOT IN (" + live + ")"
    ).rowcount
    digests, chunks = set(), set()
    for row in connection.execute("SELECT manifest FROM changelog_revisions"):
        manifest = Manifest.model_validate_json(row["manifest"])
        digests.update(manifest.digests())
        chunks.update(manifest.history_chunks or [])
    try:
        digests.update(
            _message_digests(
                connection, Manifest(sections={}, history_chunks=list(chunks))
            )
        )
    except (blobs.BlobCorruptedError, ValidationError) as exc:
        log.warning(
            "Blob collection deferred: unreadable revision chunk", error=str(exc)
        )
        return {"revisions": removed, "blobs": 0}
    stale = blobs.referenced_digests(connection, NAMESPACE.name) - digests
    blobs.release_digests(connection, NAMESPACE.name, stale)
    return {"revisions": removed, "blobs": blobs.collect(connection)}


class SnapshotStore:
    def __init__(self, directory: Path | str):
        self.db = Database.project(directory, blobs.NAMESPACE, NAMESPACE)

    async def head(self, filename: str) -> Revision | None:
        if not self.db.path.exists():
            return None

        def read(connection):
            save = _save(connection, filename)
            return _revision(connection, save.head_id) if save else None

        return await self.db.read(read)

    async def append(
        self,
        filename: str,
        manifest: Manifest,
        changed: list[blobs.Blob],
        *,
        expected_head: str | None,
        link_from: str | None = None,
        replace: bool = False,
    ) -> Revision:
        def write(connection):
            if link_from and not replace:
                raise ValueError(
                    "Linking a source requires replacing the save identity"
                )
            save = _save(connection, link_from or filename)
            if replace and link_from is None:
                save = None
            if link_from:
                head_matches = (
                    save is not None
                    and expected_head is not None
                    and connection.execute(
                        _ancestry_cte() + "SELECT 1 FROM ancestry WHERE id=:expected",
                        {"head": save.head_id, "expected": expected_head},
                    ).fetchone()
                    is not None
                )
            else:
                head_matches = (save.head_id if save else None) == expected_head
            if not head_matches:
                raise ConcurrentSaveError(
                    "This save changed elsewhere; reload it before saving again"
                )
            parent = _revision(connection, expected_head) if expected_head else None
            supplied = {blob.digest for blob in changed}
            available = (parent.manifest.digests() if parent else set()) | supplied
            if manifest.digests() - available:
                raise ValueError(
                    "New manifest content must be supplied with the revision"
                )
            for blob in changed:
                _put_content(connection, blob)
            messages = set(_message_digests(connection, manifest)) - supplied
            if blobs.missing_digests(connection, messages):
                raise ValueError(
                    "New message content must be supplied with the revision"
                )
            replaced = False
            if replace:
                replaced = (
                    connection.execute(
                        "DELETE FROM changelog_saves WHERE filename=?", (filename,)
                    ).rowcount
                    > 0
                )
            origin_id = save.id if save and not replace else uuid.uuid4().hex
            revision = Revision(
                id=uuid.uuid4().hex,
                parent_id=expected_head,
                rev=parent.rev + 1 if parent else 0,
                ts=int(time.time()),
                origin=filename,
                origin_id=origin_id,
                manifest=manifest,
            )
            _insert_revision(connection, revision)
            connection.execute(
                "INSERT INTO changelog_saves(filename, id, head_id, fork_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(filename) DO UPDATE SET head_id=excluded.head_id",
                (
                    filename,
                    origin_id,
                    revision.id,
                    expected_head if link_from else None,
                ),
            )
            if replaced:
                _collect(connection)
            return revision

        return await self.db.write(write)

    async def assemble(self, filename: str, rev: int | None = None) -> dict:
        if not self.db.path.exists():
            raise RevisionMissingError("This save has no recorded revisions yet")
        return await self.db.read(
            lambda c: _assemble(c, _at_revision(c, filename, rev))
        )

    async def fork(
        self, filename: str, rev: int, destination: str, *, replace: bool = False
    ) -> Revision:
        def write(connection):
            revision = _at_revision(connection, filename, rev)
            replaced = False
            if replace:
                replaced = (
                    connection.execute(
                        "DELETE FROM changelog_saves WHERE filename=?", (destination,)
                    ).rowcount
                    > 0
                )
            connection.execute(
                "INSERT INTO changelog_saves(filename, id, head_id, fork_id) VALUES (?, ?, ?, ?)",
                (destination, uuid.uuid4().hex, revision.id, revision.id),
            )
            if replaced:
                _collect(connection)
            return revision

        return await self.db.write(write)

    async def delete(self, filename: str) -> dict[str, int]:
        if not self.db.path.exists():
            return {"revisions": 0, "blobs": 0}

        def write(connection):
            connection.execute(
                "DELETE FROM changelog_saves WHERE filename=?", (filename,)
            )
            return _collect(connection)

        return await self.db.write(write)

    async def bundle(self, filename: str) -> RevisionBundle | None:
        if not self.db.path.exists():
            return None

        def read(connection):
            save = _save(connection, filename)
            if not save:
                return None
            revisions = _ancestry(connection, save.head_id)
            content, chunks = {}, set()
            for revision in revisions:
                try:
                    for digest in revision.manifest.digests() - content.keys():
                        content[digest] = blobs.get(connection, digest)
                    for digest in set(revision.manifest.history_chunks or []) - chunks:
                        chunk = MessageChunk.model_validate_json(content[digest].data)
                        for message in set(chunk.messages) - content.keys():
                            content[message] = blobs.get(connection, message)
                        chunks.add(digest)
                except blobs.BlobCorruptedError as exc:
                    raise blobs.BlobCorruptedError(
                        f"Cannot export revision {revision.rev} of {filename}: {exc}"
                    ) from exc
            return RevisionBundle(
                save=save, revisions=revisions, blobs=list(content.values())
            )

        return await self.db.read(read)

    async def restore(self, bundle: RevisionBundle, filename: str):
        def write(connection):
            if _save(connection, filename):
                raise ValueError("This save already has recorded revisions")
            supplied = {blob.digest for blob in bundle.blobs}
            if any(
                revision.manifest.digests() - supplied for revision in bundle.revisions
            ):
                raise ValueError("Imported revision content is incomplete")
            for blob in bundle.blobs:
                _put_content(connection, blob)
            chunks = {
                digest
                for revision in bundle.revisions
                for digest in revision.manifest.history_chunks or []
            }
            if (
                set(
                    _message_digests(
                        connection, Manifest(sections={}, history_chunks=list(chunks))
                    )
                )
                - supplied
            ):
                raise ValueError("Imported revision content is incomplete")
            ids = {revision.id: uuid.uuid4().hex for revision in bundle.revisions}
            origins = {
                origin: uuid.uuid4().hex
                for origin in {r.origin_id for r in bundle.revisions} | {bundle.save.id}
            }
            for revision in bundle.revisions:
                revision = revision.model_copy(
                    update={
                        "id": ids[revision.id],
                        "parent_id": ids[revision.parent_id]
                        if revision.parent_id
                        else None,
                        "origin": filename
                        if revision.origin_id == bundle.save.id
                        else revision.origin,
                        "origin_id": origins[revision.origin_id],
                    }
                )
                _insert_revision(connection, revision)
            connection.execute(
                "INSERT INTO changelog_saves VALUES (?, ?, ?, ?)",
                (
                    filename,
                    origins[bundle.save.id],
                    ids[bundle.save.head_id],
                    ids[bundle.save.fork_id] if bundle.save.fork_id else None,
                ),
            )

        await self.db.write(write)
