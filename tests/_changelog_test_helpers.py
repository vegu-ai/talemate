"""
Shared helpers for changelog tests.

The changelog module reads four scene-shaped attributes — ``filename``,
``save_dir``, ``changelog_dir`` (cascades off ``save_dir``) and
``serialize`` — and walks the disk under ``save_dir``. The tests need to
drive ``serialize`` with arbitrary payloads (not a real scene serialization
shape) so a small ``Scene`` subclass overrides ``serialize`` with a settable
attribute. This is still a real ``Scene`` with real validation/wiring; if
someone renames or removes ``filename``/``save_dir``/``changelog_dir`` on
``Scene`` the tests will fail.
"""

from __future__ import annotations

import os

from talemate.changelog import capture_snapshot, counts_for_span, save_changelog
from talemate.storage.changelog import RevisionEntry, SnapshotStore
from talemate.storage.revision_groups import RevisionGroupQuery, revision_groups
from talemate.tale_mate import Scene


class ChangelogScene(Scene):
    """Real ``Scene`` subclass exposing ``serialize`` and ``save_dir`` as
    settable plain attributes for changelog tests.

    The base ``Scene`` exposes both as ``@property`` descriptors.
    ``Scene.serialize`` returns the *real* serialized scene shape (with
    ``character_data``, ``world_state``, etc.); the changelog tests need to
    drive arbitrary payloads (often ``{"history": ..., "characters": ...}``)
    to verify changelog logic in isolation. ``Scene.save_dir`` joins the
    classmethod ``scenes_dir()`` with ``project_name`` and creates the
    directory; tests instead want a tempdir directly.

    Overriding both with plain class attributes (``None`` here so subclass
    instances initialize them in ``__init__``) shadows the parent's
    ``@property`` descriptors. ``changelog_dir`` is still a real ``@property``
    on the parent and cascades off ``save_dir`` correctly.
    """

    # Shadow the parent's @property descriptors with plain class attrs.
    # On instance creation these get assigned in __init__. Critical: this
    # MUST happen at class-body level so the descriptor lookup finds the
    # plain attribute first.
    serialize = None  # type: ignore[assignment]
    save_dir = None  # type: ignore[assignment]

    def __init__(
        self,
        *,
        save_dir: str,
        filename: str = "scene.json",
        initial_serialize: dict | None = None,
    ):
        super().__init__()
        self.filename = filename
        self.save_dir = save_dir
        self.serialize = (
            initial_serialize
            if initial_serialize is not None
            else {"history": [], "characters": []}
        )


def make_changelog_scene(
    tmp_dir: str,
    *,
    filename: str = "scene.json",
    initial_serialize: dict | None = None,
) -> ChangelogScene:
    """Build a ``ChangelogScene`` whose ``save_dir`` is ``tmp_dir`` directly.

    ``changelog_dir`` cascades off ``save_dir`` via the real property on
    ``Scene``.
    """
    scene = ChangelogScene(
        save_dir=tmp_dir,
        filename=filename,
        initial_serialize=initial_serialize,
    )
    os.makedirs(tmp_dir, exist_ok=True)
    return scene


async def persist_test_mutation(scene: ChangelogScene):
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    if head is None:
        head = await save_changelog(scene)
    snapshot = capture_snapshot(scene.serialize)
    if snapshot.manifest == head.manifest:
        return None
    revision = await store.append(
        scene.filename,
        snapshot.manifest,
        snapshot.changed,
        expected_head=head.id,
    )
    scene.rev = revision.rev
    return revision.rev


async def revision_entries(store: SnapshotStore, filename: str) -> list[RevisionEntry]:
    """Every revision in the save's ancestry, oldest first, as the revision list shows it."""
    entries: list[RevisionEntry] = []
    before = None
    while True:
        page = await revision_groups(
            store,
            filename,
            RevisionGroupQuery(limit=200, before_rev=before),
            counts_for_span,
        )
        entries.extend(e for group in page.groups for e in group.revisions)
        if page.next_before_rev is None:
            return entries[::-1]
        before = page.next_before_rev
