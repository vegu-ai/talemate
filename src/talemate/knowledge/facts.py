"""
Atomic facts: parsed from the summary call, stored under the world state,
mirrored into the memory store.
"""

import json
import re
from typing import TYPE_CHECKING, Callable

import pydantic
import structlog

from talemate.instance import get_agent
from talemate.knowledge.chronology import ranked_facts
from talemate.knowledge.changes import KnowledgeChange, emit_knowledge_changes
from talemate.knowledge.presence import presence_metadata
from talemate.knowledge.schema import (
    ArchiveFactSupport,
    DialogueFactSupport,
    Fact,
    FactImportance,
    KnowledgeEdge,
    ParsedFact,
)
from talemate.knowledge.supported_facts import (
    prune_contributions,
    aggregate_fact,
    sanitize_fact_links,
)
from talemate.knowledge.topics import prune_topics
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


class _Unset:
    """A field the caller did not name; None is a value of its own."""


UNSET = _Unset()


def _strip_record_age(text: str) -> str:
    return re.sub(r"^(?:\s*\(\d[^()\n]*\bago\)\s*)+", "", text, flags=re.IGNORECASE)


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

    parsed = []
    for item in data:
        if isinstance(item, dict):
            importance = item.get("importance", 2)
            try:
                level = pydantic.TypeAdapter(int).validate_python(importance)
                if isinstance(importance, bool) or level not in (1, 2, 3):
                    raise ValueError("importance must be 1, 2 or 3")
            except (pydantic.ValidationError, ValueError):
                log.warning(
                    "fact importance unreadable; defaulting to 2", importance=importance
                )
                level = 2
            item = {**item, "importance": level}
            if isinstance(item.get("text"), str):
                item["text"] = _strip_record_age(item["text"])
        try:
            parsed.append(ParsedFact.model_validate(item))
        except pydantic.ValidationError as exc:
            log.warning("facts parse failed", error=str(exc)[:300], tail=raw[-300:])
            return None
    return parsed


def fact_memory_document(fact: Fact) -> dict:
    meta = {
        "typ": "fact",
        "ts": fact.ts if fact.ts is not None else 0,
        "restatements": fact.restatements,
        "importance": fact.importance,
        "false": fact.false,
        **presence_metadata(fact.present),
    }
    if fact.archive_id:
        meta["archive_id"] = fact.archive_id
    if fact.last_seen_ts is not None:
        meta["last_seen_ts"] = fact.last_seen_ts
    if fact.subjects:
        meta["fact_subjects"] = fact.subjects
    return {"id": fact.id, "text": fact.text, "meta": meta}


def facts_for_entry(scene: "Scene", archive_id: str) -> list[Fact]:
    return [
        fact
        for fact in scene.world_state.facts.values()
        if fact.archive_id == archive_id
        or any(source.archive_id == archive_id for source in fact.archive_sources)
        or any(
            item.source.kind == "summary" and item.source.id == archive_id
            for item in fact.contributions
        )
    ]


def previous_facts(scene: "Scene", limit: int = 30) -> list[Fact]:
    from talemate.knowledge.revision_browsing import current_facts

    return ranked_facts(
        scene, current_facts(scene), limit=limit, tiers=False, prompt=False
    )


def prune_summary_facts(world_state, archive_ids: set[str]) -> set[str]:
    """
    Remove the facts of the given archive entries from a WorldState, plus
    the edges that target them. Returns the removed fact ids; memory
    documents are the caller's to delete.
    """
    before = set(world_state.facts)
    references = {
        item.source
        for fact in world_state.facts.values()
        for item in fact.contributions
        if item.source.kind == "summary" and item.source.id in archive_ids
    }
    prune_contributions(world_state, references)
    removed = before - world_state.facts.keys()
    for fact_id, fact in list(world_state.facts.items()):
        explicit = bool(fact.archive_sources)
        sources = tuple(
            source
            for source in fact.archive_sources
            if source.archive_id not in archive_ids
        )
        removed_count = sum(
            source.count
            for source in fact.archive_sources
            if source.archive_id in archive_ids
        )
        affected_primary = fact.archive_id in archive_ids
        if not explicit and affected_primary:
            removed_count = max(removed_count, 1)
        if not removed_count and not affected_primary:
            continue
        fact.archive_sources = sources
        fact.restatements = max(0, fact.restatements - removed_count)
        if affected_primary:
            fact.archive_id = sources[0].archive_id if sources else None
        if sources or fact.dialogue_sources or fact.contributions:
            if fact.archive_id is None and fact.dialogue_sources:
                fact.source = "dialogue"
                if fact.message_id is None:
                    fact.message_id = fact.dialogue_sources[0].message_id
                    fact.message_digest = fact.dialogue_sources[0].message_digest
            continue
        if fact.text_edited or fact.link_edited or fact.source == "manual":
            fact.source = "manual"
            continue
        removed.add(fact_id)
    if not removed:
        return removed
    for fact_id in removed:
        world_state.facts.pop(fact_id, None)
    world_state.knowledge = [
        edge for edge in world_state.knowledge if edge.target not in removed
    ]
    sanitize_fact_links(world_state.facts)
    return removed


def prune_serialized_facts(
    world_state: dict, archive_ids: set[str], *, reset_sources: bool = False
) -> set[str]:
    """`prune_summary_facts` over a serialized world state (an export copy)."""
    facts = world_state.get("facts") or {}
    removed = set()
    for identity, values in list(facts.items()):
        if values.get("contributions"):
            fact = Fact.model_validate(values)
            kept = tuple(
                item
                for item in fact.contributions
                if not reset_sources
                and not (
                    item.source.kind == "summary" and item.source.id in archive_ids
                )
            )
            if kept == fact.contributions:
                continue
            if kept:
                facts[identity] = aggregate_fact(fact, kept).model_dump(mode="json")
            else:
                removed.add(identity)
        else:
            archive_sources = [
                source
                for source in values.get("archive_sources", ())
                if source.get("archive_id") not in archive_ids
            ]
            affected_archive = values.get("archive_id") in archive_ids
            affected_dialogue = reset_sources and values.get("source") == "dialogue"
            if not affected_archive and not affected_dialogue:
                continue
            if archive_sources or (
                not reset_sources and values.get("dialogue_sources")
            ):
                values["archive_sources"] = archive_sources
                if affected_archive:
                    values["archive_id"] = (
                        archive_sources[0]["archive_id"] if archive_sources else None
                    )
                if affected_dialogue:
                    values.pop("message_id", None)
                    values.pop("message_digest", None)
                    values["dialogue_sources"] = []
                    values["source"] = "summary"
                    values["restatements"] = max(
                        0,
                        sum(source.get("count", 1) for source in archive_sources) - 1,
                    )
                continue
            removed.add(identity)
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
        for contribution in fact.get("contributions", []):
            if contribution.get("supersedes") in removed:
                contribution["supersedes"] = None
    return removed


async def drop_facts_for_entries(scene: "Scene", archive_ids: set[str]):
    """Remove the facts (and the edges that target them) of the given archive entries."""
    affected = {
        fact.id
        for fact in scene.world_state.facts.values()
        if any(
            item.source.kind == "summary" and item.source.id in archive_ids
            for item in fact.contributions
        )
    }
    from talemate.knowledge.revision_refresh import capture_revision_mutations

    with capture_revision_mutations(scene):
        removed = prune_summary_facts(scene.world_state, archive_ids)
    retained = affected - removed
    if retained:
        await get_agent("memory").add_many(
            [fact_memory_document(scene.world_state.facts[key]) for key in retained]
        )
    if removed:
        await get_agent("memory").delete({"ids": sorted(removed)})
        # the reset and rebuild paths run while the store may be unavailable;
        # the caller reclusters when it can
        prune_topics(scene.world_state)


async def update_fact(
    scene: "Scene",
    fact_id: str,
    *,
    text: str | _Unset = UNSET,
    importance: FactImportance | _Unset = UNSET,
    false: bool | _Unset = UNSET,
    supersedes: str | None | _Unset = UNSET,
) -> Fact | None:
    """
    Patch the author-editable fields of a stored fact; None when it is no
    longer stored. An omitted field is left alone. A text or link that is
    passed is authored whatever its value, since the editor sends a field only
    when the author saved it: it wins over the contributions from then on,
    `supersedes=None` records an authored clear, and the marks alone touch
    neither flag.
    """
    facts = scene.world_state.facts
    fact = facts.get(fact_id)
    if fact is None:
        return None
    if supersedes is not UNSET and supersedes is not None:
        if supersedes == fact_id:
            raise ValueError("A fact cannot supersede itself")
        if supersedes not in facts:
            raise ValueError(f"Unknown fact: {supersedes}")
    if supersedes is not UNSET and supersedes != fact.supersedes:
        previous = {**facts, fact_id: fact.model_copy()}
        fact.supersedes = supersedes
        # existing links win, so only the new link can be dropped
        sanitize_fact_links(facts, previous)
        fact = facts[fact_id]
        if fact.supersedes != supersedes:
            facts[fact_id] = previous[fact_id]
            raise ValueError("That link would close a supersession loop")
    if supersedes is not UNSET:
        fact.link_edited = True
    if text is not UNSET:
        fact.text = " ".join(text.split())
        fact.text_edited = True
    if importance is not UNSET:
        fact.importance = importance
    if false is not UNSET:
        fact.false = bool(false)
    await get_agent("memory").add_many([fact_memory_document(fact)])
    return fact


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
    archive_id: str | None,
    present: list[str] | None,
    ts: int | None,
    parsed: list[ParsedFact],
    dedupe_distance: float,
    *,
    notify: bool = False,
    message_id: int | None = None,
    message_digest: str | None = None,
    still_current: Callable[[], bool] | None = None,
) -> list[Fact]:
    """
    Store parsed facts for one archive entry; a near-duplicate of a stored
    fact becomes a restatement of it instead.
    """
    world_state = scene.world_state
    from talemate.agents.memory import memory_write_scene

    stored: list[Fact] = []
    # keyed by fact id: a merge updates the stored fact's document, not a second copy
    documents: dict[str, dict] = {}
    changes: list[KnowledgeChange] = []
    staged: dict[str, Fact] = {}
    restatements: dict[str, int] = {}
    grants: list[KnowledgeEdge] = []

    def add_dialogue_support(fact: Fact) -> None:
        if message_id is None or message_digest is None:
            return
        sources = list(fact.dialogue_sources)
        for index, support in enumerate(sources):
            if (
                support.message_id == message_id
                and support.message_digest == message_digest
            ):
                sources[index] = support.model_copy(update={"count": support.count + 1})
                break
        else:
            sources.append(
                DialogueFactSupport(
                    message_id=message_id,
                    message_digest=message_digest,
                )
            )
        fact.dialogue_sources = tuple(sources)

    def add_archive_support(fact: Fact) -> None:
        if archive_id is None:
            return
        sources = list(fact.archive_sources)
        for index, support in enumerate(sources):
            if support.archive_id == archive_id:
                sources[index] = support.model_copy(update={"count": support.count + 1})
                break
        else:
            sources.append(ArchiveFactSupport(archive_id=archive_id))
        fact.archive_sources = tuple(sources)

    for item in parsed:
        item = item.model_copy(update={"text": _strip_record_age(item.text)})
        existing = await _near_duplicate_in_batch(item.text, stored, dedupe_distance)
        if existing is None:
            existing = await _near_duplicate(scene, item.text, dedupe_distance)
        if still_current is not None and not still_current():
            return []
        if existing is not None:
            if still_current is not None:
                if existing.id not in staged:
                    restatements[existing.id] = 0
                existing = staged.setdefault(
                    existing.id, existing.model_copy(deep=True)
                )
                if existing.id in restatements:
                    restatements[existing.id] += 1
            existing.restatements += 1
            add_dialogue_support(existing)
            add_archive_support(existing)
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
                importance=item.importance,
                ts=ts,
                archive_id=archive_id,
                message_id=message_id,
                message_digest=message_digest,
                source="dialogue" if message_id is not None else "summary",
                present=present,
                subjects=item.subjects,
                known_by=(
                    {name: "told" for name in item.known_by if name in (present or [])}
                    if message_id is not None
                    else {}
                ),
                supersedes=supersedes,
                last_seen_ts=ts,
                dialogue_sources=(
                    (
                        DialogueFactSupport(
                            message_id=message_id,
                            message_digest=message_digest,
                        ),
                    )
                    if message_id is not None and message_digest is not None
                    else ()
                ),
                archive_sources=(
                    (ArchiveFactSupport(archive_id=archive_id),)
                    if archive_id is not None
                    else ()
                ),
            )
            if still_current is None:
                world_state.facts[fact.id] = fact
            else:
                staged[fact.id] = fact
            stored.append(fact)
            changes.extend(
                KnowledgeChange(character=name, target=fact.id)
                for name in present or []
            )
            learners = set(item.known_by)
            covered = set(present or [])
            # unknown presence means everyone witnessed it: nothing to grant
            witnessed_all = present is None

        if not witnessed_all:
            for name in sorted(learners - covered):
                if name in fact.known_by:
                    continue
                fact.known_by[name] = "told"
                changes.append(KnowledgeChange(character=name, target=fact.id))
                (world_state.knowledge if still_current is None else grants).append(
                    KnowledgeEdge(
                        character=name,
                        target=fact.id,
                        kind="grant",
                        source="told",
                        message_id=message_id,
                        ts=ts,
                    )
                )

        documents[fact.id] = fact_memory_document(fact)

    if documents:
        with memory_write_scene(scene):
            await get_agent("memory").add_many(list(documents.values()))

    if still_current is not None:
        if not still_current():
            memory = get_agent("memory")
            restore = [
                fact_memory_document(world_state.facts[identity])
                for identity in staged
                if identity in world_state.facts
            ]
            removed = staged.keys() - world_state.facts.keys()
            if restore:
                with memory_write_scene(scene):
                    await memory.add_many(restore)
            if removed:
                with memory_write_scene(scene):
                    await memory.delete({"ids": sorted(removed)})
            return []
        from talemate.knowledge.revision_refresh import capture_revision_mutations

        with capture_revision_mutations(scene):
            removed = restatements.keys() - world_state.facts.keys()
            for identity, fact in staged.items():
                if identity not in restatements:
                    world_state.facts[identity] = fact
                elif identity not in removed:
                    live = world_state.facts[identity]
                    count = restatements[identity]
                    live.restatements += count
                    if message_id is not None and message_digest is not None:
                        sources = list(live.dialogue_sources)
                        for index, support in enumerate(sources):
                            if (
                                support.message_id == message_id
                                and support.message_digest == message_digest
                            ):
                                sources[index] = support.model_copy(
                                    update={"count": support.count + count}
                                )
                                break
                        else:
                            sources.append(
                                DialogueFactSupport(
                                    message_id=message_id,
                                    message_digest=message_digest,
                                    count=count,
                                )
                            )
                        live.dialogue_sources = tuple(sources)
                        if live.message_id is None:
                            live.message_id = message_id
                            live.message_digest = message_digest
                    if archive_id is not None:
                        sources = list(live.archive_sources)
                        for index, support in enumerate(sources):
                            if support.archive_id == archive_id:
                                sources[index] = support.model_copy(
                                    update={"count": support.count + count}
                                )
                                break
                        else:
                            sources.append(
                                ArchiveFactSupport(archive_id=archive_id, count=count)
                            )
                        live.archive_sources = tuple(sources)
                    times = [
                        value for value in (live.last_seen_ts, ts) if value is not None
                    ]
                    live.last_seen_ts = max(times) if times else None
            for grant in grants:
                live = world_state.facts.get(grant.target)
                if live is None:
                    continue
                if grant.target in restatements:
                    if grant.character in live.known_by:
                        continue
                    live.known_by[grant.character] = "told"
                world_state.knowledge.append(grant)
            changes = [change for change in changes if change.target not in removed]
        repair = [
            fact_memory_document(world_state.facts[identity])
            for identity in restatements.keys() - removed
            if fact_memory_document(world_state.facts[identity]) != documents[identity]
        ]
        memory = get_agent("memory")
        if repair:
            with memory_write_scene(scene):
                await memory.add_many(repair)
        if removed:
            with memory_write_scene(scene):
                await memory.delete({"ids": sorted(removed)})

    if notify:
        emit_knowledge_changes(scene, changes)
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
