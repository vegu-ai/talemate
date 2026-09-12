import hashlib
import json
from typing import TYPE_CHECKING, Any, Sequence

from talemate.instance import get_agent
from talemate.knowledge.absence import absence_facts
from talemate.knowledge.bucket import knowledge_digest
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.topics import known_facts
from talemate.knowledge.advice import KnowledgeAnalysisType
from talemate.knowledge.schema import Fact, KnownFact
from talemate.util import count_tokens
from talemate.knowledge.chronology import (
    chronology_settings,
    render_fact,
    formerly_enabled,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene


def standard_analysis_enabled(
    scene: "Scene", character: "Character | None", typ: KnowledgeAnalysisType
) -> bool:
    return (
        typ == "conversation"
        and character is not None
        and not character_knowledge_enabled(scene)
        and get_agent("conversation").character_knowledge_enabled
    )


def standard_analysis_fingerprint(
    scene: "Scene",
    character: "Character | None",
    typ: KnowledgeAnalysisType,
    budget: int,
) -> str | None:
    if not standard_analysis_enabled(scene, character, typ):
        return None
    conversation = get_agent("conversation")
    payload = {
        "character": character.name,
        "knowledge": knowledge_digest(scene),
        "facts": scene.world_state.model_dump(include={"facts"}, mode="json"),
        "budget": budget,
        "window": conversation.knowledge_absence_window,
        "limit": conversation.knowledge_absence_limit,
        "dedupe": get_agent("summarizer").archive_fact_dedupe_distance,
        # Unknown-fact deduplication is skipped when memory is unavailable.
        "memory_ready": get_agent("memory").ready,
        "chronology": chronology_settings(scene),
        "show_formerly": formerly_enabled(),
        "scene_ts": scene.ts,
        "active_characters": sorted(scene.active_characters),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _bounded_lines(
    scene: "Scene",
    facts: Sequence[KnownFact | Fact],
    budget: int,
    *,
    false_ids: set[str] | None = None,
    diagnostics=None,
) -> list[str]:
    lines = []
    used = 0
    for fact in facts:
        status = " (known to be false)" if false_ids and fact.id in false_ids else ""
        line = f"- [{fact.id}]{status} {render_fact(scene, fact, include_id=False)}"
        size = count_tokens(line + "\n")
        if used + size <= budget:
            lines.append(line)
            used += size
        elif diagnostics is not None:
            diagnostics.exclude("fact", fact.id, fact.text, "budget", "Known facts")
    return lines


async def standard_analysis_context(
    scene: "Scene", character: "Character", budget: int
) -> dict[str, Any] | None:
    """Bound each fact list to one third of the analysis evidence budget."""
    conversation = get_agent("conversation")
    known, _ = known_facts(scene, character.name, limit=len(scene.world_state.facts))
    unknown = await absence_facts(
        scene,
        character.name,
        window=conversation.knowledge_absence_window,
        limit=conversation.knowledge_absence_limit,
        dedupe_distance=get_agent("summarizer").archive_fact_dedupe_distance,
    )
    known_lines = _bounded_lines(
        scene,
        known,
        budget // 3,
        false_ids={fact.id for fact in scene.world_state.facts.values() if fact.false},
    )
    unknown_lines = _bounded_lines(scene, unknown, budget // 3)
    if not known_lines and not unknown_lines:
        return None
    text = (
        f"<|SECTION:KNOWN FACTS|>\nKnown facts for {character.name} (importance and recency ranked, bounded):\n"
        + (
            "\n".join(known_lines)
            or (
                "No recorded known facts fit this budget."
                if known
                else "No recorded facts for this character."
            )
        )
        + "\n<|CLOSE_SECTION|>\n<|SECTION:UNKNOWN RECENT FACTS|>\n"
        + f"Unknown recent facts for {character.name} (bounded):\n"
        + ("\n".join(unknown_lines) or "No unknown recent facts selected.")
        + "\n<|CLOSE_SECTION|>"
    )
    return {"text": text, "tokens": count_tokens(text)}
