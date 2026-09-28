import pydantic

from talemate.changelog import (
    ForkSaveNameError,
    fork_scene_at_revision,
    list_revision_entries,
    reconstruct_scene_data,
    scene_ref_from_path,
)
from talemate.storage.blobs import BlobCorruptedError
from talemate.storage.changelog import RevisionMissingError
from talemate.server.websocket_plugin import Plugin

MAX_PREVIEW_MESSAGES = 100


class ListRevisionsPayload(pydantic.BaseModel):
    scene_path: str | None = None
    request_id: str | None = None


class PreviewPayload(ListRevisionsPayload):
    rev: int = pydantic.Field(ge=0)
    max_messages: int = 20


class ForkPayload(ListRevisionsPayload):
    rev: int = pydantic.Field(ge=0)
    save_name: str
    message_id: int | None = None


class SceneRevisionsPlugin(Plugin):
    router = "scene_revisions"

    def _target_scene(self, scene_path):
        if scene_path:
            return scene_ref_from_path(scene_path)
        if not self.scene or not self.scene.filename:
            raise ValueError("No saved scene available for revision operations")
        return self.scene

    async def handle_list_revisions(self, data):
        payload = ListRevisionsPayload(**data)
        scene = self._target_scene(payload.scene_path)
        revisions = await list_revision_entries(scene)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "revisions",
                "data": {
                    "scene_path": payload.scene_path,
                    "request_id": payload.request_id,
                    "revisions": revisions,
                },
            }
        )

    async def handle_preview(self, data):
        payload = PreviewPayload(**data)
        scene = self._target_scene(payload.scene_path)
        try:
            reconstructed = await reconstruct_scene_data(scene, payload.rev)
        except (BlobCorruptedError, RevisionMissingError) as exc:
            await self.signal_operation_failed(
                "Some saved content is missing or damaged."
                if isinstance(exc, BlobCorruptedError)
                else str(exc),
                emit_status=False,
                request_id=payload.request_id,
                failed_action="preview",
                extra={
                    "rev": payload.rev,
                    "scene_path": payload.scene_path,
                    "code": "damaged_blob"
                    if isinstance(exc, BlobCorruptedError)
                    else "missing_revision",
                },
            )
            return
        history = reconstructed.get("history") or []
        count = max(1, min(payload.max_messages, MAX_PREVIEW_MESSAGES))
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "preview",
                "data": {
                    "scene_path": payload.scene_path,
                    "rev": payload.rev,
                    "request_id": payload.request_id,
                    "messages": history[-count:],
                    "total_messages": len(history),
                    "intro": reconstructed.get("intro"),
                },
            }
        )

    async def handle_fork(self, data):
        payload = ForkPayload(**data)
        scene = self._target_scene(payload.scene_path)
        try:
            path = await fork_scene_at_revision(
                scene,
                payload.rev,
                payload.save_name,
                expect_message_id=payload.message_id,
            )
        except (ForkSaveNameError, RevisionMissingError, BlobCorruptedError) as exc:
            await self.signal_operation_failed(
                "Some saved content is missing or damaged. Choose another revision or restore a project backup."
                if isinstance(exc, BlobCorruptedError)
                else str(exc),
                emit_status=False,
                failed_action="fork",
                request_id=payload.request_id,
            )
            return
        await self.signal_operation_done(
            signal_only=True, request_id=payload.request_id
        )
        self.websocket_handler.queue_put(
            {"type": "system", "id": "load_scene_request", "data": {"path": path}}
        )
