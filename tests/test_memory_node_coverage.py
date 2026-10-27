"""
The viewer input of Query Context DB and the Referenced Characters node.
"""

import pytest

from _node_test_helpers import run_node
from conftest import MockScene, bootstrap_scene
from talemate.agents.memory import nodes as memory_nodes
from talemate.agents.memory.nodes import QueryContextDB, ReferencedCharacters
from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.game.engine.nodes.core import InputValueError
from talemate.instance import get_agent
from talemate.knowledge.schema import KnowledgeEdge


def doc(id, meta, text="x"):
    return MemoryDocument(text, meta, id, text)


SEEN = doc("e1", {"typ": "history", "presence_known": True, "present": '["Alice"]'})
MISSED = doc("e3", {"typ": "history", "presence_known": True, "present": '["Bob"]'})
TOLD = doc("e2", {"typ": "history", "presence_known": True, "present": '["Bob"]'})


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    s.character_data = {
        name: Character(name=name) for name in ("Alice", "Bob", "Carol")
    }
    return s


@pytest.fixture
def queries(monkeypatch):
    calls = []

    async def multi_query(queries, **kwargs):
        calls.append(kwargs)
        return [d for d in (SEEN, MISSED, TOLD) if kwargs["filter"](d)]

    monkeypatch.setattr(get_agent("memory"), "multi_query", multi_query)
    return calls


class TestQueryContextDBViewer:
    @pytest.mark.asyncio
    async def test_standard_mode_filters_what_the_viewer_does_not_know(
        self, scene, queries
    ):
        scene.world_state.knowledge = [KnowledgeEdge(character="Alice", target="e2")]
        out = await run_node(
            QueryContextDB(),
            scene=scene,
            inputs={"queries": ["ledger"], "viewer": scene.character_data["Alice"]},
        )
        assert [d.id for d in out["results"]] == ["e1", "e2"]
        assert "viewer" not in queries[0]
        assert queries[0]["over_fetch"] == 3

    @pytest.mark.asyncio
    async def test_perspectives_mode_passes_the_viewer(self, scene, queries):
        scene.knowledge_eligibility = "perception"
        await run_node(
            QueryContextDB(),
            scene=scene,
            inputs={"queries": "ledger", "viewer": "Alice"},
        )
        assert queries[0]["viewer"] == "Alice"
        assert "over_fetch" not in queries[0]

    @pytest.mark.asyncio
    async def test_without_viewer_nothing_is_filtered(self, scene, queries):
        out = await run_node(
            QueryContextDB(), scene=scene, inputs={"queries": ["ledger"]}
        )
        assert len(out["results"]) == 3
        assert "viewer" not in queries[0]
        assert "over_fetch" not in queries[0]

    @pytest.mark.asyncio
    async def test_unknown_viewer_is_refused(self, scene, queries):
        with pytest.raises(InputValueError) as exc:
            await run_node(
                QueryContextDB(),
                scene=scene,
                inputs={"queries": ["ledger"], "viewer": "Zed"},
            )
        assert exc.value.input_name == "viewer"
        assert queries == []


class TestReferencedCharacters:
    @pytest.mark.asyncio
    async def test_names_and_aliases_without_a_decision_model(self, scene):
        scene.world_state.character_name_mappings = {"Carol": ["the Captain"]}
        out = await run_node(
            ReferencedCharacters(),
            scene=scene,
            inputs={"text": "Bob spoke of the Captain, not of alice."},
        )
        assert out["characters"] == ["Bob", "Carol"]

    @pytest.mark.asyncio
    async def test_candidates_limit_the_answer(self, scene):
        out = await run_node(
            ReferencedCharacters(),
            scene=scene,
            inputs={"text": "Bob and Carol argued.", "candidates": ["Carol"]},
        )
        assert out["characters"] == ["Carol"]

    @pytest.mark.asyncio
    async def test_state_input_gates_the_request(self, scene):
        # the decision model request runs only when a graph sends the state
        node = ReferencedCharacters()
        assert "state" in [socket.name for socket in node.inputs]
        out = await run_node(
            node,
            scene=scene,
            inputs={"state": "go", "text": "Bob and Carol argued."},
        )
        assert out["state"] == "go"

    @pytest.mark.asyncio
    async def test_uses_the_memory_policy_and_setting(self, scene, monkeypatch):
        calls = []

        async def referenced(scene, text, candidates, **kwargs):
            calls.append(kwargs)
            return candidates[:1]

        monkeypatch.setattr(memory_nodes, "referenced_characters", referenced)
        memory = get_agent("memory")
        monkeypatch.setattr(
            type(memory), "retrieval_entity_decision_model", property(lambda _: True)
        )
        out = await run_node(
            ReferencedCharacters(), scene=scene, inputs={"text": "her brother"}
        )
        assert out["characters"] == ["Alice"]
        assert calls[0]["uid"] == "memory.decision-entity-references"
        assert calls[0]["enabled"] is True

    @pytest.mark.asyncio
    async def test_the_answer_is_current_only_for_the_agent_scene(
        self, scene, monkeypatch
    ):
        calls = []

        async def referenced(scene, text, candidates, **kwargs):
            calls.append(kwargs)
            return []

        monkeypatch.setattr(memory_nodes, "referenced_characters", referenced)
        memory = get_agent("memory")
        monkeypatch.setattr(memory, "scene", scene, raising=False)
        await run_node(ReferencedCharacters(), scene=scene, inputs={"text": "x"})
        is_current = calls[0]["is_current"]
        assert is_current() is True
        monkeypatch.setattr(memory, "scene", object())
        assert is_current() is False

    @pytest.mark.asyncio
    async def test_unknown_candidate_is_refused(self, scene):
        with pytest.raises(InputValueError):
            await run_node(
                ReferencedCharacters(),
                scene=scene,
                inputs={"text": "x", "candidates": ["Zed"]},
            )
