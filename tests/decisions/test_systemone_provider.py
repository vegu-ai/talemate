import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from talemate.decisions import DecisionHandle, DecisionService, FailureCode, Unavailable
from talemate.decisions.providers.systemone import SystemOneDecisionProvider


@pytest.fixture
def recorded():
    return json.loads(
        (
            Path(__file__).parents[1] / "data/decisions/recorded-systemone.json"
        ).read_text()
    )


def service(handler, base_url="http://localhost:8009", credential=lambda: None):
    return DecisionService(
        SystemOneDecisionProvider(
            "any/server-model",
            base_url,
            credential,
            transport=httpx.MockTransport(handler),
        ),
        enabled=True,
    )


async def evaluate(decision_service, recorded):
    questions = copy.deepcopy(recorded["request"]["questions"])
    questions["department"]["options"] = questions["department"].pop("criteria")
    questions["frustration"]["rubric"] = questions["frustration"].pop("criteria")
    return await decision_service.evaluate(
        "recorded",
        state=recorded["request"]["state"],
        questions=questions,
        invocation_id="systemone-test",
        template_uid="test.systemone",
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8009",
        "http://localhost:8009/",
        "https://example.test/decisions/",
    ],
)
@pytest.mark.parametrize("key", [None, "systemone-test-credential"])
async def test_recorded_systemone_batch_normalizes_all_three_types(
    recorded, base_url, key
):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=recorded["response"])

    decision_service = service(handler, base_url, lambda: key)
    result = await evaluate(decision_service, recorded)

    assert isinstance(result, DecisionHandle)
    (request,) = sent
    assert str(request.url) == f"{base_url.rstrip('/')}/v1/systemone"
    assert request.headers.get("authorization") == (f"Bearer {key}" if key else None)
    assert json.loads(request.content) == {
        **recorded["request"],
        "model": "any/server-model",
    }
    assert result.answers["escalate"].p_true == 0.93
    choice = result.answers["department"]
    assert choice.selected == "returns"
    assert choice.probabilities == {"returns": 0.47, "shipping": 0.28, "billing": 0.25}
    assert choice.confidence == 0.21
    score = result.answers["frustration"]
    assert score.value == 1.44
    assert score.legend == ["Calm", "Frustrated", "Very angry"]
    assert score.probabilities == [0.0, 0.56, 0.44]
    assert score.confidence == 0.34
    record = decision_service.log.records[result.request_id]
    assert record.provider == "systemone"
    assert record.raw == {
        k: recorded["response"][k] for k in ("model", "answers", "usage")
    }


@pytest.mark.parametrize(
    "defect",
    ["missing", "extra", "wrong_type", "bad_probability", "bad_options", "bad_legend"],
)
async def test_invalid_systemone_batch_never_becomes_a_decision(recorded, defect):
    body = recorded["response"]
    answers = body["answers"]
    if defect == "missing":
        del answers["escalate"]
    elif defect == "extra":
        answers["unasked"] = {"type": "noul", "noul": 0.5}
    elif defect == "wrong_type":
        answers["escalate"]["type"] = "choice"
    elif defect == "bad_probability":
        answers["escalate"]["noul"] = "0.93"
    elif defect == "bad_options":
        answers["department"]["probabilities"]["unasked"] = 0.0
    else:
        answers["frustration"]["legend"]["2"] = "Different rubric"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    result = await evaluate(service(handler), recorded)

    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,code",
    [
        (401, FailureCode.AUTHENTICATION),
        (403, FailureCode.AUTHENTICATION),
        (413, FailureCode.OVERSIZE),
        (429, FailureCode.TRANSPORT),
        (500, FailureCode.TRANSPORT),
        (302, FailureCode.TRANSPORT),
    ],
)
async def test_systemone_http_failures_do_not_retry_or_expose_the_body(
    recorded, status, code
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": "systemone-test-credential"})

    decision_service = service(handler)
    result = await evaluate(decision_service, recorded)

    assert result.failure.code == code
    assert len(calls) == 1
    assert decision_service.log.records[result.request_id].raw is None


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        '{"answers":{"escalate":{"noul":NaN}}}',
        '{"answers":[]}',
        '{"answers":{"escalate":{"noul":1e400}}}',
    ],
)
async def test_systemone_unreadable_response_is_a_typed_failure(recorded, text):
    result = await evaluate(
        service(lambda request: httpx.Response(200, text=text)), recorded
    )
    assert result.failure.code == FailureCode.INVALID_RESPONSE


async def test_systemone_deadline_cancels_the_only_request(recorded):
    calls = []
    cancelled = asyncio.Event()

    async def handler(request):
        calls.append(request)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    decision_service = service(handler)
    decision_service.timeout_seconds = 0.03
    result = await asyncio.wait_for(evaluate(decision_service, recorded), timeout=2)
    await asyncio.wait_for(cancelled.wait(), timeout=2)

    assert result.failure.code == FailureCode.TIMEOUT
    assert len(calls) == 1


async def test_connection_failure_does_not_retry(recorded):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("unreachable", request=request)

    result = await evaluate(service(handler), recorded)
    assert result.failure.code == FailureCode.TRANSPORT
    assert len(calls) == 1
