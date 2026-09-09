from collections.abc import Iterable

import structlog

from talemate.instance import get_agent
from talemate.knowledge.chronology import ranked_facts
from talemate.knowledge.formatting import format_message_view
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import SourceReference
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
)
from talemate.knowledge.schema import Fact, FactContribution, ParsedFact
from talemate.knowledge.summaries import summary_coverage


log = structlog.get_logger(__name__)


def source_visible(source, character, *, read, cache):
    """Hidden passages cannot remain available through their derived facts."""
    ids = summary_coverage(source, character, read=read, cache=cache)
    return all(
        not owner.owner.hidden
        for identity in ids
        for owner in read.sources.get(("message", identity, 0), ())
    )


def supported_contributions(scene, fact, character=None, *, read=None, cache=None):
    read = read or PerspectiveReadContext(scene)
    result = []
    coverage = {} if cache is None else cache
    for contribution in fact.contributions:
        names = (character,) if character is not None else contribution.audience
        audience = tuple(
            name
            for name in names
            if name in contribution.audience
            and name in scene.character_data
            and source_visible(contribution.source, name, read=read, cache=coverage)
            and select_character_view(
                scene, contribution.source, name, read=read
            ).status
            == "ready"
        )
        if audience:
            result.append(contribution.model_copy(update={"audience": audience}))
    return tuple(result)


def aggregate_fact(fact, contributions):
    ordered = sorted(contributions, key=lambda item: item.acquired.order)
    first, last = ordered[0], ordered[-1]
    return fact.model_copy(
        update={
            "text": first.text,
            "subjects": list(first.subjects),
            "ts": first.acquired.ts,
            "last_seen_ts": last.acquired.ts,
            "archive_id": next(
                (item.source.id for item in ordered if item.source.kind == "summary"),
                None,
            ),
            "present": sorted({name for item in ordered for name in item.audience}),
            "known_by": {},
            "supersedes": last.supersedes,
            "restatements": len(ordered) - 1,
            "contributions": tuple(ordered),
        }
    )


def character_fact(scene, fact, character, *, read=None, cache=None):
    if character not in scene.character_data:
        raise ValueError(f"Unknown fact perspective: {character}")
    contributions = supported_contributions(
        scene, fact, character, read=read, cache=cache
    )
    if not contributions:
        return None
    # Author corrections are not evidence the character received.
    return aggregate_fact(fact, contributions).model_copy(update={"false": False})


def previous_audience_facts(scene, audience, limit=30):
    read = PerspectiveReadContext(scene)
    result = []
    cache = {}
    for fact in scene.world_state.facts.values():
        views = [
            character_fact(scene, fact, name, read=read, cache=cache)
            for name in audience
        ]
        if views and all(view is not None for view in views):
            if len({(view.text, view.ts) for view in views}) == 1:
                seen = [view.last_seen_ts for view in views]
                result.append(
                    views[0].model_copy(
                        update={
                            "last_seen_ts": min(seen)
                            if all(ts is not None for ts in seen)
                            else None
                        }
                    )
                )
    return ranked_facts(scene, result, limit=limit, tiers=False)


def extraction_text(scene, source, character, *, read=None):
    read = read or PerspectiveReadContext(scene)
    selected = select_character_view(scene, source, character, read=read)
    if selected.status != "ready" or not source_visible(
        source, character, read=read, cache={}
    ):
        raise ValueError("Fact extraction source is not ready")
    if source.kind == "disclosure":
        return selected.text
    if source.kind == "message":
        return format_message_view(
            read.sources[source.key][0].owner, selected.text, "chat"
        )
    owner = read.sources[source.key][0]
    view = next(
        view for view in owner.knowledge.views if view.id == selected.source.view_id
    )
    texts = []
    for dependency in view.sources:
        part = select_character_view(scene, dependency, character, read=read)
        if part.status == "ready":
            texts.append(
                format_message_view(
                    read.sources[dependency.key][0].owner, part.text, "chat"
                )
                if dependency.kind == "message"
                else part.text
            )
        elif part.status not in ("omitted", "unavailable"):
            raise ValueError("Fact extraction dependency is not ready")
    return "\n\n".join(texts) if texts else selected.text


def learning_acquisition(scene, source, character, *, read, cache=None):
    cache = {} if cache is None else cache
    key = (source, character)
    if key in cache:
        return cache[key]
    selected = select_character_view(scene, source, character, read=read)
    acquired = selected.acquired
    if source.kind == "summary":
        view = next(
            view
            for view in read.sources[source.key][0].knowledge.views
            if view.id == selected.source.view_id
        )
        acquisitions = [
            learning_acquisition(scene, dependency, character, read=read, cache=cache)
            for dependency in view.sources
            if select_character_view(scene, dependency, character, read=read).status
            == "ready"
        ]
        if acquisitions:
            acquired = max(acquisitions, key=lambda item: item.order)
    cache[key] = acquired
    return acquired


def contributions_for_source(scene, source, audience, parsed):
    read = PerspectiveReadContext(scene)
    views = [select_character_view(scene, source, name, read=read) for name in audience]
    if views and not parsed and all(view.status == "omitted" for view in views):
        return ()
    if not views or any(view.status != "ready" for view in views):
        raise ValueError(
            "Fact extraction requires a current source for its whole audience"
        )
    if len({(view.source, view.text, view.acquired) for view in views}) != 1:
        raise ValueError("Fact extraction audiences must share the same source view")
    view = views[0]
    input_text = " ".join(
        extraction_text(scene, source, audience[0], read=read).split()
    )
    acquired = learning_acquisition(scene, view.source, audience[0], read=read)
    allowed_previous = {fact.id for fact in previous_audience_facts(scene, audience)}
    result = []
    for item in parsed:
        text = " ".join(item.text.split())
        time_scope = " ".join(item.time_scope.split()) if item.time_scope else None
        if time_scope and (time_scope not in text or time_scope not in input_text):
            log.debug("dropping unsupported fact time scope", source_id=source.id)
            time_scope = None
        result.append(
            FactContribution(
                source=view.source,
                acquired=acquired,
                audience=tuple(audience),
                text=text,
                importance=item.importance,
                subjects=tuple(sorted(set(item.subjects))),
                time_scope=time_scope,
                supersedes=item.supersedes
                if item.supersedes in allowed_previous
                else None,
            )
        )
    return tuple(dict.fromkeys(result))


def sanitize_fact_links(facts, previous=None):
    """Keep existing valid edges first; reject dangling, self and cyclic links.

    Include contribution edges: a character's aggregate may choose a different
    predecessor than the author aggregate does.
    """

    def edges(records):
        return {
            (fact.id, target)
            for fact in records.values()
            for target in (fact.supersedes, *(c.supersedes for c in fact.contributions))
            if target is not None
        }

    old = edges(previous or {})
    accepted = set()
    adjacency = {}
    for origin, target in sorted(
        edges(facts), key=lambda edge: (edge not in old, edge)
    ):
        if target not in facts or target == origin:
            continue
        pending, seen = [target], set()
        while pending:
            node = pending.pop()
            if node in seen:
                continue
            seen.add(node)
            pending.extend(adjacency.get(node, ()))
        if origin in seen:
            continue
        accepted.add((origin, target))
        adjacency.setdefault(origin, set()).add(target)
    touched = set()
    for identity, fact in list(facts.items()):
        contributions = tuple(
            item
            if item.supersedes is None or (identity, item.supersedes) in accepted
            else item.model_copy(update={"supersedes": None})
            for item in fact.contributions
        )
        supersedes = (
            fact.supersedes if (identity, fact.supersedes) in accepted else None
        )
        if contributions != fact.contributions or supersedes != fact.supersedes:
            facts[identity] = fact.model_copy(
                update={
                    "contributions": contributions,
                    "supersedes": supersedes,
                }
            )
            touched.add(identity)
    return touched


def _replace_contributions(facts, sources, replacements, counter):
    updated = dict(facts)
    touched = set()
    reusable = {}
    for identity, fact in facts.items():
        kept = tuple(
            item for item in fact.contributions if item.identity not in sources
        )
        if kept == fact.contributions:
            continue
        touched.add(identity)
        if kept:
            updated[identity] = aggregate_fact(fact, kept)
        else:
            del updated[identity]
            for item in fact.contributions:
                reusable.setdefault(item.equivalence_key, identity)
    exact = {
        fact.contributions[0].equivalence_key: fact.id
        for fact in updated.values()
        if fact.contributions
        and not fact.false
        and all(
            item.equivalence_key == fact.contributions[0].equivalence_key
            for item in fact.contributions
        )
    }
    for contribution in replacements:
        identity = exact.get(contribution.equivalence_key)
        if identity is None:
            identity = reusable.get(contribution.equivalence_key)
            if identity is None or identity in updated:
                counter += 1
                while f"F{counter}" in facts or f"F{counter}" in updated:
                    counter += 1
                identity = f"F{counter}"
            fact = Fact(
                id=identity,
                text=contribution.text,
                importance=contribution.importance,
                source="disclosure"
                if contribution.source.kind == "disclosure"
                else "perspective",
            )
            exact[contribution.equivalence_key] = identity
        else:
            fact = updated[identity]
        updated[identity] = aggregate_fact(fact, (*fact.contributions, contribution))
        touched.add(identity)
    for identity in touched & updated.keys() & facts.keys():
        if frozenset(updated[identity].contributions) == frozenset(
            facts[identity].contributions
        ):
            updated[identity] = facts[identity]
    touched.update(sanitize_fact_links(updated, facts))
    return updated, touched, counter


async def replace_source_facts(
    scene,
    batches: Iterable[tuple[SourceReference, tuple[str, ...], list[ParsedFact]]],
):
    if not character_knowledge_enabled(scene):
        raise ValueError("Source-supported facts require perception mode")
    batches = list(batches)
    replacements = []
    sources = set()
    for source, audience, parsed in batches:
        replacements.extend(contributions_for_source(scene, source, audience, parsed))
        selected = select_character_view(scene, source, audience[0])
        sources.add((selected.source.key, selected.source.view_id))
    facts, touched, counter = _replace_contributions(
        scene.world_state.facts, sources, replacements, scene.world_state.fact_counter
    )
    removed = scene.world_state.facts.keys() - facts.keys()
    scene.world_state.facts = facts
    scene.world_state.fact_counter = counter
    scene.world_state.knowledge = [
        edge for edge in scene.world_state.knowledge if edge.target not in removed
    ]
    summarizer = get_agent("summarizer")
    summarizer._fact_memory_dirty.setdefault(scene, set()).update(touched)
    await summarizer.flush_fact_memory(scene)
    return [facts[key] for key in touched if key in facts]


def prune_contributions(world_state, references):
    references = tuple(references)
    sources = {
        item.identity
        for fact in world_state.facts.values()
        for item in fact.contributions
        if any(
            item.source.key == reference.key
            and (reference.view_id is None or item.source.view_id == reference.view_id)
            for reference in references
        )
    }
    facts, touched, _ = _replace_contributions(
        world_state.facts, sources, (), world_state.fact_counter
    )
    world_state.facts = facts
    return touched


def retain_current_contributions(scene, references):
    """Invalidate affected evidence, preserving remaining members of a reduced audience."""
    references = tuple(references)
    read = PerspectiveReadContext(scene)
    touched = set()
    for identity, fact in list(scene.world_state.facts.items()):
        if not any(
            item.source.key == reference.key
            and (reference.view_id is None or item.source.view_id == reference.view_id)
            for item in fact.contributions
            for reference in references
        ):
            continue
        kept = supported_contributions(scene, fact, read=read)
        if kept == fact.contributions:
            continue
        touched.add(identity)
        if kept:
            scene.world_state.facts[identity] = aggregate_fact(fact, kept)
        else:
            del scene.world_state.facts[identity]
    touched.update(sanitize_fact_links(scene.world_state.facts))
    scene.world_state.knowledge = [
        edge
        for edge in scene.world_state.knowledge
        if edge.target not in touched or edge.target in scene.world_state.facts
    ]
    return touched
