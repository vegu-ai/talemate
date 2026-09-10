"""#530: the fact-centric listing and the bulk actions."""

from unittest.mock import AsyncMock, patch

import pydantic
import pytest

from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.catalog import FactQuery, latest_chapter, list_facts
from talemate.knowledge.schema import Fact, KnowledgeEdge, Topic
from talemate.scene_message import NarratorMessage
from test_fact_single_source import frames, handler_for
from test_supported_facts import passage, store, supported_scene  # noqa: F401


def fact(id, text, ts, present, subjects=(), **kw):
    return Fact(
        id=id,
        text=text,
        ts=ts,
        present=list(present) if present is not None else None,
        subjects=list(subjects),
        **kw,
    )


@pytest.fixture
def catalog_scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.ts = 1000
    for name in ("Edwin", "Mara"):
        scene.character_data[name] = Character(name=name)
    # message ids are a global counter; entry start/end are history indexes
    scene.history = [
        NarratorMessage(message=f"Line {index}.", id=100 + index) for index in range(14)
    ]
    ws = scene.world_state
    ws.facts = {
        "F1": fact(
            "F1",
            "Edwin keeps the light.",
            1,
            ["Edwin", "Mara"],
            ["Edwin"],
            archive_id="A1",
        ),
        "F2": fact(
            "F2",
            "Mara found a sextant.",
            2,
            ["Mara"],
            ["Mara", "sextant"],
            source="manual",
            importance=3,
        ),
        "F3": fact(
            "F3",
            "The boat leaks.",
            3,
            ["Mara"],
            ["boat"],
            known_by={"Edwin": "told"},
            message_id=107,
            source="dialogue",
        ),
        "F4": fact(
            "F4",
            "The boat was patched.",
            4,
            ["Mara"],
            ["boat"],
            supersedes="F3",
            archive_id="A2",
            importance=1,
        ),
        "F5": fact(
            "F5",
            "Edwin lied about the light.",
            None,
            ["Edwin"],
            ["Edwin"],
            false=True,
            archive_id="A2",
        ),
        "F10": fact(
            "F10", "A late arrival.", 5, ["Mara"], [], message_id=112, source="dialogue"
        ),
    }
    ws.fact_counter = 10
    ws.topics = {
        "T1": Topic(id="T1", name="boat", fact_ids=["F3", "F4"]),
        "T2": Topic(id="T2", name="light", fact_ids=["F1", "F5"]),
    }
    ws.knowledge = [KnowledgeEdge(character="Edwin", target="F3", source="told")]
    scene.archived_history = [
        {"id": "A1", "text": "Chapter one.", "start": 0, "end": 5, "ts": 100},
        {"id": "A2", "text": "Chapter two.", "start": 6, "end": 10, "ts": 400},
    ]
    return scene


def ids(page):
    return [row["id"] for row in page.facts]


class TestListFacts:
    def test_default_page_sorts_by_time_newest_first_with_unknown_last(
        self, catalog_scene
    ):
        page = list_facts(catalog_scene, FactQuery())
        assert ids(page) == ["F10", "F4", "F3", "F2", "F1", "F5"]
        assert page.total == 6 and page.page == 1 and page.page_size == 50
        assert page.perception_mode is False
        assert page.options.characters == ["Edwin", "Mara"]
        assert [topic.id for topic in page.options.topics] == ["T1", "T2"]
        assert [(item.value, item.label) for item in page.options.sources] == [
            ("dialogue", "dialogue"),
            ("manual", "manual entry"),
            ("summary", "history entry"),
        ]

    def test_rows_carry_topic_source_audience_and_superseded_by(self, catalog_scene):
        rows = {row["id"]: row for row in list_facts(catalog_scene, FactQuery()).facts}
        assert rows["F3"]["topic"] == {"id": "T1", "name": "boat"}
        assert rows["F3"]["source_label"] == "dialogue"
        assert rows["F3"]["source_id"] == "107"
        assert rows["F3"]["superseded_by"] == ["F4"]
        assert rows["F3"]["audience"] == {"Mara": "witnessed", "Edwin": "told"}
        assert (
            rows["F1"]["source_id"] == "A1" and rows["F1"]["topic"]["name"] == "light"
        )
        assert rows["F2"]["topic"] is None and rows["F2"]["audience"] == {
            "Mara": "witnessed"
        }
        assert rows["F4"]["superseded_by"] == []
        assert rows["F5"]["false"] is True and rows["F5"]["time"] == "Time unknown"

    def test_sorts(self, catalog_scene):
        assert ids(
            list_facts(catalog_scene, FactQuery(sort="time", descending=False))
        ) == [
            "F1",
            "F2",
            "F3",
            "F4",
            "F10",
            "F5",
        ]
        assert ids(list_facts(catalog_scene, FactQuery(sort="importance"))) == [
            "F2",
            "F10",
            "F3",
            "F1",
            "F5",
            "F4",
        ]
        assert ids(
            list_facts(catalog_scene, FactQuery(sort="id", descending=False))
        ) == [
            "F1",
            "F2",
            "F3",
            "F4",
            "F5",
            "F10",
        ]

    @pytest.mark.parametrize(
        "query, expected",
        [
            (dict(text="boat"), ["F4", "F3"]),
            (dict(text="f2"), ["F2"]),
            (dict(text="SEXTANT"), ["F2"]),
            (dict(character="Edwin"), ["F3", "F1", "F5"]),
            (dict(character="Edwin", character_filter="unknown"), ["F10", "F4", "F2"]),
            (dict(character="Edwin", character_filter="subject"), ["F1", "F5"]),
            (dict(character="edwin", character_filter="subject"), ["F1", "F5"]),
            (dict(topic_id="T1"), ["F4", "F3"]),
            (dict(importance=[3]), ["F2"]),
            (dict(importance=[1, 3]), ["F4", "F2"]),
            (dict(source=["dialogue"]), ["F10", "F3"]),
            (dict(superseded=True), ["F3"]),
            (dict(superseded=True, false=False), ["F3"]),
            (dict(superseded=False), ["F10", "F4", "F2", "F1", "F5"]),
            (dict(false=True), ["F5"]),
            (dict(latest_chapter=True), ["F4", "F3", "F5"]),
            (dict(latest_chapter=True, false=False, source=["summary"]), ["F4"]),
            (dict(character="Mara", topic_id="T1", superseded=False), ["F4"]),
            (dict(text="nothing here"), []),
        ],
    )
    def test_filters_combine(self, catalog_scene, query, expected):
        assert ids(list_facts(catalog_scene, FactQuery(**query))) == expected

    def test_paging(self, catalog_scene):
        first = list_facts(catalog_scene, FactQuery(page_size=4))
        second = list_facts(catalog_scene, FactQuery(page_size=4, page=2))
        assert ids(first) == ["F10", "F4", "F3", "F2"] and first.total == 6
        assert ids(second) == ["F1", "F5"] and second.total == 6
        assert ids(list_facts(catalog_scene, FactQuery(page_size=4, page=3))) == []

    def test_unknown_character_knows_nothing(self, catalog_scene):
        for relation in ("knows", "unknown"):
            query = FactQuery(character="Nobody", character_filter=relation)
            assert ids(list_facts(catalog_scene, query)) == []
        catalog_scene.knowledge_eligibility = "perception"
        assert ids(list_facts(catalog_scene, FactQuery(character="Nobody"))) == []

    def test_false_superseder_does_not_hide_its_predecessor(self, catalog_scene):
        catalog_scene.world_state.facts["F4"].false = True
        rows = {row["id"]: row for row in list_facts(catalog_scene, FactQuery()).facts}
        # the arrow stays, the effective rule the prompts use does not count it
        assert rows["F3"]["superseded_by"] == ["F4"]
        assert ids(list_facts(catalog_scene, FactQuery(superseded=True))) == []
        assert "F3" in ids(list_facts(catalog_scene, FactQuery(superseded=False)))

    def test_subject_filter_follows_the_alias_groups(self, catalog_scene):
        catalog_scene.world_state.character_name_mappings = {
            "Edwin": ["Ed", "the keeper"]
        }
        catalog_scene.world_state.facts["F2"].subjects = ["the Keeper"]
        query = FactQuery(character="Edwin", character_filter="subject")
        assert ids(list_facts(catalog_scene, query)) == ["F2", "F1", "F5"]

    def test_latest_chapter_names_the_newest_summary(self, catalog_scene):
        chapter = latest_chapter(catalog_scene)
        assert (chapter.id, chapter.start, chapter.end) == ("A2", 6, 10)
        assert chapter.time == "10 Minutes ago"
        # the last message of the chapter sits at index 10 and carries id 110
        fact = catalog_scene.world_state.facts["F3"]
        for message_id, inside in ((110, True), (111, False), (999, False)):
            fact.message_id = message_id
            latest = ids(list_facts(catalog_scene, FactQuery(latest_chapter=True)))
            assert ("F3" in latest) is inside
        fact.message_id = 107
        catalog_scene.archived_history.append(
            {"id": "N1", "text": "A manual note.", "ts": 900}
        )
        assert latest_chapter(catalog_scene).id == "A2"
        catalog_scene.archived_history = []
        assert latest_chapter(catalog_scene) is None
        assert ids(list_facts(catalog_scene, FactQuery(latest_chapter=True))) == [
            "F10",
            "F3",
        ]

    def test_query_validation(self):
        with pytest.raises(pydantic.ValidationError):
            FactQuery(page=0)
        with pytest.raises(pydantic.ValidationError):
            FactQuery(page_size=500)
        with pytest.raises(pydantic.ValidationError):
            FactQuery(importance=[4])
        with pytest.raises(pydantic.ValidationError):
            FactQuery(sort="colour")


@pytest.mark.asyncio
async def test_perception_listing_uses_the_character_view(supported_scene):  # noqa: F811
    scene, _, _ = supported_scene
    _, source = passage(scene, "Alice has a key.", ("Alice",))
    stored = (
        await store(scene, source, ("Alice",), "Alice has a key.", subjects=["key"])
    )[0]
    scene.world_state.facts[stored.id].text = "Alice has a brass key."
    page = list_facts(scene, FactQuery())
    assert page.perception_mode is True
    (row,) = page.facts
    assert row["text"] == "Alice has a brass key."
    assert row["audience"] == {"Alice": "inferred"}
    assert row["source_label"] == "perception" and row["source_id"] is None
    assert ids(
        list_facts(scene, FactQuery(character="Bob", character_filter="unknown"))
    ) == [stored.id]
    assert ids(list_facts(scene, FactQuery(character="Bob"))) == []


class TestHandlers:
    @pytest.fixture
    def handler(self, catalog_scene):
        return handler_for(catalog_scene)

    def patches(self):
        return (
            patch(
                "talemate.server.world_state_manager.knowledge.refresh_topics",
                AsyncMock(),
            ),
            patch.object(get_agent("memory"), "add_many", AsyncMock()),
            patch.object(get_agent("memory"), "delete", AsyncMock()),
        )

    async def test_list_facts_echoes_the_request_id(self, catalog_scene, handler):
        with ActiveScene(catalog_scene):
            await handler.handle_list_facts(
                {"text": "boat", "request_id": "r1", "page_size": 1}
            )
        (frame,) = frames(handler, "facts")
        assert frame["request_id"] == "r1"
        assert [row["id"] for row in frame["data"]["facts"]] == ["F4"]
        assert frame["data"]["total"] == 2
        assert frame["data"]["latest_chapter"]["id"] == "A2"

    async def test_update_fact_sets_false_and_supersedes(self, catalog_scene, handler):
        refresh, add_many, delete = self.patches()
        with ActiveScene(catalog_scene), refresh, add_many, delete:
            await handler.handle_update_fact(
                {
                    "fact_id": "F2",
                    "text": "Mara found a sextant.",
                    "importance": 3,
                    "false": True,
                    "supersedes": "F1",
                }
            )
            stored = catalog_scene.world_state.facts["F2"]
            assert (stored.false, stored.supersedes) == (True, "F1")
            assert frames(handler, "fact_updated")[-1]["data"]["supersedes"] == "F1"
            # a patch that names neither field leaves both alone
            await handler.handle_update_fact(
                {
                    "fact_id": "F2",
                    "text": "Mara found a brass sextant.",
                    "importance": 2,
                }
            )
            assert (stored.false, stored.supersedes) == (True, "F1")
            await handler.handle_update_fact(
                {
                    "fact_id": "F2",
                    "text": "Mara found a brass sextant.",
                    "importance": 2,
                    "false": False,
                    "supersedes": None,
                }
            )
            assert (stored.false, stored.supersedes) == (False, None)

    async def test_update_fact_refuses_bad_links(self, catalog_scene, handler):
        refresh, add_many, delete = self.patches()
        with ActiveScene(catalog_scene), refresh, add_many, delete:
            for supersedes in ("F2", "F404"):
                await handler.handle_update_fact(
                    {
                        "fact_id": "F2",
                        "text": "Mara found a sextant.",
                        "importance": 3,
                        "supersedes": supersedes,
                    }
                )
            # F4 supersedes F3 already; the reverse would close a loop
            await handler.handle_update_fact(
                {
                    "fact_id": "F3",
                    "text": "The boat leaks.",
                    "importance": 2,
                    "supersedes": "F4",
                }
            )
        failed = [
            f
            for f in handler.sent
            if f.get("action") == "operation_done"
            and f.get("failed_action") == "update_fact"
        ]
        assert len(failed) == 3
        assert catalog_scene.world_state.facts["F2"].supersedes is None
        assert catalog_scene.world_state.facts["F3"].supersedes is None
        assert catalog_scene.world_state.facts["F4"].supersedes == "F3"
        assert not frames(handler, "fact_updated")

    async def test_deleting_nothing_still_answers(self, catalog_scene, handler):
        refresh, add_many, delete = self.patches()
        done = []
        handler.signal_operation_done = AsyncMock(
            side_effect=lambda *a, **k: done.append(1)
        )
        with ActiveScene(catalog_scene), refresh, add_many, delete as memory_delete:
            await handler.handle_delete_facts({"fact_ids": ["F404"]})
            await handler.handle_delete_fact({"fact_id": "F404"})
        assert len(done) == 2
        memory_delete.assert_not_awaited()

    async def test_delete_facts_runs_once(self, catalog_scene, handler):
        refresh, add_many, delete = self.patches()
        with (
            ActiveScene(catalog_scene),
            refresh as topics,
            add_many,
            delete as memory_delete,
        ):
            await handler.handle_delete_facts({"fact_ids": ["F3", "F404", "F1"]})
        assert set(catalog_scene.world_state.facts) == {"F2", "F4", "F5", "F10"}
        assert catalog_scene.world_state.facts["F4"].supersedes is None
        assert catalog_scene.world_state.knowledge == []
        memory_delete.assert_awaited_once_with({"ids": ["F3", "F1"]})
        topics.assert_awaited_once()
        assert [f["data"]["fact_id"] for f in frames(handler, "fact_deleted")] == [
            "F3",
            "F1",
        ]

    async def test_set_facts_false_runs_once(self, catalog_scene, handler):
        refresh, add_many, delete = self.patches()
        with (
            ActiveScene(catalog_scene),
            refresh as topics,
            add_many as memory_add,
            delete,
        ):
            await handler.handle_set_facts_false(
                {"fact_ids": ["F1", "F2", "F404"], "false": True}
            )
        assert [catalog_scene.world_state.facts[i].false for i in ("F1", "F2")] == [
            True,
            True,
        ]
        memory_add.assert_awaited_once()
        assert [doc["id"] for doc in memory_add.await_args.args[0]] == ["F1", "F2"]
        topics.assert_not_awaited()
        assert [f["data"]["id"] for f in frames(handler, "fact_updated")] == [
            "F1",
            "F2",
        ]
        with pytest.raises(pydantic.ValidationError):
            await handler.handle_set_facts_false({"fact_ids": [], "false": True})

    async def test_grant_facts_adds_one_batch_of_edges(self, catalog_scene, handler):
        with (
            ActiveScene(catalog_scene),
            patch("talemate.world_state.manager.emit_knowledge_changes") as emitted,
        ):
            await handler.handle_grant_facts(
                {"name": "Edwin", "fact_ids": ["F2", "F3", "F404", "F2"]}
            )
        edges = [
            (e.character, e.target, e.kind, e.source)
            for e in catalog_scene.world_state.knowledge
        ]
        # F3 was already known through the told edge; F2 is granted once
        assert edges == [
            ("Edwin", "F3", "grant", "told"),
            ("Edwin", "F2", "grant", "manual"),
        ]
        emitted.assert_called_once()
        assert [c.target for c in emitted.call_args.args[1]] == ["F2"]
        assert frames(handler, "character_knowledge")[-1]["data"]["name"] == "Edwin"

    async def test_single_allow_lifts_an_earlier_block_too(self, catalog_scene):
        from talemate.world_state.manager import WorldStateManager

        catalog_scene.world_state.knowledge.append(
            KnowledgeEdge(
                character="Edwin", target="F2", kind="revoke", source="manual"
            )
        )
        with ActiveScene(catalog_scene):
            await WorldStateManager(catalog_scene).set_knowledge_edge(
                KnowledgeEdge(character="Edwin", target="F2", kind="grant")
            )
        edges = [
            (e.target, e.kind)
            for e in catalog_scene.world_state.knowledge
            if e.character == "Edwin"
        ]
        assert edges == [("F3", "grant"), ("F2", "grant")]

    async def test_grant_lifts_an_earlier_block(self, catalog_scene, handler):
        catalog_scene.world_state.knowledge.append(
            KnowledgeEdge(
                character="Edwin", target="F2", kind="revoke", source="manual"
            )
        )
        with (
            ActiveScene(catalog_scene),
            patch("talemate.world_state.manager.emit_knowledge_changes") as emitted,
        ):
            await handler.handle_grant_facts({"name": "Edwin", "fact_ids": ["F2"]})
        edges = [
            (e.target, e.kind)
            for e in catalog_scene.world_state.knowledge
            if e.character == "Edwin"
        ]
        assert edges == [("F3", "grant"), ("F2", "grant")]
        assert [c.target for c in emitted.call_args.args[1]] == ["F2"]
        query = FactQuery(character="Edwin")
        assert "F2" in ids(list_facts(catalog_scene, query))

    async def test_grant_facts_is_refused_in_perception_mode(
        self, catalog_scene, handler
    ):
        catalog_scene.knowledge_eligibility = "perception"
        with ActiveScene(catalog_scene):
            await handler.handle_grant_facts({"name": "Edwin", "fact_ids": ["F2"]})
        assert catalog_scene.world_state.knowledge == [
            KnowledgeEdge(**catalog_scene.world_state.knowledge[0].model_dump())
        ]
        assert len(catalog_scene.world_state.knowledge) == 1
        failed = [f for f in handler.sent if f.get("failed_action") == "grant_facts"]
        assert len(failed) == 1
