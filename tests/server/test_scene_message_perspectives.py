import pytest

from talemate.knowledge.perspectives import (
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.scene_message import DirectorMessage, NarratorMessage
from talemate.server.scene_message import SceneMessagePlugin

import test_knowledge_perspectives

add_layered_view = test_knowledge_perspectives.add_layered_view
scene = test_knowledge_perspectives.scene
scene_data = test_knowledge_perspectives.scene_data


class _Handler:
    def __init__(self, scene):
        self.scene = scene
        self.messages = []

    def queue_put(self, data):
        self.messages.append(data)


class _Summarizer:
    def __init__(self):
        self._perception_running = {}


@pytest.fixture
def summarizer(monkeypatch):
    agent = _Summarizer()
    monkeypatch.setattr("talemate.knowledge.readiness.get_agent", lambda name: agent)
    return agent


@pytest.fixture
def plugin(scene, summarizer, monkeypatch):
    saves = []

    async def auto_save():
        saves.append(scene.history[0].knowledge)

    monkeypatch.setattr(scene, "attempt_auto_save", auto_save)
    monkeypatch.setattr(scene, "emit_status", lambda: None)
    monkeypatch.setattr("talemate.server.websocket_plugin.emit", lambda *a, **kw: None)
    plug = SceneMessagePlugin(_Handler(scene))
    plug.saves = saves
    return plug


def replies(plugin, action):
    return [
        message
        for message in plugin.websocket_handler.messages
        if message["action"] == action
    ]


@pytest.mark.asyncio
async def test_get_perspectives_lists_each_message_and_the_intro(plugin, scene):
    scene.history.append(DirectorMessage(message="Bob, hurry.", id=102))
    await plugin.handle_get_perspectives({"character": "Erin"})
    (reply,) = replies(plugin, "perspectives")
    assert reply["character"] == "Erin"
    assert reply["views"] == {
        101: {"status": "omitted", "text": None, "editable": True, "reason": None},
        102: {
            "status": "unsupported",
            "text": None,
            "editable": False,
            "reason": "This type of message has no perspectives.",
        },
    }
    assert reply["intro"] == {
        "status": "not_present",
        "text": None,
        "editable": False,
        "reason": None,
    }
    assert reply["dependents"] == {}


@pytest.mark.asyncio
async def test_get_perspectives_refuses_outside_the_mode(plugin, scene):
    scene.knowledge_eligibility = "legacy"
    await plugin.handle_get_perspectives({"character": "Alice"})
    (reply,) = replies(plugin, "operation_done")
    assert reply["failed_action"] == "get_perspectives"
    assert replies(plugin, "perspectives") == []


@pytest.mark.asyncio
async def test_edit_reports_the_view_and_its_dependents_then_saves(plugin, scene):
    add_layered_view(scene)
    await plugin.handle_edit_perspective(
        {"id": 101, "character": "Alice", "text": "Alice burns the ledger."}
    )
    (reply,) = replies(plugin, "perspective_edited")
    assert reply["id"] == 101
    assert reply["character"] == "Alice"
    assert reply["view"] == {
        "status": "ready",
        "text": "Alice burns the ledger.",
        "editable": True,
        "reason": None,
    }
    assert reply["changed"] is True
    assert scene.saved is False
    assert plugin.saves == [scene.history[0].knowledge]
    summary = source_reference(scene, "summary", "summary-1")
    assert select_character_view(scene, summary, "Alice").status == "ready"


@pytest.mark.asyncio
async def test_unchanged_text_writes_nothing_and_saves_nothing(plugin, scene):
    """Enter on a view the Summarizer wrote: it has sources, which a hand edit would drop."""
    scene.history.append(NarratorMessage("A bell rings.", id=102))
    cited = select_character_view(
        scene, source_reference(scene, "message", 101), "Alice"
    ).source
    set_source_perspectives(
        scene,
        "message",
        102,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice hears a bell.",
                "sources": [cited],
            }
        ],
    )
    before = scene.history[-1].knowledge
    scene.saved = True
    await plugin.handle_edit_perspective(
        {"id": 102, "character": "Alice", "text": "Alice hears a bell."}
    )
    (reply,) = replies(plugin, "perspective_edited")
    assert reply["changed"] is False
    assert reply["view"]["text"] == "Alice hears a bell."
    assert scene.history[-1].knowledge is before
    assert before.views[0].sources == (cited,)
    assert scene.saved is True
    assert plugin.saves == []


@pytest.mark.asyncio
async def test_changed_text_on_an_analysis_view_marks_the_scene_unsaved(plugin, scene):
    scene.saved = True
    await plugin.handle_edit_perspective(
        {"id": 101, "character": "Alice", "text": "Alice burns the ledger."}
    )
    assert replies(plugin, "perspective_edited")[-1]["changed"] is True
    assert scene.saved is False
    assert len(plugin.saves) == 1


@pytest.mark.asyncio
async def test_dependents_are_counted_for_the_edited_views_at_each_read(plugin, scene):
    scene.history.append(NarratorMessage("A bell rings.", id=102))
    await plugin.handle_edit_perspective(
        {"id": 101, "character": "Alice", "text": "Alice burns the ledger."}
    )
    edited = select_character_view(
        scene, source_reference(scene, "message", 101), "Alice"
    ).source
    set_source_perspectives(
        scene,
        "message",
        102,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice hears a bell and thinks of the fire.",
                "sources": [edited],
            }
        ],
    )
    request = {"character": "Alice", "edited": [101, 102, 999]}
    await plugin.handle_get_perspectives(request)
    assert replies(plugin, "perspectives")[-1]["dependents"] == {101: 2}

    # a hand edit carries no sources, so the edited dependent leaves the chain
    await plugin.handle_edit_perspective(
        {"id": 102, "character": "Alice", "text": "Alice hears a bell."}
    )
    await plugin.handle_get_perspectives(request)
    assert replies(plugin, "perspectives")[-1]["dependents"] == {101: 1}

    await plugin.handle_reanalyze_perspective_dependents(
        {"id": 101, "character": "Alice"}
    )
    assert replies(plugin, "perspective_dependents_invalidated")[-1]["count"] == 1

    await plugin.handle_get_perspectives({"character": "Alice"})
    assert replies(plugin, "perspectives")[-1]["dependents"] == {}


@pytest.mark.asyncio
async def test_edit_with_empty_text_omits_the_view(plugin):
    await plugin.handle_edit_perspective({"id": 101, "character": "Bob", "text": ""})
    (reply,) = replies(plugin, "perspective_edited")
    assert reply["view"] == {
        "status": "omitted",
        "text": None,
        "editable": True,
        "reason": None,
    }
    assert reply["changed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,error",
    [
        ({"id": 999, "character": "Bob", "text": "x"}, "Message 999 not found"),
        ({"id": 102, "character": "Bob", "text": "x"}, "no perspectives"),
        ({"id": 101, "character": "Nobody", "text": "x"}, "Unresolved"),
    ],
)
async def test_edit_refusals_change_nothing(plugin, scene, data, error):
    scene.history.append(DirectorMessage(message="Bob, hurry.", id=102))
    before = scene.history[0].knowledge
    await plugin.handle_edit_perspective(data)
    (reply,) = replies(plugin, "operation_done")
    assert error in reply["error"]["message"]
    assert reply["failed_action"] == "edit_perspective"
    assert scene.history[0].knowledge == before
    assert plugin.saves == []


@pytest.mark.asyncio
async def test_edit_is_refused_while_the_analysis_runs(plugin, scene, summarizer):
    summarizer._perception_running[scene] = {101}
    before = scene.history[0].knowledge
    await plugin.handle_edit_perspective(
        {"id": 101, "character": "Alice", "text": "Alice burns the ledger."}
    )
    (reply,) = replies(plugin, "operation_done")
    assert reply["error"]["message"] == "The analysis of this message runs now."
    assert scene.history[0].knowledge == before


@pytest.mark.asyncio
async def test_reanalyze_sets_the_dependents_to_pending(plugin, scene):
    layered = add_layered_view(scene)
    await plugin.handle_edit_perspective(
        {"id": 101, "character": "Alice", "text": "Alice burns the ledger."}
    )
    await plugin.handle_reanalyze_perspective_dependents(
        {"id": 101, "character": "Alice"}
    )
    (reply,) = replies(plugin, "perspective_dependents_invalidated")
    assert reply["count"] == 2
    assert select_character_view(scene, layered, "Alice").status == "pending"
    assert len(plugin.saves) == 2
