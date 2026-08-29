"""Regression tests for issue #54.

Summarization hitting the retry dialogue was not persisted even when the
retry eventually worked: each concurrently failing generation registers its
own future in ``_generation_error_futures``, but the frontend dialog used to
track only a single request_id, so a second ``generation_error`` event
orphaned the first request — its coroutine waited on the dialog future
forever and its result (e.g. the archive entry) was silently lost.

These tests drive the REAL ClientBase.send_prompt retry machinery (unlike
conftest.MockClient, which overrides send_prompt entirely) with a flaky
`generate` that fails and then succeeds, while a driver task plays the user
answering the generation error dialog via resolve_generation_error().
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

import talemate.config.state as config_state
import talemate.util as util
from talemate.agents.context import ActiveAgent
from talemate.client.base import (
    ClientBase,
    _generation_error_futures,
    resolve_all_generation_errors,
    resolve_generation_error,
)
from talemate.config.schema import Client as ClientConfig
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.scene_message import CharacterMessage

from conftest import MockScene, bootstrap_scene


class FlakyClient(ClientBase):
    """Real ClientBase; only `generate` is stubbed to fail N times then succeed."""

    client_type = "stub"

    @property
    def supported_parameters(self):
        return ["temperature", "max_tokens"]

    def __init__(self, fail_times: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.fail_times = fail_times
        self.calls = 0

    async def generate(self, prompt, parameters, kind):
        self.calls += 1
        await asyncio.sleep(0.01)
        if self.calls <= self.fail_times:
            raise RuntimeError("simulated API throttle (429)")
        return (
            "SUMMARY: Alice and Bob talked about many important things at the tavern."
        )


def _char_count_tokens(source):
    if isinstance(source, list):
        return sum(_char_count_tokens(s) for s in source)
    return len(str(source))


@pytest.fixture
def flaky_setup():
    saved_clients = dict(config_state.CONFIG.clients)
    config_state.CONFIG.clients["flaky"] = ClientConfig(type="stub", name="flaky")

    scene = MockScene()
    agents = bootstrap_scene(scene)
    summarizer = agents["summarizer"]

    client = FlakyClient(fail_times=1, name="flaky")
    summarizer.client = client

    scene.active = True

    with patch.object(util, "count_tokens", side_effect=_char_count_tokens):
        yield scene, summarizer, client

    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved_clients)


def _fill_history_past_threshold(scene, summarizer):
    threshold = summarizer.archive_threshold
    line = "We talked about the weather and the harvest for a long while."
    n_messages = (threshold // len(line)) + 3
    for i in range(n_messages):
        scene.history.append(
            CharacterMessage(message=f"Alice: {line} ({i})", source="ai")
        )


async def _dialog_queue_driver(stop: asyncio.Event, action: str = "retry"):
    """Plays the user against the queued GenerationErrorDialog contract:
    every generation error that appears is answered, oldest first."""
    seen: set[str] = set()
    fifo: list[str] = []
    while not stop.is_set():
        for rid in _generation_error_futures:
            if rid not in seen:
                seen.add(rid)
                fifo.append(rid)
        if fifo:
            # human-ish delay before clicking, allowing concurrent errors
            # to pile up in the queue first
            await asyncio.sleep(0.2)
            resolve_generation_error(fifo.pop(0), action)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_build_archive_persists_after_retry(flaky_setup):
    """Single failing request: retry via the dialog future, archive persists."""
    scene, summarizer, client = flaky_setup
    _fill_history_past_threshold(scene, summarizer)

    assert not scene.archived_history

    stop = asyncio.Event()
    driver = asyncio.create_task(_dialog_queue_driver(stop))
    try:
        with ActiveScene(scene):
            result = await asyncio.wait_for(summarizer.build_archive(scene), timeout=30)
    finally:
        stop.set()
        driver.cancel()

    assert result is True
    assert client.calls >= 2, "expected at least one failure + one retry"
    assert scene.archived_history, (
        "summarization was not persisted to the scene after successful retry"
    )


@pytest.mark.asyncio
async def test_concurrent_failures_all_get_answered(flaky_setup):
    """Issue #54: a second failing generation (e.g. the TTS markup call that
    runs on a background queue task) must not orphan the summarizer's error
    dialog. With the queued dialog contract both requests are answered and
    the summarization persists."""
    scene, summarizer, client = flaky_setup
    _fill_history_past_threshold(scene, summarizer)

    bg_client = FlakyClient(fail_times=1, name="flaky")

    async def background_llm_call():
        def _fn():
            pass

        with ActiveScene(scene):
            with ActiveAgent(summarizer, _fn):
                return await bg_client.send_prompt(
                    "some background prompt", kind="analyze_freeform"
                )

    stop = asyncio.Event()
    driver = asyncio.create_task(_dialog_queue_driver(stop))
    try:
        with ActiveScene(scene):
            summarize_task = asyncio.create_task(summarizer.build_archive(scene))
            bg_task = asyncio.create_task(background_llm_call())
            done, pending = await asyncio.wait([summarize_task, bg_task], timeout=15)
    finally:
        stop.set()
        driver.cancel()
        for t in (summarize_task, bg_task):
            t.cancel()

    assert not pending, (
        f"{len(pending)} coroutine(s) hung waiting on an orphaned "
        "generation-error dialog future"
    )
    for t in done:
        assert t.exception() is None
    assert client.calls >= 2
    assert bg_client.calls >= 2
    assert scene.archived_history, "summarization was not persisted"
    assert not _generation_error_futures


@pytest.mark.asyncio
async def test_resolve_all_generation_errors_cancels_pending(flaky_setup):
    """When no user response can arrive anymore (frontend disconnect, scene
    unload), pending error dialogs resolve to cancel so their coroutines
    terminate instead of hanging forever."""
    scene, summarizer, client = flaky_setup
    _fill_history_past_threshold(scene, summarizer)

    with ActiveScene(scene):
        summarize_task = asyncio.create_task(summarizer.build_archive(scene))

        # wait for the failure to register its dialog future
        for _ in range(100):
            if _generation_error_futures:
                break
            await asyncio.sleep(0.05)
        assert _generation_error_futures

        resolve_all_generation_errors("cancel")

        with pytest.raises(GenerationCancelled):
            await asyncio.wait_for(summarize_task, timeout=5)

    assert not _generation_error_futures
    assert not scene.archived_history
