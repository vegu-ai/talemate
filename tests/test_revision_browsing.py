import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import test_perception_lifecycle
from test_perception_lifecycle import result
from talemate.exceptions import GenerationCancelled
from talemate.scene_message import NarratorMessage
from talemate.server.scene_message import SceneMessagePlugin

setup = test_perception_lifecycle.setup


@pytest.fixture
async def browsing(setup, monkeypatch):
    scene, summarizer, request = setup
    message = NarratorMessage(message="The bell rings.")
    for index in range(5):
        message.append_version(f"The bell rings {index + 2} times.", "regenerate")
    await scene.push_history(message)
    request.reset_mock()
    frames = []
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))
    yield scene, summarizer, request, message, plugin, frames


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [True, False])
async def test_five_swaps_analyze_only_kept_text(browsing, commit):
    scene, summarizer, request, message, plugin, frames = browsing
    for index in [4, 3, 2, 1, 0]:
        await plugin.handle_swap_revision({"id": message.id, "index": index})
        await asyncio.sleep(0)
        assert message.active_version == index
        assert message.id in scene.pending_perception_messages
        request.assert_not_awaited()
    analyzed = []

    async def analyze(*args, **kwargs):
        analyzed.append(kwargs["vars"]["context"]["passage"]["text"])
        return result()

    request.side_effect = analyze
    if commit:
        task = await plugin.handle_commit_revision(
            {"id": message.id, "index": 0, "request_id": "keep"}
        )
        await task
        assert any(f.get("action") == "revision_committed" for f in frames)
        # Duplicate keep requests and later catch-up reuse the valid analysis.
        await (await plugin.handle_commit_revision({"id": message.id, "index": 0}))
        await summarizer.ensure_perceptions(scene)
        assert analyzed == ["The bell rings."]
    else:
        await scene.push_history(NarratorMessage(message="Alice opens the window."))
        # One request for the kept passage, one for the new passage.
        assert analyzed == ["The bell rings.", "Alice opens the window."]
        assert request.await_count == 2
    assert scene.pending_perception_messages == []
    assert all(view.status == "ready" for view in message.knowledge.views)


@pytest.mark.asyncio
async def test_failed_commit_returns_correlated_error_and_stays_pending(browsing):
    scene, _, request, message, plugin, frames = browsing
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    request.side_effect = GenerationCancelled("Cancelled by user")
    task = await plugin.handle_commit_revision(
        {"id": message.id, "index": 0, "request_id": "keep"}
    )
    with pytest.raises(GenerationCancelled):
        await task
    assert message.id in scene.pending_perception_messages
    assert any(f.get("request_id") == "keep" and f.get("error") for f in frames)


@pytest.mark.asyncio
async def test_old_commit_does_not_analyze_new_selection(browsing):
    _, _, request, message, plugin, frames = browsing
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    await (
        await plugin.handle_commit_revision(
            {"id": message.id, "index": 1, "request_id": "old"}
        )
    )
    request.assert_not_awaited()
    assert any(f.get("request_id") == "old" and f.get("error") for f in frames)


@pytest.mark.asyncio
async def test_browse_retains_dirty_fact_work_without_scheduling(browsing):
    from talemate.knowledge.revision_browsing import defer_revision_work

    scene, summarizer, _, _, _, _ = browsing
    run = AsyncMock()
    with defer_revision_work():
        summarizer._queue_fact_work(scene, {"F42"}, run)
    await asyncio.sleep(0)
    run.assert_not_awaited()
    assert summarizer._fact_memory_dirty[scene] == {"F42"}
    summarizer._queue_fact_work(scene, set(), run)
    await summarizer._fact_wakeup_tasks[scene]
    run.assert_awaited_once_with(scene)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_rejected_swap_correlates_its_terminal_error(browsing, missing):
    _, _, request, message, plugin, frames = browsing
    await plugin.handle_swap_revision(
        {
            "id": 999999 if missing else message.id,
            "index": 999,
            "request_id": "rejected-swap",
        }
    )
    failures = [frame for frame in frames if frame.get("error")]
    assert len(failures) == 1
    assert failures[0]["request_id"] == "rejected-swap"
    assert failures[0]["failed_action"] == "swap_revision"
    assert message.active_version == 5
    request.assert_not_awaited()
