import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import threading
import time
from unittest.mock import Mock

import pytest

from talemate.server.shutdown import drain_server
from talemate.server import shutdown_watchdog


CHILD = """
import asyncio
import atexit
import ctypes
import runpy
import signal
import subprocess
import sys
import threading
import time

shutdown = runpy.run_path(sys.argv[1])["shutdown_server"]
mode = sys.argv[2]
watchdog_failed = mode.startswith("watchdog-spawn-failure")
loop = asyncio.new_event_loop()
started = threading.Event()
release = threading.Event()

class Memory:
    stopping = False

    def refuse_new_memory_work(self):
        self.stopping = True

memory = Memory()

class Server:
    def close(self):
        assert memory.stopping
        release.set()
        if not watchdog_failed:
            signal.raise_signal(signal.SIGINT)

    async def wait_closed(self):
        if mode == "blocked-loop":
            time.sleep(20)
        elif mode == "watchdog-spawn-failure-stalled":
            print("drain stalled", flush=True)
            ctypes.PyDLL(None).sleep(20)

def worker():
    started.set()
    assert release.wait(10)
    if mode == "stuck-native":
        ctypes.PyDLL(None).sleep(20)
    elif mode == "stuck-worker":
        time.sleep(20)
    else:
        time.sleep(0.75 if mode == "watchdog-spawn-failure" else 0.05)
        assert not loop.is_closed()

worker_result = None
if mode in ("normal", "stuck-worker", "stuck-native", "watchdog-spawn-failure"):
    worker_result = loop.run_in_executor(None, worker)
    assert started.wait(5)
if mode == "interpreter-exit":
    atexit.register(time.sleep, 20)
if watchdog_failed:
    def fail_spawn(*args, **kwargs):
        raise OSError("watchdog process unavailable")
    subprocess.Popen = fail_spawn

shutdown(loop, Server(), memory, timeout=5 if mode == "normal" else 0.5)
assert loop.is_closed()
if worker_result is not None:
    worker_result.result()
if watchdog_failed:
    assert signal.getsignal(signal.SIGINT) is signal.SIG_DFL
"""


def test_executor_finishes_before_loop_closes():
    loop = asyncio.new_event_loop()
    release = threading.Event()
    completed = []
    cancelled = []

    class Server:
        def close(self):
            completed.append("connections closed")

        async def wait_closed(self):
            await asyncio.sleep(0)

    def worker():
        assert release.wait(5)
        assert not loop.is_closed()
        completed.append("worker finished")

    async def waiting():
        try:
            await loop.run_in_executor(None, worker)
        finally:
            cancelled.append(True)

    try:
        loop.create_task(waiting())
        loop.run_until_complete(asyncio.sleep(0))
        loop.call_later(0.05, release.set)
        loop.run_until_complete(drain_server(loop, Server()))
        assert cancelled == [True]
        assert completed == ["connections closed", "worker finished"]
    finally:
        release.set()
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


@pytest.mark.parametrize(
    "mode",
    [
        "normal",
        "stuck-worker",
        "blocked-loop",
        "stuck-native",
        "interpreter-exit",
        "watchdog-spawn-failure",
        "watchdog-spawn-failure-stalled",
    ],
)
def test_shutdown_process_deadline(mode):
    if (
        mode in ("stuck-native", "watchdog-spawn-failure-stalled")
        and os.name != "posix"
    ):
        pytest.skip("POSIX libc sleep is used to hold the parent GIL")
    shutdown_path = Path(__file__).parents[2] / "src/talemate/server/shutdown.py"
    started = time.monotonic()
    command = [sys.executable, "-c", textwrap.dedent(CHILD), str(shutdown_path), mode]
    if mode == "watchdog-spawn-failure-stalled":
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        ) as process:
            try:
                with pytest.raises(subprocess.TimeoutExpired) as stalled:
                    process.communicate(timeout=2)
                assert b"drain stalled" in stalled.value.output
                process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=2)
                result = subprocess.CompletedProcess(
                    command, process.returncode, stdout, stderr
                )
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
    else:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    elapsed = time.monotonic() - started
    output = result.stdout + result.stderr
    graceful = mode in ("normal", "watchdog-spawn-failure")
    assert elapsed < (8 if graceful else 4), output
    assert "Traceback" not in output
    assert "terminate called" not in output
    if graceful:
        assert result.returncode == 0, output
        assert "Shutdown complete" in output
        assert "forcing process exit" not in output
    elif mode == "watchdog-spawn-failure-stalled":
        assert result.returncode == -signal.SIGINT, output
        assert "Shutdown complete" not in output
        assert "Shutdown exceeded" not in output
    else:
        assert result.returncode != 0, output
        assert "Shutdown exceeded 0.5 seconds; forcing process exit" in output
        if mode != "interpreter-exit":
            assert "Shutdown complete" not in output
    if mode.startswith("watchdog-spawn-failure"):
        assert "Cannot start shutdown watchdog; continuing without a deadline" in output
        assert "press Ctrl+C again to force exit" in output
        assert "watchdog process unavailable" in output
        assert elapsed > 0.5


@pytest.mark.skipif(os.name != "posix", reason="Filling a nonblocking POSIX pipe")
def test_watchdog_kills_with_full_stderr_pipe():
    reader, writer = os.pipe()
    target = None
    watchdog = None
    try:
        os.set_blocking(writer, False)
        with pytest.raises(BlockingIOError):
            while True:
                os.write(writer, b"x" * 4096)
        os.set_blocking(writer, True)
        target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
        started = time.monotonic()
        watchdog = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                shutdown_watchdog.__file__,
                str(target.pid),
                str(started + 0.25),
                "0.25",
            ],
            stdin=subprocess.PIPE,
            stderr=writer,
        )

        assert target.wait(timeout=3) != 0
        assert time.monotonic() - started < 2
        watchdog.stdin.close()
        assert watchdog.wait(timeout=3) == 0
    finally:
        for process in (target, watchdog):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)
        os.close(reader)
        os.close(writer)


def test_watchdog_tolerates_gone_pid_oserror(monkeypatch):
    kill = Mock(side_effect=OSError(87, "The parameter is incorrect"))
    write = Mock()
    monkeypatch.setattr(shutdown_watchdog.os, "kill", kill)
    monkeypatch.setattr(shutdown_watchdog.os, "write", write)
    monkeypatch.setattr(shutdown_watchdog.os, "_exit", Mock(side_effect=SystemExit(0)))

    with pytest.raises(SystemExit) as stopped:
        shutdown_watchdog.enforce_deadline(123, time.monotonic(), 0, threading.Event())

    assert stopped.value.code == 0
    write.assert_not_called()
