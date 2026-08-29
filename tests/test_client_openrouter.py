"""Unit tests for the OpenRouter model/provider list fetchers.

Regression coverage for the sticky-failure latch (PR #46 follow-up): a fetch
that fails (or runs before an API key is configured) must NOT mark the list
as fetched, so the retry triggers (config saves, client status refreshes)
can recover without a server restart. On a fresh setup this previously left
the model list empty until restart.
"""

from __future__ import annotations

import types

import pytest

from talemate.client import openrouter as orc


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Stands in for httpx.AsyncClient; delegates GETs to a responder."""

    def __init__(self, responder, calls):
        self._responder = responder
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self._calls.append(url)
        result = self._responder(url)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def fetch_state():
    """Reset the module-level fetch latches/caches around each test."""
    saved = (
        orc.AVAILABLE_MODELS,
        orc.AVAILABLE_PROVIDERS,
        orc.MODELS_FETCHED,
        orc.PROVIDERS_FETCHED,
        orc._models_last_attempt,
        orc._providers_last_attempt,
    )
    orc.AVAILABLE_MODELS = []
    orc.AVAILABLE_PROVIDERS = []
    orc.MODELS_FETCHED = False
    orc.PROVIDERS_FETCHED = False
    orc._models_last_attempt = None
    orc._providers_last_attempt = None
    yield
    (
        orc.AVAILABLE_MODELS,
        orc.AVAILABLE_PROVIDERS,
        orc.MODELS_FETCHED,
        orc.PROVIDERS_FETCHED,
        orc._models_last_attempt,
        orc._providers_last_attempt,
    ) = saved


@pytest.fixture
def http(monkeypatch, fetch_state):
    """Patch httpx.AsyncClient in the openrouter module; returns a control
    object whose `responder` decides each request's outcome and whose `calls`
    records requested URLs."""
    control = types.SimpleNamespace(responder=None, calls=[])

    def make_client(*args, **kwargs):
        return FakeAsyncClient(lambda url: control.responder(url), control.calls)

    monkeypatch.setattr(orc.httpx, "AsyncClient", make_client)
    return control


MODELS_PAYLOAD = {"data": [{"id": "z/model-b"}, {"id": "a/model-a"}, {"id": None}]}
PROVIDERS_PAYLOAD = {"data": [{"name": "Beta"}, {"name": "Alpha"}, {"name": None}]}


@pytest.mark.asyncio
async def test_models_fetch_success_latches(http):
    http.responder = lambda url: FakeResponse(200, MODELS_PAYLOAD)

    result = await orc.fetch_available_models()

    assert result == ["a/model-a", "z/model-b"]
    assert orc.MODELS_FETCHED is True

    # latched — no further requests
    http.calls.clear()
    await orc.fetch_available_models()
    assert http.calls == []


@pytest.mark.asyncio
async def test_models_fetch_failure_does_not_latch_and_recovers(http):
    http.responder = lambda url: ConnectionError("network down")

    result = await orc.fetch_available_models()
    assert result == []
    assert orc.MODELS_FETCHED is False

    # network recovers; bypass the retry cooldown
    orc._models_last_attempt = None
    http.responder = lambda url: FakeResponse(200, MODELS_PAYLOAD)

    result = await orc.fetch_available_models()
    assert result == ["a/model-a", "z/model-b"]
    assert orc.MODELS_FETCHED is True


@pytest.mark.asyncio
async def test_models_fetch_http_error_does_not_latch(http):
    http.responder = lambda url: FakeResponse(500)

    await orc.fetch_available_models()
    assert orc.MODELS_FETCHED is False


@pytest.mark.asyncio
async def test_models_fetch_retry_respects_cooldown(http):
    http.responder = lambda url: ConnectionError("network down")

    await orc.fetch_available_models()
    assert len(http.calls) == 1

    # immediate retry is skipped (cooldown), no new request
    await orc.fetch_available_models()
    assert len(http.calls) == 1
    assert orc.MODELS_FETCHED is False


@pytest.mark.asyncio
async def test_models_first_fetch_not_cooled_down_on_low_monotonic(http, monkeypatch):
    # On a freshly-booted host time.monotonic() can be < FETCH_RETRY_COOLDOWN;
    # the never-attempted sentinel must not read as a recent attempt.
    monkeypatch.setattr(orc.time, "monotonic", lambda: 1.0)
    http.responder = lambda url: FakeResponse(200, MODELS_PAYLOAD)

    result = await orc.fetch_available_models()

    assert result == ["a/model-a", "z/model-b"]
    assert orc.MODELS_FETCHED is True
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_providers_fetch_without_key_does_not_latch(http, monkeypatch):
    monkeypatch.setattr(
        orc,
        "get_config",
        lambda: types.SimpleNamespace(openrouter=types.SimpleNamespace(api_key=None)),
    )

    await orc.fetch_available_providers(None)
    assert orc.PROVIDERS_FETCHED is False
    assert http.calls == []

    # key arrives later (e.g. set during initial setup) — fetch now works
    http.responder = lambda url: FakeResponse(200, PROVIDERS_PAYLOAD)
    result = await orc.fetch_available_providers("sk-or-key")
    assert result == ["Alpha", "Beta"]
    assert orc.PROVIDERS_FETCHED is True


@pytest.mark.asyncio
async def test_providers_fetch_failure_does_not_latch_and_recovers(http):
    http.responder = lambda url: ConnectionError("network down")

    await orc.fetch_available_providers("sk-or-key")
    assert orc.PROVIDERS_FETCHED is False

    orc._providers_last_attempt = None
    http.responder = lambda url: FakeResponse(200, PROVIDERS_PAYLOAD)

    result = await orc.fetch_available_providers("sk-or-key")
    assert result == ["Alpha", "Beta"]
    assert orc.PROVIDERS_FETCHED is True
