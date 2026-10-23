"""
The knowledge nodes the director's context tools call: EntryKnowledge,
SetEntryVisibility, CharacterKnowledge and the grant / revoke edge nodes.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from _node_test_helpers import run_node, build_graph, execute_graph
from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.game.engine.context_id import context_id_item_from_string
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.nodes.scene import GetSceneState
from talemate.game.engine.nodes.string import Jinja2Format
from talemate.game.engine.nodes.knowledge import (
    CharacterKnowledge,
    KnowledgeCallbacks,
    EntryKnowledgeNode,
    GrantKnowledge,
    RevokeKnowledge,
    SetEntryVisibility,
)
from talemate.knowledge.entry import known_by_line, set_edge
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge
from talemate.world_state import ManualContext


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    s.character_data = {
        "Bob": Character(
            name="Bob",
            description="Bob keeps the light.",
            base_attributes={"secret": "Bob buried the ledger."},
            details={"the fall": "Bob fell from the gallery."},
            visibility={"secret": EntryVisibility(mode="owner")},
        ),
        "Alice": Character(name="Alice"),
        "Carol": Character(name="Carol"),
    }
    s.world_state.manual_context = {
        "Hidden Door": ManualContext(
            id="Hidden Door", text="Behind the cupboard.", meta={"typ": "world_state"}
        )
    }
    s.archived_history = [
        {"id": "st1", "text": "Long ago the tower was built.", "ts": 1},
        {
            "id": "h1",
            "text": "Mara and Edwin argued.",
            "ts": 5,
            "start": 0,
            "end": 4,
            "present": ["Bob", "Alice"],
        },
    ]
    s.ts = 42
    return s


async def item(scene, context_id: str):
    resolved = await context_id_item_from_string(context_id, scene)
    assert resolved is not None, context_id
    return resolved


class TestEntryKnowledge:
    @pytest.mark.asyncio
    async def test_sheet_entry_with_edges(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.secret", source="director"),
            KnowledgeEdge(character="Carol", target="Bob.secret", kind="revoke"),
        ]
        out = await run_node(
            EntryKnowledgeNode(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "character.attribute:Bob.secret")
            },
        )
        assert out["entry_id"] == "Bob.secret"
        assert out["text"] == (
            "Known by: only Bob (owner); grants: Alice (director); revokes: Carol (manual)"
        )
        assert out["visibility"] == {"mode": "owner", "characters": []}
        assert [e["character"] for e in out["grants"]] == ["Alice"]
        assert [e["character"] for e in out["revokes"]] == ["Carol"]

    @pytest.mark.asyncio
    async def test_name_form_resolves(self, scene):
        out = await run_node(
            EntryKnowledgeNode(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "world_entry.manual:Hidden Door")
            },
        )
        assert out["entry_id"] == "Hidden Door"
        assert out["text"] == "Known by: everyone"
        assert out["visibility"] == {"mode": "everyone", "characters": []}

    @pytest.mark.asyncio
    async def test_entry_without_knowledge_id(self, scene):
        out = await run_node(
            EntryKnowledgeNode(),
            scene=scene,
            inputs={
                "context_id_item": await item(
                    scene, "character.acting_instructions:Bob"
                )
            },
        )
        assert out["entry_id"] is None
        assert out["text"] == ""


class TestSetEntryVisibility:
    @pytest.mark.asyncio
    async def test_sheet_entry_list_mode(self, scene):
        out = await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "character.detail:Bob.the fall"),
                "mode": "list",
                "characters": ["alice", "Carol", "Alice"],
            },
        )
        assert out["entry_id"] == "Bob.detail.the fall"
        assert out["text"] == "Known by: Bob (owner), Alice, Carol"
        assert scene.character_data["Bob"].visibility["detail.the fall"] == (
            EntryVisibility(mode="list", characters=["Alice", "Carol"])
        )

    @pytest.mark.asyncio
    async def test_everyone_removes_the_setting(self, scene):
        out = await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "character.attribute:Bob.secret"),
                "mode": "everyone",
            },
        )
        assert out["text"] == "Known by: everyone"
        assert "secret" not in scene.character_data["Bob"].visibility

    @pytest.mark.asyncio
    async def test_description_and_world_entry(self, scene):
        out = await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "character.description:Bob"),
                "mode": "owner",
            },
        )
        assert out["text"] == "Known by: only Bob (owner)"
        assert scene.character_data["Bob"].visibility["description"].mode == "owner"

        out = await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "world_entry.manual:Hidden Door"),
                "mode": "owner",
            },
        )
        assert out["text"] == "Known by: nobody"
        assert (
            scene.world_state.manual_context["Hidden Door"].visibility.mode == "owner"
        )

    @pytest.mark.asyncio
    async def test_history_entry_is_refused(self, scene):
        with pytest.raises(InputValueError, match="sheet entries and world entries"):
            await run_node(
                SetEntryVisibility(),
                scene=scene,
                inputs={
                    "context_id_item": await item(scene, "history_entry.static:st1"),
                    "mode": "owner",
                },
            )

    @pytest.mark.asyncio
    async def test_unknown_character_and_empty_list(self, scene):
        with pytest.raises(InputValueError, match="`Dave` does not exist"):
            await run_node(
                SetEntryVisibility(),
                scene=scene,
                inputs={
                    "context_id_item": await item(
                        scene, "world_entry.manual:Hidden Door"
                    ),
                    "mode": "list",
                    "characters": ["Dave"],
                },
            )
        with pytest.raises(InputValueError, match="at least one character"):
            await run_node(
                SetEntryVisibility(),
                scene=scene,
                inputs={
                    "context_id_item": await item(
                        scene, "world_entry.manual:Hidden Door"
                    ),
                    "mode": "list",
                },
            )
        assert (
            scene.world_state.manual_context["Hidden Door"].visibility.mode
            == "everyone"
        )


class TestEdgeNodes:
    @pytest.mark.asyncio
    async def test_grant_by_context_id_item_replaces_the_pair(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.secret", kind="revoke")
        ]
        hashed = await item(
            scene, str((await item(scene, "character.attribute:Bob.secret")).context_id)
        )
        out = await run_node(
            GrantKnowledge(),
            scene=scene,
            inputs={
                "character": "Alice",
                "context_id_item": hashed,
                "note": "she read the ledger",
                "source": "director",
                "replace": True,
            },
        )
        edges = scene.world_state.knowledge
        assert len(edges) == 1
        assert edges[0].kind == "grant"
        assert edges[0].source == "director"
        assert edges[0].note == "she read the ledger"
        assert edges[0].ts == 42
        assert out["edge"]["target"] == "Bob.secret"
        assert out["text"] == (
            'Known by: only Bob (owner); grants: Alice (director, "she read the ledger")'
        )

    @pytest.mark.asyncio
    async def test_revoke_accepts_a_character_object_and_history(self, scene):
        out = await run_node(
            RevokeKnowledge(),
            scene=scene,
            inputs={
                "character": scene.character_data["Alice"],
                "context_id_item": await item(
                    scene, "history_entry.dynamic:layer.0.id.h1"
                ),
                "source": "director",
            },
        )
        assert out["edge"]["character"] == "Alice"
        assert out["edge"]["target"] == "h1"
        assert (
            out["text"] == "Known by: Bob, Alice (present); revokes: Alice (director)"
        )

    @pytest.mark.asyncio
    async def test_default_keeps_the_graph_behaviour(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="F1", kind="revoke")
        ]
        out = await run_node(
            GrantKnowledge(),
            scene=scene,
            inputs={"character": "Alice", "target": "F1"},
        )
        assert out["edge"]["source"] == "granted"
        assert len(scene.world_state.knowledge) == 2

    @pytest.mark.asyncio
    async def test_entry_without_knowledge_id_is_refused(self, scene):
        with pytest.raises(InputValueError, match="can know or not know"):
            await run_node(
                GrantKnowledge(),
                scene=scene,
                inputs={
                    "character": "Alice",
                    "context_id_item": await item(
                        scene, "character.acting_instructions:Bob"
                    ),
                },
            )


class TestCharacterKnowledge:
    @pytest.mark.asyncio
    async def test_report(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.secret", source="director")
        ]
        out = await run_node(
            CharacterKnowledge(),
            scene=scene,
            inputs={"character": scene.character_data["Alice"]},
        )
        assert out["character"] == "Alice"
        assert out["text"].splitlines() == [
            "### What Alice knows",
            "Grants:",
            "- Bob: secret: director",
            "Revokes: none",
            "Restricted entries Alice can see:",
            "- Bob: secret (Known by: only Bob (owner); grants: Alice (director))",
        ]


class TestSetEntryVisibilityGuards:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["", "   "])
    async def test_blank_mode_is_refused(self, scene, mode):
        with pytest.raises(InputValueError):
            await run_node(
                SetEntryVisibility(),
                scene=scene,
                inputs={
                    "context_id_item": await item(
                        scene, "character.attribute:Bob.secret"
                    ),
                    "mode": mode,
                },
            )
        assert scene.character_data["Bob"].visibility["secret"].mode == "owner"

    @pytest.mark.asyncio
    async def test_absent_mode_is_refused(self, scene):
        node = SetEntryVisibility()
        node.properties.pop("mode", None)
        with pytest.raises(InputValueError, match="mode"):
            await run_node(
                node,
                scene=scene,
                inputs={
                    "context_id_item": await item(
                        scene, "character.attribute:Bob.secret"
                    )
                },
            )
        assert scene.character_data["Bob"].visibility["secret"].mode == "owner"

    @pytest.mark.asyncio
    async def test_mode_is_case_insensitive(self, scene):
        out = await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "world_entry.manual:Hidden Door"),
                "mode": " Owner ",
            },
        )
        assert out["text"] == "Known by: nobody"

    @pytest.mark.asyncio
    async def test_comma_separated_names_in_one_item(self, scene):
        out = await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "world_entry.manual:Hidden Door"),
                "mode": "list",
                "characters": ["Alice, carol"],
            },
        )
        assert out["text"] == "Known by: Alice, Carol"

    @pytest.mark.asyncio
    async def test_name_with_a_comma_resolves_whole(self, scene):
        scene.character_data["Smith, John"] = Character(name="Smith, John")
        out = await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "world_entry.manual:Hidden Door"),
                "mode": "list",
                "characters": ["Smith, John", "alice, Carol"],
            },
        )
        assert out["text"] == "Known by: Smith, John, Alice, Carol"

    @pytest.mark.asyncio
    async def test_layered_history_entry_is_refused(self, scene):
        scene.layered_history = [
            [
                {
                    "id": "L1",
                    "text": "Mara and Edwin argued.",
                    "ts": 5,
                    "start": 1,
                    "end": 1,
                }
            ]
        ]
        with pytest.raises(InputValueError, match="sheet entries and world entries"):
            await run_node(
                SetEntryVisibility(),
                scene=scene,
                inputs={
                    "context_id_item": await item(
                        scene, "history_entry.dynamic:layer.1.id.L1"
                    ),
                    "mode": "owner",
                },
            )
        assert "L1" not in scene.world_state.manual_context


class TestWorldEntryTitlesAreLiteral:
    """A world entry may be titled like a description paragraph id."""

    @pytest.fixture
    def lab(self, scene):
        for title in ("Lab.description", "Lab.description.1"):
            scene.world_state.manual_context[title] = ManualContext(
                id=title,
                text=f"{title} text",
                meta={"typ": "world_state"},
                visibility=EntryVisibility(mode="owner"),
            )
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Alice",
                target="Lab.description",
                kind="revoke",
                source="manual",
            )
        ]
        return scene

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "node_cls, kind", [(GrantKnowledge, "grant"), (RevokeKnowledge, "revoke")]
    )
    async def test_edge_lands_on_the_requested_entry(self, lab, node_cls, kind):
        out = await run_node(
            node_cls(),
            scene=lab,
            inputs={
                "character": "Alice",
                "context_id_item": await item(
                    lab, "world_entry.manual:Lab.description.1"
                ),
                "source": "director",
                "replace": True,
            },
        )
        assert out["edge"]["target"] == "Lab.description.1"
        targets = sorted((e.target, e.kind) for e in lab.world_state.knowledge)
        assert targets == [("Lab.description", "revoke"), ("Lab.description.1", kind)]
        assert out["text"].startswith(
            "Known by: nobody; "
            + ("grants" if kind == "grant" else "revokes")
            + ": Alice (director)"
        )
        assert (
            known_by_line(lab, "Lab.description")
            == "Known by: nobody; revokes: Alice (manual)"
        )

    def test_bare_id_grant_stays_literal_too(self, lab):
        set_edge(
            lab,
            KnowledgeEdge(character="Bob", target="Lab.description.1"),
            replace=True,
        )
        assert [e.target for e in lab.world_state.knowledge] == [
            "Lab.description",
            "Lab.description.1",
        ]
        assert (
            known_by_line(lab, "Lab.description.1")
            == "Known by: nobody; grants: Bob (manual)"
        )


class TestAttributeNamedLikeAParagraph:
    """A sheet attribute may be named `description.3`; it is not a paragraph."""

    @pytest.fixture
    def bob(self, scene):
        bob = scene.character_data["Bob"]
        bob.base_attributes["description.3"] = "Bob's third face."
        bob.visibility["description.3"] = EntryVisibility(mode="owner")
        bob.visibility["description"] = EntryVisibility(mode="owner")
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.description", kind="revoke"),
            KnowledgeEdge(character="Alice", target="Bob.description.3", kind="grant"),
        ]
        return scene

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "node_cls, kind", [(GrantKnowledge, "grant"), (RevokeKnowledge, "revoke")]
    )
    async def test_edge_lands_on_the_attribute(self, bob, node_cls, kind):
        out = await run_node(
            node_cls(),
            scene=bob,
            inputs={
                "character": "Alice",
                "context_id_item": await item(
                    bob, "character.attribute:Bob.description.3"
                ),
                "source": "director",
                "replace": True,
            },
        )
        assert out["edge"]["target"] == "Bob.description.3"
        targets = sorted(
            (e.target, e.kind, e.source) for e in bob.world_state.knowledge
        )
        assert targets == [
            ("Bob.description", "revoke", "manual"),
            ("Bob.description.3", kind, "director"),
        ]
        assert known_by_line(bob, "Bob.description") == (
            "Known by: only Bob (owner); revokes: Alice (manual)"
        )
        word = "grants" if kind == "grant" else "revokes"
        assert out["text"] == f"Known by: only Bob (owner); {word}: Alice (director)"

    def test_bare_id_keeps_a_real_attribute_and_folds_a_paragraph(self, bob):
        set_edge(bob, KnowledgeEdge(character="Carol", target="Bob.description.3"))
        set_edge(bob, KnowledgeEdge(character="Carol", target="Bob.description.7"))
        assert [e.target for e in bob.world_state.knowledge[-2:]] == [
            "Bob.description.3",
            "Bob.description",
        ]


async def test_revoke_node_rejects_perception_scene(scene):
    scene.knowledge_eligibility = "perception"
    with pytest.raises(InputValueError, match="Revokes are unavailable"):
        await run_node(
            RevokeKnowledge(),
            scene=scene,
            inputs={"character": "Alice", "target": "Hidden Door"},
        )
    assert scene.world_state.knowledge == []


@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_director_callback_collection_omits_only_new_mode_revoke(scene, mode):
    scene.knowledge_eligibility = mode
    module = json.loads(
        Path(
            "src/talemate/agents/director/modules/instruct-character-changes.json"
        ).read_text()
    )
    node = module["nodes"]["1dc17802-3dd3-4a37-b4e8-6c123af30edc"]
    assert node["registry"] == "knowledge/KnowledgeCallbacks"
    callbacks = [
        SimpleNamespace(name=name)
        for name in ("set_known_by", "grant_knowledge", "revoke_knowledge")
    ]
    out = await run_node(KnowledgeCallbacks(), scene=scene, inputs={"list": callbacks})
    assert [item.name for item in out["list"]] == [
        item.name
        for item in callbacks
        if mode == "legacy" or item.name != "revoke_knowledge"
    ]


@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_instruct_character_changes_template_renders_with_shipped_scene_connection(
    scene, mode
):
    scene.knowledge_eligibility = mode
    module = json.loads(
        Path(
            "src/talemate/agents/director/modules/instruct-character-changes.json"
        ).read_text()
    )
    target_id = "ecaa252a-e8cf-40da-9c4f-7994c4c1795c"
    target = module["nodes"][target_id]
    producers = [
        (source, destination)
        for source, destinations in module["edges"].items()
        for destination in destinations
        if destination.startswith(target_id + ".")
        and module["nodes"][source.split(".")[0]]["registry"] == "scene/GetSceneState"
    ]
    assert len(producers) == 1
    source, destination = producers[0]
    producer = GetSceneState()
    node = Jinja2Format()
    node.dynamic_inputs = target["dynamic_inputs"]
    node.setup()
    node.set_property("template", target["properties"]["template"])
    node.set_property(
        "variables",
        {
            "instructions": "Give Alice knowledge of the hidden door.",
            "context_id_items": [],
            "context_id_types": [],
            "allowed_for_direct_update": [],
        },
    )
    graph = build_graph(producer, node)
    graph.connect(
        producer.get_output_socket(source.split(".")[1]),
        node.get_input_socket(destination.split(".")[1]),
    )
    rendered = []

    async def capture(state):
        rendered.append(node.get_output_socket("result").value)

    graph.callbacks.append(capture)
    await execute_graph(scene, graph)
    assert "Give Alice knowledge of the hidden door." in rendered[-1]
    assert ("Revocation and forgetting are unavailable" in rendered[-1]) == (
        mode == "perception"
    )
    assert ("`revoke_knowledge`" in rendered[-1]) == (mode == "legacy")
