"""
Fact graph queries over ``world_state.facts`` and ``world_state.knowledge``.

No embedding search: name matching and the `supersedes` links only.
"""

import re
from typing import TYPE_CHECKING

from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem
from talemate.knowledge.schema import Fact, KnownKind
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.knowledge.supported_facts import character_fact

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "facts_about",
    "relationship_timeline",
    "current_state",
    "bucket",
    "superseded_chain",
    "aliases_for",
    "KnownKind",
]


def aliases_for(scene: "Scene", entity: str) -> set[str]:
    """The entity's name and every alias `character_name_mappings` groups with it, lower-cased."""
    names = {entity.strip().lower()}
    mappings = scene.world_state.character_name_mappings
    for name, aliases in mappings.items():
        group = {name.lower(), *(a.lower() for a in aliases)}
        if entity.lower() in group:
            names |= group
    return {n for n in names if n}


_aliases = aliases_for


def _mentions(fact: Fact, aliases: set[str]) -> bool:
    subjects = {s.lower() for s in fact.subjects}
    if subjects & aliases:
        return True
    text = fact.text.lower()
    return any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in aliases)


def _ordered(facts: list[Fact], scene: "Scene") -> list[Fact]:
    # ids are F<n>; the store's insertion order is the tiebreak, not the string
    order = {fact_id: i for i, fact_id in enumerate(scene.world_state.facts)}
    return sorted(
        facts, key=lambda f: (f.ts if f.ts is not None else -1, order.get(f.id, 0))
    )


def facts_about(
    scene: "Scene", entity: str, character: str | None = None
) -> list[Fact]:
    """Facts that mention the entity, oldest first, optionally as one character knows them."""
    aliases = _aliases(scene, entity)
    facts = list(scene.world_state.facts.values())
    if character is not None:
        if character_knowledge_enabled(scene):
            read = PerspectiveReadContext(scene)
            cache = {}
            facts = [
                view
                for fact in facts
                if (
                    view := character_fact(
                        scene, fact, character, read=read, cache=cache
                    )
                )
                is not None
            ]
        else:
            index = KnowledgeIndex.from_scene(scene)
            facts = [
                f
                for f in facts
                if _mentions(f, aliases) and index.in_bucket(character, _item(f))
            ]
    facts = [fact for fact in facts if _mentions(fact, aliases)]
    if character is not None and character_knowledge_enabled(scene):
        return sorted(
            facts,
            key=lambda fact: max(item.acquired.order for item in fact.contributions),
        )
    return _ordered(facts, scene)


def relationship_timeline(
    scene: "Scene", a: str, b: str, *, character: str | None = None
) -> list[Fact]:
    """Facts that mention both entities, oldest first."""
    aliases_a = _aliases(scene, a)
    aliases_b = _aliases(scene, b)
    return [
        f
        for f in facts_about(scene, a, character=character)
        if _mentions(f, aliases_a) and _mentions(f, aliases_b)
    ]


def current_state(
    scene: "Scene", entity: str, *, character: str | None = None
) -> Fact | None:
    """The newest fact about the entity that no other fact supersedes."""
    facts = facts_about(scene, entity, character=character)
    superseders = facts if character is not None else scene.world_state.facts.values()
    superseded = {f.supersedes for f in superseders if f.supersedes}
    candidates = [
        f
        for f in facts
        if f.id not in superseded
        and (character is None or not character_knowledge_enabled(scene) or not f.false)
    ]
    return candidates[-1] if candidates else None


def superseded_chain(
    scene: "Scene", fact_id: str, hops: int = 2, *, character: str | None = None
) -> list[Fact]:
    """Walk `supersedes` backwards from a fact, at most `hops` steps."""
    if character is not None and not character_knowledge_enabled(scene):
        raise ValueError("Scoped superseded chains require perception mode")
    seen = {fact_id}
    chain: list[Fact] = []
    current = scene.world_state.facts.get(fact_id)
    if (
        character is not None
        and character_knowledge_enabled(scene)
        and current is not None
    ):
        current = character_fact(scene, current, character)
    while current is not None and current.supersedes and len(chain) < hops:
        current = scene.world_state.facts.get(current.supersedes)
        if (
            current is not None
            and character is not None
            and character_knowledge_enabled(scene)
        ):
            current = character_fact(scene, current, character)
        if current is None or current.id in seen:
            break
        seen.add(current.id)
        chain.append(current)
    return chain


def _item(fact: Fact) -> KnowledgeItem:
    return KnowledgeItem(id=fact.id, kind="fact", present=fact.present)


def bucket(scene: "Scene", character: str) -> list[tuple[Fact, KnownKind]]:
    """Every fact the character knows, with how they know it."""
    if character_knowledge_enabled(scene):
        read = PerspectiveReadContext(scene)
        cache = {}
        known = []
        for fact in scene.world_state.facts.values():
            view = character_fact(scene, fact, character, read=read, cache=cache)
            if view is not None:
                kind = (
                    "granted"
                    if all(
                        item.source.kind == "disclosure" for item in view.contributions
                    )
                    else "inferred"
                )
                known.append((view, kind))
        return sorted(
            known,
            key=lambda pair: max(item.acquired.order for item in pair[0].contributions),
        )
    index = KnowledgeIndex.from_scene(scene)
    known: list[tuple[Fact, KnownKind]] = []
    for fact in _ordered(list(scene.world_state.facts.values()), scene):
        if not index.in_bucket(character, _item(fact)):
            continue
        if fact.present and character in fact.present:
            kind: KnownKind = "witnessed"
        elif fact.present is None and not index.granted(character, fact.id):
            kind = "witnessed"
        else:
            kind = fact.known_by.get(character, "granted")
        known.append((fact, kind))
    return known
