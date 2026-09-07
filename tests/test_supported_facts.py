import json
from copy import deepcopy
from pathlib import Path

from unittest.mock import AsyncMock, Mock

from _node_test_helpers import run_node

import pytest

from talemate.character import Character
from talemate.context import ActiveScene
from talemate.export import ExportOptions, scene_export_json
from talemate.game.engine.nodes.knowledge import CurrentState, RelationshipTimeline
from talemate.history import ArchiveEntry, HistoryEntry
from talemate.instance import get_agent
from talemate.knowledge.facts import drop_facts_for_entries, prune_serialized_facts
from talemate.knowledge.graph import (
    bucket,
    current_state,
    facts_about,
    relationship_timeline,
    superseded_chain,
)
from talemate.knowledge.perspectives import (
    add_disclosure,
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.knowledge.schema import Fact, KnowledgeEdge, ParsedFact, Topic
from talemate.knowledge.topics import coverage, awareness_line
from talemate.knowledge.supported_facts import replace_source_facts
from talemate.load import load_scene_from_data
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage
from talemate.tale_mate import Actor, Scene


@pytest.fixture
def supported_scene(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    scene.history = []
    scene.archived_history = []
    scene.layered_history = []
    for name in ("Alice", "Bob"):
        character = Character(name=name, is_player=name == "Alice")
        actor = Actor(character, get_agent("conversation"))
        actor.scene = scene
        scene.actors.append(actor)
        scene.character_data[name] = character
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")
    summarizer.connect(scene)
    summarizer.actions["archive"].config["extract_facts"].value = True
    monkeypatch.setattr(summarizer, "schedule_audience_summaries", AsyncMock())
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="cancel")
    )
    memory = get_agent("memory")
    for name in (
        "add_many",
        "delete",
        "compare_strings",
        "compare_string_lists",
        "get",
    ):
        monkeypatch.setattr(memory, name, AsyncMock(), raising=False)
    with ActiveScene(scene):
        yield scene, summarizer, memory


def passage(scene, text, audience=("Alice",), ts=1):
    scene.ts = ts
    message = NarratorMessage(message=text)
    scene.history.append(message)
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [{"audience": audience, "status": "ready", "text": text}],
    )
    return message, select_character_view(
        scene, source_reference(scene, "message", message.id), audience[0]
    ).source


async def store(scene, source, audience, text, **kwargs):
    return await replace_source_facts(
        scene, [(source, audience, [ParsedFact(text=text, **kwargs)])]
    )


@pytest.mark.asyncio
async def test_later_disclosure_survives_early_source_regeneration_on_real_graph(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    text = "On 2026-09-01 Alice hid the ledger under the bed."
    early, early_source = passage(scene, text, ts=10)
    await store(
        scene,
        early_source,
        ("Alice",),
        text,
        time_scope="2026-09-01",
        subjects=["ledger"],
    )
    scene.ts = 20
    disclosure = add_disclosure(scene, text, ("Bob",), provenance=(early_source,))
    disclosed_source = source_reference(scene, "disclosure", disclosure.id)
    await store(
        scene,
        disclosed_source,
        ("Bob",),
        text,
        time_scope="2026-09-01",
        subjects=["ledger"],
    )
    assert len(scene.world_state.facts) == 2
    assert all(
        len(fact.contributions) == 1 for fact in scene.world_state.facts.values()
    )
    assert current_state(scene, "ledger", character="Bob").text == text
    bob_support = current_state(scene, "ledger", character="Bob").contributions

    changed = "On 2026-09-01 Alice hid the ledger in the attic."
    scene.edit_message(early.id, changed)
    set_source_perspectives(
        scene,
        "message",
        early.id,
        [{"audience": ["Alice"], "status": "ready", "text": changed}],
    )
    extract = AsyncMock(
        return_value=(
            changed,
            [ParsedFact(text=changed, time_scope="2026-09-01", subjects=["ledger"])],
        )
    )
    monkeypatch.setattr(summarizer, "summarize", extract)
    assert await summarizer.rebuild_supported_facts(scene, [early_source]) == "ok"
    extract.assert_awaited_once()
    assert extract.call_args.kwargs["audience"] == ("Alice",)
    assert current_state(scene, "ledger", character="Alice").text == changed
    assert current_state(scene, "ledger", character="Bob").text == text
    assert current_state(scene, "ledger", character="Bob").contributions == bob_support
    scene.delete_message(early.id)
    assert current_state(scene, "ledger", character="Alice") is None
    assert current_state(scene, "ledger", character="Bob").contributions == bob_support
    assert scene.knowledge.disclosures == (disclosure,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "texts",
    [
        ("Alice possesses the key.", "Alice possessed the key before losing it."),
        ("Alice says Bob owns the key.", "Bob owns the key."),
        ("Bob may hold the key.", "Bob holds the key."),
    ],
)
async def test_similar_distinctions_do_not_collapse_on_real_graph(
    supported_scene, texts
):
    scene, _, memory = supported_scene
    _, source = passage(scene, " ".join(texts), ("Bob",))
    await replace_source_facts(
        scene,
        [
            (
                source,
                ("Bob",),
                [ParsedFact(text=text, subjects=["key"]) for text in texts],
            )
        ],
    )
    assert {fact.text for fact in facts_about(scene, "key", character="Bob")} == set(
        texts
    )
    assert len(bucket(scene, "Bob")) == 2
    memory.compare_strings.assert_not_awaited()
    memory.compare_string_lists.assert_not_awaited()


@pytest.mark.asyncio
async def test_unanchored_identical_words_at_different_events_stay_separate(
    supported_scene,
):
    scene, _, _ = supported_scene
    text = "Alice possesses the key."
    for ts in (10, 20):
        _, source = passage(scene, text, ("Bob",), ts)
        await store(scene, source, ("Bob",), text)
    assert len(facts_about(scene, "key", character="Bob")) == 2


@pytest.mark.asyncio
async def test_exact_same_source_views_combine_and_ignore_model_audience(
    supported_scene,
):
    scene, _, _ = supported_scene
    message, _ = passage(scene, "Alice owns the key.")
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": [name], "status": "ready", "text": message.message}
            for name in ("Alice", "Bob")
        ],
    )
    for name in ("Alice", "Bob"):
        source = select_character_view(
            scene, source_reference(scene, "message", message.id), name
        ).source
        await store(
            scene,
            source,
            (name,),
            message.message,
            known_by=["INVENTED"],
            subjects=["key"],
        )
    assert len(scene.world_state.facts) == 1
    fact = next(iter(scene.world_state.facts.values()))
    assert len(fact.contributions) == 2
    assert fact.present == ["Alice", "Bob"]
    assert not scene.world_state.knowledge


@pytest.mark.asyncio
async def test_global_updates_do_not_replace_character_last_known_evidence(
    supported_scene,
):
    scene, _, _ = supported_scene
    _, old_source = passage(scene, "The ledger is under the bed.", ("Bob",), 10)
    old = (
        await store(
            scene,
            old_source,
            ("Bob",),
            "The ledger is under the bed.",
            subjects=["ledger"],
        )
    )[0]
    _, hidden_source = passage(
        scene, "Alice moved the ledger to the cabinet.", ("Alice",), 20
    )
    latest = (
        await store(
            scene,
            hidden_source,
            ("Alice",),
            "Alice moved the ledger to the cabinet.",
            subjects=["ledger"],
        )
    )[0]
    scene.world_state.facts[latest.id].supersedes = old.id
    scene.world_state.facts[old.id].false = True
    scene.world_state.facts[
        old.id
    ].text = "AUTHOR CORRECTION: the ledger is in the cabinet."
    scene.world_state.facts[old.id].subjects = ["cabinet"]
    assert current_state(scene, "ledger").id == latest.id
    known = current_state(scene, "ledger", character="Bob")
    assert known.id == old.id and not known.false
    assert known.text == "The ledger is under the bed."
    assert known.ts == 10
    assert [fact.id for fact in facts_about(scene, "bed", character="Bob")] == [old.id]
    assert relationship_timeline(scene, "ledger", "cabinet", character="Bob") == []

    _, witnessed = passage(scene, "Bob sees the ledger in the cabinet.", ("Bob",), 30)
    await store(
        scene,
        witnessed,
        ("Bob",),
        "Bob sees the ledger in the cabinet.",
        supersedes=old.id,
        subjects=["ledger"],
    )
    updated = current_state(scene, "ledger", character="Bob")
    assert updated.ts == 30 and updated.supersedes == old.id
    assert updated.contributions[0].acquired.ts == 30
    assert updated.text == "Bob sees the ledger in the cabinet."


@pytest.mark.asyncio
async def test_failed_multi_source_rebuild_publishes_no_partial_success(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    sources = []
    for text in ("Alice owns a key.", "Alice owns a book."):
        _, source = passage(scene, text)
        await store(scene, source, ("Alice",), text)
        sources.append(source)
    before = deepcopy(scene.world_state.facts)
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            side_effect=[
                ("New summary", [ParsedFact(text="New fact")]),
                ("No facts", None),
            ]
        ),
    )
    assert await summarizer.rebuild_supported_facts(scene, sources) == "failed"
    assert scene.world_state.facts == before
    summarizer.client._prompt_generation_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_source_changed_during_extraction_discards_response(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    message, source = passage(scene, "Alice owns a key.")

    async def request(*args, **kwargs):
        scene.edit_message(message.id, "Alice lost the key.")
        return "Stale summary", [ParsedFact(text="Alice owns a key.")]

    monkeypatch.setattr(summarizer, "summarize", request)
    assert await summarizer.rebuild_supported_facts(scene, [source]) == "failed"
    assert not scene.world_state.facts


@pytest.mark.asyncio
async def test_empty_extraction_replaces_only_requested_support(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    _, first = passage(scene, "Alice owns a key.")
    _, other = passage(scene, "Bob owns a book.", ("Bob",))
    await store(scene, first, ("Alice",), "Alice owns a key.")
    await store(scene, other, ("Bob",), "Bob owns a book.")
    before = current_state(scene, "book", character="Bob")
    extract = AsyncMock(return_value=("No durable facts", []))
    monkeypatch.setattr(summarizer, "summarize", extract)
    assert await summarizer.rebuild_supported_facts(scene, [first]) == "ok"
    extract.assert_awaited_once()
    assert current_state(scene, "key", character="Alice") is None
    assert current_state(scene, "book", character="Bob") == before


@pytest.mark.asyncio
async def test_real_summary_request_inherits_only_its_audience(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    _, secret = passage(scene, "PRIVATE: Alice hides a diamond.")
    await store(scene, secret, ("Alice",), "PRIVATE: Alice hides a diamond.")
    _, source = passage(scene, "Bob hears Alice claim the ledger burned.", ("Bob",))
    prompts = []

    async def request(uid, client, kind, **kwargs):
        prompts.append(str(Prompt.get(uid, vars=kwargs["vars"])))
        return "SUMMARY: Bob hears a claim.", {
            "summary": "Bob hears a claim.",
            "facts": '[{"text":"Alice claims the ledger burned.","subjects":["ledger"],"known_by":["Alice"]}]',
        }

    monkeypatch.setattr(Prompt, "request", request)
    assert await summarizer.rebuild_supported_facts(scene, [source]) == "ok"
    assert len(prompts) == 1 and "PRIVATE" not in prompts[0]
    assert "time_scope" in prompts[0]
    assert (
        current_state(scene, "ledger", character="Bob").text
        == "Alice claims the ledger burned."
    )
    assert current_state(scene, "ledger", character="Alice") is None


@pytest.mark.asyncio
async def test_saved_sources_rebuild_after_fact_ids_are_discarded(
    supported_scene, tmp_path, monkeypatch
):
    scene, summarizer, memory = supported_scene
    text = "On 2026-09-01 Alice hid the ledger under the bed."
    _, source = passage(scene, text, ts=10)
    await store(scene, source, ("Alice",), text, time_scope="2026-09-01")
    scene.ts = 20
    disclosure = add_disclosure(scene, text, ("Bob",))
    await store(
        scene,
        source_reference(scene, "disclosure", disclosure.id),
        ("Bob",),
        text,
        time_scope="2026-09-01",
    )
    original = json.loads(scene.json)
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    monkeypatch.setattr(memory, "set_db", AsyncMock(), raising=False)
    monkeypatch.setattr(memory, "close_db", Mock(), raising=False)
    monkeypatch.setattr(
        memory, "get_document", AsyncMock(return_value={}), raising=False
    )
    await load_scene_from_data(scene, deepcopy(original), name="supported-facts.json")
    await scene.save()
    saved = json.loads((Path(scene.save_dir) / "supported-facts.json").read_text())
    assert saved["world_state"]["facts"] == original["world_state"]["facts"]
    assert saved["knowledge"] == original["knowledge"]
    scene.world_state.facts = {}
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=(text, [ParsedFact(text=text, time_scope="2026-09-01")])
        ),
    )
    assert await summarizer.rebuild_supported_facts(scene) == "ok"
    assert current_state(scene, "ledger", character="Alice").text == text
    assert current_state(scene, "ledger", character="Bob").text == text
    assert {
        item.acquired.ts
        for fact in scene.world_state.facts.values()
        for item in fact.contributions
    } == {10, 20}


@pytest.mark.asyncio
async def test_pruning_archive_keeps_independent_disclosure(supported_scene):
    scene, _, _ = supported_scene
    text = "On 2026-09-01 Alice hid the ledger."
    _, source = passage(scene, text)
    entry = ArchiveEntry(id="archive", text=text, start=0, end=0)
    scene.archived_history = [entry.model_dump(exclude_none=True)]
    set_source_perspectives(
        scene,
        "summary",
        entry.id,
        [{"audience": ["Alice"], "status": "ready", "text": text, "sources": [source]}],
    )
    summary_source = select_character_view(
        scene, source_reference(scene, "summary", entry.id), "Alice"
    ).source
    await store(scene, summary_source, ("Alice",), text, time_scope="2026-09-01")
    disclosure = add_disclosure(scene, text, ("Bob",))
    await store(
        scene,
        source_reference(scene, "disclosure", disclosure.id),
        ("Bob",),
        text,
        time_scope="2026-09-01",
    )
    exported = scene.world_state.model_dump(mode="json")
    assert len(prune_serialized_facts(exported, {entry.id})) == 1
    assert len(next(iter(exported["facts"].values()))["contributions"]) == 1
    await drop_facts_for_entries(scene, {entry.id})
    assert current_state(scene, "ledger", character="Alice") is None
    assert current_state(scene, "ledger", character="Bob").text == text


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [False, True])
async def test_base_summary_extracts_facts_in_existing_audience_call(
    supported_scene, monkeypatch, malformed
):
    scene, summarizer, _ = supported_scene
    text = "Alice says Bob once possessed the key; Bob is unsure who holds it now."
    passage(scene, text, ("Alice", "Bob"))
    entry = ArchiveEntry(
        id="base", text="Reader summary with PRIVATE prose", start=0, end=0
    )
    scene.archived_history = [entry.model_dump(exclude_none=True)]
    prompts = []

    async def request(uid, client, kind, **kwargs):
        prompts.append(str(Prompt.get(uid, vars=kwargs["vars"])))
        return "SUMMARY: " + text, {
            "summary": text,
            "facts": "invalid"
            if malformed
            else json.dumps(
                [
                    {
                        "text": "Alice says Bob once possessed the key.",
                        "subjects": ["key"],
                    },
                    {
                        "text": "Bob is unsure who holds the key now.",
                        "subjects": ["key"],
                    },
                ]
            ),
        }

    monkeypatch.setattr(Prompt, "request", request)
    await summarizer.ensure_summary_views(scene, "base")
    assert len(prompts) == 1
    assert "PRIVATE" not in prompts[0]
    assert scene.archived_history[0]["text"] == entry.text
    assert scene.archived_history[0]["facts_status"] == (
        "failed" if malformed else "ok"
    )
    view = select_character_view(
        scene, source_reference(scene, "summary", "base"), "Alice"
    )
    assert view.status == "ready"
    assert view.text == text
    if malformed:
        assert not scene.world_state.facts
        summarizer.client._prompt_generation_error.assert_awaited_once()
    else:
        assert len(facts_about(scene, "key", character="Bob")) == 2
        assert all(
            fact.contributions[0].source.kind == "summary"
            for fact in scene.world_state.facts.values()
        )
        request_count = len(prompts)
        await summarizer.ensure_summary_views(scene, "base")
        assert len(prompts) == request_count
        monkeypatch.setattr(
            summarizer, "summarize", AsyncMock(return_value=(text, None))
        )
        before = deepcopy(scene.world_state.facts)
        assert (
            await summarizer.regenerate_facts(
                HistoryEntry(**entry.model_dump(), index=0, layer=0)
            )
            == "failed"
        )
        assert scene.world_state.facts == before
        assert scene.archived_history[0]["facts_status"] == "failed"


@pytest.mark.asyncio
async def test_rename_and_remove_preserve_other_audience_members(supported_scene):
    scene, summarizer, _ = supported_scene
    text = "Alice and Bob see the key."
    _, source = passage(scene, text, ("Alice", "Bob"))
    await store(scene, source, ("Alice", "Bob"), text)
    scene.character_data["Alice"].rename("Cara")
    assert current_state(scene, "key", character="Cara").text == text
    await scene.remove_character(scene.character_data["Cara"], purge_from_memory=False)
    assert current_state(scene, "key", character="Bob").text == text
    assert next(iter(scene.world_state.facts.values())).contributions[0].audience == (
        "Bob",
    )
    scene.character_data["Cara"] = Character(name="Cara")
    assert current_state(scene, "key", character="Cara") is None
    await summarizer.flush_fact_memory(scene)


@pytest.mark.asyncio
async def test_reset_export_remove_source_index_but_keep_manual_facts(supported_scene):
    scene, _, _ = supported_scene
    _, source = passage(scene, "Alice has a key.")
    await store(scene, source, ("Alice",), "Alice has a key.")
    disclosure = add_disclosure(scene, "Bob owns a book.", ("Bob",))
    await store(
        scene,
        source_reference(scene, "disclosure", disclosure.id),
        ("Bob",),
        "Bob owns a book.",
    )
    scene.world_state.facts["manual"] = Fact(
        id="manual", text="An authored detail", source="manual"
    )
    before = deepcopy(scene.world_state.facts)
    exported = json.loads(scene_export_json(scene, ExportOptions(name="Reset copy")))
    assert set(exported["world_state"]["facts"]) == {"manual"}
    assert scene.world_state.facts == before
    removed = scene.reset()
    assert removed == set(before) - {"manual"}
    assert set(scene.world_state.facts) == {"manual"}


@pytest.mark.asyncio
async def test_hidden_passage_does_not_survive_via_fact_index(supported_scene):
    scene, _, _ = supported_scene
    message, source = passage(scene, "Bob holds the key.", ("Bob",))
    await store(scene, source, ("Bob",), message.message)
    message.hide()
    assert facts_about(scene, "key", character="Bob") == []
    assert facts_about(scene, "key")


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["Monday", "yesterday"])
async def test_relative_time_does_not_merge_across_sources(supported_scene, scope):
    scene, _, _ = supported_scene
    text = f"Alice held the key {scope}."
    for ts in (1, 2):
        _, source = passage(scene, text, ts=ts)
        await store(scene, source, ("Alice",), text, time_scope=scope)
    assert len(scene.world_state.facts) == 2


@pytest.mark.asyncio
async def test_unsupported_time_scope_is_dropped_without_losing_fact(supported_scene):
    scene, _, _ = supported_scene
    _, source = passage(scene, "Alice held the key on September 1, 2026.")
    fact = (
        await store(
            scene,
            source,
            ("Alice",),
            "Alice held the key on September 1, 2026.",
            time_scope="2026-09-01",
        )
    )[0]
    assert fact.contributions[0].time_scope is None
    assert fact.text == "Alice held the key on September 1, 2026."


@pytest.mark.asyncio
async def test_graph_nodes_have_explicit_character_scope(supported_scene):
    scene, _, _ = supported_scene
    for text, audience, ts in [
        ("Bob sees Alice hold the key.", ("Bob",), 1),
        ("Alice secretly hides the key.", ("Alice",), 2),
    ]:
        _, source = passage(scene, text, audience, ts)
        await store(scene, source, audience, text)
    author = await run_node(CurrentState(), scene=scene, inputs={"entity": "key"})
    actor = await run_node(
        CurrentState(), scene=scene, inputs={"entity": "key", "character": "Bob"}
    )
    timeline = await run_node(
        RelationshipTimeline(),
        scene=scene,
        inputs={"a": "Alice", "b": "key", "character": "Bob"},
    )
    assert "secretly" in author["text"]
    assert actor["text"] == "Bob sees Alice hold the key."
    assert len(timeline["facts"]) == 1
    assert timeline["facts"][0]["text"] == actor["text"]


@pytest.mark.asyncio
async def test_late_archive_creation_cannot_reorder_learning(supported_scene):
    scene, _, _ = supported_scene
    _, source = passage(scene, "Bob sees the key under the bed.", ("Bob",), 10)
    scene.ts = 20
    disclosure = add_disclosure(
        scene, "Alice tells Bob she moved the key to the cabinet.", ("Bob",)
    )
    await store(
        scene,
        source_reference(scene, "disclosure", disclosure.id),
        ("Bob",),
        disclosure.text,
    )
    scene.ts = 30
    entry = ArchiveEntry(
        id="late-base", text="The key was under the bed.", start=0, end=0, ts=10
    )
    scene.archived_history = [entry.model_dump(exclude_none=True)]
    set_source_perspectives(
        scene,
        "summary",
        entry.id,
        [
            {
                "audience": ["Bob"],
                "status": "ready",
                "text": entry.text,
                "sources": [source],
            }
        ],
    )
    summary = select_character_view(
        scene, source_reference(scene, "summary", entry.id), "Bob"
    )
    assert summary.acquired.ts == 30
    fact = (
        await store(scene, summary.source, ("Bob",), "Bob sees the key under the bed.")
    )[0]
    assert fact.contributions[0].acquired.ts == 10
    assert current_state(scene, "key", character="Bob").text == disclosure.text


@pytest.mark.asyncio
async def test_switching_scene_during_fact_extraction_cannot_publish(
    supported_scene, monkeypatch
):
    scene, summarizer, memory = supported_scene
    _, source = passage(scene, "Alice holds the key.")

    async def request(*args, **kwargs):
        summarizer.scene = None
        return "Summary", [ParsedFact(text="Alice holds the key.")]

    monkeypatch.setattr(summarizer, "summarize", request)
    assert await summarizer.rebuild_supported_facts(scene, [source]) == "failed"
    assert not scene.world_state.facts
    memory.add_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_date_occurrences_and_cycle_guard(supported_scene):
    scene, _, _ = supported_scene
    sources, ids = [], []
    for state in ("open", "closed", "open"):
        text = f"On 2026-09-01 the vault is {state}."
        disclosure = add_disclosure(scene, text, ("Alice",))
        source = source_reference(scene, "disclosure", disclosure.id)
        fact = (
            await store(
                scene,
                source,
                ("Alice",),
                text,
                time_scope="2026-09-01",
                supersedes=ids[-1] if ids else None,
            )
        )[0]
        sources.append(source)
        ids.append(fact.id)
    assert len(set(ids)) == 3
    for character in (None, "Alice"):
        assert current_state(scene, "vault", character=character).id == ids[-1]
        assert [
            fact.id for fact in superseded_chain(scene, ids[-1], character=character)
        ] == ids[-2::-1]
    # Reanalysing the first occurrence cannot close the existing chain.
    text = scene.world_state.facts[ids[0]].text
    for target in (ids[-1], ids[0]):
        await store(
            scene,
            sources[0],
            ("Alice",),
            text,
            time_scope="2026-09-01",
            supersedes=target,
        )
        assert scene.world_state.facts[ids[0]].supersedes is None
        assert scene.world_state.facts[ids[0]].contributions[0].supersedes is None
        assert current_state(scene, "vault", character="Alice").id == ids[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("bob_status", [None, "failed", "pending"])
async def test_full_rebuild_covers_each_passage_audience(
    supported_scene, monkeypatch, shared, bob_status
):
    scene, summarizer, _ = supported_scene
    message, source = passage(scene, "Alice and Bob see the key.", ("Alice", "Bob"))
    if not shared:
        set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {"audience": [name], "status": "ready", "text": f"{name} sees the key."}
                for name in ("Alice", "Bob")
            ],
        )
        source = select_character_view(
            scene, source_reference(scene, "message", message.id), "Alice"
        ).source
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    views = [
        {
            "audience": ["Alice"],
            "status": "ready",
            "text": "Alice sees the key.",
            "sources": [source],
        }
    ]
    if bob_status:
        views.append({"audience": ["Bob"], "status": bob_status})
    set_source_perspectives(scene, "summary", "base", views)

    async def summarize(text, **kwargs):
        return text, [ParsedFact(text=text)]

    monkeypatch.setattr(summarizer, "summarize", summarize)
    assert await summarizer.rebuild_supported_facts(scene) == "ok"
    for name in ("Alice", "Bob"):
        assert current_state(scene, "key", character=name) is not None
    assert any(
        item.source.kind == "message" and "Bob" in item.audience
        for fact in scene.world_state.facts.values()
        for item in fact.contributions
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_failed_memory_write_is_retried_after_canonical_publication(
    supported_scene, monkeypatch, empty
):
    scene, summarizer, memory = supported_scene
    _, source = passage(scene, "Alice has the key.")
    old = (await store(scene, source, ("Alice",), "Alice has the key."))[0]
    operation = memory.delete if empty else memory.add_many
    operation.reset_mock()
    operation.side_effect = [RuntimeError("memory unavailable"), None]
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=("Summary", [] if empty else [ParsedFact(text=old.text)])
        ),
    )
    assert await summarizer.rebuild_supported_facts(scene, [source]) == "failed"
    assert old.id in summarizer._fact_memory_dirty[scene]
    assert await summarizer.rebuild_supported_facts(scene, [source]) == "ok"
    assert operation.await_count == 2
    assert not summarizer._fact_memory_dirty[scene]
    if empty:
        assert operation.call_args.args[0] == {"ids": [old.id]}
        assert not scene.world_state.facts


@pytest.mark.asyncio
async def test_replacement_preserves_ids_and_cleans_deleted_links(supported_scene):
    scene, _, _ = supported_scene
    message, source = passage(scene, "Alice opens the vault.")
    first = (await store(scene, source, ("Alice",), message.message))[0]
    _, later = passage(scene, "Alice closes the vault.", ts=2)
    second = (
        await store(
            scene, later, ("Alice",), "Alice closes the vault.", supersedes=first.id
        )
    )[0]
    scene.world_state.knowledge.append(
        KnowledgeEdge(character="Bob", target=first.id, kind="grant")
    )
    await store(scene, source, ("Alice",), message.message)
    assert [
        fact.id for fact in superseded_chain(scene, second.id, character="Alice")
    ] == [first.id]
    assert scene.world_state.knowledge[0].target == first.id
    await replace_source_facts(scene, [(source, ("Alice",), [])])
    assert not scene.world_state.knowledge
    second = scene.world_state.facts[second.id]
    assert second.supersedes is None
    assert second.contributions[0].supersedes is None
    assert superseded_chain(scene, second.id, character="Alice") == []


@pytest.mark.asyncio
async def test_rename_preserves_author_edits_on_related_and_unrelated_facts(
    supported_scene,
):
    scene, _, _ = supported_scene
    from talemate.knowledge.rename import rename_knowledge_references

    before = {}
    for name in ("Alice", "Bob"):
        _, source = passage(scene, f"{name} has a key.", (name,))
        fact = (await store(scene, source, (name,), f"{name} has a key."))[0]
        fact.text = "AUTHOR CORRECTION"
        fact.subjects = ["authored subject"]
        fact.known_by = {"Bob": "granted"}
        before[name] = fact.model_copy(deep=True)
    rename_knowledge_references(scene, "Alice", "Cara")
    assert scene.world_state.facts[before["Bob"].id] == before["Bob"]
    related = scene.world_state.facts[before["Alice"].id]
    assert related.text == "AUTHOR CORRECTION"
    assert related.subjects == ["authored subject"]
    assert related.known_by == {"Bob": "granted"}
    assert related.present == ["Cara"]
    assert related.contributions[0].audience == ("Cara",)


@pytest.mark.asyncio
async def test_bare_source_replacement_including_empty(supported_scene):
    scene, _, _ = supported_scene
    message, source = passage(scene, "Alice has the key.")
    await store(scene, source, ("Alice",), message.message)
    bare = source_reference(scene, "message", message.id)
    await store(scene, bare, ("Alice",), "Alice may have the key.")
    assert len(scene.world_state.facts) == 1
    assert (
        current_state(scene, "key", character="Alice").text == "Alice may have the key."
    )
    await replace_source_facts(scene, [(bare, ("Alice",), [])])
    assert not scene.world_state.facts


def test_scoped_legacy_chain_is_rejected(scene):
    scene.world_state.facts = {
        "F1": Fact(id="F1", text="Key"),
        "F2": Fact(id="F2", text="Key moved", supersedes="F1"),
    }
    assert [fact.id for fact in superseded_chain(scene, "F2")] == ["F1"]
    with pytest.raises(ValueError, match="require perception mode"):
        superseded_chain(scene, "F2", character="Alice")


@pytest.mark.asyncio
async def test_empty_character_node_sockets_mean_global(supported_scene):
    scene, _, _ = supported_scene
    _, source = passage(scene, "Alice has a key.")
    await store(scene, source, ("Alice",), "Alice has a key.")
    for node, inputs in [
        (CurrentState, {"entity": "key"}),
        (RelationshipTimeline, {"a": "Alice", "b": "key"}),
    ]:
        assert await run_node(
            node(), scene=scene, inputs={**inputs, "character": ""}
        ) == await run_node(node(), scene=scene, inputs=inputs)


@pytest.mark.asyncio
async def test_scene_switch_preserves_memory_obligation_without_cancellation(
    supported_scene, monkeypatch
):
    scene, summarizer, memory = supported_scene
    _, source = passage(scene, "Alice has a key.")

    async def switch(*args):
        summarizer.scene = None

    memory.add_many.side_effect = switch
    facts = await store(scene, source, ("Alice",), "Alice has a key.")
    assert summarizer._fact_memory_dirty[scene] == {facts[0].id}
    assert await summarizer.flush_fact_memory(scene) is False
    summarizer.client._prompt_generation_error.assert_not_awaited()
    memory.add_many.side_effect = None
    summarizer.scene = scene
    assert await summarizer.flush_fact_memory(scene) is True
    assert not summarizer._fact_memory_dirty[scene]
    assert memory.add_many.await_count == 2


@pytest.mark.asyncio
async def test_good_sibling_summary_cannot_clear_failed_fact_status(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    message, _ = passage(scene, "Reader text", ("Alice", "Bob"))
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": [name], "status": "ready", "text": f"{name} has a key."}
            for name in ("Alice", "Bob")
        ],
    )
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]

    async def summarize(text, **kwargs):
        return text, None if kwargs["audience"] == ("Alice",) else [
            ParsedFact(text=text)
        ]

    monkeypatch.setattr(summarizer, "summarize", summarize)
    await summarizer.ensure_summary_views(scene, "base", audiences=["Alice"])
    assert scene.archived_history[0]["facts_status"] == "failed"
    await summarizer.ensure_summary_views(scene, "base", audiences=["Bob"])
    assert scene.archived_history[0]["facts_status"] == "failed"
    for name in ("Alice", "Bob"):
        assert (
            select_character_view(
                scene, source_reference(scene, "summary", "base"), name
            ).status
            == "ready"
        )
    assert current_state(scene, "key", character="Alice") is None
    assert current_state(scene, "key", character="Bob") is not None


@pytest.mark.asyncio
async def test_background_scene_switch_requeues_without_cancelled_status(
    supported_scene, monkeypatch
):
    scene, summarizer, memory = supported_scene
    import talemate.status as status

    emitted = Mock()
    monkeypatch.setattr(status, "emit", emitted)
    _, source = passage(scene, "Alice has a key.")
    fact = (await store(scene, source, ("Alice",), "Alice has a key."))[0]
    summarizer._fact_memory_dirty.setdefault(scene, set()).add(fact.id)

    async def switch(*args):
        summarizer.scene = None

    memory.add_many.side_effect = switch
    task = await summarizer.rebuild_audience_summaries(scene)
    await task
    assert summarizer._fact_memory_dirty[scene] == {fact.id}
    assert not any("Cancelled" in str(call) for call in emitted.call_args_list)
    memory.add_many.side_effect = None
    summarizer.scene = scene
    assert await summarizer.flush_fact_memory(scene)


@pytest.mark.asyncio
async def test_time_scope_flows_through_real_prompt_and_response(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    text = "On 2026-09-01 Alice holds the key."
    _, source = passage(scene, text)
    prompts = []

    async def send(prompt, **kwargs):
        prompt = str(prompt)
        prompts.append(prompt)
        example = prompt.split("One object per fact:", 1)[1].split("Facts only:", 1)[0]
        assert '"time_scope"' in example
        assert "null" in example
        assert '"known_by"' not in example
        return (
            "SUMMARY: "
            + text
            + "\n<FACTS>\n"
            + json.dumps(
                [
                    {
                        "text": text,
                        "subjects": ["key"],
                        "time_scope": "2026-09-01",
                        "supersedes": None,
                    }
                ]
            )
            + "\n</FACTS>"
        )

    monkeypatch.setattr(summarizer.client, "send_prompt", send)
    assert await summarizer.rebuild_supported_facts(scene, [source]) == "ok"
    assert len(prompts) == 1
    fact = current_state(scene, "key", character="Alice")
    assert fact.contributions[0].time_scope == "2026-09-01"


@pytest.mark.asyncio
async def test_global_false_current_state_keeps_author_semantics(supported_scene):
    scene, _, _ = supported_scene
    _, source = passage(scene, "Alice has a key.")
    fact = (await store(scene, source, ("Alice",), "Alice has a key."))[0]
    fact.false = True
    fact.text = "AUTHOR: Alice never had a key."
    assert current_state(scene, "key") == fact
    assert current_state(scene, "key", character="Alice").text == "Alice has a key."
    assert current_state(scene, "key", character="Alice").false is False


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["facts", "bucket", "previous"])
async def test_scoped_fact_loops_share_coverage_cache(
    supported_scene, monkeypatch, query
):
    from talemate.knowledge import supported_facts

    scene, _, _ = supported_scene
    _, source = passage(scene, "Alice has a key and a book.")
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    set_source_perspectives(
        scene,
        "summary",
        "base",
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice has a key and a book.",
                "sources": [source],
            }
        ],
    )
    source = select_character_view(
        scene, source_reference(scene, "summary", "base"), "Alice"
    ).source
    await replace_source_facts(
        scene,
        [
            (
                source,
                ("Alice",),
                [
                    ParsedFact(text="Alice has a key."),
                    ParsedFact(text="Alice has a book."),
                ],
            )
        ],
    )
    caches = []
    original = supported_facts.summary_coverage

    def coverage(*args, **kwargs):
        caches.append(kwargs["cache"])
        return original(*args, **kwargs)

    monkeypatch.setattr(supported_facts, "summary_coverage", coverage)
    if query == "facts":
        facts_about(scene, "Alice", character="Alice")
    elif query == "bucket":
        bucket(scene, "Alice")
    else:
        supported_facts.previous_audience_facts(scene, ("Alice",))
    assert len(caches) == 2
    assert caches[0] is caches[1]
    assert caches[0]


def test_legacy_fact_query_filters_mentions_before_bucket(scene, monkeypatch):
    from talemate.knowledge.graph import KnowledgeIndex

    scene.world_state.facts = {
        "F1": Fact(id="F1", text="The key."),
        "F2": Fact(id="F2", text="A book."),
    }
    check = Mock(return_value=True)
    monkeypatch.setattr(KnowledgeIndex, "in_bucket", check)
    assert [fact.id for fact in facts_about(scene, "key", character="Alice")] == ["F1"]
    assert check.call_count == 1


@pytest.mark.asyncio
async def test_summary_readiness_ignores_missing_character_and_shares_read(
    supported_scene, monkeypatch
):
    from talemate.agents.summarize import audience_summaries

    scene, summarizer, _ = supported_scene
    passage(scene, "Alice and Bob have a key.", ("Alice", "Bob"))
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    original = audience_summaries.summary_inputs

    def inputs(*args, **kwargs):
        result = original(*args, **kwargs)
        result["Removed"] = result["Alice"]
        return result

    reads = []
    original_select = audience_summaries.select_character_view

    def select(scene, source, name, **kwargs):
        assert name != "Removed"
        result = original_select(scene, source, name, **kwargs)
        if result.status == "ready" and "read" in kwargs:
            reads.append(kwargs["read"])
        return result

    monkeypatch.setattr(audience_summaries, "summary_inputs", inputs)
    monkeypatch.setattr(audience_summaries, "select_character_view", select)
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(return_value=("Alice and Bob have a key.", [])),
    )
    await summarizer.ensure_summary_views(scene, "base")
    assert scene.archived_history[0]["facts_status"] == "ok"
    assert len(reads) >= 2 and reads[-1] is reads[-2]


@pytest.mark.asyncio
@pytest.mark.parametrize("audience", ["Alice", "Bob"])
async def test_one_view_rebuild_preserves_edited_two_contribution_record(
    supported_scene, monkeypatch, audience
):
    scene, summarizer, memory = supported_scene
    text = "Alice and Bob see the key."
    message, _ = passage(scene, text, ("Alice", "Bob"))
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": [name], "status": "ready", "text": text}
            for name in ("Alice", "Bob")
        ],
    )
    views = {
        name: select_character_view(
            scene, source_reference(scene, "message", message.id), name
        ).source
        for name in ("Alice", "Bob")
    }
    for name, source in views.items():
        await store(scene, source, (name,), text, subjects=["key"])
    assert len(scene.world_state.facts) == 1
    fact = next(iter(scene.world_state.facts.values()))
    assert len(fact.contributions) == 2
    fact.text = "AUTHOR CORRECTION: the key is a decoy."
    fact.subjects = ["decoy"]
    fact.known_by = {"Bob": "told"}
    scene.world_state.facts["manual"] = Fact(id="manual", text="An author predecessor.")
    fact.supersedes = "manual"
    original = fact.model_copy(deep=True)
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=(
                "Discarded summary",
                [ParsedFact(text=text, subjects=["key"])],
            )
        ),
    )
    assert await summarizer.rebuild_supported_facts(scene, [views[audience]]) == "ok"
    assert scene.world_state.facts[fact.id] == original
    assert any(
        doc["text"] == original.text for doc in memory.add_many.call_args.args[0]
    )
    assert current_state(scene, "key", character="Alice").text == text
    assert current_state(scene, "key", character="Bob").text == text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed", "omitted"])
async def test_full_rebuild_skips_unready_passage_views(
    supported_scene, monkeypatch, status
):
    scene, summarizer, _ = supported_scene
    message, _ = passage(scene, "Alice sees the key.")
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": ["Alice"], "status": "ready", "text": "Alice sees the key."},
            {"audience": ["Bob"], "status": status},
        ],
    )
    alice = select_character_view(
        scene, source_reference(scene, "message", message.id), "Alice"
    ).source
    bob = select_character_view(
        scene, source_reference(scene, "message", message.id), "Bob"
    ).source
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    set_source_perspectives(
        scene,
        "summary",
        "base",
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice sees the key.",
                "sources": [alice],
            }
        ],
    )
    requested = list(summarizer.saved_fact_sources(scene))
    assert (bob in requested) == (status == "omitted")
    request = AsyncMock(
        return_value=("Unused summary", [ParsedFact(text="Alice sees the key.")])
    )
    monkeypatch.setattr(summarizer, "summarize", request)
    assert await summarizer.rebuild_supported_facts(scene) == "ok"
    request.assert_awaited_once()
    assert request.call_args.kwargs["audience"] == ("Alice",)
    assert current_state(scene, "key", character="Alice").text == "Alice sees the key."
    assert current_state(scene, "key", character="Bob") is None
    summarizer.client._prompt_generation_error.assert_not_awaited()
    if status != "omitted":
        assert await summarizer.rebuild_supported_facts(scene, [bob]) == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("reload_failures", [False, True])
async def test_successful_full_fact_rebuild_persists_recovery(
    supported_scene, monkeypatch, reload_failures
):
    scene, summarizer, _ = supported_scene
    passage(scene, "Alice and Bob have a key.", ("Alice", "Bob"))
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(return_value=("Alice and Bob have a key.", None)),
    )
    await summarizer.ensure_summary_views(scene, "base")
    assert scene.archived_history[0]["facts_status"] == "failed"
    if reload_failures:
        # The entry survives saving; runtime failure keys do not.
        scene.archived_history = json.loads(json.dumps(scene.archived_history))
        summarizer._summary_fact_failures.pop(scene, None)
    request = AsyncMock(
        return_value=(
            "Do not publish this summary.",
            [ParsedFact(text="Alice and Bob have a key.")],
        )
    )
    monkeypatch.setattr(summarizer, "summarize", request)
    assert await summarizer.rebuild_supported_facts(scene) == "ok"
    assert scene.archived_history[0]["facts_status"] == "ok"
    assert not summarizer._summary_fact_failures[scene]
    persisted = json.loads(json.dumps(scene.archived_history))
    scene.archived_history = persisted
    summarizer._summary_fact_failures.pop(scene, None)
    await summarizer.ensure_summary_views(scene, "base")
    assert scene.archived_history[0]["facts_status"] == "ok"
    assert not summarizer._summary_fact_failures[scene]
    request.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_fact_recovery_does_not_clear_unrepaired_saved_failure(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    message, _ = passage(scene, "Reader text", ("Alice", "Bob"))
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": [name], "status": "ready", "text": f"{name} has a key."}
            for name in ("Alice", "Bob")
        ],
    )
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]

    async def malformed(text, **kwargs):
        return text, None

    monkeypatch.setattr(summarizer, "summarize", malformed)
    await summarizer.ensure_summary_views(scene, "base")
    summarizer._summary_fact_failures.pop(scene, None)
    alice = select_character_view(
        scene, source_reference(scene, "summary", "base"), "Alice"
    ).source
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(return_value=("Unused", [ParsedFact(text="Alice has a key.")])),
    )
    assert await summarizer.rebuild_supported_facts(scene, [alice]) == "ok"
    assert scene.archived_history[0]["facts_status"] == "failed"
    assert summarizer._summary_fact_failures[scene] == {(0, "base", "Bob")}


@pytest.mark.asyncio
async def test_summary_fact_retry_keeps_published_view_and_dependents(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    text = "Alice has a key."
    passage(scene, text)
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    request = AsyncMock(
        side_effect=[
            (text, None),
            (
                "Different generated prose that must be discarded.",
                [ParsedFact(text=text)],
            ),
        ]
    )
    monkeypatch.setattr(summarizer, "summarize", request)
    published = []

    async def retry(message):
        assert "Retry fact extraction" in message
        published.append(deepcopy(scene.archived_history[0]["knowledge"]))
        source = select_character_view(
            scene, source_reference(scene, "summary", "base"), "Alice"
        ).source
        scene.layered_history = [
            [{"id": "layer", "text": "Reader layer", "start": 0, "end": 0}]
        ]
        set_source_perspectives(
            scene,
            "summary",
            "layer",
            [
                {
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": text,
                    "sources": [source],
                }
            ],
            layer=1,
        )
        return "retry"

    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", retry)
    await summarizer.ensure_summary_views(scene, "base")
    assert request.await_count == 2
    assert scene.archived_history[0]["knowledge"] == published[0]
    assert scene.archived_history[0]["facts_status"] == "ok"
    assert (
        select_character_view(
            scene, source_reference(scene, "summary", "layer", layer=1), "Alice"
        ).status
        == "ready"
    )
    assert current_state(scene, "key", character="Alice").text == text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["remove", "replace"])
async def test_fact_retry_cannot_widen_when_view_changes_during_dialog(
    supported_scene, monkeypatch, change
):
    scene, summarizer, _ = supported_scene
    message, _ = passage(scene, "Reader", ("Alice", "Bob"))
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": [name], "status": "ready", "text": f"{name} sees the key."}
            for name in ("Alice", "Bob")
        ],
    )
    sources = {
        name: select_character_view(
            scene, source_reference(scene, "message", message.id), name
        ).source
        for name in ("Alice", "Bob")
    }
    scene.archived_history = [
        ArchiveEntry(id="base", text="Reader", start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    set_source_perspectives(
        scene,
        "summary",
        "base",
        [
            {
                "audience": ["Bob"],
                "status": "ready",
                "text": "Bob sees the key.",
                "sources": [sources["Bob"]],
            }
        ],
    )
    bob_source = select_character_view(
        scene, source_reference(scene, "summary", "base"), "Bob"
    ).source
    await store(scene, bob_source, ("Bob",), "Bob sees the key.")
    original_facts = deepcopy(scene.world_state.facts)
    request = AsyncMock(
        side_effect=[("Alice sees the key.", None), ("Must not be requested", [])]
    )
    monkeypatch.setattr(summarizer, "summarize", request)
    rebuild = AsyncMock(wraps=summarizer.rebuild_supported_facts)
    monkeypatch.setattr(summarizer, "rebuild_supported_facts", rebuild)

    async def retry(prompt):
        assert "Retry fact extraction" in prompt
        bob = next(
            view
            for view in scene.archived_history[0]["knowledge"]["views"]
            if "Bob" in view["audience"]
        )
        outputs = [{key: value for key, value in bob.items() if key != "revision"}]
        if change == "replace":
            outputs.append(
                {
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": "A replacement Alice view.",
                    "sources": [sources["Alice"]],
                }
            )
        set_source_perspectives(scene, "summary", "base", outputs)
        return "retry"

    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", retry)
    await summarizer.ensure_summary_views(scene, "base", audiences=["Alice"])
    rebuild.assert_not_awaited()
    request.assert_awaited_once()
    assert request.call_args.kwargs["audience"] == ("Alice",)
    assert scene.world_state.facts == original_facts
    bob = select_character_view(scene, bob_source, "Bob")
    assert bob.status == "ready" and bob.text == "Bob sees the key."
    assert scene.archived_history[0]["facts_status"] == "failed"


async def test_topic_coverage_measures_supported_access_and_staleness(supported_scene):
    scene, _, memory = supported_scene
    memory.actions["topics"].enabled = True
    message, source = passage(
        scene, "The key is in the drawer.", audience=("Alice", "Bob")
    )
    await store(scene, source, ("Alice", "Bob"), "The key is in the drawer.")
    fact = next(iter(scene.world_state.facts.values()))
    fact.present = []
    scene.world_state.topics = {"T1": Topic(id="T1", name="Key", fact_ids=[fact.id])}
    assert coverage(scene, "Bob")[0].known == 1
    assert awareness_line(scene, "Bob") is None
    scene.edit_message(message.id, "The key was moved.")
    assert coverage(scene, "Bob") == []
    scene.world_state.facts[fact.id] = fact
    scene.world_state.topics = {"T1": Topic(id="T1", name="Key", fact_ids=[fact.id])}
    assert coverage(scene, "Bob")[0].known == 0
    assert coverage(scene, "Bob")[0].total == 1


async def test_topic_coverage_tolerates_removed_viewer_without_legacy_index(
    supported_scene, monkeypatch
):
    scene, _, memory = supported_scene
    memory.actions["topics"].enabled = True
    _, source = passage(scene, "The key is in the drawer.", audience=("Alice", "Bob"))
    await store(scene, source, ("Alice", "Bob"), "The key is in the drawer.")
    fact = next(iter(scene.world_state.facts.values()))
    scene.world_state.topics = {"T1": Topic(id="T1", name="Key", fact_ids=[fact.id])}

    def unexpected_index(*args):
        raise AssertionError("Perception coverage must not build the legacy index")

    monkeypatch.setattr(
        "talemate.knowledge.topics.KnowledgeIndex.from_scene", unexpected_index
    )
    assert coverage(scene, "Bob")[0].known == 1
    scene.character_data.pop("Bob")
    assert coverage(scene, "Bob") == []
    report = await scene.world_state_manager.get_character_knowledge("Bob")
    assert report.coverage == []
