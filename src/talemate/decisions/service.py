import asyncio
import math
from time import monotonic
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from talemate.exceptions import ControlFlowException
from talemate.util.logging import serialize_log_value

from .budget import state_tokens
from .events import DecisionLog, Failure, QuestionPresentation, RequestRecord
from .models import DecisionRequest, ProviderResponse, Question, validate_answers
from .ownership import Ownership
from .provider import DecisionError, DecisionProvider, FailureCode


def _within_limits(caps, state_size: int, question_tokens: list[int]) -> bool:
    for tokens, limit in (
        (state_size + sum(question_tokens), caps.max_input_tokens),
        (state_size + max(question_tokens), caps.max_question_input_tokens),
    ):
        if limit is not None:
            padded = tokens * caps.input_token_multiplier
            if not math.isfinite(padded) or math.ceil(padded) > limit:
                return False
    return True


def _question_tokens(provider: DecisionProvider, questions) -> dict[str, int]:
    return {
        key: state_tokens({key: provider.serialize_question(question)})
        for key, question in questions.items()
    }


def _largest_state(caps, question_tokens: list[int]) -> int:
    """The most state tokens that pass the limits beside these questions; < 0 when none do."""
    tokens = min(
        math.floor(limit / caps.input_token_multiplier) - used
        for limit, used in (
            (caps.max_input_tokens, sum(question_tokens)),
            (caps.max_question_input_tokens, max(question_tokens)),
        )
        if limit is not None
    )
    # the division can round up past what the check accepts
    while tokens >= 0 and not _within_limits(caps, tokens, question_tokens):
        tokens -= 1
    return tokens


def _request_parts(request: DecisionRequest, provider: DecisionProvider):
    """
    The question sets to send, in order: one when the request fits the limits,
    otherwise the questions packed into as few parts as fit. Each part carries
    the whole state.
    """
    caps = provider.capabilities
    if caps.max_input_tokens is None and caps.max_question_input_tokens is None:
        return [request.questions]
    size = state_tokens(request.state)
    question_tokens = _question_tokens(provider, request.questions)
    if not _within_limits(caps, size, [max(question_tokens.values())]):
        raise DecisionError(FailureCode.OVERSIZE)
    parts = [{}]
    for key, question in request.questions.items():
        tokens = [question_tokens[k] for k in parts[-1]] + [question_tokens[key]]
        if parts[-1] and not _within_limits(caps, size, tokens):
            parts.append({})
        parts[-1][key] = question
    return parts


PRESENTATION = TypeAdapter(dict[str, QuestionPresentation])
QUESTIONS = TypeAdapter(dict[str, Question])


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

    def state_budget(self, questions, *, split: bool = False) -> int | None:
        """
        Tokens the state of a request with these questions may take, by the
        local estimate; None when nothing limits it. The state is sized to go
        out with all the questions in one request; with `split`, or when the
        questions alone fill the limit, it is sized beside the largest one and
        the questions are sent in parts.
        """
        provider = self.provider
        if not self.enabled or provider is None or not provider.ready:
            return None
        caps = provider.capabilities
        if caps.max_input_tokens is None and caps.max_question_input_tokens is None:
            return None
        try:
            questions = QUESTIONS.validate_python(questions)
        except (ValidationError, ValueError, TypeError):
            return None
        if not questions:
            return None
        question_tokens = list(_question_tokens(provider, questions).values())
        if not split:
            together = _largest_state(caps, question_tokens)
            if together > 0:
                return together
        return max(_largest_state(caps, [max(question_tokens)]), 0)

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
            if exc.response_body is not None:
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
        parts = _request_parts(request, provider)
        record.dispatched = True
        self.log.update(record)
        answers = {}
        bodies = []

        def response_body():
            if len(parts) > 1:
                return list(bodies)
            return bodies[0] if bodies else None

        for questions in parts:
            part = (
                request
                if len(parts) == 1
                else request.model_copy(update={"questions": questions})
            )
            try:
                response = await provider.request(part)
            except DecisionError as exc:
                if len(parts) == 1 or exc.response_body is None:
                    raise
                bodies.append(exc.response_body)
                raise DecisionError(exc.code, response_body=response_body()) from None
            try:
                response = ProviderResponse.model_validate(response)
            except (ValidationError, ValueError, TypeError):
                raise DecisionError(
                    FailureCode.INVALID_RESPONSE, response_body=response_body()
                ) from None
            bodies.append(response.response_body)
            if len(parts) > 1:
                # kept when a later part fails or the time limit ends the request
                record.raw = serialize_log_value(response_body())
            if response.refused:
                raise DecisionError(FailureCode.REFUSED, response_body=response_body())
            try:
                answers.update(validate_answers(part, response))
            except (ValidationError, ValueError, TypeError):
                raise DecisionError(
                    FailureCode.INVALID_RESPONSE, response_body=response_body()
                ) from None
        return answers, response_body()


decision_service = DecisionService()
