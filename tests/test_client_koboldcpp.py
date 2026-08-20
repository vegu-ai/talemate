"""Tests for KoboldCpp stopping string handling."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client import koboldcpp as koboldcpp_module
from talemate.client.base import STOPPING_STRINGS
from talemate.client.context import ClientContext, set_client_context_attribute
from talemate.client.koboldcpp import MAX_STOPPING_STRINGS, KoboldCppClient


@pytest.fixture
def preset_isolation():
    """Snapshot/restore the inference presets, yielding the live ones."""
    saved = config_state.CONFIG.presets.inference.model_copy(deep=True)
    yield config_state.CONFIG.presets.inference
    config_state.CONFIG.presets.inference = saved


def _make_client(name: str, api_url: str) -> KoboldCppClient:
    """`is_openai` keys off the api_url, which is read from the registered
    client config - constructing without one leaves api_url unset."""
    config_state.CONFIG.clients[name] = koboldcpp_module.ClientConfig(
        type="koboldcpp", name=name, api_url=api_url
    )
    return KoboldCppClient(name=name)


def _active_agent_context():
    """Return an ActiveAgent CM with an agent that injects no parameters.

    `tune_prompt_parameters` always reads the active agent context.
    """

    class _Agent:
        agent_type = "noop"
        verbose_name = "NoOp"

        def inject_prompt_paramters(self, parameters, kind, action):
            pass

    def _fn():
        pass

    return ActiveAgent(_Agent(), _fn)


class TestStoppingStrings:
    def test_extra_stopping_strings_reach_stop_sequence(self, cfg_isolation):
        client = _make_client("kcpp_stop", "http://fake:5001/api/v1")
        assert not client.is_openai
        parameters = {"extra_stopping_strings": ["Bob: "], "max_tokens": 50}

        with _active_agent_context():
            client.tune_prompt_parameters(parameters, "narrate")

        assert parameters["stopping_strings"] == STOPPING_STRINGS + ["Bob: "]

        client.clean_prompt_parameters(parameters)

        assert parameters["stop_sequence"] == STOPPING_STRINGS + ["Bob: "]
        assert parameters["max_length"] == 50
        assert "stopping_strings" not in parameters
        # send_prompt pops this before clean runs; clean drops it too since it
        # is not a supported parameter
        assert "extra_stopping_strings" not in parameters

    def test_stop_sequence_is_truncated_to_cap(self, cfg_isolation):
        client = _make_client("kcpp_stop_cap", "http://fake:5001/api/v1")
        extra = [f"Char{i}: " for i in range(20)]
        parameters = {"extra_stopping_strings": list(extra), "max_tokens": 50}

        with _active_agent_context():
            with capture_logs() as logs:
                client.tune_prompt_parameters(parameters, "narrate")

        client.clean_prompt_parameters(parameters)

        # pins the documented united-api limit
        assert MAX_STOPPING_STRINGS == 16

        expected = (STOPPING_STRINGS + extra)[:MAX_STOPPING_STRINGS]
        assert len(parameters["stop_sequence"]) == MAX_STOPPING_STRINGS
        assert parameters["stop_sequence"] == expected

        warnings = [entry for entry in logs if entry["log_level"] == "warning"]
        assert len(warnings) == 1
        assert warnings[0]["client_type"] == "koboldcpp"
        assert warnings[0]["max_stopping_strings"] == MAX_STOPPING_STRINGS
        assert (
            warnings[0]["dropped"] == (STOPPING_STRINGS + extra)[MAX_STOPPING_STRINGS:]
        )

    def test_openai_mode_sends_no_stop_parameter(self, cfg_isolation):
        client = _make_client("kcpp_openai", "http://fake:5001/v1")
        assert client.is_openai
        extra = [f"Char{i}: " for i in range(20)]
        parameters = {"extra_stopping_strings": list(extra), "max_tokens": 50}

        with _active_agent_context():
            with capture_logs() as logs:
                client.tune_prompt_parameters(parameters, "narrate")

        client.clean_prompt_parameters(parameters)

        assert "stopping_strings" not in parameters
        assert "stop_sequence" not in parameters
        assert "stop" not in parameters
        assert parameters["max_tokens"] == 50
        # no reroute in openai mode, so no cap to warn about either
        assert not [entry for entry in logs if entry["log_level"] == "warning"]


class _OfflineKoboldCppClient(KoboldCppClient):
    """KoboldCpp client that records the parameters `generate` receives and
    returns a canned response, so `send_prompt` can run without a backend."""

    # the real emit_status would hit HuggingFace to guess a prompt template
    auto_determine_prompt_template: bool = False

    def __init__(self, response: str, **kwargs):
        super().__init__(**kwargs)
        self._response = response
        self.generate_parameters = None

    async def status(self):
        self.connected = True

    async def get_model_name(self):
        return self.remote_model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        self.generate_parameters = parameters
        return self._response


class TestSendPromptCapFallback:
    @pytest.mark.asyncio
    async def test_cap_dropped_string_still_cuts_the_response(
        self, cfg_isolation, preset_isolation
    ):
        """A stopping string that lost its native slot to the cap is still
        applied to the response after generation."""
        name = "kcpp_fallback"
        config_state.CONFIG.clients[name] = koboldcpp_module.ClientConfig(
            type="koboldcpp", name=name, api_url="http://fake:5001/api/v1"
        )
        # 2 STOPPING_STRINGS + 15 preset entries = 17, one over the cap of 16
        kept = [f"<<KEPT_{i}>>" for i in range(14)]
        dropped = "<<DROPPED>>"
        preset_isolation.conversation.extra_stopping_strings = kept + [dropped]
        client = _OfflineKoboldCppClient(
            name=name, response=f"useful answer{dropped}garbage tail"
        )
        client.connected = True
        client.remote_model_name = "some-model"
        assert not client.is_openai

        with _active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                out = await client.send_prompt("hi", kind="conversation")

        assert out == "useful answer"
        # proves the cut came from the fallback, not from a native stop slot
        assert client.generate_parameters["stop_sequence"] == STOPPING_STRINGS + kept
        assert dropped not in client.generate_parameters["stop_sequence"]
