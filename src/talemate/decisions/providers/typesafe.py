import json
import math
from collections.abc import Callable

import httpx

from ..models import (
    ChoiceQuestion,
    DecisionRequest,
    NoulQuestion,
    ProviderResponse,
    Question,
)
from ..provider import DecisionError, FailureCode, ProviderCapabilities


PROVIDER_BAD_REQUEST_PREFIX = "HTTP 400: "
INPUT_LIMIT_ERROR_TYPE = "max_tokens_exceeded"

# Keep transport and account wrappers out of the public decision log.
INSPECTABLE_KEYS = ("model", "answers", "usage")


def _failure_facts(response: httpx.Response, detail: str) -> str:
    """Unreadable bodies may contain secrets; only response metadata is inspectable."""
    content_type = response.headers.get("content-type") or "no content type"
    return (
        f"malformed response: status {response.status_code}, "
        f"{content_type.split(';')[0].strip()}, "
        f"{len(response.content)} bytes, {detail}"
    )


def _strict_json(text: str):
    """Reject nonfinite values here so they become invalid-response failures."""

    def finite(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite number")
        return number

    def reject(name: str):
        raise ValueError(f"nonfinite constant: {name}")

    return json.loads(text, parse_float=finite, parse_constant=reject)


def _input_limit_exceeded(response: httpx.Response) -> bool:
    try:
        body = _strict_json(response.text)
        if not isinstance(body, dict):
            return False
        detail = body.get("detail")
        if detail is None:
            error = body.get("error")
            if not isinstance(error, dict):
                return False
            message = error.get("message")
            if not isinstance(message, str) or not message.startswith(
                PROVIDER_BAD_REQUEST_PREFIX
            ):
                return False
            body = _strict_json(message.removeprefix(PROVIDER_BAD_REQUEST_PREFIX))
            detail = body.get("detail") if isinstance(body, dict) else None
    except ValueError:
        return False
    return (
        isinstance(detail, dict) and detail.get("error_type") == INPUT_LIMIT_ERROR_TYPE
    )


def _levels(value):
    """Preserve malformed index maps for the framework to reject and log."""
    if not isinstance(value, dict):
        return value
    try:
        positions = sorted(int(key) for key in value)
    except (TypeError, ValueError):
        return value
    if positions != list(range(len(value))):
        return value
    return [value[key] for key in sorted(value, key=int)]


def _normalized_answer(question: Question, answer: dict) -> dict:
    wire_type = answer.get("type")
    if wire_type is not None and wire_type != question.type:
        # an answer that mislabels its type but carries the payload key of the
        # requested one would otherwise normalize into a valid answer
        return answer
    if question.type == "noul":
        return {"type": "noul", "p_true": answer.get("noul")}
    if question.type == "choice":
        return {
            "type": "choice",
            "selected": answer.get("choice"),
            "probabilities": answer.get("probabilities"),
            "confidence": answer.get("confidence"),
        }
    return {
        "type": "score",
        "value": answer.get("score"),
        "probabilities": _levels(answer.get("probabilities")),
        "legend": _levels(answer.get("legend")),
        "confidence": answer.get("confidence"),
    }


class TypeSafeDecisionProvider:
    url: str
    requires_api_key = False

    def __init__(
        self,
        model: str,
        credential: Callable[[], str | None],
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        capabilities: ProviderCapabilities | None = None,
    ):
        self.model = model
        self.credential = credential
        self.transport = transport
        self.capabilities = capabilities or ProviderCapabilities()

    @property
    def missing_settings(self) -> list[str]:
        return [
            name
            for name, present in (
                ("model", bool(self.model.strip())),
                ("base_url", bool(self.url)),
                ("api_key", not self.requires_api_key or bool(self.credential())),
            )
            if not present
        ]

    @property
    def ready(self) -> bool:
        return not self.missing_settings

    def serialize_question(self, question: Question) -> dict:
        if isinstance(question, NoulQuestion):
            wire = {"type": "noul", "instructions": question.instructions}
            # OpenRouter requires both criteria; keep one shape across providers.
            if (
                question.true_criteria is not None
                and question.false_criteria is not None
            ):
                wire["criteria"] = {
                    "true": question.true_criteria,
                    "false": question.false_criteria,
                }
            return wire
        if isinstance(question, ChoiceQuestion):
            return {
                "type": "choice",
                "instructions": question.instructions,
                "criteria": dict(question.options),
            }
        return {
            "type": "score",
            "instructions": question.instructions,
            "criteria": list(question.rubric),
        }

    async def request(self, request: DecisionRequest) -> ProviderResponse:
        api_key = self.credential()
        if self.requires_api_key and not api_key:
            raise DecisionError(FailureCode.AUTHENTICATION)

        payload = {
            "model": self.model,
            "state": request.state,
            "questions": {
                key: self.serialize_question(question)
                for key, question in request.questions.items()
            },
        }

        try:
            # no transport timeout: the decision service owns the one deadline
            # that covers waiting, connection, reading and validation
            async with httpx.AsyncClient(
                transport=self.transport, timeout=None
            ) as client:
                response = await client.post(
                    self.url,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                )
        except httpx.HTTPError:
            raise DecisionError(FailureCode.TRANSPORT) from None

        if response.status_code in (401, 403):
            raise DecisionError(FailureCode.AUTHENTICATION)
        if response.status_code == 413 or (
            response.status_code == 400 and _input_limit_exceeded(response)
        ):
            raise DecisionError(FailureCode.OVERSIZE)
        if not response.is_success:
            raise DecisionError(FailureCode.TRANSPORT)

        try:
            body = _strict_json(response.text)
        except json.JSONDecodeError as exc:
            raise DecisionError(
                FailureCode.INVALID_RESPONSE,
                response_body=_failure_facts(
                    response, f"parse error at char {exc.pos}"
                ),
            ) from None
        except ValueError:
            raise DecisionError(
                FailureCode.INVALID_RESPONSE,
                response_body=_failure_facts(response, "nonfinite number"),
            ) from None

        if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
            raise DecisionError(
                FailureCode.INVALID_RESPONSE,
                response_body=_failure_facts(response, "no answers mapping"),
            )

        inspectable = {key: body[key] for key in INSPECTABLE_KEYS if key in body}
        answers = {}
        for key, answer in body["answers"].items():
            question = request.questions.get(key)
            if question is None or not isinstance(answer, dict):
                answers[key] = answer
                continue
            answers[key] = _normalized_answer(question, answer)

        return ProviderResponse(answers=answers, response_body=inspectable)
