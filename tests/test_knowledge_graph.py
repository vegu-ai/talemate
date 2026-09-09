"""
Fact graph queries and the knowledge nodes.
"""

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphContext
import talemate.game.engine.nodes.knowledge  # noqa: F401 - registers the nodes
from talemate.game.engine.nodes.registry import get_node
from talemate.knowledge.graph import (
    bucket,
    current_state,
    facts_about,
    relationship_timeline,
    superseded_chain,
)
from talemate.knowledge.schema import Fact, KnowledgeEdge


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    s.world_state.character_name_mappings = {"Edwin": ["the keeper", "Halloran"]}
    s.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="Edwin keeps the light.",
            ts=10,
            subjects=["Edwin"],
            present=["Edwin", "Mara"],
        ),
        "F2": Fact(
            id="F2",
            text="Mara found a sextant under the floor.",
            ts=20,
            subjects=["Mara", "sextant"],
            present=["Mara"],
        ),
        "F3": Fact(
            id="F3",
            text="The keeper told Mara about the Sorena.",
            ts=30,
            subjects=["Edwin", "Mara", "Sorena"],
            present=["Edwin", "Mara"],
        ),
        "F4": Fact(
            id="F4",
            text="Mara moved the sextant to her bag.",
            ts=40,
            subjects=["sextant"],
            present=["Mara"],
            supersedes="F2",
        ),
    }
    return s


class TestQueries:
    def test_facts_about_uses_subjects_text_and_aliases(self, scene):
        assert [f.id for f in facts_about(scene, "Edwin")] == ["F3", "F1"]
        assert [f.id for f in facts_about(scene, "halloran")] == ["F3", "F1"]
        assert [f.id for f in facts_about(scene, "sextant")] == ["F4"]

    def test_facts_about_filtered_by_character(self, scene):
        assert [f.id for f in facts_about(scene, "sextant", character="Edwin")] == []
        scene.world_state.knowledge = [KnowledgeEdge(character="Edwin", target="F4")]
        assert [f.id for f in facts_about(scene, "sextant", character="Edwin")] == [
            "F4"
        ]

    def test_relationship_timeline(self, scene):
        assert [f.id for f in relationship_timeline(scene, "Edwin", "Mara")] == ["F3"]

    def test_current_state_skips_superseded(self, scene):
        assert current_state(scene, "sextant").id == "F4"
        assert current_state(scene, "nothing") is None

    def test_superseded_chain_two_hops(self, scene):
        scene.world_state.facts["F5"] = Fact(id="F5", text="x", supersedes="F4", ts=50)
        scene.world_state.facts["F6"] = Fact(id="F6", text="y", supersedes="F5", ts=60)
        assert [f.id for f in superseded_chain(scene, "F6")] == ["F5", "F4"]
        assert superseded_chain(scene, "F6", hops=3)[-1].id == "F2"

    def test_ordering_survives_two_digit_ids(self, scene):
        scene.world_state.facts = {
            f"F{i}": Fact(
                id=f"F{i}",
                text=f"sextant fact {i}",
                ts=200 if i > 3 else 100,
                subjects=["sextant"],
            )
            for i in range(1, 15)
        }
        ordered = [f.id for f in facts_about(scene, "sextant")]
        assert ordered == [f"F{i}" for i in range(14, 0, -1)]
        assert current_state(scene, "sextant").id == "F14"

    def test_bucket_kinds(self, scene):
        scene.world_state.facts["F2"].known_by = {"Edwin": "told"}
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F2", source="told"),
            KnowledgeEdge(character="Edwin", target="F4", source="manual"),
        ]
        known = {f.id: kind for f, kind in bucket(scene, "Edwin")}
        assert known == {
            "F1": "witnessed",
            "F3": "witnessed",
            "F2": "told",
            "F4": "granted",
        }


async def run_node(node, scene, inputs):
    for k, v in inputs.items():
        node.set_property(k, v)
    with ActiveScene(scene):
        with GraphContext() as state:
            await node.run(state)
            return {sock.name: sock.value for sock in node.outputs}


class TestNodes:
    async def test_facts_about_node(self, scene):
        node = get_node("knowledge/FactsAbout")()
        out = await run_node(node, scene, {"entity": "sextant"})
        assert [f["id"] for f in out["facts"]] == ["F4"]
        assert out["text"].startswith("[F4]")

    async def test_current_state_node(self, scene):
        node = get_node("knowledge/CurrentState")()
        out = await run_node(node, scene, {"entity": "sextant"})
        assert (
            out["fact"]["id"] == "F4"
            and out["text"] == "(Recently) Mara moved the sextant to her bag."
        )

    async def test_relationship_timeline_node(self, scene):
        node = get_node("knowledge/RelationshipTimeline")()
        out = await run_node(node, scene, {"a": "Edwin", "b": "Mara"})
        assert [f["id"] for f in out["facts"]] == ["F3"]

    async def test_grant_and_revoke_nodes(self, scene):
        scene.ts = 99
        grant = get_node("knowledge/GrantKnowledge")()
        out = await run_node(
            grant, scene, {"character": "Edwin", "target": "F2", "note": "told by Mara"}
        )
        assert out["edge"]["kind"] == "grant" and out["edge"]["source"] == "granted"
        revoke = get_node("knowledge/RevokeKnowledge")()
        await run_node(revoke, scene, {"character": "Edwin", "target": "F1"})
        edges = [
            (e.character, e.target, e.kind, e.ts, e.note)
            for e in scene.world_state.knowledge
        ]
        assert edges == [
            ("Edwin", "F2", "grant", 99, "told by Mara"),
            ("Edwin", "F1", "revoke", 99, None),
        ]
