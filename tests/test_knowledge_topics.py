"""
Topics (#394 part E): clustering, refresh, coverage, awareness line,
topic-first retrieval.
"""

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from conftest import MockScene, bootstrap_scene
from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.schema import Fact, KnowledgeEdge, Topic
from talemate.scene_message import CharacterMessage
from talemate.knowledge.topics import (
    awareness_line,
    cluster_facts,
    coverage,
    prune_topics,
    refresh_topics,
    topics_on_load,
)


def fact(id, text, ts, present, subjects=(), **kw):
    return Fact(id=id, text=text, ts=ts, present=present, subjects=list(subjects), **kw)


# ---------------------------------------------------------------------------
# clustering
# ---------------------------------------------------------------------------


class TestClustering:
    def test_leader_clustering_and_names(self):
        facts = [
            fact("F1", "a", 10, None, ["Sorena", "wreck"]),
            fact("F2", "b", 20, None, ["Sorena"]),
            fact("F3", "c", 30, None, ["sextant"]),
        ]
        vectors = {"F1": [1.0, 0.0], "F2": [0.98, 0.2], "F3": [0.0, 1.0]}
        topics = cluster_facts(facts, vectors, 0.8)
        assert [(t.id, t.name, t.fact_ids) for t in topics] == [
            ("T1", "Sorena", ["F1", "F2"]),
            ("T2", "sextant", ["F3"]),
        ]

    def test_deterministic_and_order_by_creation(self):
        facts = [
            fact("F10", "x", 5, None),
            fact("F2", "y", 5, None),
            fact("F1", "z", 1, None),
        ]
        vectors = {"F1": [1.0, 0.0], "F2": [0.0, 1.0], "F10": [0.0, 0.99]}
        first = cluster_facts(facts, vectors, 0.8)
        again = cluster_facts(list(reversed(facts)), vectors, 0.8)
        assert [t.fact_ids for t in first] == [["F1"], ["F2", "F10"]]
        assert [t.fact_ids for t in again] == [t.fact_ids for t in first]

    def test_refinement_moves_a_fact_to_its_nearest_centroid(self):
        # F2 joins T1 on the greedy pass (just above the threshold) but sits
        # nearer the centroid that T2 grows into
        # F2 joins T1 on the greedy pass (exactly 0.8 to its leader F1); the
        # three facts that open T2 pull its centroid to where F2 is nearer,
        # so the refinement moves F2 there and F1 stays alone
        facts = [fact(f"F{i}", "t", i, None) for i in range(1, 6)]
        vectors = {
            "F1": [1.0, 0.0],
            "F2": [0.8, 0.6],
            "F3": [0.6, 0.8],
            "F4": [0.65, 0.76],
            "F5": [0.7, 0.714],
        }
        topics = cluster_facts(facts, vectors, 0.8)
        by_fact = {i: t.id for t in topics for i in t.fact_ids}
        assert by_fact["F2"] == by_fact["F3"] == by_fact["F4"] == by_fact["F5"]
        assert by_fact["F1"] != by_fact["F2"]

    def test_admission_compares_with_the_leader_not_a_drifting_centroid(self):
        # F2 and F3 each sit at 0.8 from the leader F1 but not from each other;
        # both join T1 because the leader is held fixed for the admission test
        facts = [fact(f"F{i}", "t", i, None) for i in range(1, 4)]
        vectors = {"F1": [1.0, 0.0], "F2": [0.8, 0.6], "F3": [0.8, -0.6]}
        topics = cluster_facts(facts, vectors, 0.8)
        assert [t.fact_ids for t in topics] == [["F1", "F2", "F3"]]

    def test_named_flag_and_comma_phrases(self):
        facts = [
            fact("F1", "a", 1, None, ["Sorena, the ship"]),
            fact("F2", "b", 2, None, ["Sorena, the ship"]),
            fact("F3", "c", 3, None),
        ]
        vectors = {"F1": [1.0, 0.0], "F2": [0.99, 0.1], "F3": [0.0, 1.0]}
        topics = cluster_facts(facts, vectors, 0.8)
        assert [(t.name, t.named) for t in topics] == [
            ("Sorena", True),
            ("topic 2", False),
        ]

    def test_two_topics_never_share_a_name(self):
        facts = [
            fact("F1", "a", 1, None, ["Sorena, the ship"]),
            fact("F2", "b", 2, None, ["Sorena, the ship"]),
            fact("F3", "c", 3, None, ["Sorena, the captain"]),
            fact("F4", "d", 4, None, ["Sorena, the captain"]),
        ]
        vectors = {
            "F1": [1.0, 0.0],
            "F2": [0.99, 0.1],
            "F3": [0.0, 1.0],
            "F4": [0.1, 0.99],
        }
        topics = cluster_facts(facts, vectors, 0.8)
        assert [t.name for t in topics] == ["Sorena, the ship", "Sorena, the captain"]

    def test_shape_report_reads_the_facts_not_the_topics(self):
        from talemate.knowledge.topics import _report_shape

        def topic(i, n):
            return Topic(
                id=f"T{i}", name=f"t{i}", fact_ids=[f"F{i}_{k}" for k in range(n)]
            )

        def verdict(topics):
            with patch("talemate.knowledge.topics.log") as log:
                _report_shape(topics)
            return " ".join(str(c.args[0]) for c in log.warning.call_args_list)

        # 56 on one theme + 4 unrelated: a blob, not dust
        text = verdict([topic(1, 56)] + [topic(i, 1) for i in range(2, 6)])
        assert "too low" in text and "too high" not in text
        # 50 + 10 unrelated: still a blob (83 percent), never "too high"
        text = verdict([topic(1, 50)] + [topic(i, 1) for i in range(2, 12)])
        assert "too low" in text and "too high" not in text
        assert "too high" in verdict([topic(i, 1) for i in range(1, 11)])
        # one clustered fact (the others had no vector): no verdict
        assert verdict([topic(1, 1)]) == ""

    def test_missing_vector_left_out_and_fallback_name(self):
        facts = [fact("F1", "a", 1, None), fact("F2", "b", 2, None)]
        topics = cluster_facts(facts, {"F1": [1.0, 0.0]}, 0.8)
        assert [(t.name, t.fact_ids) for t in topics] == [("topic 1", ["F1"])]
        assert cluster_facts(facts, {}, 0.8) == []

    def test_threshold_one_never_merges(self):
        facts = [fact("F1", "a", 1, None), fact("F2", "b", 2, None)]
        vectors = {"F1": [1.0, 0.0], "F2": [0.99, 0.1]}
        assert len(cluster_facts(facts, vectors, 0.999)) == 2


# ---------------------------------------------------------------------------
# refresh + on load
# ---------------------------------------------------------------------------


class FakeMemory:
    def __init__(self, vectors, ready=True, enabled=True, step=20, threshold=0.8):
        self.vectors = vectors
        self.ready = ready
        self.topics_enabled = enabled
        self.topics_recluster_step = step
        self.topics_similarity_threshold = threshold
        self.topic_centroids = {}
        self.rebuild_topic_centroids = AsyncMock(return_value={})

    async def get_embeddings(self, ids):
        return {i: self.vectors[i] for i in ids if i in self.vectors}


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    s.world_state.facts = {
        "F1": fact("F1", "Edwin keeps the light.", 10, ["Edwin", "Mara"], ["Edwin"]),
        "F2": fact(
            "F2", "Edwin was keeper for years.", 20, ["Edwin", "Mara"], ["Edwin"]
        ),
        "F3": fact("F3", "Mara found a sextant.", 30, ["Mara"], ["sextant"]),
    }
    return s


VECTORS = {"F1": [1.0, 0.0], "F2": [0.97, 0.24], "F3": [0.0, 1.0]}


class TestRefresh:
    async def test_first_run_clusters_and_records_the_count(self, scene):
        memory = FakeMemory(VECTORS)
        with patch("talemate.knowledge.topics.get_agent", return_value=memory):
            assert await refresh_topics(scene) is True
        assert [t.fact_ids for t in scene.world_state.topics.values()] == [
            ["F1", "F2"],
            ["F3"],
        ]
        assert scene.world_state.topics_fact_count == 3
        assert set(memory.topic_centroids) == {"T1", "T2"}
        np.testing.assert_allclose(memory.topic_centroids["T2"], [0.0, 1.0])

    async def test_step_gates_a_second_run(self, scene):
        memory = FakeMemory(VECTORS, step=5)
        with patch("talemate.knowledge.topics.get_agent", return_value=memory):
            await refresh_topics(scene)
            scene.world_state.facts["F4"] = fact("F4", "x", 40, None)
            memory.vectors["F4"] = [0.0, 0.9]
            assert await refresh_topics(scene) is False
            assert scene.world_state.topics_fact_count == 3
            assert await refresh_topics(scene, force=True) is True
            assert scene.world_state.topics_fact_count == 4
            for n in range(5, 10):
                scene.world_state.facts[f"F{n}"] = fact(f"F{n}", "y", n * 10, None)
                memory.vectors[f"F{n}"] = [0.0, 1.0]
            assert await refresh_topics(scene) is True

    async def test_a_shrink_counts_toward_the_step(self, scene):
        memory = FakeMemory(VECTORS, step=2)
        with patch("talemate.knowledge.topics.get_agent", return_value=memory):
            await refresh_topics(scene)
            del scene.world_state.facts["F2"]
            assert await refresh_topics(scene) is False
            del scene.world_state.facts["F3"]
            assert await refresh_topics(scene) is True
            assert [t.fact_ids for t in scene.world_state.topics.values()] == [["F1"]]

    async def test_prune_drops_dead_ids_when_the_store_is_away(self, scene):
        memory = FakeMemory(VECTORS)
        with patch("talemate.knowledge.topics.get_agent", return_value=memory):
            await refresh_topics(scene)
            del scene.world_state.facts["F3"]
            memory.ready = False
            assert await refresh_topics(scene, force=True) is False
        assert [t.fact_ids for t in scene.world_state.topics.values()] == [["F1", "F2"]]
        assert scene.world_state.topics_fact_count == 2
        assert prune_topics(scene.world_state) is False

    async def test_disabled_or_not_ready_keeps_topics(self, scene):
        with patch(
            "talemate.knowledge.topics.get_agent",
            return_value=FakeMemory(VECTORS, enabled=False),
        ):
            assert await refresh_topics(scene, force=True) is False
        assert scene.world_state.topics == {}
        with patch(
            "talemate.knowledge.topics.get_agent",
            return_value=FakeMemory(VECTORS, ready=False),
        ):
            assert await refresh_topics(scene, force=True) is False
        with patch("talemate.knowledge.topics.get_agent", return_value=FakeMemory({})):
            assert await refresh_topics(scene, force=True) is False

    async def test_no_facts_clears_the_topics(self, scene):
        memory = FakeMemory(VECTORS)
        with patch("talemate.knowledge.topics.get_agent", return_value=memory):
            await refresh_topics(scene)
            scene.world_state.facts = {}
            assert await refresh_topics(scene) is False
        assert (
            scene.world_state.topics == {} and scene.world_state.topics_fact_count == 0
        )
        assert memory.topic_centroids == {}

    async def test_on_load_clusters_when_nothing_is_stored(self, scene):
        memory = FakeMemory(VECTORS)
        with patch("talemate.knowledge.topics.get_agent", return_value=memory):
            await topics_on_load(scene)
        assert len(scene.world_state.topics) == 2
        memory.rebuild_topic_centroids.assert_not_called()

    async def test_on_load_rebuilds_centroids_for_stored_topics(self, scene):
        scene.world_state.topics = {
            "T1": Topic(id="T1", name="Edwin", fact_ids=["F1", "F2", "F3"])
        }
        scene.world_state.topics_fact_count = 3
        memory = FakeMemory(VECTORS)
        with patch("talemate.knowledge.topics.get_agent", return_value=memory):
            await topics_on_load(scene)
        memory.rebuild_topic_centroids.assert_awaited_once_with(scene)
        assert list(scene.world_state.topics) == ["T1"]


# ---------------------------------------------------------------------------
# coverage + awareness
# ---------------------------------------------------------------------------


@pytest.fixture
def topical(scene):
    ws = scene.world_state
    ws.facts = {}
    # A: 4 facts, all known to Edwin; B: 3 facts, one known; C: 3 facts, none; D: 2 facts (below the line's minimum)
    for n in range(1, 5):
        ws.facts[f"F{n}"] = fact(f"F{n}", "a", n, ["Edwin", "Mara"], ["Sorena"])
    ws.facts["F5"] = fact("F5", "b", 5, ["Edwin", "Mara"], ["sextant"])
    ws.facts["F6"] = fact("F6", "b", 6, ["Mara"], ["sextant"])
    ws.facts["F7"] = fact("F7", "b", 7, ["Mara"], ["sextant"])
    for n in range(8, 11):
        ws.facts[f"F{n}"] = fact(f"F{n}", "c", n, ["Mara"], ["boat"])
    ws.facts["F11"] = fact("F11", "d", 11, ["Mara"], ["ledger"])
    ws.facts["F12"] = fact("F12", "d", 12, ["Mara"], ["ledger"])
    ws.topics = {
        "T1": Topic(id="T1", name="Sorena", fact_ids=["F1", "F2", "F3", "F4"]),
        "T2": Topic(id="T2", name="sextant", fact_ids=["F5", "F6", "F7"]),
        "T3": Topic(id="T3", name="boat", fact_ids=["F8", "F9", "F10"]),
        "T4": Topic(id="T4", name="ledger", fact_ids=["F11", "F12"]),
    }
    return scene


class TestCoverage:
    def test_rows_largest_first(self, topical):
        rows = coverage(topical, "Edwin")
        assert [(r.id, r.known, r.total) for r in rows] == [
            ("T1", 4, 4),
            ("T2", 1, 3),
            ("T3", 0, 3),
            ("T4", 0, 2),
        ]
        assert coverage(topical, "Mara")[1].known == 3

    def test_grants_and_revokes_count(self, topical):
        topical.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F6"),
            KnowledgeEdge(character="Edwin", target="F1", kind="revoke"),
        ]
        rows = {r.id: r for r in coverage(topical, "Edwin")}
        assert rows["T1"].known == 3 and rows["T2"].known == 2

    def test_missing_member_ids_are_ignored(self, topical):
        topical.world_state.topics["T5"] = Topic(id="T5", name="gone", fact_ids=["F99"])
        assert [r.id for r in coverage(topical, "Edwin")] == ["T1", "T2", "T3", "T4"]


class TestAwarenessLine:
    def test_all_some_nothing(self, topical):
        assert (
            awareness_line(topical, "Edwin")
            == "Edwin knows all of Sorena, some of sextant, nothing of boat"
        )
        assert (
            awareness_line(topical, "Mara")
            == "Mara knows all of Sorena, all of sextant, all of boat"
        )

    def test_topics_named_for_one_character_merge_into_one_clause(self, topical):
        from talemate.character import Character

        ws = topical.world_state
        topical.character_data["Nora"] = Character(name="Nora")
        topical.character_data["Sterling Slobberton"] = Character(
            name="Sterling Slobberton"
        )
        ws.character_name_mappings = {"Sterling Slobberton": ["Sterling"]}
        # two topics carry Nora's name; Edwin knows the Sorena facts only
        ws.topics["T1"].name = "Nora"
        ws.topics["T3"].name = "nora"
        ws.topics["T2"].name = "Sterling"
        ws.topics["T4"].name = "boat"
        assert (
            awareness_line(topical, "Edwin")
            == "Edwin knows some of Nora, some of Sterling Slobberton"
        )
        # a merged row that falls under the minimum is left out too
        ws.topics["T4"].fact_ids = ["F11"]
        assert (
            awareness_line(topical, "Mara")
            == "Mara knows all of Nora, all of Sterling Slobberton"
        )

    def test_small_topics_do_not_qualify(self, topical):
        topical.world_state.topics = {"T4": topical.world_state.topics["T4"]}
        assert awareness_line(topical, "Edwin") is None

    def test_speaker_name_and_placeholders_are_left_out(self, topical):
        ws = topical.world_state
        ws.topics["T1"].name = "Edwin"
        ws.topics["T3"].name = "topic 3"
        ws.topics["T3"].named = False
        assert awareness_line(topical, "Edwin") == "Edwin knows some of sextant"
        # the comparison ignores case
        ws.topics["T1"].name = "edwin"
        assert awareness_line(topical, "Edwin") == "Edwin knows some of sextant"
        ws.topics["T1"].name = "Edwin"
        # Mara is not the speaker named in T1: it stays for her
        assert (
            awareness_line(topical, "Mara") == "Mara knows all of Edwin, all of sextant"
        )

    def test_memory_topics_switch_stops_coverage_and_the_line(self, topical):
        memory = get_agent("memory")
        memory.actions["topics"].enabled = False
        try:
            assert coverage(topical, "Edwin") == []
            assert awareness_line(topical, "Edwin") is None
        finally:
            memory.actions["topics"].enabled = True
        assert coverage(topical, "Edwin")

    def test_cap_at_six_largest(self, topical):
        ws = topical.world_state
        for k in range(5, 13):
            ids = []
            for m in range(3):
                fid = f"F{100 + k * 10 + m}"
                ws.facts[fid] = fact(fid, "e", 200 + k, ["Mara"], [f"topic{k}"])
                ids.append(fid)
            ws.topics[f"T{k}"] = Topic(id=f"T{k}", name=f"topic{k}", fact_ids=ids)
        line = awareness_line(topical, "Edwin")
        assert line.startswith(
            "Edwin knows all of Sorena, some of sextant, nothing of "
        )
        assert line.count(",") + line.count(" and ") <= 6

    async def test_conversation_switch(self, topical):
        conversation = get_agent("conversation")
        edwin = Character(name="Edwin")
        try:
            with ActiveScene(topical):
                assert (await conversation.awareness_line(edwin)).startswith(
                    "Edwin knows"
                )
                conversation.actions["character_knowledge"].config[
                    "awareness_line"
                ].value = False
                assert await conversation.awareness_line(edwin) is None
                conversation.actions["character_knowledge"].config[
                    "awareness_line"
                ].value = True
                conversation.actions["character_knowledge"].enabled = False
                assert await conversation.awareness_line(edwin) is None
        finally:
            conversation.actions["character_knowledge"].config[
                "awareness_line"
            ].value = True
            conversation.actions["character_knowledge"].enabled = True


# ---------------------------------------------------------------------------
# memory agent: settings, centroids, topic-first retrieval
# ---------------------------------------------------------------------------


def doc(id, text, distance=0.3, typ="history"):
    return MemoryDocument(text, {"typ": typ}, id, text, distance=distance)


class TestMemoryTopics:
    @pytest.fixture
    def memory(self, topical):
        memory = get_agent("memory")
        memory.db = object()
        memory.calls = []
        table = {
            f: [1.0, 0.0] if f in ("F1", "F2", "F3", "F4") else [0.0, 1.0]
            for f in topical.world_state.facts
        }
        memory._get_embeddings = lambda ids: {i: table[i] for i in ids if i in table}
        memory.table = []

        async def fake_get(text, character=None, limit=15, **where):
            memory.calls.append(text)
            return list(memory.table)

        memory.get = fake_get
        yield memory
        memory.db = None
        memory.topic_centroids = {}
        memory.actions["topics"].enabled = True

    def test_defaults(self, memory):
        assert memory.topics_enabled is True
        assert memory.topics_recluster_step == 20
        # 0 in the setting: the embedding preset's model-dependent value
        assert memory.actions["topics"].config["similarity_threshold"].value == 0
        assert memory.topics_similarity_threshold == pytest.approx(0.50)

    def test_setting_overrides_the_preset(self, memory):
        from talemate.config.schema import EmbeddingFunctionPreset

        assert EmbeddingFunctionPreset().topic_threshold == pytest.approx(0.5)
        with patch.object(
            type(memory),
            "embeddings_config",
            new=EmbeddingFunctionPreset(topic_threshold=0.42),
        ):
            assert memory.topics_similarity_threshold == pytest.approx(0.42)
            memory.actions["topics"].config["similarity_threshold"].value = 0.7
            try:
                assert memory.topics_similarity_threshold == pytest.approx(0.7)
            finally:
                memory.actions["topics"].config["similarity_threshold"].value = 0

    async def test_rebuild_centroids(self, topical, memory):
        centroids = await memory.rebuild_topic_centroids(topical)
        assert set(centroids) == {"T1", "T2", "T3", "T4"}
        np.testing.assert_allclose(centroids["T1"], [1.0, 0.0])
        assert memory.nearest_topic(np.array([0.99, 0.1])) == "T1"
        assert memory.nearest_topic(np.array([-1.0, 0.0])) is None

    async def test_topic_first_adds_the_highest_scored_facts(self, topical, memory):
        topical.world_state.facts["F3"].restatements = 5
        for identity, fact in topical.world_state.facts.items():
            fact.text = f"Distinct fact {identity}"
        await memory.rebuild_topic_centroids(topical)
        memory.table = [
            doc("F1", "fact one", 0.2, typ="fact"),
            doc("e1", "history", 0.3),
        ]
        docs = {i: doc(i, f"fact {i}", typ="fact") for i in ("F2", "F3", "F4")}
        memory.get_document = AsyncMock(return_value=docs)
        with (
            ActiveScene(topical),
            patch.object(
                memory, "embed_text", AsyncMock(return_value=np.array([1.0, 0.0]))
            ),
        ):
            result = await memory.multi_query(
                ["the Sorena"], iterate=5, topic_first=True
            )
        # Repetition count alone does not make F3 fresher than F4.
        assert [item.id for item in result[:4]] == ["F4", "F3", "F2", "F1"]
        assert [str(item) for item in result[:4]] == [
            f"(Recently) Distinct fact {identity}"
            for identity in ("F4", "F3", "F2", "F1")
        ]
        assert "history" in result
        assert memory.get_document.call_args.args[0] == ["F4", "F3", "F2"]

    async def test_topic_first_without_predecessors_keeps_the_cheap_bucket_path(
        self, topical, memory
    ):
        await memory.rebuild_topic_centroids(topical)
        memory.get_document = AsyncMock(
            return_value={i: doc(i, "fact", typ="fact") for i in ("F2", "F3", "F4")}
        )
        with (
            ActiveScene(topical),
            patch.object(
                memory, "embed_text", AsyncMock(return_value=np.array([1.0, 0.0]))
            ),
            patch(
                "talemate.agents.memory.known_bucket",
                side_effect=AssertionError("Unnecessary predecessor bucket build"),
            ),
            patch(
                "talemate.knowledge.topics.known_bucket",
                side_effect=AssertionError("Unnecessary supersession bucket build"),
            ),
        ):
            result = await memory._topic_first(
                "the Sorena", [], None, ranking_viewer="Bob"
            )
        assert [item.id for item in result] == ["F4", "F3", "F2"]

    async def test_topic_first_respects_the_filter_and_the_switch(
        self, topical, memory
    ):
        for identity, fact in topical.world_state.facts.items():
            fact.text = f"Distinct fact {identity}"
        await memory.rebuild_topic_centroids(topical)
        memory.table = [doc("e1", "history", 0.3)]
        docs = {i: doc(i, f"fact {i}", typ="fact") for i in ("F2", "F3", "F4")}
        memory.get_document = AsyncMock(return_value=docs)
        with (
            ActiveScene(topical),
            patch.object(
                memory, "embed_text", AsyncMock(return_value=np.array([1.0, 0.0]))
            ),
        ):
            # newest three of T1 are F4, F3, F2; the filter drops F2
            result = await memory.multi_query(
                ["q"], iterate=5, filter=lambda d: d.id != "F2", topic_first=True
            )
            assert [item.id for item in result] == ["F4", "F3", "e1"]
            assert [str(item) for item in result] == [
                "(Recently) Distinct fact F4",
                "(Recently) Distinct fact F3",
                "history",
            ]
            memory.actions["topics"].enabled = False
            assert await memory.multi_query(["q"], iterate=5, topic_first=True) == [
                "history"
            ]

    async def test_topic_first_is_opt_in_and_off_under_a_metadata_condition(
        self, topical, memory
    ):
        await memory.rebuild_topic_centroids(topical)
        memory.table = [doc("e1", "history", 0.3)]
        memory.get_document = AsyncMock(
            return_value={
                i: doc(i, f"fact {i}", typ="fact") for i in ("F2", "F3", "F4")
            }
        )
        embed = AsyncMock(return_value=np.array([1.0, 0.0]))
        with ActiveScene(topical), patch.object(memory, "embed_text", embed):
            # the default: no topic-first
            assert await memory.multi_query(["q"], iterate=5) == ["history"]
            # a metadata condition (Context Database tag filter, node
            # meta_filters) turns it off
            assert await memory.multi_query(
                ["q"], iterate=5, topic_first=True, typ="history"
            ) == ["history"]
            # the formatted query selects the topic
            await memory.multi_query(
                ["q"], iterate=5, topic_first=True, formatter=lambda q: f"formatted {q}"
            )
        assert embed.await_args.args[0] == "formatted q"
        memory.get_document.assert_called_once()

    async def test_prompt_retrieval_asks_for_topic_first(self, topical, memory):
        conversation = get_agent("conversation")
        topical.history = [CharacterMessage(message="Mara: a line")]
        with (
            ActiveScene(topical),
            patch.object(memory, "multi_query", AsyncMock(return_value=[])) as mq,
        ):
            await conversation.semantic_context()
        assert mq.call_args.kwargs["topic_first"] is True

    async def test_no_embedding_function_means_no_topic_first(self, topical, memory):
        await memory.rebuild_topic_centroids(topical)
        memory.table = [doc("e1", "history", 0.3)]
        memory.get_document = AsyncMock(return_value={})
        with ActiveScene(topical):
            # the mock memory agent has no embedding function: embed_text is None
            assert await memory.multi_query(["q"], iterate=5, topic_first=True) == [
                "history"
            ]
        memory.get_document.assert_not_called()


# ---------------------------------------------------------------------------
# world state manager payload
# ---------------------------------------------------------------------------


class TestManagerPayload:
    async def test_character_knowledge_carries_coverage_and_awareness(self, topical):
        from talemate.world_state.manager import WorldStateManager

        manager = WorldStateManager(topical)
        with ActiveScene(topical):
            knowledge = await manager.get_character_knowledge("Edwin")
        assert [(r.id, r.known, r.total) for r in knowledge.coverage][:2] == [
            ("T1", 4, 4),
            ("T2", 1, 3),
        ]
        assert knowledge.awareness.startswith("Edwin knows all of Sorena")
        payload = knowledge.model_dump()
        assert payload["coverage"][0]["name"] == "Sorena"
        assert "awareness" in payload


class TestKnownFacts:
    def test_newest_known_facts_first_with_the_full_count(self, topical):
        from talemate.knowledge.topics import known_facts

        recent, total = known_facts(topical, "Edwin", limit=3)
        assert [fact.id for fact in recent] == ["F5", "F4", "F3"]
        assert [fact.topic for fact in recent] == ["sextant", "Sorena", "Sorena"]
        assert total == 5
        recent, total = known_facts(topical, "Mara")
        assert [fact.id for fact in recent] == ["F12", "F11", "F10", "F9", "F8"]
        assert total == 12

    def test_a_limit_of_zero_lists_nothing_but_still_counts(self, topical):
        from talemate.knowledge.topics import known_facts

        assert known_facts(topical, "Edwin", limit=0) == ([], 5)

    def test_the_list_survives_the_topics_switch_but_the_labels_follow_it(
        self, topical
    ):
        from talemate.knowledge.topics import known_facts

        get_agent("memory").actions["topics"].enabled = False
        recent, total = known_facts(topical, "Edwin")
        assert [fact.id for fact in recent] == ["F5", "F4", "F3", "F2", "F1"]
        assert [fact.topic for fact in recent] == [None] * 5
        assert total == 5

    async def test_handler_payload_carries_the_capped_facts(self, topical):
        from talemate.server.world_state_manager.knowledge import KnowledgeMixin

        class Handler(KnowledgeMixin):
            def __init__(self, scene):
                self.scene = scene
                self.sent = []
                self.websocket_handler = type(
                    "W", (), {"queue_put": lambda _self, m: self.sent.append(m)}
                )()

            @property
            def world_state_manager(self):
                from talemate.world_state.manager import WorldStateManager

                return WorldStateManager(self.scene)

        handler = Handler(topical)
        with ActiveScene(topical):
            await handler.handle_get_character_knowledge({"name": "Mara"})
        payload = handler.sent[-1]
        assert payload["action"] == "character_knowledge"
        assert [fact["id"] for fact in payload["data"]["known_facts"]] == [
            "F12",
            "F11",
            "F10",
            "F9",
            "F8",
        ]
        assert payload["data"]["known_facts"][0]["topic"] == "ledger"
        assert payload["data"]["known_facts_total"] == 12


class TestMutationPathsRecluster:
    async def test_delete_and_update_force_a_refresh(self, topical):
        from talemate.server.world_state_manager.knowledge import KnowledgeMixin

        class Handler(KnowledgeMixin):
            def __init__(self, scene):
                self.scene = scene
                self.sent = []
                self.websocket_handler = type(
                    "W", (), {"queue_put": lambda _self, m: self.sent.append(m)}
                )()

            async def signal_operation_done(self, *a, **k):
                pass

        handler = Handler(topical)
        with (
            ActiveScene(topical),
            patch(
                "talemate.server.world_state_manager.knowledge.refresh_topics",
                AsyncMock(),
            ) as refresh,
            patch.object(get_agent("memory"), "delete", AsyncMock()),
        ):
            await handler.handle_delete_fact({"fact_id": "F12"})
            assert "F12" not in topical.world_state.facts
            await handler.handle_update_fact(
                {"fact_id": "F1", "text": "edited", "importance": 2}
            )
        assert refresh.await_count == 2
        assert all(c.kwargs.get("force") is True for c in refresh.await_args_list)

    async def test_dropping_an_entry_prunes_the_topics(self, topical):
        from talemate.knowledge.facts import drop_facts_for_entries

        ws = topical.world_state
        for fid in ("F5", "F6"):
            ws.facts[fid].archive_id = "arch-1"
        with (
            ActiveScene(topical),
            patch.object(get_agent("memory"), "delete", AsyncMock()),
        ):
            await drop_facts_for_entries(topical, {"arch-1"})
        assert ws.topics["T2"].fact_ids == ["F7"]
        assert ws.topics_fact_count == len(ws.facts)

    async def test_preset_change_clears_the_grouping(self, topical):
        memory = get_agent("memory")
        topical.active = True
        with (
            ActiveScene(topical),
            patch.object(memory, "close_db"),
            patch.object(topical, "commit_to_memory", AsyncMock()),
            patch.object(topical, "save", AsyncMock()),
            patch("talemate.agents.memory.emit"),
        ):
            memory.topic_centroids = {"T1": np.array([1.0, 0.0])}
            await memory.handle_embeddings_change()
        assert topical.world_state.topics == {}
        assert topical.world_state.topics_fact_count == 0
        assert memory.topic_centroids == {}

    async def test_regenerate_paths_force_a_refresh(self, topical):
        from talemate.history import ArchiveEntry, HistoryEntry

        summarizer = get_agent("summarizer")
        entry = ArchiveEntry(
            id="arch-1", text="An entry.", ts=10, present=["Mara"], start=0, end=3
        )
        topical.archived_history = [entry.model_dump()]
        history_entry = HistoryEntry(
            text="An entry.", ts=10, index=0, layer=0, id="arch-1", start=0, end=3
        )
        topical.history = [
            CharacterMessage(message=f"Mara: line {i}") for i in range(4)
        ]
        with (
            ActiveScene(topical),
            patch("talemate.agents.summarize.refresh_topics", AsyncMock()) as refresh,
            patch("talemate.agents.summarize.drop_facts_for_entries", AsyncMock()),
            patch("talemate.agents.summarize.store_facts", AsyncMock(return_value=[])),
            # no facts come back: the rebuild must still follow the drop
            patch.object(summarizer, "summarize", AsyncMock(return_value=("text", []))),
        ):
            await summarizer.regenerate_facts(history_entry)
            await summarizer.summarize_with_facts(entry)
        assert refresh.await_count == 2
        assert all(c.kwargs.get("force") is True for c in refresh.await_args_list)
