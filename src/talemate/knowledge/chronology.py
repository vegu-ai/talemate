from dataclasses import dataclass
from textwrap import shorten
from typing import TYPE_CHECKING, Iterable

from pydantic import Field

from talemate.instance import get_agent
from talemate.knowledge.schema import Fact
from talemate.knowledge.names import aliases_for, mentions
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
    settings = settings if settings is not None else chronology_settings(scene)
    age = fact_age(scene, fact)
    score = fact_score(scene, fact, settings)
    recent = age is None or age < max(settings["recent_window"], 0) * DAY
    eligible = (
        recent
        or score > max(settings["score_floor"], 0)
        or any(
            mentions(fact, aliases_for(scene, name), subjects_first=True)
            for name in scene.active_characters
        )
    )
    return FactChronology(score, age, recent, eligible)


class PromptFact(Fact):
    formerly: str | None = Field(default=None, exclude=True)


def formerly_enabled() -> bool:
    return bool(
        get_agent("summarizer").resolve_config("fact_chronology", "show_formerly")
    )


def prompt_fact_text(fact) -> str:
    text = " ".join(fact.text.split())
    formerly = getattr(fact, "formerly", None)
    return f"{text} (formerly: {formerly})" if formerly else text


def superseded_fact_ids(scene, *, character=None, superseders=None) -> set[str]:
    if superseders is None:
        from talemate.knowledge.revision_browsing import current_facts

        current = current_facts(scene)
        if not any(
            fact.supersedes or any(item.supersedes for item in fact.contributions)
            for fact in current
        ):
            return set()
        if character is None:
            superseders = current
        else:
            from talemate.knowledge.topics import known_bucket

            superseders = known_bucket(scene, character)
    return {
        fact.supersedes for fact in superseders if fact.supersedes and not fact.false
    }


def ranked_facts(
    scene: "Scene",
    facts: Iterable["Fact"],
    *,
    limit=None,
    tiers=True,
    character=None,
    prompt=True,
    superseders=None,
    predecessors=None,
) -> list["Fact"]:
    settings = chronology_settings(scene)
    facts = list(facts)
    predecessors = (
        predecessors if predecessors is not None else {fact.id: fact for fact in facts}
    )
    if prompt:
        superseded = superseded_fact_ids(
            scene, character=character, superseders=superseders
        )
        facts = [fact for fact in facts if fact.id not in superseded]
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
    result = result[: max(0, limit)] if limit is not None else result
    if prompt and formerly_enabled():
        result = [
            PromptFact(
                **fact.model_dump(),
                formerly=shorten(
                    predecessors[fact.supersedes].text, width=240, placeholder="…"
                ),
            )
            if fact.supersedes in predecessors
            else fact
            for fact in result
        ]
    return result


def render_fact(
    scene: "Scene", fact: "Fact", *, include_id=True, extraction=False
) -> str:
    prefix = f"[{fact.id}] " if include_id else ""
    text = " ".join(fact.text.split())
    if extraction:
        return f"{prefix}Fact: {text} | Record age (metadata, do not copy): {fact_time(scene, fact)}"
    return f"{prefix}({fact_time(scene, fact)}) {prompt_fact_text(fact)}"


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


def render_fact_document(scene, document, *, fact=None, predecessor=None):
    # Importing the memory package initializes MemoryAgent, which imports chronology.
    from talemate.agents.memory.schema import MemoryDocument

    fact = fact if fact is not None else memory_fact(scene, document)
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
    # Keep evidence across query merging, reranking and cache-time re-rendering.
    rendered.fact_predecessor = predecessor or getattr(
        document, "fact_predecessor", None
    )
    return rendered


def ranked_fact_documents(scene, documents, *, character=None):
    from talemate.knowledge.revision_browsing import (
        has_stale_revisions,
        memory_document_current,
    )

    if has_stale_revisions(scene):
        documents = [
            document
            for document in documents
            if memory_document_current(scene, document)
        ]
    if not any(
        getattr(document, "meta", {}).get("typ") == "fact" for document in documents
    ):
        return list(documents)
    facts = [
        fact
        for document in documents
        if (fact := memory_fact(scene, document)) is not None
    ]
    predecessors = {fact.id: fact for fact in facts}
    for document in documents:
        predecessor = getattr(document, "fact_predecessor", None)
        if predecessor is not None:
            predecessors.setdefault(predecessor.id, predecessor)
    superseders = None
    if character is None and any(
        getattr(document, "meta", {}).get("knowledge_index") for document in documents
    ):
        # An unscoped caller must not infer a private successor from the reader record.
        superseders = facts
    elif character is not None:
        from talemate.knowledge.topics import known_bucket

        visible = {fact.id: fact for fact in known_bucket(scene, character)}
        superseders = list(visible.values())
        predecessors = {
            identity: fact
            for identity, fact in predecessors.items()
            if identity in visible
        }
        facts = [
            fact.model_copy(update={"supersedes": visible[fact.id].supersedes})
            if fact.id in visible
            else fact
            for fact in facts
        ]
    selected = {
        fact.id: fact
        for fact in ranked_facts(
            scene,
            facts,
            character=character,
            superseders=superseders,
            predecessors=predecessors,
        )
    }
    result = []
    for document in documents:
        fact = memory_fact(scene, document)
        if fact is None:
            result.append(document)
        elif fact.id in selected:
            rendered = PromptFact(
                **fact.model_dump(),
                formerly=getattr(selected[fact.id], "formerly", None),
            )
            result.append(
                render_fact_document(
                    scene,
                    document,
                    fact=rendered,
                    predecessor=predecessors.get(selected[fact.id].supersedes),
                )
            )
    return result
