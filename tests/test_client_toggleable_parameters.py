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
from talemate.config.schema import Config
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
        "stop",
    )

    config = OpenAICompatClientConfig(
        name="test_openai_compat",
        type="openai_compat",
        send_top_p=False,
        send_stop=True,
    )
    client = make_client(monkeypatch, OpenAICompatibleClient, config)

    assert "top_p" not in client.supported_parameters
    assert "temperature" in client.supported_parameters
    assert "presence_penalty" in client.supported_parameters
    assert "stop" in client.supported_parameters
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


class TestOpenAICompatSavedRequestShape:
    """Clients saved before Send stop / Send enable_thinking existed keep the
    request they sent; new clients start from Meta.defaults."""

    def _load(self, client: dict) -> OpenAICompatClientConfig:
        config = Config.model_validate({"clients": {client["name"]: client}})
        return config.clients[client["name"]]

    def test_saved_client_without_keys_loads_both_off(self):
        saved = {"type": "openai_compat", "name": "old", "model": "m"}
        loaded = self._load(saved)
        assert loaded.send_stop is False
        assert loaded.send_enable_thinking is False

    def test_new_client_from_defaults_saves_both_on(self):
        defaults = OpenAICompatibleClient.Meta().model_dump()["defaults"]
        new = {**defaults, "type": "openai_compat", "name": "new"}
        loaded = self._load(new)
        assert loaded.send_stop is True
        assert loaded.send_enable_thinking is True
        reloaded = self._load(loaded.model_dump())
        assert (reloaded.send_stop, reloaded.send_enable_thinking) == (True, True)

    def test_resaved_old_client_keeps_the_users_choice(self):
        loaded = self._load({"type": "openai_compat", "name": "old", "model": "m"})
        edited = loaded.model_dump()
        edited["send_stop"] = True
        reloaded = self._load(edited)
        assert reloaded.send_stop is True
        assert reloaded.send_enable_thinking is False


def test_openai_family_toggle_names_and_fields_are_unchanged():
    from talemate.client.openai import TOGGLEABLE_PARAMETERS as OPENAI_PARAMETERS
    from talemate.client.toggleable_parameters import (
        PARAMETERS_FIELD_GROUP,
        toggle_names,
        toggleable_parameters_extra_fields,
    )

    for params in (
        OPENAI_PARAMETERS,
        OPENAI_COMPAT_TOGGLEABLE_PARAMETERS,
        OPENROUTER_TOGGLEABLE_PARAMETERS,
    ):
        assert toggle_names(params) == list(params)
        fields = toggleable_parameters_extra_fields(params)
        assert list(fields) == [f"send_{p}" for p in params]
        for param, field in zip(params, fields.values()):
            assert field.label == f"Send {param}"
            assert field.group == PARAMETERS_FIELD_GROUP
            assert field.description == (
                f"When enabled, {param} is included in the request. Disable for "
                f"models/APIs that reject it."
            )


def test_a_reroute_and_a_set_share_the_toggle_of_their_talemate_names():
    from talemate.client.base import ParameterReroute
    from talemate.client.toggleable_parameters import ParameterSet, toggle_names

    params = (
        "temperature",
        ParameterReroute(talemate_parameter="top_k", client_parameter="k"),
        "xtc_threshold",
        "xtc_probability",
    )
    sets = (
        ParameterSet(
            name="xtc",
            parameters=("xtc_threshold", "xtc_probability"),
            label="Send XTC",
            description="x",
        ),
    )
    assert toggle_names(params, sets) == ["temperature", "top_k", "xtc"]
