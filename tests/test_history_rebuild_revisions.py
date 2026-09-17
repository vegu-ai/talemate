"""#662: a full history rebuild settles the per-message refresh flags."""

import weakref
from unittest.mock import AsyncMock

import test_knowledge_facts
import test_revision_browsing
from talemate.exceptions import GenerationCancelled
from talemate.history import rebuild_history
from talemate.instance import get_agent
from talemate.knowledge.revision_browsing import defer_revision_work
from talemate.knowledge.revision_refresh import (
    _archive_vector_repairs,
    begin_revision_transaction,
    refresh_revision,
    remove_revised_evidence,
    restore_revision_baseline,
    revision_refresh_payload,
    revisions_before_rebuild,
    settle_revisions_after_rebuild,
)
from talemate.knowledge.schema import Fact, KnowledgeEdge
from talemate.scene_message import RevisionIndexRepair

summarizer_scene = test_knowledge_facts.summarizer_scene
fake_memory = test_knowledge_facts.fake_memory


async def rebuilt(summarizer_scene):
    scene, summarizer = summarizer_scene
    helper = test_knowledge_facts.TestFactAgeAcrossPassages()
    helper._stub(summarizer)
    scene.history = helper._history()
    for message in scene.history:
        message._knowledge_scene = weakref.ref(scene)
    scene.active = True
    await rebuild_history(scene)
    return scene, summarizer


def learning_from_dialogue(on: bool):
    conversation = get_agent("conversation")
    conversation.write_enabled("character_knowledge", on)
    conversation.write_config("character_knowledge", "ledger", on)


def revise(scene):
    message = scene.history[1]
    message.append_version("Mara: two, but different", "revision")
    return message


def refresh(scene, message):
    return revision_refresh_payload(scene, message)["revision_refresh"]


async def test_a_rebuild_commits_a_revised_passage_and_drops_its_old_evidence(
    summarizer_scene, fake_memory
):
    scene, _ = await rebuilt(summarizer_scene)
    learning_from_dialogue(False)
    message = revise(scene)
    scene.world_state.facts["M1"] = Fact(
        id="M1", text="A manual fact.", source="manual"
    )
    scene.world_state.knowledge.append(
        KnowledgeEdge(
            character="Edwin", target="M1", source="inferred", message_id=message.id
        )
    )
    assert refresh(scene, message)["required"] is True

    await rebuild_history(scene)

    assert message.revision_matches_baseline
    assert refresh(scene, message)["required"] is False
    assert [edge for edge in scene.world_state.knowledge if edge.target == "M1"] == []


async def test_a_rebuild_leaves_only_the_learning_from_dialogue_owed(
    summarizer_scene, fake_memory
):
    scene, _ = await rebuilt(summarizer_scene)
    learning_from_dialogue(True)
    message = revise(scene)
    assert refresh(scene, message)["operations"] == ["facts", "learning"]

    await rebuild_history(scene)

    state = refresh(scene, message)
    assert message.revision_matches_baseline
    assert state["required"] is True
    assert (state["operations"], state["label"]) == (
        ["learning"],
        "Learn from dialogue",
    )


async def test_the_owed_learning_outlasts_later_fact_changes(
    summarizer_scene, fake_memory
):
    scene, _ = await rebuilt(summarizer_scene)
    learning_from_dialogue(True)
    message = revise(scene)
    await rebuild_history(scene)

    scene.world_state.facts["M9"] = Fact(id="M9", text="Unrelated.", source="manual")
    next(iter(scene.world_state.facts.values())).known_by["Edwin"] = "inferred"

    assert refresh(scene, message)["operations"] == ["learning"]


async def test_browsing_back_to_the_old_text_after_a_rebuild_owes_a_refresh(
    summarizer_scene, fake_memory
):
    scene, _ = await rebuilt(summarizer_scene)
    learning_from_dialogue(True)
    message = revise(scene)
    await rebuild_history(scene)

    with defer_revision_work():
        scene.set_message_active_version(message.id, 0)

    state = refresh(scene, message)
    assert state["required"] is True
    assert state["operations"] == ["facts", "learning"]


async def test_a_rebuild_keeps_the_author_rules_of_a_recorded_fact(
    summarizer_scene, fake_memory
):
    scene, _ = await rebuilt(summarizer_scene)
    fact = next(f for f in scene.world_state.facts.values() if f.message_id)
    scene.world_state.knowledge.append(
        KnowledgeEdge(
            character="Edwin",
            target=fact.id,
            kind="unlearn",
            message_id_boundary=max(message.id for message in scene.history),
        )
    )

    await rebuild_history(scene)

    (again,) = [f for f in scene.world_state.facts.values() if f.text == fact.text]
    assert again.id != fact.id
    assert [
        (edge.character, edge.target, edge.anchor)
        for edge in scene.world_state.knowledge
        if edge.kind == "unlearn"
    ] == [("Edwin", again.id, None)]


async def test_a_rebuild_moves_a_pending_index_repair_to_the_scene(
    summarizer_scene, fake_memory, monkeypatch
):
    scene, summarizer = await rebuilt(summarizer_scene)
    message = scene.history[1]
    message.set_revision_status(
        "clean",
        pending_index_repair=RevisionIndexRepair(
            fact_ids=["M1"], archive_ids=["base:gone"]
        ),
    )
    assert refresh(scene, message)["label"] == "Update knowledge"
    queued = []
    monkeypatch.setattr(
        summarizer, "queue_fact_memory", lambda _, ids: queued.append(list(ids))
    )

    await rebuild_history(scene)

    assert message.revision_state.pending_index_repair is None
    assert refresh(scene, message)["required"] is False
    assert ["M1"] in queued
    assert "base:gone" in _archive_vector_repairs[scene]


async def test_a_cancelled_rebuild_commits_nothing(
    summarizer_scene, fake_memory, monkeypatch
):
    scene, summarizer = await rebuilt(summarizer_scene)
    learning_from_dialogue(False)
    message = revise(scene)
    monkeypatch.setattr(
        summarizer, "build_archive", AsyncMock(side_effect=GenerationCancelled("stop"))
    )

    await rebuild_history(scene)

    assert not message.revision_matches_baseline


async def test_browsing_back_after_a_cancelled_rebuild_restores_the_old_evidence(
    summarizer_scene, fake_memory, monkeypatch
):
    scene, summarizer = await rebuilt(summarizer_scene)
    learning_from_dialogue(False)
    message = scene.history[1]
    scene.world_state.facts["M1"] = Fact(
        id="M1", text="A manual fact.", source="manual"
    )
    scene.world_state.knowledge.append(
        KnowledgeEdge(
            character="Edwin", target="M1", source="inferred", message_id=message.id
        )
    )
    revise(scene)
    monkeypatch.setattr(
        summarizer, "build_archive", AsyncMock(side_effect=GenerationCancelled("stop"))
    )
    await rebuild_history(scene)
    assert learned_m1(scene) == []

    with defer_revision_work():
        scene.set_message_active_version(message.id, 0)
        assert restore_revision_baseline(scene, message)

    assert learned_m1(scene) == [("Edwin", message.id)]
    assert refresh(scene, message)["required"] is False


async def test_a_second_cancelled_rebuild_keeps_the_first_removal(
    summarizer_scene, fake_memory, monkeypatch
):
    scene, summarizer = await rebuilt(summarizer_scene)
    learning_from_dialogue(False)
    message = scene.history[1]
    scene.world_state.facts["M1"] = Fact(
        id="M1", text="A manual fact.", source="manual"
    )
    scene.world_state.knowledge.append(
        KnowledgeEdge(
            character="Edwin", target="M1", source="inferred", message_id=message.id
        )
    )
    revise(scene)
    monkeypatch.setattr(
        summarizer, "build_archive", AsyncMock(side_effect=GenerationCancelled("stop"))
    )
    await rebuild_history(scene)
    await rebuild_history(scene)

    with defer_revision_work():
        scene.set_message_active_version(message.id, 0)
        assert restore_revision_baseline(scene, message)

    assert learned_m1(scene) == [("Edwin", message.id)]


def learned_m1(scene):
    return [
        (edge.character, edge.message_id)
        for edge in scene.world_state.knowledge
        if edge.target == "M1"
    ]


async def test_the_learning_refresh_after_a_rebuild_skips_the_extraction(
    scene, monkeypatch
):
    summarizer, conversation, message = test_revision_browsing.standard_revision(
        scene, ledger=True
    )
    revisions = revisions_before_rebuild(scene)
    remove_revised_evidence(scene, revisions)
    settle_revisions_after_rebuild(scene, revisions)
    extract = AsyncMock(return_value=("summary", []))
    learn = AsyncMock(return_value={})
    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    await refresh_revision(scene, message)

    extract.assert_not_awaited()
    learn.assert_awaited_once()
    assert refresh(scene, message)["required"] is False


def test_character_perspectives_settle_nothing(scene):
    _, _, message = test_revision_browsing.standard_revision(scene)
    begin_revision_transaction(scene, message)
    scene.knowledge_eligibility = "perception"

    assert revisions_before_rebuild(scene) == []
    assert message.revision_state.refresh_journal is not None
