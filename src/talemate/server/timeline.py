"""
Websocket plugin for the scene timeline / rollback UX.

Lets the frontend browse a scene's changelog revisions, preview the message
history at any revision, and apply a restoration:

- ``list_revisions``: timeline points — every changelog revision with its
  timestamp, plus the base snapshot (revision 0).
- ``preview``: reconstructs the scene at a revision and returns the tail of
  its message history for display.
- ``rollback``: rolls the *active* scene back to a revision in place. A
  pre-rollback backup of the scene file is written to the scene's backups
  directory first, and the rollback itself is saved as a new changelog
  revision — so the timeline is never destroyed and the user can scrub
  forward again.
- ``fork``: writes a new scene file forked from a revision and asks the
  frontend to load it.

All actions except ``rollback`` also work without a loaded scene by passing
``scene_path`` (used from the load screen), operating on a lightweight
scene scaffold.
"""

import os

import pydantic
import structlog

from talemate.changelog import (
    _get_overall_latest_revision,
    create_pre_rollback_backup,
    fork_scene_at_revision,
    list_revision_entries,
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


class RollbackPayload(pydantic.BaseModel):
    rev: int


class ForkPayload(pydantic.BaseModel):
    rev: int
    save_name: str
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

    async def handle_list_revisions(self, data: dict):
        """
        Send the scene's timeline points: base snapshot (revision 0) followed
        by all changelog revisions in ascending order.
        """
        payload = ListRevisionsPayload(**data)
        scene = self._target_scene(payload.scene_path)

        revisions = sorted(list_revision_entries(scene), key=lambda x: x["rev"])

        base_path = os.path.join(scene.changelog_dir, f"{scene.filename}.base.json")
        if os.path.exists(base_path):
            revisions.insert(
                0, {"rev": 0, "ts": int(os.path.getmtime(base_path)), "is_base": True}
            )

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "revisions",
                "data": {
                    "scene_path": payload.scene_path,
                    "revisions": revisions,
                },
            }
        )

    async def handle_preview(self, data: dict):
        """
        Reconstruct the scene at a revision and send the tail of its message
        history for the preview panel.
        """
        payload = PreviewPayload(**data)
        scene = self._target_scene(payload.scene_path)

        max_messages = max(1, min(payload.max_messages, MAX_PREVIEW_MESSAGES))
        reconstructed = await reconstruct_scene_data(scene, to_rev=payload.rev)

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

    async def handle_rollback(self, data: dict):
        """
        Roll the active scene back to a revision in place.

        Writes a pre-rollback backup of the current scene file, restores the
        scene state from the changelog, then saves — which records the
        rollback as a new changelog revision, keeping the full timeline
        intact.
        """
        payload = RollbackPayload(**data)
        scene = self.scene

        if not scene or not scene.filename:
            await self.signal_operation_failed(
                "Scene must be saved before it can be rolled back"
            )
            return

        if scene.immutable_save:
            await self.signal_operation_failed(
                "This save is immutable and cannot be rolled back in place — fork instead"
            )
            return

        original_filename = scene.filename
        original_path = os.path.join(scene.save_dir, scene.filename)
        backup_path = create_pre_rollback_backup(scene)

        try:
            await scene.restore(from_rev=payload.rev)

            # restore() loads the reconstructed state via a temp file, which
            # clears the filename and leaves `rev` resolved against the temp
            # name — point both back at the original scene file before saving.
            scene.filename = original_filename
            scene.rev = _get_overall_latest_revision(scene)

            await scene.save()
            await scene.emit_history()
        except Exception:
            # recover the session by reloading the scene file from disk
            # instead of leaving a half-reset scene in memory
            self.websocket_handler.queue_put(
                {
                    "type": "system",
                    "id": "load_scene_request",
                    "data": {"path": original_path},
                }
            )
            raise

        log.info(
            "timeline_rollback",
            rev=payload.rev,
            filename=original_filename,
            backup=backup_path,
        )

        await self.signal_operation_done(
            signal_only=True,
            emit_status_message=f"Scene rolled back to revision {payload.rev}",
        )

    async def handle_fork(self, data: dict):
        """
        Create a new scene file forked from a revision and ask the frontend
        to load it.
        """
        payload = ForkPayload(**data)
        scene = self._target_scene(payload.scene_path)

        fork_path = await fork_scene_at_revision(scene, payload.rev, payload.save_name)

        log.info("timeline_fork", rev=payload.rev, path=fork_path)

        await self.signal_operation_done(signal_only=True)

        self.websocket_handler.queue_put(
            {
                "type": "system",
                "id": "load_scene_request",
                "data": {"path": fork_path},
            }
        )
