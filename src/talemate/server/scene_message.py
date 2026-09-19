"""
Websocket plugin for scene-level message edit actions.

Routes frontend-initiated changes to a SceneMessage:

- ``edit``: plain user edit — replaces the active version's text in
  place. Runs through editor exposition cleanup when configured.
- ``append_version``: pushes a new version onto the revision stack and
  makes it the active canonical. Used by the "continue" flow (and any
  future flow that wants to grow the stack from the client side).
- ``swap_revision``: moves the active-version pointer to a different
  index on the stack, deferring derived work until keep/catch-up.
- ``commit_revision``: updates derived evidence for the kept canonical text.
- ``delete``: removes the message from scene history.
"""

import pydantic
import structlog

import talemate.instance as instance
from talemate.scene_message import VersionSource, CharacterTransitionMessage
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.revision_browsing import defer_revision_work
from talemate.knowledge.revision_refresh import (
    refresh_revision,
    restore_revision_baseline,
    revision_requires_refresh,
)
from talemate.server.websocket_plugin import Plugin
from talemate.status import background_task
from talemate.knowledge.transitions import (
    transition_available,
)

log = structlog.get_logger("talemate.server.scene_message")

__all__ = ["SceneMessagePlugin"]


class EditPayload(pydantic.BaseModel):
    id: int
    text: str


class AppendVersionPayload(pydantic.BaseModel):
    id: int
    text: str
    source: VersionSource = "custom"
    reason: str | None = None


class SwapRevisionPayload(pydantic.BaseModel):
    id: int
    index: int
    request_id: str | None = None
    scene_id: str | None = None
    selection_digest: str | None = None
    selection_serial: int | None = None


class MessageIdPayload(pydantic.BaseModel):
    id: int


class SceneMessagePlugin(Plugin):
    router = "scene_message"

    async def handle_transition_note(self, data: dict):
        payload = EditPayload(**data)
        message = self.scene.get_message(payload.id)
        if (
            not isinstance(message, CharacterTransitionMessage)
            or message.kind != "activated"
        ):
            await self.signal_operation_failed("Activation entry not found")
            return
        if not transition_available(self.scene, message):
            await self.signal_operation_failed(
                "Activation entry is no longer available"
            )
            return
        message.arrival_note = payload.text.strip()
        self.scene.saved = False
        self.scene.emit_history_message(message)
        await self.signal_operation_done()

    async def handle_delete(self, data: dict):
        """
        Remove a scene message from history.
        """
        payload = MessageIdPayload(**data)
        self.scene.delete_message(payload.id)
        await self.scene.attempt_auto_save()

    async def handle_edit(self, data: dict):
        """
        Replace a scene message's active-version text with user-edited
        text. When the editor agent's exposition cleanup is enabled and
        the target is a character message, the text is cleaned up before
        being committed.

        On success the per-router ``operation_done`` envelope is
        emitted alongside the ``message_edited`` echo. The frontend's
        revision UI consumes the echo (not the envelope) for its
        spinner/state updates today; the envelope is still posted so
        future generic-router consumers stay in sync.
        """
        payload = EditPayload(**data)
        message = self.scene.get_message(payload.id)
        if message is None:
            await self.signal_operation_failed(f"Message {payload.id} not found")
            return

        if isinstance(message, CharacterTransitionMessage):
            await self.signal_operation_failed(
                "A character transition entry cannot be edited; use its Arrival Note"
            )
            return

        new_text = payload.text
        editor = instance.get_agent("editor")

        if (
            editor.enabled
            and message.typ == "character"
            and editor.fix_exposition_enabled
            and editor.fix_exposition_user_input
        ):
            character = self.scene.get_character(message.character_name)
            new_text = await editor.cleanup_character_message(
                new_text,
                character,
                strip_partial=not editor.allow_incomplete_sentences,
            )

        with defer_revision_work():
            self.scene.edit_message(payload.id, new_text)
        await self.scene.attempt_auto_save()
        self.scene.emit_status()
        await self.signal_operation_done(signal_only=True)

    async def handle_append_version(self, data: dict):
        """
        Append a new version onto a scene message's revision stack and
        make it the active canonical. Used by client-initiated flows
        (today: continue) that want to grow the stack rather than
        rewrite the active entry in place.

        Completion is signaled via the ``operation_done`` envelope plus
        the authoritative ``message_edited`` echo (see ``handle_edit``
        for the rationale).
        """
        payload = AppendVersionPayload(**data)
        if self.scene.get_message(payload.id) is None:
            await self.signal_operation_failed(f"Message {payload.id} not found")
            return
        self.scene.append_message_version(
            payload.id,
            payload.text,
            source=payload.source,
            reason=payload.reason,
        )
        if character_knowledge_enabled(self.scene):
            await instance.get_agent("summarizer").rebuild_perceptions(self.scene)
        await self.scene.attempt_auto_save()
        await self.signal_operation_done(signal_only=True)

    async def handle_swap_revision(self, data: dict):
        """
        Set a scene message's active-version index. The canonical text
        follows the pointer — no editor cleanup runs, the chosen version
        was already a valid prior canonical.

        Completion is signaled via the ``operation_done`` envelope plus
        the authoritative ``message_edited`` echo (see ``handle_edit``
        for the rationale).
        """
        payload = SwapRevisionPayload(**data)
        if self.scene.get_message(payload.id) is None:
            await self.signal_operation_failed(
                f"Message {payload.id} not found",
                request_id=payload.request_id,
                failed_action="swap_revision",
            )
            return
        try:
            with defer_revision_work():
                self.scene.set_message_active_version(payload.id, payload.index)
        except IndexError:
            await self.signal_operation_failed(
                f"Revision index {payload.index} out of range",
                request_id=payload.request_id,
                failed_action="swap_revision",
            )
            return
        with defer_revision_work():
            restore_revision_baseline(self.scene, self.scene.get_message(payload.id))
        self.scene.saved = False
        self.scene.emit_status()
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "revision_swapped",
                "request_id": payload.request_id,
            }
        )
        await self.signal_operation_done(signal_only=True)

    @background_task("Updating kept version")
    async def handle_commit_revision(self, data: dict):
        """Run or join the authoritative refresh for the selected canonical text."""
        payload = SwapRevisionPayload(**data)
        scene = self.scene
        message = scene.get_message(payload.id)
        if (
            message is None
            or message.active_version != payload.index
            or (payload.scene_id is not None and payload.scene_id != scene.id)
            or (
                payload.selection_digest is not None
                and payload.selection_digest != message.revision_digest()
            )
            or (
                payload.selection_serial is not None
                and (
                    message.revision_state is None
                    or payload.selection_serial != message.revision_state.serial
                )
            )
        ):
            await self.signal_operation_failed(
                "The selected version changed; choose a version to keep again.",
                request_id=payload.request_id,
                failed_action="commit_revision",
            )
            return
        try:
            selection_digest = message.revision_digest()
            selection_serial = message.revision_state.serial
            selection_active = scene.active
            needs_refresh = revision_requires_refresh(scene, message)
            refresh = await refresh_revision(scene, message)
            if not needs_refresh:
                await scene.attempt_auto_save()
            if (
                self.scene is not scene
                or scene.active != selection_active
                or scene.get_message(payload.id) is not message
                or message.active_version != payload.index
                or message.revision_digest() != selection_digest
                or message.revision_state.serial != selection_serial
            ):
                return
            refresh_state = refresh["revision_refresh"]
            if refresh_state["required"] and refresh_state["operations"] == [
                "index_repair"
            ]:
                await self.signal_operation_failed(
                    "Knowledge could not be updated. You can retry or continue the story.",
                    request_id=payload.request_id,
                    failed_action="commit_revision",
                )
                return
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "revision_committed",
                    "id": payload.id,
                    "index": payload.index,
                    "request_id": payload.request_id,
                    **refresh,
                }
            )
            await self.signal_operation_done(signal_only=True)
        except Exception as exc:
            if self.scene is scene:
                await self.signal_operation_failed(
                    str(exc),
                    emit_status=False,
                    request_id=payload.request_id,
                    failed_action="commit_revision",
                )
            raise
        finally:
            if self.scene is scene:
                scene.emit_status()
