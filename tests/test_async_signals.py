import asyncio

import pytest
import structlog

from talemate.client.base import ClientDisabledError
from talemate.emit.async_signals import AsyncSignal
from talemate.exceptions import (
    AbortCommand,
    AbortWaitForInput,
    ActedAsCharacter,
    ControlFlowException,
    ExitScene,
    GenerationCancelled,
    ResetScene,
    RestartSceneLoop,
    SceneInactiveError,
)
from talemate.game.engine.nodes.core import (
    PASSTHROUGH_ERRORS,
    LoopBreak,
    LoopContinue,
    LoopExit,
    StopModule,
)


class Emission:
    pass


def make_recorder(calls: list, name: str, error: BaseException | None = None):
    async def receiver(emission):
        calls.append(name)
        if error:
            raise error

    return receiver


async def test_send_isolates_receiver_error():
    calls = []
    signal = AsyncSignal("test_signal")
    signal.connect(make_recorder(calls, "first", ValueError("boom")))
    signal.connect(make_recorder(calls, "second"))

    await signal.send(Emission())

    assert calls == ["first", "second"]


async def test_send_logs_receiver_error():
    signal = AsyncSignal("test_signal")
    signal.connect(make_recorder([], "first", ValueError("boom")))

    with structlog.testing.capture_logs() as logs:
        await signal.send(Emission())

    errors = [entry for entry in logs if entry["log_level"] == "error"]
    assert len(errors) == 1
    assert errors[0]["signal"] == "test_signal"
    assert errors[0]["receiver"]
    assert "ValueError: boom" in errors[0]["error"]


async def test_send_preserves_delivery_order():
    calls = []
    signal = AsyncSignal("test_signal")
    signal.connect(make_recorder(calls, "one"))
    signal.connect(make_recorder(calls, "two", ValueError("boom")))
    signal.connect(make_recorder(calls, "three"))
    signal.connect(make_recorder(calls, "four"))

    await signal.send(Emission())

    assert calls == ["one", "two", "three", "four"]


@pytest.mark.parametrize(
    "error",
    [
        ExitScene(),
        RestartSceneLoop(),
        ResetScene(),
        GenerationCancelled("cancelled"),
        ActedAsCharacter("Bob"),
        AbortCommand(),
        AbortWaitForInput(),
        LoopContinue(),
        LoopBreak(),
        LoopExit(),
        asyncio.CancelledError(),
    ],
)
async def test_send_propagates_control_flow(error):
    calls = []
    signal = AsyncSignal("test_signal")
    signal.connect(make_recorder(calls, "first", error))
    signal.connect(make_recorder(calls, "second"))

    with pytest.raises(type(error)):
        await signal.send(Emission())

    assert calls == ["first"]


def test_control_flow_family_is_intact():
    assert issubclass(AbortCommand, IOError)
    assert issubclass(AbortWaitForInput, IOError)
    assert all(issubclass(error, ControlFlowException) for error in PASSTHROUGH_ERRORS)
    assert not issubclass(StopModule, ControlFlowException)
    assert not issubclass(SceneInactiveError, ControlFlowException)
    assert not issubclass(ClientDisabledError, ControlFlowException)


async def test_send_returns_no_failures_on_clean_delivery():
    calls = []
    signal = AsyncSignal("test_signal")
    signal.connect(make_recorder(calls, "one"))
    signal.connect(make_recorder(calls, "two"))

    assert await signal.send(Emission()) == []
    assert calls == ["one", "two"]


async def test_send_returns_the_failing_receiver_and_its_error():
    calls = []
    error = ValueError("boom")
    signal = AsyncSignal("test_signal")
    failing = make_recorder(calls, "first", error)
    signal.connect(failing)
    signal.connect(make_recorder(calls, "second"))

    failures = await signal.send(Emission())

    assert len(failures) == 1
    assert failures[0][0] is failing
    assert failures[0][1] is error
    assert calls == ["first", "second"]


async def test_connect_dedupes_and_disconnect_is_forgiving():
    calls = []
    signal = AsyncSignal("test_signal")
    receiver = make_recorder(calls, "only")
    signal.connect(receiver)
    signal.connect(receiver)

    await signal.send(Emission())
    assert calls == ["only"]

    signal.disconnect(make_recorder(calls, "unknown"))
    signal.disconnect(receiver)

    await signal.send(Emission())
    assert calls == ["only"]
