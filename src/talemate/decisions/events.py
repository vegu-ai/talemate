import copy
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field, computed_field

from talemate.util.dialogue import TextScope

from .models import Probability
from .provider import FailureCode


log = structlog.get_logger(__name__)
RequestStatus = Literal["pending", "completed", "cancelled", "failed"]
ActionStatus = Literal["pending", "completed", "cancelled", "failed", "skipped"]
InvocationStatus = Literal[
    "new", "running", "completed", "fallback", "preserved", "cancelled"
]
DecisionEvent = Literal["request", "action", "invocation", "removed"]


class Failure(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: FailureCode
    message: str

    @classmethod
    def from_code(cls, code: FailureCode):
        return cls(code=code, message=f"Decision policy unavailable: {code.value}")


class ActionRecord(BaseModel):
    action: str
    arguments: Any = None
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: ActionStatus = "pending"
    result: Any = None
    elapsed_ms: float | None = None
    failure: Failure | None = None
    reason: str | None = None


class QuestionPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    group_id: str
    label: str
    instructions: str
    passage_id: str
    passage_text: str
    scope: TextScope = "all"
    threshold: Probability


class RequestTokens(BaseModel):
    """
    The context one request sent, by the service's own count. `budget` is
    the state budget the feature sized its state to; a state the feature
    built at a fixed size is not `sized`. `reported` is the provider's input
    count over all parts, when every part reported one.
    """

    state: int
    questions: int
    parts: int = 1
    sized: bool = False
    budget: int | None = None
    reported: int | None = None

    @computed_field
    @property
    def sent(self) -> int:
        # every part carries the whole state beside its share of the questions
        return self.state * self.parts + self.questions


class RequestRecord(BaseModel):
    invocation_id: str
    template_uid: str
    source_group: str | None
    label: str
    provider: str | None
    model: str | None
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    state: object = None
    questions: dict = Field(default_factory=dict)
    presentation: dict[str, QuestionPresentation] = Field(default_factory=dict)
    tokens: RequestTokens | None = None
    status: RequestStatus = "pending"
    dispatched: bool = False
    elapsed_ms: float | None = None
    answers: dict | None = None
    raw: object = None
    failure: Failure | None = None
    policy_failure: Failure | None = None
    actions: list[ActionRecord] = Field(default_factory=list)
    outcomes: list[dict] = Field(default_factory=list)


class InvocationRecord(BaseModel):
    id: str
    template_uid: str
    source_group: str | None = None
    status: InvocationStatus = "running"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    actions: list[ActionRecord] = Field(default_factory=list)
    request_count: int = 0
    outcomes: list[dict] = Field(default_factory=list)


class DecisionLog:
    def __init__(self, max_finished: int = 50):
        if max_finished < 0:
            raise ValueError("max_finished must not be negative")
        self.max_finished = max_finished
        self.records: OrderedDict[str, RequestRecord] = OrderedDict()
        self.invocations: OrderedDict[str, InvocationRecord] = OrderedDict()
        self.active_invocations: set[str] = set()
        self.listeners: list[Callable[[dict], None]] = []

    def subscribe(self, listener: Callable[[dict], None]):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def emit(self, event: DecisionEvent, **payload):
        for listener in tuple(self.listeners):
            try:
                listener(copy.deepcopy({"event": event, **payload}))
            except Exception as exc:
                log.warning(
                    "decision_log_listener_failed",
                    listener=getattr(listener, "__qualname__", type(listener).__name__),
                    error_type=type(exc).__name__,
                )

    def start_invocation(self, record: InvocationRecord):
        self.invocations[record.id] = record
        self.active_invocations.add(record.id)
        self.update_invocation(record.id)

    def update_invocation(self, invocation_id: str):
        self.emit(
            "invocation",
            entry=self.invocations[invocation_id].model_dump(mode="json"),
        )

    def finish_invocation(self, invocation_id: str, *, status: InvocationStatus):
        self.invocations[invocation_id].status = status
        self.active_invocations.discard(invocation_id)
        self.update_invocation(invocation_id)
        self._prune()

    def add(self, record: RequestRecord):
        self.records[record.id] = record
        if invocation := self.invocations.get(record.invocation_id):
            invocation.request_count += 1
            self.update_invocation(invocation.id)
        self.update(record)

    def update(self, record: RequestRecord, *, prune=True):
        self.emit("request", entry=record.model_dump(mode="json"))
        if prune:
            self._prune()

    def finished(self, record: RequestRecord):
        invocation = self.invocations.get(record.invocation_id)
        return (
            record.status != "pending"
            and record.invocation_id not in self.active_invocations
            and (invocation is None or self.invocation_finished(invocation))
            and all(action.status != "pending" for action in record.actions)
        )

    def invocation_finished(self, record: InvocationRecord):
        return (
            record.status not in {"new", "running"}
            and record.id not in self.active_invocations
            and all(action.status != "pending" for action in record.actions)
        )

    def _finished_entries(self):
        # Invocation metadata accompanies its requests without taking a second slot.
        # Invocations without requests occupy one slot in the same retention budget.
        return sorted(
            [
                (r.timestamp, "request", r.id)
                for r in self.records.values()
                if self.finished(r)
            ]
            + [
                (r.timestamp, "invocation", r.id)
                for r in self.invocations.values()
                if not r.request_count and self.invocation_finished(r)
            ]
        )

    def _remove(self, entries):
        request_ids = [key for _, kind, key in entries if kind == "request"]
        invocation_ids = [key for _, kind, key in entries if kind == "invocation"]
        for request_id in request_ids:
            del self.records[request_id]
        referenced = {record.invocation_id for record in self.records.values()}
        invocation_ids.extend(
            record.id
            for record in self.invocations.values()
            if record.request_count
            and record.id not in referenced
            and self.invocation_finished(record)
        )
        for invocation_id in invocation_ids:
            del self.invocations[invocation_id]
        if request_ids or invocation_ids:
            self.emit("removed", request_ids=request_ids, invocation_ids=invocation_ids)

    def _prune(self):
        finished = self._finished_entries()
        self._remove(finished[: max(0, len(finished) - self.max_finished)])

    def clear_finished(self):
        self._remove(self._finished_entries())

    def snapshot(self):
        return {
            "requests": [
                record.model_dump(mode="json") for record in self.records.values()
            ],
            "invocations": [
                record.model_dump(mode="json") for record in self.invocations.values()
            ],
        }
