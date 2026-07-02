"""
Websocket plugin for scene-level message edit actions.

Routes frontend-initiated changes to a SceneMessage:

- ``edit``: plain user edit — replaces the active version's text in
  place. Runs through editor exposition cleanup when configured.
- ``append_version``: pushes a new version onto the revision stack and
  makes it the active canonical. Used by the "continue" flow (and any
  future flow that wants to grow the stack from the client side).
- ``swap_revision``: moves the active-version pointer to a different
  index on the stack. The canonical text follows automatically.
- ``delete``: removes the message from scene history.
"""

import pydantic
import structlog

import talemate.instance as instance
from talemate.scene_message import VersionSource
from talemate.server.websocket_plugin import Plugin

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


class DeletePayload(pydantic.BaseModel):
    id: int


class SceneMessagePlugin(Plugin):
    router = "scene_message"

    async def handle_delete(self, data: dict):
        """
        Remove a scene message from history.
        """
        payload = DeletePayload(**data)
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

        self.scene.edit_message(payload.id, new_text)
        await self.scene.attempt_auto_save()
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
            await self.signal_operation_failed(f"Message {payload.id} not found")
            return
        try:
            self.scene.set_message_active_version(payload.id, payload.index)
        except IndexError:
            await self.signal_operation_failed(
                f"Revision index {payload.index} out of range"
            )
            return
        await self.scene.attempt_auto_save()
        await self.signal_operation_done(signal_only=True)
