import asyncio
import random
from collections.abc import Callable, Mapping
from pathlib import Path
from time import monotonic
from typing import Any, Generic, TypeVar
from uuid import uuid4

import jinja2
from pydantic import BaseModel, ConfigDict, Field

import talemate.emit.async_signals as async_signals
from talemate.context import active_scene
from talemate.exceptions import ControlFlowException
from talemate.prompts.base import (
    Prompt,
    active_template_uid,
    send_outside_render,
    signals_after_render,
)
from talemate.prompts.groups import get_group_template_path
from talemate.util.logging import serialize_log_value

from .events import (
    ActionRecord,
    Failure,
    InvocationRecord,
    InvocationStatus,
    RequestRecord,
    RequestStatus,
)
from .ownership import Ownership
from .provider import DecisionError, FailureCode
from .service import DecisionHandle, DecisionService, Unavailable


T = TypeVar("T")
UNSET = object()


class ActionBudget(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    limit: int = Field(ge=0)


class PolicyAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    call: Callable
    enabled: Callable[[], bool]
    budget: ActionBudget | None = None
    serialize_arguments: Callable[[dict], Any] = serialize_log_value
    serialize_result: Callable[[Any], Any] = serialize_log_value


class PolicyUnavailable(Exception):
    def __init__(self, unavailable: Unavailable):
        self.unavailable = unavailable


class PolicyActionError(DecisionError):
    def __init__(self, code, records):
        super().__init__(code)
        self.request_ids = tuple(record.id for record in records)


async_signals.register("decision.invocation.finished", "decision.gate.resolved")


class DecisionRequestOutcome(BaseModel):
    request_id: str
    label: str
    status: RequestStatus
    failure_code: str | None = None
    answers: dict | None = None
    elapsed_ms: float | None = None

    @classmethod
    def from_record(cls, record: RequestRecord) -> "DecisionRequestOutcome":
        return cls(
            request_id=record.id,
            label=record.label,
            status=record.status,
            failure_code=record.failure.code.value if record.failure else None,
            answers=record.answers,
            elapsed_ms=record.elapsed_ms,
        )


class DecisionInvocationFinished(BaseModel):
    """
    A decision policy has finished: completed (the decision model answered),
    fallback (the usual request ran instead) or preserved (the original
    result was kept).
    """

    invocation_id: str
    template_uid: str
    source_group: str | None = None
    status: InvocationStatus
    requests: list[DecisionRequestOutcome] = Field(default_factory=list)
    actions: list[dict] = Field(default_factory=list)


class PolicyInvocation(Generic[T]):
    def __init__(
        self,
        uid: str,
        *,
        service: DecisionService,
        variables: dict,
        validate_result: Callable[[Any], T],
        disabled_path: Callable,
        original_result: T,
        actions: Mapping[tuple[str, str], PolicyAction] | None = None,
        is_current: Callable[[], bool] = lambda: True,
    ):
        self.id = str(uuid4())
        self.prompt = Prompt.get(uid, variables)
        self.service = service
        self.validate_result = validate_result
        self.disabled_path = disabled_path
        self.original_result = validate_result(original_result)
        self.actions = dict(actions or {})
        self.is_current = is_current
        self.status: InvocationStatus = "new"
        self.rendered_text: str | None = None
        self.source_group: str | None = None
        self.action_trace: list[ActionRecord] = []
        self.handles: dict[str, DecisionHandle] = {}
        self._result = UNSET
        self._result_count = 0
        self._action_started = False
        # keyed by identity: separate budgets with equal limits count independently
        self._budget_usage: dict[int, int] = {}
        self._interruption: BaseException | None = None
        self._ownership: Ownership | None = None

    @property
    def result(self) -> T:
        if self.status not in {"completed", "fallback", "preserved"}:
            raise RuntimeError("Policy invocation has no completed result")
        return self._result

    def __str__(self):
        return f"PolicyInvocation({self.id}, {self.prompt.uid}, {self.status})"

    def _source_group(self, template):
        if not template.filename:
            return None
        filename = Path(template.filename).resolve()
        scene = active_scene.get()
        if scene and scene.template_dir:
            if filename.is_relative_to(Path(scene.template_dir).resolve()):
                return "scene"
        config = self.prompt.config.prompts
        groups = [*config.group_priority, *config.template_sources.values(), "default"]
        for group in dict.fromkeys(groups):
            path = get_group_template_path(
                group, self.prompt.agent_type, self.prompt.name
            )
            if path is not None and path.resolve() == filename:
                return group
        return "override"

    def _render(self):
        env = self.prompt.template_env()
        env.undefined = jinja2.StrictUndefined
        helpers = {
            "decide": self.decide,
            "agent_action": self.agent_action,
            "agent_config": self.prompt.agent_config,
            "decision_outcome": self.decision_outcome,
            "decision_result": self.decision_result,
            "random_choice": random.choice,
            "len": len,
            "make_list": list,
            "make_dict": dict,
        }
        env.globals.update(helpers)
        template = env.get_template(f"{self.prompt.name}.jinja2")
        self.source_group = self._source_group(template)
        self.service.log.invocations[self.id].source_group = self.source_group
        context = {**self.prompt.vars, **helpers}
        with signals_after_render():
            self.rendered_text = template.render(context)

    def _check_running(self):
        if self.status != "running":
            raise RuntimeError("Policy helpers require an active invocation")
        self._ownership.check()

    async def run(self) -> T:
        if self.status == "cancelled":
            raise self._interruption
        if self.status != "new":
            return self.result
        self.status = "running"
        self._ownership = Ownership(self.is_current)
        record = InvocationRecord(id=self.id, template_uid=self.prompt.uid)
        # the logged invocation and the trace share one list of actions
        self.action_trace = record.actions
        self.service.log.start_invocation(record)
        token = active_template_uid.set(self.prompt.uid)
        try:
            self._ownership.check()
            self._render()
            self._ownership.check()
            if self._result_count != 1:
                raise DecisionError(FailureCode.RESULT)
            self.status = "completed"
        except (asyncio.CancelledError, ControlFlowException) as exc:
            self.status = "cancelled"
            self._interruption = exc
            raise
        except Exception as exc:
            await self._recover(exc)
        finally:
            active_template_uid.reset(token)
            finished = DecisionInvocationFinished(
                invocation_id=self.id,
                template_uid=self.prompt.uid,
                source_group=self.source_group,
                status=self.status,
                requests=[
                    DecisionRequestOutcome.from_record(record)
                    for record in self.service.log.records.values()
                    if record.invocation_id == self.id
                ],
                actions=[
                    action.model_dump(mode="json") for action in self.action_trace
                ],
            )
            self.service.log.finish_invocation(self.id, status=self.status)
        await send_outside_render("decision.invocation.finished", finished)
        return self.result

    def _failure_records(self, exc):
        if isinstance(exc, PolicyUnavailable):
            return [self.service.log.records[exc.unavailable.request_id]]
        code = exc.code if isinstance(exc, DecisionError) else FailureCode.TEMPLATE
        records = (
            [self.service.log.records[key] for key in exc.request_ids]
            if isinstance(exc, PolicyActionError)
            else []
        )
        if records:
            for record in records:
                record.policy_failure = Failure.from_code(code)
                self.service.log.update(record)
        else:
            record = self.service.new_record(
                self.id, self.prompt.uid, self.source_group, "policy"
            )
            record.status = "failed"
            record.failure = Failure.from_code(code)
            self.service.log.add(record)
            records = [record]
        return records

    async def _recover(self, exc):
        try:
            self._ownership.check()
            records = self._failure_records(exc)
            if self._action_started:
                self._result = self.original_result
                self.status = "preserved"
                for record in records:
                    record.outcomes.append(
                        {
                            "action": "preserve_original",
                            "reason": "action_already_started",
                        }
                    )
                    self.service.log.update(record)
                return
            action = ActionRecord(action="disabled_path", reason="decision_unavailable")
            self.action_trace.append(action)
            for record in records:
                record.actions.append(action)
            self._action_update(action, records)
            started = monotonic()
            try:
                value = await self._ownership.wait(self.disabled_path())
                self._ownership.check()
                self._result = self.validate_result(value)
                action.result = serialize_log_value(value)
                action.status = "completed"
                self.status = "fallback"
            except (asyncio.CancelledError, ControlFlowException):
                action.status = "cancelled"
                raise
            except Exception:
                action.status = "failed"
                action.failure = Failure.from_code(FailureCode.FALLBACK)
                self._result = self.original_result
                self.status = "preserved"
            finally:
                action.elapsed_ms = (monotonic() - started) * 1000
                self._action_update(action, records)
        except (asyncio.CancelledError, ControlFlowException) as exc:
            self.status = "cancelled"
            self._interruption = exc
            raise

    def decide(self, label, *, state, questions, presentation=None):
        self._check_running()
        result = self._ownership.bridge(
            self.service.evaluate(
                label,
                state=state,
                questions=questions,
                invocation_id=self.id,
                template_uid=self.prompt.uid,
                source_group=self.source_group,
                ownership=self._ownership,
                presentation=presentation,
            )
        )
        self._ownership.check()
        if isinstance(result, Unavailable):
            raise PolicyUnavailable(result)
        self.handles[result.request_id] = result
        return result

    def _associated(self, association, *, allow_unassociated=False):
        if association is None and allow_unassociated:
            return []
        handles = (
            association if isinstance(association, (list, tuple)) else [association]
        )
        records = []
        for handle in handles:
            if (
                not isinstance(handle, DecisionHandle)
                or self.handles.get(handle.request_id) is not handle
            ):
                raise DecisionError(FailureCode.TEMPLATE)
            if handle.invocation_id != self.id:
                raise DecisionError(FailureCode.TEMPLATE)
            record = self.service.log.records[handle.request_id]
            if record not in records:
                records.append(record)
        if not records and not allow_unassociated:
            raise DecisionError(FailureCode.TEMPLATE)
        return records

    def _action_update(self, action, records):
        self.service.log.update_invocation(self.id)
        self.service.log.emit(
            "action",
            invocation_id=self.id,
            action=action.model_dump(mode="json"),
            request_ids=[record.id for record in records],
        )
        for record in records:
            self.service.log.update(record)

    def agent_action(self, agent_name, _action_name, *, _decision=None, **kwargs):
        self._check_running()
        records = self._associated(_decision, allow_unassociated=True)
        action = ActionRecord(action=f"{agent_name}.{_action_name}")
        self.action_trace.append(action)
        for record in records:
            record.actions.append(action)
        started = None
        try:
            spec = self.actions.get((agent_name, _action_name))
            denied = None
            if spec is None or not spec.enabled():
                denied = FailureCode.ACTION_DENIED
            elif (
                spec.budget is not None
                and self._budget_usage.get(id(spec.budget), 0) >= spec.budget.limit
            ):
                denied = FailureCode.BUDGET
            if denied:
                action.status = "skipped"
                action.failure = Failure.from_code(denied)
                raise PolicyActionError(denied, records)
            action.arguments = serialize_log_value(spec.serialize_arguments(kwargs))
            self._ownership.check()
            if spec.budget is not None:
                self._budget_usage[id(spec.budget)] = (
                    self._budget_usage.get(id(spec.budget), 0) + 1
                )
            self._action_started = True
            started = monotonic()
            self._action_update(action, records)
            value = self._ownership.bridge(spec.call(**kwargs))
            self._ownership.check()
            action.result = serialize_log_value(spec.serialize_result(value))
            action.status = "completed"
            return value
        except (asyncio.CancelledError, ControlFlowException):
            action.status = "cancelled"
            raise
        except Exception:
            if action.status == "skipped":
                raise
            action.status = "failed"
            action.failure = Failure.from_code(FailureCode.ACTION)
            raise PolicyActionError(FailureCode.ACTION, records) from None
        finally:
            if started is not None:
                action.elapsed_ms = (monotonic() - started) * 1000
            self._action_update(action, records)

    def decision_outcome(self, handle, action, *, reason=None, **details):
        self._check_running()
        if (
            not isinstance(action, str)
            or not action.strip()
            or (reason is not None and not isinstance(reason, str))
        ):
            raise DecisionError(FailureCode.TEMPLATE)
        for record in self._associated(handle):
            record.outcomes.append(
                {
                    "action": action,
                    "reason": reason or "reason unspecified",
                    "details": serialize_log_value(details),
                }
            )
            self.service.log.update(record)
        return ""

    def decision_result(self, value):
        self._check_running()
        if self._result_count:
            raise DecisionError(FailureCode.RESULT)
        try:
            self._result = self.validate_result(value)
        except (asyncio.CancelledError, ControlFlowException):
            raise
        except Exception:
            raise DecisionError(FailureCode.RESULT) from None
        self._result_count += 1
        return ""
