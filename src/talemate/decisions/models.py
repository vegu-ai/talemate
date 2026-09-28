import json
import math
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)


Text = Annotated[str, Field(strict=True, min_length=1, pattern=r"\S")]
Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
PROBABILITY_ROUNDING_PER_ENTRY = 0.005
MAX_PROBABILITY_ROUNDING_TOLERANCE = 0.05
QuestionType = Literal["noul", "choice", "score"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class NoulQuestion(Model):
    type: Literal["noul"]
    instructions: Text
    true_criteria: Text | None = None
    false_criteria: Text | None = None


class ChoiceQuestion(Model):
    type: Literal["choice"]
    instructions: Text
    options: Annotated[dict[Text, Text], Field(min_length=2)]


class ScoreQuestion(Model):
    type: Literal["score"]
    instructions: Text
    rubric: Annotated[list[Text], Field(min_length=2)]

    @model_validator(mode="after")
    def unique_levels(self):
        if len(set(self.rubric)) != len(self.rubric):
            raise ValueError("rubric descriptions must be unique")
        return self


Question = Annotated[
    NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")
]


class DecisionRequest(Model):
    invocation_id: Text
    request_id: Text
    label: Text
    state: str | dict[str, JsonValue] | list[JsonValue]
    questions: Annotated[dict[Text, Question], Field(min_length=1)]

    @model_validator(mode="after")
    def finite_state(self):
        json.dumps(self.state, allow_nan=False)
        return self


class NoulAnswer(Model):
    type: Literal["noul"]
    p_true: Probability


def normalize_distribution(values: list[float] | dict[str, float]):
    total = math.fsum(values.values() if isinstance(values, dict) else values)
    tolerance = min(
        PROBABILITY_ROUNDING_PER_ENTRY * len(values),
        MAX_PROBABILITY_ROUNDING_TOLERANCE,
    )
    # Decimal rounding boundaries can land just outside the float interval.
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=tolerance + 1e-12):
        raise ValueError("probabilities must sum to one within rounding tolerance")
    if isinstance(values, dict):
        return {key: value / total for key, value in values.items()}
    return [value / total for value in values]


class ChoiceAnswer(Model):
    type: Literal["choice"]
    selected: Text
    probabilities: Annotated[dict[Text, Probability], Field(min_length=2)]
    confidence: Probability

    @field_validator("probabilities")
    @classmethod
    def normalize_probabilities(cls, values):
        return normalize_distribution(values)

    @model_validator(mode="after")
    def distribution(self):
        if self.selected not in self.probabilities:
            raise ValueError("selected option is missing")
        return self


class ScoreAnswer(Model):
    type: Literal["score"]
    value: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    probabilities: Annotated[list[Probability], Field(min_length=2)]
    legend: Annotated[list[Text], Field(min_length=2)]
    confidence: Probability

    @field_validator("probabilities")
    @classmethod
    def normalize_probabilities(cls, values):
        return normalize_distribution(values)

    @model_validator(mode="after")
    def distribution(self):
        if len(self.probabilities) != len(self.legend):
            raise ValueError("score distribution and legend differ")
        if self.value > len(self.legend) - 1:
            raise ValueError("score is outside the rubric")
        return self


Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]
ANSWER_BATCH = TypeAdapter(dict[Text, Answer])


class ProviderResponse(Model):
    answers: dict[str, JsonValue]
    response_body: JsonValue = Field(
        description="Adapter-selected application response body for public inspection. "
        "Preserve original values; exclude credentials, headers and transport/config wrappers."
    )
    refused: bool = False

    @model_validator(mode="after")
    def finite_payload(self):
        json.dumps(self.model_dump(), allow_nan=False)
        return self


def validate_answers(request: DecisionRequest, response: ProviderResponse):
    answers = ANSWER_BATCH.validate_python(response.answers)
    if answers.keys() != request.questions.keys():
        raise ValueError("answer IDs must exactly match the question IDs")
    for key, question in request.questions.items():
        answer = answers[key]
        if answer.type != question.type:
            raise ValueError("answer type does not match the question")
        if isinstance(question, ChoiceQuestion):
            if answer.probabilities.keys() != question.options.keys():
                raise ValueError("choice options do not match the question")
        elif isinstance(question, ScoreQuestion):
            if answer.legend != question.rubric:
                raise ValueError("score legend does not match the rubric")
    return answers
