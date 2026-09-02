"""
Atomic facts: parsed from the summary call, stored under the world state,
mirrored into the memory store.
"""

import json
from typing import TYPE_CHECKING

import pydantic
import structlog

from talemate.instance import get_agent
from talemate.knowledge.presence import presence_metadata
from talemate.knowledge.schema import Fact, KnowledgeEdge, ParsedFact
from talemate.util.data import extract_json

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "parse_facts",
    "store_facts",
    "facts_for_entry",
    "drop_facts_for_entries",
    "fact_memory_document",
    "previous_facts",
]

log = structlog.get_logger("talemate.knowledge.facts")

_FactList = pydantic.TypeAdapter(list[ParsedFact])


def parse_facts(raw: str | None) -> list[ParsedFact] | None:
    """
    Parse the FACTS output of the summary call.

    Returns None when the output does not hold a JSON list of facts. The
    model's output shape is not guaranteed; a failure is the caller's to
    surface, never to guess around.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    if "```" in text:
        # take the first fenced block
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]

    try:
        _, data = extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        log.warning("facts parse failed", error=str(exc), tail=raw[-300:])
        return None

    if isinstance(data, dict):
        data = data.get("facts", data)
    if not isinstance(data, list):
        log.warning("facts parse failed", error="not a list", tail=raw[-300:])
        return None

    try:
        return _FactList.validate_python(data)
    except pydantic.ValidationError as exc:
        log.warning("facts parse failed", error=str(exc)[:300], tail=raw[-300:])
        return None


def fact_memory_document(fact: Fact) -> dict:
    meta = {
        "typ": "fact",
        "ts": fact.ts if fact.ts is not None else 0,
        "restatements": fact.restatements,
        "false": fact.false,
        **presence_metadata(fact.present),
    }
    if fact.archive_id:
        meta["archive_id"] = fact.archive_id
    return {"id": fact.id, "text": fact.text, "meta": meta}


def facts_for_entry(scene: "Scene", archive_id: str) -> list[Fact]:
    return [
        fact
        for fact in scene.world_state.facts.values()
        if fact.archive_id == archive_id
    ]


def previous_facts(scene: "Scene", limit: int = 30) -> list[Fact]:
    """The most recent stored facts, oldest first, for the summary prompt."""
    facts = list(scene.world_state.facts.values())
    return facts[-limit:]


async def drop_facts_for_entries(scene: "Scene", archive_ids: set[str]):
    """Remove the facts (and the edges that target them) of the given archive entries."""
    world_state = scene.world_state
    removed = {
        fact_id
        for fact_id, fact in world_state.facts.items()
        if fact.archive_id in archive_ids
    }
    if not removed:
        return
    for fact_id in removed:
        del world_state.facts[fact_id]
    world_state.knowledge = [
        edge for edge in world_state.knowledge if edge.target not in removed
    ]
    for fact in world_state.facts.values():
        if fact.supersedes in removed:
            fact.supersedes = None
    memory = get_agent("memory")
    await memory.delete({"ids": sorted(removed)})


async def _near_duplicate(
    scene: "Scene", text: str, max_distance: float
) -> Fact | None:
    memory = get_agent("memory")
    candidates = await memory.get(text, typ="fact", limit=3)
    for candidate in candidates:
        fact = scene.world_state.facts.get(candidate.id)
        if fact is None:
            continue
        comparison = await memory.compare_strings(text, fact.text)
        if comparison["euclidean_distance"] <= max_distance:
            return fact
    return None


async def store_facts(
    scene: "Scene",
    archive_id: str,
    present: list[str] | None,
    ts: int | None,
    parsed: list[ParsedFact],
    dedupe_distance: float,
) -> list[Fact]:
    """
    Store parsed facts for one archive entry.

    A near-duplicate of an existing fact is not stored: it bumps that fact's
    restatement count and last-seen time, and its learners become grant
    edges on the existing fact. Learners that were not present become
    `told` grant edges.
    """
    world_state = scene.world_state
    stored: list[Fact] = []
    documents: list[dict] = []
    present_set = set(present or [])

    for item in parsed:
        existing = await _near_duplicate(scene, item.text, dedupe_distance)
        if existing is not None:
            existing.restatements += 1
            existing.last_seen_ts = ts
            fact = existing
        else:
            world_state.fact_counter += 1
            supersedes = (
                item.supersedes if item.supersedes in world_state.facts else None
            )
            fact = Fact(
                id=f"F{world_state.fact_counter}",
                text=item.text,
                ts=ts,
                archive_id=archive_id,
                present=present,
                subjects=item.subjects,
                supersedes=supersedes,
                last_seen_ts=ts,
            )
            world_state.facts[fact.id] = fact
            stored.append(fact)

        for name in item.known_by:
            if name in present_set or name in fact.known_by:
                continue
            fact.known_by[name] = "told"
            world_state.knowledge.append(
                KnowledgeEdge(
                    character=name,
                    target=fact.id,
                    kind="grant",
                    source="told",
                    ts=ts,
                )
            )

        documents.append(fact_memory_document(fact))

    if documents:
        await get_agent("memory").add_many(documents)

    return stored
