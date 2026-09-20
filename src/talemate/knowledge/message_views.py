from typing import TYPE_CHECKING, Literal

import pydantic

from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
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


class MessageView(pydantic.BaseModel):
    status: MessageViewStatus
    text: str | None = None
    editable: bool = False
    reason: str | None = None

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
    if perception_running(scene, message):
        return MessageView(status="running")
    if message.revision_state is not None and not message.revision_matches_baseline:
        return MessageView(status="deferred")
    reference = source_reference(scene, "message", message.id, read=read)
    if reference is None:
        return MessageView(status="unavailable", editable=True)
    view = select_character_view(scene, reference, character, read=read)
    return MessageView(status=view.status, text=view.text, editable=True)


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
