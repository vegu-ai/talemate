from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _node_test_helpers import run_node
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.emit.signals import KnowledgeChanged
from talemate.game.engine.nodes.knowledge import GrantKnowledge, RevokeKnowledge
from talemate.instance import get_agent
from talemate.history import rebuild_history
from talemate.knowledge.entry import set_edge
from talemate.knowledge.changes import (
    KnowledgeChange,
    emit_knowledge_changes,
    knowledge_label,
)
from talemate.knowledge.facts import store_facts
from talemate.knowledge.schema import Fact, KnowledgeEdge, ParsedFact
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, TimePassageMessage
from talemate.server.websocket_server import WebsocketHandler
from talemate.world_state import ManualContext


@pytest.fixture
def notifications(scene):
    scene.active = True
    received = []
    with KnowledgeChanged.connected_to(received.append):
        yield received


@pytest.fixture
def fact_memory(monkeypatch):
    memory = SimpleNamespace(
        get=AsyncMock(return_value=[]),
        add_many=AsyncMock(),
        compare_string_lists=AsyncMock(return_value={"distance_matches": []}),
    )
    monkeypatch.setattr("talemate.knowledge.facts.get_agent", lambda _: memory)
    return memory


@pytest.mark.parametrize(
    "source", ["told", "inferred", "director", "manual", "granted"]
)
@pytest.mark.parametrize("kind", ["grant", "revoke"])
async def test_manual_edge_writes_notify_once(scene, notifications, source, kind):
    edge = KnowledgeEdge(
        character="Mara", target="Edwin.secret", source=source, kind=kind
    )
    manager = scene.world_state_manager
    await manager.set_knowledge_edge(edge)
    assert notifications[0].data == {
        "scene_id": scene.id,
        "changes": [
            {
                "character": "Mara",
                "target": "Edwin.secret",
                "kind": kind,
                "label": "Edwin.secret",
            }
        ],
    }
    await manager.set_knowledge_edge(edge.model_copy())
    await manager.remove_knowledge_edge(edge.id)
    assert len(notifications) == 1
    assert scene.world_state.knowledge == []


async def test_editing_an_edge_kind_notifies(scene, notifications):
    edge = KnowledgeEdge(character="Mara", target="F1")
    await scene.world_state_manager.set_knowledge_edge(edge)
    await scene.world_state_manager.set_knowledge_edge(
        edge.model_copy(update={"kind": "revoke"})
    )
    assert [n.data["changes"][0]["kind"] for n in notifications] == ["grant", "revoke"]


@pytest.mark.parametrize(
    "node_type,kind", [(GrantKnowledge, "grant"), (RevokeKnowledge, "revoke")]
)
@pytest.mark.parametrize("source", ["director", "granted"])
async def test_real_edge_node_emits_and_repeated_assignment_is_quiet(
    scene, notifications, node_type, kind, source
):
    scene.world_state.facts["F1"] = Fact(id="F1", text="The key is under the mat.")
    for _ in range(2):
        await run_node(
            node_type(),
            scene=scene,
            inputs={
                "character": "Mara",
                "target": "F1",
                "source": source,
                "replace": True,
            },
        )
    assert len(notifications) == 1
    assert notifications[0].data["changes"][0]["label"] == "The key is under the mat."
    assert notifications[0].data["changes"][0]["kind"] == kind


async def test_archive_facts_batch_witnesses_and_told_learners(
    scene, notifications, fact_memory
):
    await store_facts(
        scene,
        "archive",
        ["Mara"],
        10,
        [
            ParsedFact(text="The key is hidden.", known_by=["Mara", "Edwin"]),
            ParsedFact(text="The door is locked."),
        ],
        0.15,
        notify=True,
    )
    assert len(notifications) == 1
    assert [
        (c["character"], c["target"]) for c in notifications[0].data["changes"]
    ] == [
        ("Mara", "F1"),
        ("Edwin", "F1"),
        ("Mara", "F2"),
    ]
    fact_memory.add_many.assert_awaited_once()


async def test_restatement_notifies_only_new_learners(
    scene, notifications, fact_memory, monkeypatch
):
    fact = Fact(id="F1", text="The key is hidden.", present=["Mara"])
    scene.world_state.facts[fact.id] = fact
    monkeypatch.setattr(
        "talemate.knowledge.facts._near_duplicate", AsyncMock(return_value=fact)
    )
    for _ in range(2):
        await store_facts(
            scene,
            "archive",
            ["Mara", "Edwin"],
            10,
            [ParsedFact(text=fact.text)],
            0.15,
            notify=True,
        )
    assert len(notifications) == 1
    assert [c["character"] for c in notifications[0].data["changes"]] == ["Edwin"]


@pytest.mark.parametrize("present", [None, []])
async def test_unattributed_fact_does_not_guess_learners(
    scene, notifications, fact_memory, present
):
    await store_facts(
        scene,
        "archive",
        present,
        10,
        [ParsedFact(text="The key is hidden.")],
        0.15,
        notify=True,
    )
    assert scene.world_state.facts
    assert notifications == []


async def test_maintenance_fact_storage_is_silent(scene, notifications, fact_memory):
    await store_facts(
        scene,
        "archive",
        ["Mara"],
        10,
        [ParsedFact(text="The key is hidden.", known_by=["Edwin"])],
        0.15,
    )
    assert scene.world_state.facts and scene.world_state.knowledge
    assert notifications == []


@pytest.mark.parametrize("live", [True, False])
async def test_live_archive_notifies_but_history_rebuild_is_silent(
    scene, notifications, fact_memory, monkeypatch, live
):
    summarizer = get_agent("summarizer")
    summarizer.actions["archive"].config["threshold"].value = 100000
    both = ["Mara", "Edwin"]
    scene.history = [
        CharacterMessage(message="Mara: The key is under the mat.", present=both),
        CharacterMessage(message="Edwin: I see it.", present=both),
        CharacterMessage(message="Mara: Use it.", present=both),
        TimePassageMessage(ts=60, message="A minute passes", present=both),
        CharacterMessage(message="Mara: Hurry.", present=both),
    ]
    summarize = AsyncMock(
        return_value=(
            "They found the key.",
            [ParsedFact(text="The key is under the mat.")],
        )
    )
    monkeypatch.setattr(summarizer, "summarize", summarize)
    monkeypatch.setattr("talemate.agents.summarize.refresh_topics", AsyncMock())
    if live:
        await summarizer.on_push_history(SimpleNamespace())
    else:
        monkeypatch.setattr(
            "talemate.history.purge_all_history_from_memory", AsyncMock()
        )
        monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
        await rebuild_history(scene)
    summarize.assert_awaited_once()
    assert len(notifications) == int(live)
    if live:
        assert {c["character"] for c in notifications[0].data["changes"]} == set(both)
    assert scene.world_state.facts["F1"].archive_id == scene.archived_history[0]["id"]


async def test_existing_ledger_call_emits_a_batch(scene, notifications, monkeypatch):
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    conversation.actions["character_knowledge"].config["ledger"].value = True
    scene.character_data = {name: Character(name=name) for name in ["Mara", "Edwin"]}
    scene.active_characters = list(scene.character_data)
    fact = Fact(id="F1", text="The key is hidden.", present=["Mara"])
    scene.world_state.facts[fact.id] = fact
    monkeypatch.setattr(
        "talemate.agents.conversation.knowledge.absence_facts",
        AsyncMock(return_value=[fact]),
    )
    request = AsyncMock(return_value=("", {"ledger": '{"Edwin": ["F1"]}'}))
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveScene(scene):
        await conversation.record_learned_facts(
            scene.character_data["Mara"], "Mara: The key is hidden."
        )
    request.assert_awaited_once()
    assert len(notifications) == 1
    assert notifications[0].data["changes"][0]["character"] == "Edwin"


def test_websocket_passthrough_and_inactive_scene_silence(scene, notifications):
    change = KnowledgeChange(character="Mara", target="F1")
    emit_knowledge_changes(scene, [change, change])
    handler = object.__new__(WebsocketHandler)
    sent = []
    handler.queue_put = sent.append
    handler.handle(notifications[0])
    assert sent[0]["type"] == "knowledge_changed"
    assert sent[0]["data"]["scene_id"] == scene.id
    assert len(sent[0]["data"]["changes"]) == 1
    scene.active = False
    emit_knowledge_changes(scene, [change])
    assert len(notifications) == 1


def test_history_edge_has_a_readable_label(scene, notifications):
    scene.archived_history = [
        {"id": "archive-id", "text": "Mara found the cellar key.", "end": 3}
    ]
    emit_knowledge_changes(
        scene, [KnowledgeChange(character="Edwin", target="archive-id")]
    )
    assert (
        notifications[0].data["changes"][0]["label"]
        == "history: Mara found the cellar key."
    )


@pytest.mark.parametrize("writer", ["manual", "append", "replace"])
async def test_edge_writers_ignore_source_changes_and_duplicate_grants(
    scene, notifications, writer
):
    original = KnowledgeEdge(character="Mara", target="F1", source="told")
    scene.world_state.knowledge = [original]
    edge = KnowledgeEdge(character="Mara", target="F1", source="director")
    if writer == "manual":
        await scene.world_state_manager.set_knowledge_edge(edge)
    else:
        set_edge(scene, edge, replace=writer == "replace")
    assert notifications == []
    revoke = edge.model_copy(update={"kind": "revoke"})
    if writer == "manual":
        await scene.world_state_manager.set_knowledge_edge(revoke)
    else:
        set_edge(scene, revoke, replace=writer == "replace")
    assert [n.data["changes"][0]["kind"] for n in notifications] == ["revoke"]


def test_replacing_conflicting_edges_notifies_only_when_effective_kind_changes(
    scene, notifications
):
    scene.world_state.knowledge = [
        KnowledgeEdge(character="Mara", target="F1", kind=kind)
        for kind in ["grant", "revoke"]
    ]
    set_edge(scene, KnowledgeEdge(character="Mara", target="F1"))
    assert notifications == []
    set_edge(scene, KnowledgeEdge(character="Mara", target="F1"), replace=True)
    assert notifications[0].data["changes"][0]["kind"] == "grant"


def test_fact_notification_does_not_build_target_catalogue(
    scene, notifications, monkeypatch
):
    scene.world_state.facts["F1"] = Fact(id="F1", text="The key is hidden.")

    def unexpected_catalogue():
        pytest.fail("fact notification must not build the target catalogue")

    monkeypatch.setattr(
        scene.world_state_manager, "knowledge_targets", unexpected_catalogue
    )
    emit_knowledge_changes(scene, [KnowledgeChange(character="Mara", target="F1")])
    assert notifications[0].data["changes"][0]["label"] == "The key is hidden."


@pytest.mark.parametrize(
    "target,label",
    [
        ("Mara.description", "Mara: description"),
        ("Mara.secret", "Mara: secret"),
        ("Mara.detail.hobby", "Mara: hobby"),
        ("Mara.missing", "Mara.missing"),
        ("world-secret", "world-secret"),
        ("static-id", "static history: Before the story."),
        ("layer-id", "history (layer 1): Earlier in the story."),
        ("missing", "missing"),
    ],
)
def test_notification_labels_resolve_only_requested_targets(scene, target, label):
    scene.character_data = {
        "Edwin": Character(name="Edwin"),
        "Mara": Character(
            name="Mara",
            description="A keeper.",
            base_attributes={"secret": "A secret."},
            details={"hobby": "Sailing."},
        ),
    }
    scene.world_state.manual_context["world-secret"] = ManualContext(
        id="world-secret", text="The cellar floods."
    )
    scene.archived_history = [{"id": "static-id", "text": "Before the story."}]
    scene.layered_history = [
        [
            {"id": "other-layer-id", "text": "Another entry."},
            {"id": "layer-id", "text": "Earlier in the story."},
        ]
    ]
    assert knowledge_label(scene, target) == label
