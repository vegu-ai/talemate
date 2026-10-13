import asyncio
from unittest.mock import AsyncMock

import pytest

from talemate.decisions import (
    DecisionError,
    DecisionHandle,
    DecisionService,
    FailureCode,
    ProviderCapabilities,
    ProviderResponse,
    Unavailable,
)
from talemate.util.encryption import REDACTED


QUESTIONS = {
    "repeats": {"type": "noul", "instructions": "Does the supplied passage repeat?"}
}


async def evaluate(service, **kwargs):
    return await service.evaluate(
        **{
            "label": "repetition",
            "state": {"passage": "complete text"},
            "questions": QUESTIONS,
            "invocation_id": "invocation",
            "template_uid": "editor.policy",
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "mode,code",
    [
        ("default", FailureCode.DISABLED),
        ("absent", FailureCode.UNAVAILABLE),
        ("not_ready", FailureCode.UNAVAILABLE),
    ],
)
async def test_unconfigured_service_never_calls_provider(provider, mode, code):
    provider.ready = mode != "not_ready"
    service = DecisionService(
        None if mode == "absent" else provider, enabled=mode != "default"
    )
    result = await evaluate(service)
    assert isinstance(result, Unavailable)
    assert result.failure.code == code
    assert not provider.calls
    entry = service.log.records[result.request_id]
    assert not entry.dispatched
    assert entry.status == "failed"
    assert entry.answers is None
    assert service.enabled == (mode != "default")


@pytest.mark.parametrize("model", ["unknown", "tiny-chat-model", "typesafe/jev-1.13"])
async def test_readiness_and_capabilities_never_depend_on_model_name(provider, model):
    provider.model = model
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service)
    assert isinstance(result, DecisionHandle)
    assert result.answers["repeats"].p_true == 0.93
    entry = service.log.records[result.request_id]
    assert entry.raw == provider.raw
    assert entry.model == model
    assert entry.dispatched
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "caps,code",
    [
        (ProviderCapabilities(max_input_tokens=1), FailureCode.OVERSIZE),
        (ProviderCapabilities(max_question_input_tokens=1), FailureCode.OVERSIZE),
    ],
)
async def test_oversize_request_is_logged_whole_and_not_sent(provider, caps, code):
    provider.capabilities = caps
    service = DecisionService(provider, enabled=True)
    state = {"passage": "full sentence " * 100}
    questions = {**QUESTIONS, "another": QUESTIONS["repeats"]}
    result = await evaluate(service, state=state, questions=questions)
    assert result.failure.code == code
    assert not provider.calls
    entry = service.log.records[result.request_id]
    assert entry.state == state
    assert entry.questions == questions


@pytest.mark.parametrize(
    "total_limit,question_limit,multiplier,parts",
    [
        (300, 200, 1.0, 1),
        (299, 200, 1.0, 2),
        (200, 200, 1.0, 2),
        (199, 200, 1.0, 0),
        (300, 199, 1.0, 0),
        (None, 200, 1.0, 1),
        (300, None, 1.0, 1),
        (450, 300, 1.5, 1),
        (449, 300, 1.5, 2),
        (450, 299, 1.5, 0),
        (450, None, 1.501, 2),
        (451, None, 1.501, 1),
        (None, 300, 1.501, 0),
        (None, 301, 1.501, 1),
        (64000, 32000, 1e308, 0),
    ],
)
async def test_questions_that_do_not_fit_together_are_sent_in_parts(
    provider, monkeypatch, total_limit, question_limit, multiplier, parts
):
    import importlib

    module = importlib.import_module("talemate.decisions.budget")
    monkeypatch.setattr(module, "count_tokens", lambda text: 100)
    provider.capabilities = ProviderCapabilities(
        max_input_tokens=total_limit,
        max_question_input_tokens=question_limit,
        input_token_multiplier=multiplier,
    )

    async def answer(request):
        return ProviderResponse(
            answers={
                key: {"type": "noul", "p_true": 0.93} for key in request.questions
            },
            response_body=provider.raw,
        )

    provider.handler = answer
    service = DecisionService(provider, enabled=True)
    state = {"passage": "complete unchanged text"}
    questions = {**QUESTIONS, "another": QUESTIONS["repeats"]}

    result = await evaluate(service, state=state, questions=questions)

    record = service.log.records[result.request_id]
    assert record.state == state
    assert record.questions == questions
    assert record.dispatched is bool(parts)
    assert len(provider.calls) == parts
    assert all(call.state == state for call in provider.calls)
    if parts == 1:
        assert list(provider.calls[0].questions) == ["repeats", "another"]
        assert record.raw == provider.raw
    elif parts == 2:
        assert [list(call.questions) for call in provider.calls] == [
            ["repeats"],
            ["another"],
        ]
        assert record.raw == [provider.raw, provider.raw]
    assert (record.tokens.state, record.tokens.questions) == (100, 200)
    assert not record.tokens.sized and record.tokens.budget is None
    if parts:
        assert isinstance(result, DecisionHandle)
        assert set(result.answers) == {"repeats", "another"}
        assert record.tokens.parts == parts
        assert record.tokens.sent == 100 * parts + 200
    else:
        assert result.failure.code == FailureCode.OVERSIZE
        assert record.answers is None


@pytest.mark.parametrize(
    "usages,reported",
    [
        ([{"input_tokens": 120}, {"input_tokens": 80}], 200),
        ([{"input_tokens": 120}, {}], None),
        ([{"input_tokens": True}, {"input_tokens": 80}], None),
    ],
)
async def test_provider_input_tokens_are_summed_over_parts(
    provider, monkeypatch, usages, reported
):
    import importlib

    module = importlib.import_module("talemate.decisions.budget")
    monkeypatch.setattr(module, "count_tokens", lambda text: 100)
    provider.capabilities = ProviderCapabilities(
        max_input_tokens=299, max_question_input_tokens=200
    )
    bodies = iter(usages)

    async def answer(request):
        return ProviderResponse(
            answers={
                key: {"type": "noul", "p_true": 0.93} for key in request.questions
            },
            response_body={"usage": next(bodies)},
        )

    provider.handler = answer
    service = DecisionService(provider, enabled=True)
    questions = {**QUESTIONS, "another": QUESTIONS["repeats"]}

    result = await evaluate(service, questions=questions, state_budget=150, sized=True)

    tokens = service.log.records[result.request_id].tokens
    assert tokens.parts == 2
    assert tokens.reported == reported
    assert tokens.sized and tokens.budget == 150


@pytest.mark.parametrize("question_counts", [[60, 140], [140, 60]])
@pytest.mark.parametrize("limit,allowed", [(240, True), (239, False)])
async def test_largest_question_is_selected_independently_of_order(
    provider, monkeypatch, question_counts, limit, allowed
):
    import importlib

    module = importlib.import_module("talemate.decisions.budget")
    counts = iter([100, *question_counts])
    monkeypatch.setattr(module, "count_tokens", lambda text: next(counts))
    provider.capabilities = ProviderCapabilities(
        max_input_tokens=300, max_question_input_tokens=limit
    )
    provider.answers["another"] = provider.answers["repeats"]
    result = await evaluate(
        DecisionService(provider, enabled=True),
        questions={**QUESTIONS, "another": QUESTIONS["repeats"]},
    )
    assert len(provider.calls) == int(allowed)
    if allowed:
        assert isinstance(result, DecisionHandle)
    else:
        assert result.failure.code == FailureCode.OVERSIZE


@pytest.mark.parametrize(
    "question",
    [
        {"type": "noul", "instructions": "Long instruction " * 500},
        {
            "type": "noul",
            "instructions": "Decide",
            "true_criteria": "Long true criterion " * 500,
            "false_criteria": "False",
        },
        {
            "type": "choice",
            "instructions": "Choose",
            "options": {"a": "Long option " * 500, "b": "Other"},
        },
        {
            "type": "score",
            "instructions": "Score",
            "rubric": ["Low", "Long rubric entry " * 500],
        },
    ],
)
async def test_largest_question_limit_counts_instructions_and_criteria(
    provider, question
):
    provider.capabilities = ProviderCapabilities(max_question_input_tokens=100)
    service = DecisionService(provider, enabled=True)

    result = await evaluate(service, state="short", questions={"only": question})

    assert result.failure.code == FailureCode.OVERSIZE
    assert not provider.calls


@pytest.mark.parametrize(
    "state", ["long state " * 500, {"a": "long state " * 500}, ["long state " * 500]]
)
async def test_each_state_shape_counts_toward_the_largest_question_limit(
    provider, state
):
    provider.capabilities = ProviderCapabilities(max_question_input_tokens=100)
    service = DecisionService(provider, enabled=True)

    result = await evaluate(service, state=state)

    assert result.failure.code == FailureCode.OVERSIZE
    assert not provider.calls


async def test_undeclared_token_limits_do_not_refuse(provider, monkeypatch):
    import importlib

    module = importlib.import_module("talemate.decisions.budget")
    # the count only describes the request in the log; without limits no
    # size can refuse it
    monkeypatch.setattr(module, "count_tokens", lambda text: 10**9)
    service = DecisionService(provider, enabled=True)

    result = await evaluate(service)

    assert isinstance(result, DecisionHandle)
    assert len(provider.calls) == 1
    (record,) = service.log.records.values()
    assert record.tokens.parts == 1 and record.tokens.state == 10**9


@pytest.mark.parametrize(
    "patch", [{"questions": {}}, {"state": object()}, {"label": 1}]
)
async def test_invalid_request_logged_before_transport(provider, patch):
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service, **patch)
    assert result.failure.code == FailureCode.INVALID_REQUEST
    assert not provider.calls


@pytest.mark.parametrize(
    "failure,code",
    [
        (
            RuntimeError("authorization credential must not appear"),
            FailureCode.TRANSPORT,
        ),
        (DecisionError(FailureCode.AUTHENTICATION), FailureCode.AUTHENTICATION),
        (DecisionError(FailureCode.OVERSIZE), FailureCode.OVERSIZE),
        (DecisionError(FailureCode.REFUSED), FailureCode.REFUSED),
    ],
)
async def test_sanitized_failures_and_no_retry(provider, failure, code):
    provider.handler = AsyncMock(side_effect=failure)
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service)
    assert result.failure.code == code
    assert "credential" not in str(service.log.snapshot())
    assert len(provider.calls) == 1
    assert service.log.records[result.request_id].dispatched
    assert service.enabled


async def test_refusal_is_not_a_negative_answer(provider):
    provider.handler = AsyncMock(
        return_value=ProviderResponse(
            answers={}, response_body={"refused": True}, refused=True
        )
    )
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service)
    assert result.failure.code == FailureCode.REFUSED
    assert service.log.records[result.request_id].answers is None


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {"repeats": {"type": "noul", "p_true": 4}},
        {
            "repeats": {
                "type": "score",
                "value": 1,
                "probabilities": [0.0, 1.0],
                "legend": ["low", "high"],
                "confidence": 1.0,
            }
        },
    ],
)
async def test_invalid_answers_retain_selected_response_body(provider, answers):
    body = {"data": answers, "api_key": "private fixture value"}
    provider.handler = AsyncMock(
        return_value=ProviderResponse(answers=answers, response_body=body)
    )
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service)
    entry = service.log.records[result.request_id]
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    assert entry.raw == {"data": answers, "api_key": REDACTED}
    assert entry.answers is None
    assert not entry.actions


@pytest.mark.parametrize("mode", ["success", "refusal", "error", "malformed"])
async def test_adapter_selects_inspection_body_from_private_wire_payload(
    provider, mode
):
    wire = {
        "headers": {"authorization": "private header fixture"},
        "arbitrary_auth_name": "private credential fixture",
        "body": {"noul": 0.93, "original_value": "preserved"},
    }

    async def adapter(request):
        # The adapter owns this schema and exposes only its application body.
        body = wire["body"]
        if mode == "error":
            raise DecisionError(FailureCode.REFUSED, response_body=body)
        return ProviderResponse(
            answers={} if mode in {"refusal", "malformed"} else provider.answers,
            response_body=body,
            refused=mode == "refusal",
        )

    provider.handler = adapter
    service = DecisionService(provider, enabled=True)
    events = []
    service.log.subscribe(events.append)
    result = await evaluate(service)
    assert service.log.records[result.request_id].raw == wire["body"]
    assert "private" not in str(events)
    assert "arbitrary_auth_name" not in str(service.log.snapshot())


async def test_invalid_provider_envelope_does_not_expose_unknown_payload(provider):
    provider.handler = AsyncMock(return_value={"answers": {}, "credentials": "private"})
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service)
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    assert service.log.records[result.request_id].raw is None


async def test_timeout_cancels_provider_and_ignores_late_completion(provider):
    cancelled, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def late(request):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return ProviderResponse(answers=provider.answers, response_body={})
        finally:
            finished.set()

    provider.handler = late
    service = DecisionService(provider, enabled=True, timeout_seconds=0.01)
    try:
        result = await asyncio.wait_for(evaluate(service), 1)
        assert result.failure.code == FailureCode.TIMEOUT
        await asyncio.wait_for(cancelled.wait(), 1)
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
    assert service.log.records[result.request_id].answers is None
    assert service.log.records[result.request_id].status == "failed"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_deadlines(timeout):
    with pytest.raises(ValueError):
        DecisionService(timeout_seconds=timeout)


def test_default_deadline():
    assert DecisionService().timeout_seconds == 1.5


async def test_deadline_includes_answer_validation(provider, monkeypatch):
    import importlib

    ownership = importlib.import_module("talemate.decisions.ownership")
    module = importlib.import_module("talemate.decisions.service")
    now = {"value": 0.0}
    monkeypatch.setattr(ownership, "monotonic", lambda: now["value"])
    original = module.validate_answers

    def validate(request, response):
        answers = original(request, response)
        now["value"] = 2.0
        return answers

    monkeypatch.setattr(module, "validate_answers", validate)
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service)
    assert result.failure.code == FailureCode.TIMEOUT
    assert service.log.records[result.request_id].answers is None
    assert service.log.records[result.request_id].raw is None


def test_updated_deadline_is_validated():
    service = DecisionService()
    with pytest.raises(ValueError):
        service.timeout_seconds = "1.5"
    assert service.timeout_seconds == 1.5


@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled"])
async def test_presentation_survives_request_lifecycle_without_reaching_provider(
    provider, ending
):
    presentation = {
        "repeats": {
            "group_id": "authored_check",
            "label": "Repeated beats",
            "instructions": "Does this passage repeat?",
            "passage_id": "p_7",
            "passage_text": "complete text",
            "scope": "dialogue",
            "threshold": 0.8,
        }
    }
    started, release = asyncio.Event(), asyncio.Event()

    async def respond(request):
        started.set()
        await release.wait()
        if ending == "failed":
            raise DecisionError(FailureCode.TRANSPORT)
        return ProviderResponse(answers=provider.answers, response_body=provider.raw)

    provider.handler = respond
    service = DecisionService(provider, enabled=True)
    frames = []
    service.log.subscribe(frames.append)
    task = asyncio.create_task(evaluate(service, presentation=presentation))
    try:
        await asyncio.wait_for(started.wait(), 1)
        pending = next(
            frame["entry"]
            for frame in frames
            if frame.get("entry", {}).get("dispatched")
        )
        assert pending["status"] == "pending"
        assert pending["presentation"] == presentation
        payload = provider.calls[0].model_dump()
        assert "presentation" not in payload
        assert payload["state"] == {"passage": "complete text"}
        assert (
            payload["questions"]["repeats"]["instructions"]
            == QUESTIONS["repeats"]["instructions"]
        )
        if ending == "cancelled":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            await asyncio.wait_for(task, 1)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    snapshot = service.log.snapshot()["requests"][0]
    assert snapshot["status"] == ending
    assert snapshot["presentation"] == presentation
    presentation["repeats"]["passage_text"] = "changed after dispatch"
    assert (
        service.log.snapshot()["requests"][0]["presentation"]["repeats"]["passage_text"]
        == "complete text"
    )


@pytest.mark.parametrize(
    "presentation",
    [
        {
            "repeats": {
                "group_id": "check",
                "label": "Repeated beats",
                "instructions": "Repeat?",
                "passage_id": "s1",
                "passage_text": "The door opened.",
                "threshold": 1.5,
            }
        },
        {"repeats": {"passage_text": "missing fields"}},
        [],
        False,
        "",
    ],
)
async def test_invalid_presentation_is_a_logged_invalid_request(provider, presentation):
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service, presentation=presentation)
    assert isinstance(result, Unavailable)
    assert result.failure.code == FailureCode.INVALID_REQUEST
    assert not provider.calls
    entry = service.log.snapshot()["requests"][0]
    assert entry["id"] == result.request_id
    assert entry["status"] == "failed"
    assert entry["failure"]["code"] == FailureCode.INVALID_REQUEST
    assert not entry["dispatched"]


@pytest.mark.parametrize(
    "enabled,caps,code",
    [
        (False, ProviderCapabilities(), FailureCode.DISABLED),
        (True, ProviderCapabilities(max_input_tokens=1), FailureCode.OVERSIZE),
        (True, ProviderCapabilities(max_question_input_tokens=1), FailureCode.OVERSIZE),
    ],
)
async def test_valid_presentation_is_retained_on_preflight_failure(
    provider, enabled, caps, code
):
    from talemate.decisions.events import QuestionPresentation

    item = QuestionPresentation(
        group_id="check",
        label="Repeated beats",
        instructions="Does this repeat?",
        passage_id="s1",
        passage_text="The door opened.",
        threshold=0.8,
    )
    provider.capabilities = caps
    service = DecisionService(provider, enabled=enabled)
    result = await evaluate(service, presentation={"repeats": item})
    assert result.failure.code == code
    assert not provider.calls
    entry = service.log.snapshot()["requests"][0]
    assert not entry["dispatched"]
    assert entry["presentation"]["repeats"] == item.model_dump()
