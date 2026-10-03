from typing import TYPE_CHECKING, Literal

import pydantic

import talemate.emit.async_signals as async_signals
from talemate.events import Event
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    edit_message_view,
    message_view_dependents,
    select_character_view,
    source_reference,
)
from talemate.knowledge.readiness import perception_running

if TYPE_CHECKING:
    from talemate.scene_message import SceneMessage
    from talemate.tale_mate import Scene


MessageViewStatus = Literal[
    "ready",
    "omitted",
    "pending",
    "failed",
    "unavailable",
    "running",
    "deferred",
    "unsupported",
    "not_present",
]

NOT_EDITABLE_REASONS = {
    "running": "The analysis of this message runs now.",
    "deferred": "Keep a version of this message first.",
    "unsupported": "This type of message has no perspectives.",
}


async_signals.register("perspective.view_edited")


class MessageView(pydantic.BaseModel):
    status: MessageViewStatus
    text: str | None = None
    editable: bool = False
    reason: str | None = None
    # the text is the last stored view, out of sync until a repair
    stale: bool = False

    @pydantic.model_validator(mode="after")
    def explain_refusal(self):
        self.reason = NOT_EDITABLE_REASONS.get(self.status)
        return self


def message_view(
    scene: "Scene",
    message: "SceneMessage",
    character: str,
    *,
    read: PerspectiveReadContext | None = None,
) -> MessageView:
    if not message.supports_perceptions:
        return MessageView(status="unsupported")
    running = perception_running(scene, message)
    deferred = (
        message.revision_state is not None and not message.revision_matches_baseline
    )
    absent = character_knowledge_enabled(scene) and character not in (
        message.present or ()
    )
    reference = source_reference(scene, "message", message.id, read=read)
    if reference is None:
        view = MessageView(status="omitted" if absent else "unavailable", editable=True)
    else:
        selected = select_character_view(scene, reference, character, read=read)
        view = MessageView(
            status=selected.status,
            text=selected.text,
            editable=True,
            stale=selected.stale,
        )
    if absent and view.status == "omitted":
        return view.model_copy(update={"editable": not running and not deferred})
    if running:
        return MessageView(status="running", text=view.text, stale=view.stale)
    if deferred:
        return MessageView(
            status="deferred", text=view.text, stale=view.text is not None
        )
    return view


def intro_view(
    scene: "Scene", character: str, *, read: PerspectiveReadContext | None = None
) -> MessageView:
    reference = source_reference(scene, "intro", "intro", read=read)
    if reference is None:
        return MessageView(status="not_present")
    view = select_character_view(scene, reference, character, read=read)
    if view.status == "unavailable":
        return MessageView(status="not_present")
    if view.status != "ready":
        return MessageView(status=view.status)
    return MessageView(status="ready", text=scene.get_intro(perspective=character))


def edited_view_dependents(
    scene: "Scene", character: str, message_ids: list[int]
) -> dict[int, int]:
    """
    For the views the user edited by hand: how many later views a re-analysis
    would set to pending now. A view with none, or whose message is gone, is left out.
    """
    counts = {}
    for message_id in message_ids:
        if scene.get_message(message_id) is None:
            continue
        count = len(message_view_dependents(scene, message_id, character))
        if count:
            counts[message_id] = count
    return counts


def character_message_views(scene: "Scene", character: str) -> dict[int, MessageView]:
    read = PerspectiveReadContext(scene)
    return {
        message.id: message_view(scene, message, character, read=read)
        for message in scene.history
    }


class PerspectiveViewEditedEvent(Event):
    """Sent when one character's view of a message is replaced by hand."""

    message_id: int
    character: str
    status: MessageViewStatus
    text: str | None = None
    dependents: int = 0


class ViewEdit(pydantic.BaseModel):
    changed: bool
    view: MessageView


async def edit_character_view(
    scene: "Scene", message: "SceneMessage", character: str, text: str
) -> ViewEdit:
    """
    Replace a character's view of `message` by hand, as the perspective panel
    does; empty text omits it. Raises ValueError when the view is not editable.
    Later views built on it stay valid.
    """
    current = message_view(scene, message, character)
    if not current.editable:
        raise ValueError(current.reason or "This perspective cannot be edited")
    changed = edit_message_view(scene, message.id, character, text) is not None
    view = message_view(scene, message, character)
    if changed:
        scene.saved = False
        async_signals.send_soon(
            "perspective.view_edited",
            PerspectiveViewEditedEvent(
                scene=scene,
                event_type="perspective.view_edited",
                message_id=message.id,
                character=character,
                status=view.status,
                text=view.text,
                dependents=len(message_view_dependents(scene, message.id, character)),
            ),
        )
    return ViewEdit(changed=changed, view=view)
