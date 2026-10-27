"""
Character knowledge reacting to the core: each handler follows one core event
(`talemate.scene_signals`, and `scene.before_generation`). The core sends the
events without knowing that knowledge listens.
"""

import talemate.emit.async_signals as async_signals
from talemate.context import active_scene
from talemate.events import BeforeGenerationEvent
from talemate.instance import get_agent
from talemate.knowledge.intro import sync_intro_knowledge
from talemate.knowledge.memory import invalidate_memory_audiences
from talemate.knowledge.perspective_models import SourceReference
from talemate.knowledge.perspectives import (
    message_content_changed,
    remove_perspective_audiences,
    reset_perspectives,
    shift_perspective_times,
    source_content_changed,
    source_deleted,
    validate_character_rename,
)
from talemate.knowledge.rename import rename_knowledge_references
from talemate.knowledge.revision_refresh import (
    preserve_revision_index_repair,
    revision_refresh_payload,
    revision_refreshes,
)
from talemate.knowledge.status import knowledge_sync
from talemate.knowledge.step import knowledge_step
from talemate.knowledge.timeline import shift_knowledge_edge_times
from talemate.scene_signals import (
    archive_entry_changed,
    archive_entry_regenerated,
    archive_entry_removed,
    character_added,
    character_changed,
    character_removed,
    character_renamed,
    character_renaming,
    intro_changed,
    message_changed,
    message_removed,
    message_versions,
    message_visibility_changed,
    reinforcement_source_released,
    scene_reset,
    scene_status,
    timeline_shifted,
)

__all__: list[str] = []


def _message_changed(message):
    message_content_changed(message)


def _message_visibility_changed(message):
    invalidate_memory_audiences(active_scene.get())


def _message_versions(scene, *, message):
    return revision_refresh_payload(scene, message)


def _message_reference(scene, message) -> SourceReference | None:
    if message is None or message.knowledge is None or scene.knowledge is None:
        return None
    return SourceReference(
        kind="message", id=message.id, revision=message.knowledge.revision
    )


def _message_removed(scene, *, message):
    preserve_revision_index_repair(scene, message)
    source_deleted(scene, _message_reference(scene, message), message_id=message.id)


def _reinforcement_source_released(scene, *, message):
    source_deleted(scene, _message_reference(scene, message))
    invalidate_memory_audiences(scene)


def _archive_entry_changed(scene, *, identity, layer):
    source_content_changed(scene, "summary", identity, layer=layer)


def _archive_entry_regenerated(scene, *, identity, layer, generation_options):
    get_agent("summarizer").queue_summary_entry(
        scene, identity, layer, generation_options=generation_options
    )


def _archive_entry_removed(scene, *, entry):
    if entry.get("knowledge") is None or scene.knowledge is None:
        return
    reference = SourceReference(
        kind="summary", id=entry["id"], revision=entry["knowledge"]["revision"]
    )
    source_deleted(scene, reference)


def _character_added(scene, *, name):
    invalidate_memory_audiences(scene)


def _character_changed(scene, *, character):
    invalidate_memory_audiences(scene)


def _character_removed(scene, *, name):
    invalidate_memory_audiences(scene)
    remove_perspective_audiences(scene, name)


def _character_renaming(scene, *, character, new_name):
    validate_character_rename(scene, character, new_name)


def _character_renamed(scene, *, old, new):
    rename_knowledge_references(scene, old, new)
    invalidate_memory_audiences(scene)


def _timeline_shifted(scene, *, shift):
    shift_knowledge_edge_times(scene, shift)
    shift_perspective_times(scene, shift)
    # an audience document's ts comes from an acquisition stamp or from the entry
    invalidate_memory_audiences(scene)


def _scene_reset(scene):
    reset_perspectives(scene)


def _intro_changed(scene):
    sync_intro_knowledge(scene)


def _scene_status(scene):
    sync = knowledge_sync(scene)
    return {
        "knowledge_sync": sync.model_dump() if sync is not None else None,
        "revision_refreshes": revision_refreshes(scene),
    }


async def _before_generation(event: BeforeGenerationEvent):
    await knowledge_step(event.scene)


message_changed.connect(_message_changed, weak=False)
archive_entry_changed.connect(_archive_entry_changed, weak=False)
archive_entry_regenerated.connect(_archive_entry_regenerated, weak=False)
archive_entry_removed.connect(_archive_entry_removed, weak=False)
message_visibility_changed.connect(_message_visibility_changed, weak=False)
message_versions.connect(_message_versions, weak=False)
message_removed.connect(_message_removed, weak=False)
reinforcement_source_released.connect(_reinforcement_source_released, weak=False)
character_added.connect(_character_added, weak=False)
character_changed.connect(_character_changed, weak=False)
character_removed.connect(_character_removed, weak=False)
character_renaming.connect(_character_renaming, weak=False)
character_renamed.connect(_character_renamed, weak=False)
timeline_shifted.connect(_timeline_shifted, weak=False)
scene_reset.connect(_scene_reset, weak=False)
intro_changed.connect(_intro_changed, weak=False)
scene_status.connect(_scene_status, weak=False)
async_signals.get("scene.before_generation").connect(_before_generation)
