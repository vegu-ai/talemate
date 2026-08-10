"""Tests for LMStudio stopping string handling."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client.base import STOPPING_STRINGS
from talemate.client.context import ClientContext, set_client_context_attribute
from talemate.client.lmstudio import MAX_STOPPING_STRINGS, LMStudioClient
from talemate.config.schema import Client as ClientConfig

TRUNCATION_EVENT = "too many stopping strings, truncating"


@pytest.fixture
def cfg_isolation():
    """Snapshot/restore the client config section these tests mutate."""
    saved_clients = dict(config_state.CONFIG.clients)
    yield
    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved_clients)


@pytest.fixture
def preset_isolation():
    """Snapshot/restore the inference presets, yielding the live ones."""
    saved = config_state.CONFIG.presets.inference.model_copy(deep=True)
    yield config_state.CONFIG.presets.inference
    config_state.CONFIG.presets.inference = saved


def _truncation_entries(logs: list[dict]) -> list[dict]:
    """Captured log entries emitted by the stopping string cap."""
    return [entry for entry in logs if entry["event"] == TRUNCATION_EVENT]


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
    def test_extra_stopping_strings_reach_stop(self):
        client = LMStudioClient(name="lmstudio_stop")
        parameters = {"extra_stopping_strings": ["Bob: "], "max_tokens": 50}

        with _active_agent_context():
            client.tune_prompt_parameters(parameters, "narrate")

        assert parameters["stopping_strings"] == STOPPING_STRINGS + ["Bob: "]

        client.clean_prompt_parameters(parameters)

        assert parameters["stop"] == STOPPING_STRINGS + ["Bob: "]
        assert parameters["max_tokens"] == 50
        assert "stopping_strings" not in parameters
        # send_prompt pops this before clean runs; clean drops it too since it
        # is not a supported parameter
        assert "extra_stopping_strings" not in parameters

    def test_stop_list_is_truncated_to_cap(self):
        client = LMStudioClient(name="lmstudio_stop_cap")
        extra = [f"Char{i}: " for i in range(10)]
        parameters = {"extra_stopping_strings": list(extra), "max_tokens": 50}

        with _active_agent_context():
            with capture_logs() as logs:
                client.tune_prompt_parameters(parameters, "narrate")

        client.clean_prompt_parameters(parameters)

        # pins the documented OpenAI-reference limit LMStudio defers to
        assert MAX_STOPPING_STRINGS == 4

        expected = (STOPPING_STRINGS + extra)[:MAX_STOPPING_STRINGS]
        assert len(parameters["stop"]) == MAX_STOPPING_STRINGS
        assert parameters["stop"] == expected

        truncations = _truncation_entries(logs)
        assert len(truncations) == 1
        # debug, not warning: the cap is hit routinely and is not actionable
        assert truncations[0]["log_level"] == "debug"
        assert truncations[0]["client_type"] == "lmstudio"
        assert truncations[0]["max_stopping_strings"] == MAX_STOPPING_STRINGS
        assert (
            truncations[0]["dropped"]
            == (STOPPING_STRINGS + extra)[MAX_STOPPING_STRINGS:]
        )

    def test_no_truncation_log_when_within_cap(self):
        client = LMStudioClient(name="lmstudio_stop_ok")
        parameters = {"extra_stopping_strings": ["Bob: "], "max_tokens": 50}

        with _active_agent_context():
            with capture_logs() as logs:
                client.tune_prompt_parameters(parameters, "narrate")

        assert not _truncation_entries(logs)
        assert not [entry for entry in logs if entry["log_level"] == "warning"]


class _OfflineLMStudioClient(LMStudioClient):
    """LMStudio client that records the parameters `generate` receives and
    returns a canned response, so `send_prompt` can run without a backend."""

    # the real emit_status would hit HuggingFace to guess a prompt template
    auto_determine_prompt_template: bool = False

    def __init__(self, name: str, response: str):
        super().__init__(name=name)
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
        config_state.CONFIG.clients["lmstudio_fallback"] = ClientConfig(
            type="lmstudio", name="lmstudio_fallback", enabled=True
        )
        # 2 STOPPING_STRINGS + 3 preset entries = 5, one over the cap of 4
        dropped = "<<DROPPED>>"
        preset_isolation.conversation.extra_stopping_strings = [
            "<<KEPT_A>>",
            "<<KEPT_B>>",
            dropped,
        ]
        client = _OfflineLMStudioClient(
            name="lmstudio_fallback",
            response=f"useful answer{dropped}garbage tail",
        )
        client.connected = True
        client.remote_model_name = "some-model"

        with _active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                out = await client.send_prompt("hi", kind="conversation")

        assert out == "useful answer"
        # proves the cut came from the fallback, not from a native stop slot
        assert client.generate_parameters["stop"] == STOPPING_STRINGS + [
            "<<KEPT_A>>",
            "<<KEPT_B>>",
        ]
        assert dropped not in client.generate_parameters["stop"]
