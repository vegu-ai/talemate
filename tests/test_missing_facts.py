"""
History > Generate missing facts: which entries it selects, the order it runs
them in, and how a run stops between entries.
"""

from unittest.mock import AsyncMock, Mock

import pytest

import test_supported_facts
from talemate.agents.summarize.missing_facts import MissingFactsRefused
from talemate.history import ArchiveEntry
from talemate.knowledge.facts import facts_for_entry
from talemate.knowledge.perspectives import set_source_perspectives
from talemate.knowledge.schema import Fact, FactRestatement, ParsedFact

supported_scene = test_supported_facts.supported_scene


def entry(identity, text=None, **values):
    return ArchiveEntry(
        id=identity, text=f"{identity} happened." if text is None else text, **values
    ).model_dump(exclude_none=True)


@pytest.fixture
def history_scene(supported_scene, monkeypatch):
    scene, summarizer, memory = supported_scene
    scene.knowledge_eligibility = "legacy"
    scene.ts = 500
    scene.archived_history = [
        entry("first", ts=10),
        entry("with-facts", ts=20),
        entry("tried", ts=30, facts_status="ok"),
        entry("failed", ts=40, facts_status="failed"),
        entry("blank", text="", ts=50),
        entry("restated", ts=60),
        entry("last", ts=70),
    ]
    scene.world_state.facts = {
        "F1": Fact(id="F1", text="Kept fact.", archive_id="with-facts", ts=20),
        "F2": Fact(
            id="F2",
            text="Restated fact.",
            archive_id="elsewhere",
            restated_by=[FactRestatement(archive_id="restated", ts=60)],
        ),
    }
    scene.world_state.fact_counter = 2
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    return scene, summarizer


@pytest.fixture
def extraction(history_scene, monkeypatch):
    _, summarizer = history_scene
    calls = []

    async def extract(text, **kwargs):
        calls.append(text)
        return [ParsedFact(text=f"Fact from {text}")]

    monkeypatch.setattr(summarizer, "extract_facts", AsyncMock(side_effect=extract))
    return calls


def test_selection_skips_entries_with_facts_a_status_or_no_source(history_scene):
    scene, summarizer = history_scene
    assert [row.id for row in summarizer.entries_missing_facts(scene)] == [
        "first",
        "last",
    ]
    assert [row.index for row in summarizer.entries_missing_facts(scene)] == [0, 6]


def test_selection_skips_perception_entries_without_ready_views(history_scene):
    scene, summarizer = history_scene
    scene.knowledge_eligibility = "perception"
    set_source_perspectives(
        scene,
        "summary",
        "last",
        [{"audience": ["Alice"], "status": "ready", "text": "Alice saw it."}],
    )
    assert [row.id for row in summarizer.entries_missing_facts(scene)] == ["last"]


async def test_run_goes_in_history_order_and_leaves_other_entries_alone(
    history_scene, extraction
):
    scene, summarizer = history_scene
    before = {
        stored["id"]: dict(stored)
        for stored in scene.archived_history
        if stored["id"] not in ("first", "last")
    }
    states = []

    async def progress(state):
        states.append(state)

    result = await summarizer.generate_missing_facts(scene, progress=progress)

    assert extraction == ["first happened.", "last happened."]
    assert result == {
        "total": 2,
        "done": 2,
        "ok": 2,
        "failed": 0,
        "skipped": 0,
        "stopped": False,
    }
    assert [(state["done"], state["entry_id"]) for state in states] == [
        (0, None),
        (1, "first"),
        (2, "last"),
    ]
    for stored in scene.archived_history:
        if stored["id"] in before:
            assert stored == before[stored["id"]]
    assert [fact.text for fact in facts_for_entry(scene, "with-facts")] == [
        "Kept fact."
    ]
    assert [fact.text for fact in facts_for_entry(scene, "last")] == [
        "Fact from last happened."
    ]
    assert scene.archived_history[0]["facts_status"] == "ok"
    assert summarizer.entries_missing_facts(scene) == []
    assert not summarizer.missing_facts_running(scene)


async def test_failed_entry_is_counted_and_the_run_continues(
    history_scene, monkeypatch
):
    scene, summarizer = history_scene
    monkeypatch.setattr(
        summarizer,
        "extract_facts",
        AsyncMock(side_effect=[None, [ParsedFact(text="Last fact.")]]),
    )
    result = await summarizer.generate_missing_facts(scene)
    assert (result["ok"], result["failed"], result["stopped"]) == (1, 1, False)
    assert scene.archived_history[0]["facts_status"] == "failed"
    assert scene.archived_history[-1]["facts_status"] == "ok"


async def test_stop_finishes_the_current_entry_and_runs_no_other(
    history_scene, extraction
):
    scene, summarizer = history_scene

    async def progress(state):
        if state["entry_id"] == "first":
            assert summarizer.stop_missing_facts(scene) is True

    result = await summarizer.generate_missing_facts(scene, progress=progress)
    assert extraction == ["first happened."]
    assert result["done"] == 1 and result["stopped"] is True
    assert "facts_status" not in scene.archived_history[-1]
    assert summarizer.stop_missing_facts(scene) is False


async def test_interrupt_between_entries_stops_the_run(history_scene, extraction):
    scene, summarizer = history_scene

    async def progress(state):
        if state["entry_id"] == "first":
            scene.interrupt()
            # a websocket message in between clears the flag, not the interrupt
            scene.cancel_requested = False

    result = await summarizer.generate_missing_facts(scene, progress=progress)
    assert extraction == ["first happened."]
    assert result["stopped"] is True
    assert not scene.cancel_requested


async def test_interrupt_during_an_entry_keeps_that_entry_unchanged(
    history_scene, monkeypatch
):
    scene, summarizer = history_scene

    async def interrupted(text, **kwargs):
        scene.interrupt()
        scene.continue_actions()

    monkeypatch.setattr(summarizer, "extract_facts", AsyncMock(side_effect=interrupted))
    result = await summarizer.generate_missing_facts(scene)
    assert result["stopped"] is True and result["done"] == 0
    assert "facts_status" not in scene.archived_history[0]
    assert not scene.cancel_requested
    assert not summarizer.missing_facts_running(scene)


async def test_entry_that_got_facts_meanwhile_is_skipped(history_scene, extraction):
    scene, summarizer = history_scene

    async def progress(state):
        if state["entry_id"] == "first":
            scene.archived_history[-1]["facts_status"] = "ok"

    result = await summarizer.generate_missing_facts(scene, progress=progress)
    assert extraction == ["first happened."]
    assert result["skipped"] == 1 and result["done"] == 2


async def test_extract_facts_off_or_a_second_run_is_refused(history_scene, extraction):
    scene, summarizer = history_scene
    summarizer.actions["archive"].config["extract_facts"].value = False
    with pytest.raises(MissingFactsRefused, match="Extract facts"):
        await summarizer.generate_missing_facts(scene)
    assert extraction == []
    summarizer.actions["archive"].config["extract_facts"].value = True

    async def progress(state):
        with pytest.raises(MissingFactsRefused, match="already"):
            await summarizer.generate_missing_facts(scene)

    await summarizer.generate_missing_facts(scene, progress=progress)


async def test_turning_extract_facts_off_stops_the_run(history_scene, extraction):
    scene, summarizer = history_scene

    async def progress(state):
        if state["entry_id"] == "first":
            summarizer.actions["archive"].config["extract_facts"].value = False

    result = await summarizer.generate_missing_facts(scene, progress=progress)
    assert extraction == ["first happened."]
    assert (result["done"], result["skipped"], result["stopped"]) == (1, 0, True)


def test_standard_entry_without_span_messages_is_unavailable(history_scene):
    scene, summarizer = history_scene
    scene.archived_history.append(entry("gone", start=40, end=44, ts=80))
    reason = summarizer.fact_source_unavailable_reason(
        scene, ArchiveEntry(**scene.archived_history[-1])
    )
    assert reason == "This entry's source messages are no longer in the scene history."
    assert [row.id for row in summarizer.entries_missing_facts(scene)] == [
        "first",
        "last",
    ]


async def test_interrupt_during_a_perspectives_entry_keeps_it_selected(
    history_scene, monkeypatch
):
    scene, summarizer = history_scene
    scene.knowledge_eligibility = "perception"
    for identity in ("first", "last"):
        set_source_perspectives(
            scene,
            "summary",
            identity,
            [
                {
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": f"Alice saw {identity}.",
                }
            ],
        )

    async def interrupted(text, **kwargs):
        scene.interrupt()
        scene.continue_actions()

    monkeypatch.setattr(summarizer, "extract_facts", AsyncMock(side_effect=interrupted))
    result = await summarizer.generate_missing_facts(scene)
    assert (result["done"], result["failed"], result["stopped"]) == (0, 0, True)
    assert "facts_status" not in scene.archived_history[0]
    assert [row.id for row in summarizer.entries_missing_facts(scene)] == [
        "first",
        "last",
    ]
    assert not scene.cancel_requested


@pytest.fixture
def plugin(history_scene, monkeypatch):
    from talemate.server.world_state_manager import WorldStateManagerPlugin

    scene, _ = history_scene
    websocket = Mock(scene=scene)
    monkeypatch.setattr(scene, "save", AsyncMock())
    return WorldStateManagerPlugin(websocket), websocket


def sent(websocket, action):
    return [
        call.args[0]["data"]
        for call in websocket.queue_put.call_args_list
        if call.args[0].get("action") == action
    ]


async def test_handler_reports_progress_and_refreshes_the_history(plugin, extraction):
    plugin, websocket = plugin
    await (await plugin.handle_generate_missing_facts({"run_id": "run-1"}))
    progress = sent(websocket, "missing_facts_progress")
    assert [(state["run_id"], state["done"]) for state in progress] == [
        ("run-1", 0),
        ("run-1", 1),
        ("run-1", 2),
    ]
    (done,) = sent(websocket, "missing_facts_done")
    assert (done["run_id"], done["total"], done["ok"], done["stopped"]) == (
        "run-1",
        2,
        2,
        False,
    )
    assert done["error"] is None
    assert len(sent(websocket, "scene_history")) == 2


async def test_handler_stop_request_ends_the_run_after_the_current_entry(
    plugin, history_scene, monkeypatch
):
    plugin, websocket = plugin
    _, summarizer = history_scene

    async def extract(text, **kwargs):
        await plugin.handle_stop_missing_facts({})
        return [ParsedFact(text=text)]

    monkeypatch.setattr(summarizer, "extract_facts", AsyncMock(side_effect=extract))
    await (await plugin.handle_generate_missing_facts({"run_id": "run-2"}))
    (done,) = sent(websocket, "missing_facts_done")
    assert (done["run_id"], done["done"], done["stopped"]) == ("run-2", 1, True)
    summarizer.extract_facts.assert_awaited_once()


async def test_handler_refuses_with_extract_facts_off(plugin, history_scene):
    plugin, websocket = plugin
    _, summarizer = history_scene
    summarizer.actions["archive"].config["extract_facts"].value = False
    await (await plugin.handle_generate_missing_facts({"run_id": "run-3"}))
    (error,) = [
        call.args[0]
        for call in websocket.queue_put.call_args_list
        if call.args[0].get("action") == "operation_done"
    ]
    assert error["failed_action"] == "generate_missing_facts"
    assert "Extract facts" in error["error"]["message"]
    (done,) = sent(websocket, "missing_facts_done")
    assert done["run_id"] == "run-3" and "Extract facts" in done["error"]
    assert "total" not in done


async def test_handler_reports_an_unexpected_failure_as_done_with_an_error(
    plugin, history_scene, monkeypatch
):
    plugin, websocket = plugin
    _, summarizer = history_scene
    monkeypatch.setattr(
        summarizer, "extract_facts", AsyncMock(side_effect=ValueError("broken store"))
    )
    task = await plugin.handle_generate_missing_facts({"run_id": "run-4"})
    with pytest.raises(ValueError, match="broken store"):
        await task
    (done,) = sent(websocket, "missing_facts_done")
    assert (done["run_id"], done["done"], done["error"]) == ("run-4", 0, "broken store")
    assert not summarizer.missing_facts_running(history_scene[0])
