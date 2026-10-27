import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal
from types import EllipsisType

import pydantic
import structlog

from talemate.agents.context import active_agent
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.bucket import knowledge_digest
from talemate.knowledge.context import project_character_history
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    source_reference,
    select_character_view,
)
from talemate.knowledge.snapshots import snapshot_for
from talemate.util import count_tokens

log = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from talemate.agents.base import Agent, AgentEmission
    from talemate.tale_mate import Character, Scene

KnowledgeAnalysisType = Literal["conversation", "narration"]
ENTRY_SOURCE_KINDS = {"dialogue": "message", "archived": "summary", "layer": "summary"}


class AuthoredEvidence(pydantic.BaseModel):
    label: str | None = None
    text: str


def advice_character(
    scene: "Scene",
    character: "Character | str | None" = None,
    *,
    typ: KnowledgeAnalysisType | None = None,
) -> "Character | None":
    """Resolve an advice target, including the active narrator's subject."""
    if not character_knowledge_enabled(scene):
        return character
    if character is None and typ == "narration":
        context = active_agent.get()
        character = context.state.get("narrator__character") if context else None
    if isinstance(character, str):
        name = character
        character = scene.get_character(name)
        if character is None:
            raise GenerationCancelled(f"Unknown advice character: {name}")
    if character is not None and scene.get_character(character.name) is not character:
        raise GenerationCancelled("Advice character no longer belongs to this scene")
    return character


def emission_analysis_type(
    emission: "AgentEmission", character: "Character | None"
) -> KnowledgeAnalysisType:
    """Identify the generation family without treating a narrator's subject as an actor."""
    variables = getattr(emission, "template_vars", {})
    return variables.get("analysis_type") or (
        "narration"
        if emission.agent.agent_type == "narrator" or character is None
        else "conversation"
    )


def emission_character(scene: "Scene", emission: "AgentEmission") -> "Character | None":
    """Resolve the target carried by a generation or revision emission."""
    info = getattr(emission, "info", None)
    variables = getattr(emission, "template_vars", {})
    return advice_character(
        scene,
        getattr(emission, "character", None)
        or (info.character if info else None)
        or variables.get("character"),
        typ=variables.get("analysis_type")
        or ("narration" if emission.agent.agent_type == "narrator" else None),
    )


def advice_context(
    scene: "Scene",
    character: "Character | str",
    budget: int,
    *,
    read: PerspectiveReadContext | None = None,
    documents: dict | None = None,
    before_message_id: int | None = None,
    entries: list[dict] | None = None,
) -> dict[str, Any]:
    """Select bounded audience evidence; pending history cancels actor generation.

    A synchronous batch may share its read context and authored documents. Neither
    may be retained across an await or a scene mutation.
    """
    character = advice_character(scene, character)
    if character is None:
        raise ValueError("Character advice requires a character")
    viewer = character.name
    read = read or PerspectiveReadContext(scene)
    if documents is None:
        documents = audience_documents(scene, groups={("authored",)}, read=read)
    authored = []
    used = 0
    for document in documents.values():
        meta = document["meta"]
        if not (
            meta["knowledge_common"] or viewer in meta.get("knowledge_audience", ())
        ):
            continue
        size = count_tokens(document["text"])
        if used + size > budget // 3:
            continue
        authored.append(
            AuthoredEvidence(label=document.get("label"), text=document["text"])
        )
        used += size
    snapshot = snapshot_for(scene, viewer, read=read)
    bounded_snapshot = {"location": None, "characters": [], "items": [], "places": []}
    for key, value in snapshot.items():
        for text in [value] if key == "location" and value else value or []:
            candidate = {
                **bounded_snapshot,
                key: text if key == "location" else [*bounded_snapshot[key], text],
            }
            if count_tokens(json.dumps(candidate)) <= budget // 3:
                bounded_snapshot = candidate
    return {
        "character": viewer,
        "history": project_character_history(
            scene,
            viewer,
            budget=budget // 3,
            read=read,
            before_message_id=before_message_id,
            entries=entries,
        ),
        "authored": authored,
        "snapshot": bounded_snapshot,
    }


def analysis_evidence_fingerprint(
    scene: "Scene", character: "Character", boundary: list[int], budget: int
) -> str:
    """Hash the rendered audience evidence at the saved pre-reply history boundary.

    Index maintenance and later reply versions do not change these inputs. Keep
    source/view revisions too: an earlier edit must invalidate even if its repaired
    projection happens to use the same words. Knowledge edits remain invalidators.
    """
    prefix = scene.history[: len(boundary)]
    if [message.id for message in prefix] != boundary:
        return "removed-analysis-boundary"
    before = (
        scene.history[len(boundary)].id if len(scene.history) > len(boundary) else None
    )
    read = PerspectiveReadContext(scene)
    entries = []
    try:
        evidence = advice_context(
            scene,
            character,
            budget,
            read=read,
            before_message_id=before,
            entries=entries,
        )
    except GenerationCancelled:
        return "pending-analysis-evidence"
    references = []
    for entry in entries:
        if entry["type"] == "disclosure":
            continue  # Disclosures are included with their complete records below.
        reference = source_reference(
            scene,
            ENTRY_SOURCE_KINDS.get(entry["type"], entry["type"]),
            entry["id"],
            layer=entry["layer"],
            read=read,
        )
        if reference is not None:
            view = select_character_view(scene, reference, character.name, read=read)
            references.append(view.source.model_dump(mode="json"))
    payload = {
        "boundary": boundary,
        "budget": budget,
        "evidence": {
            **evidence,
            "authored": [item.model_dump() for item in evidence["authored"]],
        },
        "prefix": [
            (
                message.id,
                content_digest(message.perception_text),
                message.knowledge.revision if message.knowledge else None,
            )
            for message in prefix
        ],
        "sources": references,
        "visibility": knowledge_digest(scene),
        "disclosures": [
            item.model_dump(mode="json") for item in read.disclosures.values()
        ],
        "description": scene.description,
        "intention": scene.intent_state.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def deep_analysis_fingerprint(scene, character, boundary):
    """Cover the audience sources available to deep retrieval, beyond initial history.

    Question-based RAG returns generated text, not document references. Until it
    carries provenance, validate the full eligible source set rather than guessing
    which documents its answer used. Later reply variants stay outside the boundary.
    """
    if boundary is None or character is None:
        return advice_fingerprint(scene, character)
    messages = set(boundary)
    documents = audience_documents(scene)
    eligible = sorted(
        identity
        for identity, document in documents.items()
        if (document["group"][0] != "message" or document["group"][1] in messages)
        and (
            document["meta"]["knowledge_common"]
            or character.name in document["meta"].get("knowledge_audience", ())
        )
    )
    return hashlib.sha256(json.dumps(eligible).encode()).hexdigest()


def advice_fingerprint(
    scene: "Scene",
    character: "Character | None" = None,
    *,
    boundary: list[int] | None = None,
    budget: int | None = None,
) -> str | None:
    """Identify the current structured evidence, visibility, cast and snapshot."""
    if not character_knowledge_enabled(scene):
        return None
    if boundary is not None and character is not None:
        return analysis_evidence_fingerprint(scene, character, boundary, budget)
    read = PerspectiveReadContext(scene)
    payload = [
        character.name if character else None,
        get_agent("memory")._audience_state(scene).revision,
        knowledge_digest(scene),
        tuple(scene.active_characters),
        tuple(scene.character_data),
        scene.ts,
        [
            (
                key,
                [
                    (
                        content_digest(source.text),
                        source.knowledge.revision if source.knowledge else None,
                    )
                    for source in sources
                ],
            )
            for key, sources in read.sources.items()
        ],
        scene.world_state.model_dump(
            include={
                "location",
                "location_perspectives",
                "characters",
                "items",
                "places",
            },
            mode="json",
        ),
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def advice_record_metadata(
    agent: "Agent",
    character: "Character | None",
    typ: KnowledgeAnalysisType,
    *,
    evidence_fp: str | None = None,
    boundary: list[int] | None = None,
    budget: int | None = None,
) -> dict[str, Any]:
    """Stamp cached or directly inserted advice with its audience and freshness."""
    return {
        "character": character.name if character else None,
        "analysis_type": typ,
        "context_fp": agent.context_fingerprint(),
        "evidence_boundary": boundary,
        "evidence_budget": budget,
        "evidence_fp": evidence_fp
        if evidence_fp is not None
        else advice_fingerprint(
            agent.scene, character, boundary=boundary, budget=budget
        ),
    }


def advice_record_is_current(
    agent: "Agent",
    record: dict[str, Any],
    character: "Character | None",
    typ: KnowledgeAnalysisType | None,
    *,
    evidence_fp: str | None | EllipsisType = ...,
) -> bool:
    """Require the same target, analysis type, generation context and evidence."""
    return (
        record.get("evidence_fp")
        not in {"pending-analysis-evidence", "removed-analysis-boundary"}
        and record.get("character") == (character.name if character else None)
        and record.get("analysis_type") == typ
        and record.get("context_fp") == agent.context_fingerprint()
        and record.get("evidence_fp")
        == (
            advice_fingerprint(
                agent.scene,
                character,
                boundary=record.get("evidence_boundary"),
                budget=record.get("evidence_budget"),
            )
            if evidence_fp is ...
            else evidence_fp
        )
    )


def require_advice_scene(agent: "Agent", scene: "Scene") -> None:
    if agent.scene is not scene:
        raise GenerationCancelled("The scene changed during advice generation")


def warn_stale_advice(
    agent: "Agent",
    scene: "Scene",
    character: "Character | None",
    fingerprint: str | None,
    *,
    boundary: list[int] | None = None,
    budget: int | None = None,
) -> None:
    if boundary is not None and [message.id for message in scene.history] != boundary:
        changed = "history"
    elif (
        advice_fingerprint(scene, character, boundary=boundary, budget=budget)
        != fingerprint
    ):
        changed = "evidence"
    else:
        return
    log.warning(
        "advice evidence changed during generation",
        character=character.name if character else None,
        changed=changed,
    )
