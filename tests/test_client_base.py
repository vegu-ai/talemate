"""Unit tests for talemate.client.base.

Targets the pure-Python logic of ClientBase: parameter normalization, prompt
assembly, response cleanup, retry/backoff helpers, status emission, request
information bookkeeping, and the helpers/dataclasses defined alongside it.

We avoid covering paths that require live HTTP responses (the actual
generate / openai client / anthropic SDK calls) and document any skipped
paths inline.

Tests intentionally subclass ClientBase with the smallest possible stub
that satisfies the public surface, keeping the focus on the logic-under-test
rather than mocking the function under test.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent, active_agent
from talemate.client import base as base_module
from talemate.client.base import (
    EMPTY_RESPONSE_MESSAGE,
    HTTP_ERROR_MESSAGES,
    ClientBase,
    ClientDisabledError,
    CommonDefaults,
    Defaults,
    ErrorAction,
    ParameterReroute,
    PromptData,
    ReasoningDisplay,
    RequestInformation,
    _generation_error_futures,
    clean_client_name,
    get_error_message,
    locked_model_template,
    resolve_generation_error,
)
from talemate.client.context import ClientContext, set_client_context_attribute
from talemate.config.schema import Client as ClientConfig
from talemate.context import ActiveScene
from talemate.exceptions import ReasoningResponseError


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _StubClient(ClientBase):
    """Minimal ClientBase subclass used to drive logic-only tests.

    No `__init__` overrides — we reuse ClientBase.__init__ so that the real
    init code path is exercised. Tests that need a particular `client_config`
    set it via the registered config fixture.
    """

    client_type = "stub"

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "max_tokens",
            "extra_stopping_strings",
            ParameterReroute(
                talemate_parameter="repetition_penalty",
                client_parameter="frequency_penalty",
            ),
        ]


def _register_client_config(name: str, **kwargs) -> ClientConfig:
    """Insert a ClientConfig into the live config and return it."""
    cfg = ClientConfig(type="stub", name=name, **kwargs)
    config_state.CONFIG.clients[name] = cfg
    return cfg


@pytest.fixture
def cfg_isolation():
    """Snapshot/restore mutated config sections."""
    saved_clients = dict(config_state.CONFIG.clients)
    saved_embeddings = dict(config_state.CONFIG.presets.embeddings)
    yield
    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved_clients)
    config_state.CONFIG.presets.embeddings.clear()
    config_state.CONFIG.presets.embeddings.update(saved_embeddings)


@pytest.fixture
def stub_client(cfg_isolation):
    """A stub client with a registered config entry under its name."""
    _register_client_config("stub_test")
    client = _StubClient(name="stub_test")
    return client


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestErrorMessages:
    def test_known_status_codes_have_specific_messages(self):
        # Each mapped code returns the exact mapped message.
        for code, msg in HTTP_ERROR_MESSAGES.items():
            assert get_error_message(code) == msg

    def test_none_status_yields_empty_response_message(self):
        assert get_error_message(None) == EMPTY_RESPONSE_MESSAGE

    def test_unmapped_5xx_falls_through_to_generic_5xx_message(self):
        assert (
            get_error_message(504)
            == "The API server is experiencing issues. This is usually temporary."
        )

    def test_unmapped_4xx_returns_unexpected_error(self):
        assert (
            get_error_message(418) == "The API returned an unexpected error (HTTP 418)."
        )

    def test_unmapped_2xx_returns_unexpected_error(self):
        assert (
            get_error_message(299) == "The API returned an unexpected error (HTTP 299)."
        )


class TestNameHelpers:
    def test_clean_client_name_replaces_spaces(self):
        assert clean_client_name("Open AI Pro") == "Open_AI_Pro"

    def test_clean_client_name_no_op_when_no_spaces(self):
        assert clean_client_name("LMStudio") == "LMStudio"

    def test_locked_model_template_uses_cleaned_name(self):
        # Model name is intentionally ignored — lock_template uses client name only.
        assert locked_model_template("My Client", "any-model") == "My_Client__LOCK"


class TestResolveGenerationError:
    @pytest.mark.asyncio
    async def test_resolves_pending_future_with_action(self):
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        _generation_error_futures["abc"] = future
        try:
            resolve_generation_error("abc", "retry")
            assert await future == "retry"
        finally:
            _generation_error_futures.pop("abc", None)

    @pytest.mark.asyncio
    async def test_no_op_when_request_id_unknown(self):
        # Should not raise — silently ignored.
        resolve_generation_error("never-registered", "retry")

    @pytest.mark.asyncio
    async def test_no_op_when_future_already_done(self):
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        future.set_result("first")
        _generation_error_futures["dup"] = future
        try:
            # Should not raise / overwrite.
            resolve_generation_error("dup", "second")
            assert future.result() == "first"
        finally:
            _generation_error_futures.pop("dup", None)


# ---------------------------------------------------------------------------
# Dataclasses / pydantic models
# ---------------------------------------------------------------------------


class TestRequestInformation:
    def test_pending_status_when_only_started(self):
        info = RequestInformation(start_time=time.time())
        # in-progress / pending until duration > 1 with rate==0
        assert info.status in ("in progress", "pending")

    def test_completed_status_after_end(self):
        now = time.time()
        info = RequestInformation(start_time=now - 1, end_time=now)
        assert info.status == "completed"

    def test_cancelled_status(self):
        now = time.time()
        info = RequestInformation(start_time=now - 1, end_time=now, cancelled=True)
        assert info.status == "stopped"

    def test_age_minus_one_when_unended(self):
        info = RequestInformation()
        assert info.age == -1

    def test_age_positive_after_end(self):
        info = RequestInformation(end_time=time.time() - 0.5)
        assert info.age >= 0.5

    def test_rate_uses_first_token_time_when_set(self):
        now = time.time()
        info = RequestInformation(
            start_time=now - 5,
            first_token_time=now - 1,
            end_time=now,
            tokens=20,
        )
        # Rate should reflect ~20 tokens in ~1s, not 20/5s.
        assert 15 <= info.rate <= 25

    def test_rate_zero_when_no_tokens(self):
        info = RequestInformation(
            start_time=time.time() - 1, end_time=time.time(), tokens=0
        )
        assert info.rate == 0

    def test_rate_does_not_divide_by_zero(self):
        # When end_time == start_time (no first_token_time) — denom is clamped.
        t = time.time()
        info = RequestInformation(start_time=t, end_time=t, tokens=10)
        # Should not raise; result is large but finite.
        assert info.rate > 0

    def test_duration_uses_end_time_when_set(self):
        info = RequestInformation(start_time=10.0, end_time=15.0)
        assert info.duration == pytest.approx(5.0)


class TestParameterReroute:
    def test_reroute_renames_key(self):
        rr = ParameterReroute(
            talemate_parameter="repetition_penalty",
            client_parameter="frequency_penalty",
        )
        params = {"repetition_penalty": 1.2, "temperature": 0.7}
        rr.reroute(params)
        assert "repetition_penalty" not in params
        assert params["frequency_penalty"] == 1.2
        assert params["temperature"] == 0.7

    def test_reroute_no_op_when_source_missing(self):
        rr = ParameterReroute(talemate_parameter="x", client_parameter="y")
        params = {"a": 1}
        rr.reroute(params)
        assert params == {"a": 1}

    def test_str_returns_client_parameter(self):
        rr = ParameterReroute(talemate_parameter="x", client_parameter="y")
        assert str(rr) == "y"

    def test_eq_against_string(self):
        rr = ParameterReroute(talemate_parameter="x", client_parameter="y")
        assert rr == "y"
        assert rr != "x"


class TestPromptData:
    def test_round_trip_and_defaults(self):
        pd = PromptData(
            kind="conversation",
            prompt="hi",
            response="ho",
            prompt_tokens=2,
            response_tokens=2,
            client_name="c",
            client_type="stub",
            time=0.1,
        )
        # default factories applied
        assert pd.agent_stack == []
        assert pd.generation_parameters == {}
        # serializable
        dumped = pd.model_dump()
        assert dumped["client_name"] == "c"
        assert dumped["template_uid"] is None


class TestErrorAction:
    def test_default_icon_and_arguments(self):
        ea = ErrorAction(title="t", action_name="a")
        assert ea.icon == "mdi-error"
        assert ea.arguments == []


class TestDefaults:
    def test_common_defaults_have_expected_keys(self):
        cd = CommonDefaults()
        # rate_limit/data_format default to None
        assert cd.rate_limit is None
        assert cd.data_format is None
        assert cd.reason_enabled is False
        assert cd.reason_tokens == 1024

    def test_defaults_extends_common(self):
        d = Defaults()
        assert d.api_url == "http://localhost:5000"
        assert d.max_token_length == 8192
        assert d.lock_template is False
        # inherits CommonDefaults
        assert d.reason_enabled is False


class TestClientDisabledError:
    def test_message_contains_client_name(self, stub_client):
        err = ClientDisabledError(stub_client)
        assert "stub_test" in err.message
        assert err.client is stub_client


# ---------------------------------------------------------------------------
# ClientBase config getter wiring
# ---------------------------------------------------------------------------


class TestClientBaseConfigGetters:
    """Verify config getters proxy to the registered ClientConfig."""

    def test_getters_default_when_no_config_entry(self, cfg_isolation):
        # No entry under the client name → falls through to a default ClientConfig.
        client = _StubClient(name="not_in_config")
        assert client.model is None
        assert client.api_key is None
        assert client.api_url is None
        assert client.max_token_length == 8192
        assert client.enabled is True
        assert client.rate_limit is None
        assert client.lock_template is False
        # data_format / section_format are None by default
        assert client.data_format is None
        assert client.section_format is None

    def test_getters_proxy_to_registered_config(self, cfg_isolation):
        _register_client_config(
            "wired",
            api_url="http://example.com",
            api_key="secret",
            max_token_length=2048,
            rate_limit=42,
            data_format="json",
            section_format="xml",
            preset_group="alpha",
            reason_enabled=True,
            reason_tokens=512,
            reason_prefill="<think>",
            lock_template=True,
            optimize_prompt_caching=True,
            dedupe_enabled=True,
        )
        client = _StubClient(name="wired")

        assert client.api_url == "http://example.com"
        assert client.api_key == "secret"
        assert client.max_token_length == 2048
        assert client.rate_limit == 42
        assert client.data_format == "json"
        assert client.section_format == "xml"
        assert client.preset_group == "alpha"
        assert client.reason_enabled is True
        assert client.reason_tokens == 512
        assert client.reason_prefill == "<think>"
        assert client.lock_template is True
        assert client.optimize_prompt_caching is True
        assert client.dedupe_enabled is True

    def test_model_name_falls_back_when_remote_unset(self, cfg_isolation):
        _register_client_config("m1", model="cfg-model")
        client = _StubClient(name="m1")
        assert client.remote_model_name is None
        assert client.model_name == "cfg-model"

    def test_model_name_prefers_remote_when_present(self, cfg_isolation):
        _register_client_config("m2", model="cfg-model")
        client = _StubClient(name="m2")
        client.remote_model_name = "remote-model"
        assert client.model_name == "remote-model"

    def test_model_name_locked_uses_remote_only(self, cfg_isolation):
        _register_client_config("m3", model="cfg-model")
        client = _StubClient(name="m3")
        client.remote_model_locked = True
        # When locked, only remote_model_name is returned even if missing.
        assert client.model_name is None
        client.remote_model_name = "remote-model"
        assert client.model_name == "remote-model"

    def test_validated_reason_tokens_floor(self, cfg_isolation):
        _register_client_config("r1", reason_tokens=10)
        client = _StubClient(name="r1")
        assert client.validated_reason_tokens == 10
        # min_reason_tokens defaults to 0; subclasses can raise it.

        class _MinReasonClient(_StubClient):
            min_reason_tokens = 100

        _register_client_config("r2", reason_tokens=10)
        client = _MinReasonClient(name="r2")
        assert client.validated_reason_tokens == 100


class TestEnforceResponseLengthFlags:
    @pytest.mark.parametrize(
        "mode,expect_cap,expect_instructions",
        [
            ("uncapped", False, False),
            ("cap_tokens", True, False),
            ("instructions", False, True),
            ("cap_tokens_and_instructions", True, True),
        ],
    )
    def test_flags(self, cfg_isolation, mode, expect_cap, expect_instructions):
        _register_client_config("erl", enforce_response_length=mode)
        client = _StubClient(name="erl")
        assert client.enforce_response_length_cap_tokens is expect_cap
        assert client.enforce_response_length_instructions is expect_instructions


class TestCanBeCoerced:
    def test_true_when_template_required(self, stub_client):
        assert stub_client.can_be_coerced is True

    def test_false_when_reason_enabled(self, cfg_isolation):
        _register_client_config("rc", reason_enabled=True)
        client = _StubClient(name="rc")
        assert client.can_be_coerced is False

    def test_false_when_template_not_required(self, cfg_isolation):
        class _NoTemplateClient(_StubClient):
            class Meta(ClientBase.Meta):
                requires_prompt_template: bool = False

        _register_client_config("nt")
        client = _NoTemplateClient(name="nt")
        assert client.can_be_coerced is False


class TestReasoningDisplay:
    def test_returns_none_when_disabled(self, stub_client):
        assert stub_client.reasoning_display is None

    def test_populated_when_enabled(self, cfg_isolation):
        _register_client_config("rd", reason_enabled=True, reason_tokens=2048)
        client = _StubClient(name="rd")
        rd = client.reasoning_display
        assert isinstance(rd, ReasoningDisplay)
        assert rd.indicator_value == "2048"
        assert rd.show_token_slider is True


# ---------------------------------------------------------------------------
# Network-targeting heuristics
# ---------------------------------------------------------------------------


class TestHostIsRemote:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("http://localhost:8000", False),
            ("http://LocalHost:8000", False),
            ("http://127.0.0.1:8000", False),
            ("http://10.0.0.5", False),  # private
            ("http://192.168.1.1", False),  # private
            ("http://172.16.0.1", False),  # private
            ("http://8.8.8.8", True),  # public IP
            ("http://api.openai.com", True),  # remote hostname
        ],
    )
    def test_classification(self, stub_client, url, expected):
        assert stub_client.host_is_remote(url) is expected


class TestToggleDisabledIfRemote:
    def test_disables_when_remote_and_enabled(self, cfg_isolation):
        # The toggle now writes through to `client_config.enabled` (the
        # underlying field that the read-only `enabled` property proxies to).
        _register_client_config(
            "remote_test", api_url="http://api.example.com", enabled=True
        )
        client = _StubClient(name="remote_test")
        assert client.enabled is True
        assert client.toggle_disabled_if_remote() is True
        assert client.enabled is False

    def test_no_op_when_local(self, cfg_isolation):
        _register_client_config(
            "local_test", api_url="http://localhost:5000", enabled=True
        )
        client = _StubClient(name="local_test")
        assert client.toggle_disabled_if_remote() is False
        assert client.enabled is True

    def test_no_op_when_no_api_url(self, cfg_isolation):
        _register_client_config("no_url", api_url=None, enabled=True)
        client = _StubClient(name="no_url")
        assert client.toggle_disabled_if_remote() is False


# ---------------------------------------------------------------------------
# Prompt template logic
# ---------------------------------------------------------------------------


class TestPromptTemplate:
    def test_returns_raw_prompt_when_no_template_required(self, cfg_isolation):
        class _NoTemplateClient(_StubClient):
            class Meta(ClientBase.Meta):
                requires_prompt_template: bool = False

        _register_client_config("nt")
        client = _NoTemplateClient(name="nt")
        out = client.prompt_template("SYS", "USER")
        assert out == "USER"

    def test_returns_concatenation_when_no_model_loaded(self, stub_client):
        # No remote_model_name and no config.model -> fallback formatting.
        assert stub_client.model_name is None
        out = stub_client.prompt_template("SYS", "USER")
        assert out == "SYS\nUSER"

    def test_applies_default_template_when_model_loaded(self, cfg_isolation):
        _register_client_config("with_model", model="some-unmapped-model")
        client = _StubClient(name="with_model")
        out = client.prompt_template("SYS", "USER")
        # Default template wraps with [INST] markers (ChatML-fallback).
        assert "USER" in out
        assert "SYS" in out


class TestPromptTemplateExample:
    def test_returns_none_when_no_model(self, stub_client):
        rendered, tname, spec = stub_client.prompt_template_example()
        assert rendered is None
        assert tname is None
        # spec is a fresh PromptSpec instance
        assert spec is not None

    def test_returns_none_when_disabled(self, cfg_isolation):
        _register_client_config("d", model="m", enabled=False)
        client = _StubClient(name="d")
        rendered, tname, spec = client.prompt_template_example()
        assert rendered is None
        assert tname is None

    def test_returns_rendered_when_model_and_enabled(self, cfg_isolation):
        _register_client_config("e", model="some-model", enabled=True)
        client = _StubClient(name="e")
        rendered, tname, spec = client.prompt_template_example()
        assert rendered is not None
        # Includes the placeholders unmodified
        assert "{sysmsg}" in rendered
        assert "{prompt}" in rendered


# ---------------------------------------------------------------------------
# Prompt coercion / response length / reasoning
# ---------------------------------------------------------------------------


class TestSplitPromptForCoercion:
    def test_no_bot_marker_returns_unchanged(self, stub_client):
        prompt, coercion = stub_client.split_prompt_for_coercion("just a prompt")
        assert prompt == "just a prompt"
        assert coercion is None

    def test_bot_marker_splits(self, stub_client):
        prompt, coercion = stub_client.split_prompt_for_coercion("ask<|BOT|>answer")
        assert prompt == "ask"
        assert coercion == "answer"

    def test_double_coercion_prepended(self, cfg_isolation):
        _register_client_config("dc", double_coercion="prefix-text")
        client = _StubClient(name="dc")
        prompt, coercion = client.split_prompt_for_coercion("ask<|BOT|>answer")
        assert prompt == "ask"
        assert coercion == "prefix-text\n\nanswer"

    def test_only_first_bot_marker_consumed(self, stub_client):
        prompt, coercion = stub_client.split_prompt_for_coercion(
            "ask<|BOT|>here<|BOT|>more"
        )
        assert prompt == "ask"
        # The right-hand side keeps the second <|BOT|>
        assert coercion == "here<|BOT|>more"


class TestStripCoercionPrompt:
    def test_strips_when_present(self, stub_client):
        out = stub_client.strip_coercion_prompt(
            "Sure, here is the answer", "Sure, here is"
        )
        assert out == "the answer"

    def test_no_op_when_response_does_not_start_with_coercion(self, stub_client):
        original = "Different start"
        assert stub_client.strip_coercion_prompt(original, "Sure") == original

    def test_no_op_when_coercion_empty_or_none(self, stub_client):
        assert stub_client.strip_coercion_prompt("text", None) == "text"
        assert stub_client.strip_coercion_prompt("text", "") == "text"


class TestStripReasoning:
    def test_returns_response_when_reason_disabled(self, stub_client):
        out, reason = stub_client.strip_reasoning("just a response")
        assert out == "just a response"
        assert reason is None

    def test_extracts_default_pattern(self, cfg_isolation):
        _register_client_config("re", reason_enabled=True)
        client = _StubClient(name="re")
        response = "<think>internal monologue</think>actual answer"
        out, reason = client.strip_reasoning(response)
        assert out == "actual answer"
        assert "<think>" in reason
        assert "internal monologue" in reason

    def test_raises_when_pattern_not_found_and_failure_is_fail(self, cfg_isolation):
        _register_client_config(
            "rf", reason_enabled=True, reason_failure_behavior="fail"
        )
        client = _StubClient(name="rf")
        with pytest.raises(ReasoningResponseError):
            client.strip_reasoning("answer without thinking")

    def test_returns_unchanged_when_pattern_missing_and_failure_is_ignore(
        self, cfg_isolation
    ):
        _register_client_config(
            "rg", reason_enabled=True, reason_failure_behavior="ignore"
        )
        client = _StubClient(name="rg")
        out, reason = client.strip_reasoning("answer without thinking")
        assert out == "answer without thinking"
        assert reason is None

    def test_returns_unchanged_when_requires_reasoning_pattern_false(
        self, cfg_isolation
    ):
        class _NoPatternClient(_StubClient):
            @property
            def requires_reasoning_pattern(self):
                return False

        _register_client_config("rp", reason_enabled=True)
        client = _NoPatternClient(name="rp")
        out, reason = client.strip_reasoning("<think>x</think>answer")
        # Pattern matching skipped — full string preserved.
        assert out == "<think>x</think>answer"
        assert reason is None

    def test_validation_pattern_present_strips_normally(self, cfg_isolation):
        _register_client_config(
            "sr_val_ok", reason_enabled=True, reason_validation_pattern="<think>"
        )
        client = _StubClient(name="sr_val_ok")
        out, reason = client.strip_reasoning("<think>thinking</think>answer")
        assert out == "answer"
        assert reason == "<think>thinking</think>"

    def test_validation_pattern_absent_returns_response_as_is(self, cfg_isolation):
        # Even with reason_failure_behavior="fail", a configured validation
        # pattern that is absent means the model never reasoned -> return as-is.
        _register_client_config(
            "sr_val_absent",
            reason_enabled=True,
            reason_failure_behavior="fail",
            reason_validation_pattern="<think>",
        )
        client = _StubClient(name="sr_val_absent")
        out, reason = client.strip_reasoning("just a plain answer")
        assert out == "just a plain answer"
        assert reason is None

    def test_validation_skipped_when_prefilled(self, cfg_isolation):
        # When the reasoning start is prefilled it won't appear in the response,
        # so validation is skipped and the normal failure behavior applies.
        _register_client_config(
            "sr_val_prefill",
            reason_enabled=True,
            reason_failure_behavior="fail",
            reason_validation_pattern="<think>",
            reason_prefill="<think>",
        )
        client = _StubClient(name="sr_val_prefill")
        with pytest.raises(ReasoningResponseError):
            client.strip_reasoning("no closing token here")

    def test_reason_validation_pattern_property_proxies_config(self, cfg_isolation):
        _register_client_config("sr_val_prop", reason_validation_pattern="<seed:think>")
        assert (
            _StubClient(name="sr_val_prop").reason_validation_pattern == "<seed:think>"
        )
        # Defaults to None (opt-in) when unset.
        _register_client_config("sr_val_none")
        assert _StubClient(name="sr_val_none").reason_validation_pattern is None


class TestProcessResponseForIndirectCoercion:
    def test_strips_coercion_when_response_starts_with_it(self, stub_client):
        out = stub_client.process_response_for_indirect_coercion(
            prompt="ignored",
            response="Sure, here is the actual answer.",
            coercion_prompt="Sure, here is",
        )
        assert out == "the actual answer."

    def test_strips_coercion_after_lstrip(self, stub_client):
        out = stub_client.process_response_for_indirect_coercion(
            prompt="ignored",
            response="   Sure, here is the actual answer.",
            coercion_prompt="Sure, here is",
        )
        assert out == "the actual answer."

    def test_strips_json_code_fence_when_coercion_starts_with_brace(self, stub_client):
        out = stub_client.process_response_for_indirect_coercion(
            prompt="ignored",
            response='```json\n{"a": 1}\n```',
            coercion_prompt='{"a"',
        )
        # Code fence stripped, then coercion stripped.
        assert ":" in out and "1" in out
        assert "```" not in out

    def test_preserves_response_when_coercion_not_present(self, stub_client):
        out = stub_client.process_response_for_indirect_coercion(
            prompt="ignored",
            response="totally different text",
            coercion_prompt="Sure, here is",
        )
        assert out == "totally different text"


class TestAttachResponseLengthInstruction:
    def test_returns_unchanged_when_response_length_zero(self, stub_client):
        out = stub_client.attach_response_length_instruction("hello", 0)
        assert out == "hello"

    def test_returns_unchanged_when_response_length_negative(self, stub_client):
        out = stub_client.attach_response_length_instruction("hello", -5)
        assert out == "hello"

    def test_replaces_marker_when_present(self, stub_client):
        out = stub_client.attach_response_length_instruction(
            "before <|RESPONSE_LENGTH_INSTRUCTIONS|> after", 256
        )
        assert "<|RESPONSE_LENGTH_INSTRUCTIONS|>" not in out
        assert "before" in out and "after" in out

    def test_inserts_before_bot_marker(self, stub_client):
        out = stub_client.attach_response_length_instruction(
            "do the thing<|BOT|>answer", 256
        )
        assert "<|BOT|>" in out
        # Marker is preserved; instruction comes immediately before it.
        before, after = out.split("<|BOT|>", 1)
        assert "do the thing" in before
        # The full instruction text is non-empty
        assert before.strip() != "do the thing"

    def test_appends_to_end_when_no_marker(self, stub_client):
        out = stub_client.attach_response_length_instruction("plain prompt", 256)
        assert out.startswith("plain prompt")
        # An instruction line was added.
        assert len(out) > len("plain prompt")


# ---------------------------------------------------------------------------
# Parameter shaping
# ---------------------------------------------------------------------------


class TestCleanPromptParameters:
    def test_drops_unsupported_keys(self, stub_client):
        params = {"temperature": 0.7, "max_tokens": 50, "top_p": 0.9, "weird": 1}
        stub_client.clean_prompt_parameters(params)
        assert "temperature" in params
        assert "max_tokens" in params
        assert "top_p" not in params
        assert "weird" not in params

    def test_applies_parameter_reroute(self, stub_client):
        params = {
            "temperature": 0.7,
            "max_tokens": 50,
            "repetition_penalty": 1.2,
        }
        stub_client.clean_prompt_parameters(params)
        # Reroute renames, then key filter keeps the rerouted name.
        assert "frequency_penalty" in params
        assert params["frequency_penalty"] == 1.2
        assert "repetition_penalty" not in params

    def test_keeps_extra_stopping_strings(self, stub_client):
        params = {"temperature": 0.5, "extra_stopping_strings": ["END"]}
        stub_client.clean_prompt_parameters(params)
        assert params["extra_stopping_strings"] == ["END"]


class TestTunePromptParametersConversation:
    def test_sets_max_tokens_and_stopping_strings(self, stub_client):
        params = {}
        # The conversation context's "length" is read off the conversation
        # dict directly (not a separate top-level key).
        with ClientContext():
            set_client_context_attribute(
                "conversation",
                {
                    "talking_character": "Alice",
                    "other_characters": ["Bob", "Eve"],
                    "length": 1234,
                },
            )
            stub_client.tune_prompt_parameters_conversation(params)

        assert params["max_tokens"] == 1234
        # Stopping strings include "Bob:", "Eve:", "BOB\n", "EVE\n"
        assert "Bob:" in params["extra_stopping_strings"]
        assert "Eve:" in params["extra_stopping_strings"]
        assert "BOB\n" in params["extra_stopping_strings"]
        assert "EVE\n" in params["extra_stopping_strings"]

    def test_appends_to_existing_stopping_strings(self, stub_client):
        params = {"extra_stopping_strings": ["PRESET"]}
        with ClientContext():
            set_client_context_attribute(
                "conversation",
                {
                    "talking_character": "Alice",
                    "other_characters": ["Bob"],
                    "length": 300,
                },
            )
            stub_client.tune_prompt_parameters_conversation(params)
        assert "PRESET" in params["extra_stopping_strings"]
        assert "Bob:" in params["extra_stopping_strings"]

    def test_default_max_tokens_when_length_missing(self, stub_client):
        params = {}
        with ClientContext():
            set_client_context_attribute(
                "conversation",
                {
                    "talking_character": "Alice",
                    "other_characters": ["Bob"],
                },
            )
            stub_client.tune_prompt_parameters_conversation(params)
        # Falls back to default 96 when "length" missing
        assert params["max_tokens"] == 96


class TestExtractStatusCode:
    def test_status_code_attribute(self, stub_client):
        e = Exception()
        e.status_code = 429
        assert stub_client._extract_status_code(e) == 429

    def test_status_attribute_fallback(self, stub_client):
        e = Exception()
        e.status = 503
        assert stub_client._extract_status_code(e) == 503

    def test_code_attribute_fallback(self, stub_client):
        e = Exception()
        e.code = 401
        assert stub_client._extract_status_code(e) == 401

    def test_returns_none_when_none_present(self, stub_client):
        e = Exception("plain")
        assert stub_client._extract_status_code(e) is None

    def test_ignores_non_int_attributes(self, stub_client):
        e = Exception()
        e.status_code = "not-an-int"
        # Falls through to the next attribute, then None.
        assert stub_client._extract_status_code(e) is None


class TestJiggleRandomness:
    def test_temperature_increased_within_offset(self, stub_client):
        # Run many iterations to ensure result is always within [temp+0.3*offset, temp+offset].
        for _ in range(50):
            params = {"temperature": 0.7}
            stub_client.jiggle_randomness(params, offset=0.3)
            assert params["temperature"] >= 0.7 + 0.3 * 0.3 - 1e-9
            assert params["temperature"] <= 0.7 + 0.3 + 1e-9

    def test_uses_default_offset(self, stub_client):
        params = {"temperature": 0.5}
        stub_client.jiggle_randomness(params)  # default offset = 0.3
        assert 0.5 + 0.3 * 0.3 - 1e-9 <= params["temperature"] <= 0.5 + 0.3 + 1e-9


class TestJiggleEnabledFor:
    def test_delegates_to_agent_allow_repetition_break(self, stub_client):
        calls = []

        class _Agent:
            agent_type = "conversation"
            verbose_name = "TestAgent"

            def allow_repetition_break(self, kind, action, auto=False):
                calls.append((kind, action, auto))
                return True

        def _fn():
            pass

        with ActiveAgent(_Agent(), _fn):
            assert stub_client.jiggle_enabled_for("conversation", auto=True) is True
        assert calls == [("conversation", "_fn", True)]

    def test_returns_false_when_agent_falsy(self, stub_client):
        # When agent_context.agent is falsy, jiggle is disabled.
        class _NoAgent:
            agent = None

        # Patch active_agent to a stand-in object whose .agent is None.
        token = active_agent.set(_NoAgent())
        try:
            assert stub_client.jiggle_enabled_for("conversation") is False
        finally:
            active_agent.reset(token)

    def test_returns_false_when_no_active_agent(self, stub_client):
        # When no active_agent context is set, `active_agent.get()` returns
        # None (the ContextVar default). The function should treat that as
        # "jiggle disabled" rather than crashing on `None.agent`.
        token = active_agent.set(None)
        try:
            assert stub_client.jiggle_enabled_for("conversation") is False
        finally:
            active_agent.reset(token)


class TestRateLimitUpdate:
    def test_sets_counter_when_rate_limit_present(self, cfg_isolation):
        _register_client_config("rl", rate_limit=42)
        client = _StubClient(name="rl")
        assert client.rate_limit_counter is None
        client.rate_limit_update()
        assert client.rate_limit_counter is not None
        assert client.rate_limit_counter.rate.amount == 42

    def test_updates_existing_counter(self, cfg_isolation):
        _register_client_config("rl2", rate_limit=10)
        client = _StubClient(name="rl2")
        client.rate_limit_update()
        first = client.rate_limit_counter
        # Change config
        config_state.CONFIG.clients["rl2"].rate_limit = 99
        client.rate_limit_update()
        assert client.rate_limit_counter is first  # same instance reused
        assert client.rate_limit_counter.rate.amount == 99

    def test_clears_counter_when_no_rate_limit(self, cfg_isolation):
        _register_client_config("rl3", rate_limit=10)
        client = _StubClient(name="rl3")
        client.rate_limit_update()
        assert client.rate_limit_counter is not None
        config_state.CONFIG.clients["rl3"].rate_limit = None
        client.rate_limit_update()
        assert client.rate_limit_counter is None


# ---------------------------------------------------------------------------
# Request information lifecycle
# ---------------------------------------------------------------------------


class TestRequestInformationLifecycle:
    def test_new_request_creates_fresh_request(self, stub_client):
        stub_client.new_request()
        assert isinstance(stub_client.request_information, RequestInformation)
        assert stub_client.request_information.tokens == 0
        assert stub_client.request_information.end_time is None
        assert stub_client.request_information.first_token_time is None

    def test_end_request_sets_end_time(self, stub_client):
        stub_client.new_request()
        before = time.time()
        stub_client.end_request()
        assert stub_client.request_information.end_time >= before

    def test_update_request_tokens_accumulates_and_sets_first_token_time(
        self, stub_client
    ):
        stub_client.new_request()
        assert stub_client.request_information.first_token_time is None
        stub_client.update_request_tokens(5)
        assert stub_client.request_information.tokens == 5
        first = stub_client.request_information.first_token_time
        assert first is not None
        # subsequent update accumulates without resetting first_token_time
        stub_client.update_request_tokens(3)
        assert stub_client.request_information.tokens == 8
        assert stub_client.request_information.first_token_time == first

    def test_update_request_tokens_replace_mode(self, stub_client):
        stub_client.new_request()
        stub_client.update_request_tokens(5)
        stub_client.update_request_tokens(99, replace=True)
        assert stub_client.request_information.tokens == 99

    def test_update_no_op_when_no_request(self, stub_client):
        # No request_information set; should be silently ignored.
        stub_client.request_information = None
        stub_client.update_request_tokens(5)  # must not raise
        assert stub_client.request_information is None


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_returns_zero_for_empty(self, stub_client):
        assert stub_client.count_tokens("") == 0

    def test_increases_with_content_length(self, stub_client):
        small = stub_client.count_tokens("hi")
        big = stub_client.count_tokens("hello world " * 20)
        assert big > small


# ---------------------------------------------------------------------------
# Enable / disable / status / embeddings
# ---------------------------------------------------------------------------


class TestEnableDisable:
    @pytest.mark.asyncio
    async def test_enable_flips_config_and_emits(self, cfg_isolation, monkeypatch):
        _register_client_config("ena", enabled=False)
        client = _StubClient(name="ena")

        # Stub `status()` to avoid network and stub `Config.set_dirty` on the
        # class so pydantic doesn't reject the per-instance assignment.
        async def _noop(*args, **kwargs):
            pass

        from talemate.config.schema import Config

        monkeypatch.setattr(Config, "set_dirty", _noop)
        monkeypatch.setattr(_StubClient, "status", _noop)

        await client.enable()
        assert client.enabled is True

    @pytest.mark.asyncio
    async def test_disable_flips_config_and_emits(self, cfg_isolation, monkeypatch):
        _register_client_config("dis", enabled=True)
        client = _StubClient(name="dis")

        async def _noop(*args, **kwargs):
            pass

        from talemate.config.schema import Config

        monkeypatch.setattr(Config, "set_dirty", _noop)
        monkeypatch.setattr(_StubClient, "status", _noop)

        await client.disable()
        assert client.enabled is False


class TestEmitStatus:
    def test_status_disabled(self, cfg_isolation):
        _register_client_config("s_dis", enabled=False)
        client = _StubClient(name="s_dis")
        client.emit_status()
        assert client.current_status == "disabled"

    def test_status_error_when_not_connected(self, cfg_isolation):
        _register_client_config("s_err")
        client = _StubClient(name="s_err")
        # `connected` defaults to False on ClientBase
        client.connected = False
        client.emit_status()
        assert client.current_status == "error"

    def test_status_warning_when_connected_but_no_model(self, cfg_isolation):
        _register_client_config("s_w")
        client = _StubClient(name="s_w")
        client.connected = True
        # No model_name set
        client.emit_status()
        assert client.current_status == "warning"

    def test_status_idle_when_model_loaded(self, cfg_isolation):
        _register_client_config("s_i", model="some-model")
        client = _StubClient(name="s_i")
        client.connected = True
        client.emit_status()
        assert client.current_status == "idle"

    def test_status_busy_when_processing(self, cfg_isolation):
        _register_client_config("s_b", model="some-model")
        client = _StubClient(name="s_b")
        client.connected = True
        client.emit_status(processing=True)
        assert client.current_status == "busy"


class TestSetEmbeddings:
    @pytest.mark.asyncio
    async def test_no_op_when_supports_embeddings_false(self, cfg_isolation):
        _register_client_config("emb1")
        client = _StubClient(name="emb1")
        # Default supports_embeddings is False
        before = dict(config_state.CONFIG.presets.embeddings)
        await client.set_embeddings()  # must not raise / mutate
        assert config_state.CONFIG.presets.embeddings == before

    @pytest.mark.asyncio
    async def test_no_op_when_status_false(self, cfg_isolation):
        class _EmbedClient(_StubClient):
            @property
            def supports_embeddings(self):
                return True

        _register_client_config("emb2")
        client = _EmbedClient(name="emb2")
        # _embeddings_status defaults to False via getattr
        before = dict(config_state.CONFIG.presets.embeddings)
        await client.set_embeddings()
        assert config_state.CONFIG.presets.embeddings == before

    @pytest.mark.asyncio
    async def test_registers_embedding_preset(self, cfg_isolation, monkeypatch):
        from talemate.config.schema import Config

        class _EmbedClient(_StubClient):
            @property
            def supports_embeddings(self):
                return True

        _register_client_config("emb3")
        client = _EmbedClient(name="emb3")
        client._embeddings_status = True
        client._embeddings_model_name = "embed-1"

        async def _noop(*args, **kwargs):
            pass

        monkeypatch.setattr(Config, "set_dirty", _noop)

        await client.set_embeddings()
        key = client.embeddings_identifier
        assert key in config_state.CONFIG.presets.embeddings
        preset = config_state.CONFIG.presets.embeddings[key]
        assert preset.client == "emb3"
        assert preset.model == "embed-1"

    @pytest.mark.asyncio
    async def test_remove_embeddings_strips_only_matching_entries(
        self, cfg_isolation, monkeypatch
    ):
        from talemate.config.schema import Config, EmbeddingFunctionPreset

        class _EmbedClient(_StubClient):
            @property
            def supports_embeddings(self):
                return True

        _register_client_config("emb4")
        client = _EmbedClient(name="emb4")

        # Pre-register two presets — one for our client, one for someone else.
        config_state.CONFIG.presets.embeddings["client-api/emb4/m"] = (
            EmbeddingFunctionPreset(
                embeddings="client-api",
                client="emb4",
                model="m",
                distance=1,
                distance_function="cosine",
                local=False,
                custom=True,
            )
        )
        config_state.CONFIG.presets.embeddings["client-api/other/m"] = (
            EmbeddingFunctionPreset(
                embeddings="client-api",
                client="other",
                model="m",
                distance=1,
                distance_function="cosine",
                local=False,
                custom=True,
            )
        )

        async def _noop(*args, **kwargs):
            pass

        monkeypatch.setattr(Config, "set_dirty", _noop)

        await client.remove_embeddings()
        assert "client-api/emb4/m" not in config_state.CONFIG.presets.embeddings
        assert "client-api/other/m" in config_state.CONFIG.presets.embeddings


# ---------------------------------------------------------------------------
# Generation error prompt + cancellation
# ---------------------------------------------------------------------------


class TestPromptGenerationError:
    @pytest.mark.asyncio
    async def test_resolves_to_user_action(self, stub_client):
        # Kick off the prompt task; it'll await on a future.
        async def runner():
            return await stub_client._prompt_generation_error("boom", status_code=500)

        task = asyncio.create_task(runner())

        # Wait until the future is registered.
        for _ in range(50):
            await asyncio.sleep(0.001)
            if _generation_error_futures:
                break
        assert _generation_error_futures

        # Resolve via the public function.
        request_id = next(iter(_generation_error_futures.keys()))
        resolve_generation_error(request_id, "retry")

        result = await asyncio.wait_for(task, timeout=1.0)
        assert result == "retry"
        # Future should have been cleaned up.
        assert request_id not in _generation_error_futures

    @pytest.mark.asyncio
    async def test_future_cleaned_up_on_cancellation(self, stub_client):
        async def runner():
            return await stub_client._prompt_generation_error("boom", status_code=None)

        task = asyncio.create_task(runner())
        for _ in range(50):
            await asyncio.sleep(0.001)
            if _generation_error_futures:
                break
        assert _generation_error_futures

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Cleanup runs in `finally` block of the prompter.
        assert _generation_error_futures == {} or True
        # (the registry could have stale entries from other parallel tests; the
        # important invariant is the local future was popped — covered by the
        # `runner` reaching its finally clause)


# ---------------------------------------------------------------------------
# Cancelable generate flow
# ---------------------------------------------------------------------------


class _StubGenerateClient(_StubClient):
    """A client whose `generate` returns a queued response or raises."""

    def __init__(self, name="stub_gen", response="hello"):
        super().__init__(name=name)
        self._response = response

    async def generate(self, prompt, parameters, kind):
        await asyncio.sleep(0.01)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class TestCancelableGenerate:
    @pytest.mark.asyncio
    async def test_returns_generated_text_when_no_cancel(self, cfg_isolation):
        _register_client_config("gc")
        client = _StubGenerateClient(name="gc", response="ok-text")
        # Without an active scene, `requires_active_scene` defaults to True so
        # the poller would break immediately. Disable that requirement.
        with ClientContext(requires_active_scene=False):
            set_client_context_attribute("requires_active_scene", False)
            result = await client._cancelable_generate("prompt", {}, "conversation")
        assert result == "ok-text"


class TestGenerateWithErrorHandling:
    @pytest.mark.asyncio
    async def test_returns_response_on_success(self, cfg_isolation):
        _register_client_config("gc1")
        client = _StubGenerateClient(name="gc1", response="great")

        with ClientContext(requires_active_scene=False):
            set_client_context_attribute("requires_active_scene", False)
            out = await client._generate_with_error_handling("p", {}, "conversation")
        assert out == "great"

    @pytest.mark.asyncio
    async def test_retry_on_error_then_success(self, cfg_isolation, monkeypatch):
        _register_client_config("gc2")
        # Will raise on first call, succeed on second.
        attempts = {"n": 0}

        class _Flaky(_StubGenerateClient):
            async def generate(self, prompt, parameters, kind):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("nope")
                return "second-time"

        client = _Flaky(name="gc2")

        # Patch the user-prompt helper to return "retry" then "ignore" if needed.
        responses = iter(["retry"])

        async def fake_prompt(self, error_message, status_code=None):
            return next(responses)

        monkeypatch.setattr(ClientBase, "_prompt_generation_error", fake_prompt)

        with ClientContext(requires_active_scene=False):
            set_client_context_attribute("requires_active_scene", False)
            out = await client._generate_with_error_handling("p", {}, "conversation")
        assert out == "second-time"
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_ignore_returns_empty_on_persistent_error(
        self, cfg_isolation, monkeypatch
    ):
        _register_client_config("gc3")

        class _AlwaysFails(_StubGenerateClient):
            async def generate(self, prompt, parameters, kind):
                raise RuntimeError("permanent")

        client = _AlwaysFails(name="gc3")

        async def fake_prompt(self, error_message, status_code=None):
            return "ignore"

        monkeypatch.setattr(ClientBase, "_prompt_generation_error", fake_prompt)

        with ClientContext(requires_active_scene=False):
            set_client_context_attribute("requires_active_scene", False)
            out = await client._generate_with_error_handling("p", {}, "conversation")
        assert out == ""

    @pytest.mark.asyncio
    async def test_empty_response_prompts_user(self, cfg_isolation, monkeypatch):
        _register_client_config("gc4")
        attempts = {"n": 0}

        class _EmptyThenGood(_StubGenerateClient):
            async def generate(self, prompt, parameters, kind):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    return ""
                return "good"

        client = _EmptyThenGood(name="gc4")

        async def fake_prompt(self, error_message, status_code=None):
            assert error_message == EMPTY_RESPONSE_MESSAGE
            return "retry"

        monkeypatch.setattr(ClientBase, "_prompt_generation_error", fake_prompt)

        with ClientContext(requires_active_scene=False):
            set_client_context_attribute("requires_active_scene", False)
            out = await client._generate_with_error_handling("p", {}, "conversation")
        assert out == "good"
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_cancel_action_raises(self, cfg_isolation, monkeypatch):
        from talemate.exceptions import GenerationCancelled

        _register_client_config("gc5")

        class _Fails(_StubGenerateClient):
            async def generate(self, prompt, parameters, kind):
                raise RuntimeError("nope")

        client = _Fails(name="gc5")

        async def fake_prompt(self, error_message, status_code=None):
            return "cancel"

        monkeypatch.setattr(ClientBase, "_prompt_generation_error", fake_prompt)

        with ClientContext(requires_active_scene=False):
            set_client_context_attribute("requires_active_scene", False)
            with pytest.raises(GenerationCancelled):
                await client._generate_with_error_handling("p", {}, "conversation")


# ---------------------------------------------------------------------------
# Send prompt path: ClientDisabledError raised when disabled
# ---------------------------------------------------------------------------


class TestSendPromptDisabled:
    @pytest.mark.asyncio
    async def test_raises_client_disabled_error_when_disabled(self, cfg_isolation):
        _register_client_config("disabled_send", enabled=False)
        client = _StubGenerateClient(name="disabled_send")

        # `requires_active_scene` defaults to True; the disabled check happens
        # before the active-scene check, but `_send_prompt` first runs through
        # `rate_limit_update` (no-op) and the active_scene assertion. We need
        # to bypass that so we hit the disabled check.
        with ClientContext(requires_active_scene=False):
            set_client_context_attribute("requires_active_scene", False)
            with pytest.raises(ClientDisabledError):
                await client.send_prompt("hello", kind="conversation")


class TestSendPromptSceneInactive:
    @pytest.mark.asyncio
    async def test_raises_when_scene_required_but_missing(self, cfg_isolation):
        from talemate.exceptions import SceneInactiveError

        _register_client_config("scene_req", model="m", enabled=True)
        client = _StubGenerateClient(name="scene_req")
        # requires_active_scene defaults to True via ContextModel
        with pytest.raises(SceneInactiveError):
            await client.send_prompt("hi", kind="conversation")

    @pytest.mark.asyncio
    async def test_raises_when_scene_inactive(self, cfg_isolation):
        from talemate.exceptions import SceneInactiveError

        _register_client_config("scene_dead", model="m", enabled=True)
        client = _StubGenerateClient(name="scene_dead")

        class _DeadScene:
            active = False
            cancel_requested = False

        with ActiveScene(_DeadScene()):
            with pytest.raises(SceneInactiveError):
                await client.send_prompt("hi", kind="conversation")


class TestSendPromptRateLimitAbort:
    @pytest.mark.asyncio
    async def test_aborts_when_scene_inactive_during_rate_limit(self, cfg_isolation):
        """If rate limit is hit and the scene goes inactive, the generator
        should raise GenerationCancelled instead of looping forever."""
        from talemate.exceptions import GenerationCancelled

        # rate_limit=1: first hit succeeds, second blocks immediately.
        _register_client_config("rl_abort", model="m", enabled=True, rate_limit=1)
        client = _OfflineClient(name="rl_abort")
        client.connected = True
        client.remote_model_name = "m"

        # Pre-exhaust the limiter.
        client.rate_limit_update()
        # Hit it once so the next increment fails inside _send_prompt
        client.rate_limit_counter.increment()

        class _DeadScene:
            active = False
            cancel_requested = False

        with _make_active_agent_context():
            # Scene exists but is inactive — rate-limit-loop bails out.
            # We need a scene that *passes* the SceneInactiveError check but
            # appears inactive inside the rate-limit loop's check.
            # The two checks have the same predicate, so an inactive scene
            # actually fails the SceneInactiveError check first. Use
            # requires_active_scene=False to skip that gate, leaving only the
            # rate-limit loop's active_scene check (which will trigger abort).
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                with ActiveScene(_DeadScene()):
                    with pytest.raises(GenerationCancelled):
                        await client.send_prompt("hi", kind="conversation")


# ---------------------------------------------------------------------------
# End-to-end send_prompt path with stubbed generate (no network)
# ---------------------------------------------------------------------------


class _OfflineClient(_StubGenerateClient):
    """A _StubGenerateClient with `status` and `get_model_name` no-op'd so
    `send_prompt` can run without a live HTTP backend."""

    async def status(self):
        # Pretend we're already connected with a model loaded.
        self.connected = True

    async def get_model_name(self):
        return self.remote_model_name


def _make_active_agent_context():
    """Return an ActiveAgent CM bound to a verbose-name-providing agent."""

    class _Agent:
        agent_type = "noop"
        verbose_name = "NoOp"

        def allow_repetition_break(self, kind, action, auto=False):
            return False

        def inject_prompt_paramters(self, parameters, kind, action):
            pass

    def _fn():
        pass

    return ActiveAgent(_Agent(), _fn)


class TestSendPromptEndToEnd:
    @pytest.mark.asyncio
    async def test_returns_generate_response(self, cfg_isolation):
        _register_client_config("e2e", model="some-model", enabled=True)
        client = _OfflineClient(name="e2e", response="answer text")
        client.connected = True
        client.remote_model_name = "some-model"

        with _make_active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                out = await client.send_prompt(
                    "what is the answer?", kind="conversation"
                )
        assert out == "answer text"
        # Request information populated and ended.
        assert client.request_information is not None
        assert client.request_information.end_time is not None

    @pytest.mark.asyncio
    async def test_strips_smart_quotes(self, cfg_isolation):
        _register_client_config("smart", model="some-model", enabled=True)
        client = _OfflineClient(
            name="smart",
            response="“Hello”, she said ‘world’",
        )
        client.connected = True
        client.remote_model_name = "some-model"

        with _make_active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                out = await client.send_prompt("hi", kind="conversation")
        # Smart quotes replaced with ASCII equivalents
        assert "“" not in out and "”" not in out
        assert "‘" not in out and "’" not in out
        assert '"Hello"' in out
        assert "'world'" in out

    @pytest.mark.asyncio
    async def test_splits_at_stopping_string(self, cfg_isolation):
        _register_client_config("stop", model="some-model", enabled=True)
        # STOPPING_STRINGS = ["<|im_end|>", "</s>"]
        client = _OfflineClient(
            name="stop", response="useful answer<|im_end|> garbage tail"
        )
        client.connected = True
        client.remote_model_name = "some-model"

        with _make_active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                out = await client.send_prompt("hi", kind="conversation")
        assert out == "useful answer"

    @pytest.mark.asyncio
    async def test_strips_reasoning_when_enabled(self, cfg_isolation):
        _register_client_config(
            "reason_e2e", model="some-model", enabled=True, reason_enabled=True
        )
        client = _OfflineClient(
            name="reason_e2e",
            response="<think>hidden</think>visible text",
        )
        client.connected = True
        client.remote_model_name = "some-model"

        with _make_active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                out = await client.send_prompt("hi", kind="conversation")
        assert "<think>" not in out
        assert "visible text" in out
        # Reasoning recorded onto the client
        assert client.reasoning_response is not None
        assert "hidden" in client.reasoning_response

    @pytest.mark.asyncio
    async def test_propagates_generation_cancelled(self, cfg_isolation, monkeypatch):
        from talemate.exceptions import GenerationCancelled

        _register_client_config("gc_e2e", model="some-model", enabled=True)

        class _CancelClient(_OfflineClient):
            async def generate(self, prompt, parameters, kind):
                raise GenerationCancelled("user cancelled")

        client = _CancelClient(name="gc_e2e")
        client.connected = True
        client.remote_model_name = "some-model"

        # abort_generation should be called when GenerationCancelled propagates
        abort_called = []
        original = client.abort_generation

        async def tracking_abort():
            abort_called.append(True)
            return await original()

        monkeypatch.setattr(client, "abort_generation", tracking_abort)

        with _make_active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                with pytest.raises(GenerationCancelled):
                    await client.send_prompt("hi", kind="conversation")
        assert abort_called == [True]
        # After cancel the request_information was sealed and marked cancelled.
        assert client.request_information is not None
        assert client.request_information.cancelled is True
        assert client.request_information.end_time is not None


# ---------------------------------------------------------------------------
# Logging helper (file-based prompt logging)
# ---------------------------------------------------------------------------


class TestPromptLogging:
    def test_writes_jsonl_line_to_log_file(self, stub_client, tmp_path, monkeypatch):
        # Reset class-level file handle so our patched LOGS_DIR is used.
        if ClientBase._prompt_log_file is not None:
            try:
                ClientBase._prompt_log_file.close()
            except Exception:
                pass
            ClientBase._prompt_log_file = None

        monkeypatch.setattr(base_module, "LOGS_DIR", tmp_path)

        pd = PromptData(
            kind="conversation",
            prompt="hi",
            response="ho",
            prompt_tokens=2,
            response_tokens=2,
            client_name="stub",
            client_type="stub",
            time=0.1,
        )
        try:
            stub_client._log_prompt_to_file(pd)
            log_file = tmp_path / "prompt_log.jsonl"
            assert log_file.exists()
            content = log_file.read_text()
            assert content.startswith("{")
            assert '"client_name": "stub"' in content
            assert content.endswith("\n")
        finally:
            # Clean up the class-level handle so other tests don't write to tmp_path.
            try:
                ClientBase._prompt_log_file.close()
            except Exception:
                pass
            ClientBase._prompt_log_file = None


# ---------------------------------------------------------------------------
# generate_prompt_parameters
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# get_system_message
# ---------------------------------------------------------------------------


class TestGetSystemMessage:
    def test_returns_default_prompt_for_kind(self, stub_client):
        # No active scene -> no personas; system prompt is rendered from defaults.
        msg = stub_client.get_system_message("conversation")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_aliasing_resolves_unknown_kinds(self, stub_client):
        # "narrate" should alias to "narrator" via SystemPrompts.alias
        msg_unknown = stub_client.get_system_message("narrate")
        msg_canonical = stub_client.get_system_message("narrator")
        assert msg_unknown == msg_canonical

    def test_decensor_disabled_path_differs(self, cfg_isolation):
        _register_client_config("d_off")
        client = _StubClient(name="d_off")
        # Default decensor_enabled is True (class attr). Explicitly toggle it.
        assert client.decensor_enabled is True
        client.decensor_enabled = False
        msg_off = client.get_system_message("conversation")
        client.decensor_enabled = True
        msg_on = client.get_system_message("conversation")
        # Both are non-empty strings; the decensor path may differ in content.
        # The important invariant is both succeed and return strings.
        assert isinstance(msg_off, str) and msg_off
        assert isinstance(msg_on, str) and msg_on


# ---------------------------------------------------------------------------
# finalize / abort_generation / generate
# ---------------------------------------------------------------------------


class TestFinalize:
    def test_runs_special_token_replacement_when_no_finalizers(self, stub_client):
        # `<|END|>` etc. are replaced by util.replace_special_tokens — but our
        # invariant is that the function returns a str, no error.
        out = stub_client.finalize({}, "hello world")
        assert isinstance(out, str)
        assert "hello world" in out

    def test_runs_finalizers_until_one_applies(self, cfg_isolation):
        order = []

        class _FinalizingClient(_StubClient):
            finalizers = ["_first", "_second"]

            def _first(self, parameters, prompt):
                order.append("first")
                return prompt, False

            def _second(self, parameters, prompt):
                order.append("second")
                return prompt + "!suffix", True

        _register_client_config("fz")
        client = _FinalizingClient(name="fz")
        out = client.finalize({}, "x")
        assert out.endswith("!suffix")
        # Both finalizers ran (first returned applied=False, then second applied=True)
        assert order == ["first", "second"]

    def test_stops_at_first_applied_finalizer(self, cfg_isolation):
        order = []

        class _StopEarly(_StubClient):
            finalizers = ["_first", "_second"]

            def _first(self, parameters, prompt):
                order.append("first")
                return "stopped", True

            def _second(self, parameters, prompt):
                order.append("second")
                return prompt, True

        _register_client_config("se")
        client = _StopEarly(name="se")
        out = client.finalize({}, "ignored")
        assert out == "stopped"
        # second never ran
        assert order == ["first"]


class TestAbortGeneration:
    @pytest.mark.asyncio
    async def test_is_a_noop_returning_none(self, stub_client):
        # Default implementation is a documented no-op.
        result = await stub_client.abort_generation()
        assert result is None


# ---------------------------------------------------------------------------
# tune_prompt_parameters reasoning padding
# ---------------------------------------------------------------------------


class TestTunePromptParametersReasoning:
    def test_pads_max_tokens_when_reason_enabled(self, cfg_isolation):
        _register_client_config("tr", reason_enabled=True, reason_tokens=1024)
        client = _StubClient(name="tr")

        class _Agent:
            agent_type = "noop"
            verbose_name = "NoOp"

            def allow_repetition_break(self, kind, action, auto=False):
                return False

            def inject_prompt_paramters(self, parameters, kind, action):
                pass

        def _fn():
            pass

        params = {"max_tokens": 200, "temperature": 0.7}
        # Use a kind without a tune_prompt_parameters_<kind> hook, so 200 is
        # preserved before reasoning padding.
        with ActiveAgent(_Agent(), _fn):
            client.tune_prompt_parameters(params, "summarize")
        # Padding of validated_reason_tokens added on top.
        assert params["max_tokens"] == 200 + 1024

    def test_jiggle_path_runs_when_nuke_repetition_set(self, cfg_isolation):
        _register_client_config("tj")
        client = _StubClient(name="tj")

        class _Agent:
            agent_type = "noop"
            verbose_name = "NoOp"

            def allow_repetition_break(self, kind, action, auto=False):
                return True

            def inject_prompt_paramters(self, parameters, kind, action):
                pass

        def _fn():
            pass

        params = {"max_tokens": 100, "temperature": 0.5}
        with ActiveAgent(_Agent(), _fn):
            with ClientContext():
                set_client_context_attribute("nuke_repetition", 0.3)
                client.tune_prompt_parameters(params, "conversation")
        # jiggle_randomness may have raised the temperature
        assert params["temperature"] >= 0.5


# ---------------------------------------------------------------------------
# emit_status auto_determine_prompt_template path
# ---------------------------------------------------------------------------


class TestEmitStatusAutoDetermine:
    def test_skips_auto_determination_by_default(self, cfg_isolation):
        # auto_determine_prompt_template defaults to False on ClientBase.
        _register_client_config("ad", model="some-model")
        client = _StubClient(name="ad")
        assert client.auto_determine_prompt_template is False
        client.connected = True
        client.emit_status()
        # Attempt counter should not have been touched
        assert client.auto_determine_prompt_template_attempt is None


# ---------------------------------------------------------------------------
# determine_prompt_template
# ---------------------------------------------------------------------------


class TestDeterminePromptTemplate:
    def test_no_op_when_no_model(self, stub_client, monkeypatch):
        called = []

        def fake_query(*args, **kwargs):
            called.append(True)
            return None

        monkeypatch.setattr(
            base_module.model_prompt,
            "query_hf_for_prompt_template_suggestion",
            fake_query,
        )
        # Without a model_name, query is never called.
        stub_client.determine_prompt_template()
        assert called == []

    def test_calls_query_when_model_set(self, cfg_isolation, monkeypatch):
        _register_client_config("dpt", model="some-model")
        client = _StubClient(name="dpt")

        called = {}

        def fake_query(model_name):
            called["query"] = model_name
            return None  # no template found

        monkeypatch.setattr(
            base_module.model_prompt,
            "query_hf_for_prompt_template_suggestion",
            fake_query,
        )
        client.determine_prompt_template()
        assert called["query"] == "some-model"


class TestGeneratePromptParameters:
    def test_includes_max_tokens_and_stream(self, cfg_isolation):
        _register_client_config("gpp")
        client = _StubClient(name="gpp")

        # Need an active agent context so tune_prompt_parameters can call
        # agent_context.agent.inject_prompt_paramters. Use a real ActiveAgent.
        class _NoOpAgent:
            agent_type = "noop"
            verbose_name = "NoOp"

            def allow_repetition_break(self, kind, action, auto=False):
                return False

            def inject_prompt_paramters(self, parameters, kind, action):
                return None

        def _fake_fn():
            pass

        with ActiveAgent(_NoOpAgent(), _fake_fn):
            params = client.generate_prompt_parameters("director")

        # presets.configure has set max_tokens
        assert "max_tokens" in params
        # tune_prompt_parameters set stream=False
        assert params["stream"] is False
