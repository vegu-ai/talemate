"""
Presence: who was there when a message was pushed, carried onto archive
entries, memory documents and layered history.
"""

from unittest.mock import patch

import pytest

import talemate.util as util
from talemate.context import ActiveScene
from talemate.events import ArchiveEvent
from talemate.history import (
    ArchiveEntry,
    HistoryEntry,
    emit_archive_add,
    history_with_relative_time,
    update_history_entry,
)
from talemate.knowledge.presence import (
    layer_entry_presence,
    presence_differs,
    presence_metadata,
    span_presence,
)
from talemate.load import _prepare_history
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    TimePassageMessage,
)

from conftest import MockScene, bootstrap_scene


def _char_count_tokens(source):
    if isinstance(source, list):
        return sum(_char_count_tokens(s) for s in source)
    return len(str(source))


def line(text: str, present: list[str] | None = None) -> CharacterMessage:
    return CharacterMessage(message=f"Alice: {text}", source="ai", present=present)


# ---------------------------------------------------------------------------
# message model
# ---------------------------------------------------------------------------


class TestMessagePresence:
    def test_defaults_to_unknown(self):
        assert CharacterMessage(message="Alice: hi").present is None
        assert "present" not in CharacterMessage(message="Alice: hi").to_dict()

    def test_to_dict_carries_presence(self):
        msg = NarratorMessage(message="Rain falls.", present=["Alice", "Bob"])
        assert msg.to_dict()["present"] == ["Alice", "Bob"]

    def test_round_trips_through_load(self):
        msg = line("hi", present=["Alice"])
        loaded = _prepare_history(msg.to_dict())
        assert loaded.present == ["Alice"]

    def test_legacy_entry_loads_unknown(self):
        loaded = _prepare_history(
            {"message": "Alice: hi", "id": 3, "typ": "character", "source": "ai"}
        )
        assert loaded.present is None


# ---------------------------------------------------------------------------
# push_history stamp
# ---------------------------------------------------------------------------


class TestPushHistoryStamp:
    async def test_stamps_active_characters(self, scene):
        scene.active_characters = ["Alice", "Bob"]
        msg = line("hi")
        with ActiveScene(scene):
            await scene.push_history([msg])
        assert msg.present == ["Alice", "Bob"]
        # a copy, not the live list
        scene.active_characters.append("Carol")
        assert msg.present == ["Alice", "Bob"]

    async def test_keeps_explicit_presence(self, scene):
        scene.active_characters = ["Alice", "Bob"]
        msg = line("hi", present=["Bob"])
        with ActiveScene(scene):
            await scene.push_history([msg])
        assert msg.present == ["Bob"]

    async def test_no_active_characters_leaves_unknown(self, scene):
        scene.active_characters = []
        msg = line("hi")
        with ActiveScene(scene):
            await scene.push_history([msg])
        assert msg.present is None

    async def test_time_passage_is_stamped_too(self, scene):
        scene.active_characters = ["Alice"]
        msg = TimePassageMessage(ts=60, message="A minute passes")
        with ActiveScene(scene):
            await scene.push_history([msg])
        assert msg.present == ["Alice"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class TestSpanPresence:
    def test_union_sorted(self):
        assert span_presence([line("a", ["Bob"]), line("b", ["Alice", "Bob"])]) == [
            "Alice",
            "Bob",
        ]

    def test_unknown_message_makes_span_unknown(self):
        assert span_presence([line("a", ["Bob"]), line("b")]) is None

    def test_empty_span_is_unknown(self):
        assert span_presence([]) is None


class TestPresenceDiffers:
    def test_same_set_any_order(self):
        assert not presence_differs(["Alice", "Bob"], ["Bob", "Alice"])

    def test_different(self):
        assert presence_differs(["Alice", "Bob"], ["Alice"])

    def test_unknown_never_differs(self):
        assert not presence_differs(None, ["Alice"])
        assert not presence_differs(["Alice"], None)
        assert not presence_differs(None, None)


class TestPresenceMetadata:
    def test_known(self):
        assert presence_metadata(["Alice", "Bob"]) == {
            "presence_known": True,
            "present": '["Alice", "Bob"]',
        }

    def test_unknown(self):
        assert presence_metadata(None) == {"presence_known": False}


class TestLayerEntryPresence:
    def _scene(self):
        scene = MockScene()
        scene.archived_history = [
            {"text": "a", "start": 0, "end": 1, "ts": 0, "present": ["Alice"]},
            {"text": "b", "start": 2, "end": 3, "ts": 0, "present": ["Bob"]},
            {"text": "c", "start": 4, "end": 5, "ts": 0},
        ]
        scene.layered_history = [
            [
                {"text": "ab", "start": 0, "end": 1, "ts": 0},
                {"text": "c", "start": 2, "end": 2, "ts": 0},
            ],
            [{"text": "abc", "start": 0, "end": 1, "ts": 0}],
        ]
        return scene

    def test_union_over_base_sources(self):
        scene = self._scene()
        assert layer_entry_presence(scene, 0, scene.layered_history[0][0]) == [
            "Alice",
            "Bob",
        ]

    def test_unknown_source_propagates(self):
        scene = self._scene()
        assert layer_entry_presence(scene, 0, scene.layered_history[0][1]) is None
        assert layer_entry_presence(scene, 1, scene.layered_history[1][0]) is None

    def test_static_entry_is_unknown(self):
        scene = self._scene()
        assert layer_entry_presence(scene, 0, {"text": "static", "ts": 0}) is None

    def test_range_outside_the_layer_below_is_unknown(self):
        scene = self._scene()
        assert (
            layer_entry_presence(scene, 0, {"text": "x", "start": 7, "end": 9, "ts": 0})
            is None
        )
        assert (
            layer_entry_presence(scene, 0, {"text": "x", "start": 2, "end": 1, "ts": 0})
            is None
        )

    def test_truncated_range_over_known_sources_is_unknown(self):
        # every source is known, so only the guard can turn this into None:
        # a silent slice would return a union over fewer sources than claimed
        scene = MockScene()
        scene.archived_history = [
            {"text": "a", "start": 0, "end": 1, "ts": 0, "present": ["Alice"]},
            {"text": "b", "start": 2, "end": 3, "ts": 0, "present": ["Bob"]},
            {"text": "c", "start": 4, "end": 5, "ts": 0, "present": ["Carol"]},
        ]
        assert (
            layer_entry_presence(scene, 0, {"text": "x", "start": 0, "end": 5, "ts": 0})
            is None
        )
        assert layer_entry_presence(
            scene, 0, {"text": "x", "start": 0, "end": 2, "ts": 0}
        ) == ["Alice", "Bob", "Carol"]

    def test_negative_bounds_are_unknown(self):
        scene = MockScene()
        scene.archived_history = [
            {"text": "a", "start": 0, "end": 1, "ts": 0, "present": ["Alice"]},
            {"text": "b", "start": 2, "end": 3, "ts": 0, "present": ["Bob"]},
        ]
        for start, end in ((-3, 0), (-1, 0)):
            assert (
                layer_entry_presence(
                    scene, 0, {"text": "x", "start": start, "end": end, "ts": 0}
                )
                is None
            ), (start, end)


# ---------------------------------------------------------------------------
# archive entries
# ---------------------------------------------------------------------------


class TestArchiveEntryPresence:
    def test_model_default(self):
        entry = ArchiveEntry(text="x")
        assert entry.present is None
        assert "present" not in entry.model_dump(exclude_none=True)

    def test_history_with_relative_time_carries_presence(self):
        rows = history_with_relative_time(
            [{"text": "x", "ts": 0, "present": ["Alice"]}, {"text": "y", "ts": 0}],
            0,
        )
        assert rows[0]["present"] == ["Alice"]
        assert rows[1]["present"] is None

    async def test_archive_event_carries_presence(self, scene):
        seen = []

        async def recorder(event: ArchiveEvent):
            seen.append(event)

        import talemate.emit.async_signals as async_signals

        async_signals.get("archive_add").connect(recorder)
        try:
            await emit_archive_add(
                scene, ArchiveEntry(text="x", present=["Alice"], ts=5)
            )
        finally:
            async_signals.get("archive_add").disconnect(recorder)

        assert seen[-1].present == ["Alice"]

    async def test_memory_add_receives_presence_metadata(self, scene):
        from talemate.instance import get_agent

        memory = get_agent("memory")
        calls = []

        async def fake_add(text, character=None, uid=None, ts=None, **kwargs):
            calls.append(kwargs)

        memory.add = fake_add
        await memory.on_archive_add(
            ArchiveEvent(
                scene=scene,
                event_type="archive_add",
                text="x",
                memory_id="abc",
                ts=1,
                present=["Alice"],
            )
        )
        assert calls == [
            {"typ": "history", "presence_known": True, "present": '["Alice"]'}
        ]

    async def test_manual_edit_keeps_presence(self, scene):
        scene.archived_history = [
            {
                "text": "old",
                "ts": 0,
                "start": 0,
                "end": 1,
                "id": "e1",
                "present": ["Alice"],
            }
        ]
        payload = HistoryEntry(
            text="new", ts=0, index=0, layer=0, id="e1", start=0, end=1
        )
        with ActiveScene(scene):
            await update_history_entry(scene, payload)
        assert scene.archived_history[0]["text"] == "new"
        assert scene.archived_history[0]["present"] == ["Alice"]

    async def test_layered_edit_does_not_store_presence(self, scene):
        scene.archived_history = [
            {
                "text": "a",
                "ts": 0,
                "start": 0,
                "end": 1,
                "id": "e1",
                "present": ["Alice"],
            }
        ]
        scene.layered_history = [
            [{"text": "old", "ts": 0, "start": 0, "end": 0, "id": "l1"}]
        ]
        payload = HistoryEntry(
            text="new",
            ts=0,
            index=0,
            layer=1,
            id="l1",
            start=0,
            end=0,
            present=["Alice"],
        )
        with ActiveScene(scene):
            await update_history_entry(scene, payload)
        assert scene.layered_history[0][0]["text"] == "new"
        assert "present" not in scene.layered_history[0][0]

    async def test_commit_to_memory_carries_presence(self, scene):
        from talemate.instance import get_agent

        memory = get_agent("memory")
        added = []

        async def fake_add_many(objects):
            added.extend(objects)

        memory.add_many = fake_add_many
        memory.drop_db = lambda: None

        async def fake_set_db():
            pass

        memory.set_db = fake_set_db
        scene.archived_history = [
            {
                "text": "a",
                "ts": 0,
                "start": 0,
                "end": 1,
                "id": "e1",
                "present": ["Alice"],
            },
            {"text": "b", "ts": 0, "start": 2, "end": 3, "id": "e2"},
        ]
        with ActiveScene(scene):
            await scene.commit_to_memory()
        metas = {o["id"]: o["meta"] for o in added if o["id"] in ("e1", "e2")}
        assert metas["e1"]["present"] == '["Alice"]'
        assert metas["e1"]["presence_known"] is True
        assert metas["e2"]["presence_known"] is False
        assert "present" not in metas["e2"]


# ---------------------------------------------------------------------------
# presence cut in build_archive
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _char_tokens():
    with patch.object(util, "count_tokens", side_effect=_char_count_tokens):
        yield


@pytest.fixture
def summarizer_scene():
    scene = MockScene()
    agents = bootstrap_scene(scene)
    summarizer = agents["summarizer"]
    summarizer.actions["archive"].config["threshold"].value = 100000

    async def stub_summarize(
        text, extra_context=None, generation_options=None, return_facts=False
    ):
        return ("SUMMARY", None) if return_facts else "SUMMARY"

    summarizer.summarize = stub_summarize
    summarizer.analyze_calls = 0

    async def stub_analyze(dialogue):
        summarizer.analyze_calls += 1
        return ""

    summarizer.analyze_dialoge = stub_analyze

    with ActiveScene(scene):
        yield scene, summarizer


class TestPresenceCut:
    async def test_cuts_when_presence_changes(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        both = ["Alice", "Bob"]
        scene.history = [
            line("one", both),
            line("two", both),
            line("three", both),
            line("bob left", ["Alice"]),
            line("still alone", ["Alice"]),
            line("trailing", ["Alice"]),
        ]

        assert await summarizer.build_archive(scene) is True

        entry = scene.archived_history[0]
        assert (entry["start"], entry["end"]) == (0, 2)
        assert entry["present"] == ["Alice", "Bob"]
        assert summarizer.analyze_calls == 0

        # the next run starts at the new presence set and needs a cut of its own
        assert await summarizer.build_archive(scene) is None

    async def test_unknown_message_does_not_suppress_a_later_cut(
        self, summarizer_scene
    ):
        scene, summarizer = summarizer_scene
        both = ["Alice", "Bob"]
        scene.history = [
            line("one", both),
            line("two", both),
            line("unknown"),
            line("carol", ["Carol"]),
            line("carol again", ["Carol"]),
            line("trailing", ["Carol"]),
        ]

        assert await summarizer.build_archive(scene) is True
        entry = scene.archived_history[0]
        assert (entry["start"], entry["end"]) == (0, 2)
        # the span holds an unknown message, so its presence stays unknown
        assert "present" not in entry

    async def test_unknown_presence_never_cuts(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        scene.history = [
            line("one"),
            line("two", ["Alice"]),
            line("three"),
            TimePassageMessage(ts=60, message="A minute passes"),
            line("trailing"),
        ]

        assert await summarizer.build_archive(scene) is True
        entry = scene.archived_history[0]
        assert (entry["start"], entry["end"]) == (0, 2)
        assert "present" not in entry

    async def test_time_passage_entry_carries_presence(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        scene.history = [
            line("one", ["Alice"]),
            line("two", ["Alice"]),
            TimePassageMessage(ts=60, message="A minute passes", present=["Alice"]),
            line("trailing", ["Alice"]),
        ]

        assert await summarizer.build_archive(scene) is True
        assert scene.archived_history[0]["present"] == ["Alice"]
