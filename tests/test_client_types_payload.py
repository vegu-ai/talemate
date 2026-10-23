"""The `client_types` message ships each type's config model field defaults.

The editor shows effective values for fields the user has not touched before a
client is first saved, so what the payload ships must equal what the model
resolves on save. These tests pin that contract.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import talemate.client  # noqa: F401  - registers the client classes
from talemate.client.registry import CLIENT_CLASSES
from talemate.config.schema import Config
from talemate.server.config import ConfigPlugin, client_model_defaults


CLIENT_TYPES = sorted(CLIENT_CLASSES.keys())


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)


_CLIENT_TYPES_MESSAGE: dict | None = None


def client_types_message() -> dict:
    """The message `handle_request_client_types` puts on the queue."""
    global _CLIENT_TYPES_MESSAGE

    if _CLIENT_TYPES_MESSAGE is None:
        handler = _MockWebsocketHandler()
        asyncio.run(ConfigPlugin(handler).handle_request_client_types({}))
        (_CLIENT_TYPES_MESSAGE,) = handler.messages

    return _CLIENT_TYPES_MESSAGE


@pytest.mark.asyncio
async def test_client_types_message_shape():
    handler = _MockWebsocketHandler()
    await ConfigPlugin(handler).handle_request_client_types({})

    (message,) = handler.messages
    assert message["type"] == "config"
    assert message["action"] == "client_types"
    assert sorted(message["data"]) == CLIENT_TYPES


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_model_defaults_are_shipped(client_type: str):
    payload = client_types_message()["data"][client_type]
    model_defaults = payload["model_defaults"]

    assert isinstance(model_defaults, dict)
    # identity is the client's own, not a default the frontend could apply
    assert "type" not in model_defaults
    assert "name" not in model_defaults

    json.dumps(model_defaults)


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_model_defaults_match_a_saved_client(client_type: str):
    """Every shipped default is what a minimally saved client resolves to."""
    config = Config(clients={"c": {"type": client_type, "name": "c"}})
    client = config.clients["c"]

    shipped = client_types_message()["data"][client_type]["model_defaults"]
    assert client.model_dump(exclude={"type", "name"}) == shipped


def test_former_frontend_mirror_is_covered():
    """The fields the frontend used to mirror, with the values it mirrored."""
    model_defaults = client_model_defaults("openai")

    assert model_defaults["reason_failure_behavior"] == "fail"
    assert model_defaults["enforce_response_length"] == "adaptive"
    assert model_defaults["optimize_prompt_caching"] is False
    assert model_defaults["dedupe_enabled"] is False


def test_per_type_fields_are_covered():
    """Per-type fields the mirror could not reach ship as well."""
    model_defaults = client_model_defaults("openrouter")

    assert model_defaults["concurrent_inference_enabled"] is True


CONCURRENT_INFERENCE_DEFAULTS = {
    "openrouter": True,
    "google": True,
    "anthropic": True,
    "mistral": True,
    "openai": True,
    # local / bridged clients stay opt-in: whether parallel requests help
    # depends on the user's setup
    "llamacpp": False,
    "pi_bridge": False,
}


@pytest.mark.parametrize(
    "client_type,expected", sorted(CONCURRENT_INFERENCE_DEFAULTS.items())
)
def test_concurrent_inference_default(client_type: str, expected: bool):
    """The shipped default of `concurrent_inference_enabled` per client type."""
    assert (
        client_model_defaults(client_type)["concurrent_inference_enabled"] is expected
    )


@pytest.mark.parametrize("client_type", sorted(CONCURRENT_INFERENCE_DEFAULTS))
def test_concurrent_inference_explicit_choice_kept(client_type: str):
    """An explicitly stored value wins over the shipped default, both ways."""
    explicit = not CONCURRENT_INFERENCE_DEFAULTS[client_type]
    config = Config(
        clients={
            "c": {
                "type": client_type,
                "name": "c",
                "concurrent_inference_enabled": explicit,
            }
        }
    )
    assert config.clients["c"].concurrent_inference_enabled is explicit
