"""Unit tests for the OpenRouter model/provider list fetchers.

Regression coverage for the sticky-failure latch (PR #46 follow-up): a fetch
that fails (or runs before an API key is configured) must NOT mark the list
as fetched, so the retry triggers (config saves, client status refreshes)
can recover without a server restart. On a fresh setup this previously left
the model list empty until restart.

The image model list (#730) comes from the Image API's own model list: the
general model list only holds models that output text, so image-only models
were missing from the Visualizer's choices.
"""

from __future__ import annotations

import asyncio
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
def fetch_state(monkeypatch):
    """Fresh module-level lists, fetch states and key digest for each test;
    records the emits the fetchers send."""
    monkeypatch.setattr(orc, "AVAILABLE_MODELS", [])
    monkeypatch.setattr(orc, "IMAGE_MODELS", {})
    monkeypatch.setattr(orc, "AVAILABLE_PROVIDERS", [])
    monkeypatch.setattr(orc, "MODELS_FETCH", orc.ListFetch())
    monkeypatch.setattr(orc, "IMAGE_MODELS_FETCH", orc.ListFetch())
    monkeypatch.setattr(orc, "PROVIDERS_FETCH", orc.ListFetch())
    monkeypatch.setattr(orc, "_lists_key_digest", None)
    emits = []
    monkeypatch.setattr(orc, "emit", lambda typ, *args, **kwargs: emits.append(typ))
    return emits


@pytest.fixture
def http(monkeypatch, fetch_state):
    """Patch httpx.AsyncClient in the openrouter module; returns a control
    object whose `responder` decides each request's outcome, whose `calls`
    records requested URLs and whose `emits` records sent emit types."""
    control = types.SimpleNamespace(responder=None, calls=[], emits=fetch_state)

    def make_client(*args, **kwargs):
        return FakeAsyncClient(lambda url: control.responder(url), control.calls)

    monkeypatch.setattr(orc.httpx, "AsyncClient", make_client)
    return control


MODELS_PAYLOAD = {"data": [{"id": "z/model-b"}, {"id": "a/model-a"}, {"id": None}]}
PROVIDERS_PAYLOAD = {"data": [{"name": "Beta"}, {"name": "Alpha"}, {"name": None}]}

# shapes taken from the live GET /api/v1/images/models (2026-09-22)
IMAGE_MODELS_PAYLOAD = {
    "data": [
        {
            "id": "meta/muse-image",
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["image"],
            },
            "supported_parameters": {},
        },
        {
            "id": "inclusionai/ming-image-0.1-design",
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            },
            "supported_parameters": {
                "output_format": {"type": "enum", "values": ["png", "jpeg", "webp"]},
                "n": {"type": "range", "min": 1, "max": 1},
                "input_references": {"type": "range", "min": 0, "max": 0},
            },
        },
        {
            "id": "google/gemini-3-pro-image-preview",
            "architecture": {
                "input_modalities": ["image", "text"],
                "output_modalities": ["image", "text"],
            },
            "supported_parameters": {
                "aspect_ratio": {"type": "enum", "values": ["1:1", "16:9", "9:16"]},
                "input_references": {"type": "range", "min": 0, "max": 14},
            },
        },
        {
            "id": "recraft/recraft-v4-vector",
            "architecture": {"output_modalities": ["image"]},
            "supported_parameters": {
                "output_format": {"type": "enum", "values": ["svg"]},
            },
        },
        {"id": None},
    ]
}


def respond_by_url(url):
    if url == orc.IMAGE_MODELS_URL:
        return FakeResponse(200, IMAGE_MODELS_PAYLOAD)
    if url == orc.PROVIDERS_URL:
        return FakeResponse(200, PROVIDERS_PAYLOAD)
    return FakeResponse(200, MODELS_PAYLOAD)


def saved_config(api_key):
    return types.SimpleNamespace(openrouter=types.SimpleNamespace(api_key=api_key))


@pytest.mark.asyncio
async def test_models_fetch_success_latches(http):
    http.responder = lambda url: FakeResponse(200, MODELS_PAYLOAD)

    result = await orc.fetch_available_models()

    assert result == ["a/model-a", "z/model-b"]
    assert orc.MODELS_FETCH.fetched is True

    # latched — no further requests
    http.calls.clear()
    await orc.fetch_available_models()
    assert http.calls == []


@pytest.mark.asyncio
async def test_models_fetch_failure_does_not_latch_and_recovers(http):
    http.responder = lambda url: ConnectionError("network down")

    result = await orc.fetch_available_models()
    assert result == []
    assert orc.MODELS_FETCH.fetched is False

    # network recovers; bypass the retry cooldown
    orc.MODELS_FETCH.last_attempt = None
    http.responder = lambda url: FakeResponse(200, MODELS_PAYLOAD)

    result = await orc.fetch_available_models()
    assert result == ["a/model-a", "z/model-b"]
    assert orc.MODELS_FETCH.fetched is True


@pytest.mark.asyncio
async def test_models_fetch_http_error_does_not_latch(http):
    http.responder = lambda url: FakeResponse(500)

    await orc.fetch_available_models()
    assert orc.MODELS_FETCH.fetched is False


@pytest.mark.asyncio
async def test_models_fetch_retry_respects_cooldown(http):
    http.responder = lambda url: ConnectionError("network down")

    await orc.fetch_available_models()
    assert len(http.calls) == 1

    # immediate retry is skipped (cooldown), no new request
    await orc.fetch_available_models()
    assert len(http.calls) == 1
    assert orc.MODELS_FETCH.fetched is False


@pytest.mark.asyncio
async def test_models_first_fetch_not_cooled_down_on_low_monotonic(http, monkeypatch):
    # On a freshly-booted host time.monotonic() can be < FETCH_RETRY_COOLDOWN;
    # the never-attempted sentinel must not read as a recent attempt.
    monkeypatch.setattr(orc.time, "monotonic", lambda: 1.0)
    http.responder = lambda url: FakeResponse(200, MODELS_PAYLOAD)

    result = await orc.fetch_available_models()

    assert result == ["a/model-a", "z/model-b"]
    assert orc.MODELS_FETCH.fetched is True
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_providers_fetch_without_key_does_not_latch(http, monkeypatch):
    monkeypatch.setattr(
        orc,
        "get_config",
        lambda: types.SimpleNamespace(openrouter=types.SimpleNamespace(api_key=None)),
    )

    await orc.fetch_available_providers(None)
    assert orc.PROVIDERS_FETCH.fetched is False
    assert http.calls == []

    # key arrives later (e.g. set during initial setup) — fetch now works
    http.responder = lambda url: FakeResponse(200, PROVIDERS_PAYLOAD)
    result = await orc.fetch_available_providers("sk-or-key")
    assert result == ["Alpha", "Beta"]
    assert orc.PROVIDERS_FETCH.fetched is True


@pytest.mark.asyncio
async def test_providers_fetch_failure_does_not_latch_and_recovers(http):
    http.responder = lambda url: ConnectionError("network down")

    await orc.fetch_available_providers("sk-or-key")
    assert orc.PROVIDERS_FETCH.fetched is False

    orc.PROVIDERS_FETCH.last_attempt = None
    http.responder = lambda url: FakeResponse(200, PROVIDERS_PAYLOAD)

    result = await orc.fetch_available_providers("sk-or-key")
    assert result == ["Alpha", "Beta"]
    assert orc.PROVIDERS_FETCH.fetched is True


@pytest.mark.asyncio
async def test_image_models_fetch_reads_the_image_api_list(http):
    http.responder = respond_by_url

    result = await orc.fetch_available_image_models()

    assert http.calls == [orc.IMAGE_MODELS_URL]
    assert orc.IMAGE_MODELS_FETCH.fetched is True
    # sorted by id; the entry without an id is left out
    assert list(result) == [
        "google/gemini-3-pro-image-preview",
        "inclusionai/ming-image-0.1-design",
        "meta/muse-image",
        "recraft/recraft-v4-vector",
    ]

    gemini = result["google/gemini-3-pro-image-preview"]
    assert gemini.outputs_text is True
    assert gemini.aspect_ratios == ["1:1", "16:9", "9:16"]
    assert (gemini.min_references, gemini.max_references) == (0, 14)

    ming = result["inclusionai/ming-image-0.1-design"]
    assert ming.outputs_text is False
    assert ming.aspect_ratios == []
    assert ming.output_formats == ["png", "jpeg", "webp"]
    assert ming.takes_references is False
    assert ming.needs_references is False

    # Muse lists no parameters: no known limits
    muse = result["meta/muse-image"]
    assert muse.outputs_text is False
    assert muse.aspect_ratios == []
    assert muse.output_formats == []
    assert (muse.min_references, muse.max_references) == (None, None)
    assert muse.takes_references is True

    # kept for the routing, which names the reason; the choices leave it out
    assert result["recraft/recraft-v4-vector"].svg_only is True


@pytest.mark.asyncio
async def test_a_malformed_image_model_entry_is_skipped(http):
    http.responder = lambda url: FakeResponse(
        200,
        {
            "data": [
                {"id": "a/broken-model", "supported_parameters": ["not", "a", "map"]},
                {
                    "id": "b/styles-model",
                    "architecture": {"output_modalities": ["image"]},
                    "supported_parameters": {
                        "input_references": {"type": "range", "min": 1, "max": 10}
                    },
                },
            ]
        },
    )

    result = await orc.fetch_available_image_models()

    assert list(result) == ["b/styles-model"]
    assert result["b/styles-model"].needs_references is True
    assert orc.IMAGE_MODELS_FETCH.fetched is True


@pytest.mark.asyncio
async def test_refresh_fetches_a_loaded_image_list_again_after_the_cooldown(http):
    http.responder = respond_by_url
    await orc.fetch_available_image_models()
    http.calls.clear()

    # inside the cooldown of the fetch that loaded the list: nothing is sent
    await orc.fetch_available_image_models(refresh=True)
    assert http.calls == []

    newer = {"data": IMAGE_MODELS_PAYLOAD["data"] + [{"id": "new/image-model"}]}
    http.responder = lambda url: FakeResponse(200, newer)
    orc.IMAGE_MODELS_FETCH.last_attempt -= orc.FETCH_RETRY_COOLDOWN
    result = await orc.fetch_available_image_models(refresh=True)

    assert http.calls == [orc.IMAGE_MODELS_URL]
    assert "new/image-model" in result
    assert "new/image-model" in orc.IMAGE_MODELS


@pytest.mark.asyncio
async def test_image_models_fetch_failure_does_not_latch(http):
    http.responder = lambda url: FakeResponse(500)

    result = await orc.fetch_available_image_models()

    assert result == {}
    assert orc.IMAGE_MODELS_FETCH.fetched is False


@pytest.mark.asyncio
async def test_list_change_requests_agent_status(http):
    http.responder = respond_by_url

    await orc.fetch_available_models()
    await orc.fetch_available_image_models()
    assert http.emits == ["request_agent_status", "request_agent_status"]

    # a refetch with the same content sends nothing
    orc.MODELS_FETCH.reset()
    await orc.fetch_available_models()
    assert http.emits == ["request_agent_status", "request_agent_status"]


@pytest.mark.asyncio
async def test_config_save_with_the_same_key_keeps_the_fetched_lists(http):
    http.responder = respond_by_url

    await orc.on_config_saved(saved_config("sk-or-a"))
    assert sorted(http.calls) == sorted(
        [orc.MODELS_URL, orc.IMAGE_MODELS_URL, orc.PROVIDERS_URL]
    )

    http.calls.clear()
    await orc.on_config_saved(saved_config("sk-or-a"))
    assert http.calls == []


@pytest.mark.asyncio
async def test_config_save_with_a_new_key_fetches_every_list_again(http):
    http.responder = respond_by_url
    await orc.on_config_saved(saved_config("sk-or-a"))

    http.calls.clear()
    await orc.on_config_saved(saved_config("sk-or-b"))

    # inside the retry cooldown of the first fetch, so the reset is what allows it
    assert sorted(http.calls) == sorted(
        [orc.MODELS_URL, orc.IMAGE_MODELS_URL, orc.PROVIDERS_URL]
    )
    assert orc.MODELS_FETCH.fetched is True
    assert orc.IMAGE_MODELS_FETCH.fetched is True
    assert orc.PROVIDERS_FETCH.fetched is True


@pytest.mark.asyncio
async def test_config_save_with_the_same_key_retries_a_failed_list(http):
    http.responder = lambda url: (
        FakeResponse(503) if url == orc.IMAGE_MODELS_URL else respond_by_url(url)
    )
    await orc.on_config_saved(saved_config("sk-or-a"))
    assert orc.IMAGE_MODELS_FETCH.fetched is False

    http.responder = respond_by_url
    orc.IMAGE_MODELS_FETCH.last_attempt = None
    http.calls.clear()
    await orc.on_config_saved(saved_config("sk-or-a"))

    assert http.calls == [orc.IMAGE_MODELS_URL]
    assert "meta/muse-image" in orc.IMAGE_MODELS


@pytest.mark.asyncio
async def test_talemate_start_records_the_key_it_fetched_for(http, monkeypatch):
    monkeypatch.setattr(orc, "get_config", lambda: saved_config("sk-or-a"))
    started = []

    async def fetch_lists(api_key):
        started.append(api_key)

    monkeypatch.setattr(orc, "fetch_lists", fetch_lists)

    orc.on_talemate_started(None)
    await asyncio.sleep(0)

    assert started == ["sk-or-a"]
    assert orc._lists_key_digest == orc._key_digest("sk-or-a")
