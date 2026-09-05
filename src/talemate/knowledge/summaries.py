from dataclasses import dataclass
from typing import Literal

from talemate.knowledge.formatting import format_message_view
from talemate.knowledge.perspectives import (
    MAX_DEPENDENCY_DEPTH,
    PerspectiveReadContext,
    select_character_view,
    source_reference,
)
from talemate.knowledge.perspective_models import SourceReference
from talemate.scene_message import CharacterMessage, NarratorMessage


@dataclass(frozen=True)
class SummaryInput:
    status: Literal["ready", "omitted", "pending"]
    texts: tuple[str, ...] = ()
    sources: tuple[SourceReference, ...] = ()


def summary_entry(scene, identity, layer):
    entries = summary_layer(scene, layer)
    return next((entry for entry in entries if entry["id"] == identity), None)


def summary_layer(scene, layer):
    if layer == 0:
        return scene.archived_history
    if layer > len(scene.layered_history):
        return []
    return scene.layered_history[layer - 1]


def summary_sources(scene, entry, layer):
    start, end = entry.get("start"), entry.get("end")
    if start is None or end is None or start < 0 or end < start:
        return None
    entries = scene.history if layer == 0 else summary_layer(scene, layer - 1)
    if end >= len(entries):
        return None
    selected = entries[start : end + 1]
    if layer == 0:
        return [
            item
            for item in selected
            if isinstance(item, (CharacterMessage, NarratorMessage)) and not item.hidden
        ]
    return selected


def summary_inputs(scene, entry, layer, *, read=None):
    read = read or PerspectiveReadContext(scene)
    entries = summary_sources(scene, entry, layer)
    if not entries:
        return {}
    references = []
    names = set()
    kind = "message" if layer == 0 else "summary"
    source_layer = max(0, layer - 1)
    for item in entries:
        identity = item.id if layer == 0 else item["id"]
        reference = source_reference(
            scene,
            kind,
            identity,
            layer=source_layer,
            read=read,
        )
        references.append(reference)
        owner = read.sources.get((kind, identity, source_layer), [])
        if owner and owner[0].knowledge:
            names.update(
                name for view in owner[0].knowledge.views for name in view.audience
            )
        elif layer > 0:
            names.update(summary_inputs(scene, item, layer - 1, read=read))
    stored = entry.get("knowledge")
    if stored:
        names.update(name for view in stored["views"] for name in view["audience"])
    results = {}
    for name in sorted(names):
        texts, sources = [], []
        complete = True
        for item, reference in zip(entries, references, strict=True):
            if reference is None:
                complete = False
                continue
            view = select_character_view(scene, reference, name, read=read)
            if view.status == "unavailable":
                sources.append(reference)
                continue
            if view.status not in ("ready", "omitted"):
                complete = False
                continue
            sources.append(view.source)
            if view.status == "ready":
                texts.append(
                    format_message_view(item, view.text, "chat")
                    if layer == 0
                    else view.text
                )
        results[name] = SummaryInput(
            "ready" if complete and texts else "omitted" if complete else "pending",
            tuple(texts),
            tuple(sources),
        )
    return results


def summary_spans(scene, *, read=None):
    """Map current message ends to candidates using persisted source identities."""
    read = read or PerspectiveReadContext(scene)
    positions = {
        ("message", message.id, 0): (index, index)
        for index, message in enumerate(scene.history)
    }
    result = {}
    for layer, entries in enumerate([scene.archived_history, *scene.layered_history]):
        for entry in entries:
            dependencies = {
                SourceReference.model_validate(dependency).key
                for view in (entry.get("knowledge") or {}).get("views", [])
                for dependency in view["sources"]
                if dependency["kind"] == ("message" if layer == 0 else "summary")
                and dependency.get("layer", 0) == max(0, layer - 1)
            }
            if not dependencies or any(key not in positions for key in dependencies):
                continue
            children = [positions[key] for key in dependencies]
            span = (
                min(child[0] for child in children),
                max(child[1] for child in children),
            )
            positions["summary", entry["id"], layer] = span
            reference = source_reference(
                scene, "summary", entry["id"], layer=layer, read=read
            )
            if reference:
                result.setdefault(span[1], []).insert(0, (span[0], reference))
    return result


def summary_coverage(
    reference, character, *, read, cache, remaining=MAX_DEPENDENCY_DEPTH
):
    """Collect cited passage IDs for one audience, including through summary layers."""
    if remaining < 0:
        return frozenset()
    key = (reference, character, remaining)
    if key in cache:
        return cache[key]
    if reference.kind == "message":
        return frozenset((reference.id,))
    owners = read.sources.get(reference.key, ())
    if len(owners) != 1 or owners[0].knowledge is None:
        return frozenset()
    covered = set()
    for view in owners[0].knowledge.views:
        if character not in view.audience or (
            reference.view_id is not None and view.id != reference.view_id
        ):
            continue
        for dependency in view.sources:
            covered.update(
                summary_coverage(
                    dependency,
                    character,
                    read=read,
                    cache=cache,
                    remaining=remaining - 1,
                )
            )
    cache[key] = frozenset(covered)
    return cache[key]
