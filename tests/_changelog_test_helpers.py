"""
Shared helpers for changelog tests (test_changelog.py, test_changelog_extras.py).

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

from talemate.changelog import (
    InMemoryChangelog,
    _base_path,
    _ensure_latest_initialized,
    _get_overall_latest_revision,
    _latest_path,
    save_changelog,
)
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
    ``@property`` descriptors. ``changelog_dir``/``backups_dir`` are still
    real ``@property`` on the parent and cascade off ``save_dir`` correctly.
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

    ``changelog_dir`` and ``backups_dir`` cascade off ``save_dir`` via the
    real properties on ``Scene``.
    """
    scene = ChangelogScene(
        save_dir=tmp_dir,
        filename=filename,
        initial_serialize=initial_serialize,
    )
    os.makedirs(tmp_dir, exist_ok=True)
    return scene


async def persist_test_mutation(scene: ChangelogScene, meta: dict | None = None):
    if not os.path.exists(_base_path(scene)):
        await save_changelog(scene)
    elif not os.path.exists(_latest_path(scene)):
        await _ensure_latest_initialized(scene)
    scene.rev = max(scene.rev, _get_overall_latest_revision(scene))

    previous_changelog = scene._changelog
    async with InMemoryChangelog(scene) as changelog:
        scene._changelog = changelog
        try:
            rev = await changelog.append_delta(meta)
            if rev is not None:
                await changelog.commit()
            return rev
        finally:
            scene._changelog = previous_changelog
