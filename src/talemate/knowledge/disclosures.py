from bisect import bisect_right

from talemate.knowledge.changes import KnowledgeChange, emit_knowledge_changes
from talemate.knowledge.entry import _item_from_id, entry_text
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import add_disclosure, source_reference


def resolve_disclosure_target(scene, target):
    if not isinstance(target, str) or not target.strip():
        raise ValueError("Choose an existing source entry")
    item = _item_from_id(scene, target)
    offered = {
        (entry.id, entry.kind)
        for entry in scene.world_state_manager.knowledge_targets()
    }
    if item is None or (item.id, item.kind) not in offered:
        raise ValueError("The disclosure source is unresolved")
    provenance = ()
    if item.kind in ("static", "history"):
        for layer, entries in enumerate(
            [scene.archived_history, *scene.layered_history]
        ):
            if any(entry.get("id") == item.id for entry in entries):
                reference = source_reference(scene, "summary", item.id, layer=layer)
                provenance = (reference,) if reference else ()
                break
    return item.id, entry_text(scene, item), provenance


def grant_disclosure(scene, character, target, *, text=None, whole_entry=False):
    if not character_knowledge_enabled(scene):
        raise ValueError("Disclosures require perception mode")
    if character not in scene.character_data:
        raise ValueError(f"Unknown disclosure audience: {character}")
    if type(whole_entry) is not bool:
        raise ValueError("whole_entry must be a boolean")
    target, source_text, provenance = resolve_disclosure_target(scene, target)
    if whole_entry:
        if not isinstance(source_text, str) or not source_text.strip():
            raise ValueError("The disclosure source has no text")
        text = source_text
    elif not isinstance(text, str) or not text.strip():
        raise ValueError("A partial grant requires the information to disclose")
    disclosure = add_disclosure(
        scene, text, (character,), provenance=provenance, origin=target
    )
    emit_knowledge_changes(
        scene, [KnowledgeChange(character=character, target=disclosure.id)]
    )
    return disclosure


def disclosure_positions(scene):
    disclosures = scene.knowledge.disclosures if scene.knowledge else ()
    if not disclosures:
        return {}
    ordered = sorted(
        (message.id, index + 1) for index, message in enumerate(scene.history)
    )
    ids, positions = [], [0]
    for identity, position in ordered:
        ids.append(identity)
        positions.append(max(positions[-1], position))
    result = {}
    for disclosure in sorted(disclosures, key=lambda item: item.acquired.order):
        position = positions[bisect_right(ids, disclosure.message_id_boundary)]
        result.setdefault(position, []).append(disclosure)
    return result


def disclosure_text(disclosure):
    return f"Established knowledge (acquisition {disclosure.acquired.order}): {disclosure.text}"
