from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from talemate.history import ArchiveEntry, count_summary_layers
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    TimePassageMessage,
)
from talemate.server.scene_message import SceneMessagePlugin

from conftest import MockScene, bootstrap_scene


def _archived(text="summary", start=None, end=None):
    return ArchiveEntry(text=text, ts=0, start=start, end=end).model_dump(
        exclude_none=True
    )


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.history = []
    scene.archived_history = []
    scene.layered_history = []
    return scene


class TestCountSummaryLayers:
    def test_fresh_scene_has_no_layers(self, scene):
        assert count_summary_layers(scene) == 0

    def test_static_archive_entries_are_not_a_layer(self, scene):
        scene.archived_history = [_archived("backstory")]
        assert count_summary_layers(scene) == 0

    def test_first_summary_makes_the_base_archive_a_layer(self, scene):
        scene.archived_history = [_archived("backstory"), _archived(start=0, end=3)]
        assert count_summary_layers(scene) == 1

    def test_populated_layered_history_layers_add_one_each(self, scene):
        scene.archived_history = [_archived(start=0, end=3)]
        scene.layered_history = [[_archived(start=0, end=0)], [], [_archived()]]
        assert count_summary_layers(scene) == 3

    def test_missing_layered_history_attribute(self, scene):
        scene.archived_history = [_archived(start=0, end=3)]
        scene.layered_history = None
        assert count_summary_layers(scene) == 1


def _scene_status(scene):
    scene.active = True
    with patch("talemate.tale_mate.emit") as emit:
        scene._do_emit_status()
    (status,) = [call for call in emit.call_args_list if call.args[0] == "scene_status"]
    return status.kwargs["data"]


def test_scene_status_carries_history_stats(scene):
    scene.history = [
        CharacterMessage(message="Alice: one", source="ai"),
        CharacterMessage(message="Alice: two", source="ai"),
    ]
    scene.archived_history = [_archived(start=0, end=0)]

    stats = _scene_status(scene)["history_stats"]

    assert stats["message_count"] == 2
    assert stats["summary_layers"] == 1
    summarization = stats["summarization"]
    assert summarization["enabled"] is True
    assert summarization["due"] is False
    assert summarization["due_reason"] is None
    assert summarization["threshold"] > 0
    assert summarization["pending_tokens"] == 0
    assert summarization["remaining_tokens"] == summarization["threshold"] + 1


def test_history_stats_counts_only_character_and_narrator_messages(scene):
    scene.history = [
        CharacterMessage(message="Alice: one", source="ai"),
        NarratorMessage(message="The room falls quiet."),
        DirectorMessage(message="Alice hesitates."),
        TimePassageMessage(message="an hour later", ts=3600),
    ]

    stats = scene.history_stats()

    assert stats["message_count"] == 4
    assert stats["character_narrator_messages"] == 2


def test_scene_status_reports_summarization_without_a_ready_client(scene):
    summarizer = bootstrap_scene(scene)["summarizer"]
    summarizer.client = None

    summarization = _scene_status(scene)["history_stats"]["summarization"]

    assert summarization["enabled"] is True
    assert summarization["remaining_tokens"] == summarization["threshold"] + 1


@pytest.mark.asyncio
async def test_deleting_a_message_in_a_never_saved_scene_publishes_status(scene):
    first = CharacterMessage(message="Alice: one", source="ai")
    second = CharacterMessage(message="Alice: two", source="ai")
    scene.history = [first, second]
    scene.filename = None
    assert not scene.can_auto_save()

    class _Handler:
        def __init__(self, scene):
            self.scene = scene

    plugin = SceneMessagePlugin(_Handler(scene))
    with (
        patch.object(
            type(scene), "auto_save", new_callable=PropertyMock, return_value=True
        ),
        patch("talemate.tale_mate.emit"),
        patch.object(scene, "emit_status") as emit_status,
        patch.object(scene, "save", AsyncMock()) as save,
    ):
        assert scene.auto_save is True
        await plugin.handle_delete({"id": first.id})

    assert scene.history == [second]
    emit_status.assert_called_once()
    save.assert_awaited_once_with(auto=True)
    assert scene.history_stats()["message_count"] == 1
