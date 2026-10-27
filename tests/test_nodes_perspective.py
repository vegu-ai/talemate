"""
Perspective nodes (Get / Set Message View), the perspective.view_edited event
and the perspective input of Context History.
"""

import asyncio

import pytest

import talemate.emit.async_signals as async_signals
from _node_test_helpers import run_node
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.nodes.history import ContextHistory
from talemate.game.engine.nodes.perspective import GetMessageView, SetMessageView
from talemate.knowledge.message_views import PerspectiveViewEditedEvent
from talemate.knowledge.perspectives import select_character_view, source_reference

import test_knowledge_perspectives

add_layered_view = test_knowledge_perspectives.add_layered_view
scene = test_knowledge_perspectives.scene
scene_data = test_knowledge_perspectives.scene_data


class _Summarizer:
    def __init__(self):
        self._perception_running = {}


@pytest.fixture(autouse=True)
def summarizer(monkeypatch):
    agent = _Summarizer()
    monkeypatch.setattr("talemate.knowledge.readiness.get_agent", lambda name: agent)
    return agent


@pytest.fixture
def status_emits(scene, monkeypatch):
    calls = []
    monkeypatch.setattr(scene, "emit_status", lambda: calls.append(True))
    return calls


@pytest.fixture
def edited_events():
    events = []

    async def listener(event):
        events.append(event)

    signal = async_signals.get("perspective.view_edited")
    signal.connect(listener)
    yield events
    signal.disconnect(listener)


class TestGetMessageView:
    @pytest.mark.asyncio
    async def test_reads_a_character_view_by_id(self, scene):
        out = await run_node(
            GetMessageView(),
            scene=scene,
            inputs={"message_id": 101, "character": "Alice"},
        )
        assert out["message_id"] == 101
        assert out["character"] == "Alice"
        assert out["status"] == "ready"
        assert out["text"] == "Alice hides the ledger beneath the bed."
        assert out["editable"] is True
        assert out["reason"] is None

    @pytest.mark.asyncio
    async def test_reads_a_view_from_a_message_object(self, scene):
        out = await run_node(
            GetMessageView(),
            scene=scene,
            inputs={"message": scene.history[0], "character": "Bob"},
        )
        assert out["text"] == "Bob sees Alice kneel beside the bed."

    @pytest.mark.asyncio
    async def test_unknown_message_is_refused(self, scene):
        with pytest.raises(InputValueError) as exc:
            await run_node(
                GetMessageView(),
                scene=scene,
                inputs={"message_id": 999, "character": "Alice"},
            )
        assert exc.value.input_name == "message_id"


class TestSetMessageView:
    @pytest.mark.asyncio
    async def test_replaces_the_view_and_sends_view_edited(
        self, scene, status_emits, edited_events
    ):
        add_layered_view(scene)
        out = await run_node(
            SetMessageView(),
            scene=scene,
            inputs={
                "message_id": 101,
                "character": "Alice",
                "text": "Alice burns the ledger.",
            },
        )
        assert out["changed"] is True
        assert out["status"] == "ready"
        assert out["text"] == "Alice burns the ledger."
        assert scene.saved is False
        assert status_emits == [True]
        summary = source_reference(scene, "summary", "summary-1")
        assert select_character_view(scene, summary, "Alice").status == "ready"

        await asyncio.sleep(0)
        [event] = edited_events
        assert isinstance(event, PerspectiveViewEditedEvent)
        assert event.scene is scene
        assert event.message_id == 101
        assert event.character == "Alice"
        assert event.status == "ready"
        assert event.text == "Alice burns the ledger."
        assert event.dependents >= 1

    @pytest.mark.asyncio
    async def test_empty_text_omits_the_message(self, scene, status_emits):
        out = await run_node(
            SetMessageView(),
            scene=scene,
            inputs={"message_id": 101, "character": "Bob", "text": ""},
        )
        assert out["status"] == "omitted"
        assert out["text"] is None

    @pytest.mark.asyncio
    async def test_unchanged_text_sends_nothing(
        self, scene, status_emits, edited_events
    ):
        out = await run_node(
            SetMessageView(),
            scene=scene,
            inputs={
                "message_id": 101,
                "character": "Alice",
                "text": "Alice hides the ledger beneath the bed.",
            },
        )
        assert out["changed"] is False
        await asyncio.sleep(0)
        assert edited_events == []
        assert status_emits == []

    @pytest.mark.asyncio
    async def test_running_analysis_refuses_the_edit(self, scene, summarizer):
        summarizer._perception_running[scene] = {101}
        with pytest.raises(InputValueError, match="analysis of this message"):
            await run_node(
                SetMessageView(),
                scene=scene,
                inputs={"message_id": 101, "character": "Alice", "text": "x"},
            )

    @pytest.mark.asyncio
    async def test_refused_outside_character_perspectives(self, scene):
        scene.knowledge_eligibility = "legacy"
        with pytest.raises(InputValueError, match="perspectives are off"):
            await run_node(
                SetMessageView(),
                scene=scene,
                inputs={"message_id": 101, "character": "Alice", "text": "x"},
            )


class TestContextHistoryPerspective:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("as_object", [False, True])
    async def test_perspective_is_passed_with_stored_views(
        self, scene, monkeypatch, as_object
    ):
        calls = []

        def context_history(**kwargs):
            calls.append(kwargs)
            return ["Alice: I hid it."]

        monkeypatch.setattr(scene, "context_history", context_history)
        perspective = scene.character_data["Alice"] if as_object else "Alice"
        out = await run_node(
            ContextHistory(), scene=scene, inputs={"perspective": perspective}
        )
        assert calls[0]["perspective"] == "Alice"
        assert calls[0]["stored_views"] is True
        assert out["compiled"] == "Alice: I hid it."

    @pytest.mark.asyncio
    async def test_without_perspective_nothing_changes(self, scene, monkeypatch):
        calls = []
        monkeypatch.setattr(
            scene, "context_history", lambda **kwargs: calls.append(kwargs) or []
        )
        await run_node(ContextHistory(), scene=scene)
        assert "perspective" not in calls[0]
        assert "stored_views" not in calls[0]
