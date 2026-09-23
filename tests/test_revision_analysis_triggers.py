import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_perception_lifecycle import answer, result
from test_perception_lifecycle import setup as setup
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.perspectives import select_character_view, source_reference
from talemate.knowledge.readiness import perception_readiness
from talemate.knowledge.revision_refresh import (
    catch_up_revisions,
    revision_refresh_payload,
)
from talemate.regenerate import regenerate
from talemate.scene_message import CharacterMessage, NarratorMessage
from talemate.server.scene_message import SceneMessagePlugin
from talemate.tale_mate import Actor


@pytest.fixture
def flow(request, monkeypatch, isolate_signals):
    scene, summarizer, prompt_request = request.getfixturevalue("setup")
    scene.actors = [
        Actor(character, None) for character in scene.character_data.values()
    ]
    editor = get_agent("editor")
    editor.actions["revision"].enabled = True
    editor.actions["revision"].config["automatic_revision"].value = True
    editor.actions["revision"].config["automatic_revision_targets"].value = [
        "character",
        "narrator",
    ]
    order = []

    async def revise(info):
        order.append(("revision", info.text))
        return info.text.replace("brass", "silver")

    async def analyze(*args, **kwargs):
        passage = kwargs["vars"]["context"]["passage"]
        order.append(("perception", passage["text"]))
        return result(answer(passage["text"], passage["text"]))

    monkeypatch.setattr(editor, "revision_revise", revise)
    prompt_request.side_effect = analyze
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    isolate_signals("push_history", "push_history.after", "game_loop_new_message")
    scene.signals["push_history"].connect(editor.revision_on_push)
    frames = []
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))
    return SimpleNamespace(
        scene=scene,
        summarizer=summarizer,
        editor=editor,
        request=prompt_request,
        order=order,
        plugin=plugin,
        frames=frames,
    )


def refresh(scene, message):
    return revision_refresh_payload(scene, message)["revision_refresh"]


def assert_ready(scene, message):
    assert message.knowledge.content_digest == content_digest(message.perception_text)
    selected = select_character_view(
        scene, source_reference(scene, "message", message.id), "Bob"
    )
    assert selected.status == "ready"
    assert selected.text == message.perception_text
    assert perception_readiness(scene, message) == "ready"
    assert not refresh(scene, message)["required"]
    assert message.id not in scene.pending_perception_messages


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [NarratorMessage, CharacterMessage])
@pytest.mark.parametrize("mode", ["changed", "unchanged", "off"])
async def test_automatic_final_text_is_ready_without_action_or_next_send(
    flow, kind, mode
):
    t = flow
    original = "Alice: The brass key is on the table."
    if mode == "unchanged":
        original = original.replace("brass", "silver")
    if mode == "off":
        t.editor.actions["revision"].config["automatic_revision"].value = False
    message = kind(message=original)
    await t.scene.push_history(message)
    expected = original if mode == "off" else original.replace("brass", "silver")
    assert message.message == expected
    assert [value for phase, value in t.order if phase == "perception"] == [expected]
    assert t.request.await_count == 1
    assert_ready(t.scene, message)
    await catch_up_revisions(t.scene)
    await t.summarizer.ensure_perceptions(t.scene)
    assert t.request.await_count == 1
    assert message.revision_feature_current("perceptions")


@pytest.mark.asyncio
async def test_regeneration_analyzes_only_final_accepted_version(flow, monkeypatch):
    t = flow
    message = NarratorMessage(
        message="The old key is here.",
        meta={"agent": "narrator", "function": "narrate_environment"},
    )
    await t.scene.push_history(message)
    t.request.reset_mock()
    t.order.clear()
    monkeypatch.setattr(
        get_agent("narrator"),
        "narrate_environment",
        AsyncMock(return_value="The brass key is in the lock."),
    )
    assert await regenerate(t.scene) == [message]
    assert message.message == "The silver key is in the lock."
    assert [value for phase, value in t.order if phase == "perception"] == [
        message.message
    ]
    assert t.request.await_count == 1
    assert_ready(t.scene, message)
    await catch_up_revisions(t.scene)
    assert t.request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["action", "send"])
@pytest.mark.parametrize("kind", [NarratorMessage, CharacterMessage])
async def test_manual_save_retains_text_and_defers_until_action_or_send(
    flow, trigger, kind, monkeypatch
):
    t = flow
    message = kind(message="Alice: The brass key is here.")
    await t.scene.push_history(message)
    t.request.reset_mock()
    rebuild = AsyncMock()
    monkeypatch.setattr(t.summarizer, "rebuild_perceptions", rebuild)
    edited = 'Alice: "The ruby key is in the drawer."'
    await t.plugin.handle_edit({"id": message.id, "text": edited})
    await asyncio.sleep(0)
    assert message.message == edited
    assert message.versions[message.active_version].message == edited
    t.request.assert_not_awaited()
    rebuild.assert_not_awaited()
    assert refresh(t.scene, message)["required"]
    selected = select_character_view(
        t.scene, source_reference(t.scene, "message", message.id), "Bob"
    )
    assert selected.status not in ("ready", "omitted")
    if trigger == "action":
        await (
            await t.plugin.handle_commit_revision(
                {"id": message.id, "index": message.active_version}
            )
        )
    else:
        await catch_up_revisions(t.scene)
    assert t.request.await_count == 1
    assert_ready(t.scene, message)
    await catch_up_revisions(t.scene)
    assert t.request.await_count == 1


@pytest.mark.asyncio
async def test_unchanged_manual_save_does_not_schedule_work(flow, monkeypatch):
    t = flow
    message = NarratorMessage(message="The brass key is here.")
    await t.scene.push_history(message)
    state, knowledge = message.revision_state, message.knowledge
    t.request.reset_mock()
    rebuild = AsyncMock()
    monkeypatch.setattr(t.summarizer, "rebuild_perceptions", rebuild)
    await t.plugin.handle_edit({"id": message.id, "text": message.message})
    rebuild.assert_not_awaited()
    t.request.assert_not_awaited()
    assert message.revision_state is state
    assert message.knowledge is knowledge


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["absent", "failed"])
async def test_action_repairs_actual_missing_results_even_at_baseline(flow, missing):
    t = flow
    message = NarratorMessage(message="The brass key is here.")
    await t.scene.push_history(message)
    message.mark_revision_committed()
    if missing == "absent":
        message.knowledge = None
    else:
        message.knowledge = message.knowledge.invalidated(message.message)
    t.request.reset_mock()
    assert refresh(t.scene, message)["required"]
    await (
        await t.plugin.handle_commit_revision(
            {"id": message.id, "index": message.active_version}
        )
    )
    assert t.request.await_count == 1
    assert_ready(t.scene, message)


@pytest.mark.asyncio
async def test_failed_automatic_analysis_remains_actionable_and_retries_once(flow):
    t = flow
    successful = t.request.side_effect
    t.request.side_effect = GenerationCancelled("analysis canceled")
    message = NarratorMessage(message="The brass key is here.")
    with pytest.raises(GenerationCancelled):
        await t.scene.push_history(message)
    assert message.message == "The silver key is here."
    assert refresh(t.scene, message)["required"]
    assert perception_readiness(t.scene, message) == "failed"
    t.request.side_effect = successful
    await (
        await t.plugin.handle_commit_revision(
            {"id": message.id, "index": message.active_version}
        )
    )
    assert t.request.await_count == 2
    assert_ready(t.scene, message)


@pytest.mark.asyncio
async def test_duplicate_action_and_send_share_selected_text_analysis(flow):
    t = flow
    message = NarratorMessage(message="The brass key is here.")
    await t.scene.push_history(message)
    await t.plugin.handle_edit({"id": message.id, "text": "The ruby key is here."})
    t.request.reset_mock()
    entered, release = asyncio.Event(), asyncio.Event()
    successful = t.request.side_effect

    async def delayed(*args, **kwargs):
        entered.set()
        await asyncio.wait_for(release.wait(), 3)
        return await successful(*args, **kwargs)

    t.request.side_effect = delayed
    payload = {"id": message.id, "index": message.active_version}
    first = await t.plugin.handle_commit_revision(payload)
    await asyncio.wait_for(entered.wait(), 3)
    second = await t.plugin.handle_commit_revision(payload)
    send = asyncio.create_task(catch_up_revisions(t.scene))
    release.set()
    await asyncio.wait_for(asyncio.gather(first, second, send), 3)
    assert t.request.await_count == 1
    assert_ready(t.scene, message)


@pytest.mark.asyncio
async def test_edit_during_automatic_analysis_does_not_analyze_new_selection(flow):
    t = flow
    message = NarratorMessage(message="The brass key is here.")
    entered, release = asyncio.Event(), asyncio.Event()
    successful = t.request.side_effect

    async def delayed(*args, **kwargs):
        entered.set()
        await asyncio.wait_for(release.wait(), 3)
        return await successful(*args, **kwargs)

    t.request.side_effect = delayed
    push = asyncio.create_task(t.scene.push_history(message))
    await asyncio.wait_for(entered.wait(), 3)
    await t.plugin.handle_edit({"id": message.id, "text": "The ruby key is here."})
    release.set()
    with pytest.raises(GenerationCancelled):
        await asyncio.wait_for(push, 3)
    assert t.request.await_count == 1
    assert message.message == "The ruby key is here."
    assert refresh(t.scene, message)["required"]
    assert perception_readiness(t.scene, message) != "ready"
    t.request.side_effect = successful
    await catch_up_revisions(t.scene)
    assert t.request.await_count == 2
    assert_ready(t.scene, message)


@pytest.mark.asyncio
async def test_automatic_baseline_return_restores_results_without_analyzing_original(
    flow,
):
    t = flow
    message = NarratorMessage(message="The brass key is here.")
    await t.scene.push_history(message)
    baseline = message.knowledge.model_dump()
    await t.plugin.handle_swap_revision({"id": message.id, "index": 0})
    assert refresh(t.scene, message)["required"]
    assert perception_readiness(t.scene, message) == "deferred"
    assert t.request.await_count == 1
    await t.plugin.handle_swap_revision({"id": message.id, "index": 1})
    assert message.knowledge.model_dump() == baseline
    assert_ready(t.scene, message)
    assert t.request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_effective_eligibility_does_not_enable_perceptions(flow, mode):
    t = flow
    t.scene.knowledge_eligibility = mode
    message = NarratorMessage(message="The brass key is here.")
    await t.scene.push_history(message)
    assert t.request.await_count == int(mode == "perception")
    await t.plugin.handle_edit({"id": message.id, "text": "The ruby key is here."})
    before = t.request.await_count
    await catch_up_revisions(t.scene)
    assert t.request.await_count - before == int(mode == "perception")


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failed", "cancelled", "unchanged"])
async def test_unrevised_fallback_is_analyzed_once(flow, monkeypatch, outcome):
    t = flow

    async def revise(info):
        if outcome == "failed":
            info.skip_reason = "error"
        elif outcome == "cancelled":
            t.scene.cancel_requested = True
            raise GenerationCancelled("revision canceled")
        return info.text

    monkeypatch.setattr(t.editor, "revision_revise", revise)
    message = NarratorMessage(message="The brass key is here.")
    await t.scene.push_history(message)
    assert message.active_version == 0
    assert message.message == "The brass key is here."
    assert t.request.await_count == 1
    assert_ready(t.scene, message)


@pytest.mark.asyncio
async def test_empty_selected_source_is_registered_before_explicit_analysis(flow):
    t = flow
    message = NarratorMessage(
        message="The brass key is here.", present=["Alice", "Bob"]
    )
    t.scene.history.append(message)
    from talemate.knowledge.perspectives import bind_message_source

    bind_message_source(t.scene, message)
    await t.plugin.handle_edit({"id": message.id, "text": "The ruby key is here."})
    assert message.knowledge is None
    await (await t.plugin.handle_commit_revision({"id": message.id, "index": 0}))
    assert t.request.await_count == 1
    assert_ready(t.scene, message)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["delete", "scene", "eligibility"])
async def test_obsolete_automatic_analysis_cannot_publish_completion(flow, mutation):
    t = flow
    message = NarratorMessage(message="The brass key is here.")
    entered, release = asyncio.Event(), asyncio.Event()
    successful = t.request.side_effect

    async def delayed(*args, **kwargs):
        entered.set()
        await asyncio.wait_for(release.wait(), 3)
        return await successful(*args, **kwargs)

    t.request.side_effect = delayed
    push = asyncio.create_task(t.scene.push_history(message))
    await asyncio.wait_for(entered.wait(), 3)
    if mutation == "delete":
        t.scene.delete_message(message.id)
    elif mutation == "scene":
        t.summarizer.scene = None
    else:
        t.scene.knowledge_eligibility = "legacy"
    release.set()
    with pytest.raises(GenerationCancelled):
        await asyncio.wait_for(push, 3)
    assert t.request.await_count == 1
    assert not message.revision_matches_baseline
    assert message.knowledge is None or all(
        v.status != "ready" for v in message.knowledge.views
    )


@pytest.mark.asyncio
async def test_current_source_views_do_not_certify_failed_dependent_phase(
    flow, monkeypatch
):
    t = flow
    message = NarratorMessage(message="The brass key is here.")
    await t.scene.push_history(message)
    message.knowledge = None
    repairs = AsyncMock(side_effect=RuntimeError("dependent summary failed"))
    monkeypatch.setattr(t.summarizer, "repair_summary_views", repairs)
    payload = {"id": message.id, "index": message.active_version}
    with pytest.raises(RuntimeError, match="dependent summary failed"):
        await (await t.plugin.handle_commit_revision(payload))
    assert message.knowledge.views[0].status == "ready"
    assert refresh(t.scene, message)["required"]
    before = t.request.await_count
    repairs.side_effect = None
    await (await t.plugin.handle_commit_revision(payload))
    assert t.request.await_count == before
    assert repairs.await_count == 2
    assert_ready(t.scene, message)


@pytest.mark.asyncio
async def test_manual_save_after_auto_job_does_not_get_analyzed_by_finalizer(
    flow, monkeypatch
):
    from talemate.knowledge import revision_refresh

    t = flow
    original_refresh = revision_refresh.refresh_revision

    async def edit_after_refresh(scene, message):
        result = await original_refresh(scene, message)
        await t.plugin.handle_edit({"id": message.id, "text": "The ruby key is here."})
        return result

    monkeypatch.setattr(revision_refresh, "refresh_revision", edit_after_refresh)
    message = NarratorMessage(message="The brass key is here.")
    with pytest.raises(GenerationCancelled):
        await t.scene.push_history(message)
    assert message.message == "The ruby key is here."
    assert t.request.await_count == 1
    assert refresh(t.scene, message)["required"]
