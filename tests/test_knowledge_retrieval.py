"""
Retrieval (#394 part G): recency term, diversity threshold, similarity
knowledge gate, entity lookup by id, cross-encoder rerank.
"""

from unittest.mock import AsyncMock, patch

import pytest

from talemate.agents.memory.rerank import (
    CrossEncoderReranker,
    RERANK_CANDIDATES,
    RERANK_KEEP,
    RERANK_MODEL,
)
from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.scene_message import CharacterMessage


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
    scene.ts = 1000

    async def fake_get(text, character=None, limit=15, **where):
        memory.calls.append({"text": text, "limit": limit, **where})
        return list(memory.table)

    memory.get = fake_get
    return memory


def config(memory, key, value):
    memory.actions["retrieval"].config[key].value = value


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# recency
# ---------------------------------------------------------------------------


class TestRecency:
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


# ---------------------------------------------------------------------------
# diversity
# ---------------------------------------------------------------------------


class TestDiversity:
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


# ---------------------------------------------------------------------------
# similarity knowledge gate
# ---------------------------------------------------------------------------


class TestSimilarityGate:
    @pytest.fixture
    def table(self, memory):
        config(memory, "recency_weight", 0)
        # the vectors below are all near-identical in cosine terms; the
        # diversity check is not under test here
        config(memory, "mmr_threshold", 1.0)
        memory.table = [
            doc("F1", "known fact", 0.2, typ="fact", embedding=[1.0, 0.0]),
            doc("F9", "twin fact", 0.25, typ="fact", embedding=[1.0, 0.1]),
            doc("F8", "far fact", 0.3, typ="fact", embedding=[1.0, 0.5]),
            doc("e1", "history", 0.35, embedding=[1.0, 0.05]),
        ]
        return memory.table

    @staticmethod
    def outside(doc):
        return doc.id == "F1"

    async def test_near_duplicate_of_a_known_fact_passes(self, scene, memory, table):
        get_agent("summarizer").actions["archive"].config[
            "fact_dedupe_distance"
        ].value = 0.15
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, filter=self.outside)
        # F9 (distance 0.1 from F1) passes, e1 (0.05) passes, F8 (0.5) does not
        assert result == ["known fact", "twin fact", "history"]

    async def test_gate_off_keeps_the_filter_strict(self, scene, memory, table):
        config(memory, "similarity_gate", False)
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5, filter=self.outside)
        assert result == ["known fact"]

    async def test_no_known_fact_means_no_gate(self, scene, memory, table):
        with ActiveScene(scene):
            result = await memory.multi_query(
                ["q"], iterate=5, filter=lambda d: d.id == "e1"
            )
        assert result == ["history"]

    async def test_without_a_filter_nothing_is_gated(self, scene, memory, table):
        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# cross-encoder rerank
# ---------------------------------------------------------------------------


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

    def test_agent_details_show_the_model_or_the_error(self):
        from talemate.agents.memory import ChromaDBMemoryAgent

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


# ---------------------------------------------------------------------------
# entity lookup
# ---------------------------------------------------------------------------


class TestEntityLookup:
    @pytest.fixture
    def zed(self, scene, memory):
        zed = Character(name="Zed", description="Zed is a smuggler.")
        scene.character_data = {"Zed": zed}
        scene.world_state.character_name_mappings = {"Zed": ["the smuggler"]}
        description = MemoryDocument(
            "Zed's description: Zed is a smuggler.",
            {"typ": "base_attribute", "character": "Zed", "attr": "description"},
            "Zed.description",
            "Zed's description: Zed is a smuggler.",
        )
        memory.get_document = AsyncMock(return_value={"Zed.description": description})
        return description

    async def test_named_inactive_character_is_fetched_by_id(self, scene, memory, zed):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            found = await conversation.entity_lookup(["Mara: I saw Zed at the pier."])
        assert found == [zed]
        ids = memory.get_document.call_args.args[0]
        assert ids[0] == "Zed.description" and "Zed.description.0" in ids

    async def test_alias_from_the_name_mappings_counts(self, scene, memory, zed):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            found = await conversation.entity_lookup(["Mara: the smuggler is back."])
        assert found == [zed]

    async def test_unrelated_lines_fetch_nothing(self, scene, memory, zed):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            assert await conversation.entity_lookup(["Mara: a quiet night."]) == []
        memory.get_document.assert_not_called()

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

    async def test_backend_without_id_lookup(self, scene, memory, zed):
        memory.get_document = AsyncMock(side_effect=NotImplementedError())
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            assert await conversation.entity_lookup(["Mara: I saw Zed."]) == []

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


# ---------------------------------------------------------------------------
# conversation opt-ins (AI knowledge gate, AI rerank, ledger)
# ---------------------------------------------------------------------------

from talemate.agents.conversation.knowledge import (  # noqa: E402
    parse_index_list,
    parse_ledger,
)
from talemate.knowledge.schema import Fact  # noqa: E402
from talemate.prompts import Prompt  # noqa: E402


class TestParsers:
    def test_index_list(self):
        assert parse_index_list(None) is None
        assert parse_index_list("") is None
        assert parse_index_list("none") == []
        assert parse_index_list("None.") == []
        assert parse_index_list("1, 3, 3, 0") == [1, 3]
        assert parse_index_list("keep 2 and 4") == [2, 4]
        assert parse_index_list("no idea") is None

    def test_ledger(self):
        assert parse_ledger(None) is None
        assert parse_ledger("") is None
        assert parse_ledger('{"Mara": ["F1", "F2"]}') == {"Mara": ["F1", "F2"]}
        assert parse_ledger('{"Mara": "F1"}') == {"Mara": ["F1"]}
        assert parse_ledger('{"Mara": ["F1"], "Edwin": 3}') == {"Mara": ["F1"]}
        assert parse_ledger("garbage") is None
        assert parse_ledger("[1]") is None
        assert parse_ledger('```json\n{"Mara": ["F1"]}\n```') == {"Mara": ["F1"]}


@pytest.fixture
def opt_ins(scene):
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    for key in ("llm_gate", "llm_rerank", "ledger"):
        conversation.actions["character_knowledge"].config[key].value = False
    conversation.actions["character_knowledge"].config["llm_rerank_keep"].value = 5
    alice = Character(name="Alice")
    edwin = Character(name="Edwin")
    scene.character_data = {"Alice": alice, "Edwin": edwin}
    scene.active_characters = ["Alice", "Edwin"]
    scene.ts = 500
    scene.rag_cache = {}

    async def semantic(**kwargs):
        return ["a", "b", "c"]

    conversation.semantic_context = semantic
    return conversation, alice


def enable(conversation, key, value=True):
    conversation.actions["character_knowledge"].config[key].value = value


class TestOptIns:
    def test_off_by_default(self, scene):
        conversation = get_agent("conversation")
        assert conversation.knowledge_llm_gate is False
        assert conversation.knowledge_llm_rerank is False
        assert conversation.knowledge_ledger is False
        assert conversation.knowledge_llm_rerank_keep == 5

    async def test_no_request_when_off(self, scene, opt_ins):
        conversation, alice = opt_ins
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.rag_build(character=alice) == ["a", "b", "c"]
        request.assert_not_called()

    async def test_gate_keeps_the_answered_candidates(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_gate")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"keep": "2, 3, 9"})
            assert await conversation.rag_build(character=alice) == ["b", "c"]
        assert request.call_args.args[0] == "conversation.knowledge-gate"
        assert request.call_args.args[1] is get_agent("world_state").client
        assert request.call_args.kwargs["vars"]["candidates"] == ["a", "b", "c"]
        assert request.call_args.kwargs["vars"]["character"] is alice

    async def test_gate_none_drops_everything(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_gate")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"keep": "none"})
            assert await conversation.rag_build(character=alice) == []

    async def test_gate_unreadable_answer_keeps_everything(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_gate")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"keep": None})
            assert await conversation.rag_build(character=alice) == ["a", "b", "c"]

    async def test_gate_only_for_a_speaker(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_gate")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.rag_build() == ["a", "b", "c"]
        request.assert_not_called()

    async def test_rerank_orders_and_keeps(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_rerank")
        enable(conversation, "llm_rerank_keep", 2)
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"order": "3, 1, 2"})
            assert await conversation.rag_build(character=alice) == ["c", "a"]
        assert request.call_args.args[0] == "conversation.memory-rerank"
        assert request.call_args.kwargs["vars"]["keep"] == 2

    async def test_rerank_unreadable_answer_keeps_the_merge(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_rerank")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"order": "?"})
            assert await conversation.rag_build(character=alice) == ["a", "b", "c"]

    async def test_gate_then_rerank(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_gate")
        enable(conversation, "llm_rerank")
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.side_effect = [("", {"keep": "1, 3"}), ("", {"order": "2, 1"})]
            assert await conversation.rag_build(character=alice) == ["c", "a"]
        assert request.call_count == 2

    async def test_container_off_disables_the_opt_ins(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "llm_gate")
        conversation.actions["character_knowledge"].enabled = False
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.rag_build(character=alice) == ["a", "b", "c"]
        request.assert_not_called()
        conversation.actions["character_knowledge"].enabled = True


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

    async def test_off_makes_no_request(self, scene, opt_ins, facts):
        conversation, alice = opt_ins
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            assert await conversation.record_learned_facts(alice, "Alice: hi") == {}
        request.assert_not_called()

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


# ---------------------------------------------------------------------------
# narrator offscreen life + character.activated
# ---------------------------------------------------------------------------

import talemate.emit.async_signals as async_signals  # noqa: E402
from talemate.character import activate_character  # noqa: E402
from talemate.events import ArchiveEvent, CharacterActivatedEvent  # noqa: E402
from talemate.knowledge.absence import absence_facts  # noqa: E402
from talemate.tale_mate import Actor  # noqa: E402


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
        assert [e["id"] for e in vars["missed"]] == ["a2", "a3"]
        assert [f.id for f in vars["missed_facts"]] == ["F1"]
        assert vars["elapsed"]
        fact = scene.world_state.facts["F2"]
        assert fact.source == "offscreen"
        assert fact.present == ["Zed"] and fact.subjects == ["Zed"]
        assert fact.ts == 5000
        assert "sailed to the mainland" in fact.text
        document = memory.add_many.call_args.args[0][0]
        assert document["id"] == "F2" and document["meta"]["source"] == "offscreen"
        assert document["meta"]["present"] == '["Zed"]'
        # only Zed knows it, and it never lists for anyone
        with ActiveScene(scene):
            assert "F2" not in [f.id for f in await absence_facts(scene, "Mara")]
            assert "F2" not in [f.id for f in await absence_facts(scene, "Zed")]

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
        # the agents are bound to the scene without connect() in the test
        # bootstrap; the narrator subscribes in connect()
        narrator.connect(scene)
        try:
            with (
                ActiveScene(scene),
                patch.object(scene, "add_actor", AsyncMock()),
                patch.object(Prompt, "request", new_callable=AsyncMock) as request,
            ):
                request.return_value = ("", {"response": "Zed slept in the boat."})
                await activate_character(scene, "Zed")
                # a second activation is a no-op (add_actor is patched away,
                # so the name lookup would not find the active actor: pass the object)
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
        narrator.connect(scene)
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
        narrator.connect(scene)
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
