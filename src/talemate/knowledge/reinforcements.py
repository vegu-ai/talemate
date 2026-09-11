"""Stored passage selection for reinforcement inserts and generated entries."""

from typing import TYPE_CHECKING
import weakref

import structlog

from talemate.exceptions import GenerationCancelled
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
    source_reference,
    source_deleted,
)
from talemate.knowledge.schema import EntryVisibility, ReinforcementEntry
from talemate.scene_message import ReinforcementMessage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.world_state import Reinforcement

log = structlog.get_logger(__name__)


def prepare_reinforcement_source(
    scene: "Scene", reinforcement: "Reinforcement", *, new_answer: bool = False
) -> ReinforcementMessage | None:
    if not character_knowledge_enabled(scene) or reinforcement.insert == "sequential":
        return reinforcement.source_for(scene)
    previous = reinforcement.perspective_source
    if (
        previous is not None
        and not new_answer
        and (
            previous.message == reinforcement.answer
            and previous.question == reinforcement.question
            and previous.character_name == reinforcement.character
        )
    ):
        return previous
    reference = source_reference(scene, "message", previous.id) if previous else None
    message = None
    if reinforcement.answer:
        message = ReinforcementMessage(message=reinforcement.answer)
        message.present = list(scene.active_characters) or None
        message.set_source(
            "world_state",
            "update_reinforcement",
            question=reinforcement.question,
            character=reinforcement.character,
        )
        message._knowledge_scene = weakref.ref(scene)
    reinforcement.perspective_source = message
    if previous is not None:
        source_deleted(scene, reference, message_id=previous.id)
    return message


def prepare_reinforcement_sources(scene: "Scene") -> list[ReinforcementMessage]:
    if not character_knowledge_enabled(scene):
        return []
    return [
        source
        for reinforcement in scene.world_state.reinforce
        if reinforcement.insert != "sequential"
        and (source := prepare_reinforcement_source(scene, reinforcement)) is not None
    ]


async def write_reinforcement_entry(
    scene: "Scene", reinforcement: "Reinforcement", source: ReinforcementMessage | None
) -> None:
    if not reinforcement.answer:
        if reinforcement.character:
            character = scene.get_character(reinforcement.character)
            if reinforcement.question in character.reinforcement_entries:
                await character.set_detail(reinforcement.question, None)
        else:
            entry = scene.world_state.manual_context.get(reinforcement.question)
            if entry is not None and entry.reinforcement is not None:
                await scene.world_state_manager.delete_context_db_entry(
                    reinforcement.question
                )
        return
    binding = ReinforcementEntry(source_id=source.id if source else None)
    if reinforcement.character:
        character = scene.get_character(reinforcement.character)
        await character.set_detail(
            reinforcement.question, reinforcement.answer, reinforcement=binding
        )
    else:
        existing = scene.world_state.manual_context.get(reinforcement.question)
        await scene.world_state_manager.save_world_entry(
            reinforcement.question,
            reinforcement.as_context_line,
            dict(existing.meta) if existing else {},
            reinforcement=binding,
        )


def _bound_entry(
    scene: "Scene", entry_id: str, owner: str | None = None
) -> tuple[ReinforcementEntry | None, EntryVisibility, str | None]:
    if owner is None:
        entry = scene.world_state.manual_context.get(entry_id)
        if entry is not None:
            return entry.reinforcement, entry.visibility, None
    for name, character in scene.character_data.items():
        if owner is not None and name != owner:
            continue
        prefix = f"{name}.detail."
        if entry_id.startswith(prefix):
            detail = entry_id[len(prefix) :]
            return (
                character.reinforcement_entries.get(detail),
                character.visibility.get(f"detail.{detail}", EntryVisibility()),
                name,
            )
    return None, EntryVisibility(), None


def entry_binding(
    scene: "Scene", entry_id: str, *, owner: str | None = None
) -> ReinforcementEntry | None:
    return _bound_entry(scene, entry_id, owner)[0]


def reinforcement_source_keys(scene: "Scene") -> set[tuple]:
    bindings = [
        entry.reinforcement for entry in scene.world_state.manual_context.values()
    ]
    bindings.extend(
        binding
        for character in scene.character_data.values()
        for binding in character.reinforcement_entries.values()
    )
    return {
        ("message", binding.source_id, 0)
        for binding in bindings
        if binding is not None and binding.source_id is not None
    }


def reinforcement_entry_context(
    scene: "Scene",
    entry_id: str,
    viewer: str,
    *,
    read: PerspectiveReadContext | None = None,
    owner: str | None = None,
) -> str | None:
    binding, visibility, owner = _bound_entry(scene, entry_id, owner)
    if binding is None:
        return None
    if not visibility.allows(viewer, owner):
        return ""
    read = read or PerspectiveReadContext(scene)
    sources = read.sources.get(("message", binding.source_id, 0), ())
    source = sources[0].owner if len(sources) == 1 else None
    if not isinstance(source, ReinforcementMessage):
        log.debug(
            "reinforcement_context.skip",
            entry_id=entry_id,
            viewer=viewer,
            status="missing",
        )
        return ""
    for reinforcement in scene.world_state.reinforce:
        if reinforcement.source_for(scene) is source:
            return reinforcement_context(scene, reinforcement, viewer, read=read)
    return source_context(scene, source, viewer, read=read)


def reinforcement_visibility(
    scene: "Scene", reinforcement: "Reinforcement"
) -> EntryVisibility:
    if reinforcement.character:
        character = scene.character_data.get(reinforcement.character)
        return (
            character.visibility.get(
                f"detail.{reinforcement.question}", EntryVisibility()
            )
            if character
            else EntryVisibility(mode="owner")
        )
    entry = scene.world_state.manual_context.get(reinforcement.question)
    return entry.visibility if entry else EntryVisibility()


def source_context(
    scene: "Scene",
    source: ReinforcementMessage,
    viewer: str,
    *,
    read: PerspectiveReadContext | None = None,
) -> str:
    if source.hidden:
        return ""
    reference = source_reference(scene, "message", source.id, read=read)
    if reference is None:
        raise GenerationCancelled(
            "Reinforcement perception has not run yet; send the next line to analyze it"
        )
    selected = select_character_view(scene, reference, viewer, read=read)
    if selected.status in ("pending", "failed"):
        raise GenerationCancelled(
            f"Reinforcement perception is {selected.status}; it runs again on the next turn"
        )
    return selected.text if selected.status == "ready" else ""


def reinforcement_context(
    scene: "Scene",
    reinforcement: "Reinforcement",
    viewer: str | None = None,
    *,
    read: PerspectiveReadContext | None = None,
) -> str:
    if viewer is None or not character_knowledge_enabled(scene):
        return reinforcement.as_context_line
    if not reinforcement_visibility(scene, reinforcement).allows(
        viewer, reinforcement.character
    ):
        return ""
    source = reinforcement.source_for(scene)
    if source is None:
        log.debug("reinforcement_context.skip", viewer=viewer, status="missing")
        return ""
    if (
        source.message != reinforcement.answer
        or source.question != reinforcement.question
    ):
        raise GenerationCancelled(
            "Reinforcement perception is stale; it runs again on the next turn"
        )
    return source_context(scene, source, viewer, read=read)
