from talemate.knowledge.step import knowledge_step
from _knowledge_step_helpers import push_and_step
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import test_perception_lifecycle
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.perspectives import select_character_view, source_reference
from talemate.knowledge.revision_refresh import (
    catch_up_revisions,
    refresh_revision,
    revision_operations,
    revision_refresh_payload,
)
from talemate.knowledge.schema import KnowledgeEdge
from talemate.scene_message import (
    MessageRevisionState,
    NarratorMessage,
    RevisionIndexRepair,
)
from talemate.server.scene_message import SceneMessagePlugin
from talemate.world_state import ManualContext

setup = test_perception_lifecycle.setup


@pytest.fixture
async def revised(setup, monkeypatch):
    scene, summarizer, request = setup
    message = NarratorMessage(message="The harbor bell rings once.")
    message.append_version("The harbor bell rings twice.", "regenerate")
    await push_and_step(scene, message)
    baseline = message.knowledge
    scene.world_state.manual_context["harbor"] = ManualContext(
        id="harbor", text="The harbor closes at sunset."
    )
    edge = KnowledgeEdge(character="Bob", target="harbor", kind="revoke")
    scene.world_state.knowledge.append(edge)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    request.reset_mock()
    return SimpleNamespace(
        scene=scene,
        summarizer=summarizer,
        request=request,
        message=message,
        baseline=baseline,
        plugin=plugin,
        edge=edge,
    )


@pytest.mark.asyncio
async def test_status_refreshes_match_the_payload_of_a_history_scan(revised):
    t = revised
    payload = revision_refresh_payload(t.scene, t.message)["revision_refresh"]
    refreshes = {item["id"]: item for item in t.scene.revision_refreshes}

    assert payload["required"]
    assert refreshes[t.message.id]["revision_refresh"] == payload
    assert revision_operations(t.scene, t.message).any

    t.scene.history.remove(t.message)

    assert not revision_operations(t.scene, t.message).any


class CountingHistory(list):
    scans = 0

    def __iter__(self):
        CountingHistory.scans += 1
        return super().__iter__()


@pytest.mark.asyncio
async def test_status_refreshes_scan_the_history_once_not_per_message(revised):
    t = revised
    t.scene.history.extend(
        NarratorMessage(message=f"The tide turns {i}.") for i in range(50)
    )
    t.scene.history = CountingHistory(t.scene.history)
    CountingHistory.scans = 0

    refreshes = t.scene.revision_refreshes

    assert len(refreshes) == 51
    # the loop itself, plus the archive lookup of the one required message
    assert CountingHistory.scans <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("reload_revision", [False, True])
async def test_summary_repair_retry_reuses_view_and_preserves_authored_rules(
    revised, monkeypatch, reload_revision
):
    t = revised
    repairs = AsyncMock(side_effect=RuntimeError("dependent summary unavailable"))
    monkeypatch.setattr(t.summarizer, "repair_summary_views", repairs)

    with pytest.raises(RuntimeError, match="dependent summary unavailable"):
        await refresh_revision(t.scene, t.message)

    assert t.message.revision_state.status == "failed"
    assert t.message.revision_state.baseline_index == 1
    assert t.message.knowledge.views[0].status == "ready"
    assert revision_refresh_payload(t.scene, t.message)["revision_refresh"]["required"]
    t.request.assert_awaited_once()
    repairs.side_effect = None
    if reload_revision:
        saved_state = t.message.revision_state
        restored_state = MessageRevisionState.model_validate_json(
            saved_state.model_dump_json()
        )
        assert restored_state.phase_receipts == saved_state.phase_receipts
        t.message.revision_state = restored_state

    await refresh_revision(t.scene, t.message)
    if reload_revision:
        saved_state = t.message.revision_state
        assert "refresh:perceptions" in saved_state.phase_receipts
        restored_state = MessageRevisionState.model_validate_json(
            saved_state.model_dump_json()
        )
        assert restored_state.phase_receipts == saved_state.phase_receipts
        t.message.revision_state = restored_state
    await catch_up_revisions(t.scene)

    t.request.assert_awaited_once()
    assert repairs.await_count == 2
    assert t.message.revision_matches_baseline
    assert t.message.revision_state.status == "clean"
    assert t.scene.world_state.knowledge == [t.edge]
    assert not revision_refresh_payload(t.scene, t.message)["revision_refresh"][
        "required"
    ]


@pytest.mark.asyncio
async def test_return_after_failed_refresh_restores_views_and_keeps_later_grant(
    revised, monkeypatch
):
    t = revised
    later = KnowledgeEdge(character="Alice", target="harbor", kind="grant")

    async def fail_repair(*args, **kwargs):
        t.scene.world_state.knowledge.append(later)
        raise RuntimeError("dependent summary unavailable")

    monkeypatch.setattr(t.summarizer, "repair_summary_views", fail_repair)
    with pytest.raises(RuntimeError, match="dependent summary unavailable"):
        await refresh_revision(t.scene, t.message)

    await t.plugin.handle_swap_revision({"id": t.message.id, "index": 1})

    assert t.message.knowledge == t.baseline
    assert t.message.revision_matches_baseline
    assert t.scene.world_state.knowledge == [t.edge, later]
    assert (
        select_character_view(
            t.scene, source_reference(t.scene, "message", t.message.id), "Bob"
        ).status
        == "ready"
    )
    t.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_steps_analyze_a_revision_once(revised):
    t = revised
    started, release = asyncio.Event(), asyncio.Event()

    async def analyze(*args, **kwargs):
        started.set()
        await asyncio.wait_for(release.wait(), 3)
        return test_perception_lifecycle.result()

    t.request.side_effect = analyze
    first = asyncio.create_task(knowledge_step(t.scene))
    second = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        second = asyncio.create_task(knowledge_step(t.scene))
        await asyncio.sleep(0)
    finally:
        release.set()
        await asyncio.wait_for(
            asyncio.gather(first, *([second] if second is not None else [])), 3
        )

    t.request.assert_awaited_once()
    assert t.message.revision_matches_baseline
    assert t.scene.world_state.knowledge == [t.edge]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["scene", "selection"])
async def test_changed_owner_or_selection_cannot_commit_after_summary_await(
    revised, monkeypatch, mutation
):
    t = revised

    async def repair(*args, **kwargs):
        if mutation == "scene":
            t.summarizer.scene = SimpleNamespace()
        else:
            t.message.message = "The harbor bell is silent."

    monkeypatch.setattr(t.summarizer, "repair_summary_views", repair)

    with pytest.raises(GenerationCancelled):
        await refresh_revision(t.scene, t.message)

    assert t.message.revision_state.baseline_index == 1
    assert not t.message.revision_matches_baseline
    assert t.scene.world_state.knowledge == [t.edge]
    t.scene.attempt_auto_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_restored_archive_index_repair_does_not_analyze_again(revised):
    t = revised
    await t.plugin.handle_swap_revision({"id": t.message.id, "index": 1})
    t.message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:old"])
    )

    payload = revision_refresh_payload(t.scene, t.message)["revision_refresh"]
    assert payload["operations"] == ["index_repair"]
    await refresh_revision(t.scene, t.message)

    assert t.message.revision_state.pending_index_repair is None
    assert t.message.revision_matches_baseline
    assert t.scene.world_state.knowledge == [t.edge]
    t.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_standard_revision_invalidates_archive_without_requests_or_rule_changes(
    revised, monkeypatch
):
    t = revised
    t.scene.knowledge_eligibility = "legacy"
    t.request.side_effect = AssertionError(
        "Standard revision must not request extraction"
    )
    t.scene.archived_history = [
        {
            "id": "chapter",
            "text": "The bell rings twice.",
            "start": 0,
            "end": 0,
            "ts": 0,
        }
    ]
    deleted = AsyncMock()
    monkeypatch.setattr(get_agent("memory"), "delete", deleted)

    await refresh_revision(t.scene, t.message)

    assert t.scene.archived_history == []
    assert any(call.args[0] == {"ids": ["chapter"]} for call in deleted.await_args_list)
    assert t.message.revision_matches_baseline
    assert t.scene.world_state.knowledge == [t.edge]
    t.request.assert_not_awaited()
