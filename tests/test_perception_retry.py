import asyncio

import pytest

import test_perception_lifecycle
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.revision_browsing import defer_revision_work
from talemate.scene_message import CharacterMessage
from talemate.world_state import Reinforcement

setup = test_perception_lifecycle.setup
result = test_perception_lifecycle.result
answer = test_perception_lifecycle.answer


@pytest.fixture
def retry_flow(setup, monkeypatch):
    scene, summarizer, request = setup
    warnings = []
    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.emit",
        lambda event, **data: warnings.append(data)
        if event == "status" and data.get("status") == "warning"
        else None,
    )
    return scene, summarizer, request, warnings


def revise_before_analysis(scene):
    async def revise(event):
        event.messages[0].message = "Alice: Hello, Bob."

    scene.signals["push_history"].connect(revise)


@pytest.mark.asyncio
@pytest.mark.parametrize("backlog", ["passages", "tracked-state"])
async def test_own_analysis_progress_does_not_warn(retry_flow, backlog):
    scene, summarizer, request, warnings = retry_flow
    revise_before_analysis(scene)
    if backlog == "passages":
        scene.history.extend(
            CharacterMessage(message=f"Alice: Earlier line {index}.")
            for index in range(2)
        )
        summarizer._register_perception_sources(scene, scene.history)
    else:
        scene.world_state.reinforce.append(
            Reinforcement(
                question="Condition", character="Bob", answer="Awake.", insert="never"
            )
        )
    message = CharacterMessage(message="Alice: Draft.")

    await asyncio.wait_for(scene.push_history(message), 5)

    assert request.await_count == (3 if backlog == "passages" else 2)
    assert warnings == []
    assert message.revision_state.status == "clean"


@pytest.mark.asyncio
@pytest.mark.parametrize("revised", [False, True])
@pytest.mark.parametrize("changes", [0, 1, 3])
async def test_input_changes_retry_until_stable_without_extra_stable_request(
    retry_flow, revised, changes
):
    scene, summarizer, request, warnings = retry_flow
    if revised:
        revise_before_analysis(scene)
    seen = []

    async def analyze(*args, **kwargs):
        seen.append(kwargs["vars"]["context"]["cast"][1]["authored_description"])
        if request.await_count <= changes:
            scene.character_data[
                "Bob"
            ].description = f"Description {request.await_count}"
            return result(answer("Stale.", "Stale."))
        return result()

    request.side_effect = analyze
    message = CharacterMessage(message="Alice: Draft.")
    await asyncio.wait_for(scene.push_history(message), 5)

    assert request.await_count == changes + 1
    assert len(warnings) == changes
    assert all(
        "regenerating perception analysis" in warning["message"] for warning in warnings
    )
    assert all(
        view.status == "ready" and view.text != "Stale."
        for view in message.knowledge.views
    )
    assert message.revision_state.status == "clean"
    assert message.revision_matches_baseline
    assert seen == ["", *(f"Description {index}" for index in range(1, changes + 1))]
    await summarizer.ensure_perceptions(scene)
    assert request.await_count == changes + 1


@pytest.mark.asyncio
async def test_inputs_changed_during_summary_repair_reanalyze_ready_source(
    retry_flow, monkeypatch
):
    scene, summarizer, request, warnings = retry_flow
    revise_before_analysis(scene)
    repairs = 0

    async def repair(*args, **kwargs):
        nonlocal repairs
        repairs += 1
        if repairs == 1:
            scene.character_data["Bob"].description = "Bob is asleep."
        await asyncio.sleep(0)

    monkeypatch.setattr(summarizer, "repair_summary_views", repair)
    request.side_effect = [result(answer("Old.", "Old.")), result(answer(bob=None))]
    message = CharacterMessage(message="Alice: Draft.")
    await asyncio.wait_for(scene.push_history(message), 5)

    assert request.await_count == repairs == 2
    assert message.knowledge.views[1].status == "omitted"
    assert len(warnings) == 1
    assert message.revision_state.status == "clean"


@pytest.mark.asyncio
@pytest.mark.parametrize("revised", [False, True])
@pytest.mark.parametrize("consumed", [False, True])
async def test_user_cancel_during_stale_response_stops_retry(
    retry_flow, revised, consumed
):
    scene, _, request, warnings = retry_flow
    if revised:
        revise_before_analysis(scene)

    async def analyze(*args, **kwargs):
        scene.character_data["Bob"].description = "Changed."
        scene.interrupt()
        if consumed:
            scene.cancel_requested = False
        return result()

    request.side_effect = analyze
    with pytest.raises(GenerationCancelled) as cancelled:
        await asyncio.wait_for(
            scene.push_history(CharacterMessage(message="Alice: Draft.")), 5
        )
    assert cancelled.value.by_user
    assert request.await_count == 1
    assert warnings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["selection", "deleted", "scene"])
async def test_ownership_changes_do_not_retry_or_warn(retry_flow, change):
    scene, summarizer, request, warnings = retry_flow
    revise_before_analysis(scene)
    message = CharacterMessage(message="Alice: Draft.")

    async def analyze(*args, **kwargs):
        if change == "selection":
            with defer_revision_work():
                scene.edit_message(message.id, "Alice: A manually selected line.")
        elif change == "deleted":
            scene.delete_message(message.id)
        else:
            summarizer.scene = None
        return result()

    request.side_effect = analyze
    with pytest.raises(GenerationCancelled):
        await asyncio.wait_for(scene.push_history(message), 5)
    assert request.await_count == 1
    assert warnings == []
    if change == "selection":
        assert message.message == "Alice: A manually selected line."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [GenerationCancelled("User cancelled", by_user=True), asyncio.CancelledError()],
)
async def test_provider_cancellation_is_never_retried(retry_flow, error):
    scene, _, request, warnings = retry_flow
    revise_before_analysis(scene)
    request.side_effect = error
    with pytest.raises(type(error)):
        await asyncio.wait_for(
            scene.push_history(CharacterMessage(message="Alice: Draft.")), 5
        )
    assert request.await_count == 1
    assert warnings == []


@pytest.mark.asyncio
async def test_cancel_after_stale_attempt_stops_existing_waiter(retry_flow):
    scene, summarizer, request, warnings = retry_flow
    started, release = asyncio.Event(), asyncio.Event()

    async def analyze(*args, **kwargs):
        started.set()
        await asyncio.wait_for(release.wait(), 3)
        scene.character_data["Bob"].description = "Changed."
        scene.interrupt()
        return result()

    request.side_effect = analyze
    task = asyncio.create_task(
        scene.push_history(CharacterMessage(message="Alice: Hello."))
    )
    waiter = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        waiter = asyncio.create_task(summarizer.ensure_perceptions(scene))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(task, waiter, return_exceptions=True), 5
        )
        assert all(
            isinstance(error, GenerationCancelled) and error.by_user
            for error in results
        )
        assert request.await_count == 1
        assert warnings == []
    finally:
        release.set()
        for pending in (task, waiter):
            if pending is not None and not pending.done():
                pending.cancel()
        await asyncio.gather(
            *(pending for pending in (task, waiter) if pending is not None),
            return_exceptions=True,
        )
