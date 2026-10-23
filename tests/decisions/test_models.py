import copy

import pytest
from pydantic import ValidationError

from talemate.decisions import ProviderCapabilities
from talemate.decisions.models import (
    ChoiceAnswer,
    DecisionRequest,
    ProviderResponse,
    ScoreAnswer,
    validate_answers,
)


QUESTIONS = {
    "bool": {"type": "noul", "instructions": "Does the supplied passage repeat?"},
    "choice": {
        "type": "choice",
        "instructions": "Select a supplied candidate",
        "options": {"a": "Wait", "b": "Leave"},
    },
    "score": {
        "type": "score",
        "instructions": "Grade surprise",
        "rubric": ["ordinary", "unusual", "surprising"],
    },
}
ANSWERS = {
    "bool": {"type": "noul", "p_true": 0.74},
    "choice": {
        "type": "choice",
        "selected": "a",
        "probabilities": {"a": 0.7, "b": 0.3},
        "confidence": 0.8,
    },
    "score": {
        "type": "score",
        "value": 1.5,
        "probabilities": [0.1, 0.3, 0.6],
        "legend": ["ordinary", "unusual", "surprising"],
        "confidence": 0.85,
    },
}


def request(**kwargs):
    return DecisionRequest(
        **{
            "invocation_id": "invocation",
            "request_id": "request",
            "label": "label",
            "state": {"passage": "whole text"},
            "questions": copy.deepcopy(QUESTIONS),
            **kwargs,
        }
    )


def test_all_answer_types_keep_probability_and_raw_meanings():
    response = ProviderResponse(answers=ANSWERS, response_body={"original": ANSWERS})
    answers = validate_answers(request(), response)
    assert answers["bool"].p_true == 0.74
    assert not hasattr(answers["bool"], "confidence")
    assert not hasattr(answers["bool"], "passages")
    assert answers["choice"].selected == "a"
    assert answers["choice"].probabilities == {"a": 0.7, "b": 0.3}
    assert answers["score"].value == 1.5
    assert answers["score"].legend == QUESTIONS["score"]["rubric"]
    assert response.response_body == {"original": ANSWERS}


@pytest.mark.parametrize(
    "state", ["full text", ["text", {"x": 1}], {"a": None, "b": True}]
)
def test_serializable_state_shapes(state):
    assert request(state=state).state == state


@pytest.mark.parametrize(
    "patch",
    [
        {"questions": {}},
        {"label": " "},
        {"label": 5},
        {"request_id": ""},
        {"state": 1},
        {"state": {"x": float("nan")}},
        {"state": object()},
        {"questions": {"": QUESTIONS["bool"]}},
        {"questions": {"q": {"type": "boolean", "instructions": "x"}}},
        {"questions": {"q": {"type": "noul", "instructions": ""}}},
        {
            "questions": {
                "q": {"type": "choice", "instructions": "x", "options": {"a": "only"}}
            }
        },
        {
            "questions": {
                "q": {
                    "type": "choice",
                    "instructions": "x",
                    "options": {"a": "", "b": "second"},
                }
            }
        },
        {
            "questions": {
                "q": {"type": "score", "instructions": "x", "rubric": ["same", "same"]}
            }
        },
        {
            "questions": {
                "q": {
                    "type": "score",
                    "instructions": "x",
                    "rubric": {"0": "low", "1": "high"},
                }
            }
        },
    ],
)
def test_invalid_request(patch):
    with pytest.raises((ValidationError, ValueError)):
        request(**patch)


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("bool", "p_true", -0.1),
        ("bool", "p_true", 1.1),
        ("bool", "p_true", float("nan")),
        ("bool", "p_true", float("inf")),
        ("bool", "p_true", "0.8"),
        ("bool", "p_true", True),
        ("bool", "confidence", 0.9),
        ("bool", "type", "score"),
        ("choice", "selected", "missing"),
        ("choice", "probabilities", {"a": 0.5, "b": 0.4}),
        ("choice", "probabilities", {"a": 1.1, "b": -0.1}),
        ("choice", "probabilities", {"a": 0.5, "other": 0.5}),
        ("choice", "confidence", 1.1),
        ("score", "value", 3.0),
        ("score", "value", -0.01),
        ("score", "value", float("inf")),
        ("score", "value", True),
        ("score", "legend", ["different", "levels", "here"]),
        ("score", "probabilities", [0.3, 0.7]),
        ("score", "probabilities", [0.3, 0.3, 0.3]),
        ("score", "confidence", "0.9"),
    ],
)
def test_invalid_answer_batch(kind, field, value):
    answers = copy.deepcopy(ANSWERS)
    answers[kind][field] = value
    with pytest.raises((ValidationError, ValueError)):
        validate_answers(request(), ProviderResponse(answers=answers, response_body={}))


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_ids_match_exactly(change):
    answers = copy.deepcopy(ANSWERS)
    if change == "missing":
        answers.pop("score")
    else:
        answers["unexpected"] = answers["bool"]
    with pytest.raises(ValueError):
        validate_answers(request(), ProviderResponse(answers=answers, response_body={}))


def test_small_probability_drift_is_normalized_without_mutating_response():
    answers = copy.deepcopy(ANSWERS)
    answers["choice"]["probabilities"]["a"] += 0.0000005
    original = copy.deepcopy(answers)
    response = ProviderResponse(answers=answers, response_body=answers)
    result = validate_answers(request(), response)
    probabilities = original["choice"]["probabilities"]
    assert result["choice"].probabilities == pytest.approx(
        {
            key: value / sum(probabilities.values())
            for key, value in probabilities.items()
        }
    )
    assert response.response_body == original
    assert response.answers == original
    assert answers == original


@pytest.mark.parametrize("kind", ["score", "choice"])
@pytest.mark.parametrize(
    "probabilities",
    [
        [0.68, 0.28, 0.03],
        [0.69, 0.29, 0.03],
        [0.5, 0.49],
        [0.5, 0.51],
        [0.5, 0.3, 0.185],
        [0.5, 0.3, 0.215],
        [0.095] * 10,
        [0.105] * 10,
        [0.0475] * 20,
        [0.0525] * 20,
        [0.0, 0.0, 1.0],
    ],
)
def test_rounding_normalizes_only_probabilities(probabilities, kind):
    original = list(probabilities)
    if kind == "score":
        answer = ScoreAnswer(
            type="score",
            value=0.35,
            probabilities=probabilities,
            legend=[str(index) for index in range(len(probabilities))],
            confidence=0.48,
        )
        normalized = answer.probabilities
        assert answer.value == 0.35
    else:
        answer = ChoiceAnswer(
            type="choice",
            selected="0",
            probabilities={
                str(index): value for index, value in enumerate(probabilities)
            },
            confidence=0.48,
        )
        normalized = list(answer.probabilities.values())
        assert answer.selected == "0"
        assert list(answer.probabilities) == [
            str(index) for index in range(len(probabilities))
        ]
    assert sum(normalized) == pytest.approx(1.0)
    assert normalized == pytest.approx([value / sum(original) for value in original])
    assert probabilities == original
    assert answer.confidence == 0.48


@pytest.mark.parametrize("kind", ["score", "choice"])
@pytest.mark.parametrize(
    "probabilities",
    [
        [0.5, 0.489999],
        [0.5, 0.510001],
        [0.5, 0.3, 0.184999],
        [0.5, 0.3, 0.215001],
        [0.094999] * 10,
        [0.105001] * 10,
        [0.045] * 20,
        [0.055] * 20,
        [0.3, 0.3, 0.3],
        [0.0, 0.0],
        [-0.01, 0.51, 0.5],
        [1.01, 0.0],
        [float("nan"), 0.5],
        [float("inf"), 0.5],
        [True, 0.0],
        ["0.5", 0.5],
    ],
)
def test_rejects_invalid_entries_and_sums_outside_rounding_tolerance(
    probabilities,
    kind,
):
    with pytest.raises(ValidationError):
        if kind == "score":
            ScoreAnswer(
                type="score",
                value=0.5,
                probabilities=probabilities,
                legend=[str(index) for index in range(len(probabilities))],
                confidence=0.5,
            )
        else:
            ChoiceAnswer(
                type="choice",
                selected="0",
                probabilities={
                    str(index): value for index, value in enumerate(probabilities)
                },
                confidence=0.5,
            )


@pytest.mark.parametrize(
    "field", [{"question_types": frozenset({"noul"})}, {"max_questions": 1}]
)
def test_capabilities_declare_only_input_limits(field):
    with pytest.raises(ValidationError):
        ProviderCapabilities(**field)
