"""
Atomic facts: parsing the FACTS output, storing facts with near-duplicate
merging and told-edges, the failure path, and the scene lifecycle.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import talemate.util as util
from conftest import MockScene, bootstrap_scene
from talemate.context import ActiveScene
from talemate.agents.memory.schema import MemoryDocument
from talemate.history import ArchiveEntry
from talemate.instance import get_agent
from talemate.knowledge.facts import (
    SpanLine,
    drop_facts_for_entries,
    fact_memory_document,
    parse_facts,
    store_facts,
    verify_restatements,
)
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.schema import Fact, FactRestatement, KnowledgeEdge
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

    def test_brackets_inside_text_are_fine(self):
        assert (
            parse_facts('[{"text": "She called it Plan B]."}]')[0].text
            == "She called it Plan B]."
        )
        assert parse_facts('[{"text": "The inscription begins [REDACTED."}]')[
            0
        ].text.startswith("The inscription")

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("12", 12),
            (" [12] ", 12),
            (1043.0, 1043),
            (1043.5, None),
            ("²", None),
            ("①", None),
            ("1043.0", None),
            ("abc", None),
            (True, None),
            ("[INTRO]", "intro"),
        ],
    )
    def test_message_id_readings(self, value, expected):
        # one unreadable id drops that fact, never the whole list
        facts = parse_facts(json.dumps([{"text": "x", "message_id": value}]))
        assert facts[0].message_id == expected

    def test_trailing_prose_after_the_list(self):
        assert parse_facts('[{"text": "x"}]\nThat is all.')[0].text == "x"


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

    async def compare_string_lists(
        self, list_a, list_b, similarity_threshold=None, distance_threshold=None
    ):
        self.list_compares = getattr(self, "list_compares", 0) + 1
        matches = [
            (i, j, self.distance)
            for i in range(len(list_a))
            for j in range(len(list_b))
            if distance_threshold is None or self.distance <= distance_threshold
        ]
        return {"distance_matches": matches, "similarity_matches": []}

    async def add_many(self, objects):
        self.added.extend(objects)

    async def delete(self, meta):
        self.deleted.append(meta)


@pytest.fixture
def fake_memory():
    # standalone on purpose: pulling the conftest `scene` fixture here would
    # re-bootstrap every agent onto a second scene
    memory = FakeMemory(None)
    with patch("talemate.knowledge.facts.get_agent", return_value=memory):
        yield memory


class TestStoreFacts:
    async def test_stores_new_facts_with_ids_and_documents(self, scene, fake_memory):
        parsed = parse_facts(
            '[{"text": "Mara found a sextant.", "subjects": ["Mara", "sextant"]},'
            ' {"text": "The Sorena sank in 1973.", "subjects": ["Sorena"], "supersedes": "F99"}]'
        )
        stored = await store_facts(scene, "e1", parsed, 0.15, present=["Mara"], ts=500)
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
        await store_facts(scene, "e2", parsed, 0.15, ts=0)
        assert scene.world_state.facts["F2"].supersedes == "F1"

    async def test_told_edges_for_absent_learners(self, scene, fake_memory):
        parsed = parse_facts('[{"text": "x", "known_by": ["Mara", "Edwin"]}]')
        await store_facts(scene, "e1", parsed, 0.15, present=["Mara"], ts=7)
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
        existing = Fact(
            id="F1",
            text="Mara found a sextant.",
            archive_id="e1",
            ts=1,
            present=["Mara"],
        )
        scene.world_state.facts["F1"] = existing
        scene.world_state.fact_counter = 1
        fake_memory.neighbours = [existing]
        fake_memory.distance = 0.05
        parsed = parse_facts(
            '[{"text": "Mara discovered a brass sextant.", "known_by": ["Edwin"]}]'
        )
        stored = await store_facts(scene, "e2", parsed, 0.15, present=["Mara"], ts=9)
        assert stored == []
        assert len(scene.world_state.facts) == 1
        assert existing.restatements == 1 and existing.last_seen_ts == 9
        assert existing.known_by == {"Edwin": "told"}
        assert fake_memory.added[-1]["id"] == "F1"
        assert fake_memory.added[-1]["meta"]["restatements"] == 1

    async def test_restatement_audience_learns_the_stored_fact(
        self, scene, fake_memory
    ):
        # chapter 1: Edwin alone; chapter 5: Edwin tells Mara on screen
        existing = Fact(
            id="F1",
            text="The Sorena sank in 1973.",
            archive_id="e1",
            ts=1,
            present=["Edwin"],
        )
        scene.world_state.facts["F1"] = existing
        scene.world_state.fact_counter = 1
        fake_memory.neighbours = [existing]
        fake_memory.distance = 0.05
        parsed = parse_facts(
            '[{"text": "Edwin says the Sorena went down in 1973.", "known_by": ["Mara"]}]'
        )
        await store_facts(scene, "e5", parsed, 0.15, present=["Edwin", "Mara"], ts=50)
        assert existing.known_by == {"Mara": "told"}
        assert [(e.character, e.target) for e in scene.world_state.knowledge] == [
            ("Mara", "F1")
        ]
        from talemate.knowledge.graph import bucket

        assert "F1" in [f.id for f, _ in bucket(scene, "Mara")]

    async def test_unknown_presence_writes_no_edges(self, scene, fake_memory):
        parsed = parse_facts('[{"text": "x", "known_by": ["Mara", "Edwin"]}]')
        await store_facts(scene, "e1", parsed, 0.15, ts=7)
        fact = scene.world_state.facts["F1"]
        assert fact.known_by == {} and scene.world_state.knowledge == []

    async def test_restatement_of_unknown_presence_writes_no_edges(
        self, scene, fake_memory
    ):
        existing = Fact(id="F1", text="x", archive_id="e1", ts=1)
        scene.world_state.facts["F1"] = existing
        scene.world_state.fact_counter = 1
        fake_memory.neighbours = [existing]
        fake_memory.distance = 0.05
        await store_facts(
            scene,
            "e2",
            parse_facts('[{"text": "x again", "known_by": ["Carol"]}]'),
            0.15,
            present=["Mara"],
            ts=9,
        )
        assert existing.known_by == {} and scene.world_state.knowledge == []

    async def test_near_duplicates_inside_one_batch_merge(self, scene, fake_memory):
        fake_memory.distance = 0.05
        parsed = parse_facts(
            '[{"text": "Mara found a sextant."}, {"text": "Mara discovered a sextant."}]'
        )
        stored = await store_facts(scene, "e1", parsed, 0.15, present=["Mara"], ts=1)
        assert [f.id for f in stored] == ["F1"]
        assert scene.world_state.facts["F1"].restatements == 1
        # one embedding pass per item against the batch, and one document per fact id
        assert fake_memory.list_compares == 1
        assert [d["id"] for d in fake_memory.added] == ["F1"]
        assert fake_memory.added[0]["meta"]["restatements"] == 1

    async def test_far_neighbour_is_stored(self, scene, fake_memory):
        existing = Fact(id="F1", text="something else", archive_id="e1")
        scene.world_state.facts["F1"] = existing
        scene.world_state.fact_counter = 1
        fake_memory.neighbours = [existing]
        fake_memory.distance = 0.9
        stored = await store_facts(
            scene, "e2", parse_facts('[{"text": "new"}]'), 0.15, ts=0
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

    def _lines(self):
        return {
            11: SpanLine(message_id=11, message_digest="d11", present=["Mara"], ts=40),
            12: SpanLine(
                message_id=12, message_digest="d12", present=["Mara", "Edwin"], ts=90
            ),
        }

    async def test_bound_facts_take_their_line(self, scene, fake_memory):
        parsed = parse_facts(
            '[{"text": "Mara found a sextant.", "message_id": 12},'
            ' {"text": "Nobody knows this line.", "message_id": 99},'
            ' {"text": "A fact without a line."}]'
        )
        stored = await store_facts(scene, "e1", parsed, 0.15, lines=self._lines())
        assert [f.id for f in stored] == ["F1"]
        fact = scene.world_state.facts["F1"]
        assert (fact.message_id, fact.message_digest) == (12, "d12")
        assert (fact.present, fact.ts, fact.last_seen_ts) == (["Mara", "Edwin"], 90, 90)
        assert fact.archive_id == "e1" and fact.source == "summary"
        assert len(scene.world_state.facts) == 1

    async def test_intro_line_binds_to_the_opening(self, scene, fake_memory):
        intro = SpanLine(message_id=11, message_digest="d11", present=["Edwin"], ts=40)
        parsed = parse_facts('[{"text": "The keeper is old.", "message_id": "intro"}]')
        await store_facts(scene, "e1", parsed, 0.15, lines=self._lines(), intro=intro)
        fact = scene.world_state.facts["F1"]
        assert fact.message_id == 11 and fact.present == ["Edwin"]
        parsed = parse_facts('[{"text": "Dropped.", "message_id": "intro"}]')
        assert await store_facts(scene, "e1", parsed, 0.15, lines=self._lines()) == []

    async def test_restates_records_a_restatement(self, scene, fake_memory):
        existing = Fact(
            id="F1",
            text="Mara found a sextant.",
            archive_id="e1",
            message_id=5,
            message_digest="d5",
            ts=1,
            present=["Mara"],
        )
        scene.world_state.facts["F1"] = existing
        scene.world_state.fact_counter = 1
        parsed = parse_facts(
            '[{"text": "Mara shows Edwin the sextant she found.", "restates": "F1",'
            ' "message_id": 12, "known_by": ["Edwin"]}]'
        )
        assert await store_facts(scene, "e2", parsed, 0.15, lines=self._lines()) == []
        assert len(scene.world_state.facts) == 1
        assert existing.restatements == 1 and existing.last_seen_ts == 90
        assert [
            (r.message_id, r.message_digest, r.archive_id) for r in existing.restated_by
        ] == [(12, "d12", "e2")]
        # the restating line's audience learned the stored fact
        assert existing.known_by == {"Edwin": "told"}
        assert [
            (e.character, e.target, e.message_id) for e in scene.world_state.knowledge
        ] == [("Edwin", "F1", 12)]
        assert fake_memory.added[-1]["meta"]["restatements"] == 1

    async def test_restates_unknown_id_is_a_new_fact(self, scene, fake_memory):
        parsed = parse_facts('[{"text": "New.", "restates": "F77", "message_id": 11}]')
        stored = await store_facts(scene, "e1", parsed, 0.15, lines=self._lines())
        assert [f.id for f in stored] == ["F1"]

    def test_restates_counts_only_for_an_offered_id(self):
        parsed = parse_facts(
            '[{"text": "A.", "restates": "F1"}, {"text": "B.", "restates": "F2"},'
            ' {"text": "C."}]'
        )
        assert [item.restates for item in verify_restatements(parsed, {"F1"})] == [
            "F1",
            None,
            None,
        ]

    async def test_regenerating_an_older_chapter_keeps_the_earliest_origin(
        self, scene, fake_memory
    ):
        # F1 came from line 5 (chapter e1); line 12 (chapter e2) restated it
        fact = Fact(
            id="F1",
            text="Mara found a sextant.",
            archive_id="e1",
            message_id=5,
            message_digest="d5",
            ts=1,
            present=["Mara"],
            last_seen_ts=90,
            restatements=1,
            restated_by=(
                FactRestatement(
                    message_id=12,
                    message_digest="d12",
                    archive_id="e2",
                    present=["Mara", "Edwin"],
                    ts=90,
                ),
            ),
        )
        scene.world_state.facts["F1"] = fact
        scene.world_state.fact_counter = 1
        await drop_facts_for_entries(scene, {"e1"})
        # the restatement is the origin for now, with its audience and time
        assert (
            fact.message_id,
            fact.archive_id,
            fact.present,
            fact.ts,
            fact.last_seen_ts,
        ) == (12, "e2", ["Mara", "Edwin"], 90, 90)
        assert fact.restated_by == () and fact.restatements == 0
        assert fake_memory.deleted == []
        assert fake_memory.added[-1]["meta"]["ts"] == 90
        # the re-extraction links the earlier line again: it is the origin,
        # and the later line goes back to being a restatement
        parsed = parse_facts(
            '[{"text": "Mara found a sextant.", "restates": "F1", "message_id": 5}]'
        )
        lines = {5: SpanLine(message_id=5, message_digest="d5", present=["Mara"], ts=1)}
        assert await store_facts(scene, "e1", parsed, 0.15, lines=lines) == []
        assert (
            fact.message_id,
            fact.archive_id,
            fact.present,
            fact.ts,
            fact.last_seen_ts,
        ) == (5, "e1", ["Mara"], 1, 90)
        assert [
            (r.message_id, r.archive_id, r.present, r.ts) for r in fact.restated_by
        ] == [(12, "e2", ["Mara", "Edwin"], 90)]
        # Edwin witnessed the demoted line: his edge names that line, so the
        # cleanup of that line can take it back
        assert fact.known_by == {"Edwin": "told"}
        assert [
            (e.character, e.target, e.message_id, e.ts)
            for e in scene.world_state.knowledge
        ] == [("Edwin", "F1", 12, 90)]
        assert fake_memory.added[-1]["meta"]["ts"] == 1

    async def test_a_static_entry_takes_the_origin_back(self, scene, fake_memory):
        # a backstory fact whose static entry was regenerated: the later line
        # holds the origin for now
        fact = Fact(
            id="F1",
            text="Mara grew up at the lighthouse.",
            archive_id="e2",
            message_id=12,
            message_digest="d12",
            ts=90,
            present=["Mara", "Edwin"],
            last_seen_ts=90,
        )
        scene.world_state.facts["F1"] = fact
        scene.world_state.fact_counter = 1
        parsed = parse_facts(
            '[{"text": "Mara grew up at the lighthouse.", "restates": "F1"}]'
        )
        assert (
            await store_facts(
                scene, "backstory", parsed, 0.15, lines=None, present=["Mara"], ts=0
            )
            == []
        )
        # the static entry comes before every message: it is the origin again
        assert (
            fact.message_id,
            fact.message_digest,
            fact.archive_id,
            fact.present,
            fact.ts,
            fact.last_seen_ts,
        ) == (None, None, "backstory", ["Mara"], 0, 90)
        assert [
            (r.message_id, r.archive_id, r.present, r.ts) for r in fact.restated_by
        ] == [(12, "e2", ["Mara", "Edwin"], 90)]
        assert [
            (e.character, e.message_id, e.ts) for e in scene.world_state.knowledge
        ] == [("Edwin", 12, 90)]

    async def test_a_swap_from_an_unknown_audience_grants_the_listed_learners(
        self, scene, fake_memory
    ):
        # line 12 was pushed with no active character (unknown audience); the
        # regenerate of the older chapter finds line 5 restating it
        fact = Fact(
            id="F1",
            text="Mara found a sextant.",
            archive_id="e2",
            message_id=12,
            message_digest="d12",
            ts=90,
            present=None,
            last_seen_ts=90,
        )
        scene.world_state.facts["F1"] = fact
        scene.world_state.fact_counter = 1
        parsed = parse_facts(
            '[{"text": "Mara found a sextant.", "restates": "F1", "message_id": 5,'
            ' "known_by": ["Zed"]}]'
        )
        lines = {5: SpanLine(message_id=5, message_digest="d5", present=["Mara"], ts=1)}
        assert await store_facts(scene, "e1", parsed, 0.15, lines=lines) == []
        assert (fact.message_id, fact.present, fact.ts) == (5, ["Mara"], 1)
        assert [r.message_id for r in fact.restated_by] == [12]
        # the gate reads the audience after the swap: Zed learned it at line 5
        assert fact.known_by == {"Zed": "told"}
        assert [
            (e.character, e.message_id, e.ts) for e in scene.world_state.knowledge
        ] == [("Zed", 5, 1)]

    async def test_an_older_restatement_does_not_lower_last_seen(
        self, scene, fake_memory
    ):
        fact = Fact(
            id="F1",
            text="Mara found a sextant.",
            archive_id="e2",
            message_id=12,
            message_digest="d12",
            ts=90,
            present=["Mara", "Edwin"],
            last_seen_ts=90,
        )
        scene.world_state.facts["F1"] = fact
        scene.world_state.fact_counter = 1
        parsed = parse_facts(
            '[{"text": "Mara found a sextant.", "restates": "F1", "message_id": 11}]'
        )
        assert await store_facts(scene, "e1", parsed, 0.15, lines=self._lines()) == []
        assert (fact.message_id, fact.ts, fact.last_seen_ts) == (11, 40, 90)
        assert [r.message_id for r in fact.restated_by] == [12]

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


class TestSpecs:
    def test_prose_containing_facts_colon_is_not_truncated(self):
        from talemate.agents.summarize.response_specs import (
            SUMMARY_SPEC,
            SUMMARY_WITH_FACTS_SPEC,
        )

        text = 'ANALYSIS: ...\nSUMMARY: Mara laid out the facts: the Sorena sank in 1973, the light failed.\n<FACTS>\n[{"text": "x"}]\n</FACTS>'
        with_facts = SUMMARY_WITH_FACTS_SPEC.extract_all(text)
        assert (
            with_facts["summary"]
            == "Mara laid out the facts: the Sorena sank in 1973, the light failed."
        )
        assert parse_facts(with_facts["facts"])[0].text == "x"
        plain = SUMMARY_SPEC.extract_all(
            "SUMMARY: Mara laid out the facts: the light failed."
        )
        assert plain["summary"] == "Mara laid out the facts: the light failed."

    def test_open_facts_tag_still_parses(self):
        from talemate.agents.summarize.response_specs import SUMMARY_WITH_FACTS_SPEC

        out = SUMMARY_WITH_FACTS_SPEC.extract_all(
            'SUMMARY: prose\n<FACTS>\n[{"text": "open"}]'
        )
        assert out["summary"] == "prose"
        assert parse_facts(out["facts"])[0].text == "open"


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
        from talemate.agents.summarize.response_specs import SUMMARY_WITH_FACTS_SPEC

        assert mock_request.call_args.kwargs["response_spec"] is SUMMARY_WITH_FACTS_SPEC

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

    async def test_restates_outside_the_offered_list_is_dropped(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        scene.world_state.facts["F1"] = Fact(id="F1", text="stored, not offered")
        response = (
            "SUMMARY: prose",
            {
                "summary": "prose",
                "facts": '[{"text": "Repeat.", "restates": "F1", "message_id": 1}]',
            },
        )
        with (
            patch.object(Prompt, "request", AsyncMock(return_value=response)),
            patch("talemate.agents.summarize.previous_facts", return_value=[]),
        ):
            _, parsed = await summarizer.summarize("dialogue", return_facts=True)
        assert [item.restates for item in parsed] == [None]
        with patch.object(Prompt, "request", AsyncMock(return_value=response)):
            _, parsed = await summarizer.summarize("dialogue", return_facts=True)
        assert [item.restates for item in parsed] == ["F1"]


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

        async def stub(text, **kwargs):
            assert kwargs["line_ids"] is True
            assert text.startswith(f"[{scene.history[0].id}] Mara: one")
            return "SUMM", parse_facts(
                '[{"text": "Edwin and Mara met.", "known_by": ["Carol"],'
                f' "message_id": {scene.history[1].id}}}]'
            )

        summarizer.summarize = stub
        assert await summarizer.build_archive(scene) is True
        entry = scene.archived_history[0]
        assert entry["facts_status"] == "ok"
        fact = scene.world_state.facts["F1"]
        assert fact.archive_id == entry["id"]
        assert fact.message_id == scene.history[1].id
        assert fact.message_digest == content_digest(scene.history[1].perception_text)
        assert fact.present == ["Mara", "Edwin"]
        # the passage sits after the span: the line is at the scene's start
        assert fact.ts == 0
        assert scene.world_state.knowledge[0].character == "Carol"

    async def test_failed_facts_keep_the_summary_and_mark_the_entry(
        self, summarizer_scene, fake_memory
    ):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["threshold"].value = 100000
        scene.history = self._history()

        async def stub(text, **kwargs):
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

        async def stub(text, **kwargs):
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

    def test_reset_keeps_edges_whose_target_starts_with_f(self, scene):
        scene.archived_history = [
            {"id": "e1", "text": "x", "ts": 0, "start": 0, "end": 1}
        ]
        scene.world_state.facts = {"F3": Fact(id="F3", text="a", archive_id="e1")}
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F3"),
            KnowledgeEdge(character="Edwin", target="Fiona.age"),
            KnowledgeEdge(character="Edwin", target="Forge District"),
            KnowledgeEdge(character="Edwin", target="Mara.age"),
        ]
        dropped = scene.reset()
        assert dropped == {"F3"}
        assert [e.target for e in scene.world_state.knowledge] == [
            "Fiona.age",
            "Forge District",
            "Mara.age",
        ]

    def test_export_with_reset_progress_prunes_facts(self, scene):
        import json as _json

        from talemate.export import ExportOptions, scene_export_json

        scene.archived_history = [
            {"id": "s0", "text": "static", "ts": 0},
            {"id": "e1", "text": "x", "ts": 0, "start": 0, "end": 1},
        ]
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="a", archive_id="e1"),
            "F2": Fact(id="F2", text="manual", source="manual", supersedes="F1"),
        }
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F1"),
            KnowledgeEdge(character="Edwin", target="F2"),
        ]
        exported = _json.loads(
            scene_export_json(scene, ExportOptions(name="x", reset_progress=True))
        )
        ws = exported["world_state"]
        assert list(ws["facts"]) == ["F2"] and ws["facts"]["F2"]["supersedes"] is None
        assert [e["target"] for e in ws["knowledge"]] == ["F2"]
        assert set(scene.world_state.facts) == {"F1", "F2"}

    async def test_update_fact_refuses_unknown_ids(self, scene, fake_memory):
        from talemate.knowledge.facts import update_fact

        scene.world_state.facts = {"F1": Fact(id="F1", text="a")}
        assert await update_fact(scene, "F1", text="edited", importance=3) is not None
        assert scene.world_state.facts["F1"].text == "edited"
        assert scene.world_state.facts["F1"].importance == 3
        assert await update_fact(scene, "F9", text="ghost", importance=2) is None
        assert "F9" not in scene.world_state.facts

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
    async def test_extract_off_leaves_facts_alone(self, summarizer_scene, fake_memory):
        from talemate.history import HistoryEntry, regenerate_history_entry

        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["extract_facts"].value = False
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
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="hand edited", archive_id="e1")
        }
        calls = []

        async def stub(text, return_facts=False, **kwargs):
            calls.append(return_facts)
            return ("NEW", None) if return_facts else "NEW"

        summarizer.summarize = stub
        entry = HistoryEntry(
            text="kept", ts=5, index=0, layer=0, id="e1", start=0, end=0
        )
        assert await summarizer.regenerate_facts(entry) == "ok"
        assert calls == []
        result = await regenerate_history_entry(scene, entry)
        assert result.text == "NEW"
        assert calls == [False]
        assert scene.world_state.facts["F1"].text == "hand edited"
        assert scene.archived_history[0]["facts_status"] == "ok"

    async def test_first_chapter_keeps_its_intro_facts_across_regenerates(
        self, summarizer_scene, fake_memory
    ):
        from talemate.history import HistoryEntry, regenerate_history_entry

        scene, summarizer = summarizer_scene
        scene.intro = "The keeper is old."
        scene.history = [CharacterMessage(message="Mara: one", present=["Mara"])]
        scene.archived_history = [
            {
                "id": "e1",
                "text": "old",
                "ts": 5,
                "start": 0,
                "end": 0,
                "present": ["Mara"],
                "intro_included": True,
                "facts_status": "ok",
            }
        ]
        spans = []

        async def stub(text, **kwargs):
            spans.append(text)
            return "NEW", parse_facts(
                '[{"text": "The keeper is old.", "message_id": "intro"}]'
            )

        summarizer.summarize = stub
        for _ in range(2):
            entry = HistoryEntry(
                text="old",
                ts=5,
                index=0,
                layer=0,
                id="e1",
                start=0,
                end=0,
                intro_included=True,
            )
            result = await regenerate_history_entry(scene, entry)
            assert result.intro_included is True
            assert scene.archived_history[0]["intro_included"] is True
            assert [f.text for f in result.facts] == ["The keeper is old."]
        assert all(text.startswith("[intro] The keeper is old.") for text in spans)

    async def test_layered_entry_is_refused(self, summarizer_scene, fake_memory):
        from talemate.history import HistoryEntry

        scene, summarizer = summarizer_scene
        entry = HistoryEntry(text="x", ts=0, index=0, layer=1, id="l1", start=0, end=0)
        assert await summarizer.regenerate_facts(entry) is None

    async def test_entry_regeneration_returns_fresh_facts(
        self, summarizer_scene, fake_memory
    ):
        from talemate.history import HistoryEntry, regenerate_history_entry

        scene, summarizer = summarizer_scene
        scene.history = [CharacterMessage(message="Mara: one", present=["Mara"])]
        scene.archived_history = [
            {
                "id": "e1",
                "text": "old",
                "ts": 5,
                "start": 0,
                "end": 0,
                "present": ["Mara"],
                "facts_status": "ok",
            }
        ]
        scene.world_state.facts = {"F1": Fact(id="F1", text="stale", archive_id="e1")}
        scene.world_state.fact_counter = 1

        async def stub(text, **kwargs):
            return "NEW", parse_facts(
                f'[{{"text": "fresh", "message_id": {scene.history[0].id}}}]'
            )

        summarizer.summarize = stub
        entry = HistoryEntry(
            text="old",
            ts=5,
            index=0,
            layer=0,
            id="e1",
            start=0,
            end=0,
            facts=[Fact(id="F1", text="stale", archive_id="e1")],
        )
        result = await regenerate_history_entry(scene, entry)
        assert [f.id for f in result.facts] == ["F2"] and result.facts[
            0
        ].text == "fresh"

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

        async def stub(text, include_previous_facts=True, **kwargs):
            assert include_previous_facts
            return "NEW SUMMARY", parse_facts(
                f'[{{"text": "fresh", "message_id": {scene.history[1].id}}}]'
            )

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

        async def stub(text, include_previous_facts=True, **kwargs):
            assert include_previous_facts
            return "NEW SUMMARY", None

        summarizer.summarize = stub
        entry = HistoryEntry(
            text="kept", ts=5, index=0, layer=0, id="e1", start=0, end=0
        )
        assert await summarizer.regenerate_facts(entry) == "failed"
        assert scene.archived_history[0]["facts_status"] == "failed"
        assert scene.world_state.facts == {}
