import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

from talemate.agents.context import active_agent
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.bucket import knowledge_digest
from talemate.knowledge.context import project_character_history
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.knowledge.snapshots import snapshot_for
from talemate.util import count_tokens

if TYPE_CHECKING:
    from talemate.agents.base import Agent, AgentEmission
    from talemate.tale_mate import Character, Scene

KnowledgeAnalysisType = Literal["conversation", "narration"]


class StaleAdvice(GenerationCancelled):
    focal_reraise = True


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
        authored.append(document["text"])
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
            scene, viewer, budget=budget // 3, read=read
        ),
        "authored": authored,
        "snapshot": bounded_snapshot,
    }


def advice_fingerprint(
    scene: "Scene", character: "Character | None" = None
) -> str | None:
    """Identify the current structured evidence, visibility, cast and snapshot."""
    if not character_knowledge_enabled(scene):
        return None
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
) -> dict[str, Any]:
    """Stamp cached or directly inserted advice with its audience and freshness."""
    return {
        "character": character.name if character else None,
        "analysis_type": typ,
        "context_fp": agent.context_fingerprint(),
        "evidence_fp": evidence_fp
        if evidence_fp is not None
        else advice_fingerprint(agent.scene, character),
    }


def advice_record_is_current(
    agent: "Agent",
    record: dict[str, Any],
    character: "Character | None",
    typ: KnowledgeAnalysisType | None,
) -> bool:
    """Require the same target, analysis type, generation context and evidence."""
    return (
        record.get("character") == (character.name if character else None)
        and record.get("analysis_type") == typ
        and record.get("context_fp") == agent.context_fingerprint()
        and record.get("evidence_fp") == advice_fingerprint(agent.scene, character)
    )


def require_current_advice(
    agent: "Agent",
    scene: "Scene",
    character: "Character | None",
    fingerprint: str | None,
) -> None:
    """Cancel stale generation before insertion or Focal callback execution."""
    if agent.scene is not scene or advice_fingerprint(scene, character) != fingerprint:
        raise StaleAdvice("Character evidence changed during advice generation; retry")
