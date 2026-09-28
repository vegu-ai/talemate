import json
import re
from collections import Counter
from typing import TYPE_CHECKING

import structlog

from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.formatting import format_message_view
from talemate.knowledge.perspective_models import (
    PerspectiveOutput,
    SourceReference,
    content_digest,
)
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    can_cite_view,
    select_character_view,
    source_reference,
)
from talemate.knowledge.snapshot_models import SnapshotPerspectives
from talemate.util import count_tokens

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.world_state import WorldState

log = structlog.get_logger(__name__)


def snapshot_digest(name: str, snapshot: str | None, emotion: str | None = None) -> str:
    return content_digest(json.dumps([name, snapshot, emotion], ensure_ascii=False))


def snapshot_audience_context(
    scene: "Scene",
    budget: int,
    focus_text: str = "",
    *,
    referenced_names: list[str] | None = None,
) -> dict:
    read = PerspectiveReadContext(scene)
    candidates = []
    for key, matches in read.sources.items():
        if len(matches) == 1 and matches[0].knowledge:
            reference = source_reference(scene, key[0], key[1], layer=key[2], read=read)
            if reference:
                candidates.append((matches[0].knowledge.acquired.order, reference))
    for item in read.disclosures.values():
        reference = source_reference(scene, "disclosure", item.id, read=read)
        if reference:
            candidates.append((item.acquired.order, reference))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    names = [
        name
        for name in scene.character_data
        if name in scene.active_characters
        or (
            name in referenced_names
            if referenced_names is not None
            else re.search(
                rf"(?<!\w){re.escape(name)}(?!\w)", focus_text, re.IGNORECASE
            )
        )
    ]
    per_character = max(1, budget // max(1, len(names)))
    cast = []
    for name in names:
        known = []
        used = 0
        for _, reference in candidates:
            view = select_character_view(scene, reference, name, read=read)
            if view.status != "ready" or not can_cite_view(
                scene, view.source, name, read=read
            ):
                continue
            text = view.text
            if reference.kind == "message":
                text = format_message_view(
                    read.sources[reference.key][0].owner, text, "chat"
                )
            item = {"source": view.source.model_dump(), "text": text}
            size = count_tokens(json.dumps(item, indent=2))
            if used + size > per_character:
                continue
            known.append(item)
            used += size
            if len(known) >= 20:
                break
        cast.append({"name": name, "established_knowledge": list(reversed(known))})
    return {"cast": cast}


def prepare_snapshot_views(
    scene: "Scene", raw, digest: str, context: dict | None
) -> SnapshotPerspectives | None:
    if raw is None or context is None:
        return None
    if not isinstance(raw, (list, tuple)):
        log.warning("snapshot.invalid_views", error="Expected a list of views")
        return None
    cast = {item["name"]: item for item in context["cast"]}
    assignments = {}
    counts = Counter()
    for candidate in raw:
        audience = candidate.get("audience") if isinstance(candidate, dict) else None
        if isinstance(audience, (list, tuple)):
            counts.update(name for name in audience if isinstance(name, str))
        try:
            view = PerspectiveOutput.model_validate(candidate)
            if not set(view.audience) <= cast.keys() & scene.character_data.keys():
                raise ValueError("Unknown or unrequested snapshot audience")
            if view.sources or view.passage_provenance or view.id is not None:
                raise ValueError("Snapshot evidence is assigned by the host")
            for name in view.audience:
                assignments[name] = view
        except (ValueError, TypeError) as exc:
            log.warning("snapshot.invalid_view", error=str(exc))
    read = PerspectiveReadContext(scene)
    views = []
    for name in cast:
        if name not in scene.character_data:
            continue
        view = assignments.get(name)
        if counts[name] > 1:
            log.warning("snapshot.duplicate_audience", audience=name)
        if view is None or counts[name] != 1:
            views.append(PerspectiveOutput(audience=(name,), status="omitted"))
            continue
        sources = tuple(
            SourceReference.model_validate(item["source"])
            for item in cast[name]["established_knowledge"]
        )
        if view.status == "ready" and (
            not sources
            or not all(can_cite_view(scene, ref, name, read=read) for ref in sources)
        ):
            views.append(PerspectiveOutput(audience=(name,), status="pending"))
        else:
            views.append(
                view.model_copy(update={"audience": (name,), "sources": sources})
            )
    return SnapshotPerspectives(content_digest=digest, views=tuple(views))


def prepare_snapshot_patch(
    scene: "Scene", prior: dict, patch: dict, context: dict | None
) -> dict:
    result = {}
    for name, payload in patch.items():
        if not isinstance(payload, dict):
            result[name] = payload
            continue
        value = dict(payload)
        value.pop("perspectives", None)
        raw_views = value.pop("views", None)
        if "views" in payload or "snapshot" in payload or "emotion" in payload:
            previous = prior.get(name)
            snapshot = value.get("snapshot", previous.snapshot if previous else None)
            emotion = value.get("emotion", getattr(previous, "emotion", None))
            value["perspectives"] = prepare_snapshot_views(
                scene, raw_views, snapshot_digest(name, snapshot, emotion), context
            )
        result[name] = value
    return result


def snapshot_view_text(
    scene: "Scene",
    perspectives: SnapshotPerspectives | None,
    digest: str,
    viewer: str,
    read: PerspectiveReadContext,
) -> str | None:
    if perspectives is None or perspectives.content_digest != digest:
        return None
    for view in perspectives.views:
        if viewer not in view.audience:
            continue
        if view.status != "ready" or not view.sources:
            return None
        if not all(
            can_cite_view(scene, ref, viewer, read=read) for ref in view.sources
        ):
            return None
        return view.text
    return None


def snapshot_for(
    scene: "Scene",
    viewer: str | None,
    *,
    world_state: "WorldState | None" = None,
    read: PerspectiveReadContext | None = None,
) -> dict:
    ws = world_state if world_state is not None else scene.world_state
    projected = viewer is not None and character_knowledge_enabled(scene)
    if projected and viewer not in scene.character_data:
        raise ValueError(f"Unknown snapshot viewer: {viewer}")
    read = (read or PerspectiveReadContext(scene)) if projected else None
    location = ws.location
    if projected and location:
        location = snapshot_view_text(
            scene,
            ws.location_perspectives,
            snapshot_digest("location", ws.location),
            viewer,
            read,
        )
    result = {"location": location, "characters": [], "items": [], "places": []}
    for bucket in ("characters", "items", "places"):
        for name, item in getattr(ws, bucket).items():
            if not item.snapshot:
                continue
            if projected:
                text = snapshot_view_text(
                    scene,
                    item.perspectives,
                    snapshot_digest(
                        name, item.snapshot, getattr(item, "emotion", None)
                    ),
                    viewer,
                    read,
                )
            else:
                emotion = getattr(item, "emotion", None)
                label = f"{name} ({emotion})" if emotion else name
                text = f"{label} — {item.snapshot}"
            if text:
                result[bucket].append(text)
    return result


def snapshot_views_example(context: dict) -> list[dict]:
    return [
        {
            "audience": [item["name"]],
            "status": "ready" if item["established_knowledge"] else "omitted",
            "text": "Complete replacement containing only information this audience knows about the example entity."
            if item["established_knowledge"]
            else None,
        }
        for item in context["cast"]
    ]


def snapshot_example(context: dict, durable: bool) -> dict:
    names = [item["name"] for item in context["cast"]]
    replacements = snapshot_views_example(context)
    result = {
        "characters": {
            "Observed character (placeholder)": {
                "snapshot": "Complete reader description of this character, including public and private details.",
                "emotion": "The character's current mood.",
                "mentions": ["verbatim name from CURRENT FOCUS"],
                "views": replacements,
            }
        },
        "items": {"Departed item": None} if durable else {},
        "location": "Complete reader description of the current location.",
        "location_views": [
            {"audience": [name], "status": "omitted", "text": None} for name in names
        ],
    }
    if not durable:
        result["places"] = {}
    return result
