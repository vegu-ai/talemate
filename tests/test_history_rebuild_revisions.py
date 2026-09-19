"""A full history rebuild settles Standard revisions and preserves repair work."""

from unittest.mock import AsyncMock

import pytest

from test_revision_browsing import standard_revision
from talemate.exceptions import GenerationCancelled
from talemate.history import rebuild_history
from talemate.knowledge.revision_browsing import defer_revision_work
from talemate.knowledge.revision_refresh import (
    _archive_vector_repairs,
    begin_revision_transaction,
    revision_refresh_payload,
    revisions_before_rebuild,
)
from talemate.scene_message import RevisionIndexRepair
from talemate.knowledge.schema import KnowledgeEdge


@pytest.fixture
def rebuilding(scene, monkeypatch):
    summarizer, _, message = standard_revision(scene)
    scene.active = True
    # Summary generation itself is covered by test_summarizer; this suite
    # exercises the real rebuild coordinator around its completion boundary.
    monkeypatch.setattr(summarizer, "build_archive", AsyncMock(return_value=False))
    monkeypatch.setattr(summarizer, "summarize_to_layered_history", AsyncMock())
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    return scene, summarizer, message


async def test_rebuild_commits_standard_revision_and_keeps_authored_rules(rebuilding):
    scene, _, message = rebuilding
    edge = KnowledgeEdge(character="Bob", target="Alice.description", kind="revoke")
    scene.world_state.knowledge = [edge]
    await rebuild_history(scene)
    assert message.revision_matches_baseline
    assert not revision_refresh_payload(scene, message)["revision_refresh"]["required"]
    assert scene.world_state.knowledge == [edge]


async def test_rebuild_moves_pending_archive_index_repair_to_scene(rebuilding):
    scene, _, message = rebuilding
    message.set_revision_status(
        "deferred", pending_index_repair=RevisionIndexRepair(archive_ids=["base:gone"])
    )
    await rebuild_history(scene)
    assert message.revision_state.pending_index_repair is None
    assert "base:gone" in _archive_vector_repairs[scene]


async def test_cancelled_rebuild_does_not_commit_the_revision(rebuilding):
    scene, summarizer, message = rebuilding
    summarizer.build_archive.side_effect = GenerationCancelled("stop")
    await rebuild_history(scene)
    assert not message.revision_matches_baseline


async def test_browsing_after_rebuild_keeps_new_baseline(rebuilding):
    scene, _, message = rebuilding
    await rebuild_history(scene)
    with defer_revision_work():
        scene.set_message_active_version(message.id, 0)
    assert not message.revision_matches_baseline
    assert message.revision_state.baseline_index == 1


def test_perspective_rebuild_does_not_settle_perception_analysis(rebuilding):
    scene, _, message = rebuilding
    begin_revision_transaction(scene, message)
    scene.knowledge_eligibility = "perception"
    assert revisions_before_rebuild(scene) == []
    assert message.revision_state.refresh_journal is not None
