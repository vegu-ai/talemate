import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from talemate.emit import async_signals, emit
from talemate.save import SceneEncoder, scene_data_dumps
from talemate.storage.blobs import Blob, BlobCorruptedError
from talemate.storage.changelog import (
    ConcurrentSaveError,
    Manifest,
    MESSAGE_CHUNK_SIZE,
    Revision,
    RevisionMissingError,
    SnapshotStore,
)
from talemate.storage.revision_groups import RevisionGroupQuery, revision_groups
from talemate.util.path import is_safe_relative_filename

async_signals.register(
    "scene.revision_saved",
    "scene.revision_forked",
    "scene.revisions_deleted",
    "scene.revision_failed",
)


class SceneRevisionEvent(BaseModel):
    operation: Literal["save", "fork", "delete"]
    project_path: str
    filename: str
    revision: int | None = None
    revision_id: str | None = None
    parent_id: str | None = None
    source_filename: str | None = None
    removed_revisions: int = 0
    removed_blobs: int = 0
    error: str | None = None


class SaveRevisionOutcome(BaseModel):
    stage: Literal["validation", "revision", "file"] = "validation"
    revision: Revision | None = None
    forked: Revision | None = None
    filename: str | None = None
    source_filename: str | None = None


async def emit_revision_event(
    name, scene, operation, *, revision=None, filename=None, **details
):
    signal = async_signals.get(name)
    if not signal.receivers:
        return
    event = SceneRevisionEvent(
        operation=operation,
        project_path=str(Path(scene.save_dir).resolve()),
        filename=filename or scene.filename or "",
        revision=revision.rev if revision else None,
        revision_id=revision.id if revision else None,
        parent_id=revision.parent_id if revision else None,
        **details,
    )
    await signal.send(event)


class ForkTargetMissingError(RevisionMissingError):
    pass


class ForkSaveNameError(ValueError):
    pass


class SceneRef(BaseModel):
    filename: str
    save_dir: str

    @property
    def serialize(self):
        with open(Path(self.save_dir) / self.filename) as source:
            return json.load(source)


def scene_ref_from_path(scene_path: str) -> SceneRef:
    path = Path(scene_path)
    return SceneRef(filename=path.name, save_dir=str(path.parent))


class CachedSection(BaseModel):
    blob: Blob
    value: Any


class SnapshotCapture(BaseModel):
    manifest: Manifest
    changed: list[Blob]
    data: dict
    cache: dict[str, CachedSection]


def capture_snapshot(
    data: dict, previous: dict[str, CachedSection] | None = None
) -> SnapshotCapture:
    previous = previous or {}
    cache = {}
    changed = {}

    def capture(key, value):
        try:
            encoded = json.dumps(
                value, cls=SceneEncoder, sort_keys=True, separators=(",", ":")
            ).encode()
        except TypeError:
            # JSON saves also accept mappings whose keys cannot be sorted together.
            encoded = json.dumps(
                value, cls=SceneEncoder, separators=(",", ":")
            ).encode()
        cached = previous.get(key)
        if cached is None or cached.blob.data != encoded:
            blob = Blob.from_bytes(encoded)
            cached = CachedSection(blob=blob, value=json.loads(encoded))
            changed[blob.digest] = blob
        cache[key] = cached
        return cached

    sections, plain = {}, {}
    for name, value in data.items():
        if name == "history":
            continue
        cached = capture("section:" + name, value)
        sections[name] = cached.blob.digest
        plain[name] = cached.value
    history = None
    if "history" in data:
        history, plain["history"] = [], []
        for index, message in enumerate(data["history"]):
            message_id = (
                message.get("id", index) if isinstance(message, dict) else message.id
            )
            cached = capture(f"message:{message_id}", message)
            history.append(cached.blob.digest)
            plain["history"].append(cached.value)
    history_chunks = None
    if history is not None:
        history_chunks = []
        for index in range(0, len(history), MESSAGE_CHUNK_SIZE):
            chunk = capture(
                f"chunk:{index}",
                {"messages": history[index : index + MESSAGE_CHUNK_SIZE]},
            ).blob
            history_chunks.append(chunk.digest)
            # A write must not depend on a cached chunk still being intact on disk.
            changed[chunk.digest] = chunk
    return SnapshotCapture(
        manifest=Manifest(
            sections=sections,
            history_chunks=history_chunks,
            message_count=len(history or []),
        ),
        changed=list(changed.values()),
        data=plain,
        cache=cache,
    )


async def save_changelog(scene) -> Revision | None:
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    if head is not None:
        return head
    source = (
        await asyncio.to_thread(lambda: scene.serialize)
        if isinstance(scene, SceneRef)
        else scene.serialize
    )
    data = json.loads(json.dumps(source, cls=SceneEncoder))
    for message in data.get("history", []):
        if isinstance(message, dict):
            message["rev"] = 0
    snapshot = capture_snapshot(data)
    return await store.append(
        scene.filename, snapshot.manifest, snapshot.changed, expected_head=None
    )


async def resolve_scene_revision(scene):
    if scene._changelog:
        await scene._changelog.__aexit__(None, None, None)
    scene._changelog = SceneChangelog(scene)
    if scene.filename:
        await scene._changelog._initialize()
    else:
        scene.rev = 0
        for message in scene.history:
            message.rev = None


class SceneChangelog:
    def __init__(self, scene):
        self.scene = scene
        self.ref = None
        self.head = None
        self.cache = {}
        self.known_ids = set()
        self._ready = False
        self._store = None
        self._database_context = None
        self._keep_open = False
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        self._keep_open = True
        try:
            if self.scene.filename:
                await self._initialize()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *args):
        self._keep_open = False
        if self._database_context:
            await self._database_context.__aexit__(*args)
            self._database_context = None

    async def _open_database(self):
        if self._keep_open and self._database_context is None:
            self._database_context = self._store.db.keep_open()
            await self._database_context.__aenter__()

    async def _initialize(self) -> Revision | None:
        ref = SceneRef(filename=self.scene.filename, save_dir=self.scene.save_dir)
        if self._ready and ref == self.ref:
            return
        if self._store is None or self.ref is None or ref.save_dir != self.ref.save_dir:
            if self._database_context:
                await self._database_context.__aexit__(None, None, None)
                self._database_context = None
            self._store = SnapshotStore(ref.save_dir)
        store = self._store
        head = await store.head(ref.filename)
        seeded = None
        if (
            head is None
            and not self.scene.immutable_save
            and ref.filename not in ("initial.json", self.scene.restore_from)
            and Path(ref.save_dir, ref.filename).is_file()
        ):
            seeded = head = await save_changelog(ref)
        self.ref, self.head, self.cache = ref, head, {}
        self.known_ids = set()
        self.scene.rev = head.rev if head else 0
        if head:
            await self._open_database()
            try:
                saved = await store.assemble(ref.filename)
                self.cache = capture_snapshot(saved).cache
                recorded = {
                    m.get("id"): m.get("rev", 0) for m in saved.get("history", [])
                }
                self.known_ids = set(recorded)
                for message in self.scene.history:
                    message.rev = recorded.get(message.id)
            except BlobCorruptedError:
                # Resupply verified content from the JSON save to heal matching blobs.
                self.known_ids = {
                    m.id
                    for m in self.scene.history
                    if m.rev is not None and 0 <= m.rev <= head.rev
                }
                for message in self.scene.history:
                    if message.id not in self.known_ids:
                        message.rev = None
        else:
            for message in self.scene.history:
                message.rev = None
        self._ready = True
        return seeded

    async def record(
        self,
        outcome: SaveRevisionOutcome | None = None,
        *,
        save_as: bool = False,
        source: SceneRef | None = None,
        source_head: Revision | None = None,
    ) -> dict:
        async with self._lock:
            ref = SceneRef(filename=self.scene.filename, save_dir=self.scene.save_dir)
            replace = save_as and source != ref
            linked = None
            if replace:
                if source and source.save_dir == ref.save_dir:
                    linked = source_head
                store, head, cache = SnapshotStore(ref.save_dir), linked, {}
                known_ids = self.known_ids if linked else set()
                if self._database_context and self.ref.save_dir != ref.save_dir:
                    await self._database_context.__aexit__(None, None, None)
                    self._database_context = None
            else:
                seeded = await self._initialize()
                if outcome is not None and seeded is not None:
                    outcome.revision = seeded
                store, head, cache = self._store, self.head, self.cache
                known_ids = self.known_ids
            next_rev = head.rev + 1 if head else 0
            stamped = [m for m in self.scene.history if m.id not in known_ids]
            data = self.scene.serialize
            data["history"] = [
                m.model_copy(update={"rev": next_rev}) if m.id not in known_ids else m
                for m in self.scene.history
            ]
            try:
                snapshot = capture_snapshot(data, cache)
                if replace or head is None or snapshot.manifest != head.manifest:
                    if not replace:
                        await self._open_database()
                    head = await store.append(
                        ref.filename,
                        snapshot.manifest,
                        snapshot.changed,
                        expected_head=head.id if head else None,
                        link_from=source.filename if linked else None,
                        replace=replace,
                    )
                    if outcome is not None:
                        outcome.revision = head
                        outcome.forked = linked
            except BaseException as exc:
                # A stale writer must keep refusing until the scene is reloaded.
                if not replace:
                    self._ready = isinstance(exc, ConcurrentSaveError)
                raise
            self.ref, self.head, self._store = ref, head, store
            self._ready = True
            self.cache = snapshot.cache
            self.known_ids = {m["id"] for m in snapshot.data["history"]}
            self.scene.rev = self.head.rev
            if stamped:
                for message in stamped:
                    message.rev = next_rev
                emit(
                    "message_revs",
                    data={"revs": [{"id": m.id, "rev": m.rev} for m in stamped]},
                    websocket_passthrough=True,
                )
            return snapshot.data


SPAN_MESSAGE_TYPES = frozenset({"character", "narrator"})


def counts_for_span(message: dict) -> bool:
    return message.get("typ") in SPAN_MESSAGE_TYPES


async def list_revision_groups(scene, query: RevisionGroupQuery) -> dict:
    page = await revision_groups(
        SnapshotStore(scene.save_dir), scene.filename, query, counts_for_span
    )
    return page.model_dump()


async def reconstruct_scene_data(scene, to_rev: int | None = None) -> dict:
    data = await SnapshotStore(scene.save_dir).assemble(scene.filename, to_rev)
    # load imports Scene, which imports this module.
    from talemate.load import prepare_scene_data

    return prepare_scene_data(data)


def resolve_fork_save_name(scene, save_name: str | None) -> str:
    name = (save_name or "").strip()
    filename = f"{name}.json"
    if not name or not is_safe_relative_filename(filename, suffix=".json"):
        raise ForkSaveNameError(f"'{save_name}' is not a valid save name")
    if os.path.exists(os.path.join(scene.save_dir, filename)):
        raise ForkSaveNameError(
            f"A save named '{name}' already exists — pick a different name"
        )
    return name


async def fork_scene_at_revision(
    scene, to_rev: int, save_name: str, expect_message_id: int | None = None
) -> str:
    try:
        path, revision = await _fork_scene_at_revision(
            scene, to_rev, save_name, expect_message_id
        )
    except Exception as exc:
        await emit_revision_event(
            "scene.revision_failed", scene, "fork", error=str(exc)
        )
        raise
    await emit_revision_event(
        "scene.revision_forked",
        scene,
        "fork",
        revision=revision,
        filename=Path(path).name,
        source_filename=scene.filename,
    )
    return path


async def _fork_scene_at_revision(
    scene, to_rev: int, save_name: str, expect_message_id: int | None = None
) -> tuple[str, Revision]:
    name = resolve_fork_save_name(scene, save_name)
    data = await reconstruct_scene_data(scene, to_rev)
    if expect_message_id is not None and not any(
        m.get("id") == expect_message_id for m in data.get("history", [])
    ):
        raise ForkTargetMissingError(
            f"Revision {to_rev} does not contain message {expect_message_id}"
        )
    data.update(
        immutable_save=False,
        hidden=False,
        deprecated=False,
        memory_id=uuid.uuid4().hex[:10],
        playthrough_progress=None,
        project_name=Path(scene.save_dir).name,
    )
    path = Path(scene.save_dir) / f"{name}.json"
    encoded = scene_data_dumps(data)
    with open(path, "x") as destination:
        try:
            destination.write(encoded)
        except BaseException:
            path.unlink()
            raise

    async def link():
        try:
            return await SnapshotStore(scene.save_dir).fork(
                scene.filename, to_rev, path.name, replace=True
            )
        except BaseException:
            Path(path).unlink()
            raise

    # Finish linking before cancellation can leave a file without its ancestry.
    linking = asyncio.create_task(link())
    try:
        revision = await asyncio.shield(linking)
    except asyncio.CancelledError:
        await linking
        raise
    return str(path), revision


async def delete_scene_revisions(scene) -> dict[str, int]:
    try:
        removed = await SnapshotStore(scene.save_dir).delete(scene.filename)
    except Exception as exc:
        await emit_revision_event(
            "scene.revision_failed", scene, "delete", error=str(exc)
        )
        raise
    await emit_revision_event(
        "scene.revisions_deleted",
        scene,
        "delete",
        removed_revisions=removed["revisions"],
        removed_blobs=removed["blobs"],
    )
    return removed


async def export_scene_revisions(scene, destination: Path):
    bundle = await SnapshotStore(scene.save_dir).bundle(scene.filename)
    if bundle is None:
        return
    with tempfile.TemporaryDirectory() as temporary:
        selected = SnapshotStore(temporary)
        await selected.restore(bundle, "scene.json")
        await selected.db.backup(destination)


async def import_scene_revisions(source: Path, scene):
    if not source.is_file():
        return
    incoming = SnapshotStore(source.parent)
    bundle = await incoming.bundle("scene.json")
    if bundle is None:
        raise ValueError("The archive database has no revisions for scene.json")
    await SnapshotStore(scene.save_dir).restore(bundle, scene.filename)
    await resolve_scene_revision(scene)
