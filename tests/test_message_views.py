import pytest

from talemate.knowledge.intro import sync_intro_knowledge
from talemate.knowledge.message_views import (
    character_message_views,
    intro_view,
    message_view,
)
from talemate.scene_message import DirectorMessage, NarratorMessage

import test_knowledge_perspectives

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


@pytest.mark.parametrize(
    "name,status,text",
    [
        ("Alice", "ready", "Alice hides the ledger beneath the bed."),
        ("Cara", "ready", "Footsteps sound in the room."),
        ("Erin", "omitted", None),
        ("Finn", "pending", None),
        ("Grace", "failed", None),
        ("Hazel", "unavailable", None),
    ],
)
def test_supported_message_is_editable_in_every_view_state(scene, name, status, text):
    scene.history[0].present = [name]
    scene.history[0].mark_revision_committed()
    view = message_view(scene, scene.history[0], name)
    assert (view.status, view.text, view.editable) == (status, text, True)


def test_message_without_knowledge_is_editable(scene):
    scene.history.append(NarratorMessage("A bell rings.", id=102))
    view = message_view(scene, scene.history[-1], "Alice")
    assert (view.status, view.editable) == ("omitted", True)


def test_unsupported_running_and_deferred_are_not_editable(scene, summarizer):
    scene.history[0].present = ["Alice"]
    scene.history[0].mark_revision_committed()
    scene.history.append(DirectorMessage(message="Bob, hurry.", id=102))
    assert message_view(scene, scene.history[-1], "Bob").model_dump() == {
        "status": "unsupported",
        "text": None,
        "editable": False,
        "reason": "This type of message has no perspectives.",
    }
    summarizer._perception_running[scene] = {101}
    running = message_view(scene, scene.history[0], "Alice")
    assert (running.status, running.reason) == (
        "running",
        "The analysis of this message runs now.",
    )
    summarizer._perception_running.clear()
    scene.history[0].append_version("A new version of the passage.", source="custom")
    view = message_view(scene, scene.history[0], "Alice")
    assert (view.status, view.text, view.editable) == ("deferred", None, False)
    assert view.reason == "Keep a version of this message first."


def test_views_are_keyed_by_message_id(scene):
    scene.history.append(DirectorMessage(message="Bob, hurry.", id=102))
    views = character_message_views(scene, "Bob")
    assert {key: view.status for key, view in views.items()} == {
        101: "ready",
        102: "unsupported",
    }


class _Editor:
    fix_exposition_enabled = False


def test_intro_view_is_read_only(scene, monkeypatch):
    monkeypatch.setattr("talemate.tale_mate.get_agent", lambda name: _Editor())
    scene.intro = "Rain falls on the inn."
    scene.intro_present = ["Alice"]
    scene.intro_knowledge = None
    sync_intro_knowledge(scene)
    assert intro_view(scene, "Alice").model_dump() == {
        "status": "ready",
        "text": "Rain falls on the inn.",
        "editable": False,
        "reason": None,
    }
    assert intro_view(scene, "Bob").model_dump() == {
        "status": "not_present",
        "text": None,
        "editable": False,
        "reason": None,
    }


def test_scene_without_intro_record_reports_not_present(scene):
    scene.intro_present = None
    scene.intro_knowledge = None
    assert intro_view(scene, "Alice").status == "not_present"
