from typing import TYPE_CHECKING, Literal

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.presence import relevant_views

if TYPE_CHECKING:
    from talemate.scene_message import SceneMessage
    from talemate.tale_mate import Scene


PerceptionReadiness = Literal["running", "deferred", "failed", "ready"]


def perception_running(scene: "Scene", message: "SceneMessage") -> bool:
    summarizer = get_agent("summarizer")
    running = getattr(summarizer, "_perception_running", {}).get(scene, set())
    return message.id in running


def perception_readiness(
    scene: "Scene",
    message: "SceneMessage",
    view_status: str | None = None,
    *,
    character: str | None = None,
) -> PerceptionReadiness:
    if perception_running(scene, message):
        return "running"
    state = getattr(message, "revision_state", None)
    if state is not None and not message.revision_matches_baseline:
        if state.status in ("running", "failed"):
            return state.status
        return "deferred"
    if view_status == "failed":
        return "failed"
    if view_status == "pending":
        return "deferred"
    views = relevant_views(scene, message) if message.knowledge is not None else ()
    if any(view.status == "failed" for view in views):
        return "failed"
    if character is not None:
        from talemate.knowledge.perspectives import (
            PerspectiveReadContext,
            select_character_view,
            source_reference,
        )

        read = PerspectiveReadContext(scene)
        reference = source_reference(scene, "message", message.id, read=read)
        if reference is None:
            return "deferred"
        selected = select_character_view(scene, reference, character, read=read)
        if selected.status == "failed":
            return "failed"
        if selected.status != "ready" or selected.stale:
            return "deferred"
    if (
        message.knowledge is not None
        and message.knowledge.content_digest == content_digest(message.perception_text)
        and views
        and all(
            view.status in ("ready", "omitted") and not view.stale for view in views
        )
    ):
        return "ready"
    return "deferred"


def perception_status_message(state: PerceptionReadiness, message_id: int) -> str:
    if state == "running":
        return (
            f"Perception analysis for passage {message_id} is still running; "
            "the preview updates when it finishes."
        )
    if state == "failed":
        return (
            f"Perception analysis for passage {message_id} failed; "
            "Repair runs it again."
        )
    if state == "deferred":
        return (
            "This perspective is out of sync with the passage. "
            "Analyze perceptions now, or choose Repair."
        )
    return f"Perception analysis for passage {message_id} is ready."


def perception_status_data(
    scene: "Scene",
    message: "SceneMessage",
    state: PerceptionReadiness,
    *,
    character: str | None = None,
) -> dict:
    return {
        "scene_id": scene.id,
        "message_id": message.id,
        "selection_index": message.active_version,
        "selection_digest": message.revision_digest(),
        "selection_serial": (
            message.revision_state.serial if message.revision_state else 0
        ),
        "character": character,
        "audiences": sorted(set(scene.active_characters) | set(message.present or ())),
        "state": state,
        "message": perception_status_message(state, message.id),
    }


def emit_perception_status(
    scene: "Scene", message: "SceneMessage", state: PerceptionReadiness
) -> None:
    if not scene.active:
        return
    emit(
        "perception_status",
        scene=scene,
        data=perception_status_data(scene, message, state),
        websocket_passthrough=True,
    )
