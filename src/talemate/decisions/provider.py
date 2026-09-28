from enum import StrEnum
from typing import Protocol

from pydantic import Field, JsonValue

from .models import DecisionRequest, Model, ProviderResponse, Question, QuestionType


class FailureCode(StrEnum):
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED = "unsupported"
    OVERSIZE = "oversize"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    AUTHENTICATION = "authentication"
    INVALID_RESPONSE = "invalid_response"
    REFUSED = "refused"
    TEMPLATE = "template"
    RESULT = "result"
    ACTION = "action"
    ACTION_DENIED = "action_denied"
    BUDGET = "budget"
    FALLBACK = "fallback"


class DecisionError(Exception):
    def __init__(self, code: FailureCode, *, response_body=None):
        self.code = FailureCode(code)
        self.response_body = response_body
        super().__init__(self.code.value)


class ProviderCapabilities(Model):
    question_types: frozenset[QuestionType] = Field(
        default=frozenset({"noul", "choice", "score"}), min_length=1
    )
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_question_input_tokens: int | None = Field(default=None, gt=0)
    input_token_multiplier: float = Field(default=1.0, ge=1, allow_inf_nan=False)
    max_questions: int | None = Field(default=None, gt=0)


class DecisionProvider(Protocol):
    """Adapters select inspectable response bodies, never transport/config wrappers."""

    name: str
    model: str
    ready: bool
    capabilities: ProviderCapabilities

    def serialize_question(self, question: Question) -> dict[str, JsonValue]: ...

    async def request(self, request: DecisionRequest) -> ProviderResponse: ...
