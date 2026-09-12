"""Live, character-scoped orientation for the first turns after entry."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pydantic

from talemate.knowledge.context import project_recent_character_lines
from talemate.knowledge.chronology import ranked_facts, render_fact
from talemate.knowledge.mode import (
    character_knowledge_enabled as perception_mode_enabled,
)
from talemate.knowledge.names import aliases_for, mentions
from talemate.knowledge.perspectives import (
    add_disclosure,
    remove_disclosure,
    replace_disclosure,
)
from talemate.knowledge.topics import known_bucket
from talemate.prompts import Prompt
from talemate.util import count_tokens
from talemate.util.time import duration_to_human

if TYPE_CHECKING:
    from talemate.agents.conversation import ConversationAgent
    from talemate.knowledge.perspective_models import Disclosure
    from talemate.tale_mate import Character, Scene


ENTRY_WINDOWS_STATE_KEY = "character_entry_windows"
ENTRY_BRIEFINGS_STATE_KEY = "character_entry_briefings"
ENTRY_BRIEFING_DISCLOSURE_ORIGIN = "character-entry-briefing"
VISIBLE_LINE_LIMIT = 5
ENTRY_FACT_LIMIT = 12
ENTRY_ORIENTATION_TOKEN_LIMIT = 1024
ENTRY_BRIEFING_TOKEN_ALLOWANCE = 256
ENTRY_BRIEFING_MIN_CHARS = 32


class CharacterEntryWindow(pydantic.BaseModel):
    """The durable boundary and turn budget for one character's arrival."""

    model_config = pydantic.ConfigDict(extra="allow")

    boundary_message_id: int = 0
    entry_scene_time: int = 0
    away_scene_time: int | None = pydantic.Field(default=None, ge=0)
    remaining_turns: int = pydantic.Field(ge=0)
    briefing_disclosure_id: str | None = None


class CharacterEntryOrientation(pydantic.BaseModel):
    """Live prompt inputs derived from a durable entry window."""

    character_name: str
    remaining_turns: int
    present_characters: list[str]
    elapsed: str
    away_elapsed: str = ""
    known_facts: list[str] = pydantic.Field(default_factory=list)
    visible_lines: list[str] = pydantic.Field(default_factory=list)


def entry_windows(agent: "ConversationAgent") -> dict[str, CharacterEntryWindow]:
    """Return valid stored windows, tolerating absent or malformed saved state."""

    raw = agent.get_scene_state(ENTRY_WINDOWS_STATE_KEY, {})
    if not isinstance(raw, dict):
        return {}
    windows = {}
    for name, value in raw.items():
        try:
            window = CharacterEntryWindow.model_validate(value)
        except (TypeError, ValueError, pydantic.ValidationError):
            continue
        if window.remaining_turns:
            windows[str(name)] = window
    return windows


def save_entry_windows(
    agent: "ConversationAgent", windows: dict[str, CharacterEntryWindow]
) -> None:
    agent.set_scene_states(
        **{
            ENTRY_WINDOWS_STATE_KEY: {
                name: window.model_dump(mode="json")
                for name, window in windows.items()
                if window.remaining_turns
            }
        }
    )


def entry_briefings(agent: "ConversationAgent") -> dict[str, str]:
    """Return readable stored briefings only."""

    raw = agent.get_scene_state(ENTRY_BRIEFINGS_STATE_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): text.strip()
        for name, text in raw.items()
        if isinstance(text, str) and text.strip()
    }


def save_entry_briefings(agent: "ConversationAgent", briefings: dict[str, str]):
    agent.set_scene_states(**{ENTRY_BRIEFINGS_STATE_KEY: briefings})


def clear_entry_briefing(agent: "ConversationAgent", character_name: str) -> bool:
    briefings = entry_briefings(agent)
    if character_name not in briefings:
        return False
    briefings.pop(character_name)
    save_entry_briefings(agent, briefings)
    return True


def bind_entry_disclosure(
    agent: "ConversationAgent", character_name: str, disclosure_id: str | None
) -> bool:
    """Bind prompt rendering to the disclosure produced for the open window."""

    windows = entry_windows(agent)
    window = windows.get(character_name)
    if window is None:
        return False
    window.briefing_disclosure_id = disclosure_id
    windows[character_name] = window
    save_entry_windows(agent, windows)
    return True


def set_entry_briefing(
    agent: "ConversationAgent", character_name: str, text: str
) -> bool:
    """Store a briefing only while its corresponding entry window is active."""

    text = text.strip()
    if not text or character_name not in entry_windows(agent):
        return False
    briefings = entry_briefings(agent)
    briefings[character_name] = text
    save_entry_briefings(agent, briefings)
    return True


def perspective_entry_briefing(
    scene: "Scene", character_name: str, disclosure_id: str | None = None
):
    """Return the current generated entry disclosure for one character."""

    disclosures = scene.knowledge.disclosures if scene.knowledge else ()
    matches = [
        item
        for item in disclosures
        if item.origin == ENTRY_BRIEFING_DISCLOSURE_ORIGIN
        and item.audience == (character_name,)
        and (disclosure_id is None or item.id == disclosure_id)
    ]
    return max(matches, key=lambda item: item.acquired.order) if matches else None


def store_perspective_entry_briefing(
    scene: "Scene",
    character_name: str,
    text: str,
    *,
    window: CharacterEntryWindow,
    disclosure_id: str | None = None,
):
    """Create or replace the character's origin-tagged entry disclosure."""

    existing = perspective_entry_briefing(scene, character_name, disclosure_id)
    if disclosure_id is not None and existing is None:
        raise ValueError("Character entry briefing disclosure does not exist")
    if existing is None:
        existing = perspective_entry_briefing(scene, character_name)
    if existing is not None:
        return replace_disclosure(
            scene,
            existing.id,
            text,
            preserve_boundary=disclosure_id is not None,
            message_id_boundary=(
                None if disclosure_id is not None else window.boundary_message_id
            ),
            origin_scene_ts=(
                None if disclosure_id is not None else window.entry_scene_time
            ),
            away_scene_ts=(
                None if disclosure_id is not None else window.away_scene_time
            ),
        )
    return add_disclosure(
        scene,
        text,
        (character_name,),
        origin=ENTRY_BRIEFING_DISCLOSURE_ORIGIN,
        message_id_boundary=window.boundary_message_id,
        origin_scene_ts=window.entry_scene_time,
        away_scene_ts=window.away_scene_time,
    )


def remove_perspective_entry_briefing(
    scene: "Scene", character_name: str, disclosure_id: str | None = None
):
    """Remove only the character's tagged entry disclosure, when present."""

    disclosure = perspective_entry_briefing(scene, character_name, disclosure_id)
    if disclosure is None:
        if disclosure_id is not None:
            raise ValueError("Character entry briefing disclosure does not exist")
        return None
    return remove_disclosure(scene, disclosure.id)


def start_entry_window(
    agent: "ConversationAgent",
    character: "Character",
    *,
    away_scene_time: int | None = None,
) -> CharacterEntryWindow | None:
    """Start a fresh window at the current history and scene-time boundary."""

    turns = agent.knowledge_character_entry_turns
    if not agent.character_knowledge_enabled or turns <= 0:
        return None
    window = CharacterEntryWindow(
        boundary_message_id=agent.scene.history[-1].id if agent.scene.history else 0,
        entry_scene_time=agent.scene.ts,
        away_scene_time=away_scene_time,
        remaining_turns=turns,
    )
    windows = entry_windows(agent)
    windows[character.name] = window
    save_entry_windows(agent, windows)
    clear_entry_briefing(agent, character.name)
    return window


def restart_entry_window(
    agent: "ConversationAgent",
    character: "Character",
    disclosure: "Disclosure",
) -> CharacterEntryWindow | None:
    """Reset only the turn budget while retaining the original entry boundary."""

    turns = agent.knowledge_character_entry_turns
    if not agent.character_knowledge_enabled or turns <= 0:
        return None
    windows = entry_windows(agent)
    window = windows.get(character.name)
    if window is None or window.briefing_disclosure_id != disclosure.id:
        window = CharacterEntryWindow(
            boundary_message_id=disclosure.message_id_boundary,
            entry_scene_time=(
                disclosure.origin_scene_ts
                if disclosure.origin_scene_ts is not None
                else disclosure.acquired.ts
            ),
            away_scene_time=disclosure.away_scene_ts,
            remaining_turns=turns,
        )
    else:
        window.remaining_turns = turns
    window.briefing_disclosure_id = disclosure.id
    windows[character.name] = window
    save_entry_windows(agent, windows)
    clear_entry_briefing(agent, character.name)
    return window


def consume_entry_turn(agent: "ConversationAgent", character_name: str) -> bool:
    """Consume one committed own turn, returning whether a window changed."""

    windows = entry_windows(agent)
    window = windows.get(character_name)
    if window is None:
        return False
    window.remaining_turns -= 1
    if window.remaining_turns:
        windows[character_name] = window
    else:
        windows.pop(character_name, None)
        clear_entry_briefing(agent, character_name)
    save_entry_windows(agent, windows)
    return True


def _facts_about_present(
    scene: "Scene", character: "Character", present: list[str]
) -> list[str]:
    known = known_bucket(scene, character.name)
    alias_sets = [aliases_for(scene, name) for name in present]
    matching = [
        fact
        for fact in known
        if any(mentions(fact, names, subjects_first=True) for names in alias_sets)
    ]
    if not matching:
        return []
    return [
        render_fact(scene, fact, include_id=False)
        for fact in ranked_facts(
            scene,
            matching,
            character=character.name,
            superseders=known,
            limit=ENTRY_FACT_LIMIT,
        )
    ]


def _visible_lines_since(
    scene: "Scene", character: "Character", boundary_message_id: int
) -> list[str]:
    return project_recent_character_lines(
        scene,
        character.name,
        after_message_id=boundary_message_id,
        max_messages=VISIBLE_LINE_LIMIT,
    )


def build_entry_orientation(
    agent: "ConversationAgent", character: "Character"
) -> CharacterEntryOrientation | None:
    """Build the live scoped inputs for an active arrival window."""

    if not agent.character_knowledge_enabled:
        return None
    window = entry_windows(agent).get(character.name)
    if window is None:
        return None
    return build_entry_orientation_for_window(agent, character, window)


def build_entry_orientation_for_window(
    agent: "ConversationAgent",
    character: "Character",
    window: CharacterEntryWindow,
) -> CharacterEntryOrientation:
    """Build scoped inputs for an active or transient deferred-return window."""

    present = [item.name for item in agent.scene.get_characters()]
    elapsed_seconds = max(0, agent.scene.ts - window.entry_scene_time)
    elapsed = duration_to_human(
        elapsed_seconds,
        suffix="",
        zero_time_default="Moments",
    )
    away_elapsed = (
        duration_to_human(
            max(0, window.entry_scene_time - window.away_scene_time),
            suffix="",
            zero_time_default="Moments",
        )
        if window.away_scene_time is not None
        else ""
    )
    return CharacterEntryOrientation(
        character_name=character.name,
        remaining_turns=window.remaining_turns,
        present_characters=present,
        elapsed=elapsed,
        away_elapsed=away_elapsed,
        known_facts=_facts_about_present(agent.scene, character, present),
        visible_lines=_visible_lines_since(
            agent.scene, character, window.boundary_message_id
        ),
    )


def render_entry_block(orientation: CharacterEntryOrientation) -> str:
    """Render the live block within its fixed prompt-token ceiling."""

    fitted = orientation.model_copy(deep=True)

    def render() -> str:
        return Prompt.get(
            "conversation.character-entry",
            vars={"entry_orientation": fitted},
        ).render()

    rendered = render()
    while count_tokens(rendered) > ENTRY_ORIENTATION_TOKEN_LIMIT:
        if fitted.known_facts:
            # Facts are ranked best-first, so discard the weakest first.
            fitted.known_facts.pop()
        elif fitted.visible_lines:
            # Preserve the newest post-entry context as long as possible.
            fitted.visible_lines.pop(0)
        else:
            return _rendered_text_backstop(rendered)
        rendered = render()
    return rendered


def _rendered_text_backstop(rendered: str) -> str:
    """Hard-limit static rendered text after section markers were consumed."""

    while rendered and count_tokens(rendered) > ENTRY_ORIENTATION_TOKEN_LIMIT:
        overflow = count_tokens(rendered) - ENTRY_ORIENTATION_TOKEN_LIMIT
        rendered = rendered[: max(0, len(rendered) - max(1, overflow * 3))].rstrip()
    return rendered


def render_entry_briefing_context(
    character_name: str,
    briefing: str,
    remaining_turns: int,
) -> str:
    """Render a generated briefing within the same complete-section ceiling."""

    fitted = briefing

    def render() -> str:
        return Prompt.get(
            "conversation.character-entry-briefing-context",
            vars={
                "character_name": character_name,
                "briefing": fitted,
                "remaining_turns": remaining_turns,
            },
        ).render()

    rendered = render()
    while fitted and count_tokens(rendered) > ENTRY_ORIENTATION_TOKEN_LIMIT:
        overflow = count_tokens(rendered) - ENTRY_ORIENTATION_TOKEN_LIMIT
        fitted_tokens = max(1, count_tokens(fitted))
        chars_per_token = len(fitted) / fitted_tokens
        remove_chars = max(1, math.ceil(overflow * chars_per_token))
        minimum = min(len(fitted), ENTRY_BRIEFING_MIN_CHARS)
        new_length = max(minimum, len(fitted) - remove_chars)
        if new_length == len(fitted):
            break
        shortened = fitted[:new_length].rstrip()
        fitted = shortened if len(shortened) >= minimum else fitted[:minimum]
        rendered = render()
    if count_tokens(rendered) > ENTRY_ORIENTATION_TOKEN_LIMIT:
        return _rendered_text_backstop(rendered)
    return rendered


def render_entry_orientation(
    agent: "ConversationAgent", character: "Character"
) -> str | None:
    """Render the shared prompt/context-preview entry section."""

    orientation = build_entry_orientation(agent, character)
    if orientation is None:
        return None
    window = entry_windows(agent).get(character.name)
    if window is None:
        return None
    if perception_mode_enabled(agent.scene):
        disclosure = (
            perspective_entry_briefing(
                agent.scene, character.name, window.briefing_disclosure_id
            )
            if window.briefing_disclosure_id
            else None
        )
        briefing = disclosure.text if disclosure is not None else None
    else:
        briefing = entry_briefings(agent).get(character.name)
    if briefing:
        return render_entry_briefing_context(
            character.name,
            briefing,
            orientation.remaining_turns,
        )
    return render_entry_block(orientation)
