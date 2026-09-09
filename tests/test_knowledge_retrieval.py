"""
Retrieval (#394 part G): recency term, diversity threshold, similarity
knowledge gate, entity lookup by id, cross-encoder rerank, the conversation
opt-ins (the AI memory pass, the ledger), the narrator's offscreen life and the character.activated signal.
"""

from itertools import combinations
from math import cos, radians, sin
from unittest.mock import AsyncMock, patch

import pytest
import numpy as np

import talemate.emit.async_signals as async_signals
from talemate.agents.conversation.knowledge import (
    normalize_fact_id,
    parse_ledger,
    pass_items,
)
from talemate.agents.conversation.response_specs import MEMORY_PASS_SPEC
from talemate.agents.memory.rerank import (
    CrossEncoderReranker,
    RERANK_CANDIDATES,
    RERANK_KEEP,
    RERANK_MODEL,
)
from talemate.agents.memory import ChromaDBMemoryAgent
from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character, activate_character
from talemate.context import ActiveScene, SceneIsLoading
from talemate.events import ArchiveEvent, CharacterActivatedEvent
from talemate.instance import get_agent
from talemate.knowledge.absence import absence_facts
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.chronology import DAY
from talemate.knowledge.schema import Fact, KnowledgeEdge
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage
from talemate.tale_mate import Actor


def doc(id, text, distance=0.3, ts=None, embedding=None, typ="history", **meta):
    meta = {"typ": typ, **meta}
    if ts is not None:
        meta["ts"] = ts
    return MemoryDocument(text, meta, id, text, distance=distance, embedding=embedding)


@pytest.fixture
def memory(scene):
    memory = get_agent("memory")
    memory.table = []
    memory.calls = []
    memory.vectors = {}
    memory.db = object()
    memory._get_embeddings = lambda ids: {
        i: memory.vectors[i] for i in ids if i in memory.vectors
    }
    scene.ts = 1000

    async def fake_get(text, character=None, limit=15, **where):
        memory.calls.append({"text": text, "limit": limit, **where})
        return list(memory.table)

    memory.get = fake_get
    yield memory
    memory.db = None


def config(memory, key, value):
    memory.actions["retrieval"].config[key].value = value


class TestSettings:
    def test_defaults(self, memory):
        assert memory.retrieval_recency_weight == pytest.approx(0.1)
        assert memory.retrieval_mmr_threshold == pytest.approx(0.92)
        assert memory.retrieval_entity_lookup is True
        assert memory.retrieval_similarity_gate is True
        assert memory.retrieval_rerank is False

    def test_reranker_follows_the_device(self, memory):
        first = memory.reranker
        assert first.device == memory.device
        assert memory.reranker is first
        memory.actions["_config"].config["device"].value = "cuda"
        assert memory.reranker is not first
        assert memory.reranker.device == "cuda"
        memory.actions["_config"].config["device"].value = "cpu"


class TestRecency:
    async def test_weight_zero_keeps_distance_order_for_facts(self, scene, memory):
        config(memory, "recency_weight", 0)
        scene.ts = 100 * DAY
        memory.table = [
            doc("F1", "relevant old fact", 0.1, ts=70 * DAY, typ="fact", importance=3),
            doc(
                "F2",
                "less relevant fresh fact",
                0.2,
                ts=99 * DAY,
                typ="fact",
                importance=3,
            ),
        ]
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5)
        assert [item.raw for item in result] == [
            "relevant old fact",
            "less relevant fresh fact",
        ]

    async def test_newer_result_outranks_a_slightly_closer_old_one(self, scene, memory):
        # A: 0.30 + 0.1 * 1.0 = 0.40, B: 0.35 + 0.1 * 0.0 = 0.35
        memory.table = [doc("A", "old", 0.30, ts=100), doc("B", "new", 0.35, ts=1000)]
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == ["new", "old"]

    async def test_weight_zero_keeps_the_distance_order(self, scene, memory):
        config(memory, "recency_weight", 0)
        memory.table = [doc("A", "old", 0.30, ts=100), doc("B", "new", 0.35, ts=1000)]
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == ["old", "new"]

    async def test_missing_ts_counts_as_half_age(self, scene, memory):
        # C has no ts: 0.33 + 0.05 = 0.38, between A (0.40) and B (0.35)
        memory.table = [
            doc("A", "old", 0.30, ts=100),
            doc("B", "new", 0.35, ts=1000),
            doc("C", "undated", 0.33),
        ]
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == [
                "new",
                "undated",
                "old",
            ]

    async def test_iterate_cuts_after_the_recency_rank(self, scene, memory):
        memory.table = [doc("A", "old", 0.30, ts=100), doc("B", "new", 0.35, ts=1000)]
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=1) == ["new"]


class TestDiversity:
    @pytest.mark.parametrize("threshold", [0.5, 0.92, 0.99])
    @pytest.mark.parametrize("dimensions", [2, 3, 8])
    def test_random_merge_selection_has_no_near_duplicate_pair(
        self, scene, memory, threshold, dimensions
    ):
        config(memory, "mmr_threshold", threshold)
        rng = np.random.default_rng(504)
        for trial in range(200):
            vectors = rng.normal(size=(24, dimensions))
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
            timestamps = rng.integers(0, 100, size=len(vectors))
            candidates = [
                doc(
                    f"random-{number}",
                    f"Random fact {number}",
                    ts=int(timestamp),
                    typ="fact",
                    embedding=vector.tolist(),
                )
                for number, (vector, timestamp) in enumerate(zip(vectors, timestamps))
            ]
            query_count = int(rng.integers(1, 5))
            result = memory._merge_round_robin(
                [candidates[offset::query_count] for offset in range(query_count)]
            )
            assert result
            assert {item.id for item in result} <= {item.id for item in candidates}
            assert all(
                float(np.dot(left.embedding, right.embedding)) <= threshold + 1e-12
                for left, right in combinations(result, 2)
            ), (trial, dimensions, threshold, [item.id for item in result])

    @pytest.mark.parametrize("budget", [1, 2, 5])
    async def test_fresher_fact_removes_all_beaten_slots(
        self, scene, memory, monkeypatch, budget
    ):
        config(memory, "recency_weight", 0)
        config(memory, "mmr_threshold", 0.92)
        scene.ts = 100 * DAY

        def fact(identity, degrees, timestamp):
            angle = radians(degrees)
            return doc(
                identity,
                identity,
                ts=timestamp * DAY,
                typ="fact",
                importance=3,
                embedding=[cos(angle), sin(angle)],
            )

        first = fact("first", 0, 60)
        second = fact("second", 40, 70)
        fresh = fact("fresh", 20, 99)
        other = doc("other", "Other history", embedding=[-1.0, 0.0])
        later = doc("later", "Later history", embedding=[0.0, -1.0])
        memory.get = AsyncMock(side_effect=[[first, second, later], [other, fresh]])
        monkeypatch.setattr("talemate.agents.memory.util.count_tokens", len)
        with ActiveScene(scene):
            result = await memory.multi_query(
                ["q1", "q2"], iterate=5, max_tokens=budget
            )
        assert [item.id for item in result] == ["fresh", "other", "later"][:budget]

    async def test_fresh_replacement_must_clear_every_duplicate(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "mmr_threshold", 0.92)
        scene.ts = 100 * DAY

        def vector(degrees):
            angle = radians(degrees)
            return [cos(angle), sin(angle)]

        history = doc("H", "history", embedding=vector(0))
        fresh = doc(
            "F_fresh",
            "fresh fact",
            ts=99 * DAY,
            typ="fact",
            importance=3,
            embedding=vector(20),
        )
        old = doc(
            "F_old",
            "old fact",
            ts=70 * DAY,
            typ="fact",
            importance=3,
            embedding=vector(40),
        )
        other = doc("X", "other history", embedding=vector(120))
        memory.get = AsyncMock(side_effect=[[history, old], [other, fresh]])
        with ActiveScene(scene):
            result = await memory.multi_query(["q1", "q2"], iterate=5)
        assert [item.id for item in result] == ["H", "X", "F_old"]
        assert all(
            sum(a * b for a, b in zip(left.embedding, right.embedding)) <= 0.92
            for left, right in combinations(result, 2)
        )

    @pytest.mark.parametrize("budget", [1, 2, 5])
    async def test_fresher_fact_keeps_selected_slot_across_queries(
        self, scene, memory, monkeypatch, budget
    ):
        config(memory, "recency_weight", 0)
        config(memory, "mmr_threshold", 0.92)
        scene.ts = 100 * DAY
        old = doc(
            "F_old",
            "old wording",
            0.1,
            ts=70 * DAY,
            typ="fact",
            importance=3,
            embedding=[1.0, 0.0, 0.0],
        )
        fresh = doc(
            "F_fresh",
            "fresh wording",
            0.3,
            ts=99 * DAY,
            typ="fact",
            importance=3,
            embedding=[0.995, (1 - 0.995**2) ** 0.5, 0.0],
        )
        h1 = doc("H1", "history one", embedding=[0.0, 0.0, 1.0])
        h2 = doc("H2", "history two", embedding=[0.0, 1.0, 0.0])
        h3 = doc("H3", "history three", embedding=[-1.0, 0.0, 0.0])
        memory.get = AsyncMock(side_effect=[[old, h1], [h2, h3, fresh]])
        monkeypatch.setattr("talemate.agents.memory.util.count_tokens", len)
        with ActiveScene(scene):
            result = await memory.multi_query(
                ["q1", "q2"], iterate=5, max_tokens=budget
            )
        assert [item.id for item in result] == ["F_fresh", "H2", "H1", "H3"][:budget]

    @pytest.mark.parametrize("reverse", [False, True])
    async def test_fresher_fact_wins_near_duplicate_across_queries(
        self, scene, memory, reverse
    ):
        config(memory, "recency_weight", 0)
        scene.ts = 100 * DAY
        old = doc(
            "F1",
            "month-old event",
            0.1,
            ts=70 * DAY,
            typ="fact",
            importance=3,
            embedding=[1.0, 0.0],
        )
        fresh = doc(
            "F2",
            "yesterday event",
            0.2,
            ts=99 * DAY,
            typ="fact",
            importance=1,
            embedding=[0.99, 0.1],
        )
        queries = [[old], [fresh]]
        memory.get = AsyncMock(
            side_effect=list(reversed(queries)) if reverse else queries
        )
        with ActiveScene(scene):
            result = await memory.multi_query(["q1", "q2"], iterate=5)
        assert [item.id for item in result] == ["F2"]

    async def test_near_identical_result_is_skipped(self, scene, memory):
        config(memory, "recency_weight", 0)
        memory.table = [
            doc("A", "first", 0.2, embedding=[1.0, 0.0, 0.0]),
            doc("B", "twin", 0.25, embedding=[0.99, 0.1, 0.0]),
            doc("C", "other", 0.3, embedding=[0.0, 1.0, 0.0]),
        ]
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == ["first", "other"]

    async def test_threshold_one_keeps_everything(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "mmr_threshold", 1.0)
        memory.table = [
            doc("A", "first", 0.2, embedding=[1.0, 0.0, 0.0]),
            doc("B", "twin", 0.25, embedding=[0.99, 0.1, 0.0]),
        ]
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == ["first", "twin"]

    async def test_result_without_embedding_is_kept(self, scene, memory):
        config(memory, "recency_weight", 0)
        memory.table = [
            doc("A", "first", 0.2, embedding=[1.0, 0.0, 0.0]),
            doc("B", "blind", 0.25),
        ]
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == ["first", "blind"]


class TestSimilarityGate:
    """
    A result rejected for presence alone passes when a fact in Edwin's
    bucket is a near-duplicate of it; revoked, hidden and offscreen items
    never do. Both settings sit at their defaults (0.15 / 0.92).
    """

    @pytest.fixture
    def filtered(self, scene, memory):
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="known fact", ts=10, present=["Edwin", "Mara"]),
            "F9": Fact(id="F9", text="twin fact", ts=20, present=["Mara"]),
            "F8": Fact(id="F8", text="far fact", ts=30, present=["Mara"]),
            "F7": Fact(id="F7", text="revoked twin", ts=40, present=["Mara"]),
            "F6": Fact(
                id="F6",
                text="offscreen twin",
                ts=50,
                present=["Mara"],
                source="offscreen",
            ),
        }
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F7", kind="revoke")
        ]
        memory.vectors = {
            "F1": [1.0, 0.0],
            "F9": [1.0, 0.1],
            "F8": [1.0, 0.5],
            "F7": [1.0, 0.05],
            "F6": [1.0, 0.02],
            "e1": [1.0, 0.05],
            "Mara.detail.secret": [1.0, 0.03],
        }
        config(memory, "recency_weight", 0)
        get_agent("summarizer").actions["archive"].config[
            "fact_dedupe_distance"
        ].value = 0.15
        mara = Character(name="Mara")
        from talemate.knowledge.schema import EntryVisibility

        mara.visibility = {"detail.secret": EntryVisibility(mode="owner")}
        scene.character_data = {"Mara": mara, "Edwin": Character(name="Edwin")}
        return KnowledgeIndex.from_scene(scene).retrieval_filter(scene, "Edwin")

    def presence(self, id, text, distance, embedding, typ="fact", present='["Mara"]'):
        return MemoryDocument(
            text,
            {"typ": typ, "presence_known": True, "present": present},
            id,
            text,
            distance=distance,
            embedding=embedding,
        )

    async def test_near_duplicate_of_a_known_fact_passes_and_survives_the_merge(
        self, scene, memory, filtered
    ):
        memory.table = [
            self.presence(
                "F1", "known fact", 0.2, [1.0, 0.0], present='["Edwin", "Mara"]'
            ),
            self.presence("F9", "twin fact", 0.25, [1.0, 0.1]),
            self.presence("F8", "far fact", 0.3, [1.0, 0.5]),
            self.presence("e1", "history", 0.35, [1.0, 0.05], typ="history"),
        ]
        with ActiveScene(scene), patch("talemate.agents.memory.log.debug") as debug:
            result = await memory.multi_query(["q"], iterate=5, filter=filtered)
        assert [doc.raw for doc in result] == ["twin fact"]
        debug.assert_any_call("similarity gate passed", id="e1")
        assert str(result[0]) == "(16 Minutes and 20 Seconds ago) twin fact"
        assert filtered.rejection(memory.table[1]) == "presence"

    @pytest.mark.parametrize("reverse", [False, True])
    @pytest.mark.parametrize("admitted_is_fresher", [False, True])
    async def test_admitted_and_selected_facts_keep_only_the_fresher_copy(
        self, scene, memory, filtered, reverse, admitted_is_fresher
    ):
        scene.world_state.facts["F1"].ts = 10 if admitted_is_fresher else 30
        known = self.presence(
            "F1", "known fact", 0.2, [1.0, 0.0], present='["Edwin", "Mara"]'
        )
        admitted = self.presence("F9", "twin fact", 0.25, [1.0, 0.1])
        memory.table = [admitted, known] if reverse else [known, admitted]
        with ActiveScene(scene), patch("talemate.agents.memory.log.debug") as debug:
            result = await memory.multi_query(["q"], iterate=5, filter=filtered)
        kept, dropped = ("F9", "F1") if admitted_is_fresher else ("F1", "F9")
        assert [item.id for item in result] == [kept]
        debug.assert_any_call("similarity gate passed", id="F9")
        assert any(
            call.args == ("diversity skip",)
            and call.kwargs.get("id") == dropped
            and call.kwargs.get("reason") == "duplicate"
            for call in debug.call_args_list
        )
        assert len(memory.calls) == 1

    async def test_revoked_hidden_and_offscreen_are_never_rescued(
        self, scene, memory, filtered
    ):
        memory.table = [
            self.presence("F7", "revoked twin", 0.2, [1.0, 0.05]),
            self.presence("F6", "offscreen twin", 0.22, [1.0, 0.02]),
            MemoryDocument(
                "secret",
                {"typ": "details", "character": "Mara", "detail": "secret"},
                "Mara.detail.secret",
                "secret",
                distance=0.24,
                embedding=[1.0, 0.03],
            ),
            self.presence("F9", "twin fact", 0.25, [1.0, 0.1]),
        ]
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, filter=filtered)
        assert [doc.raw for doc in result] == ["twin fact"]
        assert filtered.rejection(memory.table[0]) == "revoke"
        assert filtered.rejection(memory.table[2]) == "visibility"
        assert filtered.gateable(memory.table[1]) is False

    async def test_an_admission_is_remembered_by_the_diversity_check(
        self, scene, memory, filtered
    ):
        memory.table = [
            self.presence("F9", "twin fact", 0.25, [1.0, 0.1]),
            # an ordinary near-copy of the admitted document, known to Edwin
            self.presence(
                "e2",
                "copy of the twin",
                0.3,
                [1.0, 0.11],
                typ="history",
                present='["Edwin", "Mara"]',
            ),
        ]
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, filter=filtered)
        assert [doc.raw for doc in result] == ["twin fact"]

    async def test_anchors_are_fetched_once_per_call(self, scene, memory, filtered):
        memory.table = [self.presence("F9", "twin fact", 0.25, [1.0, 0.1])]
        with (
            ActiveScene(scene),
            patch.object(
                memory, "get_embeddings", wraps=memory.get_embeddings
            ) as fetch,
        ):
            await memory.multi_query(["q1", "q2", "q3"], iterate=5, filter=filtered)
        anchor_fetches = [c for c in fetch.await_args_list if "F1" in c.args[0]]
        assert len(anchor_fetches) == 1

    async def test_gate_off_keeps_the_filter_strict(self, scene, memory, filtered):
        config(memory, "similarity_gate", False)
        memory.table = [
            self.presence(
                "F1", "known fact", 0.2, [1.0, 0.0], present='["Edwin", "Mara"]'
            ),
            self.presence("F9", "twin fact", 0.25, [1.0, 0.1]),
        ]
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, filter=filtered)
        assert [doc.raw for doc in result] == ["known fact"]

    async def test_anchors_are_the_whole_bucket_not_the_query(
        self, scene, memory, filtered
    ):
        # F1 is known but not among this query's results: the gate still admits F9
        memory.table = [self.presence("F9", "twin fact", 0.25, [1.0, 0.1])]
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, filter=filtered)
        assert [doc.raw for doc in result] == ["twin fact"]

    async def test_plain_callable_filter_has_no_gate(self, scene, memory, filtered):
        memory.table = [self.presence("F9", "twin fact", 0.25, [1.0, 0.1])]
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, filter=lambda d: False)
        assert result == []

    async def test_without_a_filter_nothing_is_gated(self, scene, memory, filtered):
        memory.table = [
            self.presence("F1", "known fact", 0.2, [1.0, 0.0]),
            self.presence("F8", "far fact", 0.3, [0.0, 1.0]),
        ]
        with ActiveScene(scene):
            assert len(await memory.multi_query(["q"], iterate=5)) == 2


class FakeReranker:
    def __init__(self, device, error=None):
        self.device = device
        self.error = error
        self.calls = []

    def rerank(self, queries, docs, keep):
        self.calls.append((list(queries), list(docs), keep))
        if self.error:
            return docs
        return list(reversed(docs))[:keep]


class TestRerank:
    async def test_reranker_owns_fact_order_and_budget(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "rerank", True)
        scene.ts = 100 * DAY
        memory.table = [
            doc("F2", "fresh candidate", 0.1, ts=99 * DAY, typ="fact", importance=3),
            doc(
                "F1",
                "most relevant old candidate",
                0.2,
                ts=70 * DAY,
                typ="fact",
                importance=3,
            ),
        ]
        memory._reranker = FakeReranker(memory.device)
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, max_tokens=1)
        assert [item.id for item in result] == ["F1"]
        assert [item.id for item in memory._reranker.calls[0][1]] == ["F2", "F1"]

    async def test_off_by_default_leaves_the_merge_alone(self, scene, memory):
        config(memory, "recency_weight", 0)
        memory.table = [doc("A", "a", 0.2), doc("B", "b", 0.3)]
        fake = FakeReranker(memory.device)
        memory._reranker = fake
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == ["a", "b"]
        assert fake.calls == []

    async def test_reranks_the_merged_candidates(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "rerank", True)
        memory.table = [doc("A", "a", 0.2), doc("B", "b", 0.3), doc("C", "c", 0.4)]
        fake = FakeReranker(memory.device)
        memory._reranker = fake
        with ActiveScene(scene):
            result = await memory.multi_query(["q1", "", "q2"], iterate=5)
        assert result == ["c", "b", "a"]
        queries, docs, keep = fake.calls[0]
        assert queries == ["q1", "q2"]
        assert keep == RERANK_KEEP

    async def test_pool_is_capped(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "rerank", True)
        memory.table = [doc(f"D{i}", f"d{i}", 0.1 + i * 0.001) for i in range(40)]
        fake = FakeReranker(memory.device)
        memory._reranker = fake
        with ActiveScene(scene):
            await memory.multi_query(["q"], iterate=40)
        assert len(fake.calls[0][1]) == RERANK_CANDIDATES

    async def test_load_failure_falls_back_to_the_merge(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "rerank", True)
        memory.table = [doc("A", "a", 0.2), doc("B", "b", 0.3)]
        memory._reranker = FakeReranker(memory.device, error="no model")
        with ActiveScene(scene):
            assert await memory.multi_query(["q"], iterate=5) == ["a", "b"]
        assert memory.rerank_error == "no model"

    async def test_load_failure_does_not_cap_the_merge_at_the_pool(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "rerank", True)
        memory.table = [doc(f"D{i}", f"d{i}", 0.1 + i * 0.001) for i in range(40)]

        class FailingReranker(FakeReranker):
            def rerank(self, queries, docs, keep):
                self.calls.append((list(queries), list(docs), keep))
                self.error = "no model"
                return docs

        fake = FailingReranker(memory.device)
        memory._reranker = fake
        with ActiveScene(scene):
            first = await memory.multi_query(["q"], iterate=40)
            # the failure is recorded: the plain merge, not the 30-candidate pool
            assert len(first) == 40
            second = await memory.multi_query(["q"], iterate=40)
        assert len(second) == 40
        # asked once; a recorded failure is not retried
        assert len(fake.calls) == 1

    def test_agent_details_show_the_model_or_the_error(self):
        memory = ChromaDBMemoryAgent()
        config(memory, "rerank", True)
        memory._reranker = FakeReranker(memory.device)
        details = memory.agent_details
        assert details["rerank"]["value"] == RERANK_MODEL
        memory._reranker = FakeReranker(memory.device, error="boom")
        details = memory.agent_details
        assert details["rerank"]["color"] == "warning"
        assert "boom" in details["rerank"]["description"]
        config(memory, "rerank", False)
        assert "rerank" not in memory.agent_details


class FakeModel:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = None

    def predict(self, pairs):
        self.pairs = pairs
        return [self.scores[(q, d)] for q, d in pairs]


class TestCrossEncoderReranker:
    def test_best_score_over_the_queries_orders_the_documents(self):
        reranker = CrossEncoderReranker(device="cpu")
        reranker.model = FakeModel(
            {
                ("q1", "a"): 0.1,
                ("q2", "a"): 0.9,
                ("q1", "b"): 0.5,
                ("q2", "b"): 0.2,
                ("q1", "c"): 0.0,
                ("q2", "c"): 0.0,
            }
        )
        assert reranker.rerank(["q1", "q2"], ["a", "b", "c"], keep=2) == ["a", "b"]
        assert len(reranker.model.pairs) == 6

    def test_load_failure_is_recorded_once(self):
        reranker = CrossEncoderReranker(device="cpu", model_name="nope/nope")
        with patch("sentence_transformers.CrossEncoder", side_effect=OSError("404")):
            assert reranker.load() is False
            assert reranker.rerank(["q"], ["a", "b"]) == ["a", "b"]
        assert "404" in reranker.error
        assert reranker.available is False
        # a later call does not try again
        with patch("sentence_transformers.CrossEncoder") as ctor:
            assert reranker.load() is False
        ctor.assert_not_called()


class TestEntityLookup:
    @pytest.fixture
    def zed(self, scene, memory):
        zed = Character(name="Zed", description="Zed is a smuggler.")
        will = Character(name="Will", description="Will is a fisherman.")
        scene.character_data = {"Zed": zed, "Will": will}
        scene.world_state.character_name_mappings = {"Zed": ["the smuggler"]}

        def description(name, text):
            return MemoryDocument(
                text,
                {"typ": "base_attribute", "character": name, "attr": "description"},
                f"{name}.description",
                text,
            )

        docs = {
            "Zed": {
                "Zed.description": description(
                    "Zed", "Zed's description: Zed is a smuggler."
                )
            },
            "Will": {
                "Will.description": description(
                    "Will", "Will's description: Will is a fisherman."
                )
            },
        }

        async def by_meta(meta):
            memory.meta_calls.append(meta)
            return docs.get(meta.get("character"), {})

        memory.meta_calls = []
        memory.get_documents_by_meta = by_meta
        return docs["Zed"]["Zed.description"]

    async def test_named_inactive_character_is_fetched_by_metadata(
        self, scene, memory, zed
    ):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            found = await conversation.entity_lookup(["Mara: I saw Zed at the pier."])
        assert found == [zed]
        assert memory.meta_calls == [
            {"character": "Zed", "typ": "base_attribute", "attr": "description"}
        ]

    async def test_alias_from_the_name_mappings_counts(self, scene, memory, zed):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            found = await conversation.entity_lookup(["Mara: The Smuggler is back."])
        # a lower-case alias matches whatever the prose's case
        assert found == [zed]

    async def test_a_name_that_is_also_a_word_needs_its_capital(
        self, scene, memory, zed
    ):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            assert (
                await conversation.entity_lookup(["Alice: I will go north at dawn."])
                == []
            )
            found = await conversation.entity_lookup(
                ["Alice: Will went north at dawn."]
            )
        assert [d.id for d in found] == ["Will.description"]

    async def test_description_paragraphs_come_back_in_number_order(
        self, scene, memory, zed
    ):
        conversation = get_agent("conversation")

        def paragraph(n):
            text = f"paragraph {n}"
            return MemoryDocument(
                text,
                {"typ": "base_attribute", "character": "Zed", "attr": "description"},
                f"Zed.description.{n}",
                text,
            )

        docs = {f"Zed.description.{n}": paragraph(n) for n in range(12)}
        memory.get_documents_by_meta = AsyncMock(return_value=docs)
        with ActiveScene(scene):
            found = await conversation.entity_lookup(["Mara: I saw Zed."])
        assert [d.id for d in found] == [f"Zed.description.{n}" for n in range(12)]

    async def test_unrelated_lines_fetch_nothing(self, scene, memory, zed):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            assert await conversation.entity_lookup(["Mara: a quiet night."]) == []
        assert memory.meta_calls == []

    async def test_active_character_is_not_looked_up(self, scene, memory, zed):
        conversation = get_agent("conversation")
        scene.active_characters = ["Zed"]
        with ActiveScene(scene):
            assert await conversation.entity_lookup(["Mara: I saw Zed."]) == []

    async def test_setting_off(self, scene, memory, zed):
        config(memory, "entity_lookup", False)
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            assert await conversation.entity_lookup(["Mara: I saw Zed."]) == []

    async def test_knowledge_filter_applies(self, scene, memory, zed):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            found = await conversation.entity_lookup(
                ["Mara: I saw Zed."], filter=lambda d: False
            )
        assert found == []

    async def test_semantic_context_puts_the_description_first(
        self, scene, memory, zed
    ):
        conversation = get_agent("conversation")
        scene.history = [CharacterMessage(message="Mara: I saw Zed at the pier.")]
        memory.table = [doc("e1", "the pier at night", 0.2)]
        with ActiveScene(scene):
            context = await conversation.semantic_context()
        assert context[0] == zed
        assert "the pier at night" in context

    async def test_description_leads_under_the_queries_method_too(
        self, scene, memory, zed
    ):
        conversation = get_agent("conversation")
        world_state = get_agent("world_state")
        scene.history = [CharacterMessage(message="Mara: I saw Zed at the pier.")]
        scene.rag_cache = {}
        memory.table = [doc("e1", "the pier at night", 0.2)]
        conversation.actions["use_long_term_memory"].config[
            "retrieval_method"
        ].value = "queries"
        conversation.actions["use_long_term_memory"].config["cache"].value = False
        try:
            with (
                ActiveScene(scene),
                patch.object(scene, "context_history", return_value=[]),
                patch.object(
                    world_state,
                    "analyze_text_and_extract_context_via_queries",
                    AsyncMock(return_value=["queried"]),
                ),
            ):
                context = await conversation.rag_build()
        finally:
            conversation.actions["use_long_term_memory"].config[
                "retrieval_method"
            ].value = "direct"
            conversation.actions["use_long_term_memory"].config["cache"].value = True
        assert context[0] == zed
        assert context[1:] == ["the pier at night", "queried"]


class TestParsers:
    def test_pass_items(self):
        assert pass_items(None) == []
        assert pass_items([]) == []
        assert pass_items(
            [
                {"type": "item", "n": "3", "content": " Third "},
                {"type": "item", "n": "1", "content": "First"},
                {"type": "item", "n": "3", "content": "again"},
                {"type": "item", "n": "2", "content": ""},
            ]
        ) == [(3, "Third"), (1, "First"), (2, "")]

    def test_pass_answer_extraction(self):
        def extract(text):
            return {
                name: extractor.extract(text)
                for name, extractor in MEMORY_PASS_SPEC.extractors.items()
            }

        blocks = extract(
            '<ITEMS>\n<ITEM n="1">Mara owes the harbourmaster\n3.5 crowns.</ITEM>\n'
            '<ITEM n="2">The Sorena went down in\n1929. The town watched.</ITEM>\n</ITEMS>'
        )
        assert pass_items(blocks["items"]) == [
            (1, "Mara owes the harbourmaster\n3.5 crowns."),
            (2, "The Sorena went down in\n1929. The town watched."),
        ]
        blocks = extract(
            '<ITEMS>\n<ITEM n="1">one</ITEM>\n<ITEM n="2">two</ITEM>\n\n'
            "I dropped candidate 3 because Mara knows nothing of it.\n</ITEMS>"
        )
        assert pass_items(blocks["items"]) == [(1, "one"), (2, "two")]
        blocks = extract('<ITEMS>\n<ITEM n="2">two</ITEM>\n<ITEM n="1">cut off')
        assert pass_items(blocks["items"]) == [(2, "two")]
        for text in ("<ITEMS>none</ITEMS>", "<ITEMS>None - nothing applies</ITEMS>"):
            blocks = extract(text)
            assert blocks["items"] == []
            assert blocks["answer"].lower().startswith("none")
        blocks = extract('<ITEMS>None apply except:\n<ITEM n="3">three</ITEM></ITEMS>')
        assert pass_items(blocks["items"]) == [(3, "three")]
        # whitespace inside a tag, mixed with a well-formed item
        blocks = extract(
            '<ITEMS>\n<ITEM n="1">alpha</ITEM >\n<ITEM  n="2" >beta</ITEM n="2">\n'
            '<ITEM n = "3">gamma</ITEM>\n</ITEMS>'
        )
        assert pass_items(blocks["items"]) == [(1, "alpha"), (2, "beta"), (3, "gamma")]
        # an unclosed middle block ends at the next opener
        blocks = extract(
            '<ITEMS>\n<ITEM n="3">The Sorena went down the year Mara was born.\n'
            '<ITEM n="1">Mara still owes the harbourmaster.</ITEM>\n</ITEMS>'
        )
        assert pass_items(blocks["items"]) == [
            (3, "The Sorena went down the year Mara was born."),
            (1, "Mara still owes the harbourmaster."),
        ]
        # a tagged aside after the container is not an item
        blocks = extract(
            '<ITEMS>\n<ITEM n="1">Mara still owes the harbourmaster.</ITEM>\n</ITEMS>\n'
            'I left out <ITEM n="2">Edwin hid the sextant.</ITEM> because Mara was not there.'
        )
        assert pass_items(blocks["items"]) == [
            (1, "Mara still owes the harbourmaster.")
        ]
        blocks = extract(
            '<ITEMS>none</ITEMS>\nFor reference I considered <ITEM n="2">the sextant</ITEM>.'
        )
        assert blocks["items"] == []
        assert blocks["answer"].lower().startswith("none")

    def test_ledger(self):
        assert parse_ledger(None) is None
        assert parse_ledger("") is None
        assert parse_ledger('{"Mara": ["F1", "F2"]}') == {"Mara": ["F1", "F2"]}
        assert parse_ledger('{"Mara": "F1"}') == {"Mara": ["F1"]}
        assert parse_ledger('{"Mara": ["F1"], "Edwin": 3}') == {"Mara": ["F1"]}
        assert parse_ledger("garbage") is None
        assert parse_ledger("[1]") is None
        assert parse_ledger('```json\n{"Mara": ["F1"]}\n```') == {"Mara": ["F1"]}
        # prose around the JSON: the recovery path
        assert parse_ledger('Here is the ledger: {"Mara": ["F12"]} as asked') == {
            "Mara": ["F12"]
        }
        # ids are normalised
        assert parse_ledger('{"Mara": [12, "f3", "[F4]", " F5 "]}') == {
            "Mara": ["F12", "F3", "F4", "F5"]
        }
        assert normalize_fact_id("(f7)") == "F7"


@pytest.fixture
def opt_ins(scene):
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    for key in ("memory_pass", "ledger"):
        conversation.actions["character_knowledge"].config[key].value = False
    conversation.actions["character_knowledge"].config[
        "perspective_filter"
    ].value = True
    alice = Character(name="Alice")
    edwin = Character(name="Edwin")
    scene.character_data = {"Alice": alice, "Edwin": edwin}
    scene.active_characters = ["Alice", "Edwin"]
    scene.ts = 500
    scene.rag_cache = {}

    async def semantic(**kwargs):
        return ["a", "b", "c"]

    conversation.semantic_context = semantic
    scene.context_history = lambda **kwargs: ["Alice: hello", "Edwin: hi"]
    return conversation, alice


def enable(conversation, key, value=True):
    conversation.actions["character_knowledge"].config[key].value = value


def items(*pairs):
    return [{"type": "item", "n": str(n), "content": text} for n, text in pairs]


class TestMemoryPass:
    def test_off_by_default(self, scene):
        conversation = get_agent("conversation")
        assert conversation.knowledge_memory_pass is False
        assert conversation.knowledge_ledger is False

    async def test_no_request_when_off(self, scene, opt_ins):
        conversation, alice = opt_ins
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.rag_build(character=alice) == ["a", "b", "c"]
        request.assert_not_called()

    async def test_one_request_rewrites_drops_and_orders(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = (
                "",
                {
                    "answer": "...",
                    "items": items((3, "C as Alice knows it"), (1, "A, in short")),
                },
            )
            assert await conversation.rag_build(character=alice) == [
                "C as Alice knows it",
                "A, in short",
            ]
        assert request.call_count == 1
        assert request.call_args.args[0] == "conversation.memory-pass"
        assert request.call_args.args[1] is get_agent("world_state").client
        assert request.call_args.args[2] == "analyze_long"
        vars = request.call_args.kwargs["vars"]
        assert vars["candidates"] == ["a", "b", "c"]
        assert vars["character"] is alice
        assert vars["viewer"] == "Alice"
        assert vars["scene_history"] == ["Alice: hello", "Edwin: hi"]

    async def test_story_context_follows_the_perspective_filter(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        calls = []

        def context_history(**kwargs):
            calls.append(kwargs)
            return []

        scene.context_history = context_history
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"answer": "", "items": items((2, "B"))})
            assert await conversation.rag_build(character=alice) == ["B"]
            assert calls[-1]["perspective"] == "Alice"
            assert calls[-1]["keep_director"] == "Alice"
            assert request.call_args.kwargs["vars"]["viewer"] == "Alice"

            enable(conversation, "perspective_filter", False)
            scene.rag_cache = {}
            request.return_value = (
                "",
                {"answer": "", "items": items((3, "C"), (1, ""))},
            )
            assert await conversation.rag_build(character=alice) == ["C", "a"]
            assert calls[-1]["perspective"] is None
            assert request.call_args.kwargs["vars"]["viewer"] is None
        assert request.call_count == 2

    async def test_director_guidance_drops_the_director_messages(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        calls = []

        def context_history(**kwargs):
            calls.append(kwargs)
            return []

        scene.context_history = context_history
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
            patch("talemate.agents.conversation.knowledge.active_agent") as agent_var,
        ):
            request.return_value = ("", {"answer": "", "items": items((1, "A"))})
            agent_var.get.return_value.state = {}
            await conversation.rag_build(character=alice)
            assert calls[-1]["keep_director"] == "Alice"
            agent_var.get.return_value.state = {"director__actor_guidance": "Sulk."}
            scene.rag_cache = {}
            await conversation.rag_build(character=alice)
        assert calls[-1]["keep_director"] is False

    async def test_none_drops_everything(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"answer": "none", "items": []})
            assert await conversation.rag_build(character=alice) == []
            request.return_value = (
                "",
                {"answer": "None apply except:", "items": items((3, "three"))},
            )
            assert await conversation.rag_build(character=alice) == ["three"]
            # a preamble plus an item the extractor could not read is unreadable
            request.return_value = (
                "",
                {
                    "answer": 'None apply except:\n<ITEM n="3">Mara was born the year the Sor',
                    "items": [],
                },
            )
            assert await conversation.rag_build(character=alice) == ["a", "b", "c"]

    async def test_unreadable_answer_keeps_the_candidates(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            for answer, blocks in (
                (None, None),
                ("I would keep the first one.", []),
                ("", items((9, "nine"), (0, "zero"))),
            ):
                request.return_value = ("", {"answer": answer, "items": blocks})
                assert await conversation.rag_build(character=alice) == ["a", "b", "c"]

    async def test_out_of_range_dropped_and_empty_rewrite_kept(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = (
                "",
                {"answer": "", "items": items((9, "nine"), (2, ""), (1, "one"))},
            )
            assert await conversation.rag_build(character=alice) == ["b", "one"]

    async def test_only_for_a_speaker(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.rag_build() == ["a", "b", "c"]
        request.assert_not_called()

    async def test_container_off_disables_the_pass(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        conversation.actions["character_knowledge"].enabled = False
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.rag_build(character=alice) == ["a", "b", "c"]
        request.assert_not_called()
        conversation.actions["character_knowledge"].enabled = True

    def test_template_renders_both_branches(self, scene, opt_ins):
        conversation, alice = opt_ins
        alice.description = "A keeper.\nShe hides a letter."
        rendered = {}
        for viewer in ("Alice", None):
            with ActiveScene(scene):
                prompt = Prompt.get(
                    "conversation.memory-pass",
                    vars={
                        "scene": scene,
                        "max_tokens": 8192,
                        "character": alice,
                        "viewer": viewer,
                        "candidates": ["The lamp went out.", "Edwin hid the sextant."],
                        "scene_history": ["Alice: Hello.", "Edwin: Hi."],
                        "knowledge_index": KnowledgeIndex.from_scene(scene),
                    },
                )
                rendered[viewer] = prompt.render()
        with_viewer, without = rendered["Alice"], rendered[None]
        assert "## Alice" in with_viewer and "She hides a letter." in with_viewer
        assert "as what Alice knows of it" in with_viewer
        assert "## Alice" not in without
        assert "the part that matters for Alice's next line" in without
        for text in rendered.values():
            assert "1. The lamp went out." in text
            assert "2. Edwin hid the sextant." in text
            assert "Alice: Hello." in text
            assert '<ITEM n="3">' in text
            assert text.rstrip().endswith("<ITEMS>")


class TestLedger:
    @pytest.fixture
    def facts(self, scene):
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="Alice found the key.", ts=10, present=["Alice"]),
            "F2": Fact(id="F2", text="The cellar floods.", ts=20, present=["Alice"]),
            "F3": Fact(id="F3", text="Everyone saw this.", ts=30, present=None),
        }
        return scene.world_state.facts

    async def test_learned_facts_become_inferred_grants(self, scene, opt_ins, facts):
        conversation, alice = opt_ins
        enable(conversation, "ledger")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"ledger": '{"Edwin": ["F1", "F9"]}'})
            learned = await conversation.record_learned_facts(
                alice, "Alice: I found the key under the mat."
            )
        assert learned == {"Edwin": ["F1"]}
        vars = request.call_args.kwargs["vars"]
        assert vars["speaker"] == "Alice"
        assert list(vars["absence"]) == ["Edwin"]
        assert [f.id for f in vars["absence"]["Edwin"]] == ["F2", "F1"]
        assert vars["recent_lines"] == []
        assert request.call_args.args[0] == "conversation.knowledge-ledger"
        edges = scene.world_state.knowledge
        assert len(edges) == 1
        assert (edges[0].character, edges[0].target, edges[0].kind) == (
            "Edwin",
            "F1",
            "grant",
        )
        assert edges[0].source == "inferred" and edges[0].ts == 500
        assert facts["F1"].known_by["Edwin"] == "inferred"

    async def test_the_new_line_is_not_repeated_in_the_recent_lines(
        self, scene, opt_ins, facts
    ):
        conversation, alice = opt_ins
        enable(conversation, "ledger")
        scene.history = [
            CharacterMessage(message="Edwin: Evening."),
            CharacterMessage(message="Alice: I found the key under the mat."),
        ]
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"ledger": "{}"})
            await conversation.record_learned_facts(
                alice, "Alice: I found the key under the mat."
            )
        assert request.call_args.kwargs["vars"]["recent_lines"] == ["Edwin: Evening."]

    async def test_off_makes_no_request(self, scene, opt_ins, facts):
        conversation, alice = opt_ins
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.record_learned_facts(alice, "Alice: hi") == {}
        request.assert_not_called()

    async def test_uses_the_configured_near_duplicate_distance(
        self, scene, opt_ins, facts
    ):
        conversation, alice = opt_ins
        enable(conversation, "ledger")
        get_agent("summarizer").actions["archive"].config[
            "fact_dedupe_distance"
        ].value = 0.3
        try:
            with (
                ActiveScene(scene),
                patch(
                    "talemate.agents.conversation.knowledge.absence_facts",
                    AsyncMock(return_value=[]),
                ) as absence,
            ):
                await conversation.record_learned_facts(alice, "Alice: hi")
            assert absence.call_args.kwargs["dedupe_distance"] == 0.3
        finally:
            get_agent("summarizer").actions["archive"].config[
                "fact_dedupe_distance"
            ].value = 0.15

    async def test_skipped_when_the_listeners_know_everything(
        self, scene, opt_ins, facts
    ):
        conversation, alice = opt_ins
        enable(conversation, "ledger")
        for fact in facts.values():
            fact.present = None
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.record_learned_facts(alice, "Alice: hi") == {}
        request.assert_not_called()

    async def test_unreadable_answer_makes_no_grants(self, scene, opt_ins, facts):
        conversation, alice = opt_ins
        enable(conversation, "ledger")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"ledger": "no"})
            assert await conversation.record_learned_facts(alice, "Alice: hi") == {}
        assert scene.world_state.knowledge == []

    async def test_speaker_alone_makes_no_request(self, scene, opt_ins, facts):
        conversation, alice = opt_ins
        enable(conversation, "ledger")
        scene.active_characters = ["Alice"]
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.record_learned_facts(alice, "Alice: hi") == {}
        request.assert_not_called()


@pytest.fixture
def offscreen(scene):
    narrator = get_agent("narrator")
    narrator.actions["offscreen_life"].enabled = True
    narrator.actions["offscreen_life"].config["min_entries"].value = 1
    zed = Character(name="Zed", description="Zed is a smuggler.")
    mara = Character(name="Mara")
    scene.character_data = {"Zed": zed, "Mara": mara}
    scene.active_characters = ["Mara"]
    scene.ts = 5000
    scene.rag_cache = {}
    scene.archived_history = [
        {
            "id": "a1",
            "text": "Zed and Mara argued.",
            "ts": 1000,
            "present": ["Mara", "Zed"],
            "start": 0,
            "end": 3,
        },
        {
            "id": "a2",
            "text": "Mara found a sextant.",
            "ts": 2000,
            "present": ["Mara"],
            "start": 4,
            "end": 6,
        },
        {
            "id": "a3",
            "text": "Mara hid it.",
            "ts": 3000,
            "present": ["Mara"],
            "start": 7,
            "end": 9,
        },
    ]
    scene.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="Mara found a sextant.",
            ts=2000,
            present=["Mara"],
            archive_id="a2",
        ),
    }
    scene.world_state.fact_counter = 1
    get_agent("memory").add_many = AsyncMock()
    narrator.connect(scene)
    yield narrator, zed
    narrator.actions["offscreen_life"].enabled = False


def activation(scene, character):
    return CharacterActivatedEvent(
        scene=scene, character=character, event_type="character.activated"
    )


class TestOffscreenLife:
    def test_off_by_default(self, scene):
        narrator = get_agent("narrator")
        assert narrator.actions["offscreen_life"].enabled is False

    def test_missed_entries(self, scene, offscreen):
        narrator, zed = offscreen
        assert [e["id"] for e in narrator.missed_entries(zed)] == ["a2", "a3"]
        assert narrator.missed_entries(scene.character_data["Mara"]) == []
        # unknown presence counts as present: the walk stops there
        scene.archived_history[1]["present"] = None
        assert [e["id"] for e in narrator.missed_entries(zed)] == ["a3"]

    async def test_a_scene_load_spends_no_request(self, scene, offscreen):
        """The load path activates the scene's own characters, and an adopted
        player has presence in the history. An offscreen account is a turn the
        player asks for, so opening a scene must not spend one."""
        narrator, zed = offscreen
        with (
            ActiveScene(scene),
            SceneIsLoading(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, zed))
        request.assert_not_called()
        assert narrator.pending_returns == {}

    async def test_return_writes_an_offscreen_fact(self, scene, offscreen):
        narrator, zed = offscreen
        memory = get_agent("memory")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = (
                "",
                {"response": "Zed sailed to the mainland and sold the cargo."},
            )
            await narrator.on_character_activated(activation(scene, zed))
        assert request.call_args.args[0] == "narrator.offscreen-life"
        vars = request.call_args.kwargs["vars"]
        # the prompt renders from Zed's perspective: no missed facts or entries in it
        assert "missed_facts" not in vars and "missed" not in vars
        assert vars["knowledge_index"] is not None
        assert vars["elapsed"]
        fact = scene.world_state.facts["F2"]
        assert fact.source == "offscreen"
        assert fact.present == ["Zed"] and fact.subjects == ["Zed"]
        assert fact.ts == 5000
        assert "sailed to the mainland" in fact.text
        document = memory.add_many.call_args.args[0][0]
        assert document["id"] == "F2"
        # the store's own `source` key stays the store's: an explicit value
        # would take the document out of the unsaved-session purge
        assert "source" not in document["meta"]
        assert document["meta"]["present"] == '["Zed"]'
        # only Zed knows it, and it never lists for anyone
        with ActiveScene(scene):
            assert "F2" not in [f.id for f in await absence_facts(scene, "Mara")]
            assert "F2" not in [f.id for f in await absence_facts(scene, "Zed")]

    async def test_never_present_character_gets_no_account(self, scene, offscreen):
        narrator, zed = offscreen
        mira = Character(name="Mira")
        scene.character_data["Mira"] = mira
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, mira))
        request.assert_not_called()
        assert narrator.missed_entries(mira) == []
        assert narrator.pending_returns == {}

    async def test_unknown_presence_is_not_prior_presence(self, scene, offscreen):
        # a scene from before presence tracking: the old entry has no presence
        narrator, zed = offscreen
        scene.archived_history[0]["present"] = None
        mira = Character(name="Mira")
        scene.character_data["Mira"] = mira
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, mira))
        request.assert_not_called()
        assert narrator.was_in_scene(mira) is False
        # Zed is on no entry with known presence either, but on a message
        assert narrator.was_in_scene(zed) is False
        scene.history = [CharacterMessage(message="Zed: here", present=["Zed"])]
        assert narrator.was_in_scene(zed) is True

    async def test_partial_archive_waits_for_the_last_chunk(self, scene, offscreen):
        narrator, zed = offscreen
        # messages 10-13 are Mara alone and not archived yet; the absence is
        # cut in two chunks by the summarizer, and the account waits for both
        scene.history = [
            CharacterMessage(message=f"Mara: line {i}", present=["Mara"])
            for i in range(14)
        ]
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, zed))
            request.assert_not_called()
            assert "Zed" in narrator.pending_returns
            actor = Actor(character=zed, agent=get_agent("conversation"))
            actor.scene = scene
            scene.actors.append(actor)
            scene.active_characters.append("Zed")
            scene.history.append(
                CharacterMessage(message="Zed: back", present=["Mara", "Zed"])
            )
            request.return_value = ("", {"response": "Zed rowed to the mainland."})

            scene.archived_history.append(
                {
                    "id": "a4",
                    "text": "First chunk.",
                    "ts": 4000,
                    "present": ["Mara"],
                    "start": 10,
                    "end": 11,
                }
            )
            await narrator.on_archive_add_offscreen(
                ArchiveEvent(
                    scene=scene,
                    event_type="archive_add",
                    text="First chunk.",
                    memory_id="a4",
                    ts=4000,
                    present=["Mara"],
                )
            )
            request.assert_not_called()
            assert "Zed" in narrator.pending_returns

            scene.archived_history.append(
                {
                    "id": "a5",
                    "text": "Second chunk.",
                    "ts": 4500,
                    "present": ["Mara"],
                    "start": 12,
                    "end": 13,
                }
            )
            await narrator.on_archive_add_offscreen(
                ArchiveEvent(
                    scene=scene,
                    event_type="archive_add",
                    text="Second chunk.",
                    memory_id="a5",
                    ts=4500,
                    present=["Mara"],
                )
            )
        request.assert_called_once()
        assert "Zed" not in narrator.pending_returns
        assert narrator.absence_fully_archived(zed) is True

    async def test_disabled_makes_no_request(self, scene, offscreen):
        narrator, zed = offscreen
        narrator.actions["offscreen_life"].enabled = False
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, zed))
        request.assert_not_called()

    async def test_min_entries_gate(self, scene, offscreen):
        narrator, zed = offscreen
        narrator.actions["offscreen_life"].config["min_entries"].value = 3
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, zed))
        request.assert_not_called()

    async def test_nothing_missed_makes_no_request(self, scene, offscreen):
        narrator, zed = offscreen
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(
                activation(scene, scene.character_data["Mara"])
            )
        request.assert_not_called()

    async def test_empty_response_stores_nothing(self, scene, offscreen):
        narrator, zed = offscreen
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"response": ""})
            await narrator.on_character_activated(activation(scene, zed))
        assert list(scene.world_state.facts) == ["F1"]

    async def test_activate_character_sends_the_signal(self, scene, offscreen):
        narrator, zed = offscreen
        seen = []

        async def recorder(event):
            seen.append(event)

        async_signals.get("character.activated").connect(recorder)
        try:
            with (
                ActiveScene(scene),
                patch.object(Prompt, "request", new_callable=AsyncMock) as request,
            ):
                request.return_value = ("", {"response": "Zed slept in the boat."})
                await activate_character(scene, "Zed")
                # the character now has an actor, so a second activation is a
                # no-op
                assert await activate_character(scene, zed) is False
        finally:
            async_signals.get("character.activated").disconnect(recorder)
        assert len(seen) == 1
        assert isinstance(seen[0], CharacterActivatedEvent)
        assert seen[0].character is zed and seen[0].scene is scene
        assert "Zed" in scene.active_characters
        # the narrator listened as well: the offscreen fact exists
        assert scene.world_state.facts["F2"].source == "offscreen"


class TestOffscreenLifeDeferral:
    """The missed span is archived only after the return: the narration waits."""

    async def test_return_before_the_cut_waits_for_the_archive(self, scene, offscreen):
        narrator, zed = offscreen
        # nothing archived yet for the span Zed missed
        scene.archived_history = [scene.archived_history[0]]
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"response": "Zed slept in the boat."})
            await narrator.on_character_activated(activation(scene, zed))
            request.assert_not_called()
            assert "Zed" in narrator.pending_returns
            # back in the scene: an actor, and the name in active_characters
            actor = Actor(character=zed, agent=get_agent("conversation"))
            actor.scene = scene
            scene.actors.append(actor)
            scene.active_characters.append("Zed")

            # the missed span is cut once the first message after the return is archived
            scene.archived_history.append(
                {
                    "id": "a2",
                    "text": "Mara found a sextant.",
                    "ts": 2000,
                    "present": ["Mara"],
                    "start": 4,
                    "end": 6,
                }
            )
            await narrator.on_archive_add_offscreen(
                ArchiveEvent(
                    scene=scene,
                    event_type="archive_add",
                    text="Mara found a sextant.",
                    memory_id="a2",
                    ts=2000,
                    present=["Mara"],
                )
            )
        request.assert_called_once()
        assert "Zed" not in narrator.pending_returns
        assert scene.world_state.facts["F2"].source == "offscreen"

    async def test_archive_that_covers_the_character_clears_the_wait(
        self, scene, offscreen
    ):
        narrator, zed = offscreen
        narrator.connect(scene)
        scene.archived_history = [scene.archived_history[0]]
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, zed))
            scene.active_characters.append("Zed")
            scene.archived_history.append(
                {
                    "id": "a4",
                    "text": "Zed and Mara talked.",
                    "ts": 4000,
                    "present": ["Mara", "Zed"],
                    "start": 4,
                    "end": 6,
                }
            )
            await narrator.on_archive_add_offscreen(
                ArchiveEvent(
                    scene=scene,
                    event_type="archive_add",
                    text="Zed and Mara talked.",
                    memory_id="a4",
                    ts=4000,
                    present=["Mara", "Zed"],
                )
            )
        request.assert_not_called()
        assert narrator.pending_returns == {}

    async def test_leaving_again_drops_the_wait(self, scene, offscreen):
        narrator, zed = offscreen
        scene.archived_history = [scene.archived_history[0]]
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await narrator.on_character_activated(activation(scene, zed))
            # Zed leaves before anything is archived
            await narrator.on_archive_add_offscreen(
                ArchiveEvent(
                    scene=scene,
                    event_type="archive_add",
                    text="x",
                    memory_id="a9",
                    ts=2000,
                    present=["Mara"],
                )
            )
        request.assert_not_called()
        assert narrator.pending_returns == {}
