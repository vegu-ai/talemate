"""Unit tests for talemate.client.google.GoogleClient.

Focused on the setup-incomplete status handling for issue #40:

- The "Setup incomplete" sentinel must not leak into the emitted model name.
  The frontend persists the emitted model name back into the client `model`
  field, so leaking the sentinel corrupts the config and causes every Google
  request to fail with HTTP 400.
- A config that already has the leaked sentinel persisted in its `model` field
  must be healed to "no model selected" rather than sent to the API verbatim.
"""

from __future__ import annotations

import pytest

import talemate.config.state as config_state
from talemate.client import google as google_module
from talemate.client.google import (
    ClientConfig,
    GoogleClient,
    SETUP_INCOMPLETE_MODEL,
)


@pytest.fixture
def cfg_isolation():
    """Snapshot/restore the config sections these tests mutate."""
    saved_clients = dict(config_state.CONFIG.clients)
    saved_api_key = config_state.CONFIG.google.api_key
    saved_creds = config_state.CONFIG.google.gcloud_credentials_path
    saved_location = config_state.CONFIG.google.gcloud_location
    yield
    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved_clients)
    config_state.CONFIG.google.api_key = saved_api_key
    config_state.CONFIG.google.gcloud_credentials_path = saved_creds
    config_state.CONFIG.google.gcloud_location = saved_location


@pytest.fixture
def no_google_credentials(cfg_isolation):
    """Ensure the Google service is treated as not configured."""
    config_state.CONFIG.google.api_key = None
    config_state.CONFIG.google.gcloud_credentials_path = None
    config_state.CONFIG.google.gcloud_location = None


@pytest.fixture
def capture_emit(monkeypatch):
    """Capture every emit() call made by the google client module."""
    calls = []

    def _fake_emit(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(google_module, "emit", _fake_emit)
    return calls


def _register(name: str, **kwargs) -> ClientConfig:
    cfg = ClientConfig(type="google", name=name, **kwargs)
    config_state.CONFIG.clients[name] = cfg
    return cfg


class TestModelSentinelHealing:
    def test_persisted_sentinel_model_resolves_to_none(self, no_google_credentials):
        _register("g_healed", model=SETUP_INCOMPLETE_MODEL)
        client = GoogleClient(name="g_healed")
        # The leaked sentinel must not be treated as a real model.
        assert client.model is None
        assert client.model_name is None

    def test_real_model_passes_through(self, no_google_credentials):
        _register("g_real", model="gemini-3.5-flash")
        client = GoogleClient(name="g_real")
        assert client.model == "gemini-3.5-flash"
        assert client.model_name == "gemini-3.5-flash"


class TestEmitStatus:
    def test_not_ready_keeps_real_model_name(self, no_google_credentials, capture_emit):
        _register("g_not_ready", model="gemini-3.5-flash")
        client = GoogleClient(name="g_not_ready")

        client.emit_status()

        assert client.current_status == "error"
        emitted = capture_emit[-1]["kwargs"]
        # The model name shown to (and persisted by) the frontend must stay the
        # real model, never the "Setup incomplete" sentinel.
        assert emitted["details"] == "gemini-3.5-flash"
        assert emitted["details"] != SETUP_INCOMPLETE_MODEL
        # The incomplete-setup state is communicated via error_message instead.
        assert emitted["data"]["error_message"] == "Setup incomplete"
        assert emitted["data"]["error_action"] is not None

    def test_ready_with_model_is_idle(self, cfg_isolation, capture_emit):
        config_state.CONFIG.google.api_key = "test-key"
        config_state.CONFIG.google.gcloud_credentials_path = None
        config_state.CONFIG.google.gcloud_location = None
        _register("g_ready", model="gemini-3.5-flash")
        client = GoogleClient(name="g_ready")

        client.emit_status()

        assert client.current_status == "idle"
        emitted = capture_emit[-1]["kwargs"]
        assert emitted["details"] == "gemini-3.5-flash"
        assert emitted["data"]["error_message"] is None
        assert emitted["data"]["error_action"] is None

    def test_healed_sentinel_reports_no_model_loaded(self, cfg_isolation, capture_emit):
        # Key is set (so `ready` is True) but the persisted model is the leaked
        # sentinel. Instead of shipping it to Google, the client must surface a
        # clean "No model loaded" state.
        config_state.CONFIG.google.api_key = "test-key"
        config_state.CONFIG.google.gcloud_credentials_path = None
        config_state.CONFIG.google.gcloud_location = None
        _register("g_healed_ready", model=SETUP_INCOMPLETE_MODEL)
        client = GoogleClient(name="g_healed_ready")

        client.emit_status()

        assert client.current_status == "error"
        emitted = capture_emit[-1]["kwargs"]
        assert emitted["data"]["error_message"] == "No model loaded"
        assert emitted["details"] != SETUP_INCOMPLETE_MODEL


class TestGenerateGuards:
    @pytest.mark.asyncio
    async def test_generate_raises_when_not_ready(self, no_google_credentials):
        _register("g_gen_not_ready", model="gemini-3.5-flash")
        client = GoogleClient(name="g_gen_not_ready")
        with pytest.raises(Exception, match="setup incomplete"):
            await client.generate("prompt", {}, "conversation")

    @pytest.mark.asyncio
    async def test_generate_raises_when_no_model(self, cfg_isolation):
        config_state.CONFIG.google.api_key = "test-key"
        config_state.CONFIG.google.gcloud_credentials_path = None
        config_state.CONFIG.google.gcloud_location = None
        _register("g_gen_no_model", model=SETUP_INCOMPLETE_MODEL)
        client = GoogleClient(name="g_gen_no_model")
        with pytest.raises(Exception, match="no model selected"):
            await client.generate("prompt", {}, "conversation")
