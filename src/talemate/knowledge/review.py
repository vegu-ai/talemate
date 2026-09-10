"""Author-facing inspection of the same evidence used by character prompts."""

from talemate.instance import get_agent
from talemate.knowledge.advice import advice_context
from talemate.knowledge.diagnostics import ContextDiagnostics
from talemate.knowledge.chronology import (
    fact_chronology,
    chronology_settings,
    superseded_fact_ids,
)
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.standard_analysis import (
    _bounded_lines,
    standard_analysis_context,
    standard_analysis_enabled,
)
from talemate.knowledge.topics import known_bucket, known_facts
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


def fact_exclusions(scene, known, diagnostics):
    visible = {fact.id: fact for fact in known}
    superseded = superseded_fact_ids(scene, superseders=known)
    settings = chronology_settings(scene)
    for canonical in scene.world_state.facts.values():
        fact = visible.get(canonical.id)
        if fact is None:
            diagnostics.exclude(
                "fact", canonical.id, canonical.text, "not_in_audience", "Known facts"
            )
        elif fact.id in superseded:
            diagnostics.exclude("fact", fact.id, fact.text, "superseded", "Known facts")
        elif not fact_chronology(scene, fact, settings).eligible:
            diagnostics.exclude(
                "fact", fact.id, fact.text, "chronology_floor", "Known facts"
            )


async def character_context_review(scene, character, overrides=None):
    conversation = get_agent("conversation")
    summarizer = get_agent("summarizer")
    diagnostics = ContextDiagnostics()
    preview = await conversation.history_context(
        character,
        conversation.client.max_token_length,
        preview=True,
        overrides=overrides,
        diagnostics=diagnostics,
    )
    history_tokens = preview["summary"]["total_tokens"]
    budget = preview["budget"]["total"]
    perspective = await conversation.knowledge_perspective(character)
    perception = character_knowledge_enabled(scene)
    preview["perspective"] = character.name
    preview["history_perspective"] = perspective
    preview["knowledge_mode"] = scene.knowledge_eligibility

    if perception or conversation.character_knowledge_enabled:
        entry_context = conversation.character_entry_context(character)
        if entry_context:
            preview["sections"].append(
                section(
                    "knowledge",
                    "Character entry orientation",
                    [entry_context],
                )
            )
        bucket = known_bucket(scene, character.name)
        fact_exclusions(scene, bucket, diagnostics)
        known, _ = known_facts(
            scene, character.name, limit=len(scene.world_state.facts), known=bucket
        )
        lines = _bounded_lines(
            scene,
            known,
            budget // 3,
            false_ids={fact.id for fact in bucket if fact.false},
            diagnostics=diagnostics,
        )
        preview["sections"].append(
            section("knowledge", "Known facts (eligible)", lines)
        )
        absence = await conversation.absence_block(character)
        preview["sections"].append(
            section("knowledge", "Unknown fact reminders", absence)
        )
    if summarizer.analyze_scene and summarizer.analyze_scene_for_conversation:
        if perception:
            evidence = advice_context(
                scene, character, summarizer.client.max_token_length // 2
            )
            text = Prompt.get(
                "common.character-evidence-context",
                vars={"scene": scene, "evidence": evidence},
            ).render()
            preview["sections"].append(section("analysis", "Analysis evidence", [text]))
        elif standard_analysis_enabled(scene, character, "conversation"):
            evidence = await standard_analysis_context(
                scene, character, summarizer.client.max_token_length // 2
            )
            if evidence:
                preview["sections"].append(
                    section("analysis", "Analysis fact inputs", [evidence["text"]])
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
    return preview
