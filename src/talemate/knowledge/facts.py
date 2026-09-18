"""
Atomic facts: parsed from the summary call, bound to the span line they came
from, stored under the world state, mirrored into the memory store.
"""

import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Callable

import pydantic
import structlog

from talemate.instance import get_agent
from talemate.knowledge.chronology import ranked_facts
from talemate.knowledge.changes import (
    KnowledgeChange,
    drop_fact_edges,
    emit_knowledge_changes,
    is_author_rule,
    lifts_unlearn,
    unlearn_lifted_by,
)
from talemate.knowledge.presence import presence_metadata
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import _acquire, _commit_order
from talemate.knowledge.revision_browsing import current_facts
from talemate.knowledge.schema import (
    INTRO_LINE,
    Fact,
    FactImportance,
    FactRestatement,
    KnowledgeEdge,
    ParsedFact,
)
from talemate.knowledge.supported_facts import (
    prune_contributions,
    sanitize_fact_links,
)
from talemate.knowledge.timeline import refresh_fact_times
from talemate.knowledge.topics import prune_topics
from talemate.util.data import extract_json

if TYPE_CHECKING:
    from talemate.knowledge.cutoff import FactCutoff
    from talemate.tale_mate import Scene

__all__ = [
    "SpanLine",
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
    "fact_is_independent",
    "follow_static_audiences",
    "follow_static_entry_audience",
]

log = structlog.get_logger("talemate.knowledge.facts")


class _Unset:
    """A field the caller did not name; None is a value of its own."""


UNSET = _Unset()


@dataclass(frozen=True)
class SpanLine:
    """One line of an extraction span: the binding a fact from it receives."""

    message_id: int
    message_digest: str
    present: list[str] | None
    ts: int | None


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
        **presence_metadata(fact.present),
    }
    if fact.archive_id:
        meta["archive_id"] = fact.archive_id
    if fact.last_seen_ts is not None:
        meta["last_seen_ts"] = fact.last_seen_ts
    if fact.subjects:
        meta["fact_subjects"] = fact.subjects
    return {"id": fact.id, "text": fact.text, "meta": meta}


def fact_is_independent(world_state, fact: Fact, *, edges: bool = True) -> bool:
    """
    An author-edited fact outlives its source; with `edges`, so does a fact
    the author granted by hand.
    """
    return (
        fact.text_edited
        or fact.link_edited
        or fact.source == "manual"
        or (
            edges
            and any(
                edge.target == fact.id
                and edge.source == "manual"
                and edge.kind != "unlearn"
                for edge in world_state.knowledge
            )
        )
    )


def restatement_learners(
    world_state, fact: Fact, sources: list[tuple[set[str], int | None, int | None]]
) -> list[tuple[set[str], int | None, int | None]]:
    """
    The characters each source of a fact teaches it, as (names, line id, scene
    time): the source's audience that the origin audience does not cover. An
    unknown origin audience covers everyone. A character whose Unlearn the
    source's line lifts is never covered.
    """
    groups = []
    for audience, message_id, ts in sources:
        relearners = {
            edge.character
            for edge in world_state.knowledge
            if edge.kind == "unlearn"
            and edge.target == fact.id
            and unlearn_lifted_by(edge, message_id)
        }
        if fact.present is None:
            learners = audience & relearners
        else:
            learners = audience - (set(fact.present) - relearners)
        if learners:
            groups.append((learners, message_id, ts))
    return groups


def _write_told_grants(world_state, fact: Fact, groups, append, changes) -> None:
    for learners, message_id, ts in groups:
        for name in sorted(learners):
            if name in fact.known_by and not _relearns(
                world_state, name, fact.id, message_id
            ):
                continue
            fact.known_by.setdefault(name, "told")
            changes.append(KnowledgeChange(character=name, target=fact.id))
            append(
                KnowledgeEdge(
                    character=name,
                    target=fact.id,
                    kind="grant",
                    source="told",
                    message_id=message_id,
                    ts=ts,
                )
            )


def _relearns(world_state, character: str, target: str, message_id) -> bool:
    """
    A line newer than the pair's Unlearn records its own grant, even when an
    older grant stands beside the rule: that grant is what lifts the rule.
    """
    return lifts_unlearn(
        world_state.knowledge, character, target, message_id
    ) and not any(
        edge.kind == "grant"
        and edge.character == character
        and edge.target == target
        and edge.message_id == message_id
        for edge in world_state.knowledge
    )


def follow_static_entry_audience(
    world_state, archive_id: str, present: list[str] | None
) -> list[Fact]:
    """
    The facts a static entry recorded, and its restatements of other facts,
    take the entry's audience; a source that restated such a fact teaches
    what that audience no longer covers. Returns the changed facts; their
    memory documents are the caller's to rewrite.
    """
    changed = []
    for fact in world_state.facts.values():
        if fact.contributions:
            continue
        touched = False
        if (
            fact.archive_id == archive_id
            and fact.message_id is None
            and fact.present != present
        ):
            fact.present = list(present) if present is not None else None
            touched = True
        restated_by = tuple(
            item.model_copy(
                update={"present": list(present) if present is not None else None}
            )
            if item.archive_id == archive_id
            and item.message_id is None
            and item.present != present
            else item
            for item in fact.restated_by
        )
        if restated_by != fact.restated_by:
            fact.restated_by = restated_by
            touched = True
        if touched:
            # a source that restated the fact teaches what the entry's audience
            # no longer covers, as it did when the audience was set first
            _write_told_grants(
                world_state,
                fact,
                restatement_learners(
                    world_state,
                    fact,
                    [
                        (
                            set(item.present or []) | set(item.told),
                            item.message_id,
                            item.ts,
                        )
                        for item in fact.restated_by
                    ],
                ),
                world_state.knowledge.append,
                [],
            )
            changed.append(fact)
    return changed


def follow_static_audiences(scene: "Scene") -> set[str]:
    changed = set()
    for entry in scene.archived_history:
        if entry.get("start") is None and entry.get("end") is None and entry.get("id"):
            changed.update(
                fact.id
                for fact in follow_static_entry_audience(
                    scene.world_state, entry["id"], entry.get("present")
                )
            )
    return changed


def facts_for_entry(scene: "Scene", archive_id: str) -> list[Fact]:
    return [
        fact
        for fact in scene.world_state.facts.values()
        if fact.archive_id == archive_id
        or any(item.archive_id == archive_id for item in fact.restated_by)
        or any(
            item.source.kind == "summary" and item.source.id == archive_id
            for item in fact.contributions
        )
    ]


def previous_facts(
    scene: "Scene", limit: int = 30, *, before: "FactCutoff | None" = None
) -> list[Fact]:
    facts = current_facts(scene)
    if before is not None:
        facts = [fact for fact in facts if before.admits(fact)]
    return ranked_facts(scene, facts, limit=limit, tiers=False, prompt=False)


def _binding_key(item) -> tuple[int, int, int]:
    """
    The order of a fact's sources: the earliest is the origin. A static
    entry comes before every message; equal times fall back to the message
    id order.
    """
    return (
        0 if item.message_id is None else 1,
        item.ts if item.ts is not None else 0,
        item.message_id if item.message_id is not None else 0,
    )


def _last_seen(fact: Fact) -> None:
    """`last_seen_ts` is the latest of the fact's own sources."""
    if fact.contributions:
        return
    times = [
        value
        for value in (fact.ts, *(item.ts for item in fact.restated_by))
        if value is not None
    ]
    if times:
        fact.last_seen_ts = max(times)


def _promote_restatement(fact: Fact) -> bool:
    """
    The earliest remaining source becomes the origin once the origin is
    gone, with its audience and time.
    """
    if not fact.restated_by:
        return False
    first = min(fact.restated_by, key=_binding_key)
    fact.message_id = first.message_id
    fact.message_digest = first.message_digest
    fact.archive_id = first.archive_id
    fact.present = list(first.present) if first.present is not None else None
    if first.ts is not None:
        fact.ts = first.ts
    fact.restated_by = tuple(item for item in fact.restated_by if item is not first)
    fact.restatements = max(0, fact.restatements - 1)
    _last_seen(fact)
    return True


def _drop_restatements(fact: Fact, matches: Callable[[FactRestatement], bool]):
    dropped = [item for item in fact.restated_by if matches(item)]
    if dropped:
        fact.restated_by = tuple(item for item in fact.restated_by if not matches(item))
        fact.restatements = max(0, fact.restatements - len(dropped))
        _last_seen(fact)
    return dropped


def prune_summary_facts(
    world_state, archive_ids: set[str], *, keep_rules: bool = False
) -> set[str]:
    """
    Remove the facts of the given archive entries from a WorldState, plus
    the edges that target them. Returns the removed fact ids; memory
    documents are the caller's to delete. With `keep_rules` (a regeneration)
    the author rules of a removed fact wait for its statement.
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
        _drop_restatements(fact, lambda item: item.archive_id in archive_ids)
        if fact.archive_id not in archive_ids:
            continue
        if _promote_restatement(fact):
            continue
        if fact.contributions:
            continue
        if fact_is_independent(world_state, fact, edges=False):
            fact.source = "manual"
            fact.archive_id = None
            continue
        removed.add(fact_id)
    if not removed:
        return removed
    drop_fact_edges(world_state, removed, keep_rules=keep_rules)
    for fact_id in removed:
        world_state.facts.pop(fact_id, None)
    sanitize_fact_links(world_state.facts)
    return removed


def prune_serialized_facts(
    world_state: dict, archive_ids: set[str], *, reset_history: bool = False
) -> set[str]:
    """
    `prune_summary_facts` over a serialized world state (an export copy).
    With `reset_history` every message-bound fact goes too: the copy has no
    messages left to bind them to.
    """
    facts = world_state.get("facts") or {}
    holder = SimpleNamespace(
        facts={key: Fact.model_validate(value) for key, value in facts.items()},
        knowledge=[
            KnowledgeEdge.model_validate(edge)
            for edge in world_state.get("knowledge") or []
        ],
    )
    removed = prune_summary_facts(holder, archive_ids)
    if reset_history:
        # the copy has no messages, views or disclosures to bind facts to
        for identity, fact in list(holder.facts.items()):
            fact.restated_by = tuple(
                item for item in fact.restated_by if item.message_id is None
            )
            fact.restatements = min(fact.restatements, len(fact.restated_by))
            if fact.message_id is None and not fact.contributions:
                continue
            if fact_is_independent(holder, fact, edges=False):
                fact.message_id = None
                fact.message_digest = None
                fact.contributions = ()
                fact.source = "manual"
                continue
            removed.add(identity)
            del holder.facts[identity]
        holder.knowledge = [
            edge
            for edge in holder.knowledge
            if edge.target not in removed and edge.anchor is None
        ]
        sanitize_fact_links(holder.facts)
    if (
        not removed
        and holder.facts
        == {key: Fact.model_validate(value) for key, value in facts.items()}
        and len(holder.knowledge) == len(world_state.get("knowledge") or [])
    ):
        return removed
    world_state["facts"] = {
        key: fact.model_dump(mode="json") for key, fact in holder.facts.items()
    }
    world_state["knowledge"] = [
        edge.model_dump(mode="json") for edge in holder.knowledge
    ]
    return removed


async def drop_facts_for_entries(
    scene: "Scene", archive_ids: set[str], *, keep_rules: bool = True
):
    """
    Remove the facts (and the edges that target them) of the given archive
    entries. By default the entries are regenerated next, so the author rules
    of a removed fact wait for its statement; a reset passes `keep_rules=False`.
    """
    affected = {
        fact.id
        for fact in scene.world_state.facts.values()
        if fact.archive_id in archive_ids
        or any(item.archive_id in archive_ids for item in fact.restated_by)
        or any(
            item.source.kind == "summary" and item.source.id in archive_ids
            for item in fact.contributions
        )
    }
    from talemate.knowledge.revision_refresh import capture_revision_mutations

    with capture_revision_mutations(scene):
        removed = prune_summary_facts(
            scene.world_state, archive_ids, keep_rules=keep_rules
        )
        if not keep_rules:
            drop_dead_anchors(scene)
        affected.update(refresh_fact_times(scene, affected))
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
    supersedes: str | None | _Unset = UNSET,
) -> Fact | None:
    """
    Patch the author-editable fields of a stored fact; None when it is no
    longer stored. An omitted field is left alone. A text or link that is
    passed is authored whatever its value, since the editor sends a field only
    when the author saved it: it wins over the contributions from then on,
    `supersedes=None` records an authored clear, and an importance alone
    touches neither flag.
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


def _restated(
    fact: Fact,
    line: SpanLine | None,
    archive_id: str | None,
    *,
    present: list[str] | None = None,
    ts: int | None = None,
    told: list[str] = (),
) -> FactRestatement | None:
    """
    Record `line` (or, without a line, the static entry `archive_id` with
    its `present` and `ts`) as a restatement of `fact`. The origin is always
    the earliest source: a source before the origin takes its place, and the
    origin becomes a restatement. Returns the demoted origin in that case.
    """
    if line is not None and (
        fact.message_id == line.message_id
        or any(item.message_id == line.message_id for item in fact.restated_by)
    ):
        return None
    item = FactRestatement(
        message_id=line.message_id if line else None,
        message_digest=line.message_digest if line else None,
        archive_id=archive_id,
        present=list(line.present)
        if line is not None and line.present is not None
        else list(present)
        if line is None and present is not None
        else None,
        ts=line.ts if line else ts,
        told=list(told),
    )
    demoted = None
    if fact.message_id is not None and _binding_key(item) < _binding_key(fact):
        demoted = FactRestatement(
            message_id=fact.message_id,
            message_digest=fact.message_digest,
            archive_id=fact.archive_id,
            present=fact.present,
            ts=fact.ts,
        )
        fact.message_id = item.message_id
        fact.message_digest = item.message_digest
        fact.archive_id = item.archive_id
        fact.present = list(item.present) if item.present is not None else None
        fact.ts = item.ts
        item = demoted
    fact.restatements += 1
    fact.restated_by = (*fact.restated_by, item)
    _last_seen(fact)
    return demoted


def verify_restatements(
    parsed: list[ParsedFact], offered: set[str]
) -> list[ParsedFact]:
    """
    `restates` is a model verdict: it counts only for an id the request
    offered in its known-facts list. Any other id is dropped, and the
    statement is stored as a new fact.
    """
    result = []
    for item in parsed:
        if item.restates is not None and item.restates not in offered:
            log.warning(
                "fact restates an id the request did not offer; stored as new",
                restates=item.restates,
                text=item.text[:80],
            )
            item = item.model_copy(update={"restates": None})
        result.append(item)
    return result


def verify_links(parsed: list[ParsedFact], offered: set[str]) -> list[ParsedFact]:
    """
    `restates` and `supersedes` name facts from the request's known-facts
    list; a link to any other id is dropped.
    """
    result = []
    for item in verify_restatements(parsed, offered):
        if item.supersedes is not None and item.supersedes not in offered:
            log.warning(
                "fact supersedes an id the request did not offer; link dropped",
                supersedes=item.supersedes,
                text=item.text[:80],
            )
            item = item.model_copy(update={"supersedes": None})
        result.append(item)
    return result


async def store_facts(
    scene: "Scene",
    archive_id: str | None,
    parsed: list[ParsedFact],
    dedupe_distance: float,
    *,
    lines: dict[int, SpanLine] | None = None,
    intro: SpanLine | None = None,
    present: list[str] | None = None,
    ts: int | None = None,
    notify: bool = False,
    still_current: Callable[[], bool] | None = None,
) -> list[Fact]:
    """
    Store parsed facts for one archive entry.

    With `lines` every fact must name one of the span's lines (or the opening
    through `intro`); a fact that names no readable line is dropped. Without
    `lines` (a static entry) facts carry the entry's `present` and `ts`. A
    fact the model links through `restates`, or a near-duplicate of a stored
    fact, becomes a restatement of that fact instead of a record of its own.
    """
    world_state = scene.world_state
    from talemate.agents.memory import memory_write_scene

    stored: list[Fact] = []
    # keyed by fact id: a merge updates the stored fact's document, not a second copy
    documents: dict[str, dict] = {}
    changes: list[KnowledgeChange] = []
    staged: dict[str, Fact] = {}
    # fact id -> (line, audience, scene time, named learners) of each staged restatement
    restatements: dict[str, list[tuple]] = {}
    grants: list[KnowledgeEdge] = []
    # (fact id, line id) of every statement this span records
    recorded: list[tuple[str, int | None]] = []

    for item in parsed:
        item = item.model_copy(update={"text": _strip_record_age(item.text)})
        if lines is None:
            line = None
            line_present, line_ts = present, ts
        else:
            line = (
                intro if item.message_id == INTRO_LINE else lines.get(item.message_id)
            )
            if line is None:
                log.warning(
                    "fact names no line of its span; dropped",
                    archive_id=archive_id,
                    message_id=item.message_id,
                    text=item.text[:80],
                )
                continue
            line_present, line_ts = line.present, line.ts
        existing = (
            world_state.facts.get(item.restates) if item.restates is not None else None
        )
        if item.restates is not None and existing is None:
            log.warning("fact restates an unknown fact id", restates=item.restates)
        if existing is None:
            existing = await _near_duplicate_in_batch(
                item.text, stored, dedupe_distance
            )
        if existing is None:
            existing = await _near_duplicate(scene, item.text, dedupe_distance)
        if still_current is not None and not still_current():
            return []
        if existing is not None:
            if still_current is not None:
                if existing.id not in staged:
                    restatements[existing.id] = []
                existing = staged.setdefault(
                    existing.id, existing.model_copy(deep=True)
                )
                if existing.id in restatements:
                    restatements[existing.id].append(
                        (line, line_present, line_ts, list(item.known_by))
                    )
            witnesses = set(existing.present or [])
            demoted = _restated(
                existing,
                line,
                archive_id,
                present=line_present,
                ts=line_ts,
                told=item.known_by,
            )
            times = [
                value for value in (existing.last_seen_ts, line_ts) if value is not None
            ]
            existing.last_seen_ts = max(times) if times else None
            fact = existing
            recorded.append((fact.id, line.message_id if line else None))
            # the restating line's audience learned the stored fact; when the
            # line became the origin, the audience of the demoted one learned
            # it at the demoted line
            # the gate reads the audience after a swap: an unknown audience of
            # the demoted line does not stop the grants of the new origin
            sources = [
                (
                    set(line_present or []) | set(item.known_by),
                    line.message_id if line else None,
                    line_ts,
                )
            ]
            if demoted is not None:
                sources.append((witnesses, demoted.message_id, demoted.ts))
            groups = restatement_learners(world_state, existing, sources)
        else:
            world_state.fact_counter += 1
            supersedes = (
                item.supersedes if item.supersedes in world_state.facts else None
            )
            fact = Fact(
                id=f"F{world_state.fact_counter}",
                text=item.text,
                importance=item.importance,
                ts=line_ts,
                archive_id=archive_id,
                message_id=line.message_id if line else None,
                message_digest=line.message_digest if line else None,
                present=line_present,
                subjects=item.subjects,
                supersedes=supersedes,
                last_seen_ts=line_ts,
            )
            if still_current is None:
                world_state.facts[fact.id] = fact
            else:
                staged[fact.id] = fact
            stored.append(fact)
            recorded.append((fact.id, line.message_id if line else None))
            changes.extend(
                KnowledgeChange(character=name, target=fact.id)
                for name in line_present or []
            )
            # unknown presence means everyone witnessed it: nothing to grant
            groups = restatement_learners(
                world_state,
                fact,
                [(set(item.known_by), line.message_id if line else None, line_ts)],
            )

        _write_told_grants(
            world_state,
            fact,
            groups,
            (world_state.knowledge if still_current is None else grants).append,
            changes,
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
                    for line, audience, when, told in restatements[identity]:
                        _restated(
                            live,
                            line,
                            archive_id,
                            present=audience,
                            ts=when,
                            told=told,
                        )
                    times = [
                        value
                        for value in (live.last_seen_ts, fact.last_seen_ts)
                        if value is not None
                    ]
                    live.last_seen_ts = max(times) if times else None
            for grant in grants:
                live = world_state.facts.get(grant.target)
                if live is None:
                    continue
                if grant.target in restatements:
                    if grant.character in live.known_by and not _relearns(
                        world_state, grant.character, grant.target, grant.message_id
                    ):
                        continue
                    live.known_by.setdefault(grant.character, "told")
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

    await reattach_author_rules(
        scene,
        recorded,
        archive_id=archive_id,
        span=set(lines) if lines else set(),
        dedupe_distance=dedupe_distance,
    )

    if notify:
        emit_knowledge_changes(scene, changes)
    return stored


def _anchor_alive(scene: "Scene", anchor) -> bool:
    if anchor.message_id is not None:
        return scene.get_message(anchor.message_id) is not None
    return any(entry.get("id") == anchor.archive_id for entry in scene.archived_history)


def drop_dead_anchors(scene: "Scene") -> None:
    """A waiting rule goes with the line or entry its statement came from."""
    world_state = scene.world_state
    world_state.knowledge = [
        edge
        for edge in world_state.knowledge
        if edge.anchor is None or _anchor_alive(scene, edge.anchor)
    ]


async def reattach_author_rules(
    scene: "Scene",
    recorded: list[tuple[str, int | None]],
    *,
    archive_id: str | None,
    span: set[int],
    dedupe_distance: float,
) -> None:
    """
    An author rule, or a learning from dialogue, whose fact a regeneration
    removed takes over the fact that records the same statement again: from a
    line of the same span, or, for a fact without a line, from the same entry.
    The same text matches at once; other wording matches within the fact
    matching tolerance. A rule whose line or entry is gone goes.
    """
    world_state = scene.world_state
    if not any(edge.anchor is not None for edge in world_state.knowledge):
        return
    drop_dead_anchors(scene)
    waiting = [
        edge
        for edge in world_state.knowledge
        if edge.anchor is not None
        and (
            edge.anchor.message_id in span
            if edge.anchor.message_id is not None
            else edge.anchor.archive_id == archive_id
        )
    ]
    facts = [
        world_state.facts[identity]
        for identity in dict.fromkeys(identity for identity, _ in recorded)
        if identity in world_state.facts
    ]
    if not waiting or not facts:
        return
    matches: dict[str, str] = {}
    for edge in waiting:
        text = edge.anchor.text.strip().casefold()
        fact = next((f for f in facts if f.text.strip().casefold() == text), None)
        if fact is not None:
            matches[edge.id] = fact.id
    rest = [edge for edge in waiting if edge.id not in matches]
    if rest:
        result = await get_agent("memory").compare_string_lists(
            [edge.anchor.text for edge in rest],
            [fact.text for fact in facts],
            distance_threshold=dedupe_distance,
        )
        for index, fact_index, *_ in sorted(
            result["distance_matches"], key=lambda match: match[-1]
        ):
            matches.setdefault(rest[index].id, facts[fact_index].id)
    from talemate.knowledge.revision_refresh import capture_revision_mutations

    with capture_revision_mutations(scene):
        _move_waiting_rules(world_state, matches)


def _hand_order(old: KnowledgeEdge, new: KnowledgeEdge) -> tuple[bool, bool]:
    """
    Which of two author rules of one pair stay, (old, new), when `new` was
    written after `old`: the pair's knowledge state after setting them by hand
    in that order. The by-hand paths keep the older edge of a duplicate Learn,
    so they can hold a different edge of the same kind with the same effect.
    """
    if old.kind == new.kind:
        # the newer rule takes the older's place, so a newer Learn is never
        # refused and a newer Unlearn carries the newer boundary
        return (False, True)
    kinds = (old.kind, new.kind)
    if kinds == ("revoke", "grant"):
        # a Learn lifts an older Never Learn
        return (False, True)
    if kinds == ("grant", "revoke"):
        # a Never Learn stays beside an older Learn, and the bucket orders them
        return (True, True)
    if "revoke" in kinds:
        # a Never Learn replaces an Unlearn, and no Unlearn applies beside it
        return (old.kind == "revoke", new.kind == "revoke")
    # a Learn and an Unlearn replace each other: the newer one stays
    return (False, True)


def _replay_rules(
    candidates: list[KnowledgeEdge], position: dict[str, int]
) -> list[KnowledgeEdge]:
    """
    The edges that remain when the candidates meet in list order, giving the
    pair the knowledge state it has after setting them by hand in that order.
    A newer rule of the same kind takes the older's place, and the older's note
    when it has none of its own.
    """
    survivors = []
    for rule in sorted(candidates, key=lambda item: position[item.id]):
        verdicts = []
        for kept in survivors:
            keep_old, keep_new = _hand_order(kept, rule)
            if kept.kind == rule.kind and not rule.note:
                rule.note = kept.note
            verdicts.append((kept, keep_old, keep_new))
        if all(keep_new for _, _, keep_new in verdicts):
            survivors = [kept for kept, keep_old, _ in verdicts if keep_old] + [rule]
    return survivors


def _move_waiting_rules(world_state, matches: dict[str, str]) -> None:
    """
    Move each matched waiting edge to its new fact, in list order (older
    first). The author rules that meet on one pair keep the pair's by-hand
    knowledge state (`_hand_order`): the pair is replayed in list order, so a
    later rule still lifts an earlier Never Learn, and a dropped rule's note
    moves to the same-kind rule that replaces it. A moved Unlearn gets the
    told grants that the fact's sources owe it, since those were computed
    before the rule arrived.
    """
    position = {edge.id: index for index, edge in enumerate(world_state.knowledge)}
    rules: dict[tuple[str, str], list[KnowledgeEdge]] = {}
    incoming: dict[tuple[str, str], list[KnowledgeEdge]] = {}
    grants: set[tuple] = set()
    for edge in world_state.knowledge:
        if edge.anchor is not None:
            continue
        if is_author_rule(edge):
            rules.setdefault((edge.character, edge.target), []).append(edge)
        else:
            grants.add((edge.character, edge.target, edge.source, edge.message_id))
    dropped: set[str] = set()
    for edge in world_state.knowledge:
        target = matches.get(edge.id)
        fact = world_state.facts.get(target) if target is not None else None
        if fact is None:
            continue
        if not is_author_rule(edge):
            key = (edge.character, target, edge.source, edge.message_id)
            if key in grants:
                dropped.add(edge.id)
                continue
            grants.add(key)
            fact.known_by.setdefault(edge.character, edge.source)
        else:
            incoming.setdefault((edge.character, target), []).append(edge)
        edge.target = target
        edge.anchor = None
    unlearned: list[Fact] = []
    for pair, moved in incoming.items():
        candidates = rules.get(pair, []) + moved
        survivors = _replay_rules(candidates, position)
        surviving = {rule.id for rule in survivors}
        for rule in candidates:
            if rule.id not in surviving:
                dropped.add(rule.id)
        for rule in moved:
            if rule.id in surviving and rule.kind == "unlearn":
                unlearned.append(world_state.facts[pair[1]])
    world_state.knowledge = [
        edge for edge in world_state.knowledge if edge.id not in dropped
    ]
    for identity in dict.fromkeys(fact.id for fact in unlearned):
        fact = world_state.facts[identity]
        sources = [
            (set(item.present or []) | set(item.told), item.message_id, item.ts)
            for item in fact.restated_by
        ]
        if fact.message_id is not None:
            # the fact's own line lifts the rule too when it is the later one
            sources.insert(0, (set(fact.present or []), fact.message_id, fact.ts))
        _write_told_grants(
            world_state,
            fact,
            restatement_learners(world_state, fact, sources),
            world_state.knowledge.append,
            [],
        )


async def store_offscreen_fact(
    scene: "Scene",
    character: str,
    text: str,
    *,
    still_current: Callable[[], bool] = lambda: True,
) -> Fact | None:
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
    from talemate.agents.memory import memory_write_scene

    try:
        with memory_write_scene(scene):
            await get_agent("memory").add_many([fact_memory_document(fact)])
        if not still_current():
            get_agent("summarizer").queue_fact_memory(scene, {fact.id})
            return None
    except BaseException:
        # The memory write can finish even after cancellation. The canonical
        # fact is unpublished; reconcile any residual index document.
        get_agent("summarizer").queue_fact_memory(scene, {fact.id})
        raise
    if character_knowledge_enabled(scene):
        fact.acquired = _acquire(scene)
        _commit_order(scene, fact.acquired)
    world_state.facts[fact.id] = fact
    log.debug("offscreen fact stored", id=fact.id, character=character)
    return fact
