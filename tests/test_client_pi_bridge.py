"""Unit tests for the Pi Bridge client.

The pi subprocess is faked with canned JSONL event streams (mirroring pi's
RPC protocol as probed against pi 0.80.x), covering response assembly,
thinking capture, error paths, catalog parsing and per-request process
isolation. No real pi binary or network access is required.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from structlog.testing import capture_logs

import talemate.config.state as config_state
from talemate.client import pi_bridge
from talemate.client.context import ClientContext, set_client_context_attribute
from talemate.exceptions import GenerationCancelled


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _event_line(event: dict) -> bytes:
    return (json.dumps(event) + "\n").encode("utf-8")


class FakeStdin:
    def __init__(self):
        self.written = b""
        self.closed = False
        self.closed_event = asyncio.Event()

    def write(self, data: bytes):
        self.written += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True
        self.closed_event.set()


class FakeProcess:
    """Stands in for the pi RPC subprocess. The stdout reader uses the same
    line limit the client requests from create_subprocess_exec. Models a pi
    that exits as soon as it is waited on (i.e. honors the stdin-EOF
    shutdown request)."""

    def __init__(
        self,
        events: list[dict],
        stderr: bytes = b"",
        stderr_eof=True,
        stdout_eof=True,
    ):
        self.pid = 4242
        self.stdin = FakeStdin()
        self.stdout = asyncio.StreamReader(limit=pi_bridge.PI_STDOUT_LIMIT)
        for event in events:
            self.stdout.feed_data(_event_line(event))
        if stdout_eof:
            self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
        if stderr_eof:
            self.stderr.feed_eof()
        self.returncode = None
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class HangingProcess(FakeProcess):
    """A pi that ignores the stdin-EOF shutdown request and only exits when
    killed (models the orphaned-node hang behind the pi.cmd shim)."""

    def __init__(self, events: list[dict], **kwargs):
        super().__init__(events, **kwargs)
        self._exited = asyncio.Event()

    def kill(self):
        super().kill()
        self._exited.set()

    async def wait(self):
        if self.returncode is None:
            await self._exited.wait()
        return self.returncode


@pytest.fixture
def spawner(monkeypatch):
    """Patch subprocess creation in the pi_bridge module; tests queue fake
    processes and inspect the spawn calls afterwards."""

    class Spawner:
        def __init__(self):
            self.processes: list[FakeProcess] = []
            self.calls: list[dict] = []

        def queue(self, proc: FakeProcess):
            self.processes.append(proc)

        async def spawn(self, *args, **kwargs):
            self.calls.append({"args": args, "kwargs": kwargs})
            return self.processes.pop(0)

    spawner = Spawner()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawner.spawn)
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: "/usr/bin/pi")
    return spawner


@pytest.fixture
def client(spawner):
    """A pi_bridge client with a registered config entry."""
    name = "pi_bridge_test"
    config_state.CONFIG.clients[name] = pi_bridge.ClientConfig(
        type="pi_bridge",
        name=name,
        model="deepseek/deepseek-v4-flash",
    )
    yield pi_bridge.PiBridgeClient(name=name)
    config_state.CONFIG.clients.pop(name, None)


def _assistant_message(
    content: list[dict],
    stop_reason: str = "stop",
    usage: dict | None = None,
    error_message: str | None = None,
) -> dict:
    message = {
        "role": "assistant",
        "content": content,
        "provider": "openrouter",
        "model": "deepseek/deepseek-v4-flash",
        "stopReason": stop_reason,
        "usage": usage or {},
    }
    if error_message:
        message["errorMessage"] = error_message
    return message


def _generation_events(message: dict) -> list[dict]:
    return [
        {"id": "generate", "type": "response", "command": "prompt", "success": True},
        {"type": "agent_start"},
        {"type": "turn_start"},
        {"type": "message_end", "message": {"role": "user", "content": "hi"}},
        {"type": "message_end", "message": message},
        {"type": "turn_end", "message": message, "toolResults": []},
        {"type": "agent_end", "messages": [message]},
        {"type": "agent_settled"},
    ]


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_assembles_text_and_thinking(client, spawner):
    message = _assistant_message(
        [
            {"type": "thinking", "thinking": "pondering the prompt"},
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ],
        usage={"input": 42, "output": 7},
    )
    spawner.queue(FakeProcess(_generation_events(message)))

    response = await client.generate("hi", {}, "conversation")

    assert response == "Hello world"
    assert client._reasoning_response == "pondering the prompt"
    assert client._returned_prompt_tokens == 42
    assert client._returned_response_tokens == 7


@pytest.mark.asyncio
async def test_generate_sends_prompt_command_and_cleans_up(client, spawner):
    message = _assistant_message([{"type": "text", "text": "ok"}])
    proc = FakeProcess(_generation_events(message))
    spawner.queue(proc)

    await client.generate("tell a story", {}, "conversation")

    command = json.loads(proc.stdin.written.decode())
    assert command == {"id": "generate", "type": "prompt", "message": "tell a story"}
    # the resolved binary path is spawned, not the bare name (Windows
    # CreateProcess cannot find npm's pi.cmd shim by bare name)
    assert spawner.calls[0]["args"][0] == "/usr/bin/pi"
    # shutdown is requested via stdin EOF (killing the shim process would
    # orphan node on Windows) and the process exits on its own
    assert proc.stdin.closed
    assert proc.returncode == 0
    assert not proc.killed
    # the raised stream limit is requested from the subprocess reader
    assert spawner.calls[0]["kwargs"]["limit"] == pi_bridge.PI_STDOUT_LIMIT


@pytest.mark.asyncio
async def test_shutdown_falls_back_to_kill_when_pi_ignores_stdin_eof(
    client, spawner, monkeypatch
):
    """A pi that does not exit on stdin EOF is force-killed after the grace
    period instead of hanging generate() forever (issue #126)."""
    monkeypatch.setattr(pi_bridge, "PI_SHUTDOWN_GRACE", 0.01)
    message = _assistant_message([{"type": "text", "text": "ok"}])
    proc = HangingProcess(_generation_events(message))
    spawner.queue(proc)

    assert await client.generate("hi", {}, "conversation") == "ok"
    assert proc.stdin.closed
    assert proc.killed


@pytest.mark.asyncio
async def test_shutdown_kills_process_tree_on_windows(client, spawner, monkeypatch):
    """On Windows the fallback kill must take down the whole tree via
    taskkill - killing only the pi.cmd shim orphans the node process, which
    holds the stdio pipes open and hangs the generation (issue #126)."""
    monkeypatch.setattr(pi_bridge, "PI_SHUTDOWN_GRACE", 0.01)
    monkeypatch.setattr(pi_bridge.sys, "platform", "win32")
    message = _assistant_message([{"type": "text", "text": "ok"}])
    proc = HangingProcess(_generation_events(message))
    spawner.queue(proc)
    spawner.queue(FakeProcess([]))  # stands in for the taskkill process

    assert await client.generate("hi", {}, "conversation") == "ok"
    assert proc.killed
    assert spawner.calls[1]["args"] == ("taskkill", "/F", "/T", "/PID", "4242")


@pytest.mark.asyncio
async def test_cancelled_generation_shuts_down_pi(client, spawner, monkeypatch):
    """Cancelling mid-stream must still shut pi down (stdin EOF, then the
    kill fallback) - on Windows a leaked node process keeps the provider
    request running (issue #126)."""
    monkeypatch.setattr(pi_bridge, "PI_SHUTDOWN_GRACE", 0.01)
    # stream never settles: only the prompt ack arrives, stdout stays open
    proc = HangingProcess(
        [{"id": "generate", "type": "response", "command": "prompt", "success": True}],
        stdout_eof=False,
    )
    spawner.queue(proc)

    task = asyncio.ensure_future(client.generate("hi", {}, "conversation"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert proc.stdin.closed
    assert proc.killed


@pytest.mark.asyncio
async def test_repeated_cancel_during_grace_wait_still_kills(
    client, spawner, monkeypatch
):
    """A second cancellation delivered while cleanup is parked in the
    shutdown grace wait must not skip the kill fallback."""
    monkeypatch.setattr(pi_bridge, "PI_SHUTDOWN_GRACE", 30.0)
    proc = HangingProcess(
        [{"id": "generate", "type": "response", "command": "prompt", "success": True}],
        stdout_eof=False,
    )
    spawner.queue(proc)

    task = asyncio.ensure_future(client.generate("hi", {}, "conversation"))
    await asyncio.sleep(0.05)
    task.cancel()  # lands in _consume_events, unwinds into cleanup
    # deterministic handshake: stdin closing means cleanup reached
    # terminate_pi_process; one extra tick parks it in the grace wait
    await asyncio.wait_for(proc.stdin.closed_event.wait(), timeout=1)
    await asyncio.sleep(0)
    task.cancel()  # impatient repeat cancel
    with pytest.raises(asyncio.CancelledError):
        await task

    assert proc.killed


@pytest.mark.asyncio
async def test_unexpected_exit_reports_partial_stderr_on_drain_timeout(
    client, spawner, monkeypatch
):
    """When stdout EOFs but stderr never closes, the bounded drain must
    surface whatever pi wrote before dying (as a PiBridgeError, not a
    CancelledError from re-awaiting the timed-out drain task)."""
    monkeypatch.setattr(pi_bridge, "PI_STDERR_DRAIN_TIMEOUT", 0.05)
    proc = FakeProcess([], stderr=b"Error: partial diagnosis", stderr_eof=False)
    spawner.queue(proc)

    with pytest.raises(pi_bridge.PiBridgeError, match="partial diagnosis"):
        await client.generate("hi", {}, "conversation")


@pytest.mark.asyncio
async def test_generate_returns_even_if_stderr_never_closes(
    client, spawner, monkeypatch
):
    """Cleanup must not block response delivery on the stderr drain - an
    orphaned grandchild holding the pipe open was exactly the Windows hang:
    the response was fully received but never returned (issue #126)."""
    monkeypatch.setattr(pi_bridge, "PI_STDERR_DRAIN_TIMEOUT", 0.05)
    message = _assistant_message([{"type": "text", "text": "ok"}])
    proc = FakeProcess(_generation_events(message), stderr_eof=False)
    spawner.queue(proc)

    assert await client.generate("hi", {}, "conversation") == "ok"


@pytest.mark.asyncio
async def test_generate_handles_oversized_event_lines(client, spawner):
    """A long thinking session produces a message_end line far beyond
    asyncio's 64KB default readline limit (regression: LimitOverrunError
    surfaced as an empty-response error after minutes of generation)."""
    big_thinking = "pondering the derelict ship " * 10000  # ~280KB single line
    message = _assistant_message(
        [
            {"type": "thinking", "thinking": big_thinking},
            {"type": "text", "text": "done"},
        ]
    )
    spawner.queue(FakeProcess(_generation_events(message)))

    assert await client.generate("hi", {}, "conversation") == "done"
    assert client._reasoning_response == big_thinking


@pytest.mark.asyncio
async def test_generation_error_dialog_shows_pi_message(client, spawner, monkeypatch):
    """Statusless pi failures (missing key, process exit) must surface pi's
    actual error text in the generation error dialog instead of the generic
    empty-response message."""
    spawner.queue(
        FakeProcess(
            [
                {
                    "id": "generate",
                    "type": "response",
                    "command": "prompt",
                    "success": False,
                    "error": "No API key found for openrouter.",
                }
            ]
        )
    )

    captured = {}

    async def fake_dialog(message, status_code=None, generation_id=None):
        captured["message"] = message
        captured["status_code"] = status_code
        return "cancel"

    monkeypatch.setattr(client, "_prompt_generation_error", fake_dialog)

    with ClientContext(requires_active_scene=False):
        set_client_context_attribute("requires_active_scene", False)
        with pytest.raises(GenerationCancelled):
            await client._generate_with_error_handling("hi", {}, "conversation", "gid")

    assert "No API key found for openrouter" in captured["message"]
    assert captured["status_code"] is None


@pytest.mark.asyncio
async def test_generate_error_on_rejected_prompt(client, spawner):
    spawner.queue(
        FakeProcess(
            [
                {
                    "id": "generate",
                    "type": "response",
                    "command": "prompt",
                    "success": False,
                    "error": "No API key found for openrouter.",
                }
            ]
        )
    )

    with pytest.raises(pi_bridge.PiBridgeError, match="No API key found"):
        await client.generate("hi", {}, "conversation")


@pytest.mark.asyncio
async def test_generate_error_on_provider_error(client, spawner):
    message = _assistant_message(
        [],
        stop_reason="error",
        error_message='400: {"message":"not a valid model ID","code":400}',
    )
    spawner.queue(FakeProcess(_generation_events(message)[:5]))

    with pytest.raises(pi_bridge.PiBridgeError, match="not a valid model") as excinfo:
        await client.generate("hi", {}, "conversation")

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_generate_error_on_spawn_failure_names_binary(
    client, spawner, monkeypatch
):
    async def spawn(*args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    with pytest.raises(pi_bridge.PiBridgeError, match="/usr/bin/pi"):
        await client.generate("hi", {}, "conversation")


@pytest.mark.asyncio
async def test_generate_error_on_unexpected_exit(client, spawner):
    spawner.queue(FakeProcess([], stderr=b'Error: Unknown provider "nope".'))

    with pytest.raises(pi_bridge.PiBridgeError, match="Unknown provider"):
        await client.generate("hi", {}, "conversation")


@pytest.mark.asyncio
async def test_generate_error_on_failed_auto_retry(client, spawner):
    spawner.queue(
        FakeProcess(
            [
                {
                    "id": "generate",
                    "type": "response",
                    "command": "prompt",
                    "success": True,
                },
                {"type": "agent_start"},
                {"type": "auto_retry_start", "attempt": 1, "maxAttempts": 3},
                {
                    "type": "auto_retry_end",
                    "success": False,
                    "attempt": 3,
                    "finalError": "529 overloaded_error: Overloaded",
                },
            ]
        )
    )

    with pytest.raises(pi_bridge.PiBridgeError, match="529 overloaded_error"):
        await client.generate("hi", {}, "conversation")


@pytest.mark.asyncio
async def test_generate_skips_protocol_noise(client, spawner):
    message = _assistant_message([{"type": "text", "text": "ok"}])
    proc = FakeProcess([])
    proc.stdout = asyncio.StreamReader()
    proc.stdout.feed_data(b"pi startup banner (not JSON)\n")
    for event in _generation_events(message):
        proc.stdout.feed_data(_event_line(event))
    proc.stdout.feed_eof()
    spawner.queue(proc)

    assert await client.generate("hi", {}, "conversation") == "ok"


@pytest.mark.asyncio
async def test_concurrent_generates_use_isolated_processes(client, spawner):
    """Concurrent requests each get their own pi subprocess (G2)."""
    for text in ("one", "two"):
        spawner.queue(
            FakeProcess(
                _generation_events(_assistant_message([{"type": "text", "text": text}]))
            )
        )

    results = await asyncio.gather(
        client.generate("first", {}, "conversation"),
        client.generate("second", {}, "conversation"),
    )

    assert sorted(results) == ["one", "two"]
    assert len(spawner.calls) == 2


# ---------------------------------------------------------------------------
# command assembly
# ---------------------------------------------------------------------------


def test_build_command_pure_bridge_flags(client):
    command = client._build_command("conversation", "/usr/bin/pi", "/tmp/system.txt")

    assert command[0] == "/usr/bin/pi"
    for flag in (
        "--no-tools",
        "--no-extensions",
        "--no-skills",
        "--no-context-files",
        "--no-prompt-templates",
        "--no-session",
    ):
        assert flag in command

    assert command[command.index("--provider") + 1] == "openrouter"
    assert command[command.index("--model") + 1] == "deepseek/deepseek-v4-flash"
    assert command[command.index("--system-prompt") + 1] == "/tmp/system.txt"
    # reasoning disabled by default
    assert command[command.index("--thinking") + 1] == "off"


def test_build_command_thinking_level(client):
    client.client_config.reason_enabled = True
    client.client_config.effort_level = "high"

    command = client._build_command("conversation", "/usr/bin/pi", "/tmp/system.txt")

    assert command[command.index("--thinking") + 1] == "high"


@pytest.mark.asyncio
async def test_generate_passes_system_prompt_as_file(client, spawner, monkeypatch):
    """The system prompt goes to pi as a file path, never inline on the argv:
    on Windows the resolved pi is npm's pi.cmd and cmd.exe re-parses the
    command line, where the prompt's newlines would truncate it."""
    message = _assistant_message([{"type": "text", "text": "ok"}])
    spawner.queue(FakeProcess(_generation_events(message)))

    system_message = client.get_system_message("conversation")
    seen = {}

    async def spawn(*args, **kwargs):
        path = args[args.index("--system-prompt") + 1]
        seen["path"] = path
        seen["contents"] = open(path, encoding="utf-8").read()
        return spawner.processes.pop(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await client.generate("hi", {}, "conversation")

    assert seen["contents"] == system_message
    assert system_message not in seen["path"]
    # the temporary file is cleaned up once the generation finishes
    assert not os.path.exists(seen["path"])


# ---------------------------------------------------------------------------
# model catalog
# ---------------------------------------------------------------------------


PI_LIST_MODELS_OUTPUT = """provider    model                       context  max-out  thinking  images
openrouter  anthropic/claude-opus-4.5   200K     64K      yes       yes
openrouter  deepseek/deepseek-v4-flash  128K     8.2K     yes       no
my-custom   local-model                 32K      4.1K     no        no
malformed-line-without-model
"""


def test_parse_model_list():
    models = pi_bridge.parse_model_list(PI_LIST_MODELS_OUTPUT)

    assert models == {
        "openrouter": [
            "anthropic/claude-opus-4.5",
            "deepseek/deepseek-v4-flash",
        ],
        "my-custom": ["local-model"],
    }


def test_parse_error_status_code():
    assert pi_bridge.parse_error_status_code("400: bad request") == 400
    assert pi_bridge.parse_error_status_code("generation failed") is None


@pytest.fixture
def catalog_state():
    """Reset the module-level catalog latch/cache around each test."""
    saved = (
        pi_bridge.AVAILABLE_MODELS,
        pi_bridge.MODELS_FETCHED,
        pi_bridge._models_last_attempt,
    )
    pi_bridge.AVAILABLE_MODELS = {}
    pi_bridge.MODELS_FETCHED = False
    pi_bridge._models_last_attempt = None
    yield
    (
        pi_bridge.AVAILABLE_MODELS,
        pi_bridge.MODELS_FETCHED,
        pi_bridge._models_last_attempt,
    ) = saved


class FakeListModelsProcess:
    def __init__(self, stdout: bytes, returncode: int = 0, stderr: bytes = b""):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_fetch_available_models_success(monkeypatch, catalog_state):
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: "/usr/bin/pi")

    async def spawn(*args, **kwargs):
        assert args[0] == "/usr/bin/pi"
        assert "--list-models" in args
        return FakeListModelsProcess(PI_LIST_MODELS_OUTPUT.encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    models = await pi_bridge.fetch_available_models()

    assert pi_bridge.MODELS_FETCHED
    assert "my-custom" in models
    assert pi_bridge.models_for_provider("openrouter") == [
        "anthropic/claude-opus-4.5",
        "deepseek/deepseek-v4-flash",
    ]
    assert pi_bridge.available_providers() == ["my-custom", "openrouter"]


@pytest.mark.asyncio
async def test_fetch_available_models_failure_stays_unlatched(
    monkeypatch, catalog_state
):
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: "/usr/bin/pi")

    async def spawn(*args, **kwargs):
        return FakeListModelsProcess(b"", returncode=1, stderr=b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    models = await pi_bridge.fetch_available_models()

    assert models == {}
    assert not pi_bridge.MODELS_FETCHED
    # cooldown recorded so retries are rate limited
    assert pi_bridge._models_last_attempt is not None


@pytest.mark.asyncio
async def test_fetch_available_models_missing_binary(monkeypatch, catalog_state):
    """pi not being installed is not an error - the startup fetch stays
    silent (debug only); the error belongs to configured pi_bridge clients."""
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: None)

    with capture_logs() as logs:
        models = await pi_bridge.fetch_available_models()

    assert models == {}
    assert not pi_bridge.MODELS_FETCHED
    assert all(entry["log_level"] == "debug" for entry in logs)


@pytest.mark.asyncio
async def test_fetch_available_models_spawn_failure_names_binary(
    monkeypatch, catalog_state
):
    """A spawn-time FileNotFoundError (e.g. WinError 2) is logged with the
    resolved executable path - the raw OS error doesn't name the file."""
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: "/usr/bin/pi")

    async def spawn(*args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    with capture_logs() as logs:
        models = await pi_bridge.fetch_available_models()

    assert models == {}
    assert not pi_bridge.MODELS_FETCHED
    errors = [entry for entry in logs if entry["log_level"] == "error"]
    assert errors and errors[0]["path"] == "/usr/bin/pi"


@pytest.mark.asyncio
async def test_config_save_refreshes_catalog(monkeypatch, catalog_state):
    """Saving the config unlatches and refetches, so models.json changes
    made while the server is running show up without a restart."""
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: "/usr/bin/pi")

    outputs = [
        PI_LIST_MODELS_OUTPUT,
        PI_LIST_MODELS_OUTPUT + "added-provider  new-model  32K  4.1K  no  no\n",
    ]

    async def spawn(*args, **kwargs):
        return FakeListModelsProcess(outputs.pop(0).encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    await pi_bridge.fetch_available_models()
    assert pi_bridge.MODELS_FETCHED
    assert "added-provider" not in pi_bridge.AVAILABLE_MODELS

    # latched: a plain fetch does not refresh
    await pi_bridge.fetch_available_models()
    assert "added-provider" not in pi_bridge.AVAILABLE_MODELS

    await pi_bridge.on_config_saved(None)
    assert pi_bridge.models_for_provider("added-provider") == ["new-model"]


# ---------------------------------------------------------------------------
# Subprocess environment (env variable store injection)
# ---------------------------------------------------------------------------


@pytest.fixture
def env_config():
    """Save/restore the config env store and openrouter key around a test."""
    saved_env = dict(config_state.CONFIG.env)
    saved_openrouter_key = config_state.CONFIG.openrouter.api_key
    yield config_state.CONFIG
    config_state.CONFIG.env = saved_env
    config_state.CONFIG.openrouter.api_key = saved_openrouter_key


@pytest.mark.asyncio
async def test_generate_env_injects_store_and_openrouter_key(
    client, spawner, env_config
):
    env_config.env = {"KIMI_API_KEY": "sk-kimi-secret"}
    env_config.openrouter.api_key = "sk-or-talemate"

    message = _assistant_message([{"type": "text", "text": "ok"}])
    spawner.queue(FakeProcess(_generation_events(message)))

    await client.generate("hi", {}, "conversation")

    env = spawner.calls[0]["kwargs"]["env"]
    assert env["KIMI_API_KEY"] == "sk-kimi-secret"
    assert env["OPENROUTER_API_KEY"] == "sk-or-talemate"


def test_env_store_wins_over_process_env_and_convenience(monkeypatch, env_config):
    monkeypatch.setenv("KIMI_API_KEY", "sk-from-shell")
    env_config.env = {
        "KIMI_API_KEY": "sk-from-store",
        "OPENROUTER_API_KEY": "sk-or-from-store",
    }
    env_config.openrouter.api_key = "sk-or-talemate"

    env = pi_bridge.pi_subprocess_env()

    assert env["KIMI_API_KEY"] == "sk-from-store"
    assert env["OPENROUTER_API_KEY"] == "sk-or-from-store"


def test_empty_store_inherits_process_env(monkeypatch, env_config):
    monkeypatch.setenv("SOME_SHELL_VAR", "shell-value")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_config.env = {}
    env_config.openrouter.api_key = None

    env = pi_bridge.pi_subprocess_env()

    assert env["SOME_SHELL_VAR"] == "shell-value"
    assert "OPENROUTER_API_KEY" not in env


@pytest.mark.asyncio
async def test_list_models_env_injects_store(monkeypatch, catalog_state, env_config):
    """Catalog fetches see the env store, so models.json providers gated on
    $VAR references become visible once the variable is configured."""
    env_config.env = {"KIMI_API_KEY": "sk-kimi-secret"}
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: "/usr/bin/pi")

    seen = {}

    async def spawn(*args, **kwargs):
        seen.update(kwargs)
        return FakeListModelsProcess(PI_LIST_MODELS_OUTPUT.encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    await pi_bridge.fetch_available_models()

    assert seen["env"]["KIMI_API_KEY"] == "sk-kimi-secret"
