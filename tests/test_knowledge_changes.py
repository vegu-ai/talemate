import pytest

from _node_test_helpers import run_node
from talemate.character import Character
from talemate.emit.signals import KnowledgeChanged
from talemate.game.engine.nodes.knowledge import GrantKnowledge, RevokeKnowledge
from talemate.knowledge.entry import set_edge
from talemate.knowledge.changes import (
    KnowledgeChange,
    emit_knowledge_changes,
    knowledge_label,
)
from talemate.knowledge.schema import KnowledgeEdge
from talemate.server.websocket_server import WebsocketHandler
from talemate.world_state import ManualContext


@pytest.fixture
def notifications(scene):
    scene.active = True
    received = []
    with KnowledgeChanged.connected_to(received.append):
        yield received


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
    scene.world_state.manual_context["key"] = ManualContext(
        id="key", text="The key is under the mat."
    )
    for _ in range(2):
        await run_node(
            node_type(),
            scene=scene,
            inputs={
                "character": "Mara",
                "target": "key",
                "source": source,
                "replace": True,
            },
        )
    assert len(notifications) == 1
    assert notifications[0].data["changes"][0]["label"] == "key"
    assert notifications[0].data["changes"][0]["kind"] == kind


async def test_websocket_passthrough_and_inactive_scene_silence(scene, notifications):
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


async def test_history_edge_has_a_readable_label(scene, notifications):
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


async def test_replacing_conflicting_edges_notifies_only_when_effective_kind_changes(
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


async def test_disclosure_notification_labels_only_selected_text(
    scene, notifications, monkeypatch
):
    from talemate.knowledge.disclosures import grant_disclosure

    scene.knowledge_eligibility = "perception"
    scene.character_data["Bob"] = Character(name="Bob")
    scene.world_state.manual_context["mixed"] = ManualContext(
        id="mixed", text="The ledger is under the bed. Alice plans betrayal."
    )
    disclosure = grant_disclosure(
        scene, "Bob", "mixed", text="The ledger is under the bed."
    )
    assert knowledge_label(scene, disclosure.id) == disclosure.text
    assert notifications[-1].data["changes"] == [
        {
            "character": "Bob",
            "target": disclosure.id,
            "kind": "grant",
            "label": disclosure.text,
        }
    ]
