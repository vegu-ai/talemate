"""
Atomic facts: parsing the FACTS output, storing facts with near-duplicate
merging and told-edges, the failure path, and the scene lifecycle.
"""

from unittest.mock import AsyncMock, patch

import pytest

import talemate.util as util
from conftest import MockScene, bootstrap_scene
from talemate.context import ActiveScene
from talemate.agents.memory.schema import MemoryDocument
from talemate.history import ArchiveEntry
from talemate.instance import get_agent
from talemate.knowledge.facts import (
    drop_facts_for_entries,
    fact_memory_document,
    parse_facts,
    store_facts,
)
from talemate.knowledge.schema import Fact, KnowledgeEdge
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, TimePassageMessage


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


class TestParseFacts:
    def test_json_list(self):
        facts = parse_facts(
            '[{"text": "Edwin keeps sea glass on the sill.", "subjects": ["Edwin"], "known_by": ["Mara"], "supersedes": null}]'
        )
        assert len(facts) == 1
        assert facts[0].subjects == ["Edwin"]
        assert facts[0].known_by == ["Mara"]
        assert facts[0].supersedes is None

    def test_fenced_json(self):
        raw = 'Here you go:\n```json\n[{"text": "A fact."}]\n```\n'
        facts = parse_facts(raw)
        assert facts and facts[0].text == "A fact."
        assert facts[0].subjects == [] and facts[0].known_by == []

    def test_object_with_facts_key(self):
        facts = parse_facts('{"facts": [{"text": "A fact.", "supersedes": "F3"}]}')
        assert facts[0].supersedes == "F3"

    def test_supersedes_none_strings(self):
        for value in ("none", "null", ""):
            facts = parse_facts('[{"text": "x", "supersedes": "%s"}]' % value)
            assert facts[0].supersedes is None

    def test_string_subject_becomes_list(self):
        facts = parse_facts('[{"text": "x", "subjects": "Edwin"}]')
        assert facts[0].subjects == ["Edwin"]

    def test_prose_fails(self):
        assert parse_facts("The chapter establishes that Edwin is sad.") is None

    def test_empty_fails(self):
        assert parse_facts(None) is None
        assert parse_facts("   ") is None

    def test_item_without_text_fails(self):
        assert parse_facts('[{"subjects": ["Edwin"]}]') is None

    def test_not_a_list_fails(self):
        assert parse_facts('{"text": "x"}') is None


# ---------------------------------------------------------------------------
# storing
# ---------------------------------------------------------------------------


class FakeMemory:
    def __init__(self, scene, neighbours=None, distance=1.0):
        self.scene = scene
        self.neighbours = neighbours or []
        self.distance = distance
        self.added = []
        self.deleted = []

    async def get(self, text, character=None, limit=15, **where):
        return [
            MemoryDocument(f.text, {"typ": "fact"}, f.id, f.text)
            for f in self.neighbours
        ]

    async def compare_strings(self, a, b):
        return {"cosine_similarity": 1.0, "euclidean_distance": self.distance}

    async def add_many(self, objects):
        self.added.extend(objects)

    async def delete(self, meta):
        self.deleted.append(meta)


@pytest.fixture
def fake_memory(scene):
    memory = FakeMemory(scene)
    with patch("talemate.knowledge.facts.get_agent", return_value=memory):
        yield memory


class TestStoreFacts:
    async def test_stores_new_facts_with_ids_and_documents(self, scene, fake_memory):
        parsed = parse_facts(
            '[{"text": "Mara found a sextant.", "subjects": ["Mara", "sextant"]},'
            ' {"text": "The Sorena sank in 1973.", "subjects": ["Sorena"], "supersedes": "F99"}]'
        )
        stored = await store_facts(scene, "e1", ["Mara"], 500, parsed, 0.15)
        assert [f.id for f in stored] == ["F1", "F2"]
        assert scene.world_state.fact_counter == 2
        f1 = scene.world_state.facts["F1"]
        assert f1.archive_id == "e1" and f1.present == ["Mara"] and f1.ts == 500
        # an unknown supersedes id is dropped, not stored
        assert scene.world_state.facts["F2"].supersedes is None
        docs = {d["id"]: d for d in fake_memory.added}
        assert docs["F1"]["meta"]["typ"] == "fact"
        assert docs["F1"]["meta"]["present"] == '["Mara"]'
        assert docs["F1"]["meta"]["archive_id"] == "e1"

    async def test_supersedes_known_fact(self, scene, fake_memory):
        scene.world_state.facts["F1"] = Fact(id="F1", text="old")
        scene.world_state.fact_counter = 1
        parsed = parse_facts('[{"text": "new", "supersedes": "F1"}]')
        await store_facts(scene, "e2", None, 0, parsed, 0.15)
        assert scene.world_state.facts["F2"].supersedes == "F1"

    async def test_told_edges_for_absent_learners(self, scene, fake_memory):
        parsed = parse_facts('[{"text": "x", "known_by": ["Mara", "Edwin"]}]')
        await store_facts(scene, "e1", ["Mara"], 7, parsed, 0.15)
        fact = scene.world_state.facts["F1"]
        # Mara was present: derived, never stored; Edwin was told
        assert fact.known_by == {"Edwin": "told"}
        edges = scene.world_state.knowledge
        assert len(edges) == 1
        assert (
            edges[0].character,
            edges[0].target,
            edges[0].kind,
            edges[0].source,
            edges[0].ts,
        ) == (
            "Edwin",
            "F1",
            "grant",
            "told",
            7,
        )

    async def test_near_duplicate_is_a_restatement(self, scene, fake_memory):
        existing = Fact(id="F1", text="Mara found a sextant.", archive_id="e1", ts=1)
        scene.world_state.facts["F1"] = existing
        scene.world_state.fact_counter = 1
        fake_memory.neighbours = [existing]
        fake_memory.distance = 0.05
        parsed = parse_facts(
            '[{"text": "Mara discovered a brass sextant.", "known_by": ["Edwin"]}]'
        )
        stored = await store_facts(scene, "e2", ["Mara"], 9, parsed, 0.15)
        assert stored == []
        assert len(scene.world_state.facts) == 1
        assert existing.restatements == 1 and existing.last_seen_ts == 9
        assert existing.known_by == {"Edwin": "told"}
        assert fake_memory.added[-1]["id"] == "F1"
        assert fake_memory.added[-1]["meta"]["restatements"] == 1

    async def test_far_neighbour_is_stored(self, scene, fake_memory):
        existing = Fact(id="F1", text="something else", archive_id="e1")
        scene.world_state.facts["F1"] = existing
        scene.world_state.fact_counter = 1
        fake_memory.neighbours = [existing]
        fake_memory.distance = 0.9
        stored = await store_facts(
            scene, "e2", None, 0, parse_facts('[{"text": "new"}]'), 0.15
        )
        assert [f.id for f in stored] == ["F2"]

    async def test_drop_facts_for_entries(self, scene, fake_memory):
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="a", archive_id="e1"),
            "F2": Fact(id="F2", text="b", archive_id="e2", supersedes="F1"),
        }
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F1"),
            KnowledgeEdge(character="Edwin", target="F2"),
        ]
        await drop_facts_for_entries(scene, {"e1"})
        assert list(scene.world_state.facts) == ["F2"]
        assert scene.world_state.facts["F2"].supersedes is None
        assert [e.target for e in scene.world_state.knowledge] == ["F2"]
        assert fake_memory.deleted == [{"ids": ["F1"]}]

    def test_fact_memory_document_unknown_presence(self):
        doc = fact_memory_document(Fact(id="F1", text="x"))
        assert doc["meta"]["presence_known"] is False and "present" not in doc["meta"]


# ---------------------------------------------------------------------------
# summarizer integration
# ---------------------------------------------------------------------------


def _chars(source):
    if isinstance(source, list):
        return sum(_chars(s) for s in source)
    return len(str(source))


@pytest.fixture
def summarizer_scene():
    scene = MockScene()
    agents = bootstrap_scene(scene)
    summarizer = agents["summarizer"]
    with ActiveScene(scene), patch.object(util, "count_tokens", side_effect=_chars):
        yield scene, summarizer


RESPONSE_WITH_FACTS = (
    "ANALYSIS: ...\nSUMMARY: Edwin told Mara about the wreck.\nFACTS:\n"
    '[{"text": "Edwin told Mara the Sorena sank in 1973.", "subjects": ["Edwin", "Mara", "Sorena"], "known_by": ["Mara"]}]'
)


class TestSummarizeWithFacts:
    async def test_returns_summary_and_facts(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        spec_extracted = {
            "summary": "Edwin told Mara about the wreck.",
            "facts": '[{"text": "Edwin told Mara the Sorena sank in 1973.", "known_by": ["Mara"]}]',
        }
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (RESPONSE_WITH_FACTS, spec_extracted)
            summary, facts = await summarizer.summarize("dialogue", return_facts=True)
        assert summary == "Edwin told Mara about the wreck."
        assert facts and facts[0].known_by == ["Mara"]
        assert mock_request.call_args.kwargs["vars"]["extract_facts"] is True

    async def test_plain_call_keeps_the_string_contract(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "SUMMARY: Just prose.",
                {"summary": "Just prose.", "facts": None},
            )
            assert await summarizer.summarize("dialogue") == "Just prose."
            assert mock_request.call_args.kwargs["vars"]["extract_facts"] is False

    async def test_unparseable_facts_yield_none(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "SUMMARY: prose",
                {"summary": "prose", "facts": "some prose, no list"},
            )
            summary, facts = await summarizer.summarize("dialogue", return_facts=True)
        assert summary == "Prose" and facts is None

    async def test_extract_facts_off_skips_the_section(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["extract_facts"].value = False
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "SUMMARY: prose",
                {"summary": "prose", "facts": None},
            )
            summary, facts = await summarizer.summarize("dialogue", return_facts=True)
        assert facts is None
        assert mock_request.call_args.kwargs["vars"]["extract_facts"] is False
        assert summarizer._facts_status(None) is None

    async def test_known_facts_are_passed_to_the_prompt(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        scene.world_state.facts["F1"] = Fact(id="F1", text="older fact")
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "SUMMARY: prose",
                {"summary": "prose", "facts": "[]"},
            )
            await summarizer.summarize("dialogue", return_facts=True)
        previous = mock_request.call_args.kwargs["vars"]["previous_facts"]
        assert [f.id for f in previous] == ["F1"]


class TestBuildArchiveFacts:
    def _history(self):
        both = ["Mara", "Edwin"]
        return [
            CharacterMessage(message="Mara: one", present=both),
            CharacterMessage(message="Edwin: two", present=both),
            CharacterMessage(message="Mara: three", present=both),
            TimePassageMessage(ts=60, message="A minute passes", present=both),
            CharacterMessage(message="Mara: trailing", present=both),
        ]

    async def test_facts_stored_with_the_entry(self, summarizer_scene, fake_memory):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["threshold"].value = 100000
        scene.history = self._history()

        async def stub(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return "SUMM", parse_facts(
                '[{"text": "Edwin and Mara met.", "known_by": ["Carol"]}]'
            )

        summarizer.summarize = stub
        assert await summarizer.build_archive(scene) is True
        entry = scene.archived_history[0]
        assert entry["facts_status"] == "ok"
        fact = scene.world_state.facts["F1"]
        assert fact.archive_id == entry["id"]
        assert fact.present == ["Edwin", "Mara"]
        assert fact.ts == entry["ts"]
        assert scene.world_state.knowledge[0].character == "Carol"

    async def test_failed_facts_keep_the_summary_and_mark_the_entry(
        self, summarizer_scene, fake_memory
    ):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["threshold"].value = 100000
        scene.history = self._history()

        async def stub(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return "SUMM", None

        summarizer.summarize = stub
        assert await summarizer.build_archive(scene) is True
        entry = scene.archived_history[0]
        assert entry["text"] == "SUMM"
        assert entry["facts_status"] == "failed"
        assert scene.world_state.facts == {}

    async def test_extract_facts_off_leaves_status_unset(
        self, summarizer_scene, fake_memory
    ):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["threshold"].value = 100000
        summarizer.actions["archive"].config["extract_facts"].value = False
        scene.history = self._history()

        async def stub(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return "SUMM", None

        summarizer.summarize = stub
        assert await summarizer.build_archive(scene) is True
        assert "facts_status" not in scene.archived_history[0]


# ---------------------------------------------------------------------------
# scene lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_commit_to_memory_re_adds_facts(self, scene):
        memory = get_agent("memory")
        added = []

        async def fake_add_many(objects):
            added.extend(objects)

        memory.add_many = fake_add_many
        memory.drop_db = lambda: None

        async def fake_set_db():
            pass

        memory.set_db = fake_set_db
        scene.world_state.facts["F1"] = Fact(
            id="F1", text="a fact", present=["Mara"], ts=3
        )
        with ActiveScene(scene):
            await scene.commit_to_memory()
        docs = {o["id"]: o for o in added}
        assert docs["F1"]["meta"]["typ"] == "fact"
        assert docs["F1"]["meta"]["present"] == '["Mara"]'

    def test_reset_drops_summary_facts_and_their_edges(self, scene):
        scene.archived_history = [
            {"id": "s0", "text": "static", "ts": 0},
            {"id": "e1", "text": "x", "ts": 0, "start": 0, "end": 1},
        ]
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="a", archive_id="e1"),
            "F2": Fact(id="F2", text="manual", source="manual"),
        }
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F1"),
            KnowledgeEdge(character="Edwin", target="F2"),
            KnowledgeEdge(character="Edwin", target="Mara.age"),
        ]
        scene.reset()
        assert list(scene.world_state.facts) == ["F2"]
        assert [e.target for e in scene.world_state.knowledge] == ["F2", "Mara.age"]

    def test_archive_entry_facts_status_round_trip(self):
        entry = ArchiveEntry(text="x", facts_status="failed")
        assert entry.model_dump(exclude_none=True)["facts_status"] == "failed"
        assert "facts_status" not in ArchiveEntry(text="x").model_dump(
            exclude_none=True
        )


class TestRegenerateFacts:
    async def test_replaces_facts_and_keeps_the_text(
        self, summarizer_scene, fake_memory
    ):
        from talemate.history import HistoryEntry

        scene, summarizer = summarizer_scene
        scene.history = [
            CharacterMessage(message="Mara: one", present=["Mara"]),
            CharacterMessage(message="Mara: two", present=["Mara"]),
        ]
        scene.archived_history = [
            {
                "id": "e1",
                "text": "kept",
                "ts": 5,
                "start": 0,
                "end": 1,
                "present": ["Mara"],
                "facts_status": "failed",
            }
        ]
        scene.world_state.facts = {"F1": Fact(id="F1", text="stale", archive_id="e1")}
        scene.world_state.fact_counter = 1

        async def stub(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return "NEW SUMMARY", parse_facts('[{"text": "fresh"}]')

        summarizer.summarize = stub
        entry = HistoryEntry(
            text="kept", ts=5, index=0, layer=0, id="e1", start=0, end=1
        )
        status = await summarizer.regenerate_facts(entry)

        assert status == "ok"
        assert scene.archived_history[0]["text"] == "kept"
        assert scene.archived_history[0]["facts_status"] == "ok"
        assert [f.text for f in scene.world_state.facts.values()] == ["fresh"]
        assert scene.world_state.facts["F2"].archive_id == "e1"

    async def test_failure_marks_the_entry_and_keeps_nothing(
        self, summarizer_scene, fake_memory
    ):
        from talemate.history import HistoryEntry

        scene, summarizer = summarizer_scene
        scene.history = [CharacterMessage(message="Mara: one", present=["Mara"])]
        scene.archived_history = [
            {
                "id": "e1",
                "text": "kept",
                "ts": 5,
                "start": 0,
                "end": 0,
                "present": ["Mara"],
                "facts_status": "ok",
            }
        ]
        scene.world_state.facts = {"F1": Fact(id="F1", text="stale", archive_id="e1")}

        async def stub(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return "NEW SUMMARY", None

        summarizer.summarize = stub
        entry = HistoryEntry(
            text="kept", ts=5, index=0, layer=0, id="e1", start=0, end=0
        )
        assert await summarizer.regenerate_facts(entry) == "failed"
        assert scene.archived_history[0]["facts_status"] == "failed"
        assert scene.world_state.facts == {}
