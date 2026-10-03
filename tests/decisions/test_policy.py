import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.context import ActiveScene
from talemate.decisions import (
    ActionBudget,
    FailureCode,
    PolicyAction,
    ProviderCapabilities,
    ProviderResponse,
)
from talemate.exceptions import (
    AbortCommand,
    AbortWaitForInput,
    ExitScene,
    GenerationCancelled,
    ResetScene,
    RestartSceneLoop,
)
from talemate.prompts.base import PrependTemplateDirectories, Prompt


ASK = '{% set answers = ask("test", state=passage, questions={"repeats": yes_no("Repeat?", threshold=0.5)}) %}'
ASK_OTHER = ASK.replace("set answers =", "set other =")
REVISE = "revise([])"


async def test_spec_example_uses_real_render_and_async_action_once(
    policy_factory, provider
):
    p = policy_factory
    invocation = p.create()
    assert await invocation.run() == "rewritten"
    assert invocation.result == "rewritten"
    assert await invocation.run() == "rewritten"
    assert "completed" in str(invocation)
    assert len(provider.calls) == 1
    p.editor.revision_rewrite.assert_awaited_once_with(
        info=invocation.prompt.vars["info"],
        decision_findings=[
            {
                "passage_id": "s1",
                "kind": "repetition",
                "text": "original",
                "instructions": "Remove the repeated story beat.",
            }
        ],
    )
    p.fallback.assert_not_awaited()
    p.generative.assert_not_awaited()
    entry = next(iter(p.service.log.records.values()))
    assert entry.status == "completed"
    assert entry.actions[0].status == "completed"
    assert entry.actions[0].arguments["info"] == {"text": "original"}
    assert entry.actions[0].result == "rewritten"
    assert entry.elapsed_ms is not None and entry.actions[0].elapsed_ms is not None
    assert "changed" not in str(entry.actions[0])


async def test_empty_render_has_explicit_once_guard(policy_factory, provider):
    p = policy_factory
    source = ASK.replace("%}", "-%}") + "{{- keep() -}}"
    invocation = p.create(source, original_result="value")
    with pytest.raises(RuntimeError):
        _ = invocation.result
    assert await invocation.run() == "value"
    assert invocation.rendered_text == ""
    assert invocation.result == "value"
    assert await invocation.run() == "value"
    str(invocation)
    assert len(provider.calls) == 1
    second = p.create(original_result="value")
    assert await second.run() == "value"
    assert len(provider.calls) == 2
    assert second.id != invocation.id


async def test_no_action_threshold_reason_is_template_owned(policy_factory, provider):
    p = policy_factory
    provider.answers["repeats"]["p_true"] = 0.74
    assert await p.create().run() == "original"
    p.editor.revision_rewrite.assert_not_awaited()
    record = next(iter(p.service.log.records.values()))
    assert record.outcomes == [
        {
            "action": "no_action",
            "reason": "below_threshold",
            "details": {"threshold": 0.8},
        }
    ]
    p.editor.threshold = 0.70
    assert await p.create().run() == "rewritten"
    p.editor.revision_rewrite.assert_awaited_once()


async def test_source_inspection_editing_and_override_do_not_execute(
    policy_factory, provider
):
    p = policy_factory
    invocation = p.create()
    source = Prompt.load_template_source("editor", "policy")
    assert "Does this passage repeat" in source
    assert not provider.calls
    assert invocation.status == "new"
    replacement = ASK.replace("Repeat?", "Is this surprising?") + "{{ keep() }}"
    (p.directory / "policy.jinja2").write_text(replacement)
    assert Prompt.load_template_source("editor", "policy") == replacement
    assert not provider.calls
    p.editor.revision_rewrite.assert_not_awaited()
    assert await invocation.run() == "original"
    p.editor.revision_rewrite.assert_not_awaited()
    assert provider.calls[0].questions["repeats"].instructions == "Is this surprising?"


async def test_missing_explanation_stays_unspecified(policy_factory):
    p = policy_factory
    assert await p.create(ASK + "{{ keep() }}").run() == "original"
    record = next(iter(p.service.log.records.values()))
    assert record.outcomes == []
    assert not record.actions


@pytest.mark.parametrize(
    "mode,code",
    [
        ("transport", FailureCode.TRANSPORT),
        ("oversize", FailureCode.OVERSIZE),
        ("timeout", FailureCode.TIMEOUT),
        ("missing", FailureCode.INVALID_RESPONSE),
        ("extra", FailureCode.INVALID_RESPONSE),
        ("malformed", FailureCode.INVALID_RESPONSE),
        ("refused", FailureCode.REFUSED),
    ],
)
async def test_failure_runs_disabled_path_once_before_any_dependent_action(
    policy_factory, provider, mode, code
):
    p = policy_factory
    if mode == "transport":
        provider.handler = AsyncMock(side_effect=RuntimeError("private error detail"))
    elif mode == "oversize":
        provider.capabilities = ProviderCapabilities(max_input_tokens=1)
    elif mode == "timeout":
        p.service.timeout_seconds = 0.01
        provider.handler = lambda request: asyncio.Event().wait()
    elif mode == "missing":
        provider.answers = {}
    elif mode == "extra":
        provider.answers["extra"] = {"type": "noul", "p_true": 0.9}
    elif mode == "malformed":
        provider.answers["repeats"]["p_true"] = 8
    else:
        provider.handler = AsyncMock(
            return_value=ProviderResponse(answers={}, response_body={}, refused=True)
        )
    invocation = p.create()
    assert await asyncio.wait_for(invocation.run(), 1) == "disabled result"
    assert await invocation.run() == "disabled result"
    p.fallback.assert_awaited_once()
    p.editor.revision_rewrite.assert_not_awaited()
    assert p.service.enabled
    entry = next(iter(p.service.log.records.values()))
    assert entry.failure.code == code
    assert entry.answers is None
    assert entry.actions[0].action == "disabled_path"
    assert entry.actions[0].status == "completed"
    assert "private error detail" not in str(p.service.log.snapshot())


@pytest.mark.parametrize(
    "source,code",
    [
        ("{{ undefined_value }}", FailureCode.TEMPLATE),
        ("{% broken %}", FailureCode.TEMPLATE),
        ("empty", FailureCode.RESULT),
        ("{{ keep() }}{{ keep() }}", FailureCode.RESULT),
        ("{{ revise() }}", FailureCode.TEMPLATE),
        ("{{ unknown_action([]) }}", FailureCode.TEMPLATE),
    ],
)
async def test_template_and_result_failure_before_action_uses_fallback(
    policy_factory, source, code
):
    p = policy_factory
    assert await p.create(source).run() == "disabled result"
    p.fallback.assert_awaited_once()
    entry = next(iter(p.service.log.records.values()))
    assert entry.failure.code == code
    assert not entry.dispatched


async def test_failed_and_disabled_continuations_are_identical(
    policy_factory, provider
):
    p = policy_factory
    p.service.enabled = False
    disabled = await p.create().run()
    assert not provider.calls
    p.service.enabled = True
    provider.handler = AsyncMock(side_effect=RuntimeError("transport"))
    failed = await p.create().run()
    assert disabled == failed == "disabled result"
    assert p.fallback.await_count == 2
    assert p.service.enabled


@pytest.mark.parametrize(
    "suffix",
    [
        "{{ keep() }}",
        "{{ missing }}",
        "{{ " + REVISE + " }}",
    ],
)
async def test_no_recovery_action_after_first_dispatch(policy_factory, suffix):
    p = policy_factory
    invocation = p.create(ASK + "{{ " + REVISE + " }}" + suffix)
    assert await invocation.run() == "original"
    p.editor.revision_rewrite.assert_awaited_once()
    p.fallback.assert_not_awaited()
    assert invocation.status == "preserved"
    entry = next(iter(p.service.log.records.values()))
    if len(entry.actions) == 2:
        assert entry.actions[1].status == "skipped"
        assert entry.actions[1].failure.code == FailureCode.BUDGET


async def test_action_failure_is_logged_without_second_rewrite(policy_factory):
    p = policy_factory
    p.editor.revision_rewrite.side_effect = RuntimeError("private agent configuration")
    assert await p.create().run() == "original"
    p.editor.revision_rewrite.assert_awaited_once()
    p.fallback.assert_not_awaited()
    entry = next(iter(p.service.log.records.values()))
    assert entry.status == "completed"
    assert entry.actions[0].status == "failed"
    assert entry.actions[0].failure.code == FailureCode.ACTION
    assert "private agent configuration" not in str(p.service.log.snapshot())


async def test_enablement_rejects_override_action(policy_factory):
    p = policy_factory
    actions = {
        "revise": PolicyAction(
            name="editor.revision_rewrite",
            call=p.editor.revision_rewrite,
            enabled=lambda: False,
        )
    }
    assert await p.create(actions=actions).run() == "disabled result"
    p.editor.revision_rewrite.assert_not_awaited()
    entry = next(iter(p.service.log.records.values()))
    assert entry.actions[0].status == "skipped"
    assert entry.actions[0].failure.code == FailureCode.ACTION_DENIED


@pytest.mark.parametrize("stage", ["request", "action"])
@pytest.mark.parametrize("cancel_mode", ["task", "revision", "scene", "user"])
async def test_cancellation_through_render_bridge_owns_work(
    policy_factory, provider, stage, cancel_mode
):
    p = policy_factory
    started, stopped = asyncio.Event(), asyncio.Event()
    revision = {"current": True}
    scene = SimpleNamespace(
        active=True, cancel_requested=False, cancel_sequence=0, template_dir=None
    )

    async def blocked(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    if stage == "request":
        provider.handler = blocked
    else:
        p.editor.revision_rewrite.side_effect = blocked
    with ActiveScene(scene):
        invocation = p.create(is_current=lambda: revision["current"])
        task = asyncio.create_task(invocation.run())
        try:
            await asyncio.wait_for(started.wait(), 1)
            if cancel_mode == "task":
                task.cancel()
            elif cancel_mode == "revision":
                revision["current"] = False
            elif cancel_mode == "scene":
                scene.active = False
            else:
                scene.cancel_sequence += 1
            with pytest.raises((asyncio.CancelledError, GenerationCancelled)):
                await asyncio.wait_for(task, 1)
            await asyncio.wait_for(stopped.wait(), 1)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert invocation.status == "cancelled"
    p.fallback.assert_not_awaited()
    if stage == "request":
        p.editor.revision_rewrite.assert_not_awaited()
    with pytest.raises(RuntimeError):
        _ = invocation.result


async def test_late_response_after_invalidation_cannot_dispatch(
    policy_factory, provider
):
    p = policy_factory
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    current = {"value": True}

    async def stubborn(request):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return ProviderResponse(answers=provider.answers, response_body={})
        finally:
            finished.set()

    provider.handler = stubborn
    invocation = p.create(is_current=lambda: current["value"])
    task = asyncio.create_task(invocation.run())
    try:
        await asyncio.wait_for(started.wait(), 1)
        current["value"] = False
        with pytest.raises(GenerationCancelled):
            await asyncio.wait_for(task, 1)
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
    p.editor.revision_rewrite.assert_not_awaited()
    p.fallback.assert_not_awaited()
    assert next(iter(p.service.log.records.values())).answers is None


async def test_action_completion_updates_same_request_after_model_completion(
    policy_factory,
):
    p = policy_factory
    assert await p.create().run() == "rewritten"
    snapshots = [event["entry"] for event in p.events if event["event"] == "request"]
    model_done = next(
        entry
        for entry in snapshots
        if entry["status"] == "completed" and not entry["actions"]
    )
    pending = next(
        entry
        for entry in snapshots
        if entry["actions"] and entry["actions"][0]["status"] == "pending"
    )
    action_done = next(
        entry
        for entry in snapshots
        if entry["actions"] and entry["actions"][0]["status"] == "completed"
    )
    assert model_done["id"] == pending["id"] == action_done["id"]
    assert (
        model_done["elapsed_ms"] == pending["elapsed_ms"] == action_done["elapsed_ms"]
    )
    assert not model_done["actions"]


async def test_an_action_belongs_to_every_request_before_it(policy_factory):
    p = policy_factory
    invocation = p.create(ASK + ASK_OTHER + "{{ " + REVISE + " }}")
    assert await invocation.run() == "rewritten"
    assert len(invocation.action_trace) == 1
    entries = list(p.service.log.records.values())
    assert len(entries) == 2
    assert entries[0].actions[0].id == entries[1].actions[0].id
    assert len(entries[0].actions) == len(entries[1].actions) == 1


async def test_concurrent_requests_keep_their_own_action_outcomes(
    policy_factory, provider
):
    p = policy_factory
    first_started, second_finished = asyncio.Event(), asyncio.Event()

    async def respond(request):
        if request.state["passage"] == "first":
            first_started.set()
            await second_finished.wait()
            probability = 0.1
        else:
            probability = 0.9
            second_finished.set()
        return ProviderResponse(
            answers={"repeats": {"type": "noul", "p_true": probability}},
            response_body={},
        )

    provider.handler = respond
    first = p.create(
        variables={
            "passage": "first",
            "decision_checks": [p.editor],
            "last3": [],
            "info": SimpleNamespace(text="first"),
        },
        original_result="first",
    )
    second = p.create(
        variables={
            "passage": "second",
            "decision_checks": [p.editor],
            "last3": [],
            "info": SimpleNamespace(text="second"),
        }
    )
    task = asyncio.create_task(first.run())
    await asyncio.wait_for(first_started.wait(), 1)
    assert await asyncio.wait_for(second.run(), 1) == "rewritten"
    assert await asyncio.wait_for(task, 1) == "first"
    entries = {entry.invocation_id: entry for entry in p.service.log.records.values()}
    assert not entries[first.id].actions
    assert entries[first.id].outcomes[0]["reason"] == "below_threshold"
    assert entries[second.id].actions[0].result == "rewritten"


async def test_real_loader_scene_and_explicit_group_sources(
    policy_factory, monkeypatch, tmp_path
):
    from talemate.prompts import groups

    p = policy_factory
    scene_dir = tmp_path / "scene"
    (scene_dir / "editor").mkdir(parents=True)
    (scene_dir / "editor/policy.jinja2").write_text(
        ASK + '{{ note("scene", "source") }}{{ keep() }}'
    )
    custom_dir = tmp_path / "groups"
    (custom_dir / "experiment/editor").mkdir(parents=True)
    (custom_dir / "experiment/editor/policy.jinja2").write_text(
        ASK + '{{ note("group", "source") }}{{ keep() }}'
    )
    monkeypatch.setattr(groups, "_CUSTOM_GROUPS_DIR", custom_dir)
    scene = SimpleNamespace(
        active=True,
        cancel_requested=False,
        cancel_sequence=0,
        template_dir=str(scene_dir),
    )
    with ActiveScene(scene), PrependTemplateDirectories([]):
        first = p.create()
        first.prompt._config = first.prompt.config.model_copy(deep=True)
        first.prompt.config.prompts.template_sources = {}
        assert await first.run() == "original"
        assert first.source_group == "scene"
        assert (
            p.service.log.records[next(iter(first.handles))].outcomes[0]["action"]
            == "scene"
        )
        second = p.create()
        second.prompt._config = second.prompt.config.model_copy(deep=True)
        second.prompt.config.prompts.template_sources = {"editor.policy": "experiment"}
        assert await second.run() == "original"
        assert second.source_group == "experiment"
        assert (
            p.service.log.records[next(iter(second.handles))].outcomes[0]["action"]
            == "group"
        )


@pytest.mark.parametrize("hook", ["enabled", "arguments"])
async def test_pre_dispatch_hook_error_finishes_attempt_and_uses_fallback(
    policy_factory, hook
):
    p = policy_factory

    def broken(*args):
        raise ValueError("private hook detail")

    action = PolicyAction(
        name="editor.revision_rewrite",
        call=lambda findings: p.editor.revision_rewrite(decision_findings=findings),
        enabled=broken if hook == "enabled" else lambda: True,
        serialize_arguments=broken if hook == "arguments" else lambda kwargs: {},
    )
    invocation = p.create(actions={"revise": action})
    assert await invocation.run() == "disabled result"
    p.fallback.assert_awaited_once()
    p.editor.revision_rewrite.assert_not_awaited()
    entry = next(iter(p.service.log.records.values()))
    assert entry.actions[0].status == "failed"
    assert entry.actions[0].elapsed_ms is None
    assert p.service.log.finished(entry)


async def test_helpers_cannot_execute_before_or_after_invocation(
    policy_factory, provider
):
    p = policy_factory
    invocation = p.create()
    with pytest.raises(RuntimeError):
        invocation.keep()
    assert await invocation.run() == "rewritten"
    with pytest.raises(RuntimeError):
        invocation.ask("repeat", state="text", questions={})
    with pytest.raises(RuntimeError):
        invocation.note("no_action")
    with pytest.raises(RuntimeError):
        invocation.keep()
    assert invocation.result == "rewritten"
    assert len(provider.calls) == 1


async def test_foreign_answer_cannot_receive_outcomes(policy_factory):
    p = policy_factory
    first = p.create(ASK + "{% set _ = captured.append(answers.repeats) %}{{ keep() }}")
    captured = []
    first.prompt.vars["captured"] = captured
    assert await first.run() == "original"
    (foreign,) = captured
    second = p.create(
        '{{ note("no_action", "foreign", foreign) }}{{ keep() }}',
        variables={"info": SimpleNamespace(text="second"), "foreign": foreign},
    )
    assert await second.run() == "disabled result"
    assert not p.service.log.records[foreign.request_id].outcomes


async def test_disabled_path_error_preserves_original_and_records_failure(
    policy_factory,
):
    p = policy_factory
    p.fallback.side_effect = RuntimeError("private fallback detail")
    invocation = p.create("{{ invalid }}")
    assert await invocation.run() == "original"
    assert await invocation.run() == "original"
    p.fallback.assert_awaited_once()
    record = next(iter(p.service.log.records.values()))
    assert record.actions[0].status == "failed"
    assert record.actions[0].failure.code == FailureCode.FALLBACK


async def test_cancellation_during_fallback_stops_instead_of_preserving(policy_factory):
    p = policy_factory
    started, stopped = asyncio.Event(), asyncio.Event()

    async def fallback():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    invocation = p.create("{{ invalid }}", disabled_path=fallback)
    task = asyncio.create_task(invocation.run())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    await asyncio.wait_for(stopped.wait(), 1)
    assert invocation.status == "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await invocation.run()


async def test_currentness_rechecked_before_returning_action_output(policy_factory):
    p = policy_factory
    current = {"value": True}

    async def revise(**kwargs):
        current["value"] = False
        return "stale output"

    p.editor.revision_rewrite.side_effect = revise
    invocation = p.create(is_current=lambda: current["value"])
    with pytest.raises(GenerationCancelled):
        await invocation.run()
    p.fallback.assert_not_awaited()
    with pytest.raises(RuntimeError):
        _ = invocation.result


@pytest.mark.parametrize(
    "interruption",
    [AbortCommand, AbortWaitForInput, ExitScene, ResetScene, RestartSceneLoop],
)
@pytest.mark.parametrize(
    "stage", ["provider", "action", "fallback", "enabled", "result"]
)
async def test_control_flow_propagates_through_policy_without_recovery(
    policy_factory, provider, stage, interruption
):
    p = policy_factory
    error = interruption("control flow")
    source = None
    kwargs = {}
    armed = False

    def interrupt(*args):
        raise error

    if stage == "provider":
        provider.handler = AsyncMock(side_effect=error)
    elif stage == "action":
        p.editor.revision_rewrite.side_effect = error
    elif stage == "fallback":
        source = "{{ undefined }}"
        p.fallback.side_effect = error
    elif stage == "enabled":
        kwargs["actions"] = {
            "revise": PolicyAction(
                name="editor.revision_rewrite",
                call=p.editor.revision_rewrite,
                enabled=interrupt,
            )
        }
    else:
        source = ASK + "{{ keep() }}"
        kwargs["original_result"] = "interrupted"
        kwargs["validate_result"] = (
            lambda value: interrupt() if value == "interrupted" and armed else value
        )
    invocation = p.create(source, **kwargs)
    armed = True
    with pytest.raises(interruption) as caught:
        await invocation.run()
    assert caught.value is error
    assert invocation.status == "cancelled"
    with pytest.raises(interruption):
        await invocation.run()
    assert p.fallback.await_count == (1 if stage == "fallback" else 0)
    for entry in p.service.log.records.values():
        assert entry.status != "pending"
        assert entry.outcomes == []
        assert all(action.status == "cancelled" for action in entry.actions)
        assert entry.policy_failure is None
    if stage == "provider":
        assert next(iter(p.service.log.records.values())).status == "cancelled"
        p.editor.revision_rewrite.assert_not_awaited()


async def test_action_before_any_request_stays_on_the_invocation(policy_factory):
    p = policy_factory
    invocation = p.create("{{ " + REVISE + " }}")
    assert await invocation.run() == "rewritten"
    assert not p.service.log.records
    assert invocation.action_trace[0].status == "completed"
    event = [event for event in p.events if event["event"] == "invocation"][-1]
    assert event["entry"]["actions"][0]["result"] == "rewritten"


async def test_denied_action_failure_and_fallback_follow_the_requests(
    policy_factory,
):
    p = policy_factory
    actions = {
        "revise": PolicyAction(
            name="editor.denied", call=p.editor.revision_rewrite, enabled=lambda: False
        )
    }
    invocation = p.create(ASK + ASK_OTHER + "{{ " + REVISE + " }}", actions=actions)
    assert await invocation.run() == "disabled result"
    first, second = p.service.log.records.values()
    assert first.policy_failure.code == FailureCode.ACTION_DENIED
    assert [a.action for a in first.actions] == ["editor.denied", "disabled_path"]
    assert second.policy_failure.code == FailureCode.ACTION_DENIED
    assert [a.id for a in second.actions] == [a.id for a in first.actions]
    assert all(entry.failure is None for entry in (first, second))
    p.fallback.assert_awaited_once()


@pytest.mark.parametrize(
    "suffix,code",
    [
        ("{{ undefined }}", FailureCode.TEMPLATE),
        ("", FailureCode.RESULT),
        ("{{ keep() }}{{ keep() }}", FailureCode.RESULT),
    ],
)
async def test_unassociated_failures_get_synthetic_policy_entry(
    policy_factory, suffix, code
):
    p = policy_factory
    invocation = p.create(ASK + ASK_OTHER + suffix)
    assert await invocation.run() == "disabled result"
    first, second, policy = p.service.log.records.values()
    for entry in (first, second):
        assert entry.policy_failure is None
        assert entry.actions == entry.outcomes == []
    assert policy.label == "policy"
    assert policy.failure.code == code
    assert not policy.dispatched
    assert policy.actions[0].action == "disabled_path"
    p.fallback.assert_awaited_once()


@pytest.mark.parametrize("association", ["none", "[]", "answers", '"text"'])
async def test_a_note_takes_only_answers(policy_factory, association):
    p = policy_factory
    source = ASK + '{{ note("no_action", "reason", ' + association + ") }}{{ keep() }}"
    assert await p.create(source).run() == "disabled result"
    first, policy = p.service.log.records.values()
    assert first.outcomes == []
    assert policy.failure.code == FailureCode.TEMPLATE


async def test_outcome_without_a_request_belongs_to_the_invocation(policy_factory):
    p = policy_factory
    source = '{{ note("no_action", "nothing_in_scope", skipped=2) }}{{ keep() }}'
    assert await p.create(source).run() == "original"
    assert not p.service.log.records
    (invocation,) = p.service.log.invocations.values()
    assert invocation.status == "completed"
    assert invocation.outcomes == [
        {"action": "no_action", "reason": "nothing_in_scope", "details": {"skipped": 2}}
    ]
    emitted = [e["entry"] for e in p.events if e["event"] == "invocation"]
    assert emitted[-1]["outcomes"] == invocation.outcomes
    p.fallback.assert_not_awaited()


async def test_invocation_outcome_stays_when_a_request_follows(policy_factory):
    p = policy_factory
    source = (
        '{{ note("note", "checked_first") }}'
        + ASK
        + '{{ note("no_action") }}{{ keep() }}'
    )
    assert await p.create(source).run() == "original"
    (invocation,) = p.service.log.invocations.values()
    (record,) = p.service.log.records.values()
    assert invocation.request_count == 1
    assert [o["reason"] for o in invocation.outcomes] == ["checked_first"]
    assert [o["action"] for o in record.outcomes] == ["no_action"]


async def test_reused_action_map_has_fresh_shared_budget_per_invocation(policy_factory):
    p = policy_factory
    budget = ActionBudget(limit=1)
    alternative = AsyncMock(return_value="alternative")
    actions = {
        "revise": PolicyAction(
            name="editor.revision_rewrite",
            call=p.editor.revision_rewrite,
            enabled=lambda: True,
            budget=budget,
        ),
        "alternative": PolicyAction(
            name="editor.alternative",
            call=alternative,
            enabled=lambda: True,
            budget=budget,
        ),
    }
    source = ASK + "{{ revise() }}{{ alternative() }}"
    for _ in range(2):
        invocation = p.create(source, actions=actions)
        assert await invocation.run() == "original"
        assert invocation.action_trace[0].status == "completed"
        assert invocation.action_trace[1].failure.code == FailureCode.BUDGET
    assert p.editor.revision_rewrite.await_count == 2
    alternative.assert_not_awaited()
    p.fallback.assert_not_awaited()


async def test_equal_limits_on_distinct_budgets_allow_both_actions(policy_factory):
    p = policy_factory
    first, second = AsyncMock(return_value="first"), AsyncMock(return_value="second")
    actions = {
        "first": PolicyAction(
            name="editor.first",
            call=first,
            enabled=lambda: True,
            budget=ActionBudget(limit=1),
        ),
        "second": PolicyAction(
            name="editor.second",
            call=second,
            enabled=lambda: True,
            budget=ActionBudget(limit=1),
        ),
    }
    invocation = p.create("{{ first() }}{{ second() }}", actions=actions)
    # both budgets allow their action; the second result is what fails
    assert await invocation.run() == "original"
    assert invocation.status == "preserved"
    first.assert_awaited_once()
    second.assert_awaited_once()
    assert [action.status for action in invocation.action_trace] == [
        "completed",
        "completed",
    ]
    p.fallback.assert_not_awaited()


@pytest.mark.parametrize(
    "mode", ["unknown", "disabled", "budget", "selector_failure", "enabled_failure"]
)
async def test_only_successful_argument_projection_can_reach_logs(policy_factory, mode):
    p = policy_factory
    private = "private argument sentinel"
    selector = Mock(return_value={"text": "public"})
    enabled = Mock(return_value=mode != "disabled")
    if mode == "selector_failure":
        selector.side_effect = RuntimeError(private)
    if mode == "enabled_failure":
        enabled.side_effect = RuntimeError(private)
    spec = PolicyAction(
        name="editor.revision_rewrite",
        call=p.editor.revision_rewrite,
        enabled=enabled,
        budget=ActionBudget(limit=1),
        serialize_arguments=selector,
    )
    action = "{{ revise(hidden=private_value) }}"
    source = ASK + (action if mode == "budget" else "") + action
    invocation = p.create(
        source,
        actions={} if mode == "unknown" else {"revise": spec},
    )
    invocation.prompt.vars["private_value"] = private
    assert await invocation.run() == (
        "original" if mode == "budget" else "disabled result"
    )
    if mode == "unknown":
        assert invocation.action_trace[0].action == "disabled_path"
    else:
        attempt = next(
            a
            for a in reversed(invocation.action_trace)
            if a.action == "editor.revision_rewrite"
        )
        assert attempt.arguments is None
        assert attempt.status == ("failed" if mode.endswith("failure") else "skipped")
    assert private not in str(p.events)
    assert private not in str(p.service.log.snapshot())
    if mode == "budget":
        assert invocation.action_trace[0].arguments == {"text": "public"}
        selector.assert_called_once()
        p.editor.revision_rewrite.assert_awaited_once()
        p.fallback.assert_not_awaited()
    else:
        p.editor.revision_rewrite.assert_not_awaited()
        p.fallback.assert_awaited_once()
        assert selector.call_count == (1 if mode == "selector_failure" else 0)


@pytest.mark.parametrize(
    "history", ["no_action", "explicit_reason", "action_before_request", "cancelled"]
)
async def test_late_subscriber_can_distinguish_invocation_outcomes(
    policy_factory, history
):
    p = policy_factory
    prefix, suffix = ASK, "{{ keep() }}"
    kwargs = {}
    armed = False
    if history == "explicit_reason":
        suffix = '{{ note("no_action", "below_threshold", threshold=0.8) }}' + suffix
    elif history == "action_before_request":
        prefix, suffix = "{{ " + REVISE + " }}", ASK
    elif history == "cancelled":

        def validate(value):
            if armed:
                raise ExitScene()
            return value

        kwargs["validate_result"] = validate
    invocation = p.create(prefix + suffix, **kwargs)
    armed = True
    if history == "cancelled":
        with pytest.raises(ExitScene):
            await invocation.run()
    else:
        assert await invocation.run() == (
            "rewritten" if history == "action_before_request" else "original"
        )
    late_events = []
    p.service.log.subscribe(late_events.append)
    snapshot = p.service.log.snapshot()
    request, retained = snapshot["requests"][0], snapshot["invocations"][0]
    assert late_events == []
    assert retained["id"] == request["invocation_id"] == invocation.id
    assert retained["template_uid"] == "editor.policy"
    assert retained["source_group"] == invocation.source_group
    assert request["status"] == "completed"
    assert request["actions"] == []
    assert retained["status"] == (
        "cancelled" if history == "cancelled" else "completed"
    )
    if history == "action_before_request":
        assert retained["actions"][0]["result"] == "rewritten"
        assert retained["actions"][0]["status"] == "completed"
    else:
        assert retained["actions"] == []
    if history == "explicit_reason":
        assert request["outcomes"][0]["reason"] == "below_threshold"
    else:
        assert request["outcomes"] == []
    retained["actions"].append({"action": "snapshot-only"})
    assert "snapshot-only" not in str(p.service.log.snapshot())


async def test_pending_unassociated_action_is_retained_with_its_invocation(
    policy_factory,
):
    p = policy_factory
    started, stopped = asyncio.Event(), asyncio.Event()

    async def action(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    p.editor.revision_rewrite.side_effect = action
    invocation = p.create("{{ " + REVISE + " }}" + ASK)
    task = asyncio.create_task(invocation.run())
    try:
        await asyncio.wait_for(started.wait(), 1)
        p.service.log.clear_finished()
        snapshot = p.service.log.snapshot()
        assert snapshot["requests"] == []
        assert snapshot["invocations"][0]["status"] == "running"
        assert snapshot["invocations"][0]["actions"][0]["status"] == "pending"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        await asyncio.wait_for(stopped.wait(), 1)
    snapshot = p.service.log.snapshot()
    assert snapshot["invocations"][0]["status"] == "cancelled"
    assert snapshot["invocations"][0]["actions"][0]["status"] == "cancelled"
    p.service.log.clear_finished()
    assert p.service.log.snapshot() == {"requests": [], "invocations": []}


MIXED_ANSWERS = {
    "bool": {"type": "noul", "p_true": 0.74},
    "choice": {
        "type": "choice",
        "selected": "a",
        "probabilities": {"none": 0.1, "a": 0.6, "b": 0.3},
        "confidence": 0.8,
    },
}


@pytest.mark.parametrize("invalid", [False, True])
async def test_question_types_route_through_real_jinja_and_log(
    policy_factory, provider, invalid
):
    p = policy_factory
    provider.answers = copy.deepcopy(MIXED_ANSWERS)
    if invalid:
        provider.answers["choice"]["probabilities"] = {"a": 0.7, "b": 0.3}
    source = """
    {% set answers = ask("mixed", state=passage, questions={
        "bool": yes_no("Does the supplied passage repeat?", threshold=0.7),
        "choice": choice("Select a supplied candidate", options={"a": "Wait", "b": "Leave"}, none="Neither fits", threshold=0.75)
    }) %}
    {% if answers.bool.yes and answers.choice.value == "a" %}
      {{ revise([]) }}
    {% else %}
      {{ keep() }}
    {% endif %}
    """
    invocation = p.create(source)
    assert await invocation.run() == ("disabled result" if invalid else "rewritten")
    entry = next(iter(p.service.log.records.values()))
    assert len(provider.calls) == 1
    questions = provider.calls[0].questions
    assert set(questions) == {"bool", "choice"}
    assert list(questions["choice"].options) == ["none", "a", "b"]
    if invalid:
        assert entry.answers is None
        assert entry.failure.code == FailureCode.INVALID_RESPONSE
        p.editor.revision_rewrite.assert_not_awaited()
        p.fallback.assert_awaited_once()
    else:
        assert entry.answers == MIXED_ANSWERS
        p.editor.revision_rewrite.assert_awaited_once()
        p.fallback.assert_not_awaited()
    p.generative.assert_not_awaited()


NOTE_ANSWERS = {
    "a": {"type": "noul", "p_true": 0.9},
    "b": {"type": "noul", "p_true": 0.2},
    "c": {
        "type": "choice",
        "selected": "x",
        "probabilities": {"none": 0.2, "x": 0.8},
        "confidence": 0.8,
    },
}


@pytest.mark.parametrize(
    "thresholds,noted,details",
    [
        (
            (0.8, 0.8, 0.8),
            "answers.a, answers.c",
            {
                "p_true": 0.9,
                "confidence": 0.9,
                "choice_confidence": 0.8,
                "threshold": 0.8,
            },
        ),
        (
            (0.8, 0.8, 0.7),
            "answers.a, answers.c",
            {
                "p_true": 0.9,
                "confidence": 0.9,
                "choice_confidence": 0.8,
                "thresholds": {"a": 0.8, "c": 0.7},
            },
        ),
        (
            (0.8, 0.8, 0.8),
            "answers.a, answers.b",
            {
                "p_true": {"a": 0.9, "b": 0.2},
                "confidence": {"a": 0.9, "b": 0.8},
                "threshold": 0.8,
            },
        ),
        (
            (0.8, 0.8, 0.8),
            "answers.a, answers.b, answers.c, pin='door'",
            {
                "pin": "door",
                "p_true": {"a": 0.9, "b": 0.2},
                "confidence": {"a": 0.9, "b": 0.8},
                "choice_confidence": 0.8,
                "threshold": 0.8,
            },
        ),
    ],
)
async def test_a_note_adds_the_details_of_its_answers(
    policy_factory, provider, thresholds, noted, details
):
    p = policy_factory
    provider.answers = copy.deepcopy(NOTE_ANSWERS)
    a, b, c = thresholds
    source = (
        '{% set answers = ask("note", state=passage, questions={'
        f'"a": yes_no("A?", threshold={a}), "b": yes_no("B?", threshold={b}), '
        f'"c": choice("C?", options={{"x": "X"}}, none="Neither", threshold={c})'
        "}) %}"
        '{{ note("no_action", "checked", ' + noted + ") }}{{ keep() }}"
    )
    assert await p.create(source).run() == "original"
    (record,) = p.service.log.records.values()
    (outcome,) = record.outcomes
    assert outcome["details"] == details
    assert list(outcome["details"]) == list(details)


@pytest.mark.parametrize("explicit", ["threshold=0.5", "thresholds={}", "p_true=0.5"])
async def test_a_note_refuses_a_detail_its_answers_record(
    policy_factory, provider, explicit
):
    p = policy_factory
    provider.answers = {"a": copy.deepcopy(NOTE_ANSWERS["a"])}
    source = (
        '{% set answers = ask("note", state=passage, questions={'
        '"a": yes_no("A?", threshold=0.8)}) %}'
        '{{ note("no_action", "checked", answers.a, ' + explicit + ") }}{{ keep() }}"
    )
    assert await p.create(source).run() == "disabled result"
    record, policy = p.service.log.records.values()
    assert record.outcomes == []
    assert policy.failure.code == FailureCode.TEMPLATE


async def test_none_is_not_an_option_id(policy_factory, provider):
    p = policy_factory
    source = (
        '{% set answers = ask("pick", state=passage, questions={"c": choice("C?", '
        'options={"none": "A real candidate", "x": "X"}, none="Neither", threshold=0.5)}) %}'
        "{{ keep() }}"
    )
    assert await p.create(source).run() == "disabled result"
    assert not provider.calls
    (policy,) = p.service.log.records.values()
    assert policy.failure.code == FailureCode.TEMPLATE


async def test_a_note_refuses_answers_from_two_requests_with_one_id(
    policy_factory, provider
):
    p = policy_factory
    provider.answers = {"a": copy.deepcopy(NOTE_ANSWERS["a"])}
    source = (
        '{% set one = ask("one", state=passage, questions={"a": yes_no("A?", threshold=0.8)}) %}'
        '{% set two = ask("two", state=passage, questions={"a": yes_no("A?", threshold=0.6)}) %}'
        '{{ note("no_action", "checked", one.a, two.a) }}{{ keep() }}'
    )
    assert await p.create(source).run() == "disabled result"
    first, second, policy = p.service.log.records.values()
    assert first.outcomes == second.outcomes == []
    assert policy.failure.code == FailureCode.TEMPLATE


async def test_a_note_takes_the_same_answer_twice(policy_factory, provider):
    p = policy_factory
    provider.answers = {"a": copy.deepcopy(NOTE_ANSWERS["a"])}
    source = (
        '{% set answers = ask("one", state=passage, questions={"a": yes_no("A?", threshold=0.8)}) %}'
        '{{ note("no_action", "checked", answers.a, answers.a) }}{{ keep() }}'
    )
    assert await p.create(source).run() == "original"
    (record,) = p.service.log.records.values()
    assert record.outcomes[0]["details"] == {
        "p_true": 0.9,
        "confidence": 0.9,
        "threshold": 0.8,
    }
