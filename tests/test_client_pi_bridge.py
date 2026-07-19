"""Unit tests for the Pi Bridge client.

The pi subprocess is faked with canned JSONL event streams (mirroring pi's
RPC protocol as probed against pi 0.80.x), covering response assembly,
thinking capture, error paths, catalog parsing and per-request process
isolation. No real pi binary or network access is required.
"""

from __future__ import annotations

import asyncio
import json

import pytest

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

    def write(self, data: bytes):
        self.written += data

    async def drain(self):
        pass


class FakeProcess:
    """Stands in for the pi RPC subprocess. The stdout reader uses the same
    line limit the client requests from create_subprocess_exec."""

    def __init__(self, events: list[dict], stderr: bytes = b""):
        self.stdin = FakeStdin()
        self.stdout = asyncio.StreamReader(limit=pi_bridge.PI_STDOUT_LIMIT)
        for event in events:
            self.stdout.feed_data(_event_line(event))
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
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
    # the subprocess is terminated after the response
    assert proc.killed
    # the raised stream limit is requested from the subprocess reader
    assert spawner.calls[0]["kwargs"]["limit"] == pi_bridge.PI_STDOUT_LIMIT


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
    command = client._build_command("conversation")

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
    # reasoning disabled by default
    assert command[command.index("--thinking") + 1] == "off"


def test_build_command_thinking_level(client):
    client.client_config.reason_enabled = True
    client.client_config.effort_level = "high"

    command = client._build_command("conversation")

    assert command[command.index("--thinking") + 1] == "high"


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
    monkeypatch.setattr(pi_bridge.shutil, "which", lambda _: None)

    models = await pi_bridge.fetch_available_models()

    assert models == {}
    assert not pi_bridge.MODELS_FETCHED


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
