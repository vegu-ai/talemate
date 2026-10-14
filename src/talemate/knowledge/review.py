"""Author-facing inspection of the same evidence used by character prompts."""

import json

from talemate.instance import get_agent
from talemate.knowledge.advice import advice_context
from talemate.knowledge.diagnostics import ContextDiagnostics
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.disclosures import disclosure_text
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.prompts import Prompt
from talemate.util import count_tokens


def section(kind, label, entries):
    entries = [entry for entry in entries if entry]
    return {
        "type": kind,
        "label": label,
        "entries": entries,
        "entry_count": len(entries),
        "token_count": count_tokens(entries),
    }


def _history_identity(entry):
    return (entry.get("type"), entry.get("id"), entry.get("layer"), entry.get("text"))


def _history_boundary(entries):
    passage_ids = [
        identity
        for entry in entries
        for identity in entry.get("covered_message_ids", ())
    ]
    passage_ids.extend(
        entry.get("id") for entry in entries if entry.get("type") == "dialogue"
    )
    passage_ids = [identity for identity in passage_ids if isinstance(identity, int)]
    return max(passage_ids) if passage_ids else None


def _analysis_review_section(scene, character, preview, summarizer):
    budget = summarizer.client.max_token_length // 2
    history_budget = budget // 3
    read = PerspectiveReadContext(scene)
    entries = []
    evidence = advice_context(scene, character, budget, read=read, entries=entries)
    full_text = Prompt.get(
        "common.character-evidence-context",
        vars={"scene": scene, "evidence": evidence},
    ).render()

    shown = preview.get("history_selection", [])
    matches = [_history_identity(item) for item in entries] == [
        _history_identity(item) for item in shown
    ]
    selected_boundary = _history_boundary(entries)
    boundary = scene.history[-1].id if scene.history else None
    boundary_text = (
        f"through passage #{boundary}"
        if boundary is not None
        else "before the first passage"
    )
    if matches:
        history_note = (
            f"History as shown above, {len(entries)} selected entries. "
            f"Analysis cutoff: {boundary_text}."
        )
    else:
        history_note = (
            "Analysis uses its own history selection: "
            f"{len(entries)} selected entries, analysis cutoff {boundary_text}, "
            f"{history_budget}-token history budget."
        )

    compact = [history_note, f"Analysis budget: {budget} tokens."]
    compact.extend(
        f"Authored evidence ({item.label}): {item.text}"
        if item.label
        else f"Authored evidence: {item.text}"
        for item in evidence["authored"]
    )
    snapshot = evidence["snapshot"]
    if snapshot.get("location") or any(
        snapshot.get(key) for key in ("characters", "items", "places")
    ):
        compact.append(
            "Scene snapshot: "
            + json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        )
    disclosure_ids = {
        str(entry["id"]) for entry in entries if entry.get("type") == "disclosure"
    }
    disclosure_ids.update(
        str(identity)
        for entry in entries
        for identity in entry.get("covered_disclosure_ids", ())
    )
    compact.extend(
        f"Selected disclosure: {disclosure_text(read.disclosures[identity])}"
        for identity in sorted(disclosure_ids)
        if identity in read.disclosures
    )
    result = section("analysis", "Analysis evidence", compact)
    result.update(
        full_evidence=full_text,
        full_token_count=count_tokens(full_text),
        history_matches_preview=matches,
        analysis_budget=budget,
        history_budget=history_budget,
        boundary_message_id=boundary,
        selected_boundary_message_id=selected_boundary,
    )
    return result


async def character_context_review(scene, character):
    conversation = get_agent("conversation")
    summarizer = get_agent("summarizer")
    diagnostics = ContextDiagnostics()
    preview = await conversation.history_context(
        character,
        conversation.client.max_token_length,
        preview=True,
        diagnostics=diagnostics,
    )
    history_tokens = preview["summary"]["total_tokens"]
    perspective = await conversation.knowledge_perspective(character)
    perception = character_knowledge_enabled(scene)
    preview["perspective"] = character.name
    preview["history_perspective"] = perspective
    preview["knowledge_mode"] = scene.knowledge_eligibility

    if summarizer.analyze_scene and summarizer.analyze_scene_for_conversation:
        if perception:
            preview["sections"].append(
                _analysis_review_section(scene, character, preview, summarizer)
            )
        cached = await summarizer.get_cached_analysis("conversation", character)
        preview["sections"].append(section("analysis", "Cached analysis", [cached]))
    preview["exclusions"] = diagnostics.samples
    preview["exclusion_counts"] = dict(diagnostics.counts)
    preview["exclusion_total"] = sum(diagnostics.counts.values())
    preview["summary"]["history_tokens"] = history_tokens
    preview["summary"]["total_tokens"] = sum(
        item["token_count"] for item in preview["sections"]
    )
    preview["summary"]["knowledge_tokens"] = (
        preview["summary"]["total_tokens"] - history_tokens
    )
    preview["scene_id"] = scene.id
    return preview
