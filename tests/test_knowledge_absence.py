"""
The absence block: recent facts minus the bucket minus near-duplicates.
"""

from unittest.mock import patch

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.absence import absence_facts
from talemate.knowledge.schema import Fact, KnowledgeEdge


def fact(id, text, ts, present, **kw):
    return Fact(id=id, text=text, ts=ts, present=present, **kw)


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    s.world_state.facts = {
        "F1": fact("F1", "Edwin keeps the light.", 10, ["Edwin", "Mara"]),
        "F2": fact("F2", "Mara found a sextant.", 20, ["Mara"]),
        "F3": fact(
            "F3", "Mara hid the sextant in her bag.", 30, ["Mara"], restatements=2
        ),
        "F4": fact("F4", "The boat leaks.", 40, ["Mara"]),
        "F5": fact("F5", "Edwin lies about the wreck.", 50, ["Mara"], false=True),
    }
    return s


class FakeMemory:
    def __init__(self, vectors, ready=True):
        self.vectors = vectors
        self.ready = ready

    async def get_embeddings(self, ids):
        return {i: self.vectors[i] for i in ids if i in self.vectors}


@pytest.fixture
def embeddings():
    # standalone on purpose: a `scene` dependency would re-bootstrap the agents
    vectors = {}
    with patch(
        "talemate.knowledge.absence.get_agent", return_value=FakeMemory(vectors)
    ):
        yield vectors


class TestAbsenceFacts:
    async def test_unknown_facts_ordered_by_restatements_then_recency(
        self, scene, embeddings
    ):
        result = await absence_facts(scene, "Edwin")
        assert [f.id for f in result] == ["F3", "F4", "F2"]

    async def test_cap_and_window(self, scene, embeddings):
        assert [f.id for f in await absence_facts(scene, "Edwin", limit=1)] == ["F3"]
        # a window of two keeps only F4 and F5 (F5 is false: dropped)
        assert [f.id for f in await absence_facts(scene, "Edwin", window=2)] == ["F4"]

    async def test_known_character_gets_nothing(self, scene, embeddings):
        assert await absence_facts(scene, "Mara") == []

    async def test_grant_removes_from_the_block(self, scene, embeddings):
        scene.world_state.knowledge = [KnowledgeEdge(character="Edwin", target="F3")]
        assert [f.id for f in await absence_facts(scene, "Edwin")] == ["F4", "F2"]

    async def test_false_fact_shown_only_when_granted(self, scene, embeddings):
        assert "F5" not in [f.id for f in await absence_facts(scene, "Edwin")]
        scene.world_state.knowledge = [KnowledgeEdge(character="Carol", target="F5")]
        # Carol holds the grant so F5 is in her bucket; it never lists for her,
        # and Edwin without a grant still never sees it
        assert "F5" not in [f.id for f in await absence_facts(scene, "Edwin")]

    async def test_near_duplicate_of_a_known_fact_is_dropped(self, scene, embeddings):
        # Edwin was told a retelling of F3; the retelling F6 is in his bucket
        scene.world_state.facts["F6"] = fact(
            "F6", "Mara has the sextant in her bag.", 60, ["Edwin", "Mara"]
        )
        embeddings.update(
            {"F3": [1.0, 0.0], "F6": [0.95, 0.05], "F2": [0.0, 1.0], "F4": [0.5, 0.5]}
        )
        result = await absence_facts(scene, "Edwin", dedupe_distance=0.15)
        assert [f.id for f in result] == ["F4", "F2"]

    async def test_missing_embeddings_keep_the_fact(self, scene, embeddings):
        embeddings.update({"F1": [1.0, 0.0]})
        assert "F3" in [f.id for f in await absence_facts(scene, "Edwin")]

    async def test_offscreen_facts_are_never_listed(self, scene, embeddings):
        scene.world_state.facts["F7"] = fact(
            "F7", "Edwin mended nets alone.", 70, ["Edwin"], source="offscreen"
        )
        assert "F7" not in [f.id for f in await absence_facts(scene, "Mara")]

    async def test_backend_not_ready_is_tolerated(self, scene):
        # a backend that is not ready skips the near-duplicate step
        with patch(
            "talemate.knowledge.absence.get_agent",
            return_value=FakeMemory({}, ready=False),
        ):
            assert [f.id for f in await absence_facts(scene, "Edwin")] == [
                "F3",
                "F4",
                "F2",
            ]


class TestConversationContainer:
    async def test_perspective_and_block_follow_the_switches(self, scene, embeddings):
        conversation = get_agent("conversation")
        edwin = Character(name="Edwin")
        with ActiveScene(scene):
            assert await conversation.knowledge_perspective(edwin) == "Edwin"
            assert await conversation.knowledge_perspective(None) is None
            assert conversation.rag_knowledge_filter(edwin) is not None
            lines = await conversation.absence_block(edwin)
            assert lines == [
                "Mara hid the sextant in her bag.",
                "The boat leaks.",
                "Mara found a sextant.",
            ]

            conversation.actions["character_knowledge"].config[
                "perspective_filter"
            ].value = False
            assert await conversation.knowledge_perspective(edwin) is None
            assert conversation.rag_knowledge_filter(edwin) is None

            conversation.actions["character_knowledge"].config[
                "absence_block"
            ].value = False
            assert await conversation.absence_block(edwin) == []

            conversation.actions["character_knowledge"].config[
                "perspective_filter"
            ].value = True
            conversation.actions["character_knowledge"].config[
                "absence_block"
            ].value = True
            conversation.actions["character_knowledge"].enabled = False
            assert await conversation.knowledge_perspective(edwin) is None
            assert await conversation.absence_block(edwin) == []
            conversation.actions["character_knowledge"].enabled = True

    async def test_limit_setting(self, scene, embeddings):
        conversation = get_agent("conversation")
        conversation.actions["character_knowledge"].config["absence_limit"].value = 1
        try:
            with ActiveScene(scene):
                assert await conversation.absence_block(Character(name="Edwin")) == [
                    "Mara hid the sextant in her bag."
                ]
        finally:
            conversation.actions["character_knowledge"].config[
                "absence_limit"
            ].value = 5
