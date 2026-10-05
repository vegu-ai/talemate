import asyncio

import pytest

from talemate.decisions import (
    DecisionError,
    DecisionHandle,
    DecisionService,
    FailureCode,
    ProviderCapabilities,
    ProviderResponse,
)
from talemate.decisions.budget import fit_list, fit_text, state_tokens
from talemate.decisions.service import QUESTIONS, _largest_state, _within_limits


QUESTION = {"type": "noul", "instructions": "Does the passage repeat?"}
LONG_TEXT = " ".join(f"Line {number}: the tide turned." for number in range(400))


def answer_every_question(provider):
    async def answer(request):
        return ProviderResponse(
            answers={key: {"type": "noul", "p_true": 0.9} for key in request.questions},
            response_body={"parts": list(request.questions)},
        )

    provider.handler = answer


def test_fit_list_keeps_the_newest_items_within_budget():
    items = [f"Message {number}: the lamp flickers." for number in range(50)]
    fitted = fit_list({"history": [], "speaker": "Mara"}, "history", items, 120)
    history = fitted["history"]
    assert state_tokens(fitted) <= 120
    assert 0 < len(history) < len(items)
    assert history[1:] == items[-len(history) + 1 :]
    assert items[-len(history)].endswith(history[0])
    assert list(fitted) == ["history", "speaker"]


def test_fit_list_shortens_a_single_text_item_from_its_start():
    summary = " ".join(f"Chunk {number}: the keepers argued." for number in range(80))
    fitted = fit_list({"summaries": []}, "summaries", [summary], 100)
    (kept,) = fitted["summaries"]
    assert state_tokens(fitted) <= 100
    assert summary.endswith(kept) and len(kept) < len(summary)


def test_fit_list_without_budget_or_room():
    items = ["one", "two"]
    assert fit_list({"history": []}, "history", items, None) == {"history": items}
    assert fit_list({"history": [], "big": "x " * 200}, "history", items, 50) == {
        "history": [],
        "big": "x " * 200,
    }


def test_fit_text_keeps_the_end():
    fitted = fit_text(LONG_TEXT, 200)
    assert state_tokens(fitted) <= 200
    assert LONG_TEXT.endswith(fitted)
    assert fit_text(LONG_TEXT, None) == LONG_TEXT
    assert fit_text("short", 200) == "short"
    assert fit_text(LONG_TEXT, 0) == ""


@pytest.mark.parametrize(
    "text",
    ["猫" * 100, "😀a" * 80, "灯台の守り人は霧の夜に鐘を鳴らした。" * 20],
)
def test_fit_text_never_splits_a_character(text):
    for budget in range(200):
        fitted = fit_text(text, budget)
        assert "\ufffd" not in fitted
        assert text.endswith(fitted)
        assert state_tokens(fitted) <= max(budget, state_tokens(""))


def question_tokens(provider, questions):
    return [
        state_tokens({key: provider.serialize_question(question)})
        for key, question in QUESTIONS.validate_python(questions).items()
    ]


async def evaluate(service, state, questions):
    return await service.evaluate(
        "budget",
        state=state,
        questions=questions,
        invocation_id="invocation",
        template_uid="test",
    )


def test_state_budget_leaves_room_for_every_question(provider):
    service = DecisionService(provider, enabled=True)
    questions = {"short": QUESTION, "long": {**QUESTION, "instructions": "Why? " * 50}}
    assert service.state_budget(questions) is None

    provider.capabilities = ProviderCapabilities(
        max_input_tokens=3000,
        max_question_input_tokens=2000,
        input_token_multiplier=1.5,
    )
    tokens = question_tokens(provider, questions)
    budget = service.state_budget(questions)
    assert _within_limits(provider.capabilities, budget, tokens)
    assert not _within_limits(provider.capabilities, budget + 1, tokens)

    service.enabled = False
    assert service.state_budget(questions) is None
    service.enabled = True
    provider.ready = False
    assert service.state_budget(questions) is None
    provider.ready = True
    assert service.state_budget({"bad": {"type": "noul"}}) is None


@pytest.mark.parametrize(
    "limit,multiplier", [(8100, 1.35), (12100, 1.1), (187, 1.1), (8000, 1.5)]
)
def test_budget_is_what_the_check_accepts(limit, multiplier):
    caps = ProviderCapabilities(
        max_input_tokens=limit,
        max_question_input_tokens=limit,
        input_token_multiplier=multiplier,
    )
    tokens = _largest_state(caps, [20, 30])
    assert _within_limits(caps, tokens, [20, 30])
    assert not _within_limits(caps, tokens + 1, [20, 30])


@pytest.mark.parametrize("multiplier", [1.0, 1.1, 1.5])
async def test_a_fitted_state_goes_out_with_all_its_questions(provider, multiplier):
    provider.capabilities = ProviderCapabilities(
        max_input_tokens=800,
        max_question_input_tokens=800,
        input_token_multiplier=multiplier,
    )
    answer_every_question(provider)
    service = DecisionService(provider, enabled=True)
    questions = {f"q{number}": QUESTION for number in range(12)}
    state = fit_text(LONG_TEXT, service.state_budget(questions))
    assert state

    result = await evaluate(service, state, questions)

    assert isinstance(result, DecisionHandle)
    assert set(result.answers) == set(questions)
    (call,) = provider.calls
    assert call.state == state
    assert service.log.records[result.request_id].raw == {"parts": list(questions)}

    overfull = fit_text(LONG_TEXT, service.state_budget(questions) + 20)
    provider.calls.clear()
    result = await evaluate(service, overfull, questions)
    assert len(provider.calls) == 2


async def test_questions_that_fill_the_limit_alone_are_split(provider):
    provider.capabilities = ProviderCapabilities(
        max_input_tokens=400, max_question_input_tokens=400
    )
    answer_every_question(provider)
    service = DecisionService(provider, enabled=True)
    questions = {f"q{number}": QUESTION for number in range(30)}
    assert sum(question_tokens(provider, questions)) > 400
    state = fit_text(LONG_TEXT, service.state_budget(questions))
    assert state

    result = await evaluate(service, state, questions)

    assert isinstance(result, DecisionHandle)
    assert len(provider.calls) > 1
    assert [key for call in provider.calls for key in call.questions] == list(questions)
    record = service.log.records[result.request_id]
    assert record.raw == [{"parts": list(call.questions)} for call in provider.calls]


def two_part_limit(provider):
    provider.capabilities = ProviderCapabilities(
        max_input_tokens=state_tokens("short")
        + max(question_tokens(provider, {"a": QUESTION}))
        + 1
    )


def second_part(provider, failure):
    calls = []

    async def answer(request):
        calls.append(list(request.questions))
        if len(calls) == 2:
            return await failure()
        return ProviderResponse(
            answers={key: {"type": "noul", "p_true": 0.9} for key in request.questions},
            response_body={"part": 1},
        )

    provider.handler = answer
    return calls


async def test_invalid_answers_in_a_later_part_keep_every_body(provider):
    two_part_limit(provider)

    async def failure():
        return ProviderResponse(answers={}, response_body={"part": 2})

    calls = second_part(provider, failure)
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service, "short", {"a": QUESTION, "b": QUESTION})
    assert calls == [["a"], ["b"]]
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    assert service.log.records[result.request_id].raw == [{"part": 1}, {"part": 2}]


async def test_an_unreadable_later_part_keeps_the_split_shape(provider):
    two_part_limit(provider)

    async def failure():
        return {"not": "a provider response"}

    second_part(provider, failure)
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service, "short", {"a": QUESTION, "b": QUESTION})
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    assert service.log.records[result.request_id].raw == [{"part": 1}]


async def test_a_later_part_that_raises_keeps_the_earlier_bodies(provider):
    two_part_limit(provider)

    async def failure():
        raise DecisionError(FailureCode.TRANSPORT)

    second_part(provider, failure)
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service, "short", {"a": QUESTION, "b": QUESTION})
    assert result.failure.code == FailureCode.TRANSPORT
    assert service.log.records[result.request_id].raw == [{"part": 1}]


async def test_a_later_part_that_times_out_keeps_the_earlier_bodies(provider):
    two_part_limit(provider)

    async def failure():
        await asyncio.Event().wait()

    second_part(provider, failure)
    service = DecisionService(provider, enabled=True, timeout_seconds=0.2)
    result = await evaluate(service, "short", {"a": QUESTION, "b": QUESTION})
    assert result.failure.code == FailureCode.TIMEOUT
    assert service.log.records[result.request_id].raw == [{"part": 1}]


async def test_a_later_part_that_raises_with_a_body_keeps_every_body(provider):
    two_part_limit(provider)

    async def failure():
        raise DecisionError(
            FailureCode.INVALID_RESPONSE, response_body="malformed response: part 2"
        )

    second_part(provider, failure)
    service = DecisionService(provider, enabled=True)
    result = await evaluate(service, "short", {"a": QUESTION, "b": QUESTION})
    assert result.failure.code == FailureCode.INVALID_RESPONSE
    assert service.log.records[result.request_id].raw == [
        {"part": 1},
        "malformed response: part 2",
    ]
