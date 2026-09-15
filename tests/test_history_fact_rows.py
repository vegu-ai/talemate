"""
Fact rows in the History tab: each row carries the age of its latest source
and of its first record, whichever payload delivers the entry.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from conftest import MockScene, bootstrap_scene

from talemate.context import ActiveScene
from talemate.history import HistoryEntry
from talemate.instance import get_agent
from talemate.knowledge.chronology import fact_display
from talemate.knowledge.schema import Fact, FactRestatement
from talemate.scene_message import CharacterMessage, TimePassageMessage
from talemate.server.world_state_manager import WorldStateManagerPlugin

DAY, HOUR = 86400, 3600


@pytest.fixture
async def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    with ActiveScene(scene):
        scene.history = [
            CharacterMessage(message="Mara: the lamp is out", present=["Mara"]),
            TimePassageMessage(ts=2 * DAY, message="Two days pass"),
            CharacterMessage(message="Mara: the lamp is still out", present=["Mara"]),
        ]
        scene.archived_history = [
            {"id": "e1", "text": "first", "start": 0, "end": 0, "ts": 0},
            {"id": "e2", "text": "second", "start": 2, "end": 2, "ts": 2 * DAY},
        ]
        scene.ts = 2 * DAY + 4 * HOUR
        restated = FactRestatement(
            message_id=scene.history[2].id, archive_id="e2", ts=2 * DAY
        )
        scene.world_state.facts = {
            "F1": Fact(
                id="F1",
                text="The lamp is out.",
                ts=0,
                last_seen_ts=2 * DAY,
                archive_id="e1",
                message_id=scene.history[0].id,
                restatements=1,
                restated_by=(restated,),
            )
        }
        yield scene


def _plugin(scene):
    return WorldStateManagerPlugin(
        websocket_handler=SimpleNamespace(scene=scene, queue_put=Mock())
    )


def _sent(plugin, action):
    return next(
        call.args[0]["data"]
        for call in plugin.websocket_handler.queue_put.call_args_list
        if call.args[0].get("action") == action
    )


def test_a_row_carries_the_latest_and_the_first_time(scene):
    row = fact_display(scene, scene.world_state.facts["F1"])
    assert row["time"] == "4 Hours ago"
    assert row["origin_time"] == "2 Days and 4 Hours ago"


def test_an_undated_fact_has_no_origin_time(scene):
    assert fact_display(scene, Fact(id="F9", text="x"))["origin_time"] is None


async def test_the_restating_entry_lists_the_fact_with_its_origin(scene):
    plugin = _plugin(scene)
    await plugin.handle_request_scene_history({})
    history = _sent(plugin, "scene_history")["history"]
    rows = {row["id"]: row["facts"] for row in history}
    assert [fact["id"] for fact in rows["e2"]] == ["F1"]
    fact = rows["e2"][0]
    assert fact["archive_id"] == "e1"
    assert fact["origin_time"] == "2 Days and 4 Hours ago"


async def test_a_regenerated_entry_sends_the_scene_history_row(scene):
    plugin = _plugin(scene)
    plugin.signal_operation_done = AsyncMock()
    waiting = (
        "This entry's character perspectives must be ready before extracting facts."
    )
    entry = HistoryEntry(
        id="e2",
        text="second",
        ts=2 * DAY,
        index=1,
        layer=0,
        start=2,
        end=2,
        facts=[scene.world_state.facts["F1"]],
    )
    with (
        patch(
            "talemate.server.world_state_manager.history.regenerate_history_entry",
            AsyncMock(return_value=entry),
        ),
        patch.object(
            get_agent("summarizer"),
            "fact_source_unavailable_reason",
            Mock(return_value=waiting),
        ),
    ):
        task = await plugin.handle_regenerate_history_entry(
            {"entry": entry.model_dump()}
        )
        await task
        await plugin.handle_request_scene_history({})
    regenerated = _sent(plugin, "history_entry_regenerated")
    listed = _sent(plugin, "scene_history")["history"][1]
    assert regenerated["facts_unavailable_reason"] == waiting
    assert regenerated["facts"] == listed["facts"]
    fact = regenerated["facts"][0]
    assert (fact["time"], fact["origin_time"]) == (
        "4 Hours ago",
        "2 Days and 4 Hours ago",
    )
