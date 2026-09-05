from typing import TYPE_CHECKING, Literal

import structlog

from talemate.exceptions import GenerationCancelled
from talemate.knowledge.formatting import format_message_view
from talemate.knowledge.summaries import summary_spans, summary_coverage
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
    source_reference,
)
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    SceneMessage,
)
from talemate.util import count_tokens

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


log = structlog.get_logger(__name__)


def history_prefix(
    scene: "Scene", before_message_id: int | None = None
) -> list[SceneMessage]:
    if before_message_id is None:
        return scene.history
    for index, message in enumerate(scene.history):
        if message.id == before_message_id:
            return scene.history[:index]
    raise GenerationCancelled(f"History boundary {before_message_id} was removed")


def project_character_history(
    scene: "Scene",
    character: str,
    *,
    budget: int | None = None,
    max_messages: int | None = None,
    before_message_id: int | None = None,
    keep_director: bool | str = False,
    show_hidden: bool = False,
    direction_mode: Literal["direction", "internal_monologue"] = "direction",
) -> list[str]:
    if not character_knowledge_enabled(scene):
        raise ValueError("Character history projection requires perception mode")
    if character not in scene.character_data:
        raise ValueError(f"Unknown history perspective: {character}")
    read = PerspectiveReadContext(scene)
    parts = []
    tokens = 0
    prefix = history_prefix(scene, before_message_id)
    spans = summary_spans(scene, read=read)
    coverage_cache = {}
    required = {}

    def is_required(item):
        if item.id not in required:
            source = (
                source_reference(scene, "message", item.id, read=read)
                if isinstance(item, (CharacterMessage, NarratorMessage))
                and not (item.hidden and not show_hidden)
                else None
            )
            required[item.id] = bool(source) and select_character_view(
                scene, source, character, read=read
            ).status in ("ready", "pending", "failed")
        return required[item.id]

    cursor = len(prefix) - 1
    while cursor >= 0:
        if max_messages is not None and len(parts) >= max_messages:
            break
        message = prefix[cursor]
        candidates = spans.get(cursor, ())
        selected = False
        for start, reference in candidates:
            if any(
                (item.hidden and not show_hidden)
                or (
                    isinstance(item, DirectorMessage)
                    and keep_director
                    and item.character_name == character
                )
                for item in prefix[start : cursor + 1]
            ):
                continue
            view = select_character_view(scene, reference, character, read=read)
            if view.status not in ("ready", "omitted"):
                log.debug(
                    "character_history.skip_summary",
                    source_id=reference.id,
                    viewer=character,
                    status=view.status,
                )
                continue
            covered = summary_coverage(
                view.source, character, read=read, cache=coverage_cache
            )
            if any(
                item.id not in covered and is_required(item)
                for item in prefix[start : cursor + 1]
            ):
                log.debug(
                    "character_history.skip_summary",
                    source_id=reference.id,
                    viewer=character,
                    status="incomplete_coverage",
                )
                continue
            size = count_tokens(view.text) if view.text else 0
            if budget is not None and tokens + size > budget:
                continue
            if view.text:
                parts.append(view.text)
                tokens += size
            cursor = start - 1
            selected = True
            break
        if selected:
            continue
        cursor -= 1
        if message.hidden and not show_hidden:
            continue
        if isinstance(message, DirectorMessage):
            if not keep_director or message.character_name != character:
                continue
            text = message.as_format(scene.conversation_format, mode=direction_mode)
        elif isinstance(message, (CharacterMessage, NarratorMessage)):
            reference = source_reference(scene, "message", message.id, read=read)
            if reference is None:
                log.debug(
                    "character_history.skip",
                    message_id=message.id,
                    viewer=character,
                    status="unavailable",
                )
                continue
            view = select_character_view(scene, reference, character, read=read)
            if view.status in ("pending", "failed"):
                raise GenerationCancelled(
                    f"Perception for passage {message.id} is {view.status}; "
                    "retry perception analysis before character generation"
                )
            if view.status != "ready":
                log.debug(
                    "character_history.skip",
                    message_id=message.id,
                    viewer=character,
                    status=view.status,
                )
                continue
            text = format_message_view(message, view.text, scene.conversation_format)
        else:
            continue
        if not text:
            continue
        size = count_tokens(text)
        if budget is not None and tokens + size > budget:
            break
        parts.append(text)
        tokens += size
    return list(reversed(parts))
