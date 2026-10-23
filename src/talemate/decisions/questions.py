"""
Questions and answers as a policy template sees them: a question with its
options and threshold in, a decided value out. The engine's question types
and answer shapes stay behind these models.
"""

from collections.abc import Iterator
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from .models import ChoiceAnswer, NoulAnswer

Threshold = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]

NONE_OPTION = "none"


class YesNo(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    threshold: Threshold
    true_criteria: str | None = None
    false_criteria: str | None = None

    def engine_question(self) -> dict:
        return {
            "type": "noul",
            "instructions": self.text,
            "true_criteria": self.true_criteria,
            "false_criteria": self.false_criteria,
        }


class Choice(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    options: dict[str, str]
    # what choosing none of the options means
    none: str
    threshold: Threshold

    @field_validator("options")
    @classmethod
    def none_is_reserved(cls, options):
        if NONE_OPTION in options:
            raise ValueError(f"{NONE_OPTION!r} is reserved for choosing none")
        return options

    def engine_question(self) -> dict:
        return {
            "type": "choice",
            "instructions": self.text,
            "options": {NONE_OPTION: self.none, **self.options},
        }


def yes_no(
    text: str,
    threshold: float,
    true_criteria: str | None = None,
    false_criteria: str | None = None,
) -> YesNo:
    return YesNo(
        text=text,
        threshold=threshold,
        true_criteria=true_criteria,
        false_criteria=false_criteria,
    )


def choice(text: str, options: dict[str, str], none: str, threshold: float) -> Choice:
    return Choice(text=text, options=options, none=none, threshold=threshold)


class YesNoAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    p_true: float
    threshold: float

    @property
    def confidence(self) -> float:
        return max(self.p_true, 1 - self.p_true)

    @property
    def yes(self) -> bool:
        return self.p_true >= self.threshold

    @property
    def no(self) -> bool:
        return 1 - self.p_true >= self.threshold

    @property
    def value(self) -> bool | None:
        if self.yes:
            return True
        if self.no:
            return False
        return None

    @property
    def uncertain(self) -> bool:
        return self.value is None

    def log_details(self) -> dict:
        return {"p_true": self.p_true, "confidence": self.confidence}


class ChoiceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    selected: str
    confidence: float
    threshold: float

    @property
    def value(self) -> str | None:
        """The chosen option, or None when the model chose none or is unsure."""
        if self.selected == NONE_OPTION or self.confidence < self.threshold:
            return None
        return self.selected

    @property
    def uncertain(self) -> bool:
        return self.value is None

    def log_details(self) -> dict:
        return {"choice_confidence": self.confidence}


Answer = YesNoAnswer | ChoiceResult


class Answers(RootModel[dict[str, Answer]]):
    """Answers by question id; a template reads `answers.<id>` or `answers[id]`."""

    model_config = ConfigDict(frozen=True)

    def __getitem__(self, key: str) -> Answer:
        return self.root[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def __contains__(self, key: object) -> bool:
        return key in self.root

    def items(self):
        return self.root.items()

    def keys(self):
        return self.root.keys()

    def values(self):
        return self.root.values()

    def decided(self) -> dict:
        return {key: answer.value for key, answer in self.root.items()}


def to_answer(
    key: str,
    request_id: str,
    question: YesNo | Choice,
    answer: NoulAnswer | ChoiceAnswer,
) -> Answer:
    if isinstance(question, YesNo):
        return YesNoAnswer(
            id=key,
            request_id=request_id,
            p_true=answer.p_true,
            threshold=question.threshold,
        )
    return ChoiceResult(
        id=key,
        request_id=request_id,
        selected=answer.selected,
        confidence=answer.confidence,
        threshold=question.threshold,
    )


def plain(value):
    """Answer objects inside an action's arguments become their decided values."""
    if isinstance(value, Answers):
        return value.decided()
    if isinstance(value, (YesNoAnswer, ChoiceResult)):
        return value.value
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
