"""Fake HTTP responses include recorded distributions whose probabilities sum to 0.99."""

import json
from pathlib import Path

import httpx
import pytest

from talemate.decisions import (
    DecisionHandle,
    DecisionService,
    FailureCode,
    ProviderCapabilities,
    Unavailable,
)
from talemate.decisions.providers.openrouter import (
    DECISIONS_URL,
    OpenRouterDecisionProvider,
)


API_KEY = "sk-or-test-key"
FIXTURES = Path(__file__).parents[1] / "data" / "decisions"

QUESTION_CASES = {
    "noul": (
        {
            "type": "noul",
            "instructions": "Does this passage repeat an earlier story beat?",
            "true_criteria": "It restates a beat the history already delivered.",
            "false_criteria": "It adds a new action or a new point.",
        },
        {
            "type": "noul",
            "instructions": "Does this passage repeat an earlier story beat?",
            "criteria": {
                "true": "It restates a beat the history already delivered.",
                "false": "It adds a new action or a new point.",
            },
        },
        {"type": "noul", "noul": 0.93},
        {"type": "noul", "p_true": 0.93},
    ),
    "choice": (
        {
            "type": "choice",
            "instructions": "Which revision does this passage need?",
            "options": {"rewrite": "Rewrite the passage", "leave": "Leave it alone"},
        },
        {
            "type": "choice",
            "instructions": "Which revision does this passage need?",
            "criteria": {
                "rewrite": "Rewrite the passage",
                "leave": "Leave it alone",
            },
        },
        {
            "type": "choice",
            "choice": "rewrite",
            "probabilities": {"rewrite": 0.8, "leave": 0.2},
            "confidence": 0.6,
        },
        {
            "type": "choice",
            "selected": "rewrite",
            "probabilities": {"rewrite": 0.8, "leave": 0.2},
            "confidence": 0.6,
        },
    ),
    "score": (
        {
            "type": "score",
            "instructions": "How ornate is the prose?",
            "rubric": ["Plain", "Lean", "Purple"],
        },
        {
            "type": "score",
            "instructions": "How ornate is the prose?",
            "criteria": ["Plain", "Lean", "Purple"],
        },
        {
            "type": "score",
            "score": 1.43,
            "confidence": 0.35,
            "legend": {"0": "Plain", "1": "Lean", "2": "Purple"},
            "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43},
        },
        {
            "type": "score",
            "value": 1.43,
            "probabilities": [0.0, 0.57, 0.43],
            "legend": ["Plain", "Lean", "Purple"],
            "confidence": 0.35,
        },
    ),
}


def transport(handler):
    return httpx.MockTransport(handler)


def responder(body, status=200, sent=None, text=None):
    def handler(request):
        if sent is not None:
            sent["url"] = str(request.url)
            sent["headers"] = dict(request.headers)
            sent["body"] = json.loads(request.content)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    return handler


def service(handler, *, model="typesafe/jev-1.13", key=API_KEY, **kwargs):
    provider = OpenRouterDecisionProvider(
        model, lambda: key, transport=transport(handler)
    )
    return DecisionService(provider, enabled=True, **kwargs)


async def evaluate(decision_service, questions, state="the passage"):
    return await decision_service.evaluate(
        "repetition",
        state=state,
        questions=questions,
        invocation_id="invocation",
        template_uid="editor.decision-policy",
    )


@pytest.mark.parametrize("question_type", sorted(QUESTION_CASES))
async def test_every_question_type_reaches_the_decisions_endpoint(
    question_type, monkeypatch
):
    import importlib

    service_module = importlib.import_module("talemate.decisions.service")
    count_tokens = service_module.count_tokens
    counted = []

    def count(text):
        counted.append(json.loads(text))
        return count_tokens(text)

    monkeypatch.setattr(service_module, "count_tokens", count)
    question, wire_question, wire_answer, normalized = QUESTION_CASES[question_type]
    sent = {}
    body = {
        "model": "jev-1.13.0",
        "answers": {"only": wire_answer},
        "usage": {"input_tokens": 120, "output_tokens": 8},
    }
    decision_service = service(responder(body, sent=sent))
    decision_service.provider.capabilities = ProviderCapabilities(
        max_input_tokens=64000, max_question_input_tokens=32000
    )

    result = await evaluate(decision_service, {"only": question})

    assert sent["url"] == DECISIONS_URL
    assert sent["headers"]["authorization"] == f"Bearer {API_KEY}"
    assert sent["body"] == {
        "model": "typesafe/jev-1.13",
        "state": "the passage",
        "questions": {"only": wire_question},
    }
    assert isinstance(result, DecisionHandle)
    assert counted == [sent["body"]["state"], sent["body"]["questions"]]
    assert result.answers["only"].model_dump() == normalized
    assert decision_service.log.records[result.request_id].raw == body


@pytest.mark.parametrize(
    "criteria",
    [
        {},
        {"true_criteria": "Present"},
        {"false_criteria": "Absent"},
        {"true_criteria": None, "false_criteria": None},
    ],
)
async def test_a_noul_question_without_a_complete_criteria_pair_omits_it(criteria):
    sent = {}
    decision_service = service(
        responder(
            {"answers": {"only": {"type": "noul", "noul": 0.1}}},
            sent=sent,
        )
    )

    await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?", **criteria}},
    )

    assert sent["body"]["questions"]["only"] == {
        "type": "noul",
        "instructions": "Does it repeat?",
    }


@pytest.mark.parametrize("criterion", ["true_criteria", "false_criteria"])
async def test_omitted_noul_criterion_does_not_exhaust_input_bound(criterion):
    sent = {}
    decision_service = service(
        responder({"answers": {"only": {"type": "noul", "noul": 0.1}}}, sent=sent)
    )
    decision_service.provider.capabilities = ProviderCapabilities(
        max_input_tokens=100, max_question_input_tokens=100, input_token_multiplier=1.5
    )
    questions = {
        "only": {
            "type": "noul",
            "instructions": "Does it repeat?",
            criterion: "unused " * 1000,
        }
    }

    result = await evaluate(decision_service, questions)

    assert isinstance(result, DecisionHandle)
    assert sent["body"]["questions"]["only"] == {
        "type": "noul",
        "instructions": "Does it repeat?",
    }
    record = decision_service.log.records[result.request_id]
    assert record.dispatched
    assert record.questions["only"][criterion] == questions["only"][criterion]


async def test_state_is_submitted_unchanged():
    sent = {}
    state = {"passage": "complete text", "history": ["earlier"]}
    decision_service = service(
        responder({"answers": {"only": {"type": "noul", "noul": 0.1}}}, sent=sent)
    )

    await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
        state=state,
    )

    assert sent["body"]["state"] == state


@pytest.mark.parametrize(
    "status,code",
    [
        (401, FailureCode.AUTHENTICATION),
        (403, FailureCode.AUTHENTICATION),
        (413, FailureCode.OVERSIZE),
        (422, FailureCode.TRANSPORT),
        (429, FailureCode.TRANSPORT),
        (529, FailureCode.TRANSPORT),
        (302, FailureCode.TRANSPORT),
    ],
)
async def test_response_status_maps_to_a_typed_failure(status, code):
    decision_service = service(
        responder({"error": {"code": status, "message": "refused"}}, status=status)
    )

    result = await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    assert isinstance(result, Unavailable)
    assert result.failure.code == code
    record = decision_service.log.records[result.request_id]
    assert record.raw is None
    assert API_KEY not in json.dumps(
        {"message": result.failure.message, "questions": record.questions}
    )


@pytest.mark.parametrize(
    "body",
    [
        {"detail": {"error_type": "max_tokens_exceeded"}},
        json.loads((FIXTURES / "recorded-token-limit-error.json").read_text()),
    ],
)
async def test_token_limit_errors_are_oversize_without_exposing_the_body(body):
    sent = {}
    decision_service = service(responder(body, status=400, sent=sent))

    result = await evaluate(decision_service, {"only": QUESTION_CASES["noul"][0]})

    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.OVERSIZE
    record = decision_service.log.records[result.request_id]
    assert record.dispatched
    assert record.raw is None
    assert sent["url"] == DECISIONS_URL


@pytest.mark.parametrize(
    "body,text",
    [
        (None, "max_tokens_exceeded"),
        (
            None,
            '<html>HTTP 400: {"detail":{"error_type":"max_tokens_exceeded"}}</html>',
        ),
        (None, '{"detail":{"error_type":"max_tokens_exceeded"},"bad":NaN}'),
        ([], None),
        (None, None),
        ({"detail": "max_tokens_exceeded"}, None),
        ({"detail": {"error_type": "other"}}, None),
        ({"detail": {"error_type": "MAX_TOKENS_EXCEEDED"}}, None),
        ({"error": "max_tokens_exceeded"}, None),
        ({"error": {"message": "max_tokens_exceeded"}}, None),
        ({"error": {"message": 'HTTP 400: {"detail":{"error_type":"other"}}'}}, None),
        (
            {
                "error": {
                    "message": 'HTTP 400: {"detail":{"error_type":"max_tokens_exceeded"}} trailing'
                }
            },
            None,
        ),
        (
            {
                "error": {
                    "message": 'HTTP 413: {"detail":{"error_type":"max_tokens_exceeded"}}'
                }
            },
            None,
        ),
        ({"error": {"message": "HTTP 400: []"}}, None),
        ({"error": {"message": "HTTP 400: not JSON"}}, None),
        ({"error": {"message": None}}, None),
    ],
)
async def test_unknown_or_malformed_bad_requests_remain_transport(body, text):
    decision_service = service(responder(body, text=text, status=400))

    result = await evaluate(decision_service, {"only": QUESTION_CASES["noul"][0]})

    assert result.failure.code == FailureCode.TRANSPORT
    assert decision_service.log.records[result.request_id].raw is None


@pytest.mark.parametrize("status", [401, 403, 422, 500])
async def test_token_limit_body_does_not_override_other_http_statuses(status):
    body = json.loads((FIXTURES / "recorded-token-limit-error.json").read_text())
    decision_service = service(responder(body, status=status))

    result = await evaluate(decision_service, {"only": QUESTION_CASES["noul"][0]})

    assert result.failure.code == (
        FailureCode.AUTHENTICATION if status in (401, 403) else FailureCode.TRANSPORT
    )


@pytest.mark.parametrize(
    "recorded",
    json.loads((FIXTURES / "recorded-rounded-scores.json").read_text()),
)
async def test_recorded_rounded_score_batches_complete_and_preserve_raw(recorded):
    decision_service = service(responder(recorded["response"]))

    result = await evaluate(decision_service, recorded["questions"])

    assert isinstance(result, DecisionHandle)
    record = decision_service.log.records[result.request_id]
    assert record.raw == recorded["response"]
    for key, answer in result.answers.items():
        raw = recorded["response"]["answers"][key]
        assert sum(answer.probabilities) == pytest.approx(1.0)
        assert answer.value == raw["score"]
        assert answer.confidence == raw["confidence"]


@pytest.mark.parametrize(
    "recorded",
    json.loads((FIXTURES / "recorded-rounded-choices.json").read_text()),
)
async def test_recorded_rounded_choice_batches_complete_and_preserve_raw(recorded):
    decision_service = service(responder(recorded["response"]))

    result = await evaluate(decision_service, recorded["questions"])

    assert isinstance(result, DecisionHandle)
    record = decision_service.log.records[result.request_id]
    assert record.raw == recorded["response"]
    for key, answer in result.answers.items():
        raw = recorded["response"]["answers"][key]
        assert answer.selected == raw["choice"]
        assert answer.confidence == raw["confidence"]
        assert sum(answer.probabilities.values()) == pytest.approx(1.0)
        assert answer.probabilities == pytest.approx(
            {
                option: value / sum(raw["probabilities"].values())
                for option, value in raw["probabilities"].items()
            }
        )


async def test_a_connection_error_is_a_transport_failure():
    def handler(request):
        raise httpx.ConnectError("unreachable", request=request)

    result = await evaluate(
        service(handler),
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.TRANSPORT


@pytest.mark.parametrize(
    "body,text",
    [
        (None, "not json at all"),
        (None, '{"answers": {"only": {"type": "noul", "noul": NaN}}}'),
        (None, '{"answers": {"only": {"type": "noul", "noul": 1e400}}}'),
        ({"answers": "not a mapping"}, None),
        ({"usage": {}}, None),
    ],
)
async def test_an_unreadable_body_is_an_invalid_response(body, text):
    decision_service = service(responder(body, text=text))

    result = await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    # what arrived is the one thing a reader needs to diagnose a shape change
    assert decision_service.log.records[result.request_id].raw


@pytest.mark.parametrize(
    "body,text,detail",
    [
        (None, "<html>not json at all</html>", "parse error at char 0"),
        (None, '{"answers": {"only": {"noul": 1e400}}}', "nonfinite number"),
        ({"result": {"answers": {"only": {"noul": 0.93}}}}, None, "no answers mapping"),
    ],
)
async def test_an_unreadable_body_is_recorded_as_facts_about_the_response(
    body, text, detail
):
    secret = "a passage the scene sent and an apparent key sk-or-leaked"
    decision_service = service(
        responder(body, text=None if text is None else f"{text}{secret}")
    )

    result = await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    raw = decision_service.log.records[result.request_id].raw
    assert raw.startswith("malformed response: status 200, ")
    assert raw.endswith(f", {detail}")
    assert "bytes," in raw
    # nothing of the body reaches the record, whatever it held
    assert secret not in raw
    assert len(raw) < 120


@pytest.mark.parametrize(
    "question,answer",
    [
        (
            {"type": "noul", "instructions": "Does it repeat?"},
            {"type": "choice", "noul": 0.93},
        ),
        (
            {
                "type": "choice",
                "instructions": "Which revision?",
                "options": {"rewrite": "Rewrite it", "leave": "Leave it"},
            },
            {
                "type": "noul",
                "choice": "rewrite",
                "probabilities": {"rewrite": 0.8, "leave": 0.2},
                "confidence": 0.6,
            },
        ),
    ],
)
async def test_an_answer_that_mislabels_its_type_is_rejected(question, answer):
    decision_service = service(responder({"answers": {"only": answer}}))

    result = await evaluate(decision_service, {"only": question})

    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.INVALID_RESPONSE


async def test_an_answer_without_a_type_is_still_normalized():
    decision_service = service(responder({"answers": {"only": {"noul": 0.93}}}))

    result = await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    assert isinstance(result, DecisionHandle)
    assert result.answers["only"].p_true == 0.93


@pytest.mark.parametrize(
    "answers",
    [
        {"only": {"type": "noul", "noul": "0.93"}},
        {"only": {"type": "noul", "noul": 1.4}},
        {"only": {"type": "noul"}},
        {"only": "not an answer object"},
        {"different": {"type": "noul", "noul": 0.93}},
        {
            "only": {"type": "noul", "noul": 0.93},
            "extra": {"type": "noul", "noul": 0.1},
        },
        {},
    ],
)
async def test_a_batch_the_contract_rejects_never_becomes_an_answer(answers):
    body = {"model": "jev-1.13.0", "answers": answers}
    decision_service = service(responder(body))

    result = await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    # the original body stays inspectable even though nothing validated
    assert decision_service.log.records[result.request_id].raw == body


@pytest.mark.parametrize(
    "legend,probabilities",
    [
        ({"1": "Plain", "2": "Lean"}, {"1": 0.5, "2": 0.5}),
        ({"a": "Plain", "b": "Lean"}, {"a": 0.5, "b": 0.5}),
        ({"0": "Plain", "1": "Ornate"}, {"0": 0.5, "1": 0.5}),
    ],
)
async def test_score_levels_must_be_an_index_map_of_the_requested_rubric(
    legend, probabilities
):
    body = {
        "answers": {
            "only": {
                "type": "score",
                "score": 0.5,
                "confidence": 0.4,
                "legend": legend,
                "probabilities": probabilities,
            }
        }
    }

    result = await evaluate(
        service(responder(body)),
        {
            "only": {
                "type": "score",
                "instructions": "How ornate is the prose?",
                "rubric": ["Plain", "Lean"],
            }
        },
    )

    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.INVALID_RESPONSE


async def test_only_the_application_body_is_kept_for_inspection():
    body = {
        "model": "jev-1.13.0",
        "answers": {"only": {"type": "noul", "noul": 0.93}},
        "usage": {"input_tokens": 120, "output_tokens": 8},
        "authorization": f"Bearer {API_KEY}",
        "provider_transport": {"upstream_key": API_KEY},
    }
    decision_service = service(responder(body))

    result = await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    raw = decision_service.log.records[result.request_id].raw
    assert set(raw) == {"model", "answers", "usage"}
    assert API_KEY not in json.dumps(raw)


async def test_a_provider_never_reports_a_refusal_it_cannot_read():
    body = {"answers": {"only": {"type": "noul", "noul": 0.93}}, "refused": True}
    decision_service = service(responder(body))

    result = await evaluate(
        decision_service,
        {"only": {"type": "noul", "instructions": "Does it repeat?"}},
    )

    assert isinstance(result, DecisionHandle)
    assert result.answers["only"].p_true == 0.93


@pytest.mark.parametrize("model", ["", "   "])
async def test_a_blank_model_is_not_ready(model):
    provider = OpenRouterDecisionProvider(model, lambda: API_KEY)
    assert provider.ready is False


@pytest.mark.parametrize("model", ["typesafe/jev-1.13", "some/other-decision-model"])
def test_capabilities_never_depend_on_the_model_name(model):
    capabilities = OpenRouterDecisionProvider(model, lambda: API_KEY).capabilities
    assert capabilities.question_types == frozenset({"noul", "choice", "score"})
    assert capabilities.max_input_tokens is None
    assert capabilities.max_questions is None
