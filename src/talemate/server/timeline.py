"""
Websocket plugin for the scene timeline UX.

Lets the frontend browse a scene's changelog revisions, preview the message
history at any revision, and fork from one:

- ``list_revisions``: timeline points — every changelog revision with its
  timestamp, plus the base snapshot (revision 0).
- ``preview``: reconstructs the scene at a revision and returns the tail of
  its message history for display.
- ``fork``: writes a new scene file forked from a revision and asks the
  frontend to load it.

Forking is the only action that writes: the timeline never modifies the scene
it browses, and ``fork`` refuses a save name that already exists, so no
timeline action can overwrite an existing scene file.

All actions also work without a loaded scene by passing ``scene_path`` (used
from the load screen), operating on a lightweight scene scaffold.
"""

import os

import pydantic
import structlog

from talemate.changelog import (
    ChangelogCorruptedError,
    ChangelogDivergedError,
    ForkSaveNameError,
    check_chain_divergence,
    fork_scene_at_revision,
    resolve_fork_save_name,
    list_revision_entries,
    read_rebase_marker,
    rebase_changelog_chain,
    reconstruct_scene_data,
    scene_ref_from_path,
)
from talemate.server.websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.timeline")

__all__ = ["TimelinePlugin"]

MAX_PREVIEW_MESSAGES = 100


class ListRevisionsPayload(pydantic.BaseModel):
    scene_path: str | None = None


class PreviewPayload(pydantic.BaseModel):
    rev: int
    scene_path: str | None = None
    max_messages: int = 20


class ForkPayload(pydantic.BaseModel):
    rev: int
    save_name: str
    scene_path: str | None = None


class RepairPayload(pydantic.BaseModel):
    scene_path: str | None = None


class TimelinePlugin(Plugin):
    router = "timeline"

    def _target_scene(self, scene_path: str | None):
        """
        Resolve the scene object timeline actions operate on: a scaffold for
        the given path (load-screen mode), or the active scene.
        """
        if scene_path:
            return scene_ref_from_path(scene_path)

        if not self.scene or not self.scene.filename:
            raise ValueError("No saved scene available for timeline operations")

        return self.scene

    def _aliases_active_scene(self, scene) -> bool:
        """Whether a scaffold built from ``scene_path`` names the scene that
        is currently loaded — the same chain, reached from the load screen."""
        active = self.scene
        if not active or not active.filename:
            return False
        if active.filename != scene.filename:
            return False
        return os.path.abspath(active.changelog_dir) == os.path.abspath(
            scene.changelog_dir
        )

    async def _chain_status(self, scene) -> dict:
        """Chain health for the timeline UI: ok / diverged / unverifiable."""
        try:
            divergent = await check_chain_divergence(scene)
        except ChangelogCorruptedError as e:
            return {"status": "unverifiable", "detail": str(e)}
        if divergent is None:
            return {"status": "ok", "detail": None}
        if divergent:
            return {
                "status": "diverged",
                "detail": f"{len(divergent)} path(s), e.g. {divergent[0]}",
            }
        return {"status": "ok", "detail": None}

    async def handle_list_revisions(self, data: dict):
        """
        Send the scene's timeline points: base snapshot (revision 0) followed
        by all changelog revisions in ascending order, plus the chain health
        (diverged chains can be repaired) and any rebase history.
        """
        payload = ListRevisionsPayload(**data)
        scene = self._target_scene(payload.scene_path)

        revisions = sorted(list_revision_entries(scene), key=lambda x: x["rev"])

        base_path = os.path.join(scene.changelog_dir, f"{scene.filename}.base.json")
        if os.path.exists(base_path):
            revisions.insert(
                0, {"rev": 0, "ts": int(os.path.getmtime(base_path)), "is_base": True}
            )
            chain = await self._chain_status(scene)
            rebase = read_rebase_marker(scene)
        else:
            chain = {"status": "ok", "detail": None}
            rebase = None

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "revisions",
                "data": {
                    "scene_path": payload.scene_path,
                    "revisions": revisions,
                    "chain": chain,
                    "rebase": rebase,
                },
            }
        )

    async def handle_repair(self, data: dict):
        """
        Rebase a diverged/unverifiable chain onto the latest snapshot.

        User-confirmed from the timeline UI: the old chain is preserved
        under ``changelog/rebased-<ts>/`` and a fresh chain starts from the
        current scene state, so previews and forks reconstruct exactly again.
        """
        payload = RepairPayload(**data)
        scene = self._target_scene(payload.scene_path)

        if payload.scene_path and self._aliases_active_scene(scene):
            # a repair started from the load screen can name the scene that is
            # loaded right now; rebasing the scaffold would leave the live
            # scene's in-memory changelog on the archived revision namespace
            scene = self.scene

        try:
            result = await rebase_changelog_chain(scene)
        except ValueError as e:
            log.warning("timeline_repair_refused", scene=scene.filename, detail=str(e))
            await self.signal_operation_failed(
                "Nothing to repair — this scene's history already matches the scene."
            )
            return
        except ChangelogCorruptedError as e:
            log.warning("timeline_repair_refused", scene=scene.filename, detail=str(e))
            await self.signal_operation_failed(
                "Repair isn't possible: the scene's latest saved state could not be read."
            )
            return
        except Exception as e:
            # the rebase restores the chain before it raises, so nothing is
            # half-repaired and the session stays usable
            log.error("timeline_repair_failed", scene=scene.filename, error=e)
            await self.signal_operation_failed(
                f"Repair failed — nothing was changed. ({e})"
            )
            return

        log.info("timeline_repair", scene=scene.filename, **result)

        if scene is self.scene:
            # message rev stamps were zeroed — the frontend's fork targets
            # still carry the archived chain's revisions
            await scene.emit_history()

        await self.signal_operation_done(
            signal_only=True,
            emit_status_message=(
                f"Timeline repaired — the scene's history now starts fresh from "
                f"its current state. The old history files are kept in "
                f"changelog/{result['preserved_to']}/."
            ),
        )

        await self.handle_list_revisions({"scene_path": payload.scene_path})

    async def handle_preview(self, data: dict):
        """
        Reconstruct the scene at a revision and send the tail of its message
        history for the preview panel.
        """
        payload = PreviewPayload(**data)
        scene = self._target_scene(payload.scene_path)

        max_messages = max(1, min(payload.max_messages, MAX_PREVIEW_MESSAGES))
        try:
            divergent = await check_chain_divergence(scene)
        except ChangelogCorruptedError as e:
            log.warning(
                "preview_from_unverifiable_chain", rev=payload.rev, detail=str(e)
            )
            divergent = None
        if divergent:
            log.warning(
                "preview_from_diverged_chain",
                rev=payload.rev,
                paths=divergent[:20],
            )
        try:
            reconstructed = await reconstruct_scene_data(scene, to_rev=payload.rev)
        except ChangelogDivergedError as e:
            log.warning("timeline_preview_refused", rev=payload.rev, detail=str(e))
            await self.signal_operation_failed(
                "Preview unavailable: this scene's history is out of sync with "
                "the scene itself. Use Repair on the timeline to fix it."
            )
            return

        history = reconstructed.get("history") or []
        messages = history[-max_messages:]

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "preview",
                "data": {
                    "scene_path": payload.scene_path,
                    "rev": payload.rev,
                    "messages": messages,
                    "total_messages": len(history),
                    "intro": reconstructed.get("intro"),
                },
            }
        )

    async def handle_fork(self, data: dict):
        """
        Create a new scene file forked from a revision and ask the frontend
        to load it.

        The fork always writes a save of its own: a name that would land on an
        existing file is refused rather than overwriting it with older,
        reconstructed data.
        """
        payload = ForkPayload(**data)
        scene = self._target_scene(payload.scene_path)

        try:
            save_name = resolve_fork_save_name(scene, payload.save_name)
        except ForkSaveNameError as e:
            await self.signal_operation_failed(str(e))
            return

        warning = None
        try:
            divergent = await check_chain_divergence(scene)
        except ChangelogCorruptedError as e:
            divergent = None
            warning = (
                "Fork created, but this scene's history chain could not be "
                f"verified ({e}) — the fork may be missing or misrepresenting "
                "data from the original scene."
            )
        if divergent:
            warning = (
                "Fork created, but this scene's history chain has diverged "
                f"({len(divergent)} path(s)) — the fork may be missing or "
                "misrepresenting data from the original scene."
            )

        try:
            fork_path = await fork_scene_at_revision(scene, payload.rev, save_name)
        except ChangelogDivergedError as e:
            log.warning("timeline_fork_refused", rev=payload.rev, detail=str(e))
            await self.signal_operation_failed(
                "Fork refused: this scene's history is out of sync with the "
                "scene itself, so the fork could contain incorrect data. Use "
                "Repair on the timeline to fix it."
            )
            return

        log.info("timeline_fork", rev=payload.rev, path=fork_path)
        await self.signal_operation_done(
            signal_only=True,
            emit_status_message={"message": warning, "status": "warning"}
            if warning
            else None,
        )

        self.websocket_handler.queue_put(
            {
                "type": "system",
                "id": "load_scene_request",
                "data": {"path": fork_path},
            }
        )
