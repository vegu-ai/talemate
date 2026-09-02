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
    "prune_summary_facts",
    "prune_serialized_facts",
    "update_fact",
    "fact_memory_document",
    "previous_facts",
    "store_offscreen_fact",
]

log = structlog.get_logger("talemate.knowledge.facts")

_FactList = pydantic.TypeAdapter(list[ParsedFact])


def parse_facts(raw: str | None) -> list[ParsedFact] | None:
    """
    Parse the facts output of the summary call; None when it holds no JSON
    list of facts.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # trailing prose: fall back to the bracket scanner
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


def prune_summary_facts(world_state, archive_ids: set[str]) -> set[str]:
    """
    Remove the facts of the given archive entries from a WorldState, plus
    the edges that target them. Returns the removed fact ids; memory
    documents are the caller's to delete.
    """
    removed = {
        fact_id
        for fact_id, fact in world_state.facts.items()
        if fact.archive_id in archive_ids
    }
    if not removed:
        return removed
    for fact_id in removed:
        del world_state.facts[fact_id]
    world_state.knowledge = [
        edge for edge in world_state.knowledge if edge.target not in removed
    ]
    for fact in world_state.facts.values():
        if fact.supersedes in removed:
            fact.supersedes = None
    return removed


def prune_serialized_facts(world_state: dict, archive_ids: set[str]) -> set[str]:
    """`prune_summary_facts` over a serialized world state (an export copy)."""
    facts = world_state.get("facts") or {}
    removed = {
        fact_id
        for fact_id, fact in facts.items()
        if fact.get("archive_id") in archive_ids
    }
    if not removed:
        return removed
    world_state["facts"] = {k: v for k, v in facts.items() if k not in removed}
    world_state["knowledge"] = [
        edge
        for edge in world_state.get("knowledge") or []
        if edge.get("target") not in removed
    ]
    for fact in world_state["facts"].values():
        if fact.get("supersedes") in removed:
            fact["supersedes"] = None
    return removed


async def drop_facts_for_entries(scene: "Scene", archive_ids: set[str]):
    """Remove the facts (and the edges that target them) of the given archive entries."""
    removed = prune_summary_facts(scene.world_state, archive_ids)
    if removed:
        await get_agent("memory").delete({"ids": sorted(removed)})


async def update_fact(scene: "Scene", fact: Fact) -> bool:
    """Replace a stored fact; a fact that is no longer stored is refused."""
    if fact.id not in scene.world_state.facts:
        return False
    scene.world_state.facts[fact.id] = fact
    await get_agent("memory").add_many([fact_memory_document(fact)])
    return True


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


async def _near_duplicate_in_batch(
    text: str, batch: list[Fact], max_distance: float
) -> Fact | None:
    if not batch:
        return None
    memory = get_agent("memory")
    result = await memory.compare_string_lists(
        [text], [fact.text for fact in batch], distance_threshold=max_distance
    )
    matches = result["distance_matches"]
    return batch[matches[0][1]] if matches else None


async def store_facts(
    scene: "Scene",
    archive_id: str,
    present: list[str] | None,
    ts: int | None,
    parsed: list[ParsedFact],
    dedupe_distance: float,
) -> list[Fact]:
    """
    Store parsed facts for one archive entry; a near-duplicate of a stored
    fact becomes a restatement of it instead.
    """
    world_state = scene.world_state
    stored: list[Fact] = []
    # keyed by fact id: a merge updates the stored fact's document, not a second copy
    documents: dict[str, dict] = {}

    for item in parsed:
        existing = await _near_duplicate_in_batch(item.text, stored, dedupe_distance)
        if existing is None:
            existing = await _near_duplicate(scene, item.text, dedupe_distance)
        if existing is not None:
            existing.restatements += 1
            existing.last_seen_ts = ts
            fact = existing
            # the restating entry's audience learned the stored fact
            learners = set(present or []) | set(item.known_by)
            covered = set(existing.present or [])
            witnessed_all = existing.present is None
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
            learners = set(item.known_by)
            covered = set(present or [])
            # unknown presence means everyone witnessed it: nothing to grant
            witnessed_all = present is None

        if not witnessed_all:
            for name in sorted(learners - covered):
                if name in fact.known_by:
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

        documents[fact.id] = fact_memory_document(fact)

    if documents:
        await get_agent("memory").add_many(list(documents.values()))

    return stored


async def store_offscreen_fact(scene: "Scene", character: str, text: str) -> Fact:
    """
    What a character did while away from the scene: a fact only they were
    present for, so it retrieves for them alone and never lists in an absence
    block.
    """
    world_state = scene.world_state
    world_state.fact_counter += 1
    fact = Fact(
        id=f"F{world_state.fact_counter}",
        text=" ".join(text.split()),
        ts=scene.ts,
        present=[character],
        subjects=[character],
        source="offscreen",
        last_seen_ts=scene.ts,
    )
    world_state.facts[fact.id] = fact
    await get_agent("memory").add_many([fact_memory_document(fact)])
    log.debug("offscreen fact stored", id=fact.id, character=character)
    return fact
