import math
from typing import Literal

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from talemate.world_state.templates.base import repairs_unknown_choices

log = structlog.get_logger("world-state.templates.decision_checks")

DecisionCheckKind = Literal["repetition", "style"]
DEFAULT_THRESHOLD = 0.8


class DecisionCheckQuestion(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    question: str = Field(min_length=1, pattern=r"\S")
    true_criteria: str = ""
    false_criteria: str = ""
    kind: DecisionCheckKind = "style"
    instructions: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="before")
    @classmethod
    def repair_missing_id(cls, value, info):
        if (
            repairs_unknown_choices(info)
            and isinstance(value, dict)
            and "id" not in value
        ):
            return {**value, "id": None}
        return value

    @field_validator("id", "kind", "true_criteria", "false_criteria", mode="wrap")
    @classmethod
    def repair_choice(cls, value, handler, info):
        try:
            return handler(value)
        except ValidationError:
            if not repairs_unknown_choices(info):
                raise
            fallback = {"id": "question", "kind": "style"}.get(info.field_name, "")
            log.warning(
                "repairing decision question field",
                field=info.field_name,
                fallback=fallback,
            )
            return fallback


class DecisionCheck(BaseModel):
    name: str = Field(min_length=1)
    active: bool = True
    threshold: float = Field(default=DEFAULT_THRESHOLD, ge=0, le=1, allow_inf_nan=False)
    requires_style: bool = False
    questions: list[DecisionCheckQuestion] = Field(min_length=1)

    @field_validator("threshold", mode="wrap")
    @classmethod
    def repair_threshold(cls, value, handler, info):
        try:
            return handler(value)
        except ValidationError:
            if not repairs_unknown_choices(info):
                raise
            try:
                number = float(value)
                fallback = (
                    min(1.0, max(0.0, number))
                    if math.isfinite(number)
                    else DEFAULT_THRESHOLD
                )
            except (ValueError, TypeError, OverflowError):
                fallback = DEFAULT_THRESHOLD
            log.warning("repairing decision check threshold", fallback=fallback)
            return fallback


def load_decision_checks(value, info) -> list[DecisionCheck]:
    if not isinstance(value, list):
        log.warning(
            "ignoring malformed decision check list", template=info.data.get("name")
        )
        return []
    checks = []
    question_order = []
    for index, item in enumerate(value):
        try:
            check = DecisionCheck.model_validate(item, context=info.context)
            checks.append(check)
            originals = item["questions"] if isinstance(item, dict) else item.questions
            for original, question in zip(originals, check.questions):
                original_id = (
                    original.get("id") if isinstance(original, dict) else original.id
                )
                question_order.append((original_id != question.id, question))
        except ValidationError:
            log.warning(
                "ignoring malformed decision check",
                template=info.data.get("name"),
                check_index=index,
            )
    reserved = {question.id for check in checks for question in check.questions}
    seen = set()
    # Keep authored IDs before assigning unique names to repaired questions.
    for _, question in sorted(question_order, key=lambda item: item[0]):
        if question.id in seen:
            suffix = 2
            while f"{question.id}_{suffix}" in reserved:
                suffix += 1
            question.id = f"{question.id}_{suffix}"
            reserved.add(question.id)
            log.warning(
                "renaming duplicate decision question ID", question_id=question.id
            )
        seen.add(question.id)
    return checks


def default_writing_style_decision_checks() -> list[DecisionCheck]:
    return [
        DecisionCheck(
            name="Repeated beats and description reuse",
            questions=[
                DecisionCheckQuestion(
                    id="repetition",
                    question="Does passage {passage_id} repeat information, an action, observation or story beat already conveyed in preceding history or earlier passages of the current text? Judge meaning, not shared words. For summarization or contextual generation, overlap with source_context or summarization_history is expected evidence, not itself repetition; flag only redundant retelling within the draft.",
                    true_criteria="The passage restates an already conveyed beat without a meaningful new development.",
                    false_criteria="The passage adds a new action, fact or development; necessary continuity or recurring subjects alone are not repetition.",
                    kind="repetition",
                    instructions="Remove this repeated beat, or replace it with genuinely different content if repetition handling is set to rewrite.",
                ),
                DecisionCheckQuestion(
                    id="description_reuse",
                    question="Does passage {passage_id} reuse a distinctive phrase, image, or description already used in the history or an earlier current passage? Reuse may be near-verbatim, paraphrased, or applied to a new occurrence; shared names, ordinary words, and factual continuity alone do not count. For summarization or contextual generation, overlap with source_context or summarization_history is expected evidence, not itself description reuse; flag only redundant reuse within the draft.",
                    true_criteria="Substantially the same distinctive wording or image is reused, even if this describes a new occurrence of the action.",
                    false_criteria="No reuse of distinctive phrasing or imagery; shared names, common words, or necessary factual continuity alone do not count.",
                    kind="repetition",
                    instructions="Replace the reused description with fresh wording or a different image. Preserve the event and factual content; do not remove the event merely because its description was reused.",
                ),
            ],
        ),
        DecisionCheck(
            name="Writing style and unwanted prose",
            requires_style=True,
            questions=[
                DecisionCheckQuestion(
                    id="style",
                    question="Does passage {passage_id} violate the supplied writing_style or an active prose_rule? Evaluate the passage in its complete current text and task context. The prose rules include the director's intended corrections; judge their meaning, not just matching words.",
                    true_criteria="The passage conflicts with an explicit writing-style instruction or exhibits unwanted prose described by an active rule.",
                    false_criteria="The passage follows the applicable instructions. Vivid detail, atmosphere or dialogue is not a violation on its own.",
                    kind="style",
                    instructions="Follow the writing style and active prose rules; preserve factual content.",
                ),
            ],
        ),
    ]
