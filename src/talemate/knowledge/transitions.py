from __future__ import annotations

from typing import TYPE_CHECKING

from talemate.context import scene_is_loading
from talemate.instance import get_agent
from talemate.knowledge.context import _project_character_message
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem
from talemate.knowledge.chronology import prompt_fact_text
from talemate.knowledge.revision_browsing import fact_current
from talemate.knowledge.supported_facts import character_fact
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import (
    bind_message_source,
    PerspectiveReadContext,
    select_character_view,
)
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
    # Context scaffolding must not dispatch passage analysis or fact extraction.
    scene.history.append(transition)
    bind_message_source(scene, transition)
    scene.saved = False
    scene.emit_history_message(transition)


def record_departure(scene: Scene, character: Character) -> None:
    if scene_is_loading.get() is scene:
        return
    departure = CharacterTransitionMessage(
        character_name=character.name,
        kind="deactivated",
        present=[character.name],
    )
    append_transition(scene, departure)
    # The entry is the departure point: a time passage placed after it in
    # history is part of the absence, one placed before it is not.
    departures(scene)[character.name] = {"message_id": departure.id}


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


def absence_seconds(scene: Scene, transition: CharacterTransitionMessage) -> int | None:
    times = message_times(scene)
    returned = times.get(transition.id)
    departed = times.get(transition.departure_message_id)
    if returned is None or departed is None:
        return None
    return max(0, returned - departed)


def offscreen_eligible(scene: Scene, transition: CharacterTransitionMessage) -> bool:
    if not transition.returning or not transition_available(scene, transition):
        return False
    if (absence_seconds(scene, transition) or 0) > 0:
        return True
    start = next(
        (
            i
            for i, item in enumerate(scene.history)
            if item.id == transition.departure_message_id
        ),
        None,
    )
    if start is None:
        return False
    end = transition_index(scene, transition)
    return any(
        isinstance(item, (CharacterMessage, NarratorMessage))
        for item in scene.history[start + 1 : end]
    )


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
        isinstance(item, CharacterMessage)
        and item.character_name == character
        and not item.history_dispatch_pending
        for item in scene.history[index + 1 :]
    ):
        return None
    return transition


def arrival_lines(scene: Scene, transition: CharacterTransitionMessage) -> list[str]:
    """Read at most two post-entry lines, ending at the first own reply."""
    index = transition_index(scene, transition)
    perspective_mode = character_knowledge_enabled(scene)
    read = PerspectiveReadContext(scene) if perspective_mode else None
    knowledge = KnowledgeIndex.from_scene(scene) if not perspective_mode else None
    lines = []
    for message in scene.history[index + 1 :]:
        if (
            message.typ == "character_transition"
            and message.character_name == transition.character_name
        ):
            break
        if (
            isinstance(message, CharacterMessage)
            and message.character_name == transition.character_name
        ):
            break
        if (
            not isinstance(message, (CharacterMessage, NarratorMessage))
            or message.hidden
        ):
            continue
        if perspective_mode:
            text = _project_character_message(
                scene,
                transition.character_name,
                message,
                read=read,
                select=lambda reference: select_character_view(
                    scene, reference, transition.character_name, read=read
                ),
                keep_director=False,
                show_hidden=False,
                direction_mode="direction",
                diagnostics=None,
            )
        else:
            text = (
                str(message)
                if knowledge.rejection(
                    transition.character_name, KnowledgeItem.from_message(message)
                )
                is None
                else None
            )
        if text:
            lines.append(f"[{message.id}] {text}")
        if len(lines) == 2:
            break
    return lines


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
        elapsed = (
            "The elapsed scene time is unknown."
            if seconds is None
            else f"{duration_to_human(seconds, suffix='')} of scene time passed during the absence."
            if seconds
            else "No scene-time passage was recorded during the absence."
        )
        lines = [
            f"{name} left the scene. {elapsed} {name} has now returned to the scene."
        ]
    else:
        lines = [f"{name} has now entered the scene for the first time."]
    core_count = len(lines)
    fact = offscreen_account(scene, transition)
    if fact is not None:
        lines.append(f"During the absence: {prompt_fact_text(fact)}")
    elif transition.returning:
        lines.append("No offscreen events have been established for this return.")
    if transition.participants:
        lines.append(
            f"Scene participants at entry: {', '.join(transition.participants)}."
        )
    established = arrival_lines(scene, transition)
    lines.append(
        "Established arrival context:\n" + "\n".join(established)
        if established
        else "No arrival action has yet been established."
    )
    if transition.arrival_note:
        lines.append(f"Author's arrival note: {transition.arrival_note}")
    if budget is not None:
        # Keep the departure/time/return scaffold. Optional
        # arrival details are removed before the owned offscreen account.
        while len(lines) > core_count and count_tokens("\n".join(lines)) > budget:
            lines.pop()
    return "\n".join(lines)


def offscreen_account(scene: Scene, transition: CharacterTransitionMessage):
    """Resolve the owned account without projecting unrelated facts on every frame."""
    name = transition.character_name
    fact = scene.world_state.facts.get(transition.offscreen_fact_id)
    if (
        fact is None
        or fact.source != "offscreen"
        or fact.present != [name]
        or fact.false
        or not fact_current(scene, fact)
    ):
        return None
    perspective_mode = character_knowledge_enabled(scene)
    if perspective_mode and name not in scene.character_data:
        return None
    index = None if perspective_mode else KnowledgeIndex.from_scene(scene)

    def project(candidate):
        if perspective_mode:
            return character_fact(scene, candidate, name)
        return (
            candidate
            if index.in_bucket(
                name,
                KnowledgeItem(id=candidate.id, kind="fact", present=candidate.present),
            )
            else None
        )

    if project(fact) is None:
        return None
    for candidate in scene.world_state.facts.values():
        # A character's contribution can carry a different link from the reader's.
        if candidate.supersedes != fact.id and not any(
            item.supersedes == fact.id for item in candidate.contributions
        ):
            continue
        if not fact_current(scene, candidate):
            continue
        successor = project(candidate)
        if (
            successor is not None
            and not successor.false
            and successor.supersedes == fact.id
        ):
            return None
    return fact


def offscreen_status(scene: Scene, transition: CharacterTransitionMessage) -> str:
    if (
        transition.offscreen_status == "ready"
        and transition.offscreen_fact_id not in scene.world_state.facts
    ):
        return "failed"
    return transition.offscreen_status


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
    account = offscreen_account(scene, transition)
    return {
        **payload,
        "returning": transition.returning,
        "absence_seconds": seconds,
        "absence": duration_to_human(seconds, suffix="").lower() if seconds else None,
        "participants": transition.participants,
        "offscreen_account": account.text if account is not None else None,
        "arrival_note": transition.arrival_note,
        "offscreen_fact_id": transition.offscreen_fact_id
        if transition.offscreen_fact_id in scene.world_state.facts
        else None,
        "offscreen_status": offscreen_status(scene, transition),
        "available": transition_available(scene, transition),
        "can_retry": enabled
        and offscreen_eligible(scene, transition)
        and transition_current(scene, transition),
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
