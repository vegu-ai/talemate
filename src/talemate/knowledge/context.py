from typing import TYPE_CHECKING, Literal

import structlog

from talemate.exceptions import GenerationCancelled
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
    for message in reversed(history_prefix(scene, before_message_id)):
        if max_messages is not None and len(parts) >= max_messages:
            break
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
            body = view.text
            if isinstance(message, CharacterMessage) and ":" in message.message:
                body = CharacterMessage.with_name_prefix(message.character_name, body)
            projected = message.model_copy(update={"message": body})
            if isinstance(message, CharacterMessage) and ":" not in message.message:
                text = SceneMessage.as_format(projected, scene.conversation_format)
            else:
                text = projected.as_format(scene.conversation_format)
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
