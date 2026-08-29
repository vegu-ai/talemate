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

In-place rollback is not exposed: it is being reworked, so the route is gone.
``fork`` refuses a save name that already exists, so no timeline action can
overwrite an existing scene file.

All actions also work without a loaded scene by passing ``scene_path`` (used
from the load screen), operating on a lightweight scene scaffold.
"""

import os

import pydantic
import structlog

from talemate.changelog import (
    fork_scene_at_revision,
    list_revision_entries,
    reconstruct_scene_data,
    scene_ref_from_path,
)
from talemate.server.websocket_plugin import Plugin
from talemate.util.path import is_safe_relative_filename

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

        fork_filename = f"{payload.save_name}.json"

        if not is_safe_relative_filename(fork_filename, suffix=".json"):
            await self.signal_operation_failed(
                f"'{payload.save_name}' is not a valid save name"
            )
            return

        if os.path.exists(os.path.join(scene.save_dir, fork_filename)):
            await self.signal_operation_failed(
                f"A save named '{payload.save_name}' already exists — pick a different name"
            )
            return

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
