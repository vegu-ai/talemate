from __future__ import annotations

from typing import TYPE_CHECKING

from talemate.context import scene_is_loading
from talemate.instance import get_agent
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import bind_message_source
from talemate.knowledge.timeline import message_times
from talemate.scene_message import (
    CharacterMessage,
    CharacterTransitionMessage,
    NarratorMessage,
)
from talemate.util.time import duration_to_human
from talemate.util import count_tokens

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

DEPARTURES_KEY = "character_departures"


def transitions_enabled(scene: Scene) -> bool:
    return character_knowledge_enabled(scene) or bool(
        get_agent("conversation").knowledge_perspective_filter
    )


def transition_in_context(scene: Scene, transition: CharacterTransitionMessage) -> bool:
    return transition.kind == "activated" and transitions_enabled(scene)


def departures(scene: Scene) -> dict:
    return scene.agent_state.setdefault("conversation", {}).setdefault(
        DEPARTURES_KEY, {}
    )


def append_transition(scene: Scene, transition: CharacterTransitionMessage) -> None:
    # Context scaffolding must not dispatch passage analysis.
    scene.history.append(transition)
    bind_message_source(scene, transition)
    scene.saved = False
    scene.emit_history_message(transition)


def record_departure(
    scene: Scene, character: Character
) -> CharacterTransitionMessage | None:
    if scene_is_loading.get() is scene:
        return None
    departure = CharacterTransitionMessage(
        character_name=character.name,
        kind="deactivated",
        present=[character.name],
    )
    append_transition(scene, departure)
    # The entry is the departure point: a time passage placed after it in
    # history is part of the absence, one placed before it is not.
    departures(scene)[character.name] = {"message_id": departure.id}
    return departure


def latest_transition(
    scene: Scene, character: str
) -> CharacterTransitionMessage | None:
    return next(
        (
            message
            for message in reversed(scene.history)
            if isinstance(message, CharacterTransitionMessage)
            and message.kind == "activated"
            and message.character_name == character
        ),
        None,
    )


def record_arrival(
    scene: Scene, character: Character
) -> CharacterTransitionMessage | None:
    if scene_is_loading.get() is scene:
        return None
    departure = departures(scene).pop(character.name, None)
    if departure is None:
        # Scenes saved by 0.39.0 or earlier have no departure record and no
        # message presence, so the character's own last line also counts.
        last_present = next(
            (
                message
                for message in reversed(scene.history)
                if (
                    isinstance(message, (CharacterMessage, NarratorMessage))
                    and character.name in (message.present or ())
                )
                or (
                    isinstance(message, CharacterMessage)
                    and message.character_name == character.name
                )
            ),
            None,
        )
        if last_present is not None:
            departure = {"message_id": last_present.id}
    transition = CharacterTransitionMessage(
        character_name=character.name,
        departure_message_id=departure.get("message_id") if departure else None,
        returning=departure is not None,
        participants=list(scene.active_characters),
        present=[character.name],
    )
    append_transition(scene, transition)
    return transition


def transition_index(
    scene: Scene, transition: CharacterTransitionMessage
) -> int | None:
    return next((i for i, item in enumerate(scene.history) if item is transition), None)


def transition_available(scene: Scene, transition: CharacterTransitionMessage) -> bool:
    return transition_index(scene, transition) is not None


def set_arrival_note(
    scene: Scene, transition: CharacterTransitionMessage, text: str
) -> None:
    """Raises ValueError unless `transition` is an arrival still in the history."""
    if (
        not isinstance(transition, CharacterTransitionMessage)
        or transition.kind != "activated"
    ):
        raise ValueError("Activation entry not found")
    if not transition_available(scene, transition):
        raise ValueError("Activation entry is no longer available")
    transition.arrival_note = text.strip()
    scene.saved = False
    scene.emit_history_message(transition)


def absence_seconds(scene: Scene, transition: CharacterTransitionMessage) -> int | None:
    times = message_times(scene)
    returned = times.get(transition.id)
    departed = times.get(transition.departure_message_id)
    if returned is None or departed is None:
        return None
    return max(0, returned - departed)


def transition_current(scene: Scene, transition: CharacterTransitionMessage) -> bool:
    return (
        transition_available(scene, transition)
        and latest_transition(scene, transition.character_name) is transition
        and transition.character_name in scene.active_characters
        and transition.character_name
        not in scene.agent_state.get("conversation", {}).get(DEPARTURES_KEY, {})
    )


def protected_transition(
    scene: Scene, character: str
) -> CharacterTransitionMessage | None:
    transition = latest_transition(scene, character)
    if (
        transition is None
        or not transition_in_context(scene, transition)
        or not transition_current(scene, transition)
    ):
        return None
    index = transition_index(scene, transition)
    if any(
        isinstance(item, CharacterMessage) and item.character_name == character
        for item in scene.history[index + 1 :]
    ):
        return None
    return transition


def render_transition(
    scene: Scene,
    transition: CharacterTransitionMessage,
    *,
    budget: int | None = None,
) -> str:
    name = transition.character_name
    if not transition_in_context(scene, transition) or not transition_available(
        scene, transition
    ):
        return ""
    if transition.returning:
        seconds = absence_seconds(scene, transition)
        absence = (
            f"{duration_to_human(seconds, suffix='').lower()} away"
            if seconds
            else "being away"
        )
        lines = [f"{name} has returned to the scene after {absence}."]
    else:
        lines = [f"{name} has entered the scene for the first time."]
    core_count = len(lines)
    participants = [person for person in transition.participants if person != name]
    if participants:
        lines.append(
            f"Already in the scene when {name} arrived: {', '.join(participants)}."
        )
    if transition.arrival_note:
        lines.append(f"Author's arrival note: {transition.arrival_note}")
    if budget is not None:
        while len(lines) > core_count and count_tokens("\n".join(lines)) > budget:
            lines.pop()
    return "\n".join(lines)


def transition_payload(scene: Scene, transition: CharacterTransitionMessage) -> dict:
    character = scene.get_character(transition.character_name)
    enabled = transitions_enabled(scene)
    payload = {
        "type": transition.typ,
        "id": transition.id,
        "kind": transition.kind,
        "character": transition.character_name,
        "color": character.color if character else None,
        "transitions_enabled": enabled,
    }
    if transition.kind != "activated":
        return payload
    seconds = absence_seconds(scene, transition) if transition.returning else None
    return {
        **payload,
        "returning": transition.returning,
        "absence_seconds": seconds,
        "absence": duration_to_human(seconds, suffix="").lower() if seconds else None,
        "participants": transition.participants,
        "arrival_note": transition.arrival_note,
        "available": transition_available(scene, transition),
    }


def summary_message_span(scene, entry, layer=0):
    """Resolve Standard summary indices to the underlying chronological span."""
    start, end = (
        entry.get("raw_start", entry.get("start")),
        entry.get("raw_end", entry.get("end")),
    )
    if start is None or end is None or start < 0 or end < start:
        return None
    if layer == 0:
        if end >= len(scene.history):
            return None
        previous_end = max(
            (
                item.get("end", -1)
                for item in scene.archived_history
                if item.get("end") is not None and item["end"] < start
            ),
            default=-1,
        )
        while (
            start - 1 > previous_end
            and scene.history[start - 1].typ == "character_transition"
        ):
            start -= 1
        return (start, end) if end < len(scene.history) else None
    if layer > len(scene.layered_history) + 1:
        return None
    children = (
        scene.archived_history if layer == 1 else scene.layered_history[layer - 2]
    )
    if end >= len(children):
        return None
    spans = [
        summary_message_span(scene, child, layer - 1)
        for child in children[start : end + 1]
    ]
    spans = [span for span in spans if span is not None]
    return (spans[0][0], spans[-1][1]) if spans else None
