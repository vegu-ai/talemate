from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from talemate.instance import get_agent
from talemate.knowledge.schema import Fact
from talemate.util.time import UNIT_TO_SECONDS, duration_to_human

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

DAY = UNIT_TO_SECONDS["day"]
DEFAULTS = {
    "milestone_half_life": 90.0,
    "state_half_life": 14.0,
    "routine_half_life": 2.0,
    "recent_window": 3.0,
    "score_floor": 0.5,
}


def chronology_settings(scene: "Scene") -> dict[str, float]:
    summarizer = get_agent("summarizer")
    return {
        key: float(summarizer.resolve_config("fact_chronology", key))
        for key in DEFAULTS
    }


def fact_timestamp(fact: "Fact") -> int | None:
    times = [value for value in (fact.ts, fact.last_seen_ts) if value is not None]
    return max(times) if times else None


def fact_age(scene: "Scene", fact: "Fact") -> int | None:
    ts = fact_timestamp(fact)
    return max(0, scene.ts - ts) if ts is not None else None


def fact_time(scene: "Scene", fact: "Fact") -> str:
    age = fact_age(scene, fact)
    return duration_to_human(age) if age is not None else "Time unknown"


def fact_score(scene: "Scene", fact: "Fact", settings=None) -> float:
    settings = settings if settings is not None else chronology_settings(scene)
    key = {1: "routine_half_life", 2: "state_half_life", 3: "milestone_half_life"}[
        fact.importance
    ]
    half_life = max(settings[key], 0.1)
    return fact.importance / (1 + (fact_age(scene, fact) or 0) / DAY / half_life)


@dataclass(frozen=True)
class FactChronology:
    score: float
    age: int | None
    recent: bool
    eligible: bool


def fact_chronology(scene: "Scene", fact: "Fact", settings=None) -> FactChronology:
    # graph imports supported_facts, whose prompt selector uses this module.
    from talemate.knowledge.graph import _mentions, aliases_for

    settings = settings if settings is not None else chronology_settings(scene)
    age = fact_age(scene, fact)
    score = fact_score(scene, fact, settings)
    recent = age is None or age < max(settings["recent_window"], 0) * DAY
    eligible = (
        recent
        or score > max(settings["score_floor"], 0)
        or any(
            _mentions(fact, aliases_for(scene, name))
            for name in scene.active_characters
        )
    )
    return FactChronology(score, age, recent, eligible)


def ranked_facts(
    scene: "Scene", facts: Iterable["Fact"], *, limit=None, tiers=True
) -> list["Fact"]:
    settings = chronology_settings(scene)
    rows = [(fact, fact_chronology(scene, fact, settings)) for fact in facts]
    order = {identity: index for index, identity in enumerate(scene.world_state.facts)}
    rows = [row for row in rows if not tiers or row[1].eligible]
    rows.sort(
        key=lambda row: (
            -row[1].score,
            -(fact_timestamp(row[0]) or 0),
            -order.get(row[0].id, 0),
        )
    )
    result = [fact for fact, _ in rows]
    return result[: max(0, limit)] if limit is not None else result


def render_fact(
    scene: "Scene", fact: "Fact", *, include_id=True, extraction=False
) -> str:
    prefix = f"[{fact.id}] " if include_id else ""
    text = " ".join(fact.text.split())
    if extraction:
        return f"{prefix}Fact: {text} | Record age (metadata, do not copy): {fact_time(scene, fact)}"
    return f"{prefix}({fact_time(scene, fact)}) {text}"


def fact_display(scene, fact):
    return {**fact.model_dump(), "time": fact_time(scene, fact)}


def memory_fact(scene, document):
    meta = getattr(document, "meta", {})
    if meta.get("typ") != "fact":
        return None
    identity = meta.get("knowledge_id", document.id)
    if not meta.get("knowledge_index"):
        canonical = scene.world_state.facts.get(identity)
        if canonical is not None:
            return canonical
    return Fact(
        id=identity,
        text=document.raw,
        ts=meta.get("ts"),
        last_seen_ts=meta.get("last_seen_ts"),
        importance=meta.get("importance", 2),
        subjects=meta.get("fact_subjects", []),
    )


def render_fact_document(scene, document):
    # Importing the memory package initializes MemoryAgent, which imports chronology.
    from talemate.agents.memory.schema import MemoryDocument

    fact = memory_fact(scene, document)
    if fact is None:
        return document
    rendered = MemoryDocument(
        render_fact(scene, fact, include_id=False),
        document.meta,
        document.id,
        document.raw,
        distance=document.distance,
        embedding=document.embedding,
    )
    if getattr(document, "gate_admitted", False):
        rendered.gate_admitted = True
    return rendered


def ranked_fact_documents(scene, documents):
    if not any(
        getattr(document, "meta", {}).get("typ") == "fact" for document in documents
    ):
        return list(documents)
    settings = chronology_settings(scene)
    result = []
    for document in documents:
        fact = memory_fact(scene, document)
        if fact is None:
            result.append(document)
        elif fact_chronology(scene, fact, settings).eligible:
            result.append(render_fact_document(scene, document))
    return result
