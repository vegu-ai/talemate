"""Unit tests for the shared toggleable sampler-parameter plumbing
(talemate.client.toggleable_parameters) as consumed by the OpenRouter and
OpenAI-compatible clients.

A disabled `send_<param>` flag must remove the parameter from the client's
`supported_parameters`, which makes `ClientBase.clean_prompt_parameters`
omit it from the request payload entirely.
"""

from __future__ import annotations

import types

import pytest

import talemate.client.base as client_base
from talemate.client.openai_compat import (
    ClientConfig as OpenAICompatClientConfig,
    OpenAICompatibleClient,
    TOGGLEABLE_PARAMETERS as OPENAI_COMPAT_TOGGLEABLE_PARAMETERS,
)
from talemate.client.openrouter import (
    ClientConfig as OpenRouterClientConfig,
    OpenRouterClient,
    TOGGLEABLE_PARAMETERS as OPENROUTER_TOGGLEABLE_PARAMETERS,
)


def make_client(monkeypatch, client_cls, config):
    """Instantiate a client whose stored config resolves to `config`."""
    client = client_cls(name=config.name)
    monkeypatch.setattr(
        client_base,
        "get_config",
        lambda: types.SimpleNamespace(clients={config.name: config}),
    )
    return client


@pytest.fixture
def openrouter_client_factory(monkeypatch):
    def factory(**config_kwargs):
        config = OpenRouterClientConfig(
            name="test_openrouter", type="openrouter", **config_kwargs
        )
        return make_client(monkeypatch, OpenRouterClient, config)

    return factory


def test_openrouter_all_parameters_sent_by_default(openrouter_client_factory):
    client = openrouter_client_factory()

    assert client.supported_parameters == [
        "temperature",
        "top_p",
        "top_k",
        "min_p",
        "frequency_penalty",
        "presence_penalty",
        "repetition_penalty",
        "max_tokens",
    ]


def test_openrouter_disabled_parameters_not_supported(openrouter_client_factory):
    client = openrouter_client_factory(
        send_frequency_penalty=False, send_presence_penalty=False
    )

    assert "frequency_penalty" not in client.supported_parameters
    assert "presence_penalty" not in client.supported_parameters
    assert "temperature" in client.supported_parameters
    assert "max_tokens" in client.supported_parameters


def test_openrouter_disabled_parameters_dropped_from_payload(
    openrouter_client_factory,
):
    client = openrouter_client_factory(
        send_frequency_penalty=False, send_presence_penalty=False
    )

    parameters = {
        "temperature": 0.85,
        "frequency_penalty": 0.05,
        "presence_penalty": 0.7,
        "max_tokens": 512,
    }
    client.clean_prompt_parameters(parameters)

    assert parameters == {"temperature": 0.85, "max_tokens": 512}


def test_openrouter_config_defaults_all_enabled():
    config = OpenRouterClientConfig(name="test_openrouter", type="openrouter")

    for param in OPENROUTER_TOGGLEABLE_PARAMETERS:
        assert getattr(config, f"send_{param}") is True


def test_openrouter_meta_exposes_toggle_fields():
    meta = OpenRouterClient.Meta()

    for param in OPENROUTER_TOGGLEABLE_PARAMETERS:
        field = meta.extra_fields[f"send_{param}"]
        assert field.type == "bool"
        assert field.group.name == "parameters"
        assert getattr(meta.defaults, f"send_{param}") is True


def test_openai_compat_gating_unchanged(monkeypatch):
    assert OPENAI_COMPAT_TOGGLEABLE_PARAMETERS == (
        "temperature",
        "top_p",
        "presence_penalty",
    )

    config = OpenAICompatClientConfig(
        name="test_openai_compat", type="openai_compat", send_top_p=False
    )
    client = make_client(monkeypatch, OpenAICompatibleClient, config)

    assert "top_p" not in client.supported_parameters
    assert "temperature" in client.supported_parameters
    assert "presence_penalty" in client.supported_parameters
    assert "max_tokens" in client.supported_parameters


def test_openrouter_client_exposes_send_flags_for_status(openrouter_client_factory):
    """The client status payload reads extra-field values off the client
    instance (ClientBase.populate_extra_fields / _common_status_data); the
    frontend replaces missing values with the Meta defaults and echoes them
    back on save, so the flags must resolve on the client itself."""
    client = openrouter_client_factory(send_top_k=False)

    assert client.send_top_k is False
    assert client.send_temperature is True

    data = {}
    client.populate_extra_fields(data)
    assert data["send_top_k"] is False
    assert data["send_temperature"] is True


def test_openai_compat_client_exposes_send_flags_for_status(monkeypatch):
    config = OpenAICompatClientConfig(
        name="test_openai_compat", type="openai_compat", send_presence_penalty=False
    )
    client = make_client(monkeypatch, OpenAICompatibleClient, config)

    assert client.send_presence_penalty is False
    assert client.send_temperature is True

    data = {}
    client.populate_extra_fields(data)
    assert data["send_presence_penalty"] is False
    assert data["send_temperature"] is True


def test_openrouter_config_round_trip_preserves_flags():
    """Config validation converts client dicts to the client's config_cls
    (validate_client_type), so persisted send_* flags must survive."""
    from talemate.config.schema import Config

    config = Config.model_validate(
        {
            "clients": {
                "test_openrouter": {
                    "type": "openrouter",
                    "name": "test_openrouter",
                    "send_frequency_penalty": False,
                }
            }
        }
    )
    client_config = config.clients["test_openrouter"]

    assert isinstance(client_config, OpenRouterClientConfig)
    assert client_config.send_frequency_penalty is False
    assert client_config.send_temperature is True

    dumped = config.model_dump()
    assert dumped["clients"]["test_openrouter"]["send_frequency_penalty"] is False


def test_openai_compat_meta_exposes_toggle_fields():
    meta = OpenAICompatibleClient.Meta()

    for param in OPENAI_COMPAT_TOGGLEABLE_PARAMETERS:
        field = meta.extra_fields[f"send_{param}"]
        assert field.type == "bool"
        assert field.group.name == "parameters"
        assert getattr(meta.defaults, f"send_{param}") is True
