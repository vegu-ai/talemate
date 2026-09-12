import re

from talemate.util import count_tokens
from talemate.knowledge.perspective_models import PassageEvidence
from talemate.knowledge.perspectives import (
    MAX_DEPENDENCY_DEPTH,
    PerspectiveReadContext,
    select_character_view,
)


def passage_spans(text):
    return tuple(
        part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()
    )


def budget_evidence(evidence, context_limit, used_tokens, response_tokens=1024):
    budget = max(
        0, min(context_limit // 8, context_limit - used_tokens - response_tokens - 2048)
    )
    lines = []
    for item in evidence:
        excerpt = " ".join(item["text"].split())
        if len(excerpt) > 160:
            excerpt = excerpt[:157] + "..."
        line = f"{item['id']}: {excerpt}"
        cost = count_tokens(line + "\n")
        if cost > budget:
            break
        lines.append(line)
        budget -= cost
    return "\n".join(lines)


def message_views(scene, source, character, *, read=None, depth=0):
    read = read or PerspectiveReadContext(scene)
    if depth > MAX_DEPENDENCY_DEPTH:
        return {}
    selected = select_character_view(scene, source, character, read=read)
    if selected.status != "ready" or source.kind not in ("message", "summary"):
        return {}
    owner = read.sources[source.key][0]
    view = next(
        view for view in owner.knowledge.views if view.id == selected.source.view_id
    )
    if source.kind == "message":
        return {source.id: (selected.source, view)}
    result = {}
    for dependency in view.sources:
        result.update(
            message_views(scene, dependency, character, read=read, depth=depth + 1)
        )
    return result


def view_evidence(scene, source, character, *, read=None):
    read = read or PerspectiveReadContext(scene)
    result = {}
    for reference, view in message_views(scene, source, character, read=read).values():
        spans = passage_spans(read.sources[reference.key][0].text)
        result.update(
            {
                PassageEvidence(
                    message_id=reference.id, revision=reference.revision, span=index
                ): spans[index]
                for index in (view.evidence_spans or ())
                if index < len(spans)
            }
        )
    return result


def recipient_evidence_view(scene, source, evidence, character, *, read):
    entry = message_views(scene, source, character, read=read).get(evidence.message_id)
    if entry is None:
        return None
    reference, view = entry
    if reference.revision != evidence.revision or view.evidence_spans is None:
        return None
    if evidence.span not in view.evidence_spans:
        return None
    return view


def extraction_evidence(scene, sources, audience, *, read=None):
    read = read or PerspectiveReadContext(scene)
    members = []
    for name in audience:
        evidence = {}
        for source in sources:
            evidence.update(view_evidence(scene, source, name, read=read))
        members.append(evidence)
    if not members:
        return []
    shared = set(members[0]).intersection(*(set(member) for member in members[1:]))
    return [
        {"id": item.id, "text": members[0][item]}
        for item in sorted(
            shared, key=lambda item: (item.message_id, item.revision, item.span)
        )
    ]


def evidence_presence(read, evidence, character):
    owners = read.sources.get(("message", evidence.message_id, 0), ())
    return (
        len(owners) == 1
        and owners[0].knowledge is not None
        and owners[0].knowledge.revision == evidence.revision
        and (owners[0].owner.present is None or character in owners[0].owner.present)
    )


def competitors_visible(scene, source, character, competitors, *, read):
    return not competitors or set(competitors).issubset(
        view_evidence(scene, source, character, read=read)
    )
