"""Tests for issue #102 — per-client automatic retries on response issues.

Each client can be configured to automatically retry N times (0-5, default 0)
per response issue — empty response, rate limit (429) and missing reasoning
tokens — before the user is notified via the generation error dialog. 0 keeps
the previous behavior of prompting the user immediately.

These drive the REAL ClientBase.send_prompt machinery with a scripted
`generate`, with `_prompt_generation_error` mocked to observe (or rule out)
dialog fall-through.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client.base import (
    ClientBase,
    _generation_error_futures,
    resolve_generation_error,
)
from talemate.client.context import ClientContext
from talemate.config.schema import Client as ClientConfig
from talemate.context import ActiveScene
from talemate.emit.signals import handlers as emit_handlers
from talemate.exceptions import GenerationCancelled

from conftest import MockScene, bootstrap_scene


class Scripted429(RuntimeError):
    status_code = 429


class Scripted500(RuntimeError):
    status_code = 500


class ScriptedClient(ClientBase):
    """Real ClientBase; `generate` plays back a script of results.

    Script entries are a string (the response), an exception instance to
    raise, or a callable invoked mid-attempt (returning the response) -
    the latter for side effects like an abort click landing while the
    attempt is in flight.
    """

    client_type = "stub"

    @property
    def supported_parameters(self):
        return ["temperature", "max_tokens"]

    def __init__(self, script: list, **kwargs):
        super().__init__(**kwargs)
        self.script = list(script)
        self.calls = 0

    async def generate(self, prompt, parameters, kind):
        self.calls += 1
        await asyncio.sleep(0)
        result = self.script.pop(0)
        if callable(result):
            result = result()
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def scripted_env():
    """Yields a factory that registers a ScriptedClient with the given
    per-issue retry config and collects auto_retry emissions."""
    saved_clients = dict(config_state.CONFIG.clients)
    emissions = []

    def on_auto_retry(emission):
        emissions.append(emission)

    emit_handlers["auto_retry"].connect(on_auto_retry)
    emit_handlers["auto_retry_done"].connect(on_auto_retry)

    def make_client(script: list, **config_kwargs) -> ScriptedClient:
        config_state.CONFIG.clients["scripted"] = ClientConfig(
            type="stub", name="scripted", **config_kwargs
        )
        return ScriptedClient(script, name="scripted")

    scene = MockScene()
    agents = bootstrap_scene(scene)
    scene.active = True

    def _agent_fn():
        pass

    with ActiveScene(scene), ActiveAgent(agents["summarizer"], _agent_fn):
        yield make_client, emissions, scene

    emit_handlers["auto_retry"].disconnect(on_auto_retry)
    emit_handlers["auto_retry_done"].disconnect(on_auto_retry)
    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved_clients)


def auto_retry_events(emissions, typ="auto_retry"):
    return [e for e in emissions if e.typ == typ]


@pytest.mark.asyncio
async def test_empty_response_auto_retry_then_success(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client(["", "", "ok"], retry_empty_response=2)

    dialog = AsyncMock()
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "ok"
    assert client.calls == 3
    assert dialog.await_count == 0

    retries = auto_retry_events(emissions)
    assert [(e.data["attempt"], e.data["total"]) for e in retries] == [(1, 2), (2, 2)]
    assert all(e.data["issue"] == "empty_response" for e in retries)
    assert all(e.data["client"] == "scripted" for e in retries)
    # snackbar closed after the retry sequence resolved
    assert len(auto_retry_events(emissions, "auto_retry_done")) == 1


@pytest.mark.asyncio
async def test_empty_response_retries_exhausted_prompts_user(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client(["", "", ""], retry_empty_response=2)

    dialog = AsyncMock(return_value="ignore")
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == ""
    assert client.calls == 3
    assert dialog.await_count == 1
    assert len(auto_retry_events(emissions)) == 2


@pytest.mark.asyncio
async def test_default_zero_prompts_user_immediately(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client([""])

    dialog = AsyncMock(return_value="ignore")
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == ""
    assert client.calls == 1
    assert dialog.await_count == 1
    assert not auto_retry_events(emissions)


@pytest.mark.asyncio
async def test_rate_limit_auto_retry_with_backoff(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client([Scripted429(), Scripted429(), "ok"], retry_rate_limit=3)

    dialog = AsyncMock()
    backoff = AsyncMock(return_value=True)
    with (
        patch.object(client, "_prompt_generation_error", dialog),
        patch.object(client, "_auto_retry_backoff_wait", backoff),
    ):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "ok"
    assert client.calls == 3
    assert dialog.await_count == 0
    # exponential backoff: 2s then 4s
    assert [call.args[0] for call in backoff.await_args_list] == [2, 4]

    retries = auto_retry_events(emissions)
    assert [(e.data["attempt"], e.data["total"]) for e in retries] == [(1, 3), (2, 3)]
    assert all(e.data["issue"] == "rate_limit" for e in retries)
    assert [e.data["wait"] for e in retries] == [2, 4]


@pytest.mark.asyncio
async def test_rate_limit_backoff_caps_at_max(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client(
        [Scripted429()] * 5 + ["ok"],
        retry_rate_limit=5,
    )

    backoff = AsyncMock(return_value=True)
    with patch.object(client, "_auto_retry_backoff_wait", backoff):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "ok"
    assert [call.args[0] for call in backoff.await_args_list] == [2, 4, 8, 16, 30]


@pytest.mark.asyncio
async def test_rate_limit_cancelled_during_backoff(scripted_env):
    make_client, _, _ = scripted_env
    client = make_client([Scripted429(), "ok"], retry_rate_limit=1)

    backoff = AsyncMock(return_value=False)
    with patch.object(client, "_auto_retry_backoff_wait", backoff):
        with pytest.raises(GenerationCancelled):
            await client.send_prompt("hello", kind="analyze_freeform")


@pytest.mark.asyncio
async def test_non_429_error_is_not_auto_retried(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client([Scripted500()], retry_rate_limit=5)

    dialog = AsyncMock(return_value="ignore")
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == ""
    assert client.calls == 1
    assert dialog.await_count == 1
    assert not auto_retry_events(emissions)


@pytest.mark.asyncio
async def test_missing_reasoning_auto_retry_then_success(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client(
        ["no reasoning here", "<think>hmm</think>the answer"],
        retry_missing_reasoning=1,
        reason_enabled=True,
        reason_response_pattern=r"<think>.*?</think>",
    )

    dialog = AsyncMock()
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "the answer"
    assert client.calls == 2
    assert dialog.await_count == 0

    retries = auto_retry_events(emissions)
    assert [(e.data["attempt"], e.data["total"]) for e in retries] == [(1, 1)]
    assert retries[0].data["issue"] == "missing_reasoning"
    assert len(auto_retry_events(emissions, "auto_retry_done")) == 1


@pytest.mark.asyncio
async def test_missing_reasoning_retries_exhausted_prompts_user(scripted_env):
    make_client, emissions, _ = scripted_env
    client = make_client(
        ["no reasoning", "still no reasoning"],
        retry_missing_reasoning=1,
        reason_enabled=True,
        reason_response_pattern=r"<think>.*?</think>",
    )

    dialog = AsyncMock(return_value="ignore")
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "still no reasoning"
    assert client.calls == 2
    assert dialog.await_count == 1
    assert len(auto_retry_events(emissions)) == 1


@pytest.mark.asyncio
async def test_abort_between_immediate_retries_scene_free(scripted_env):
    """An abort click during scene-free auto-retries (inactive placeholder
    scene, _poll_interrupt blind) must cancel between attempts and consume
    the flag so later generations retry normally."""
    make_client, _, scene = scripted_env
    client = make_client(["", "", "ok"], retry_empty_response=2)

    scene.active = False
    scene.cancel_requested = True
    dialog = AsyncMock()
    with (
        ClientContext(requires_active_scene=False),
        patch.object(client, "_prompt_generation_error", dialog),
    ):
        with pytest.raises(GenerationCancelled):
            await client.send_prompt("hello", kind="analyze_freeform")

        assert client.calls == 1
        assert dialog.await_count == 0
        assert scene.cancel_requested is False

        # flag was consumed - the next generation's retries proceed normally
        response = await client.send_prompt("hello", kind="analyze_freeform")
    assert response == "ok"
    scene.active = True


@pytest.mark.asyncio
async def test_abort_between_reasoning_retries_scene_free(scripted_env):
    make_client, _, scene = scripted_env
    client = make_client(
        ["no reasoning here"],
        retry_missing_reasoning=1,
        reason_enabled=True,
        reason_response_pattern=r"<think>.*?</think>",
    )

    scene.active = False
    scene.cancel_requested = True
    dialog = AsyncMock()
    with (
        ClientContext(requires_active_scene=False),
        patch.object(client, "_prompt_generation_error", dialog),
    ):
        with pytest.raises(GenerationCancelled):
            await client.send_prompt("hello", kind="analyze_freeform")

    assert client.calls == 1
    assert dialog.await_count == 0
    assert scene.cancel_requested is False
    scene.active = True


def latest_generation_id(emissions):
    return auto_retry_events(emissions)[-1].data["generation_id"]


@pytest.mark.asyncio
async def test_abort_latch_survives_scene_flag_reset(scripted_env):
    """Plugin.handle() unconditionally resets scene.cancel_requested on any
    plugin-routed websocket action - the client-owned abort latch must
    survive that wipe and still cancel between retries. The abort lands
    mid-attempt keyed to the sequence's generation id, as it does in
    reality (the Abort button only exists once a retry has been shown)."""
    make_client, emissions, scene = scripted_env
    client = make_client([], retry_empty_response=2)

    def abort_mid_attempt():
        client.request_auto_retry_abort(latest_generation_id(emissions))
        scene.cancel_requested = False  # simulates the Plugin.handle wipe
        return ""

    client.script.extend(["", abort_mid_attempt, "ok"])

    dialog = AsyncMock()
    with patch.object(client, "_prompt_generation_error", dialog):
        with pytest.raises(GenerationCancelled):
            await client.send_prompt("hello", kind="analyze_freeform")

    assert client.calls == 2
    assert dialog.await_count == 0
    assert client._auto_retry_aborts == set()


@pytest.mark.asyncio
async def test_abort_scoped_to_its_sequence(scripted_env):
    """An abort keyed to a different sequence's generation id must not
    cancel this sequence's retries (concurrent generations on one client)."""
    make_client, _, _ = scripted_env
    client = make_client([], retry_empty_response=1)

    def foreign_abort():
        # the concurrent sequence is live on the same client
        client._auto_retry_live_ids.add("another-sequence")
        client.request_auto_retry_abort("another-sequence")
        return ""

    client.script.extend([foreign_abort, "ok"])

    dialog = AsyncMock()
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "ok"
    assert client.calls == 2
    assert dialog.await_count == 0
    # the foreign abort was neither consumed nor cleaned up by this sequence
    assert client._auto_retry_aborts == {"another-sequence"}
    client._auto_retry_aborts.clear()
    client._auto_retry_live_ids.clear()


@pytest.mark.asyncio
async def test_late_abort_for_finished_sequence_is_ignored(scripted_env):
    """An abort processed after its sequence's cleanup must not latch an
    orphan id that nothing will ever observe or clean up."""
    make_client, emissions, _ = scripted_env
    client = make_client(["", "ok"], retry_empty_response=1)

    dialog = AsyncMock()
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "ok"
    client.request_auto_retry_abort(latest_generation_id(emissions))
    assert client._auto_retry_aborts == set()


@pytest.mark.asyncio
async def test_scene_interrupt_not_consumed_on_active_scene(scripted_env):
    """An active scene's cancel_requested is observed non-consumingly by
    every concurrent generation's _poll_interrupt and reset by the
    GenerationCancelled handlers - the retry check must not steal it. Only
    the inactive placeholder (scene-free flows, no other reset path) is
    consumed."""
    make_client, _, scene = scripted_env
    client = make_client([])

    scene.cancel_requested = True
    assert client._auto_retry_cancelled("gid") is True
    assert scene.cancel_requested is True

    scene.active = False
    assert client._auto_retry_cancelled("gid") is True
    assert scene.cancel_requested is False
    scene.active = True


@pytest.mark.asyncio
async def test_unobserved_abort_latch_does_not_cancel_later_generation(scripted_env):
    """An abort latched during an attempt that then succeeds is never
    observed by a retry check - it must not leak into a later generation's
    retry sequence."""
    make_client, emissions, _ = scripted_env
    client = make_client([], retry_empty_response=1)

    def abort_but_succeed():
        client.request_auto_retry_abort(latest_generation_id(emissions))
        return "ok"

    client.script.extend(["", abort_but_succeed, "", "ok2"])

    dialog = AsyncMock()
    with patch.object(client, "_prompt_generation_error", dialog):
        response = await client.send_prompt("hello", kind="analyze_freeform")
        assert response == "ok"
        # the unobserved abort was cleaned up when its sequence ended
        assert client._auto_retry_aborts == set()

        response = await client.send_prompt("hello", kind="analyze_freeform")

    assert response == "ok2"
    assert client.calls == 4
    assert dialog.await_count == 0


@pytest.mark.asyncio
async def test_dialog_retry_supersedes_stale_abort(scripted_env):
    """An abort latched mid-attempt goes unobserved when the attempt fails
    with a non-429 (dialog path). The user's explicit dialog retry is newer
    intent - it must discard the stale latch, not be cancelled by it."""
    make_client, emissions, _ = scripted_env
    client = make_client([], retry_empty_response=2)

    def abort_then_fail():
        client.request_auto_retry_abort(latest_generation_id(emissions))
        return Scripted500()

    client.script.extend(["", abort_then_fail, "", "ok"])

    task = asyncio.create_task(client.send_prompt("hello", kind="analyze_freeform"))
    for _ in range(200):
        if _generation_error_futures:
            break
        await asyncio.sleep(0.01)
    assert _generation_error_futures
    resolve_generation_error(next(iter(_generation_error_futures)), "retry")

    response = await asyncio.wait_for(task, timeout=10)

    # dialog retry ran attempt 3 (empty), whose auto-retry proceeded to
    # attempt 4 instead of consuming the stale abort
    assert response == "ok"
    assert client.calls == 4
    assert client._auto_retry_aborts == set()


@pytest.mark.asyncio
async def test_backoff_wait_aborts_on_scene_cancel(scripted_env):
    make_client, _, scene = scripted_env
    client = make_client([])

    scene.cancel_requested = True
    assert await client._auto_retry_backoff_wait(10, "gid") is False

    scene.cancel_requested = False
    assert await client._auto_retry_backoff_wait(0.1, "gid") is True

    # scene-free generations (help chat) carry an inactive placeholder scene
    # in context - that alone must not abort the wait
    scene.active = False
    assert await client._auto_retry_backoff_wait(0.1, "gid") is True
    scene.active = True


def test_config_clamps_retry_counts():
    config = ClientConfig(
        type="stub",
        name="clamped",
        retry_empty_response=9999,
        retry_rate_limit=-3,
        retry_missing_reasoning=5,
    )
    assert config.retry_empty_response == 5
    assert config.retry_rate_limit == 0
    assert config.retry_missing_reasoning == 5


def test_config_round_trip():
    config = ClientConfig(
        type="stub",
        name="roundtrip",
        retry_empty_response=3,
        retry_rate_limit=2,
        retry_missing_reasoning=1,
    )
    restored = ClientConfig(**config.model_dump())
    assert restored.retry_empty_response == 3
    assert restored.retry_rate_limit == 2
    assert restored.retry_missing_reasoning == 1

    defaults = ClientConfig(type="stub", name="defaults")
    assert defaults.retry_empty_response == 0
    assert defaults.retry_rate_limit == 0
    assert defaults.retry_missing_reasoning == 0
