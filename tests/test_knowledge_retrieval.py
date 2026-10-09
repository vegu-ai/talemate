"""
Retrieval: recency, diversity, entity lookup, cross-encoder reranking,
the optional AI memory pass and the character.activated signal.
"""

from itertools import combinations
from math import cos, radians, sin
from unittest.mock import AsyncMock, patch

import pytest
import numpy as np

from talemate.agents.context import ActiveAgent
from talemate.agents.conversation.knowledge import (
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
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.memory_pass import MemoryPassItem

DAY = 86400
from talemate.prompts import Prompt
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
                    f"Random history {number}",
                    ts=int(timestamp),
                    typ="history",
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
            typ="history",
            importance=3,
            embedding=vector(20),
        )
        old = doc(
            "F_old",
            "old fact",
            ts=70 * DAY,
            typ="history",
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
    async def test_reranker_owns_order_and_budget(self, scene, memory):
        config(memory, "recency_weight", 0)
        config(memory, "rerank", True)
        scene.ts = 100 * DAY
        memory.table = [
            doc("F2", "fresh candidate", 0.1, ts=99 * DAY, typ="history", importance=3),
            doc(
                "F1",
                "most relevant old candidate",
                0.2,
                ts=70 * DAY,
                typ="history",
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


@pytest.fixture
def opt_ins(scene):
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    conversation.actions["character_knowledge"].config["memory_pass"].value = False
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

    async def test_result_records_kept_and_dropped_memories(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")

        async def semantic(**kwargs):
            return [
                MemoryDocument(
                    "Edwin: Mara owes me two kroner.",
                    {"typ": "history", "knowledge_kind": "message"},
                    "m1",
                    "",
                ),
                MemoryDocument(
                    "Edwin keeps the light.",
                    {"typ": "details", "character": "Edwin", "detail": "role"},
                    "d1",
                    "",
                ),
                "The tide turns at six.",
            ]

        conversation.semantic_context = semantic
        with (
            ActiveScene(scene),
            ActiveAgent(conversation, conversation.converse),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = (
                "",
                {
                    "answer": "",
                    "items": items(
                        (3, "The tide turns at six."),
                        (1, "Alice heard that Mara owes Edwin two kroner."),
                    ),
                },
            )
            await conversation.rag_build(character=alice)
            result = conversation.take_memory_pass_record()
            assert conversation.take_memory_pass_record() is None
        assert result.status == "kept"
        assert result.candidates == 3
        assert result.model_dump()["kept"] == [
            MemoryPassItem(text="The tide turns at six.", kind="insight").model_dump(),
            MemoryPassItem(
                text="Alice heard that Mara owes Edwin two kroner.",
                retrieved="Edwin: Mara owes me two kroner.",
                kind="story",
            ).model_dump(),
        ]
        assert result.model_dump()["dropped"] == [
            MemoryPassItem(
                text="Edwin keeps the light.", kind="character", subject="Edwin"
            ).model_dump()
        ]

    @pytest.mark.parametrize(
        "answer, blocks, status, kept, dropped",
        [
            ("none", [], "none", [], ["a", "b", "c"]),
            ("I would keep the first one.", [], "fallback", ["a", "b", "c"], []),
        ],
    )
    async def test_result_records_none_and_fallback(
        self, scene, opt_ins, answer, blocks, status, kept, dropped
    ):
        conversation, alice = opt_ins
        enable(conversation, "memory_pass")
        with (
            ActiveScene(scene),
            ActiveAgent(conversation, conversation.converse),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"answer": answer, "items": blocks})
            await conversation.rag_build(character=alice)
            result = conversation.take_memory_pass_record()
        assert result.status == status
        assert result.candidates == 3
        assert [item.text for item in result.kept] == kept
        assert [item.text for item in result.dropped] == dropped
        assert {item.kind for item in result.kept + result.dropped} == {"insight"}

    async def test_no_record_without_the_pass(self, scene, opt_ins):
        conversation, alice = opt_ins
        with ActiveScene(scene), ActiveAgent(conversation, conversation.converse):
            await conversation.rag_build(character=alice)
            assert conversation.take_memory_pass_record() is None

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
