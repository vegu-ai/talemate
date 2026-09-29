import asyncio
import json
import math
from time import monotonic
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from talemate.exceptions import ControlFlowException
from talemate.util import count_tokens
from talemate.util.logging import serialize_log_value

from .events import DecisionLog, Failure, QuestionPresentation, RequestRecord
from .models import DecisionRequest, ProviderResponse, validate_answers
from .ownership import Ownership
from .provider import DecisionError, DecisionProvider, FailureCode


def _check_input_size(request: DecisionRequest, provider: DecisionProvider):
    caps = provider.capabilities
    if caps.max_input_tokens is None and caps.max_question_input_tokens is None:
        return
    state_tokens = count_tokens(json.dumps(request.state, ensure_ascii=False))
    question_tokens = [
        count_tokens(
            json.dumps({key: provider.serialize_question(question)}, ensure_ascii=False)
        )
        for key, question in request.questions.items()
    ]
    for tokens, limit in (
        (state_tokens + sum(question_tokens), caps.max_input_tokens),
        (state_tokens + max(question_tokens), caps.max_question_input_tokens),
    ):
        if limit is not None:
            padded = tokens * caps.input_token_multiplier
            if not math.isfinite(padded) or math.ceil(padded) > limit:
                raise DecisionError(FailureCode.OVERSIZE)


PRESENTATION = TypeAdapter(dict[str, QuestionPresentation])


class DecisionHandle(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    request_id: str
    invocation_id: str
    # read-only: policy templates receive the answers
    answers: MappingProxyType


class Unavailable(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    invocation_id: str
    failure: Failure


class DecisionService:
    def __init__(
        self,
        provider: DecisionProvider | None = None,
        *,
        enabled: bool = False,
        timeout_seconds: float = 1.5,
        log: DecisionLog | None = None,
    ):
        self.provider = provider
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.log = log if log is not None else DecisionLog()

    @property
    def timeout_seconds(self):
        return self._timeout_seconds

    @timeout_seconds.setter
    def timeout_seconds(self, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")
        self._timeout_seconds = float(value)

    def new_record(self, invocation_id, template_uid, source_group, label):
        return RequestRecord(
            invocation_id=invocation_id,
            template_uid=template_uid,
            source_group=source_group,
            label=label,
            provider=self.provider.name if self.provider else None,
            model=self.provider.model if self.provider else None,
        )

    async def evaluate(
        self,
        label,
        *,
        state,
        questions,
        invocation_id,
        template_uid,
        source_group=None,
        ownership=None,
        presentation=None,
    ) -> DecisionHandle | Unavailable:
        ownership = ownership or Ownership()
        record = self.new_record(
            invocation_id,
            template_uid,
            source_group,
            label if isinstance(label, str) else "invalid request",
        )
        started = monotonic()
        self.log.add(record)
        try:
            answers, raw = await ownership.wait(
                self._request(record, label, state, questions, presentation),
                self.timeout_seconds,
            )
            record.answers = {
                key: answer.model_dump() for key, answer in answers.items()
            }
            record.status = "completed"
            record.raw = serialize_log_value(raw)
            return DecisionHandle(
                request_id=record.id,
                invocation_id=invocation_id,
                answers=MappingProxyType(answers),
            )
        except (asyncio.CancelledError, ControlFlowException):
            record.status = "cancelled"
            raise
        except TimeoutError:
            record.failure = Failure.from_code(FailureCode.TIMEOUT)
        except DecisionError as exc:
            record.failure = Failure.from_code(exc.code)
            record.raw = serialize_log_value(exc.response_body)
        except Exception:
            record.failure = Failure.from_code(FailureCode.TRANSPORT)
        finally:
            record.elapsed_ms = (monotonic() - started) * 1000
            if record.failure:
                record.status = "failed"
            self.log.update(record)
        return Unavailable(
            request_id=record.id, invocation_id=invocation_id, failure=record.failure
        )

    async def _request(self, record, label, state, questions, presentation=None):
        try:
            request = DecisionRequest(
                invocation_id=record.invocation_id,
                request_id=record.id,
                label=label,
                state=state,
                questions=questions,
            )
            record.presentation = PRESENTATION.validate_python(
                {} if presentation is None else presentation
            )
        except (ValidationError, ValueError, TypeError):
            raise DecisionError(FailureCode.INVALID_REQUEST) from None
        record.state = serialize_log_value(request.state)
        record.questions = serialize_log_value(
            {
                key: question.model_dump(exclude_none=True)
                for key, question in request.questions.items()
            }
        )
        if not self.enabled:
            raise DecisionError(FailureCode.DISABLED)
        provider = self.provider
        if provider is None or not provider.ready:
            raise DecisionError(FailureCode.UNAVAILABLE)
        _check_input_size(request, provider)
        record.dispatched = True
        self.log.update(record)
        response = await provider.request(request)
        try:
            response = ProviderResponse.model_validate(response)
        except (ValidationError, ValueError, TypeError):
            raise DecisionError(FailureCode.INVALID_RESPONSE) from None
        if response.refused:
            raise DecisionError(
                FailureCode.REFUSED, response_body=response.response_body
            )
        try:
            answers = validate_answers(request, response)
        except (ValidationError, ValueError, TypeError):
            raise DecisionError(
                FailureCode.INVALID_RESPONSE, response_body=response.response_body
            ) from None
        return answers, response.response_body


decision_service = DecisionService()
