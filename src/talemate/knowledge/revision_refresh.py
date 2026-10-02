"""Revision refresh coordination shared by explicit keep and next-send catch-up."""

import hashlib
import json
from contextlib import contextmanager
from weakref import WeakKeyDictionary

import structlog
from pydantic import BaseModel, ConfigDict

from talemate.agents.summarize.perceptions import eligible_passage
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.presence import relevant_audiences
from talemate.knowledge.revision_browsing import affected_archive_ids
from talemate.knowledge.revision_scope import active_revision_phase
from talemate.scene_message import CharacterMessage, RevisionIndexRepair

_archive_vector_repairs = WeakKeyDictionary()
log = structlog.get_logger(__name__)


class RevisionOperations(BaseModel):
    model_config = ConfigDict(frozen=True)

    perceptions: bool = False

    @property
    def any(self) -> bool:
        return self.perceptions

    def names(self) -> tuple[str, ...]:
        return ("perceptions",) if self.perceptions else ()


def revision_operations(
    scene, message, *, skip_history_membership_check: bool = False
) -> RevisionOperations:
    """Resolve eligibility from the effective scene-aware configuration."""
    content = message.perception_text if message is not None else ""
    if isinstance(message, CharacterMessage) and ":" in content:
        content = content.split(":", 1)[1]
    if (
        message is None
        or not (
            skip_history_membership_check
            or any(entry is message for entry in scene.history)
        )
        or not message.supports_perceptions
        or message.hidden
        or not content.strip()
        or message.revision_state is None
    ):
        return RevisionOperations()
    if character_knowledge_enabled(scene):
        return RevisionOperations(
            perceptions=eligible_passage(message)
            and bool(relevant_audiences(scene, message))
        )
    return RevisionOperations()


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


def _phase_identity(scene, message, *, include_settings: bool = True) -> str:
    from talemate.agents.summarize.perceptions import (
        perception_context,
        perception_intention,
    )

    summarizer = get_agent("summarizer")
    context = perception_context(scene, message)
    context["passage"]["provenance"].pop("revision", None)
    values = {
        "message": message.id,
        "digest": message.revision_digest(),
        "eligibility": scene.knowledge_eligibility,
        "context": context,
        "intention": perception_intention(scene),
    }
    if include_settings:
        values["settings"] = {
            "enabled": summarizer.resolve_enabled("perceptions"),
            "repair": summarizer.resolve_config("perceptions", "automatic_repair"),
            "analyze_player": summarizer.resolve_config(
                "perceptions", "analyze_player"
            ),
        }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, default=str).encode()
    ).hexdigest()


def _receipts_current(scene, message, operations: RevisionOperations, *, state=None):
    state = state or message.revision_state
    return state is not None and (
        not operations.perceptions
        or state.phase_receipts.get("refresh:perceptions")
        == _phase_identity(scene, message)
    )


def revision_requires_refresh(scene, message, operations=None) -> bool:
    """Include missing revised-source results without backfilling pristine history."""
    return bool(
        message.revision_state and message.revision_state.pending_index_repair
    ) or _revision_work_required(scene, message, operations)


def _revision_work_required(scene, message, operations=None) -> bool:
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


def revision_refresh_payload(
    scene, message, *, skip_history_membership_check: bool = False
) -> dict:
    operations = revision_operations(
        scene,
        message,
        skip_history_membership_check=skip_history_membership_check,
    )
    pending_repair = bool(
        message.revision_state and message.revision_state.pending_index_repair
    )
    work_required = _revision_work_required(scene, message, operations)
    dirty = pending_repair or work_required
    repair_only = pending_repair and not work_required
    status = message.revision_state.status if message.revision_state else "clean"
    if repair_only:
        label = "Update knowledge"
        explanation = "This version is restored; its saved knowledge needs updating."
        running = "Updating knowledge…"
    elif operations.perceptions:
        label = "Analyze perceptions"
        explanation = "Perception analysis for this version has not run yet."
        running = "Analyzing perceptions…"
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
            "required": dirty and (operations.any or pending_repair),
            "status": status,
            "operations": ["index_repair"] if repair_only else list(operations.names()),
            "label": label,
            "explanation": explanation,
            "running_label": running,
            "deferred_hint": (
                "If you skip it, this runs when you send your next line."
                if dirty and (operations.any or pending_repair)
                else None
            ),
        }
    }


def _scene_owned(scene) -> bool:
    return get_agent("summarizer").scene is scene


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
        _scene_owned(scene)
        and (expected_operations is None or operations == expected_operations)
        and any(entry is message for entry in scene.history)
        and message.revision_state is not None
        and _identity(scene, message, operations) == identity
    )


def _dump(value):
    return value.model_dump(mode="json") if value is not None else None


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
        "archives": archives,
        "archive_positions": archive_positions,
    }


def _message_has_revision_work(scene, message) -> bool:
    journal = message.revision_state.refresh_journal or {}
    return bool(journal.get("mutations") or affected_archive_ids(scene, message))


def _journal(scene, message) -> dict:
    state = message.revision_state
    snapshot = _record_snapshot(scene, message)
    archive_ids = affected_archive_ids(scene, message)
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
            "archives": {
                key: value
                for key, value in snapshot["archives"].items()
                if value.get("id") in archive_ids
            },
        },
        "writes": {"perspectives": {}, "archives": {}},
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
    for group in ("perspectives", "archives"):
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
    token = active_revision_phase.set((scene, message, phase))
    try:
        yield
    finally:
        active_revision_phase.reset(token)


@contextmanager
def capture_revision_mutations(scene, *, message=None, phase: str | None = None):
    """Journal only mutations performed inside this synchronous write seam.

    The surrounding model await is intentionally outside the snapshot window:
    another task can write while generation is pending, and those writes must
    never be claimed by this revision transaction.
    """
    active = active_revision_phase.get()
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
    _restore_mutation_log(scene, message, journal)
    archives = {
        mutation["identity"]
        for mutation in journal.get("mutations", ())
        if mutation["group"] == "archives"
    } | set(journal.get("writes", {}).get("archives", {}))
    pending = state.pending_index_repair
    if pending:
        archives.update(pending.archive_ids)
    repair = RevisionIndexRepair(archive_ids=sorted(archives)) if archives else None
    message.mark_revision_committed(tuple(journal.get("baseline_features", ())))
    message.set_revision_status(
        "clean",
        phase_receipts=dict(journal.get("baseline_receipts", {})),
        pending_index_repair=repair,
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


def _restore_mutation_log(scene, message, journal) -> None:
    """Undo this transaction's actual writes, newest first."""
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
        elif group == "archives" and _find_archive(scene, identity) == after:
            _replace_archive(
                scene, identity, before, position=mutation.get("before_position")
            )
        mutation["restored"] = True


async def _rollback_transaction_writes(scene, message, journal=None) -> None:
    """Undo only writes still owned by an obsolete revision job."""
    state = message.revision_state
    journal = journal or (state.refresh_journal if state else None)
    if not journal:
        return
    _restore_mutation_log(scene, message, journal)
    await reconcile_revision_archive_vectors(scene, journal)


def _affected_history_entries(scene, message):
    from talemate.history import HistoryEntry

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


async def _invalidate_affected_archives(scene, message):
    entries = _affected_history_entries(scene, message)
    if not entries:
        return set()
    archive_ids = {entry.id for entry in entries if entry.id}
    # Drop stale summaries so ordinary archive building can recreate them.
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


async def reconcile_revision_archive_vectors(
    scene, journal, *, include_pending: bool = True
) -> bool:
    """Make base-history vectors match archive records restored from a journal."""
    pending = _archive_vector_repairs.setdefault(scene, set())
    if not journal and not pending:
        return True
    memory = get_agent("memory")
    identities = set(pending) if include_pending else set()
    identities.update(
        {
            mutation["identity"]
            for mutation in (journal or {}).get("mutations", ())
            if mutation["group"] == "archives"
        }
        or set((journal or {}).get("writes", {}).get("archives", {}))
    )
    if include_pending:
        pending.update(identities)
    complete = True
    for identity in sorted(identities):
        if not identity.startswith("base:"):
            pending.discard(identity)
            continue
        if not _memory_scene_owned(scene):
            return False
        record = _find_archive(scene, identity)
        if record is None or not record.get("text"):
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
            complete = False
            continue
        pending.discard(identity)
    return complete


async def _refresh_perceptions(scene, message, identity, operations):
    from talemate.agents.summarize.perceptions import (
        PerceptionInputsChanged,
        perception_results_current,
        warn_perception_regeneration,
    )

    summarizer = get_agent("summarizer")
    cancel_sequence = scene.cancel_sequence

    def operation_current():
        if scene.cancel_requested or scene.cancel_sequence != cancel_sequence:
            raise GenerationCancelled("Generation cancelled", by_user=True)
        return _current(scene, message, identity, operations)

    with revision_phase(scene, message, "perceptions"):
        summarizer.register_perception_sources(scene, [message])
        await summarizer.ensure_perceptions(
            scene,
            before_message_id=message.id,
            still_current=operation_current,
        )
    while True:
        perception_identity = _phase_identity(scene, message)
        input_identity = _phase_identity(scene, message, include_settings=False)

        def still_current():
            if not operation_current():
                return False
            if _phase_identity(scene, message) != perception_identity:
                raise PerceptionInputsChanged(
                    invalidate=_phase_identity(scene, message, include_settings=False)
                    != input_identity
                )
            return True

        if not still_current():
            raise GenerationCancelled("The selected version changed during analysis")
        if message.revision_state.phase_receipts.get(
            "refresh:perceptions"
        ) == perception_identity and perception_results_current(scene, message):
            return
        receipts = dict(message.revision_state.phase_receipts)
        # Missing source results revoke completion of the whole phase, even
        # when its inputs match an older successful run. A later repair
        # failure must remain retryable after source analysis succeeds.
        receipts.pop("refresh:perceptions", None)
        message.set_revision_status("running", phase_receipts=receipts)
        try:
            with revision_phase(scene, message, "perceptions"):
                await summarizer.ensure_perceptions(scene, still_current=still_current)
            if not still_current():
                raise GenerationCancelled(
                    "The selected version changed during analysis"
                )
            with revision_phase(scene, message, "perceptions"):
                await summarizer.repair_summary_views(scene)
            if not still_current():
                raise GenerationCancelled(
                    "The selected version changed during analysis"
                )
        except PerceptionInputsChanged as exc:
            with revision_phase(scene, message, "perceptions"):
                summarizer._perception_status(
                    scene, message, "pending", invalidate=exc.invalidate
                )
            if exc.invalidate:
                warn_perception_regeneration(message)
            continue
        if not perception_results_current(scene, message):
            raise GenerationCancelled(
                "Selected-source perception results are not ready"
            )
        receipts = {
            **message.revision_state.phase_receipts,
            "refresh:perceptions": perception_identity,
        }
        message.set_revision_status("running", phase_receipts=receipts)
        return


async def _refresh(scene, message, identity: str, operations: RevisionOperations):
    from talemate.agents.summarize.perceptions import perception_results_current

    begin_revision_transaction(scene, message)
    await reconcile_revision_archive_vectors(scene, None)
    message.set_revision_status("running")
    scene.emit_status()
    rollback_journal = None
    try:
        if operations.perceptions:
            await _refresh_perceptions(scene, message, identity, operations)

        def transaction_current():
            return (
                _current(scene, message, identity, operations)
                and _receipts_current(scene, message, operations)
                and (
                    not operations.perceptions
                    or perception_results_current(scene, message)
                )
            )

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
                and _scene_owned(scene)
                and any(entry is message for entry in scene.history)
            ):
                try:
                    await scene.attempt_auto_save()
                except Exception:
                    pass
        raise


async def _repair_restored_indexes(scene, message) -> bool:
    pending = message.revision_state.pending_index_repair
    if pending is None:
        return False
    operations = revision_operations(scene, message)
    identity = _identity(scene, message, operations)

    def still_current():
        return (
            _current(scene, message, identity, operations)
            and message.revision_state.pending_index_repair is pending
        )

    journal = {"writes": {"archives": dict.fromkeys(pending.archive_ids)}}
    try:
        complete = await reconcile_revision_archive_vectors(
            scene, journal, include_pending=False
        )
        if not still_current():
            raise GenerationCancelled(
                "The selection changed during restored index repair"
            )
    except GenerationCancelled:
        raise
    except Exception as exc:
        log.warning(
            "Restored knowledge update deferred", message_id=message.id, error=str(exc)
        )
        complete = False
    if not still_current():
        raise GenerationCancelled("The selection changed during restored index repair")
    if not complete:
        log.warning("Restored knowledge update remains pending", message_id=message.id)
        return False
    message.set_revision_status(
        message.revision_state.status, pending_index_repair=None
    )
    return True


async def _refresh_revision(scene, message, identity, operations):
    if not _current(scene, message, identity, operations):
        raise GenerationCancelled("The selected version changed before refresh")
    repaired = await _repair_restored_indexes(scene, message)
    if not _revision_work_required(scene, message, operations):
        if repaired:
            await scene.attempt_auto_save()
        return revision_refresh_payload(scene, message)
    if not operations.any:
        if not character_knowledge_enabled(scene) and not _message_has_revision_work(
            scene, message
        ):
            message.mark_revision_committed()
            await scene.attempt_auto_save()
            return revision_refresh_payload(scene, message)
        identity = _identity(scene, message, operations)
        begin_revision_transaction(scene, message)
        rollback_journal = None
        try:
            with revision_phase(scene, message, "disabled"):
                await _invalidate_affected_archives(scene, message)
            if not _current(scene, message, identity, operations):
                raise GenerationCancelled("The scene changed during revision cleanup")
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
                and _scene_owned(scene)
                and any(entry is message for entry in scene.history)
            ):
                try:
                    await scene.attempt_auto_save()
                except Exception:
                    pass
            raise
        scene.emit_status()
        return revision_refresh_payload(scene, message)
    return await _refresh(scene, message, identity, operations)


async def refresh_revision(scene, message):
    """Settle one revision."""
    if not revision_requires_refresh(scene, message):
        return revision_refresh_payload(scene, message)
    operations = revision_operations(scene, message)
    identity = _identity(scene, message, operations)
    return await _refresh_revision(scene, message, identity, operations)


def revisions_before_rebuild(scene) -> list:
    """
    The passages a full history rebuild settles. Character perspectives settle
    nothing, since a rebuild runs no perception analysis.
    """
    if character_knowledge_enabled(scene):
        return []
    return [
        message
        for message in scene.history
        if message.revision_state is not None
        and revision_requires_refresh(scene, message)
    ]


def settle_revisions_after_rebuild(scene, messages: list) -> None:
    for message in messages:
        if not any(entry is message for entry in scene.history):
            continue
        preserve_revision_index_repair(scene, message)
        message.mark_revision_committed()
        message.set_revision_status("clean", pending_index_repair=None)


def preserve_revision_index_repair(scene, message) -> None:
    pending = (
        message.revision_state.pending_index_repair if message.revision_state else None
    )
    if pending is None:
        return
    _archive_vector_repairs.setdefault(scene, set()).update(pending.archive_ids)


async def _repair_scene_indexes(scene) -> None:
    try:
        if _archive_vector_repairs.get(scene):
            await reconcile_revision_archive_vectors(scene, None)
    except GenerationCancelled:
        raise
    except Exception as exc:
        log.warning("Scene knowledge update deferred", error=str(exc))


async def catch_up_revisions(scene) -> None:
    """Settle every pending revision in history order."""
    await _repair_scene_indexes(scene)
    for message in list(scene.history):
        if message.revision_state is not None and revision_requires_refresh(
            scene, message
        ):
            await refresh_revision(scene, message)
