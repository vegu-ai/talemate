from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import structlog

from talemate.shared_context import SharedContext
import pydantic

log = structlog.get_logger("talemate.server.world_state_manager.shared_context")



class SelectSharedContextPayload(pydantic.BaseModel):
    filepath: str


class CreateSharedContextPayload(pydantic.BaseModel):
    filename: str | None = None


class DeleteSharedContextPayload(pydantic.BaseModel):
    filepath: str



class SetShareStaticHistoryPayload(pydantic.BaseModel):
    enabled: bool = False


class SharedContextMixin:
    """
    Websocket handlers and helpers for managing scene shared context files.

    Expects the consumer class to provide:
      - self.scene
      - self.websocket_handler.queue_put(...)
      - self.signal_operation_done / self.signal_operation_failed
    """

    # -------- Helpers --------
    def _list_shared_context_files(self) -> list[dict[str, Any]]:
        scene = self.scene
        shared_dir = Path(scene.shared_context_dir)
        shared_dir.mkdir(parents=True, exist_ok=True)

        items: list[dict[str, Any]] = []
        for file in shared_dir.glob("*.json"):
            try:
                stat = file.stat()
                items.append(
                    {
                        "filename": file.name,
                        "filepath": str(file.resolve()),
                        "mtime": int(stat.st_mtime),
                        "selected": bool(
                            scene.shared_context
                            and str(file.name) == scene.shared_context.filename
                        ),
                    }
                )
            except Exception:
                continue
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items

    def _shared_counts(self) -> dict[str, int]:
        """
        Count shared characters and world entries for the current scene.
        """
        scene = self.scene
        # Characters: count across scene.character_data
        characters = sum(1 for c in scene.character_data.values() if c.shared)

        # World entries: manual world entries marked shared
        world_entries = sum(
            1
            for entry in scene.world_state.manual_context_for_world().values()
            if entry.shared
        )

        return {"characters": characters, "world_entries": world_entries}

    async def _ensure_shared_context_exists(self) -> SharedContext:
        """
        Ensure the scene has a shared context selected/created following rules:
        - If none exist: create world.json and use it
        - If one exists: use that
        - If multiple exist: use the most recent one
        """
        scene = self.scene
        shared_dir = Path(scene.shared_context_dir)
        shared_dir.mkdir(parents=True, exist_ok=True)

        files = sorted(
            shared_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True
        )

        if len(files) == 0:
            chosen = shared_dir / "world.json"
            shared = SharedContext(filepath=chosen)
            await shared.init_from_scene(scene, write=True)
            scene.shared_context = shared
        elif len(files) == 1:
            chosen = files[0]
            shared = SharedContext(filepath=chosen)
            await shared.init_from_file()
            scene.shared_context = shared
        else:
            chosen = files[0]
            shared = SharedContext(filepath=chosen)
            await shared.init_from_file()
            scene.shared_context = shared

        await scene.shared_context.update_to_scene(scene)
        return scene.shared_context

    # -------- Handlers --------
    async def handle_list_shared_contexts(self, data: dict):
        items = self._list_shared_context_files()
        counts = self._shared_counts()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "shared_context_list",
                "data": {"items": items, "shared_counts": counts},
            }
        )

    async def handle_select_shared_context(self, data: dict):
        payload = SelectSharedContextPayload(**data)
        try:
            shared = SharedContext(
                filepath=self.scene.shared_context_dir / Path(payload.filepath)
            )
            await shared.init_from_file()
            self.scene.shared_context = shared
            await shared.update_to_scene(self.scene)
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "shared_context_selected",
                    "data": {"filepath": shared.filepath},
                }
            )
            await self.signal_operation_done()
            self.scene.emit_status()
        except Exception as e:
            log.error("Failed to select shared context", error=e)
            await self.signal_operation_failed("Failed to select shared context")

    async def handle_create_shared_context(self, data: dict):
        scene = self.scene
        shared_dir = Path(scene.shared_context_dir)
        shared_dir.mkdir(parents=True, exist_ok=True)
        payload = CreateSharedContextPayload(**data)
        suggested_name = payload.filename
        if not suggested_name:
            if not (shared_dir / "world.json").exists():
                suggested_name = "world.json"
            else:
                suggested_name = f"world-{uuid.uuid4().hex[:8]}.json"
        else:
            # Normalize and ensure .json extension, prevent directory traversal
            suggested_name = Path(str(suggested_name)).name
            if not suggested_name.endswith(".json"):
                suggested_name = f"{suggested_name}.json"

        target = shared_dir / suggested_name
        if target.exists():
            await self.signal_operation_failed("Shared context already exists")
            return
        shared = SharedContext(filepath=target)
        await shared.init_from_scene(scene, write=True)
        scene.shared_context = shared

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "shared_context_created",
                "data": {
                    "filename": target.name,
                    "filepath": str(target.resolve()),
                },
            }
        )
        await self.handle_list_shared_contexts({})
        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_delete_shared_context(self, data: dict):
        payload = DeleteSharedContextPayload(**data)
        path = Path(payload.filepath)
        try:
            # If deleting the currently selected shared context, clear it
            if self.scene.shared_context and self.scene.shared_context.filename == str(
                path.name
            ):
                self.scene.shared_context = None
            if path.exists():
                path.unlink()
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "shared_context_deleted",
                    "data": {
                        "filename": path.name,
                        "filepath": str(path),
                    },
                }
            )
            await self.handle_list_shared_contexts({})
            await self.signal_operation_done()
            self.scene.emit_status()
        except Exception as e:
            log.error("Failed to delete shared context", error=e)
            await self.signal_operation_failed("Failed to delete shared context")

    async def handle_clear_shared_context(self, data: dict):
        try:
            # Clear current shared context association for the scene
            self.scene.shared_context = None
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "shared_context_cleared",
                    "data": {},
                }
            )
            await self.handle_list_shared_contexts({})
            await self.signal_operation_done()
            self.scene.emit_status()
        except Exception as e:
            log.error("Failed to clear shared context", error=e)
            await self.signal_operation_failed("Failed to clear shared context")

    async def handle_get_shared_context_settings(self, data: dict):
        sc = self.scene.shared_context
        settings = {
            "selected": bool(sc),
            "filename": sc.filename if sc else None,
            "share_static_history": bool(sc.share_static_history) if sc else False,
        }
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "shared_context_settings",
                "data": settings,
            }
        )

    async def handle_set_shared_context_share_static_history(self, data: dict):
        payload = SetShareStaticHistoryPayload(**data)
        enabled = payload.enabled

        # ensure a shared context exists when enabling
        if enabled and not self.scene.shared_context:
            await self._ensure_shared_context_exists()

        sc = self.scene.shared_context
        if not sc:
            await self.signal_operation_failed("No shared context selected")
            return

        try:
            sc.share_static_history = enabled
            # when enabled, capture current scene static history into shared context
            await sc.update_from_scene(self.scene)
            await sc.write_to_file()

            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "shared_context_settings",
                    "data": {
                        "selected": True,
                        "filename": sc.filename,
                        "share_static_history": sc.share_static_history,
                    },
                }
            )
            await self.signal_operation_done()
            self.scene.emit_status()
        except Exception as e:
            log.error("Failed to set share_static_history", error=e)
            await self.signal_operation_failed("Failed to update setting")
