from typing import TYPE_CHECKING, Literal

import structlog

from talemate.exceptions import GenerationCancelled
from talemate.knowledge.formatting import format_message_view
from talemate.knowledge.summaries import (
    summary_spans,
    summary_coverage,
)
from talemate.knowledge.disclosures import disclosure_positions, disclosure_text
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
    source_reference,
)
from talemate.scene_message import (
    DirectorMessage,
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
    read: PerspectiveReadContext | None = None,
    entries: list[dict] | None = None,
    diagnostics=None,
) -> list[str]:
    if not character_knowledge_enabled(scene):
        raise ValueError("Character history projection requires perception mode")
    if character not in scene.character_data:
        raise ValueError(f"Unknown history perspective: {character}")
    read = read or PerspectiveReadContext(scene)
    parts = []

    def append(text, kind, identity, layer=0):
        parts.append(text)
        if entries is not None:
            entries.append({"text": text, "type": kind, "id": identity, "layer": layer})

    views = {}

    def select(reference):
        if reference not in views:
            view = select_character_view(scene, reference, character, read=read)
            views[reference] = view
            if diagnostics is not None and view.status != "ready":
                owners = read.sources.get(reference.key, [])
                text = owners[0].text if owners else ""
                kind = (
                    "layer"
                    if reference.kind == "summary" and reference.layer
                    else "archived"
                    if reference.kind == "summary"
                    else reference.kind
                )
                reason = (
                    "not_in_audience" if view.status == "unavailable" else view.status
                )
                if (
                    reference.kind == "intro"
                    and scene.intro_present is not None
                    and character not in scene.intro_present
                ):
                    reason = "absent"
                diagnostics.exclude(
                    kind,
                    reference.id,
                    text,
                    reason,
                    layer=reference.layer - 1 if kind == "layer" else reference.layer,
                )
        return views[reference]

    if diagnostics is not None:
        # The same view selector also explains summaries bypassed by a raw-history fit.
        for kind, identity, layer in read.sources:
            if kind not in ("summary", "intro"):
                continue
            reference = source_reference(scene, kind, identity, layer=layer, read=read)
            if reference is not None:
                select(reference)

    tokens = 0
    prefix = history_prefix(scene, before_message_id)
    spans = summary_spans(scene, read=read)
    coverage_cache = {}
    required = {}

    def is_required(item):
        if item.id not in required:
            source = (
                source_reference(scene, "message", item.id, read=read)
                if item.supports_perceptions and not (item.hidden and not show_hidden)
                else None
            )
            required[item.id] = bool(source) and select_character_view(
                scene, source, character, read=read
            ).status in ("ready", "pending", "failed")
        return required[item.id]

    disclosures = {
        position: [item for item in items if character in item.audience]
        for position, items in disclosure_positions(scene).items()
    }
    consumed = set()
    cursor = len(prefix) - 1
    while cursor >= -1:
        for disclosure in reversed(disclosures.get(cursor + 1, ())):
            if disclosure.id in consumed:
                continue
            if max_messages is not None and len(parts) >= max_messages:
                return list(reversed(parts))
            text = disclosure_text(disclosure)
            size = count_tokens(text)
            if budget is not None and tokens + size > budget:
                return list(reversed(parts))
            append(text, "disclosure", disclosure.id)
            tokens += size
            consumed.add(disclosure.id)
        if cursor < 0:
            break
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
            view = select(reference)
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
            disclosed = summary_coverage(
                view.source,
                character,
                read=read,
                cache=coverage_cache,
                kind="disclosure",
            )
            required_disclosures = {
                item.id
                for position, items in disclosures.items()
                if start <= position <= cursor
                for item in items
            }
            if not required_disclosures <= disclosed:
                continue
            size = count_tokens(view.text) if view.text else 0
            if budget is not None and tokens + size > budget:
                continue
            if view.text:
                append(
                    view.text,
                    "layer" if reference.layer else "archived",
                    reference.id,
                    reference.layer,
                )
                tokens += size
            consumed.update(disclosed)
            cursor = start - 1
            selected = True
            break
        if selected:
            continue
        cursor -= 1
        if message.hidden and not show_hidden:
            if diagnostics is not None:
                diagnostics.exclude("message", message.id, str(message), "hidden")
            continue
        if isinstance(message, DirectorMessage):
            if not keep_director or message.character_name != character:
                continue
            text = message.as_format(scene.conversation_format, mode=direction_mode)
        elif message.supports_perceptions:
            reference = source_reference(scene, "message", message.id, read=read)
            if reference is None:
                if diagnostics is not None:
                    diagnostics.exclude(
                        "message", message.id, str(message), "not_in_audience"
                    )
                log.debug(
                    "character_history.skip",
                    message_id=message.id,
                    viewer=character,
                    status="unavailable",
                )
                continue
            view = select(reference)
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
        append(text, "dialogue", message.id)
        tokens += size
    if cursor < 0 and (max_messages is None or len(parts) < max_messages):
        reference = source_reference(scene, "intro", "intro", read=read)
        if reference is not None:
            view = select(reference)
            if view.status == "ready":
                text = scene.get_intro(view.text, perspective=character)
                if text and (budget is None or tokens + count_tokens(text) <= budget):
                    append(text, "intro", "intro")
    return list(reversed(parts))
