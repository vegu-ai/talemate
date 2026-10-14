import hashlib
import json

import structlog
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.reinforcements import entry_binding, reinforcement_entry_context

from talemate.knowledge.bucket import visibility_key
from talemate.knowledge.formatting import format_message_view
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
)
from talemate.knowledge.schema import EntryVisibility
from talemate.knowledge.summaries import source_visible


log = structlog.get_logger(__name__)


def audience_where(viewer):
    # $ne includes unmarked canonical rows when initial reconciliation fails.
    clauses = [{"knowledge_index": True if viewer is not None else {"$ne": True}}]
    if viewer is not None:
        clauses.extend(
            [
                {"pin_only": False},
                {
                    "$or": [
                        {"knowledge_common": True},
                        {"knowledge_audience": {"$contains": viewer}},
                    ]
                },
            ]
        )
    return clauses


def audience_documents(scene, *, groups=None, read=None):
    if not character_knowledge_enabled(scene):
        raise ValueError("Audience indexing requires perception mode")
    read = read or PerspectiveReadContext(scene)
    coverage = {}
    documents = {}

    def wanted(group):
        return groups is None or group in groups

    def add(group, key, text, meta, audience=(), common=False, label=None):
        if not wanted(group):
            return
        if not text or not (common or audience):
            return
        meta = {
            **meta,
            "knowledge_index": True,
            "knowledge_common": common,
            "knowledge_source": str(key),
            "knowledge_id": str(key if group == ("authored",) else group[1]),
            "pin_only": bool(meta.get("pin_only", False)),
        }
        identity = hashlib.sha256(
            json.dumps([key, text, meta], sort_keys=True).encode()
        ).hexdigest()
        identity = f"knowledge:{identity}"
        if identity in documents:
            audience = (
                *documents[identity]["meta"].get("knowledge_audience", ()),
                *audience,
            )
        if audience:
            meta["knowledge_audience"] = sorted(set(audience))
        documents[identity] = {
            "id": identity,
            "text": text,
            "meta": meta,
            "group": group,
        }
        if label is not None:
            documents[identity]["label"] = label

    def authored(key, text, meta, visibility, owner=None, label=None):
        if entry_binding(scene, key, owner=owner) is not None:
            for name in scene.character_data:
                if not visibility.allows(name, owner):
                    continue
                try:
                    projected = reinforcement_entry_context(
                        scene, key, name, read=read, owner=owner
                    )
                except GenerationCancelled as error:
                    log.debug(
                        "reinforcement_memory.skip",
                        entry_id=key,
                        viewer=name,
                        status=str(error),
                    )
                    continue
                add(
                    ("authored",),
                    key,
                    projected,
                    {**meta, "knowledge_reinforcement": True},
                    (name,),
                )
            return
        add(
            ("authored",),
            key,
            text,
            meta,
            audience=tuple(
                name for name in scene.character_data if visibility.allows(name, owner)
            )
            if visibility.mode != "everyone"
            else (),
            common=visibility.mode == "everyone",
            label=label,
        )

    for character in scene.character_data.values() if wanted(("authored",)) else ():
        for document in character.memory_documents():
            meta = document["meta"]
            key = visibility_key(meta)
            authored(
                document["id"],
                document["text"],
                meta,
                character.visibility.get(key, EntryVisibility()),
                character.name,
            )
    for entry in (
        scene.world_state.manual_context.values() if wanted(("authored",)) else ()
    ):
        meta = {
            key: value
            for key, value in entry.meta.items()
            if isinstance(value, (str, int, float, bool))
        }
        authored(
            entry.id,
            entry.text,
            meta,
            entry.visibility,
            label=f"World entry: {entry.id}",
        )

    for key, owners in read.sources.items():
        if len(owners) != 1:
            continue
        source = owners[0]
        if (
            source.kind == "summary"
            and source.layer == 0
            and source.owner.get("end") is None
        ):
            authored(
                str(source.id),
                source.text,
                {"typ": "history", "ts": source.owner.get("ts") or 0},
                EntryVisibility(),
                label="Static history",
            )
            continue
        if not wanted(key):
            continue
        knowledge = source.knowledge
        if knowledge is None:
            continue
        reference = source.reference()
        for view in knowledge.views:
            for name in view.audience:
                if name not in scene.character_data:
                    continue
                selected = select_character_view(scene, reference, name, read=read)
                if selected.status != "ready" or not source_visible(
                    selected.source, name, read=read, cache=coverage
                ):
                    continue
                text = selected.text
                if source.kind == "message":
                    text = format_message_view(source.owner, text, "chat")
                add(
                    key,
                    (*key, selected.source.view_id),
                    text,
                    {
                        "typ": "history",
                        "ts": knowledge.acquired.ts,
                        "knowledge_order": knowledge.acquired.order,
                        "knowledge_revision": selected.source.view_revision,
                        "knowledge_kind": source.kind,
                        "knowledge_layer": source.layer,
                    },
                    (name,),
                )
    for disclosure in read.disclosures.values():
        add(
            ("disclosure", disclosure.id, 0),
            ("disclosure", disclosure.id),
            disclosure.text,
            {
                "typ": "disclosure",
                "ts": disclosure.acquired.ts,
                "knowledge_order": disclosure.acquired.order,
                "knowledge_revision": disclosure.revision,
            },
            tuple(name for name in disclosure.audience if name in scene.character_data),
        )
    return documents


def invalidate_memory_audiences(scene):
    if scene is None or not character_knowledge_enabled(scene):
        return
    from talemate.instance import get_agent

    try:
        memory = get_agent("memory")
    except KeyError:
        return
    if memory is not None and memory.scene is scene:
        memory.invalidate_audience_index(scene)
