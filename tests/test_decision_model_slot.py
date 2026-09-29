"""The configured decision-model slot: its settings, its wiring and its status.

Every request in here goes through a fake HTTP transport. No paid call is made.
"""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pydantic
import pytest
from pydantic import TypeAdapter

from talemate.config import get_config
from talemate.config.schema import Config, DecisionModelConfig
from talemate.decisions import (
    DecisionHandle,
    FailureCode,
    PolicyInvocation,
    Unavailable,
    decision_service,
)
from talemate.decisions import slot as slot_module
from talemate.decisions.slot import (
    DecisionModelSlotStatus,
    configure_decision_service,
    decision_model_slot,
    decision_model_status,
    emit_decision_model_status,
)
from talemate.prompts.base import PrependTemplateDirectories
from talemate.server.config import ConfigApplyPipeline, DecisionModelApplySection


API_KEY = "sk-or-test-key"
QUESTION = {"only": {"type": "noul", "instructions": "Does this passage repeat?"}}
ANSWERED = {
    "model": "jev-1.13.0",
    "answers": {"only": {"type": "noul", "noul": 0.93}},
    "usage": {"input_tokens": 90, "output_tokens": 4},
}

POLICY = """
{% set r = decide("repetition", state={"passage": passage}, questions={"only": {
    "type": "noul", "instructions": "Does this passage repeat?"}}) %}
{{ decision_result("decided") }}
"""


class Calls:
    """A fake transport that counts what the adapter actually sent."""

    def __init__(self, responder):
        self.sent = []

        async def handle(request):
            self.sent.append(request)
            return await responder(request)

        self.transport = httpx.MockTransport(handle)


def answers(body=ANSWERED, status=200):
    async def responder(request):
        return httpx.Response(status, json=body)

    return Calls(responder)


def hangs():
    async def responder(request):
        await asyncio.sleep(30)
        return httpx.Response(200, json=ANSWERED)

    return Calls(responder)


@pytest.fixture
def slot():
    config = get_config()
    saved = (
        config.decision_model,
        config.openrouter.api_key,
        decision_service.provider,
        decision_service.enabled,
        decision_service.timeout_seconds,
        decision_model_slot.last_failure,
    )
    config.decision_model = DecisionModelConfig()
    config.openrouter.api_key = None
    yield config
    (
        config.decision_model,
        config.openrouter.api_key,
        decision_service.provider,
        decision_service.enabled,
        decision_service.timeout_seconds,
        decision_model_slot.last_failure,
    ) = saved
    decision_service.log.clear_finished()


def use(calls, **settings):
    """Apply a slot configuration and give its provider the fake transport."""
    config = get_config()
    config.decision_model = DecisionModelConfig(**settings)
    configure_decision_service()
    decision_service.provider.transport = calls.transport


async def evaluate(label="repetition"):
    return await decision_service.evaluate(
        label,
        state={"passage": "complete text"},
        questions=QUESTION,
        invocation_id="invocation",
        template_uid="editor.decision-policy",
    )


class TestSlotSettings:
    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "  ",
            "http://localhost:8009",
            "https://example.test/prefix/",
            "http://[::1]:8009",
        ],
    )
    def test_systemone_url_and_optional_key_roundtrip(self, base_url):
        settings = DecisionModelConfig(
            provider="systemone", base_url=base_url, api_key="systemone-test-credential"
        )
        assert DecisionModelConfig.model_validate(settings.model_dump()) == settings
        assert settings.base_url == base_url.strip().rstrip("/")
        assert settings.enabled is False

    @pytest.mark.parametrize(
        "base_url",
        [
            "localhost:8009",
            "ftp://localhost",
            "file:///tmp/server",
            "https://",
            "http://user:password@localhost",
            "http://localhost?key=test",
            "http://localhost#fragment",
            "http://localhost?",
            "http://localhost#",
        ],
    )
    def test_invalid_systemone_base_url_is_rejected(self, base_url):
        with pytest.raises(pydantic.ValidationError):
            DecisionModelConfig(provider="systemone", base_url=base_url)

    def test_systemone_key_is_encrypted_and_roundtrips_through_config_save(
        self, slot, tmp_path, monkeypatch
    ):
        import yaml
        from cryptography.fernet import Fernet
        from talemate.config import state as config_state
        from talemate.util import encryption

        monkeypatch.setattr(encryption, "_fernet", Fernet(Fernet.generate_key()))
        slot.decision_model = DecisionModelConfig(
            provider="systemone",
            base_url="http://localhost:8009",
            api_key="systemone-test-credential",
        )
        path = tmp_path / "systemone.yaml"
        monkeypatch.setattr(config_state, "CONFIG_FILE", str(path))
        config_state.save_config()
        stored = yaml.safe_load(path.read_text())
        assert stored["decision_model"]["api_key"].startswith(encryption.ENC_PREFIX)
        assert "systemone-test-credential" not in path.read_text()
        encryption.decrypt_sensitive_values(stored)
        assert Config(**stored).decision_model == slot.decision_model

    def test_a_new_configuration_defaults_off(self):
        slot = Config().decision_model
        assert slot.enabled is False
        assert slot.provider == "openrouter"
        assert slot.model == "typesafe/jev-1.13"
        assert slot.timeout_seconds == 1.5
        assert slot.max_input_tokens == 64000
        assert slot.max_question_input_tokens == 32000
        assert slot.input_token_multiplier == 1.5

    def test_a_configuration_without_the_section_gets_the_defaults(self):
        assert Config(**{"clients": {}}).decision_model == DecisionModelConfig()

    def test_explicit_slot_values_survive_a_reload(self):
        saved = Config(
            **{
                "decision_model": {
                    "enabled": True,
                    "provider": "openrouter",
                    "model": "some/other-decision-model",
                    "timeout_seconds": 4.25,
                    "max_input_tokens": 12000,
                    "max_question_input_tokens": 6000,
                    "input_token_multiplier": 1.75,
                }
            }
        ).model_dump()

        reloaded = Config(**saved).decision_model

        assert reloaded.enabled is True
        assert reloaded.model == "some/other-decision-model"
        assert reloaded.timeout_seconds == 4.25
        assert reloaded.max_input_tokens == 12000
        assert reloaded.max_question_input_tokens == 6000
        assert reloaded.input_token_multiplier == 1.75

    @pytest.mark.parametrize("field", ["max_input_tokens", "max_question_input_tokens"])
    @pytest.mark.parametrize(
        "value", [-1, 1.5, True, "32000", None, float("inf"), float("nan")]
    )
    def test_invalid_input_limit_is_rejected(self, field, value):
        with pytest.raises(pydantic.ValidationError):
            DecisionModelConfig(**{field: value})

    @pytest.mark.parametrize(
        "value", [0, 0.99, float("nan"), float("inf"), True, "1.5"]
    )
    def test_invalid_input_multiplier_is_rejected(self, value):
        with pytest.raises(pydantic.ValidationError):
            DecisionModelConfig(input_token_multiplier=value)

    @pytest.mark.parametrize(
        "model", ["typesafe/jev-1.13", "some/other-decision-model"]
    )
    def test_configured_bounds_reach_provider_independently_of_model(self, slot, model):
        slot.decision_model = DecisionModelConfig(
            model=model,
            max_input_tokens=12000,
            max_question_input_tokens=6000,
            input_token_multiplier=1.75,
        )
        configure_decision_service()
        caps = decision_service.provider.capabilities
        assert caps.max_input_tokens == 12000
        assert caps.max_question_input_tokens == 6000
        assert caps.input_token_multiplier == 1.75

    def test_config_can_explicitly_leave_bounds_undeclared(self, slot):
        slot.decision_model = DecisionModelConfig(
            max_input_tokens=0, max_question_input_tokens=0
        )
        configure_decision_service()
        caps = decision_service.provider.capabilities
        assert caps.max_input_tokens is None
        assert caps.max_question_input_tokens is None

    @pytest.mark.parametrize(
        "timeout", [0, -1, -0.5, float("inf"), float("-inf"), float("nan"), "soon"]
    )
    def test_an_invalid_timeout_is_rejected(self, timeout):
        with pytest.raises(pydantic.ValidationError):
            DecisionModelConfig(timeout_seconds=timeout)

    def test_another_provider_is_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            DecisionModelConfig(provider="anthropic")


class TestStatus:
    @pytest.mark.parametrize(
        "enabled,base_url,state,missing",
        [
            (False, "http://localhost:8009", "disabled", []),
            (True, "", "incomplete", ["base_url"]),
            (True, "http://localhost:8009", "ready", []),
        ],
    )
    def test_systemone_slot_state_needs_no_key_or_probe(
        self, slot, enabled, base_url, state, missing
    ):
        calls = answers()
        use(
            calls,
            provider="systemone",
            enabled=enabled,
            base_url=base_url,
            model="server-model",
        )
        status = decision_model_status()
        assert status.state == state
        assert status.missing == missing
        assert status.provider == "systemone"
        assert status.model == "server-model"
        assert decision_service.provider.ready is bool(base_url)
        assert calls.sent == []

    async def test_systemone_slot_uses_only_its_own_key_and_applies_provider_switch(
        self, slot
    ):
        slot.openrouter.api_key = API_KEY
        calls = answers()
        use(
            calls,
            provider="systemone",
            enabled=True,
            base_url="http://localhost:8009",
            model="server-model",
            api_key="systemone-test-credential",
        )
        assert isinstance(await evaluate(), DecisionHandle)
        assert (
            calls.sent[0].headers["authorization"] == "Bearer systemone-test-credential"
        )
        assert str(calls.sent[0].url) == "http://localhost:8009/v1/systemone"
        assert "systemone-test-credential" not in str(decision_model_status())
        slot.decision_model.api_key = None
        assert isinstance(await evaluate(), DecisionHandle)
        assert "authorization" not in calls.sent[1].headers
        slot.decision_model.provider = "openrouter"
        configure_decision_service()
        decision_service.provider.transport = calls.transport
        assert isinstance(await evaluate(), DecisionHandle)
        assert calls.sent[2].headers["authorization"] == f"Bearer {API_KEY}"
        assert str(calls.sent[2].url) == "https://openrouter.ai/api/alpha/decisions"

    def test_a_disabled_slot_reports_disabled(self, slot):
        slot.openrouter.api_key = API_KEY
        configure_decision_service()

        assert decision_model_status().state == "disabled"

    def test_an_enabled_slot_without_a_key_is_incomplete(self, slot):
        slot.decision_model = DecisionModelConfig(enabled=True)
        configure_decision_service()

        status = decision_model_status()
        assert status.state == "incomplete"
        assert status.missing == ["api_key"]

    def test_an_enabled_slot_with_the_shared_key_is_ready(self, slot):
        slot.openrouter.api_key = API_KEY
        slot.decision_model = DecisionModelConfig(enabled=True)
        configure_decision_service()

        status = decision_model_status()
        assert status.state == "ready"
        assert status.missing == []
        assert status.model == "typesafe/jev-1.13"
        assert status.timeout_seconds == 1.5
        assert API_KEY not in str(status)

    async def test_changing_the_configuration_retires_the_recorded_failure(self, slot):
        slot.openrouter.api_key = API_KEY
        use(answers({"error": {"code": 401}}, status=401), enabled=True)
        await evaluate()
        assert decision_model_status().last_failure

        use(answers(), enabled=False)

        reported = decision_model_status()
        assert reported.state == "disabled"
        assert reported.last_failure is None

    async def test_the_status_reports_a_failure_and_clears_it_on_success(self, slot):
        slot.openrouter.api_key = API_KEY
        failing = answers({"error": {"code": 401}}, status=401)
        use(failing, enabled=True)

        await evaluate()

        failure = decision_model_status().last_failure
        assert failure.code == FailureCode.AUTHENTICATION
        assert failure.dispatched is True

        decision_service.provider.transport = answers().transport
        await evaluate()

        assert decision_model_status().last_failure is None

    async def test_the_emitted_status_keeps_its_wire_shape(self, slot, monkeypatch):
        slot.openrouter.api_key = API_KEY
        use(answers({"error": {"code": 401}}, status=401), enabled=True)
        await evaluate()
        emitted = []
        monkeypatch.setattr(
            slot_module, "emit", lambda typ, data: emitted.append((typ, data))
        )

        emit_decision_model_status()

        ((typ, data),) = emitted
        assert typ == "decision_model_status"
        timestamp = data["last_failure"].pop("timestamp")
        assert isinstance(timestamp, str) and timestamp
        assert data == {
            "enabled": True,
            "provider": "openrouter",
            "model": "typesafe/jev-1.13",
            "timeout_seconds": 1.5,
            "state": "ready",
            "missing": [],
            "last_failure": {"code": "authentication", "dispatched": True},
        }

    @pytest.mark.parametrize(
        "field",
        [{"state": "unknown"}, {"provider": "fake"}, {"missing": ["password"]}],
    )
    def test_the_status_fields_take_only_known_values(self, field):
        status = {
            "enabled": True,
            "provider": None,
            "model": "",
            "timeout_seconds": 1.5,
            "state": "incomplete",
            "missing": ["model", "base_url", "api_key"],
            "last_failure": None,
        }
        DecisionModelSlotStatus(**status)
        with pytest.raises(pydantic.ValidationError):
            DecisionModelSlotStatus(**{**status, **field})


class TestOptIn:
    @pytest.mark.parametrize(
        "enabled,base_url,code",
        [
            (False, "http://localhost:8009", FailureCode.DISABLED),
            (True, "", FailureCode.UNAVAILABLE),
        ],
    )
    async def test_systemone_disabled_or_incomplete_slot_does_not_dispatch(
        self, slot, enabled, base_url, code
    ):
        calls = answers()
        use(calls, provider="systemone", enabled=enabled, base_url=base_url)
        assert (await evaluate()).failure.code == code
        assert calls.sent == []

    def test_saving_a_key_never_enables_the_slot(self, slot):
        calls = answers()
        use(calls)

        slot.openrouter.api_key = API_KEY
        configure_decision_service()
        decision_model_status()

        assert slot.decision_model.enabled is False
        assert decision_service.enabled is False
        assert calls.sent == []

    async def test_a_disabled_slot_sends_nothing_although_it_is_configured(self, slot):
        slot.openrouter.api_key = API_KEY
        calls = answers()
        use(calls, enabled=False, model="typesafe/jev-1.13")

        result = await evaluate()

        assert isinstance(result, Unavailable)
        assert result.failure.code == FailureCode.DISABLED
        assert calls.sent == []

    async def test_disabling_the_slot_suppresses_the_next_request(self, slot):
        slot.openrouter.api_key = API_KEY
        calls = answers()
        use(calls, enabled=True)
        assert isinstance(await evaluate(), DecisionHandle)

        use(calls, enabled=False)
        result = await evaluate()

        assert isinstance(result, Unavailable)
        assert len(calls.sent) == 1
        assert slot.openrouter.api_key == API_KEY
        assert slot.decision_model.model == "typesafe/jev-1.13"

    async def test_an_enabled_slot_without_a_key_never_sends_the_request(self, slot):
        calls = answers()
        use(calls, enabled=True)

        result = await evaluate()

        assert isinstance(result, Unavailable)
        assert result.failure.code == FailureCode.UNAVAILABLE
        assert calls.sent == []
        record = decision_service.log.records[result.request_id]
        assert record.dispatched is False


class TestDeadline:
    async def test_a_hanging_transport_is_stopped_without_a_retry(self, slot):
        slot.openrouter.api_key = API_KEY
        calls = hangs()
        use(calls, enabled=True, timeout_seconds=0.05)

        result = await evaluate()

        assert isinstance(result, Unavailable)
        assert result.failure.code == FailureCode.TIMEOUT
        assert len(calls.sent) == 1
        record = decision_service.log.records[result.request_id]
        assert record.status == "failed"
        assert record.answers is None

    async def test_a_late_completion_cannot_change_the_outcome(self, slot):
        slot.openrouter.api_key = API_KEY
        completed = asyncio.Event()

        async def responder(request):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass
            completed.set()
            return httpx.Response(200, json=ANSWERED)

        # a transport that swallows the cancellation still answers, after the
        # deadline has already returned its failure
        calls = Calls(responder)
        use(calls, enabled=True, timeout_seconds=0.05)

        result = await evaluate()
        await asyncio.wait_for(completed.wait(), timeout=5)
        await asyncio.sleep(0.05)

        assert isinstance(result, Unavailable)
        assert result.failure.code == FailureCode.TIMEOUT
        record = decision_service.log.records[result.request_id]
        assert record.status == "failed"
        assert record.answers is None
        assert record.raw is None
        assert decision_model_slot.last_failure.code == FailureCode.TIMEOUT

    async def test_the_configured_timeout_is_the_deadline(self, slot):
        slot.openrouter.api_key = API_KEY
        use(hangs(), enabled=True, timeout_seconds=0.2)

        started = asyncio.get_running_loop().time()
        await evaluate()
        elapsed = asyncio.get_running_loop().time() - started

        assert 0.2 <= elapsed < 1.0


class TestContinuation:
    @pytest.fixture
    def policy(self, slot, tmp_path, monkeypatch):
        (tmp_path / "slot.jinja2").write_text(POLICY)
        text = TypeAdapter(str)
        fallback = AsyncMock(return_value="existing behavior")

        def create():
            return PolicyInvocation(
                "slot",
                service=decision_service,
                variables={"passage": "complete text"},
                validate_result=lambda value: text.validate_python(value, strict=True),
                disabled_path=fallback,
                original_result="complete text",
            )

        with PrependTemplateDirectories(str(tmp_path)):
            yield create, fallback

    @pytest.mark.parametrize(
        "failure", ["wrong_type", "missing", "timeout", "transport"]
    )
    async def test_systemone_failure_takes_existing_path_once(
        self, slot, policy, failure
    ):
        create, fallback = policy
        if failure == "timeout":
            calls = hangs()
        elif failure == "transport":
            calls = answers(status=500)
        else:
            calls = answers(
                {
                    "answers": {}
                    if failure == "missing"
                    else {"only": {"type": "choice", "noul": 0.93}}
                }
            )
        use(
            calls,
            provider="systemone",
            enabled=True,
            base_url="http://localhost:8009",
            timeout_seconds=0.05,
        )

        assert await asyncio.wait_for(create().run(), timeout=2) == "existing behavior"
        fallback.assert_awaited_once()
        assert len(calls.sent) == 1
        assert (
            decision_model_status().last_failure.code
            == {
                "timeout": FailureCode.TIMEOUT,
                "transport": FailureCode.TRANSPORT,
                "wrong_type": FailureCode.INVALID_RESPONSE,
                "missing": FailureCode.INVALID_RESPONSE,
            }[failure]
        )

    @pytest.mark.parametrize(
        "status,code",
        [
            (401, FailureCode.AUTHENTICATION),
            (413, FailureCode.OVERSIZE),
            (500, FailureCode.TRANSPORT),
        ],
    )
    async def test_a_failed_request_continues_like_a_disabled_slot(
        self, slot, policy, status, code
    ):
        create, fallback = policy
        slot.openrouter.api_key = API_KEY

        use(answers(), enabled=False)
        while_disabled = await create().run()

        use(answers({"error": {"code": status}}, status=status), enabled=True)
        while_failing = await create().run()

        assert while_failing == while_disabled == "existing behavior"
        assert fallback.await_count == 2
        failed = [
            record
            for record in decision_service.log.records.values()
            if record.failure and record.failure.code == code
        ]
        assert len(failed) == 1
        assert API_KEY not in str(failed[0].failure) + str(failed[0].raw)

    async def test_a_malformed_answer_continues_like_a_disabled_slot(
        self, slot, policy
    ):
        create, fallback = policy
        slot.openrouter.api_key = API_KEY

        use(
            answers({"answers": {"only": {"type": "noul", "noul": "yes"}}}),
            enabled=True,
        )
        result = await create().run()

        assert result == "existing behavior"
        assert fallback.await_count == 1

    async def test_a_successful_request_lets_the_policy_decide(self, slot, policy):
        create, fallback = policy
        slot.openrouter.api_key = API_KEY

        use(answers(), enabled=True)
        result = await create().run()

        assert result == "decided"
        assert fallback.await_count == 0


class TestApplySection:
    def test_a_saved_key_re_applies_the_slot(self):
        section = DecisionModelApplySection()
        before = Config().model_dump()
        after = Config(**{"openrouter": {"api_key": API_KEY}}).model_dump()

        assert section.changed(before, after) is True

    def test_a_saved_slot_change_re_applies_the_slot(self):
        section = DecisionModelApplySection()
        before = Config().model_dump()
        after = Config(**{"decision_model": {"enabled": True}}).model_dump()

        assert section.changed(before, after) is True

    async def test_a_key_only_save_applies_the_slot_without_enabling_it(self, slot):
        calls = answers()
        use(calls)
        before = get_config().model_dump()
        slot.openrouter.api_key = API_KEY
        after = get_config().model_dump()

        outcome = await ConfigApplyPipeline().run(before, after)

        assert outcome.error is None
        assert outcome.applied == {"decision_model"}
        assert slot.decision_model.enabled is False
        assert decision_service.enabled is False
        assert decision_model_status().state == "disabled"

        decision_service.provider.transport = calls.transport
        result = await evaluate()

        assert result.failure.code == FailureCode.DISABLED
        assert calls.sent == []

    def test_an_unrelated_change_leaves_the_slot_alone(self):
        section = DecisionModelApplySection()
        before = Config().model_dump()
        after = Config(**{"sound": {"muted": True}}).model_dump()

        assert section.changed(before, after) is False
