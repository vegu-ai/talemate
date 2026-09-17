"""
Fact graph queries over ``world_state.facts`` and ``world_state.knowledge``.

No embedding search: name matching and the `supersedes` links only.
"""

from typing import TYPE_CHECKING

from talemate.knowledge.chronology import ranked_facts
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem
from talemate.knowledge.schema import Fact, KnownKind
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.knowledge.supported_facts import character_fact
from talemate.knowledge.names import aliases_for, mentions
from talemate.knowledge.revision_browsing import current_facts, fact_current

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


def _ordered(facts: list[Fact], scene: "Scene") -> list[Fact]:
    # ids are F<n>; the store's insertion order is the tiebreak, not the string
    order = {fact_id: i for i, fact_id in enumerate(scene.world_state.facts)}
    return sorted(
        facts, key=lambda f: (f.ts if f.ts is not None else -1, order.get(f.id, 0))
    )


def _acquisition_order(fact: Fact) -> int:
    return max(
        (item.acquired.order for item in fact.contributions),
        default=fact.acquired.order if fact.acquired is not None else 0,
    )


def _facts_about(
    scene: "Scene", entity: str, character: str | None = None, *, known=None
) -> list[Fact]:
    """Facts that mention the entity, oldest first, optionally as one character knows them."""
    aliases = aliases_for(scene, entity)
    facts = list(known) if known is not None else current_facts(scene)
    if known is None and character is not None:
        if character_knowledge_enabled(scene):
            facts = [fact for fact, _ in bucket(scene, character)]
        else:
            index = KnowledgeIndex.from_scene(scene)
            facts = [
                fact
                for fact in facts
                if mentions(fact, aliases) and index.in_bucket(character, _item(fact))
            ]
    facts = [fact for fact in facts if mentions(fact, aliases)]
    if character is not None and character_knowledge_enabled(scene):
        return sorted(facts, key=_acquisition_order)
    return _ordered(facts, scene)


def facts_about(
    scene: "Scene", entity: str, character: str | None = None
) -> list[Fact]:
    if not character_knowledge_enabled(scene) and not any(
        fact.supersedes for fact in current_facts(scene)
    ):
        # No supersession needs unrelated facts: preserve Standard's cheap
        # entity filter before checking knowledge membership.
        matching = _facts_about(scene, entity, character)
        return ranked_facts(scene, matching, character=character, superseders=matching)
    known = (
        [fact for fact, _ in bucket(scene, character)]
        if character is not None
        else current_facts(scene)
    )
    return ranked_facts(
        scene,
        _facts_about(scene, entity, character, known=known),
        character=character,
        superseders=known,
    )


def relationship_timeline(
    scene: "Scene", a: str, b: str, *, character: str | None = None
) -> list[Fact]:
    """Facts that mention both entities, oldest first."""
    aliases_a = aliases_for(scene, a)
    aliases_b = aliases_for(scene, b)
    return [
        f
        for f in _facts_about(scene, a, character=character)
        if mentions(f, aliases_a) and mentions(f, aliases_b)
    ]


def current_state(
    scene: "Scene", entity: str, *, character: str | None = None
) -> Fact | None:
    """The newest fact about the entity that no other fact supersedes."""
    facts = _facts_about(scene, entity, character=character)
    superseders = facts if character is not None else current_facts(scene)
    superseded = {f.supersedes for f in superseders if f.supersedes}
    candidates = [f for f in facts if f.id not in superseded]
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
    if current is not None and not fact_current(scene, current):
        current = None
    if (
        character is not None
        and character_knowledge_enabled(scene)
        and current is not None
    ):
        current = character_fact(scene, current, character)
    while current is not None and current.supersedes and len(chain) < hops:
        current = scene.world_state.facts.get(current.supersedes)
        if current is not None and not fact_current(scene, current):
            current = None
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


def perception_kind(view: Fact) -> KnownKind:
    if view.source == "offscreen":
        return "witnessed"
    return (
        "granted"
        if all(item.source.kind == "disclosure" for item in view.contributions)
        else "inferred"
    )


def standard_kind(
    index: KnowledgeIndex, character: str, fact: Fact
) -> KnownKind | None:
    """How the character knows the fact under the access rules; None when they do not."""
    if not index.in_bucket(character, _item(fact)):
        return None
    if fact.present and character in fact.present:
        return "witnessed"
    if fact.present is None and not index.granted(character, fact.id):
        return "witnessed"
    return fact.known_by.get(character, "granted")


def bucket(scene: "Scene", character: str) -> list[tuple[Fact, KnownKind]]:
    """Every fact the character knows, with how they know it."""
    if character_knowledge_enabled(scene):
        read = PerspectiveReadContext(scene)
        cache = {}
        known = []
        for fact in current_facts(scene):
            view = character_fact(scene, fact, character, read=read, cache=cache)
            if view is not None:
                known.append((view, perception_kind(view)))
        return sorted(
            known,
            key=lambda pair: _acquisition_order(pair[0]),
        )
    index = KnowledgeIndex.from_scene(scene)
    known: list[tuple[Fact, KnownKind]] = []
    for fact in _ordered(current_facts(scene), scene):
        kind = standard_kind(index, character, fact)
        if kind is not None:
            known.append((fact, kind))
    return known
