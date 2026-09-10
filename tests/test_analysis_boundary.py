from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock
from unittest.mock import Mock
import pytest
import test_actor_perspective_history
from talemate.agents.context import ActiveAgent
from talemate.agents.conversation import ConversationAgentEmission
from talemate.context import RegenerationContext
from talemate.instance import get_agent
from talemate.knowledge.perspectives import (
    perspectives_changed,
    set_source_perspectives,
)
from talemate.regenerate import regenerate
from talemate.scene_message import CharacterMessage
from talemate.knowledge.perspectives import add_disclosure
from talemate.knowledge.schema import Fact

cast = test_actor_perspective_history.cast


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [False, True])
async def test_analysis_waits_for_existing_snapshot_before_capturing_evidence(
    cast, monkeypatch, direct
):
    from talemate.knowledge.perspectives import source_reference, select_character_view
    from talemate.knowledge.snapshot_models import SnapshotPerspectives
    from talemate.knowledge.snapshots import snapshot_digest

    scene, message = cast
    summarizer = get_agent("summarizer")
    world_state = get_agent("world_state")
    summarizer.actions["analyze_scene"].enabled = True
    bob = scene.get_character("Bob")
    release = asyncio.Event()
    waiting = asyncio.Event()
    statuses = []

    def status(typ, **data):
        statuses.append(data)
        if data.get("status") == "busy":
            waiting.set()

    monkeypatch.setattr("talemate.status.emit", status)
    monkeypatch.setattr(summarizer, "emit_message", AsyncMock())

    async def update(**kwargs):
        await release.wait()
        source = select_character_view(
            scene, source_reference(scene, "message", message.id), bob.name
        ).source
        scene.world_state.location = "The harbor"
        scene.world_state.location_perspectives = SnapshotPerspectives(
            content_digest=snapshot_digest("location", "The harbor"),
            views=[
                {
                    "audience": [bob.name],
                    "status": "ready",
                    "text": "The harbor",
                    "sources": [source],
                }
            ],
        )

    update = AsyncMock(side_effect=update)
    monkeypatch.setattr(type(scene.world_state), "request_update", update)
    request = AsyncMock(return_value=("", {"analysis": "Ask about the harbor."}))
    monkeypatch.setattr("talemate.prompts.Prompt.request", request)
    await world_state.dispatch_world_state_update()
    emission = ConversationAgentEmission(
        agent=get_agent("conversation"), character=bob, response=""
    )
    with ActiveAgent(
        get_agent("conversation"),
        test_analysis_waits_for_existing_snapshot_before_capturing_evidence,
    ):
        task = asyncio.create_task(
            summarizer.analyze_scene_for_next_action("conversation", bob)
            if direct
            else summarizer.on_inject_instructions(emission)
        )
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            assert not task.done()
            request.assert_not_awaited()
            assert (
                statuses[0]["message"]
                == "Waiting for knowledge updates before scene analysis"
            )
            release.set()
            await asyncio.wait_for(task, 5)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    update.assert_awaited_once()
    request.assert_awaited_once()
    assert (
        request.call_args.kwargs["vars"]["evidence"]["snapshot"]["location"]
        == "The harbor"
    )
    assert statuses[-1]["status"] == "idle"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback_name",
    ["before_deep_analysis", "after_deep_analysis", "after", "retrieval"],
)
@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_valid_analysis_survives_downstream_callback_abort(
    cast, monkeypatch, callback_name, mode
):
    from talemate.emit.async_signals import get
    from talemate.exceptions import GenerationCancelled

    scene, _ = cast
    scene.knowledge_eligibility = mode
    summarizer = get_agent("summarizer")
    conversation = get_agent("conversation")
    bob = scene.get_character("Bob")
    summarizer.actions["analyze_scene"].enabled = True
    summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
    summarizer.actions["use_long_term_memory"].enabled = True
    request = AsyncMock(
        return_value=(
            "",
            {"analysis": "Ask about the harbor.", "investigate": "Earlier events"},
        )
    )
    monkeypatch.setattr("talemate.prompts.Prompt.request", request)
    monkeypatch.setattr(
        summarizer, "rag_build", AsyncMock(return_value=["Old harbor events."])
    )
    monkeypatch.setattr(summarizer, "rag_build_for_author", summarizer.rag_build)
    monkeypatch.setattr(summarizer, "emit_message", AsyncMock())

    async def abort(emission):
        raise GenerationCancelled("Downstream operation stopped")

    signal = (
        get("agent.summarization.scene_analysis." + callback_name)
        if callback_name != "retrieval"
        else None
    )
    if signal:
        signal.connect(abort)
    else:
        summarizer.rag_build.side_effect = [
            GenerationCancelled("Downstream retrieval cancelled", by_user=True),
            ["Old harbor events."],
        ]
    with ActiveAgent(
        conversation, test_valid_analysis_survives_downstream_callback_abort
    ):
        emission = ConversationAgentEmission(
            agent=conversation, character=bob, response=""
        )
        with pytest.raises(GenerationCancelled, match="Downstream"):
            await summarizer.on_inject_instructions(emission)
        assert (
            await summarizer.get_cached_analysis("conversation", bob)
            == "Ask about the harbor."
        )
        if signal:
            signal.disconnect(abort)
        await summarizer.on_inject_instructions(emission)
        assert any(
            item.content == "Ask about the harbor."
            for item in emission.dynamic_instructions
        )
        assert any(
            item.title == "Deep Analysis Context"
            and item.content == "Old harbor events."
            for item in emission.dynamic_instructions
        )
    request.assert_awaited_once()
    assert summarizer.rag_build.await_count == (
        2 if callback_name in ("retrieval", "after_deep_analysis") else 1
    )


@pytest.fixture
async def analysis_turn(cast, monkeypatch, request):
    scene, earlier = cast
    mode, deep = (
        request.param if isinstance(request.param, tuple) else (request.param, False)
    )
    scene.knowledge_eligibility = mode
    conversation, summarizer, memory = [
        get_agent(n) for n in ("conversation", "summarizer", "memory")
    ]
    summarizer.actions["analyze_scene"].enabled = True
    summarizer.actions["analyze_scene"].config["deep_analysis"].value = deep
    calls = AsyncMock(
        return_value=(
            "",
            {
                "analysis": "Ask about the harbor.",
                "investigate": "Earlier events" if deep else "",
            },
        )
    )
    monkeypatch.setattr(
        summarizer, "rag_build", AsyncMock(return_value=["Earlier harbor events."])
    )
    monkeypatch.setattr("talemate.prompts.Prompt.request", calls)
    monkeypatch.setattr(summarizer, "emit_message", AsyncMock())
    monkeypatch.setattr(
        get_agent("editor"), "maybe_revise_inplace", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(conversation, "finalize_message_avatar", AsyncMock())
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    perspectives_changed.connect(memory._audiences_changed, sender=scene)

    async def finalize(scene, messages):
        if scene.knowledge_eligibility == "perception":
            for message in messages:
                set_source_perspectives(
                    scene,
                    "message",
                    message.id,
                    [
                        {
                            "audience": list(scene.active_characters),
                            "status": "ready",
                            "text": message.message,
                        }
                    ],
                )

    monkeypatch.setattr(summarizer, "finalize_perceptions", finalize)
    count = 0

    async def converse(actor, instruction=None):
        nonlocal count
        count += 1
        with ActiveAgent(conversation, converse):
            emission = ConversationAgentEmission(
                agent=conversation, character=actor.character, response=""
            )
            await summarizer.on_inject_instructions(emission)
        return [CharacterMessage(message=f"Bob: Reply {count}.")]

    monkeypatch.setattr(conversation, "converse", converse)
    message = (await converse(scene.get_character("Bob").actor))[0]
    await scene.push_history(message)
    try:
        yield SimpleNamespace(
            scene=scene,
            earlier=earlier,
            message=message,
            calls=calls,
            summarizer=summarizer,
            converse=converse,
        )
    finally:
        perspectives_changed.disconnect(memory._audiences_changed, sender=scene)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "analysis_turn", ["legacy", "perception", ("perception", True)], indirect=True
)
@pytest.mark.parametrize("action", ["regenerate", "directed", "swap"])
async def test_reply_changes_reuse_analysis(analysis_turn, action):
    t = analysis_turn
    assert t.calls.await_count == 1
    if action == "swap":
        t.scene.append_message_version(
            t.message.id, "Bob: Another reply.", source="regenerate"
        )
        t.scene.set_message_active_version(t.message.id, 0)
    with RegenerationContext(
        t.scene, direction="Speak tersely." if action == "directed" else None
    ):
        assert await regenerate(t.scene)
    assert t.calls.await_count == 1
    if t.summarizer.deep_analysis:
        t.summarizer.rag_build.assert_awaited_once()
        assert (
            t.summarizer.get_scene_state("deep_analysis_context")
            == "Earlier harbor events."
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_turn", ["perception"], indirect=True)
@pytest.mark.parametrize(
    "change",
    ["earlier_edit", "new_player_line", "disclosure", "fact", "authored", "budget"],
)
async def test_changed_analysis_inputs_make_one_new_request(
    analysis_turn, change, monkeypatch
):
    t = analysis_turn
    if change == "earlier_edit":
        t.scene.edit_message(t.earlier.id, "Alice: The harbor is closed.")
        set_source_perspectives(
            t.scene,
            "message",
            t.earlier.id,
            [
                {
                    "audience": ["Bob"],
                    "status": "ready",
                    "text": "Alice says the harbor is closed.",
                }
            ],
        )
    elif change == "disclosure":
        add_disclosure(t.scene, "The harbor is closed.", ["Bob"])
    elif change == "fact":
        t.scene.world_state.facts["F900"] = Fact(
            id="F900", text="The harbor is closed."
        )
    elif change == "authored":
        t.scene.get_character("Bob").description = "A harbor watchman."
    elif change == "budget":
        monkeypatch.setattr(
            type(t.summarizer.client), "max_token_length", property(lambda _: 8192)
        )
    elif change == "new_player_line":
        await t.scene.push_history(
            CharacterMessage(message="Alice: Is the harbor closed?", source="player")
        )
        await t.converse(t.scene.get_character("Bob").actor)
        assert t.calls.await_count == 2
        return
    assert await regenerate(t.scene)
    assert t.calls.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_turn", ["perception"], indirect=True)
async def test_reply_and_index_changes_stay_outside_saved_boundary(analysis_turn):
    from talemate.knowledge.advice import advice_fingerprint

    t = analysis_turn
    record = t.summarizer.get_scene_state("cached_analysis_conversation")
    bob = t.scene.get_character("Bob")

    def fingerprint():
        return advice_fingerprint(
            t.scene,
            bob,
            boundary=record["evidence_boundary"],
            budget=record["evidence_budget"],
        )

    assert fingerprint() == record["evidence_fp"]
    t.scene.append_message_version(
        t.message.id, "Bob: The reply changes.", source="regenerate"
    )
    get_agent("memory").invalidate_audience_index(t.scene, reconcile=True)
    # Reader-only snapshot fields and scene clock are absent from this audience's prompt.
    t.scene.world_state.location = "A reader-only location."
    t.scene.ts += 100
    assert fingerprint() == record["evidence_fp"]
    assert await regenerate(t.scene)
    assert t.calls.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_turn", ["perception"], indirect=True)
async def test_concurrent_new_line_still_cancels_analysis(analysis_turn):
    from talemate.exceptions import GenerationCancelled

    t = analysis_turn
    t.summarizer.actions["analyze_scene"].config["cache_analysis"].value = False

    async def changed(*args, **kwargs):
        t.scene.history.append(
            CharacterMessage(message="Alice: New information.", source="player")
        )
        return "", {"analysis": "Outdated advice."}

    t.calls.side_effect = changed
    with pytest.raises(GenerationCancelled, match="evidence changed"):
        await t.converse(t.scene.get_character("Bob").actor)
    assert t.calls.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_turn", ["perception"], indirect=True)
async def test_cached_turn_shares_projection_until_the_await_boundary(
    analysis_turn, monkeypatch
):
    import talemate.knowledge.advice as advice

    t = analysis_turn
    project = Mock(wraps=advice.analysis_evidence_fingerprint)
    monkeypatch.setattr(advice, "analysis_evidence_fingerprint", project)
    assert await regenerate(t.scene)
    assert t.calls.await_count == 1
    # One capture shared with the cache lookup; one fresh check after cached callbacks.
    assert project.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_turn", [("perception", True)], indirect=True)
@pytest.mark.parametrize("has_context", [False, True])
async def test_cached_deep_analysis_walks_only_for_nonempty_injection(
    analysis_turn, monkeypatch, has_context
):
    from talemate.agents.summarize import analyze_scene

    t = analysis_turn
    if not has_context:
        t.summarizer.set_scene_states(deep_analysis_context="")
    fingerprint = Mock(wraps=analyze_scene.deep_analysis_fingerprint)
    monkeypatch.setattr(analyze_scene, "deep_analysis_fingerprint", fingerprint)
    await t.summarizer.get_cached_analysis("conversation", t.scene.get_character("Bob"))
    fingerprint.assert_not_called()
    assert await regenerate(t.scene)
    assert t.calls.await_count == 1
    assert fingerprint.call_count == int(has_context)


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_turn", [("perception", True)], indirect=True)
async def test_no_investigation_skips_retrieval_fingerprint(analysis_turn, monkeypatch):
    from talemate.agents.summarize import analyze_scene

    t = analysis_turn
    t.summarizer.actions["analyze_scene"].config["cache_analysis"].value = False
    t.calls.return_value = "", {"analysis": "Stay here."}
    fingerprint = Mock(wraps=analyze_scene.deep_analysis_fingerprint)
    monkeypatch.setattr(analyze_scene, "deep_analysis_fingerprint", fingerprint)
    assert await regenerate(t.scene)
    assert t.calls.await_count == 2
    fingerprint.assert_not_called()
    assert not t.summarizer.get_scene_state("deep_analysis_context")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate_during_retrieval", [False, True])
async def test_deep_analysis_checks_summary_outside_initial_evidence(
    cast, monkeypatch, mutate_during_retrieval
):
    from talemate.knowledge.advice import (
        advice_context,
        advice_fingerprint,
        StaleAdvice,
    )
    from talemate.knowledge.memory import audience_documents

    scene, _ = cast
    summarizer = get_agent("summarizer")
    conversation = get_agent("conversation")
    bob = scene.get_character("Bob")
    summarizer.actions["analyze_scene"].enabled = True
    summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
    summarizer.actions["use_long_term_memory"].enabled = True
    monkeypatch.setattr(
        type(summarizer.client), "max_token_length", property(lambda _: 2048)
    )
    scene.archived_history = [
        {"id": "old", "text": "Reader summary.", "start": 0, "end": 0, "ts": 0}
    ]

    def summary(text):
        set_source_perspectives(
            scene,
            "summary",
            "old",
            [{"audience": ["Bob"], "status": "ready", "text": text}],
        )

    summary("The old chapter says the harbor is open.")
    for i in range(10):
        message = CharacterMessage(
            message=f"Alice: Recent topic {i}. " + "wind and rain " * 30
        )
        scene.history.append(message)
        set_source_perspectives(
            scene,
            "message",
            message.id,
            [{"audience": ["Bob"], "status": "ready", "text": message.message}],
        )
    assert "old chapter" not in str(advice_context(scene, bob, 1024))
    assert any("old chapter" in d["text"] for d in audience_documents(scene).values())
    request = AsyncMock(
        return_value=(
            "",
            {
                "analysis": "Ask about the harbor.",
                "investigate": "Read the old chapter.",
            },
        )
    )
    monkeypatch.setattr("talemate.prompts.Prompt.request", request)
    monkeypatch.setattr(summarizer, "emit_message", AsyncMock())

    async def retrieve(**kwargs):
        if mutate_during_retrieval:
            summary("The old chapter says the harbor is closed.")
        return ["The harbor is open."]

    monkeypatch.setattr(summarizer, "rag_build", AsyncMock(side_effect=retrieve))
    with ActiveAgent(
        conversation, test_deep_analysis_checks_summary_outside_initial_evidence
    ):
        emission = ConversationAgentEmission(
            agent=conversation, character=bob, response=""
        )
        if mutate_during_retrieval:
            with pytest.raises(StaleAdvice, match="Deep analysis sources changed"):
                await summarizer.on_inject_instructions(emission)
            assert not emission.dynamic_instructions
            mutate_during_retrieval = False
            await summarizer.on_inject_instructions(emission)
            assert any(
                item.title == "Deep Analysis Context"
                for item in emission.dynamic_instructions
            )
            request.assert_awaited_once()
            assert summarizer.rag_build.await_count == 2
            return
        await summarizer.on_inject_instructions(emission)
        assert any(
            item.title == "Deep Analysis Context"
            for item in emission.dynamic_instructions
        )
        record = summarizer.get_scene_state("cached_analysis_conversation")
        summary("The old chapter says the harbor is closed.")
        assert (
            advice_fingerprint(
                scene,
                bob,
                boundary=record["evidence_boundary"],
                budget=record["evidence_budget"],
            )
            == record["evidence_fp"]
        )
        emission.dynamic_instructions.clear()
        summarizer._inject_deep_analysis_context(emission)
        assert not emission.dynamic_instructions
        assert (
            await summarizer.get_cached_analysis("conversation", bob)
            == record["guidance"]
        )
        await summarizer.on_inject_instructions(emission)
        assert [item.title for item in emission.dynamic_instructions] == [
            "Scene Analysis"
        ]
        request.assert_awaited_once()
        summarizer.rag_build.assert_awaited_once()


@pytest.mark.asyncio
async def test_analysis_waits_for_summarizer_passes_before_capturing_evidence(
    cast, monkeypatch
):
    from talemate.knowledge.advice import analysis_evidence_fingerprint

    scene, message = cast
    summarizer = get_agent("summarizer")
    conversation = get_agent("conversation")
    bob = scene.get_character("Bob")
    summarizer.actions["analyze_scene"].enabled = True
    summarizer.actions["archive"].config["extract_facts"].value = False
    scene.archived_history = [
        {"id": "archive", "text": "Reader summary", "start": 0, "end": 0, "ts": 0}
    ]
    entered = asyncio.Event()
    release = asyncio.Event()
    waiting = asyncio.Event()

    def status(typ, **data):
        if data.get("message") == "Waiting for knowledge updates before scene analysis":
            waiting.set()

    async def summarize(text, **kwargs):
        entered.set()
        await release.wait()
        return "The rain stopped earlier."

    summary_request = AsyncMock(side_effect=summarize)
    analysis_request = AsyncMock(return_value=("", {"analysis": "Ask about the rain."}))
    monkeypatch.setattr("talemate.status.emit", status)
    monkeypatch.setattr(summarizer, "summarize", summary_request)
    monkeypatch.setattr(summarizer, "schedule_audience_summaries", AsyncMock())
    monkeypatch.setattr(summarizer, "emit_message", AsyncMock())
    monkeypatch.setattr("talemate.prompts.Prompt.request", analysis_request)
    writer = asyncio.create_task(summarizer.ensure_summary_views(scene, "archive"))
    analysis = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        boundary, budget = summarizer._analysis_evidence_key(scene, bob, "conversation")
        before = analysis_evidence_fingerprint(scene, bob, boundary, budget)
        with ActiveAgent(
            conversation,
            test_analysis_waits_for_summarizer_passes_before_capturing_evidence,
        ):
            emission = ConversationAgentEmission(
                agent=conversation, character=bob, response=""
            )
            analysis = asyncio.create_task(summarizer.on_inject_instructions(emission))
            await asyncio.wait_for(waiting.wait(), 2)
            analysis_request.assert_not_awaited()
            release.set()
            await asyncio.wait_for(analysis, 5)
        assert analysis_evidence_fingerprint(scene, bob, boundary, budget) != before
        assert summary_request.await_count == 2  # Alice, then Bob and Cara.
        analysis_request.assert_awaited_once()
        assert any(
            item.content == "Ask about the rain."
            for item in emission.dynamic_instructions
        )
    finally:
        release.set()
        await asyncio.gather(
            writer, *([analysis] if analysis else []), return_exceptions=True
        )
