from collections import defaultdict

import structlog

from talemate.instance import get_agent
from talemate.knowledge.evidence import (
    evidence_presence,
    competitors_visible,
    view_evidence,
    recipient_evidence_view,
)
from talemate.knowledge.names import aliases_for
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
)


log = structlog.get_logger(__name__)


def without_inferences(facts, source_keys):
    from talemate.knowledge.supported_facts import aggregate_fact

    result = dict(facts)
    for identity, fact in facts.items():
        kept = tuple(
            item
            for item in fact.contributions
            if item.inferred_from is None or item.source.key not in source_keys
        )
        if kept == fact.contributions:
            continue
        if kept:
            result[identity] = aggregate_fact(fact, kept)
        else:
            del result[identity]
    return result


async def reconcile_facts(scene, facts, source_keys, *, comparisons):
    from talemate.knowledge.supported_facts import (
        aggregate_fact,
        learning_acquisition,
        supported_contributions,
    )

    facts = dict(facts)
    groups = defaultdict(list)
    for fact in facts.values():
        if fact.false or not fact.contributions:
            continue
        first = fact.contributions[0]
        if first.evidence is None or first.source.key not in source_keys:
            continue
        if all(
            (item.evidence, item.time_scope, item.supersedes)
            == (first.evidence, first.time_scope, first.supersedes)
            for item in fact.contributions
        ):
            groups[
                (
                    first.source.key,
                    first.evidence,
                    first.time_scope,
                    first.supersedes,
                )
            ].append(fact.id)

    aliases = {}
    for identities in groups.values():
        audiences = {
            identity: {
                name for item in facts[identity].contributions for name in item.audience
            }
            for identity in identities
        }
        if not any(
            not audiences[left] & audiences[right]
            for index, left in enumerate(identities)
            for right in identities[index + 1 :]
        ):
            continue
        matches = []
        for left, identity in enumerate(identities):
            for right in range(left + 1, len(identities)):
                distance = await comparisons.distance(
                    facts[identity].contributions[0].evidence,
                    facts[identity].text,
                    facts[identities[right]].text,
                )
                if distance <= get_agent("summarizer").archive_fact_dedupe_distance:
                    matches.append((left, right, distance))
        for left, right, _ in sorted(matches, key=lambda item: item[2]):
            if left >= right:
                continue
            a, b = identities[left], identities[right]
            while a in aliases:
                a = aliases[a]
            while b in aliases:
                b = aliases[b]
            if a == b or audiences[a] & audiences[b]:
                continue
            left_subjects, right_subjects = (
                {
                    alias
                    for subject in facts[a].subjects
                    for alias in aliases_for(scene, subject)
                },
                {
                    alias
                    for subject in facts[b].subjects
                    for alias in aliases_for(scene, subject)
                },
            )
            if left_subjects and right_subjects and not left_subjects & right_subjects:
                continue
            facts[a] = aggregate_fact(
                facts[a], (*facts[a].contributions, *facts[b].contributions)
            )
            audiences[a].update(audiences[b])
            aliases[b] = a
            del facts[b]

    for identity in aliases:
        target = aliases[identity]
        while target in aliases:
            target = aliases[target]
        aliases[identity] = target

    read = PerspectiveReadContext(scene)
    held = defaultdict(list)
    for fact in facts.values():
        for item in fact.contributions:
            if item.evidence is not None:
                for name in item.audience:
                    held[item.source.key, item.evidence, name].append(item.text)

    for identity, fact in list(facts.items()):
        if (
            not fact.contributions
            or fact.contributions[0].source.key not in source_keys
        ):
            continue
        direct = fact.contributions
        if supported_contributions(scene, fact, read=read) != direct:
            raise ValueError("Fact sources changed during reconciliation")
        source = direct[0].source
        if source.kind != "summary" and source.kind != "message":
            continue
        owner = read.sources[source.key][0]
        known = {name for item in direct for name in item.audience}
        inferred = []
        for group in owner.knowledge.views:
            for name in group.audience:
                if name in known:
                    continue
                selected = select_character_view(
                    scene,
                    source.model_copy(update={"view_id": None, "view_revision": None}),
                    name,
                    read=read,
                )
                if selected.status != "ready":
                    continue
                donor = None
                for item in direct:
                    if item.evidence is None or not evidence_presence(
                        read, item.evidence, name
                    ):
                        continue
                    recipient = recipient_evidence_view(
                        scene,
                        selected.source,
                        item.evidence,
                        name,
                        read=read,
                    )
                    if recipient is None:
                        continue
                    if not competitors_visible(
                        scene,
                        selected.source,
                        name,
                        item.evidence_competitors,
                        read=read,
                    ):
                        log.warning(
                            "citation not supported",
                            source_id=source.id,
                            evidence_id=item.evidence.id,
                            recipient=name,
                        )
                        continue
                    duplicate = False
                    for text in held[source.key, item.evidence, name]:
                        if (
                            await comparisons.distance(item.evidence, item.text, text)
                            <= get_agent("summarizer").archive_fact_dedupe_distance
                        ):
                            duplicate = True
                            break
                    if duplicate:
                        continue
                    donor = item
                    break
                if donor is None:
                    continue
                held[source.key, donor.evidence, name].append(donor.text)
                inferred.append(
                    donor.model_copy(
                        update={
                            "source": selected.source,
                            "audience": (name,),
                            "acquired": learning_acquisition(
                                scene, selected.source, name, read=read
                            ),
                            "inferred_from": donor.source,
                            "supersedes": donor.supersedes
                            if donor.supersedes in facts
                            and supported_contributions(
                                scene, facts[donor.supersedes], name, read=read
                            )
                            else None,
                        }
                    )
                )
        if inferred:
            facts[identity] = aggregate_fact(fact, (*direct, *inferred))
    read = PerspectiveReadContext(scene)
    if any(
        fact.contributions
        and fact.contributions[0].source.key in source_keys
        and supported_contributions(scene, fact, read=read) != fact.contributions
        for fact in facts.values()
    ):
        raise ValueError("Fact sources changed during reconciliation")
    return facts, aliases


def inference_supported(scene, contribution, character, *, read):
    if contribution.inferred_from is None:
        return True
    origin = contribution.inferred_from
    owners = read.sources.get(origin.key, ())
    if len(owners) != 1 or owners[0].knowledge is None or contribution.evidence is None:
        return False
    donor = next(
        (view for view in owners[0].knowledge.views if view.id == origin.view_id), None
    )
    return (
        donor is not None
        and donor.revision == origin.view_revision
        and any(
            contribution.evidence in view_evidence(scene, origin, name, read=read)
            for name in donor.audience
        )
        and competitors_visible(
            scene,
            contribution.source,
            character,
            contribution.evidence_competitors,
            read=read,
        )
        and evidence_presence(read, contribution.evidence, character)
        and recipient_evidence_view(
            scene,
            contribution.source,
            contribution.evidence,
            character,
            read=read,
        )
        is not None
    )


def fact_knowledge_reason(scene, fact, character, *, read=None, cache=None):
    from talemate.knowledge.supported_facts import supported_contributions

    read = read or PerspectiveReadContext(scene)
    own = supported_contributions(scene, fact, character, read=read, cache=cache)
    if own:
        return (
            "Inferred from shared evidence"
            if all(item.inferred_from is not None for item in own)
            else None
        )
    reasons = set()
    for item in fact.contributions:
        if item.inferred_from is not None or item.source.kind == "disclosure":
            continue
        source = item.source.model_copy(update={"view_id": None, "view_revision": None})
        selected = select_character_view(scene, source, character, read=read)
        owners = read.sources.get(source.key, ())
        absent_from_message = (
            source.kind == "message"
            and len(owners) == 1
            and owners[0].owner.present is not None
            and character not in owners[0].owner.present
        )
        evidence_owners = (
            read.sources.get(("message", item.evidence.message_id, 0), ())
            if item.evidence
            else ()
        )
        stale = item.evidence is not None and (
            len(evidence_owners) != 1
            or evidence_owners[0].knowledge is None
            or evidence_owners[0].knowledge.revision != item.evidence.revision
        )
        absent_from_evidence = (
            len(evidence_owners) == 1
            and evidence_owners[0].owner.present is not None
            and character not in evidence_owners[0].owner.present
        )
        if selected.status in ("pending", "failed"):
            reasons.add("View pending or failed")
        elif stale:
            reasons.add("View being rebuilt")
        elif absent_from_message or absent_from_evidence:
            reasons.add("Not present")
        elif selected.status == "omitted":
            reasons.add("Private moment")
        elif item.citation_rejected or (
            item.evidence is not None
            and item.evidence in view_evidence(scene, source, character, read=read)
            and not competitors_visible(
                scene, source, character, item.evidence_competitors, read=read
            )
        ):
            reasons.add("Citation not supported")
        elif (
            item.evidence is None
            or selected.status == "ready"
            and item.evidence not in view_evidence(scene, source, character, read=read)
        ):
            reasons.add("Not in their view")
    for reason in (
        "View pending or failed",
        "View being rebuilt",
        "Not present",
        "Private moment",
        "Citation not supported",
        "Not in their view",
    ):
        if reason in reasons:
            return reason
    return f"No contribution from {character}'s view"
