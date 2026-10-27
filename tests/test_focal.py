"""
Tests for the focal system's execution logic.

Tests _execute() directly using real Focal/Callback/Call/State objects
plus a real `DirectorAgent` (with a stubbed `log_function_call`) and a
real `ClientBase` subclass. LLM client is not driven during these tests
since we feed well-formed responses that _extract() can parse natively.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock

from conftest import MockClient

import talemate.instance as instance
from talemate.agents.director import DirectorAgent
from talemate.game.focal import (
    Focal,
    FocalContext,
    collect_calls,
)
from talemate.game.focal.schema import Argument, Call, Callback, State
from talemate.agents.director.action_core.exceptions import ActionRejected
from talemate.exceptions import GenerationCancelled


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_callback(
    name: str, fn=None, multiple: bool = True, concurrent: bool = False
) -> Callback:
    """Create a Callback with a simple async fn that records invocations."""
    if fn is None:

        async def fn(**kwargs):
            return kwargs

    return Callback(
        name=name,
        arguments=[
            Argument(name="text", type="str"),
        ],
        fn=fn,
        multiple=multiple,
        concurrent=concurrent,
    )


def make_response(*calls: dict) -> str:
    """Build a well-formed JSON response that _extract() parses natively."""
    blocks = []
    for call in calls:
        blocks.append(f"```json\n{json.dumps(call)}\n```")
    return "\n".join(blocks)


def make_call_dict(name: str, **arguments) -> dict:
    """Shortcut for building a call dict."""
    return {"function": name, "arguments": arguments}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def setup_director():
    """Register a real `DirectorAgent` in the agent registry.

    `log_function_call` is stubbed because it's a peripheral RPC the unit
    under test (`Focal._execute`) happens to call — Focal's behaviour does
    not depend on the log side-effect, only on whether it was invoked.
    """
    director = DirectorAgent()
    director.log_function_call = AsyncMock()
    original = instance.AGENTS.copy()
    instance.AGENTS["director"] = director
    yield director
    instance.AGENTS.clear()
    instance.AGENTS.update(original)


class _SequentialClient(MockClient):
    """Real ClientBase subclass used in non-concurrent Focal tests.

    Overrides only the two properties Focal reads — `data_format` and
    `supports_concurrent_inference`. Everything else is the real ClientBase
    contract.
    """

    @property
    def data_format(self):
        return "json"

    @property
    def supports_concurrent_inference(self):
        return False


class _ConcurrentClient(_SequentialClient):
    """Variant that opts in to concurrent inference."""

    @property
    def supports_concurrent_inference(self):
        return True


async def test_plain_callback_cancellation_aborts_remaining_calls(setup_director):
    async def cancelled(text):
        raise GenerationCancelled("Character development cancelled")

    later = AsyncMock()
    handler = Focal(
        _SequentialClient("cancellation-test"),
        [make_callback("develop", cancelled), make_callback("later", later)],
    )
    with pytest.raises(GenerationCancelled, match="Character development cancelled"):
        await handler._execute(
            make_response(
                make_call_dict("develop", text="first"),
                make_call_dict("later", text="second"),
            ),
            State(),
        )
    assert handler.state.batch[0].skipped_reason == "interrupted"
    assert handler.state.batch[1].skipped_reason == "aborted"
    assert not handler.state.calls
    later.assert_not_awaited()


@pytest.mark.parametrize("reason", ["reject", "timed_out", "reject_with_instructions"])
async def test_batch_records_rejection_and_remainder(
    mock_client, setup_director, reason
):
    applied = []

    async def write(text):
        if text == "2":
            raise ActionRejected(
                "write",
                text,
                reason=reason,
                instructions="Use blue" if reason == "reject_with_instructions" else "",
            )
        applied.append(text)

    handler = Focal(mock_client, [make_callback("write", fn=write)])
    response = make_response(
        *(make_call_dict("write", text=str(i)) for i in range(1, 6))
    )
    hook = AsyncMock()
    with FocalContext() as context:
        context.hooks_after_batch.append(hook)
        if reason == "reject_with_instructions":
            await handler._execute(response, State())
            assert applied == ["1", "3", "4", "5"]
            assert handler.state.batch[1].rejection_instructions == "Use blue"
        else:
            with pytest.raises(ActionRejected):
                await handler._execute(response, State())
            assert applied == ["1"]
            assert [c.skipped_reason for c in handler.state.batch[1:]] == [reason] + [
                "aborted"
            ] * 3
    hook.assert_awaited_once_with(handler.state.batch)
    assert handler.state.batch[1].arguments == {"text": "2"}
    assert not handler.state.batch[1].called


async def test_budget_preserves_dropped_calls_and_still_reports(
    mock_client, setup_director
):
    write = AsyncMock()
    report = AsyncMock()
    handler = Focal(
        mock_client,
        [
            Callback(name="write", fn=write),
            Callback(name="report_issue", fn=report, counts_toward_budget=False),
        ],
        max_calls=1,
    )
    await handler._execute(
        make_response(
            make_call_dict("write", text="one"),
            make_call_dict("write", text="two"),
            make_call_dict("report_issue", issue="limit"),
        ),
        State(),
    )
    write.assert_awaited_once_with(text="one")
    report.assert_awaited_once_with(issue="limit")
    assert handler.state.batch[1].skipped_reason == "over_budget"
    assert handler.state.batch[1].arguments == {"text": "two"}
    assert "report_issue calls do not count" in handler.render_instructions()


async def test_nested_abort_retains_leaf_outcomes_and_emits_one_batch(
    mock_client, setup_director
):
    async def write(text):
        if text == "two":
            raise ActionRejected("write", text)

    inner = Focal(mock_client, [Callback(name="write", fn=write)])

    async def outer(tag, _focal_call):
        inner.parent_call = _focal_call
        await inner._execute(
            make_response(
                *(
                    make_call_dict("write", text=text)
                    for text in ("one", "two", "three")
                )
            ),
            State(),
        )

    handler = Focal(mock_client, [Callback(name="outer", fn=outer, pass_call=True)])
    hook = AsyncMock()
    with FocalContext() as context:
        context.hooks_after_batch.append(hook)
        with pytest.raises(ActionRejected):
            await handler._execute(
                make_response(
                    make_call_dict("outer", tag="first"),
                    make_call_dict("outer", tag="second"),
                ),
                State(),
            )
    hook.assert_awaited_once_with(handler.state.batch)
    assert handler.state.batch[0].subcalls[0].called
    assert [call.skipped_reason for call in handler.state.batch[0].subcalls[1:]] == [
        "reject",
        "aborted",
    ]
    assert handler.state.batch[1].skipped_reason == "aborted"


@pytest.fixture
def mock_client():
    return _SequentialClient("focal_sequential")


# ---------------------------------------------------------------------------
# Phase 1: Tests for existing _execute() behaviour
# ---------------------------------------------------------------------------


class TestExecuteSequential:
    """Tests for the current sequential execution in Focal._execute()."""

    @pytest.mark.asyncio
    async def test_sequential_execution_order(self, mock_client, setup_director):
        """Three callbacks are executed in the order they appear in the response."""
        order = []

        async def fn_a(text):
            order.append("a")
            return "result_a"

        async def fn_b(text):
            order.append("b")
            return "result_b"

        async def fn_c(text):
            order.append("c")
            return "result_c"

        focal = Focal(
            client=mock_client,
            callbacks=[
                make_callback("a", fn=fn_a),
                make_callback("b", fn=fn_b),
                make_callback("c", fn=fn_c),
            ],
            max_calls=10,
        )

        response = make_response(
            make_call_dict("a", text="1"),
            make_call_dict("b", text="2"),
            make_call_dict("c", text="3"),
        )

        await focal._execute(response, State())

        assert order == ["a", "b", "c"]
        assert len(focal.state.calls) == 3
        assert [c.result for c in focal.state.calls] == [
            "result_a",
            "result_b",
            "result_c",
        ]

    @pytest.mark.asyncio
    async def test_max_calls_respected(self, mock_client, setup_director):
        """Only max_calls callbacks are executed even if more are extracted."""
        call_count = 0

        async def counting_fn(text):
            nonlocal call_count
            call_count += 1
            return "ok"

        focal = Focal(
            client=mock_client,
            callbacks=[make_callback("action", fn=counting_fn)],
            max_calls=2,
        )

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
            make_call_dict("action", text="3"),
            make_call_dict("action", text="4"),
            make_call_dict("action", text="5"),
        )

        await focal._execute(response, State())

        assert call_count == 2
        assert len(focal.state.calls) == 2

    @pytest.mark.asyncio
    async def test_unknown_callback_skipped(self, mock_client, setup_director):
        """Calls referencing unknown callbacks are skipped without error."""
        called = []

        async def known_fn(text):
            called.append(text)
            return "ok"

        focal = Focal(
            client=mock_client,
            callbacks=[make_callback("known", fn=known_fn)],
            max_calls=10,
        )

        response = make_response(
            make_call_dict("unknown", text="skip me"),
            make_call_dict("known", text="run me"),
        )

        await focal._execute(response, State())

        assert called == ["run me"]
        # Only the known call is appended to state
        assert len(focal.state.calls) == 1
        assert focal.state.calls[0].name == "known"

    @pytest.mark.asyncio
    async def test_callback_error_stored_and_execution_continues(
        self, mock_client, setup_director
    ):
        """A failing callback stores the error and doesn't block subsequent calls."""
        called = []

        async def failing_fn(text):
            raise ValueError("boom")

        async def ok_fn(text):
            called.append(text)
            return "ok"

        focal = Focal(
            client=mock_client,
            callbacks=[
                make_callback("fail", fn=failing_fn),
                make_callback("ok", fn=ok_fn),
            ],
            max_calls=10,
        )

        response = make_response(
            make_call_dict("fail", text="x"),
            make_call_dict("ok", text="y"),
        )

        await focal._execute(response, State())

        # Error call is recorded with error message
        assert focal.state.calls[0].error == "boom"
        assert focal.state.calls[0].called is False
        # Subsequent call still executes
        assert called == ["y"]
        assert focal.state.calls[1].called is True

    @pytest.mark.asyncio
    async def test_focal_reraise_propagates(self, mock_client, setup_director):
        """Exceptions with focal_reraise=True are re-raised."""

        async def reraise_fn(text):
            exc = RuntimeError("must propagate")
            exc.focal_reraise = True
            raise exc

        focal = Focal(
            client=mock_client,
            callbacks=[make_callback("reraise", fn=reraise_fn)],
            max_calls=10,
        )

        response = make_response(make_call_dict("reraise", text="x"))

        with pytest.raises(RuntimeError, match="must propagate"):
            await focal._execute(response, State())

    @pytest.mark.asyncio
    async def test_call_results_stored(self, mock_client, setup_director):
        """call.result and call.called are set after successful execution."""

        async def fn(text):
            return {"processed": text}

        focal = Focal(
            client=mock_client,
            callbacks=[make_callback("process", fn=fn)],
            max_calls=10,
        )

        response = make_response(make_call_dict("process", text="hello"))
        await focal._execute(response, State())

        call = focal.state.calls[0]
        assert call.called is True
        assert call.result == {"processed": "hello"}
        assert call.error is None
        assert call.name == "process"

    @pytest.mark.asyncio
    async def test_focal_context_hooks(self, mock_client, setup_director):
        """FocalContext before/after hooks fire around each call."""
        hook_log = []

        async def before_hook(call: Call):
            hook_log.append(("before", call.name))

        async def after_hook(call: Call):
            hook_log.append(("after", call.name))

        async def fn(text):
            hook_log.append(("fn", text))
            return "ok"

        focal = Focal(
            client=mock_client,
            callbacks=[make_callback("action", fn=fn)],
            max_calls=10,
        )

        ctx = FocalContext()
        ctx.hooks_before_call.append(before_hook)
        ctx.hooks_after_call.append(after_hook)

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
        )

        with ctx:
            await focal._execute(response, State())

        assert hook_log == [
            ("before", "action"),
            ("fn", "1"),
            ("after", "action"),
            ("before", "action"),
            ("fn", "2"),
            ("after", "action"),
        ]

    @pytest.mark.asyncio
    async def test_director_log_called_per_call(self, mock_client, setup_director):
        """Director.log_function_call is called for each executed call."""

        async def fn(text):
            return "ok"

        focal = Focal(
            client=mock_client,
            callbacks=[make_callback("action", fn=fn)],
            max_calls=10,
        )

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
        )

        await focal._execute(response, State())

        assert setup_director.log_function_call.call_count == 2


class TestCollectCalls:
    """Tests for the collect_calls() helper."""

    def test_basic_collection(self):
        """Collects all calls from a flat list."""
        calls = [
            Call(name="a", arguments={"x": "1"}, result="r1", called=True),
            Call(name="b", arguments={"x": "2"}, result="r2", called=True),
        ]

        result = collect_calls(calls)
        assert len(result) == 2
        assert result[0].name == "a"
        assert result[1].name == "b"

    def test_filter(self):
        """Filter function selects matching calls."""
        calls = [
            Call(name="a", arguments={}, result="r1", called=True),
            Call(name="b", arguments={}, result="r2", called=True),
            Call(name="a", arguments={}, result="r3", called=True),
        ]

        result = collect_calls(calls, filter=lambda c: c.name == "a")
        assert len(result) == 2
        assert all(c.name == "a" for c in result)

    def test_nested_collection(self):
        """Nested call results are collected when nested=True."""
        inner_calls = [
            Call(name="inner", arguments={}, result="inner_r", called=True),
        ]
        outer = Call(name="outer", arguments={}, result=inner_calls, called=True)

        result = collect_calls([outer], nested=True)
        assert len(result) == 2
        assert result[0].name == "outer"
        assert result[1].name == "inner"

    def test_nested_with_filter(self):
        """Filter applies to both outer and inner calls when nested."""
        inner_calls = [
            Call(name="keep", arguments={}, result="ok", called=True),
            Call(name="skip", arguments={}, result="no", called=True),
        ]
        outer = Call(name="skip", arguments={}, result=inner_calls, called=True)

        result = collect_calls([outer], nested=True, filter=lambda c: c.name == "keep")
        assert len(result) == 1
        assert result[0].name == "keep"


# ---------------------------------------------------------------------------
# Phase 2: Tests for concurrent execution
# ---------------------------------------------------------------------------


@pytest.fixture
def concurrent_client():
    """Real ClientBase subclass that opts into concurrent inference."""
    return _ConcurrentClient("focal_concurrent")


class TestExecuteConcurrent:
    """Tests for concurrent callback execution via asyncio.gather + semaphore."""

    @pytest.mark.asyncio
    async def test_concurrent_streak_all_complete(
        self, concurrent_client, setup_director
    ):
        """Consecutive concurrent-flagged calls all complete and are recorded."""
        results = []

        async def fn(text):
            results.append(text)
            return f"done:{text}"

        focal = Focal(
            client=concurrent_client,
            callbacks=[make_callback("action", fn=fn, concurrent=True)],
            max_calls=10,
            max_concurrent=3,
        )

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
            make_call_dict("action", text="3"),
        )

        await focal._execute(response, State())

        assert len(focal.state.calls) == 3
        assert all(c.called for c in focal.state.calls)
        assert all(c.error is None for c in focal.state.calls)
        # All three were called (order may vary since concurrent)
        assert sorted(results) == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_mixed_sequential_and_concurrent(
        self, concurrent_client, setup_director
    ):
        """seq → concurrent streak → seq preserves overall ordering of groups."""
        log = []

        async def seq_fn(text):
            log.append(("seq", text))
            return "seq"

        async def conc_fn(text):
            log.append(("conc", text))
            return "conc"

        focal = Focal(
            client=concurrent_client,
            callbacks=[
                make_callback("seq_action", fn=seq_fn, concurrent=False),
                make_callback("conc_action", fn=conc_fn, concurrent=True),
            ],
            max_calls=10,
            max_concurrent=3,
        )

        response = make_response(
            make_call_dict("seq_action", text="first"),
            make_call_dict("conc_action", text="a"),
            make_call_dict("conc_action", text="b"),
            make_call_dict("conc_action", text="c"),
            make_call_dict("seq_action", text="last"),
        )

        await focal._execute(response, State())

        assert len(focal.state.calls) == 5

        # First call must be sequential (ran before concurrent streak)
        assert focal.state.calls[0].name == "seq_action"
        assert focal.state.calls[0].result == "seq"

        # Middle 3 are the concurrent streak (all recorded)
        concurrent_calls = focal.state.calls[1:4]
        assert all(c.name == "conc_action" for c in concurrent_calls)
        assert all(c.called for c in concurrent_calls)

        # Last call is sequential again
        assert focal.state.calls[4].name == "seq_action"
        assert focal.state.calls[4].result == "seq"

        # Sequential calls must have run before and after the streak
        seq_indices = [i for i, entry in enumerate(log) if entry[0] == "seq"]
        conc_indices = [i for i, entry in enumerate(log) if entry[0] == "conc"]
        assert seq_indices[0] < min(conc_indices)
        assert seq_indices[1] > max(conc_indices)

    @pytest.mark.asyncio
    async def test_concurrent_respects_max_concurrent(
        self, concurrent_client, setup_director
    ):
        """Semaphore limits actual parallelism to max_concurrent."""
        active = 0
        max_active = 0
        lock = asyncio.Lock()

        async def tracking_fn(text):
            nonlocal active, max_active
            async with lock:
                active += 1
                if active > max_active:
                    max_active = active
            # Yield to allow other tasks to start if they can
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            return "ok"

        focal = Focal(
            client=concurrent_client,
            callbacks=[make_callback("action", fn=tracking_fn, concurrent=True)],
            max_calls=10,
            max_concurrent=2,
        )

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
            make_call_dict("action", text="3"),
            make_call_dict("action", text="4"),
            make_call_dict("action", text="5"),
        )

        await focal._execute(response, State())

        assert len(focal.state.calls) == 5
        assert all(c.called for c in focal.state.calls)
        # Semaphore should have limited concurrency to 2
        assert max_active <= 2

    @pytest.mark.asyncio
    async def test_client_without_concurrency_falls_back_to_sequential(
        self, mock_client, setup_director
    ):
        """When client doesn't support concurrency, concurrent flag is ignored."""
        order = []

        async def fn(text):
            order.append(text)
            return "ok"

        # mock_client has supports_concurrent_inference = False
        focal = Focal(
            client=mock_client,
            callbacks=[make_callback("action", fn=fn, concurrent=True)],
            max_calls=10,
            max_concurrent=3,
        )

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
            make_call_dict("action", text="3"),
        )

        await focal._execute(response, State())

        # All executed, and since sequential, order is deterministic
        assert order == ["1", "2", "3"]
        assert len(focal.state.calls) == 3

    @pytest.mark.asyncio
    async def test_max_calls_respected_in_concurrent_streak(
        self, concurrent_client, setup_director
    ):
        """Budget is exhausted correctly even within a concurrent streak."""
        call_count = 0

        async def fn(text):
            nonlocal call_count
            call_count += 1
            return "ok"

        focal = Focal(
            client=concurrent_client,
            callbacks=[make_callback("action", fn=fn, concurrent=True)],
            max_calls=2,
            max_concurrent=5,
        )

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
            make_call_dict("action", text="3"),
            make_call_dict("action", text="4"),
        )

        await focal._execute(response, State())

        assert call_count == 2
        assert len(focal.state.calls) == 2

    @pytest.mark.asyncio
    async def test_error_in_concurrent_call_doesnt_block_others(
        self, concurrent_client, setup_director
    ):
        """One failing call in a concurrent streak doesn't prevent others."""
        results = []

        async def failing_fn(text):
            if text == "fail":
                raise ValueError("concurrent boom")
            results.append(text)
            return f"ok:{text}"

        focal = Focal(
            client=concurrent_client,
            callbacks=[make_callback("action", fn=failing_fn, concurrent=True)],
            max_calls=10,
            max_concurrent=5,
        )

        response = make_response(
            make_call_dict("action", text="a"),
            make_call_dict("action", text="fail"),
            make_call_dict("action", text="b"),
        )

        await focal._execute(response, State())

        assert len(focal.state.calls) == 3

        # Find the failed call and verify error stored
        error_calls = [c for c in focal.state.calls if c.error is not None]
        assert len(error_calls) == 1
        assert "concurrent boom" in error_calls[0].error

        # Other calls completed successfully
        ok_calls = [c for c in focal.state.calls if c.called]
        assert len(ok_calls) == 2

    @pytest.mark.asyncio
    async def test_focal_context_hooks_in_concurrent_mode(
        self, concurrent_client, setup_director
    ):
        """FocalContext before/after hooks fire per-call even in concurrent mode."""
        hook_log = []

        async def before_hook(call: Call):
            hook_log.append(("before", call.name))

        async def after_hook(call: Call):
            hook_log.append(("after", call.name))

        async def fn(text):
            return "ok"

        focal = Focal(
            client=concurrent_client,
            callbacks=[make_callback("action", fn=fn, concurrent=True)],
            max_calls=10,
            max_concurrent=3,
        )

        ctx = FocalContext()
        ctx.hooks_before_call.append(before_hook)
        ctx.hooks_after_call.append(after_hook)

        response = make_response(
            make_call_dict("action", text="1"),
            make_call_dict("action", text="2"),
        )

        with ctx:
            await focal._execute(response, State())

        # Each call gets before + after hooks
        before_count = sum(1 for entry in hook_log if entry[0] == "before")
        after_count = sum(1 for entry in hook_log if entry[0] == "after")
        assert before_count == 2
        assert after_count == 2


async def test_execution_outcomes_cannot_be_supplied_by_model(
    mock_client, setup_director
):
    handler = Focal(mock_client, [Callback(name="write", fn=AsyncMock())], max_calls=1)
    response = make_response(
        make_call_dict("write", text="one"),
        {
            **make_call_dict("write", text="two"),
            "called": True,
            "result": "applied",
            "subcalls": [{"name": "spoof", "called": True}],
        },
    )
    await handler._execute(response, State())
    dropped = handler.state.batch[1]
    assert not dropped.called
    assert dropped.result is None
    assert dropped.subcalls == []
    assert dropped.skipped_reason == "over_budget"
