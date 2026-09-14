from collections.abc import Iterable

import structlog

from talemate.instance import get_agent
from talemate.knowledge.chronology import ranked_facts
from talemate.knowledge.formatting import format_message_view
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.evidence import message_views, view_evidence
from talemate.knowledge.perspective_models import SourceReference
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
)
from talemate.knowledge.schema import Fact, FactContribution, ParsedFact
from talemate.knowledge.summaries import summary_coverage
from talemate.knowledge.timeline import message_times, refresh_fact_times


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
    from talemate.knowledge.fact_reconciliation import inference_supported

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
            and inference_supported(scene, contribution, name, read=read)
            and source_visible(contribution.source, name, read=read, cache=coverage)
            and select_character_view(
                scene, contribution.source, name, read=read
            ).status
            == "ready"
        )
        if audience:
            result.append(contribution.model_copy(update={"audience": audience}))
    return tuple(result)


def _ordered(contributions):
    return sorted(
        contributions,
        key=lambda item: (item.acquired.order, item.inferred_from is not None),
    )


def contribution_link(ordered):
    """The link the contributions carry: the last direct one, else the last."""
    return next(
        (item.supersedes for item in reversed(ordered) if item.inferred_from is None),
        ordered[-1].supersedes,
    )


def contribution_time(item, times=None):
    """The scene time at the contribution's message; its acquisition otherwise."""
    if times is not None and item.message_id in times:
        return times[item.message_id]
    return item.acquired.ts


def aggregate_fact(fact, contributions, *, times=None):
    ordered = _ordered(contributions)
    first = ordered[0]
    message_id = next(
        (item.message_id for item in ordered if item.message_id is not None), None
    )
    # an authored text or link stays; otherwise the contributions decide, so
    # each view keeps its own wording
    return fact.model_copy(
        update={
            "text": fact.text if fact.text_edited else first.text,
            "ts": contribution_time(first, times),
            "last_seen_ts": max(contribution_time(item, times) for item in ordered),
            "archive_id": next(
                (item.source.id for item in ordered if item.source.kind == "summary"),
                None,
            ),
            "message_id": message_id,
            "present": sorted({name for item in ordered for name in item.audience}),
            "known_by": {},
            "supersedes": fact.supersedes
            if fact.link_edited
            else contribution_link(ordered),
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
    times = cache.get("message_times") if cache is not None else None
    if times is None:
        times = message_times(scene)
        if cache is not None:
            cache["message_times"] = times
    # The false mark is an author judgement, and the chain a character holds
    # runs through their own contributions.
    return aggregate_fact(fact, contributions, times=times).model_copy(
        update={
            "false": False,
            "supersedes": contribution_link(_ordered(contributions)),
        }
    )


def previous_audience_facts(scene, audience, limit=30, *, prompt=True):
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
    return ranked_facts(
        scene, result, limit=limit, tiers=False, superseders=result, prompt=prompt
    )


def extraction_lines(
    scene, source, character, *, read=None
) -> list[tuple[str, int | None]]:
    """
    The text a fact rebuild reads for `source`, one item per line with the
    message id the line came from (None for a disclosure or a line that is
    not a message): the same inputs the archive step sends.
    """
    read = read or PerspectiveReadContext(scene)
    selected = select_character_view(scene, source, character, read=read)
    if selected.status != "ready" or not source_visible(
        source, character, read=read, cache={}
    ):
        raise ValueError("Fact extraction source is not ready")
    if source.kind == "disclosure":
        return [(selected.text, None)]
    if source.kind == "message":
        return [
            (
                format_message_view(
                    read.sources[source.key][0].owner, selected.text, "chat"
                ),
                source.id,
            )
        ]
    owner = read.sources[source.key][0]
    view = next(
        view for view in owner.knowledge.views if view.id == selected.source.view_id
    )
    lines = []
    for dependency in view.sources:
        part = select_character_view(scene, dependency, character, read=read)
        if part.status == "ready":
            lines.append(
                (
                    format_message_view(
                        read.sources[dependency.key][0].owner, part.text, "chat"
                    ),
                    dependency.id,
                )
                if dependency.kind == "message"
                else (part.text, None)
            )
        elif part.status not in ("omitted", "unavailable"):
            raise ValueError("Fact extraction dependency is not ready")
    return lines if lines else [(selected.text, None)]


def extraction_text(scene, source, character, *, read=None):
    return "\n\n".join(
        text for text, _ in extraction_lines(scene, source, character, read=read)
    )


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


async def contributions_for_source(
    scene, source, audience, parsed, *, comparisons=None
):
    from talemate.knowledge.fact_comparisons import FactComparisons

    comparisons = comparisons or FactComparisons(scene, [(source, audience, parsed)])
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
    inputs = extraction_lines(scene, source, audience[0], read=read)
    input_text = " ".join(" ".join(text for text, _ in inputs).split())
    acquired = learning_acquisition(scene, view.source, audience[0], read=read)
    allowed_previous = {
        fact.id for fact in previous_audience_facts(scene, audience, prompt=False)
    }
    result = []
    evidence = {
        item.id: item for item in view_evidence(scene, source, audience[0], read=read)
    }
    # a span fact must name one of the lines the view was built from; a
    # disclosure or a static entry has no lines at all. A request that read
    # exactly one input, a message, has exactly one line that can establish
    # a fact, so a missing id binds to it.
    line_ids = (
        set(message_views(scene, source, audience[0], read=read)) or None
        if source.kind != "disclosure"
        else None
    )
    single = len(inputs) == 1 and line_ids is not None and len(line_ids) == 1
    for item in parsed:
        if single and item.message_id is None:
            item = item.model_copy(update={"message_id": next(iter(line_ids))})
        if line_ids is not None and item.message_id not in line_ids:
            log.warning(
                "fact names no line of its span; dropped",
                source_id=source.id,
                message_id=item.message_id,
                text=item.text[:80],
            )
            continue
        if item.evidence_id is not None and item.evidence_id not in evidence:
            log.warning(
                "dropping unsupported fact evidence",
                source_id=source.id,
                evidence_id=item.evidence_id,
            )
        text = " ".join(item.text.split())
        cited = evidence.get(item.evidence_id)
        competitors = (
            await comparisons.outranking(text, cited, source, audience[0])
            if cited is not None
            else ()
        )
        citation_rejected = cited is not None and (
            competitors is None or not set(competitors).issubset(evidence.values())
        )
        if citation_rejected:
            log.warning(
                "citation not supported",
                source_id=source.id,
                evidence_id=item.evidence_id,
            )
            cited = None
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
                message_id=item.message_id if line_ids is not None else None,
                evidence=cited,
                citation_rejected=citation_rejected,
                evidence_competitors=competitors or (),
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
            if identity is not None and identity not in updated:
                # the same evidence returned: the author's record survives
                fact = facts[identity].model_copy(update={"contributions": ()})
            else:
                counter += 1
                while f"F{counter}" in facts or f"F{counter}" in updated:
                    counter += 1
                identity = f"F{counter}"
                fact = Fact(
                    id=identity,
                    text=contribution.text,
                    importance=contribution.importance,
                    subjects=list(contribution.subjects),
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
    snapshot = {
        key: fact.model_copy(deep=True) for key, fact in scene.world_state.facts.items()
    }
    from talemate.knowledge.fact_comparisons import FactComparisons

    comparisons = FactComparisons(scene, batches)
    replacements = []
    sources = set()
    for source, audience, parsed in batches:
        replacements.extend(
            await contributions_for_source(
                scene, source, audience, parsed, comparisons=comparisons
            )
        )
        selected = select_character_view(scene, source, audience[0])
        sources.add((selected.source.key, selected.source.view_id))
    from talemate.knowledge.fact_reconciliation import (
        without_inferences,
        reconcile_facts,
    )

    source_keys = {source.key for source, _, _ in batches}
    facts, touched, _ = _replace_contributions(
        without_inferences(scene.world_state.facts, source_keys),
        sources,
        replacements,
        scene.world_state.fact_counter,
    )
    facts, aliases = await reconcile_facts(
        scene, facts, source_keys, comparisons=comparisons
    )
    if (
        scene.world_state.facts != snapshot
        or get_agent("summarizer").scene is not scene
    ):
        raise ValueError("Stored facts changed during reconciliation")
    if aliases:
        for identity, fact in list(facts.items()):
            facts[identity] = fact.model_copy(
                update={
                    "supersedes": aliases.get(fact.supersedes, fact.supersedes),
                    "contributions": tuple(
                        item.model_copy(
                            update={
                                "supersedes": aliases.get(
                                    item.supersedes, item.supersedes
                                ),
                            }
                        )
                        for item in fact.contributions
                    ),
                }
            )
        for topic in scene.world_state.topics.values():
            topic.fact_ids = list(
                dict.fromkeys(
                    aliases.get(identity, identity) for identity in topic.fact_ids
                )
            )
    touched.update(sanitize_fact_links(facts, snapshot))
    for identity in facts.keys() & snapshot.keys():
        if facts[identity].supersedes == snapshot[identity].supersedes and frozenset(
            facts[identity].contributions
        ) == frozenset(snapshot[identity].contributions):
            facts[identity] = snapshot[identity]
    touched.update(
        key
        for key in snapshot.keys() | facts.keys()
        if snapshot.get(key) != facts.get(key)
    )
    removed = scene.world_state.facts.keys() - facts.keys()
    scene.world_state.facts = facts
    scene.world_state.fact_counter = max(
        scene.world_state.fact_counter,
        max(
            (
                int(identity[1:])
                for identity in facts
                if identity.startswith("F") and identity[1:].isdigit()
            ),
            default=0,
        ),
    )
    scene.world_state.knowledge = [
        edge for edge in scene.world_state.knowledge if edge.target not in removed
    ]
    touched.update(refresh_fact_times(scene))
    summarizer = get_agent("summarizer")
    summarizer._fact_memory_dirty.setdefault(scene, set()).update(touched)
    await summarizer.flush_fact_memory(scene)
    return [facts[key] for key in touched if key in facts]


def prune_contributions(world_state, references):
    references = tuple(references)
    facts = dict(world_state.facts)
    touched = set()
    for identity, fact in world_state.facts.items():
        kept = tuple(
            item
            for item in fact.contributions
            if not any(
                support.key == reference.key
                and (reference.view_id is None or support.view_id == reference.view_id)
                for support in (item.source, item.inferred_from)
                if support is not None
                for reference in references
            )
        )
        if kept == fact.contributions:
            continue
        touched.add(identity)
        if kept:
            facts[identity] = aggregate_fact(fact, kept)
        else:
            del facts[identity]
    touched.update(sanitize_fact_links(facts, world_state.facts))
    world_state.facts = facts
    return touched


def retain_current_contributions(scene, references):
    """Invalidate affected evidence, preserving remaining members of a reduced audience."""
    references = tuple(references)
    read = PerspectiveReadContext(scene)
    touched = set()
    for identity, fact in list(scene.world_state.facts.items()):
        if not any(
            any(
                support.key == reference.key
                and (reference.view_id is None or support.view_id == reference.view_id)
                for support in (item.source, item.inferred_from)
                if support is not None
            )
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
    touched.update(refresh_fact_times(scene))
    return touched
