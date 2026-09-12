"""Revision refresh coordination shared by explicit keep and next-send catch-up."""

import asyncio
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from weakref import WeakKeyDictionary

from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.facts import prune_summary_facts, store_facts
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.schema import Fact, KnowledgeEdge
from talemate.knowledge.topics import refresh_topics
from talemate.scene_message import CharacterMessage

_active_transaction = ContextVar("revision_refresh_transaction", default=None)
_archive_vector_repairs = WeakKeyDictionary()
_catch_up_locks = WeakKeyDictionary()
_catch_up_owners = WeakKeyDictionary()


@dataclass(frozen=True)
class RevisionOperations:
    perceptions: bool = False
    extract_facts: bool = False
    learn_facts: bool = False

    @property
    def any(self) -> bool:
        return self.perceptions or self.extract_facts or self.learn_facts

    def names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, enabled in (
                ("perceptions", self.perceptions),
                ("facts", self.extract_facts),
                ("learning", self.learn_facts),
            )
            if enabled
        )


def revision_operations(scene, message) -> RevisionOperations:
    """Resolve eligibility from the effective scene-aware configuration."""
    content = message.perception_text if message is not None else ""
    if isinstance(message, CharacterMessage) and ":" in content:
        content = content.split(":", 1)[1]
    if (
        message is None
        or not any(entry is message for entry in scene.history)
        or not message.supports_perceptions
        or message.hidden
        or not content.strip()
        or message.revision_state is None
    ):
        return RevisionOperations()
    if character_knowledge_enabled(scene):
        from talemate.agents.summarize.perceptions import (
            eligible_passage,
            relevant_audiences,
        )

        return RevisionOperations(
            perceptions=eligible_passage(message)
            and bool(relevant_audiences(scene, message))
        )
    summarizer = get_agent("summarizer")
    conversation = get_agent("conversation")
    extraction = bool(
        summarizer.enabled
        and summarizer.resolve_enabled("archive")
        and summarizer.resolve_config("archive", "extract_facts")
    )
    learning = bool(
        isinstance(message, CharacterMessage)
        and conversation.enabled
        and conversation.resolve_enabled("character_knowledge")
        and conversation.resolve_config("character_knowledge", "ledger")
    )
    return RevisionOperations(extract_facts=extraction, learn_facts=learning)


def _identity(scene, message, operations: RevisionOperations) -> str:
    state = message.revision_state
    values = {
        "scene": id(scene),
        "message": message.id,
        "index": message.active_version,
        "digest": message.revision_digest(),
        "serial": state.serial if state else 0,
        "active": scene.active,
    }
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _phase_identity(scene, message, phase: str, recent=None, *, journal=None) -> str:
    summarizer = get_agent("summarizer")
    state = message.revision_state
    values = {
        "message": message.id,
        "digest": message.revision_digest(),
        "recent": (
            recent if recent is not None else _historical_context(scene, message)[0]
        ),
        "eligibility": scene.knowledge_eligibility,
    }
    if phase == "perceptions":
        from talemate.agents.summarize.perceptions import perception_context

        context = perception_context(scene, message)
        context["passage"]["provenance"].pop("revision", None)
        values["context"] = context
        values["settings"] = {
            "enabled": summarizer.resolve_enabled("perceptions"),
            "repair": summarizer.resolve_config("perceptions", "automatic_repair"),
        }
    else:
        journal = (
            journal
            if journal is not None
            else (state.refresh_journal if state else None)
        )
        facts = _normalized_fact_inputs(scene, message, journal, phase)
        if phase == "extract":
            stripped = {}
            for identity, fact in facts.items():
                fact = _without_message_fact_support(fact, message)
                if fact is not None:
                    stripped[identity] = fact
            facts = stripped
        values["facts"] = facts
    if phase == "extract":
        values["settings"] = {
            "method": summarizer.resolve_config("archive", "method"),
            "instructions": summarizer.resolve_config("archive", "instructions"),
            "dedupe": summarizer.resolve_config("archive", "fact_dedupe_distance"),
        }
        if _affected_history_entries(scene, message):
            values["archive_inputs"] = _archive_phase_inputs(
                scene, message, phase, journal=journal
            )
    elif phase == "learn":
        conversation = get_agent("conversation")
        values["settings"] = {
            "ledger": conversation.resolve_config("character_knowledge", "ledger"),
            "establish": conversation.resolve_config(
                "character_knowledge", "establish_facts"
            ),
            "absence_window": conversation.resolve_config(
                "character_knowledge", "absence_window"
            ),
        }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, default=str).encode()
    ).hexdigest()


def _receipts_current(
    scene,
    message,
    operations: RevisionOperations,
    *,
    state=None,
    journal=None,
) -> bool:
    state = state or message.revision_state
    if state is None:
        return False
    expected = (
        ("perceptions", "refresh:perceptions", operations.perceptions),
        ("extract", "refresh:extract", operations.extract_facts),
        ("learn", "refresh:learn", operations.learn_facts),
    )
    return all(
        not enabled
        or state.phase_receipts.get(receipt)
        == _phase_identity(scene, message, phase, journal=journal)
        for phase, receipt, enabled in expected
    )


def revision_requires_refresh(scene, message, operations=None) -> bool:
    """Include missing revised-source results without backfilling pristine history."""
    if not message.revision_matches_baseline:
        return True
    if (
        message.revision_state.refresh_journal is not None
        and message.revision_state.status in ("running", "failed")
    ):
        return True
    if not character_knowledge_enabled(scene) or (
        len(message.versions) <= 1 and message.revision_state.serial == 0
    ):
        return False
    operations = operations or revision_operations(scene, message)
    if operations.perceptions:
        from talemate.agents.summarize.perceptions import perception_results_current

        return not perception_results_current(scene, message)
    return False


def revision_refresh_payload(scene, message) -> dict:
    operations = revision_operations(scene, message)
    dirty = revision_requires_refresh(scene, message, operations)
    status = message.revision_state.status if message.revision_state else "clean"
    if operations.perceptions:
        label = "Analyze perceptions"
        explanation = "Perception analysis for this version has not run yet."
        running = "Analyzing perceptions…"
    elif operations.extract_facts or operations.learn_facts:
        label = "Refresh facts"
        explanation = "Facts for this version have not been refreshed yet."
        running = "Refreshing facts…"
    else:
        label = explanation = running = None
    return {
        "revision_refresh": {
            "scene_id": scene.id,
            "message_id": message.id,
            "selection_index": message.active_version,
            "selection_digest": message.revision_digest(),
            "selection_serial": (
                message.revision_state.serial if message.revision_state else 0
            ),
            "required": dirty and operations.any,
            "status": status,
            "operations": list(operations.names()),
            "label": label,
            "explanation": explanation,
            "running_label": running,
            "deferred_hint": (
                "If you skip it, this runs when you send your next line."
                if dirty and operations.any
                else None
            ),
        }
    }


def _scene_owned(scene, operations: RevisionOperations) -> bool:
    summarizer = get_agent("summarizer")
    if summarizer.scene is not scene:
        return False
    if operations.learn_facts and get_agent("conversation").scene is not scene:
        return False
    return True


def _memory_scene_owned(scene) -> bool:
    memory = get_agent("memory")
    return getattr(memory, "scene", scene) is scene


def _current(
    scene,
    message,
    identity: str,
    expected_operations: RevisionOperations | None = None,
) -> bool:
    operations = revision_operations(scene, message)
    return bool(
        _scene_owned(scene, operations)
        and (expected_operations is None or operations == expected_operations)
        and any(entry is message for entry in scene.history)
        and message.revision_state is not None
        and _identity(scene, message, operations) == identity
    )


def _dump(value):
    return value.model_dump(mode="json") if value is not None else None


def _restore_fact_data(message, current_data, written, original):
    """Remove one transaction-owned fact delta from a serialized live record."""
    if current_data == written:
        return original, True
    if current_data is None or written is None:
        return current_data, False
    current = Fact.model_validate(current_data)
    if original is None:
        current.dialogue_sources = tuple(
            source
            for source in current.dialogue_sources
            if source.message_id != message.id
        )
        if current.message_id == message.id:
            current.message_id = None
            current.message_digest = None
        if current.text_edited or current.link_edited:
            current.source = "manual"
        return _dump(current), False

    merged = dict(current_data)
    written_data = written or {}
    structured = {
        "archive_sources",
        "dialogue_sources",
        "known_by",
        "restatements",
    }
    for key in (
        current_data.keys() | written_data.keys() | original.keys()
    ) - structured:
        if current_data.get(key) != written_data.get(key):
            continue
        if key in original:
            merged[key] = original[key]
        else:
            merged.pop(key, None)

    original_restatements = original.get("restatements", 0)
    written_restatements = written_data.get("restatements", 0)
    current_restatements = current_data.get("restatements", 0)
    owned_restatements = written_restatements - original_restatements
    merged["restatements"] = max(0, current_restatements - owned_restatements)

    original_known = original.get("known_by", {})
    written_known = written_data.get("known_by", {})
    current_known = dict(current_data.get("known_by", {}))
    for character in original_known.keys() | written_known.keys():
        if current_known.get(character) != written_known.get(character):
            continue
        if character in original_known:
            current_known[character] = original_known[character]
        else:
            current_known.pop(character, None)
    merged["known_by"] = current_known

    def restore_supports(field, key_fields):
        def support_map(records):
            return {
                tuple(record[key] for key in key_fields): record.get("count", 1)
                for record in records
            }

        original_support = support_map(original.get(field, ()))
        written_support = support_map(written_data.get(field, ()))
        current_support = support_map(current_data.get(field, ()))
        order = [
            tuple(record[key] for key in key_fields)
            for record in current_data.get(field, ())
        ]
        for support in original_support:
            if support not in order:
                order.append(support)
        for support in original_support.keys() | written_support.keys():
            owned_count = written_support.get(support, 0) - original_support.get(
                support, 0
            )
            restored_count = current_support.get(support, 0) - owned_count
            if restored_count > 0:
                current_support[support] = restored_count
            else:
                current_support.pop(support, None)
        merged[field] = [
            {
                **dict(zip(key_fields, support)),
                "count": current_support[support],
            }
            for support in order
            if support in current_support
        ]

    restore_supports("dialogue_sources", ("message_id", "message_digest"))
    restore_supports("archive_sources", ("archive_id",))
    return merged, False


def _normalized_fact_inputs(scene, message, journal, phase: str) -> dict:
    """Live fact inputs with this transaction's own unconsumed effects removed."""
    facts = {
        identity: _dump(fact) for identity, fact in scene.world_state.facts.items()
    }
    for mutation in reversed((journal or {}).get("mutations", ())):
        if (
            mutation.get("restored")
            or mutation.get("group") != "facts"
            or (phase == "learn" and mutation.get("phase") != "learn")
        ):
            continue
        identity = mutation["identity"]
        restored, _ = _restore_fact_data(
            message,
            facts.get(identity),
            mutation.get("after"),
            mutation.get("before"),
        )
        if restored is None:
            facts.pop(identity, None)
        else:
            facts[identity] = restored
    return facts


def _without_message_fact_support(fact_data, message):
    """Remove only this passage's provenance while retaining independent support."""
    fact = Fact.model_validate(fact_data)
    matching = [
        source for source in fact.dialogue_sources if source.message_id == message.id
    ]
    if matching:
        fact.dialogue_sources = tuple(
            source
            for source in fact.dialogue_sources
            if source.message_id != message.id
        )
        fact.restatements = max(
            0, fact.restatements - sum(source.count for source in matching)
        )
    if fact.message_id == message.id:
        if fact.dialogue_sources:
            fact.message_id = fact.dialogue_sources[0].message_id
            fact.message_digest = fact.dialogue_sources[0].message_digest
        else:
            fact.message_id = None
            fact.message_digest = None
    independent = bool(
        fact.dialogue_sources
        or fact.archive_sources
        or fact.contributions
        or fact.text_edited
        or fact.link_edited
        or fact.source == "manual"
    )
    if not independent:
        return None
    if fact.text_edited or fact.link_edited:
        fact.source = "manual"
    elif not fact.dialogue_sources and fact.archive_sources:
        fact.source = "summary"
        fact.archive_id = fact.archive_sources[0].archive_id
    return _dump(fact)


def _perspective_snapshot(scene) -> dict:
    from talemate.knowledge.perspectives import _sources

    return {
        json.dumps(source.key, separators=(",", ":")): _dump(source.knowledge)
        for source in _sources(scene)
    }


def _restore_perspective_record(scene, identity: str, written, original) -> None:
    from talemate.knowledge.perspective_models import SourcePerspectives
    from talemate.knowledge.perspectives import _find

    source = _find(scene, tuple(json.loads(identity)))
    if source is None or _dump(source.knowledge) != written:
        return
    if original is None and isinstance(source.owner, dict):
        source.owner.pop("knowledge", None)
        return
    source.knowledge = (
        SourcePerspectives.model_validate(original) if original is not None else None
    )


def _restore_fact_record(scene, message, identity, written, original) -> bool:
    current = scene.world_state.facts.get(identity)
    current_data = _dump(current)
    restored, exact = _restore_fact_data(message, current_data, written, original)
    if restored is None:
        scene.world_state.facts.pop(identity, None)
    elif restored != current_data:
        scene.world_state.facts[identity] = Fact.model_validate(restored)
    return exact


def _record_snapshot(scene, message) -> dict:
    archives = {
        f"base:{entry['id']}": entry.copy()
        for entry in scene.archived_history
        if entry.get("id")
    }
    for layer, entries in enumerate(scene.layered_history):
        archives.update(
            {
                f"layer:{layer}:{entry['id']}": entry.copy()
                for entry in entries
                if entry.get("id")
            }
        )
    archive_positions = {}
    for layer, entries in enumerate([scene.archived_history, *scene.layered_history]):
        prefix = "base" if layer == 0 else f"layer:{layer - 1}"
        for index, entry in enumerate(entries):
            if not entry.get("id"):
                continue
            archive_positions[f"{prefix}:{entry['id']}"] = {
                "index": index,
                "previous": entries[index - 1].get("id") if index else None,
                "next": (
                    entries[index + 1].get("id") if index + 1 < len(entries) else None
                ),
            }
    return {
        "knowledge": _dump(message.knowledge),
        "perspectives": _perspective_snapshot(scene),
        "facts": {
            identity: _dump(fact) for identity, fact in scene.world_state.facts.items()
        },
        "edges": {edge.id: _dump(edge) for edge in scene.world_state.knowledge},
        "archives": archives,
        "archive_positions": archive_positions,
    }


def _journal(scene, message) -> dict:
    state = message.revision_state
    snapshot = _record_snapshot(scene, message)
    from talemate.knowledge.revision_browsing import affected_archive_ids

    archive_ids = affected_archive_ids(scene, message)
    fact_ids = {
        identity
        for identity, fact in scene.world_state.facts.items()
        if fact.message_id == message.id
        or any(source.message_id == message.id for source in fact.dialogue_sources)
        or fact.archive_id in archive_ids
        or any(source.archive_id in archive_ids for source in fact.archive_sources)
        or any(
            item.source.kind == "summary" and item.source.id in archive_ids
            for item in fact.contributions
        )
    }
    edge_ids = {
        edge.id
        for edge in scene.world_state.knowledge
        if edge.message_id == message.id or edge.target in fact_ids
    }
    return {
        "baseline_digest": state.baseline_digest,
        "baseline_index": state.baseline_index,
        "baseline_content_digest": (
            content_digest(message.versions[state.baseline_index].message)
            if 0 <= state.baseline_index < len(message.versions)
            else None
        ),
        "baseline_features": list(state.completed_features),
        "baseline_receipts": dict(state.phase_receipts),
        "affected_archive_ids": sorted(archive_ids),
        "baseline": {
            "knowledge": snapshot["knowledge"],
            "perspectives": {},
            "facts": {identity: snapshot["facts"][identity] for identity in fact_ids},
            "edges": {identity: snapshot["edges"][identity] for identity in edge_ids},
            "archives": {
                key: value
                for key, value in snapshot["archives"].items()
                if value.get("id") in archive_ids
            },
        },
        "writes": {"perspectives": {}, "facts": {}, "edges": {}, "archives": {}},
        "phase_writes": {},
        "mutations": [],
    }


def begin_revision_transaction(scene, message) -> None:
    """Capture the committed source slice before revision work can invalidate it."""
    state = message.revision_state
    if state is None or state.refresh_journal is not None:
        return
    message.set_revision_status(state.status, refresh_journal=_journal(scene, message))


def _record_transaction_writes(scene, message, before: dict, phase: str) -> None:
    state = message.revision_state
    if state is None or state.refresh_journal is None:
        return
    journal = state.refresh_journal.copy()
    baseline = {**journal.get("baseline", {})}
    writes = {**journal.get("writes", {})}
    phase_writes = {
        key: {group: dict(records) for group, records in value.items()}
        for key, value in journal.get("phase_writes", {}).items()
    }
    mutations = list(journal.get("mutations", ()))
    owned = phase_writes.setdefault(phase, {})
    after = _record_snapshot(scene, message)
    if before["knowledge"] != after["knowledge"]:
        baseline.setdefault("knowledge", before["knowledge"])
        writes["knowledge"] = after["knowledge"]
        mutations.append(
            {
                "phase": phase,
                "group": "knowledge",
                "identity": None,
                "before": before["knowledge"],
                "after": after["knowledge"],
            }
        )
    for group in ("perspectives", "facts", "edges", "archives"):
        base_group = dict(baseline.get(group, {}))
        write_group = dict(writes.get(group, {}))
        for identity in before[group].keys() | after[group].keys():
            old = before[group].get(identity)
            new = after[group].get(identity)
            if old == new:
                continue
            base_group.setdefault(identity, old)
            write_group[identity] = new
            owned.setdefault(group, {})[identity] = new
            mutations.append(
                {
                    "phase": phase,
                    "group": group,
                    "identity": identity,
                    "before": old,
                    "after": new,
                    **(
                        {
                            "before_position": before["archive_positions"].get(
                                identity
                            ),
                            "after_position": after["archive_positions"].get(identity),
                        }
                        if group == "archives"
                        else {}
                    ),
                }
            )
        baseline[group] = base_group
        writes[group] = write_group
    journal["baseline"] = baseline
    journal["writes"] = writes
    journal["phase_writes"] = phase_writes
    journal["mutations"] = mutations
    message.set_revision_status(state.status, refresh_journal=journal)


@contextmanager
def revision_phase(scene, message, phase: str):
    """Make synchronous mutation seams inside one awaited phase journal-aware."""
    token = _active_transaction.set((scene, message, phase))
    try:
        yield
    finally:
        _active_transaction.reset(token)


@contextmanager
def capture_revision_mutations(scene, *, message=None, phase: str | None = None):
    """Journal only mutations performed inside this synchronous write seam.

    The surrounding model await is intentionally outside the snapshot window:
    another task can write while generation is pending, and those writes must
    never be claimed by this revision transaction.
    """
    active = _active_transaction.get()
    if active is not None and active[0] is scene:
        _, active_message, active_phase = active
        if message is None:
            message = active_message
        if message is active_message:
            phase = phase or active_phase
    if (
        message is None
        or message.revision_state is None
        or message.revision_state.refresh_journal is None
    ):
        yield
        return
    before = _record_snapshot(scene, message)
    try:
        yield
    finally:
        _record_transaction_writes(
            scene, message, before, phase or "revision-selection"
        )


def restore_revision_baseline(scene, message) -> bool:
    """Restore the bounded evidence slice when navigation returns to its baseline."""
    state = message.revision_state
    journal = state.refresh_journal if state else None
    if not journal or message.revision_digest() != journal.get("baseline_digest"):
        return False
    touched = _restore_mutation_log(scene, message, journal)
    touched.update(journal.get("pending_fact_memory_ids", ()))
    get_agent("summarizer").queue_fact_memory(scene, touched)
    message.mark_revision_committed(tuple(journal.get("baseline_features", ())))
    message.set_revision_status(
        "clean", phase_receipts=dict(journal.get("baseline_receipts", {}))
    )
    return True


def _find_archive(scene, identity: str):
    parts = identity.split(":", 2)
    entries = (
        scene.archived_history
        if parts[0] == "base"
        else scene.layered_history[int(parts[1])]
    )
    wanted = parts[-1]
    return next((entry for entry in entries if entry.get("id") == wanted), None)


def _replace_archive(scene, identity: str, value, position=None) -> None:
    parts = identity.split(":", 2)
    entries = (
        scene.archived_history
        if parts[0] == "base"
        else scene.layered_history[int(parts[1])]
    )
    wanted = parts[-1]
    index = next(
        (index for index, entry in enumerate(entries) if entry.get("id") == wanted),
        None,
    )
    if index is not None and value is None:
        entries.pop(index)
    elif index is not None:
        entries[index] = value
    elif value is not None:
        position = position or {}
        next_id = position.get("next")
        previous_id = position.get("previous")
        insert_at = next(
            (
                item
                for item, entry in enumerate(entries)
                if next_id is not None and entry.get("id") == next_id
            ),
            None,
        )
        if insert_at is None and previous_id is not None:
            previous_at = next(
                (
                    item
                    for item, entry in enumerate(entries)
                    if entry.get("id") == previous_id
                ),
                None,
            )
            if previous_at is not None:
                insert_at = previous_at + 1
        if insert_at is None:
            insert_at = min(position.get("index", len(entries)), len(entries))
        entries.insert(insert_at, value)


def _restore_mutation_log(scene, message, journal) -> set[str]:
    """Undo this transaction's actual writes, newest first."""
    touched_facts = set()
    for mutation in reversed(journal.get("mutations", ())):
        if mutation.get("restored"):
            continue
        group = mutation["group"]
        identity = mutation["identity"]
        before = mutation.get("before")
        after = mutation.get("after")
        if group == "knowledge":
            if _dump(message.knowledge) == after:
                from talemate.knowledge.perspective_models import SourcePerspectives

                message.knowledge = (
                    SourcePerspectives.model_validate(before) if before else None
                )
        elif group == "perspectives":
            _restore_perspective_record(scene, identity, after, before)
        elif group == "facts":
            _restore_fact_record(scene, message, identity, after, before)
            touched_facts.add(identity)
        elif group == "edges":
            edges = {edge.id: edge for edge in scene.world_state.knowledge}
            if _dump(edges.get(identity)) != after:
                continue
            if before is None:
                edges.pop(identity, None)
            else:
                edges[identity] = KnowledgeEdge.model_validate(before)
            scene.world_state.knowledge = list(edges.values())
        elif group == "archives" and _find_archive(scene, identity) == after:
            _replace_archive(
                scene, identity, before, position=mutation.get("before_position")
            )
        mutation["restored"] = True
    return touched_facts


async def _rollback_transaction_writes(scene, message, journal=None) -> None:
    """Undo only writes still owned by an obsolete revision job."""
    state = message.revision_state
    journal = journal or (state.refresh_journal if state else None)
    if not journal:
        return
    touched_facts = _restore_mutation_log(scene, message, journal)
    pending_facts = set(journal.get("pending_fact_memory_ids", ())) | touched_facts
    journal["pending_fact_memory_ids"] = sorted(pending_facts)
    summarizer = get_agent("summarizer")
    if pending_facts:
        summarizer.queue_fact_memory(scene, pending_facts)
    await reconcile_revision_archive_vectors(scene, journal)
    if (
        pending_facts
        and summarizer.scene is scene
        and _memory_scene_owned(scene)
        and await summarizer.flush_fact_memory(scene)
    ):
        journal["pending_fact_memory_ids"] = []


def _remove_message_evidence_impl(scene, message, *, facts: bool) -> set[str]:
    removed = set()
    if facts:
        for fact in list(scene.world_state.facts.values()):
            matching = [
                source
                for source in fact.dialogue_sources
                if source.message_id == message.id
            ]
            if matching:
                fact.dialogue_sources = tuple(
                    source
                    for source in fact.dialogue_sources
                    if source.message_id != message.id
                )
                fact.restatements = max(
                    0, fact.restatements - sum(source.count for source in matching)
                )
                if fact.message_id == message.id:
                    if fact.dialogue_sources:
                        source = fact.dialogue_sources[0]
                        fact.message_id = source.message_id
                        fact.message_digest = source.message_digest
                    else:
                        fact.message_id = None
                        fact.message_digest = None
                if not fact.dialogue_sources and not (
                    fact.text_edited
                    or fact.link_edited
                    or fact.restatements
                    or fact.archive_sources
                    or fact.contributions
                    or any(
                        edge.target == fact.id and edge.source == "manual"
                        for edge in scene.world_state.knowledge
                    )
                ):
                    removed.add(fact.id)
                elif not fact.dialogue_sources and fact.archive_sources:
                    fact.source = "summary"
                    fact.archive_id = fact.archive_sources[0].archive_id
                continue
            if fact.message_id != message.id:
                continue
            independent = (
                fact.text_edited
                or fact.link_edited
                or fact.restatements > 0
                or bool(fact.archive_sources)
                or bool(fact.contributions)
                or any(
                    edge.target == fact.id and edge.source == "manual"
                    for edge in scene.world_state.knowledge
                )
            )
            if independent:
                fact.message_id = None
                fact.message_digest = None
                if fact.text_edited or fact.link_edited:
                    fact.source = "manual"
                elif fact.archive_sources:
                    fact.source = "summary"
                    fact.archive_id = fact.archive_sources[0].archive_id
            else:
                removed.add(fact.id)
        for identity in removed:
            scene.world_state.facts.pop(identity, None)
    old_edges = [
        edge
        for edge in scene.world_state.knowledge
        if edge.message_id == message.id and edge.source != "manual"
    ]
    for edge in scene.world_state.knowledge:
        if edge.message_id == message.id and edge.source == "manual":
            edge.message_id = None
    scene.world_state.knowledge = [
        edge
        for edge in scene.world_state.knowledge
        if edge.target not in removed
        and (edge.message_id != message.id or edge.source == "manual")
    ]
    for edge in old_edges:
        fact = scene.world_state.facts.get(edge.target)
        if fact is None or fact.known_by.get(edge.character) not in (
            "inferred",
            "told",
        ):
            continue
        if not any(
            other.character == edge.character and other.target == edge.target
            for other in scene.world_state.knowledge
        ):
            fact.known_by.pop(edge.character, None)
    return removed


def _remove_message_evidence(scene, message, *, facts: bool) -> set[str]:
    with capture_revision_mutations(scene, message=message):
        return _remove_message_evidence_impl(scene, message, facts=facts)


def _historical_context(scene, message) -> tuple[list[str], list[str] | None, int]:
    index = scene.history.index(message)
    recent = [
        str(entry)
        for entry in scene.history[max(0, index - 12) : index]
        if entry.typ in ("character", "narrator", "director") and not entry.hidden
    ]
    metadata = message.meta or {}
    historical_ts = metadata.get("ts")
    return (
        recent,
        message.present,
        int(scene.ts if historical_ts is None else historical_ts),
    )


def _affected_history_entries(scene, message):
    from talemate.history import HistoryEntry
    from talemate.knowledge.revision_browsing import affected_archive_ids

    affected = affected_archive_ids(scene, message)
    entries = []
    for layer, records in enumerate([scene.archived_history, *scene.layered_history]):
        for index, record in enumerate(records):
            if record.get("id") in affected:
                entries.append(
                    HistoryEntry(
                        **record,
                        index=index,
                        layer=layer,
                    )
                )
    return entries


def _archive_phase_inputs(scene, message, phase: str, *, journal=None) -> dict:
    """Resolve the live archive/source inputs while discounting our own writes."""
    archives = _record_snapshot(scene, message)["archives"]
    state = message.revision_state
    journal = (
        journal if journal is not None else (state.refresh_journal if state else None)
    )
    phase_writes = (
        (journal or {}).get("phase_writes", {}).get(phase, {}).get("archives", {})
    )
    for identity, written in phase_writes.items():
        if archives.get(identity) != written:
            continue
        original = (journal or {}).get("baseline", {}).get("archives", {}).get(identity)
        if original is None:
            archives.pop(identity, None)
        else:
            archives[identity] = original
    return {
        "history": [
            {
                "id": entry.id,
                "text": str(entry),
                "hidden": entry.hidden,
                "present": entry.present,
                "meta": entry.meta,
            }
            for entry in scene.history
        ],
        "archives": archives,
        "include_previous": get_agent("summarizer").resolve_config(
            "archive", "include_previous"
        ),
    }


async def _refresh_affected_archives(
    scene,
    message,
    identity: str,
    phase: str,
    operations: RevisionOperations,
):
    from talemate.history import regenerate_history_entry

    def still_current():
        return _current(scene, message, identity, operations) and (
            _phase_identity(scene, message, phase) == phase_identity
        )

    phase_identity = _phase_identity(scene, message, phase)
    for entry in _affected_history_entries(scene, message):
        refreshed = await regenerate_history_entry(
            scene, entry, still_current=still_current
        )
        if not still_current():
            raise GenerationCancelled("The scene changed during history refresh")
        if entry.layer == 0 and refreshed.facts_status == "failed":
            raise ValueError("Archived fact extraction was missing or malformed")


async def _invalidate_affected_archives(scene, message):
    entries = _affected_history_entries(scene, message)
    if not entries:
        return set()
    archive_ids = {entry.id for entry in entries if entry.id}
    with capture_revision_mutations(scene, message=message):
        removed = prune_summary_facts(scene.world_state, archive_ids)
    if removed:
        get_agent("summarizer").queue_fact_memory(scene, removed)
    # A disabled feature performs deterministic cleanup only: remove the stale
    # summaries and their dependent layers so ordinary archive building can
    # recreate them from the revised source later.
    affected_by_layer = {}
    for entry in entries:
        affected_by_layer.setdefault(entry.layer, set()).add(entry.index)
    records_by_layer = [scene.archived_history, *scene.layered_history]
    with capture_revision_mutations(scene, message=message):
        for layer, records in enumerate(records_by_layer):
            removed_indexes = affected_by_layer.get(layer, set())
            if removed_indexes:
                records[:] = [
                    record
                    for index, record in enumerate(records)
                    if index not in removed_indexes
                ]
            if layer + 1 >= len(records_by_layer):
                continue
            for record in records_by_layer[layer + 1]:
                if record.get("start") is None or record.get("end") is None:
                    continue
                record["start"] -= sum(
                    index < record["start"] for index in removed_indexes
                )
                record["end"] -= sum(
                    index <= record["end"] for index in removed_indexes
                )
    if archive_ids:
        if not _memory_scene_owned(scene):
            raise GenerationCancelled("The scene changed during archive cleanup")
        from talemate.agents.memory import memory_write_scene

        with memory_write_scene(scene):
            await get_agent("memory").delete({"ids": sorted(archive_ids)})
    return archive_ids


async def reconcile_revision_archive_vectors(scene, journal) -> bool:
    """Make base-history vectors match archive records restored from a journal."""
    pending = _archive_vector_repairs.setdefault(scene, set())
    if not journal and not pending:
        return True
    memory = get_agent("memory")
    identities = set(pending)
    identities.update(
        {
            mutation["identity"]
            for mutation in (journal or {}).get("mutations", ())
            if mutation["group"] == "archives"
        }
        or set((journal or {}).get("writes", {}).get("archives", {}))
    )
    pending.update(identities)
    for identity in sorted(identities):
        if not identity.startswith("base:"):
            pending.discard(identity)
            continue
        if not _memory_scene_owned(scene):
            return False
        record = _find_archive(scene, identity)
        if record is None:
            from talemate.agents.memory import memory_write_scene

            with memory_write_scene(scene):
                completed = await memory.delete({"ids": [identity.split(":", 1)[1]]})
        else:
            from talemate.knowledge.presence import presence_metadata

            from talemate.agents.memory import memory_write_scene

            with memory_write_scene(scene):
                completed = await memory.add(
                    record["text"],
                    uid=record["id"],
                    ts=record.get("ts") or 0,
                    typ="history",
                    **presence_metadata(record.get("present")),
                )
        if completed is False:
            return False
        pending.discard(identity)
    return True


async def _refresh(scene, message, identity: str, operations: RevisionOperations):
    from talemate.agents.summarize.perceptions import perception_results_current

    summarizer = get_agent("summarizer")
    begin_revision_transaction(scene, message)
    await reconcile_revision_archive_vectors(scene, None)
    message.set_revision_status("running")
    scene.emit_status()
    recent, present, ts = _historical_context(scene, message)
    rollback_journal = None
    try:
        if operations.perceptions:
            with revision_phase(scene, message, "perceptions"):
                summarizer._register_perception_sources(scene, [message])
        perception_identity = _phase_identity(scene, message, "perceptions", recent)
        if operations.perceptions and (
            message.revision_state.phase_receipts.get("refresh:perceptions")
            != perception_identity
            or not perception_results_current(scene, message)
        ):
            receipts = dict(message.revision_state.phase_receipts)
            # Missing source results revoke completion of the whole phase, even
            # when its inputs match an older successful run. A later repair
            # failure must remain retryable after source analysis succeeds.
            receipts.pop("refresh:perceptions", None)
            message.set_revision_status("running", phase_receipts=receipts)
            with revision_phase(scene, message, "perceptions"):
                await summarizer.ensure_perceptions(
                    scene,
                    still_current=lambda: _current(
                        scene, message, identity, operations
                    ),
                )
            if not _current(scene, message, identity, operations):
                raise GenerationCancelled(
                    "The selected version changed during analysis"
                )
            if _phase_identity(scene, message, "perceptions") != perception_identity:
                raise GenerationCancelled("Perception inputs changed during analysis")
            with revision_phase(scene, message, "perceptions"):
                await summarizer.repair_summary_views(scene)
            if not _current(scene, message, identity, operations):
                raise GenerationCancelled(
                    "The selected version changed during analysis"
                )
            if _phase_identity(scene, message, "perceptions") != perception_identity:
                raise GenerationCancelled("Perception inputs changed during analysis")
            if not perception_results_current(scene, message):
                raise GenerationCancelled(
                    "Selected-source perception results are not ready"
                )
            receipts = {
                **message.revision_state.phase_receipts,
                "refresh:perceptions": perception_identity,
            }
            message.set_revision_status("running", phase_receipts=receipts)

        extract_identity = _phase_identity(scene, message, "extract", recent)
        if (
            operations.extract_facts
            and message.revision_state.phase_receipts.get("refresh:extract")
            != extract_identity
        ):
            receipts = dict(message.revision_state.phase_receipts)
            if operations.learn_facts:
                # Extraction cleanup can revoke a prior learning phase's grants.
                # Never reuse that receipt after its output has been removed.
                receipts.pop("refresh:learn", None)
                message.set_revision_status("running", phase_receipts=receipts)
            with revision_phase(scene, message, "extract"):
                removed = _remove_message_evidence(scene, message, facts=True)
            if removed:
                summarizer.queue_fact_memory(scene, removed)

            def still_current():
                return _current(scene, message, identity, operations) and (
                    _phase_identity(scene, message, "extract") == extract_identity
                )

            if _affected_history_entries(scene, message):
                with revision_phase(scene, message, "extract"):
                    await _refresh_affected_archives(
                        scene, message, identity, "extract", operations
                    )
            else:
                _, parsed = await summarizer.summarize(
                    message.perception_text,
                    extra_context=recent,
                    return_facts=True,
                    skip_author_hooks=True,
                )
                if parsed is None:
                    raise ValueError(
                        "Fact extraction response was missing or malformed"
                    )
                if not _current(scene, message, identity, operations):
                    raise GenerationCancelled(
                        "The selected version changed during fact extraction"
                    )
                if _phase_identity(scene, message, "extract") != extract_identity:
                    raise GenerationCancelled("Fact inputs changed during extraction")
                with revision_phase(scene, message, "extract"):
                    await store_facts(
                        scene,
                        None,
                        present,
                        ts,
                        parsed,
                        summarizer.archive_fact_dedupe_distance,
                        notify=True,
                        message_id=message.id,
                        message_digest=content_digest(message.perception_text),
                        still_current=still_current,
                    )
                if not _current(scene, message, identity, operations):
                    raise GenerationCancelled(
                        "The selected version changed during fact storage"
                    )
                if _phase_identity(scene, message, "extract") != extract_identity:
                    raise GenerationCancelled("Fact inputs changed during extraction")
            receipts = {
                **message.revision_state.phase_receipts,
                "refresh:extract": extract_identity,
            }
            message.set_revision_status("running", phase_receipts=receipts)
            await refresh_topics(scene, still_current=still_current)

        learn_identity = _phase_identity(scene, message, "learn", recent)
        if (
            operations.learn_facts
            and message.revision_state.phase_receipts.get("refresh:learn")
            != learn_identity
        ):
            character = scene.get_character(message.character_name)
            if character is None:
                character = next(
                    (
                        candidate
                        for candidate in scene.character_data.values()
                        if candidate.name.lower() == message.character_name.lower()
                    ),
                    None,
                )
            if character is not None:

                def learning_current():
                    return _current(scene, message, identity, operations) and (
                        _phase_identity(scene, message, "learn") == learn_identity
                    )

                with revision_phase(scene, message, "learn"):
                    learned = await get_agent("conversation").record_learned_facts(
                        character,
                        str(message),
                        message=message,
                        present_override=present,
                        recent_lines_override=recent,
                        ts_override=ts,
                        establish_override=(
                            False if operations.extract_facts else None
                        ),
                        still_current=learning_current,
                        replace_message_evidence=True,
                        replace_facts=not operations.extract_facts,
                        require_validated_result=True,
                    )
                if learned is None:
                    raise ValueError("Fact learning response was missing or malformed")
            if not _current(scene, message, identity, operations):
                raise GenerationCancelled(
                    "The selected version changed during fact learning"
                )
            if _phase_identity(scene, message, "learn") != learn_identity:
                raise GenerationCancelled("Fact inputs changed during learning")
            receipts = {
                **message.revision_state.phase_receipts,
                "refresh:learn": learn_identity,
            }
            message.set_revision_status("running", phase_receipts=receipts)

        def transaction_current():
            return (
                _current(scene, message, identity, operations)
                and _receipts_current(scene, message, operations)
                and (
                    not operations.perceptions
                    or perception_results_current(scene, message)
                )
            )

        await summarizer.flush_fact_memory(scene)
        if not transaction_current():
            raise GenerationCancelled("The selected version changed during refresh")
        await refresh_topics(scene, still_current=transaction_current)
        if not transaction_current():
            raise GenerationCancelled("The selected version changed during indexing")
        await scene.attempt_auto_save()
        if not transaction_current():
            raise GenerationCancelled("The scene changed during refresh persistence")
        pending_state = message.revision_state
        rollback_journal = pending_state.refresh_journal
        message.mark_revision_committed(operations.names())
        committed_state = message.revision_state
        try:
            await scene.attempt_auto_save()
        except BaseException:
            if message.revision_state is committed_state:
                object.__setattr__(message, "revision_state", pending_state)
            raise
        if not (
            _current(scene, message, identity, operations)
            and (
                not operations.perceptions or perception_results_current(scene, message)
            )
            and _receipts_current(
                scene,
                message,
                operations,
                state=pending_state,
                journal=rollback_journal,
            )
        ):
            if message.revision_state is committed_state:
                object.__setattr__(message, "revision_state", pending_state)
            raise GenerationCancelled("The scene changed during refresh completion")
        if operations.perceptions:
            from talemate.knowledge.readiness import emit_perception_status

            emit_perception_status(scene, message, "ready")
        scene.emit_status()
        return revision_refresh_payload(scene, message)
    except BaseException:
        if _current(scene, message, identity, operations):
            message.set_revision_status("failed")
            if operations.perceptions:
                from talemate.knowledge.readiness import emit_perception_status

                emit_perception_status(scene, message, "failed")
            scene.emit_status()
            try:
                await scene.attempt_auto_save()
            except Exception:
                pass
        else:
            await _rollback_transaction_writes(scene, message, journal=rollback_journal)
            if (
                rollback_journal is not None
                and _scene_owned(scene, revision_operations(scene, message))
                and any(entry is message for entry in scene.history)
            ):
                try:
                    await scene.attempt_auto_save()
                except Exception:
                    pass
        raise


_jobs = WeakKeyDictionary()


async def refresh_revision(scene, message):
    """Run or join the one scene-local job for this canonical revision."""
    if not revision_requires_refresh(scene, message):
        return revision_refresh_payload(scene, message)
    operations = revision_operations(scene, message)
    if not operations.any:
        summarizer = get_agent("summarizer")
        identity = _identity(scene, message, operations)
        begin_revision_transaction(scene, message)
        rollback_journal = None
        try:
            with revision_phase(scene, message, "disabled"):
                removed = _remove_message_evidence(scene, message, facts=True)
                await _invalidate_affected_archives(scene, message)
            if removed:
                summarizer.queue_fact_memory(scene, removed)
            await summarizer.flush_fact_memory(scene)
            if not _current(scene, message, identity, operations):
                raise GenerationCancelled("The scene changed during revision cleanup")
            await refresh_topics(
                scene,
                still_current=lambda: _current(scene, message, identity, operations),
            )
            if not _current(scene, message, identity, operations):
                raise GenerationCancelled("The scene changed during revision indexing")
            await scene.attempt_auto_save()
            if not _current(scene, message, identity, operations):
                raise GenerationCancelled(
                    "The scene changed during revision persistence"
                )
            pending_state = message.revision_state
            rollback_journal = pending_state.refresh_journal
            message.mark_revision_committed()
            committed_state = message.revision_state
            try:
                await scene.attempt_auto_save()
            except BaseException:
                if message.revision_state is committed_state:
                    object.__setattr__(message, "revision_state", pending_state)
                raise
            if not _current(scene, message, identity, operations):
                if message.revision_state is committed_state:
                    object.__setattr__(message, "revision_state", pending_state)
                raise GenerationCancelled(
                    "The scene changed during revision completion"
                )
        except BaseException:
            await _rollback_transaction_writes(scene, message, journal=rollback_journal)
            if (
                rollback_journal is not None
                and _scene_owned(scene, revision_operations(scene, message))
                and any(entry is message for entry in scene.history)
            ):
                try:
                    await scene.attempt_auto_save()
                except Exception:
                    pass
            raise
        scene.emit_status()
        return revision_refresh_payload(scene, message)
    identity = _identity(scene, message, operations)
    jobs = _jobs.setdefault(scene, {})
    job = jobs.get(message.id)
    if job is None or job.done() or getattr(job, "revision_identity", None) != identity:
        job = asyncio.create_task(_refresh(scene, message, identity, operations))
        job.revision_identity = identity
        jobs[message.id] = job
    try:
        return await asyncio.shield(job)
    finally:
        if job.done() and jobs.get(message.id) is job:
            jobs.pop(message.id, None)


async def catch_up_revisions(scene) -> None:
    """Await every pending revision in history order before new generation."""
    # History listeners may push another message from inside this dispatch.
    if _catch_up_owners.get(scene) is asyncio.current_task():
        return
    lock = _catch_up_locks.setdefault(scene, asyncio.Lock())
    async with lock:
        _catch_up_owners[scene] = asyncio.current_task()
        try:
            for message in list(scene.history):
                if message.history_dispatch_pending:
                    if not any(entry is message for entry in scene.history):
                        continue
                    # Acceptance is durable before refresh; dispatch must not append
                    # or emit the player's line again after an interrupted refresh.
                    try:
                        await scene.dispatch_history([message])
                        message.history_dispatch_pending = False
                    finally:
                        await scene.attempt_auto_save()
                elif message.revision_state is not None and revision_requires_refresh(
                    scene, message
                ):
                    await refresh_revision(scene, message)
        finally:
            _catch_up_owners.pop(scene, None)
