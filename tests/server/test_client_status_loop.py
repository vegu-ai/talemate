"""The status loop that runs while a frontend is connected (issue #338).

A step of the loop that fails must neither end the loop nor starve the steps
after it - `commit_config()` runs last, and a settings change that never
reaches disk is lost without a trace.
"""

from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

import talemate.instance as instance
from talemate.server import api

STEPS = ("emit_clients_status", "agent_ready_checks", "commit_config")


async def _run_until(calls: list, count: int, timeout: float = 5.0):
    """Let the loop run until `calls` holds `count` entries.

    Bounded on purpose: without it a regression that kills the loop would spin
    an xdist worker forever and read as CI trouble instead of a failure.
    """

    async def _wait():
        while len(calls) < count:
            await asyncio.sleep(0)

    await asyncio.wait_for(_wait(), timeout=timeout)


@pytest.fixture
def loop_steps(monkeypatch):
    """Replace the three loop steps with recorders and hand back the call log.

    Call it with the names of the steps that should raise on every cycle.
    """
    calls = []

    def _install(*raising: str):
        for name in STEPS:

            def _fn(name=name):
                async def _step():
                    calls.append(name)
                    if name in raising:
                        raise RuntimeError(f"{name} failed")

                _step.__name__ = name
                return _step

            target = api if name == "commit_config" else instance
            monkeypatch.setattr(target, name, _fn())
        return calls

    return _install


class TestClientStatusLoop:
    @pytest.mark.asyncio
    async def test_loop_continues_after_a_step_raises(self, loop_steps):
        calls = loop_steps("emit_clients_status")

        task = asyncio.create_task(api.client_status_loop(interval=0))
        try:
            await _run_until(calls, 9)
        finally:
            task.cancel()

        assert calls.count("emit_clients_status") >= 3

    @pytest.mark.asyncio
    async def test_a_failing_step_does_not_starve_the_steps_after_it(self, loop_steps):
        calls = loop_steps("emit_clients_status", "agent_ready_checks")

        task = asyncio.create_task(api.client_status_loop(interval=0))
        try:
            await _run_until(calls, 9)
        finally:
            task.cancel()

        assert calls.count("commit_config") >= 3

    @pytest.mark.asyncio
    async def test_loop_stops_on_cancellation(self, loop_steps):
        calls = loop_steps()

        task = asyncio.create_task(api.client_status_loop(interval=0))
        await _run_until(calls, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_a_step_that_keeps_failing_is_logged_once(self, loop_steps):
        calls = loop_steps("commit_config")

        with capture_logs() as logs:
            task = asyncio.create_task(api.client_status_loop(interval=0))
            try:
                await _run_until(calls, 12)
            finally:
                task.cancel()

        errors = [
            entry
            for entry in logs
            if entry.get("log_level") == "error"
            and entry.get("event") == "client status loop"
        ]
        assert len(errors) == 1
        assert errors[0]["step"] == "commit_config"
