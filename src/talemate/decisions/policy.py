import asyncio
import copy
import inspect
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

from .budget import state_tokens
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
from .questions import (
    Answers,
    ChoiceResult,
    Choice,
    YesNo,
    YesNoAnswer,
    choice,
    plain,
    to_answer,
    yes_no,
)
from .service import DecisionHandle, DecisionService, Unavailable


T = TypeVar("T")
UNSET = object()


class ActionBudget(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    limit: int = Field(ge=0)


class PolicyAction(BaseModel):
    """
    An action a policy template may call by its helper name. `name` is the
    action as the Decision Log shows it, e.g. `gate.resolve`. The value the
    action returns is the invocation's result.
    """

    model_config = ConfigDict(frozen=True)

    name: str
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
        actions: Mapping[str, PolicyAction] | None = None,
        can_keep: bool = False,
        is_current: Callable[[], bool] = lambda: True,
    ):
        self.id = str(uuid4())
        self.prompt = Prompt.get(uid, variables)
        self.service = service
        self.validate_result = validate_result
        self.disabled_path = disabled_path
        self.original_result = validate_result(original_result)
        self.actions = dict(actions or {})
        self.can_keep = can_keep
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
            "ask": self.ask,
            "yes_no": yes_no,
            "choice": choice,
            "note": self.note,
            "agent_config": self.prompt.agent_config,
            "random_choice": random.choice,
            "len": len,
            "make_list": list,
            "make_dict": dict,
        }
        for name, spec in self.actions.items():
            helpers[name] = self._action_helper(spec)
        if self.can_keep:
            helpers["keep"] = self.keep
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

    def ask(self, label, *, state, questions, presentation=None) -> Answers:
        self._check_running()
        if not isinstance(questions, dict) or not all(
            isinstance(question, (YesNo, Choice)) for question in questions.values()
        ):
            raise DecisionError(FailureCode.TEMPLATE)
        engine_questions = {
            key: question.engine_question() for key, question in questions.items()
        }
        if callable(state):
            budget = self.service.state_budget(engine_questions)
            fitted = state(budget)
            if budget is not None and state_tokens(fitted) > budget:
                # the part of the state that cannot shrink does not fit beside
                # every question; the questions go out in parts, so give the
                # state the room one part leaves
                split = self.service.state_budget(engine_questions, split=True)
                if split != budget:
                    fitted = state(split)
            state = fitted
        result = self._ownership.bridge(
            self.service.evaluate(
                label,
                state=state,
                questions=engine_questions,
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
        return Answers(
            {
                key: to_answer(key, result.request_id, question, result.answers[key])
                for key, question in questions.items()
            }
        )

    def _records(self, answers=()):
        """
        The requests an outcome or action belongs to: those that produced the
        given answers, otherwise every request this invocation made.
        """
        if not answers:
            return [self.service.log.records[key] for key in self.handles]
        records = []
        for answer in answers:
            if (
                not isinstance(answer, (YesNoAnswer, ChoiceResult))
                or answer.request_id not in self.handles
            ):
                raise DecisionError(FailureCode.TEMPLATE)
            record = self.service.log.records[answer.request_id]
            if record not in records:
                records.append(record)
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

    def _action_helper(self, spec):
        def helper(*args, **kwargs):
            self._set_result(self._run_action(spec, args, kwargs))
            return ""

        return helper

    def _run_action(self, spec: PolicyAction, args, kwargs):
        self._check_running()
        try:
            arguments = inspect.signature(spec.call).bind(
                *plain(list(args)), **plain(kwargs)
            )
        except TypeError:
            raise DecisionError(FailureCode.TEMPLATE) from None
        records = self._records()
        action = ActionRecord(action=spec.name)
        self.action_trace.append(action)
        for record in records:
            record.actions.append(action)
        started = None
        try:
            denied = None
            if not spec.enabled():
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
            action.arguments = serialize_log_value(
                spec.serialize_arguments(dict(arguments.arguments))
            )
            self._ownership.check()
            if spec.budget is not None:
                self._budget_usage[id(spec.budget)] = (
                    self._budget_usage.get(id(spec.budget), 0) + 1
                )
            self._action_started = True
            started = monotonic()
            self._action_update(action, records)
            value = self._ownership.bridge(
                spec.call(*arguments.args, **arguments.kwargs)
            )
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

    def note(self, action, reason=None, *answers, **details):
        """
        Records why the template decided as it did. Each answer adds its
        probabilities and its threshold to the details, keyed by answer id
        where several answers share a detail; with no answers the note belongs
        to every request, or to the invocation when it made none.
        """
        self._check_running()
        if (
            not isinstance(action, str)
            or not action.strip()
            or (reason is not None and not isinstance(reason, str))
        ):
            raise DecisionError(FailureCode.TEMPLATE)
        records = self._records(answers)
        details = dict(details)
        measured: dict[str, dict] = {}
        thresholds = {}
        sources = {}
        for answer in answers:
            # a question id is unique within one request only
            if sources.setdefault(answer.id, answer.request_id) != answer.request_id:
                raise DecisionError(FailureCode.TEMPLATE)
            for key, value in answer.log_details().items():
                measured.setdefault(key, {})[answer.id] = value
            thresholds[answer.id] = answer.threshold
        for key, values in measured.items():
            if key in details:
                raise DecisionError(FailureCode.TEMPLATE)
            details[key] = next(iter(values.values())) if len(values) == 1 else values
        if thresholds:
            if "threshold" in details or "thresholds" in details:
                raise DecisionError(FailureCode.TEMPLATE)
            if len(set(thresholds.values())) == 1:
                details["threshold"] = next(iter(thresholds.values()))
            else:
                details["thresholds"] = thresholds
        outcome = {
            "action": action,
            "reason": reason or "reason unspecified",
            "details": serialize_log_value(details),
        }
        if not records:
            invocation = self.service.log.invocations[self.id]
            invocation.outcomes.append(outcome)
            self.service.log.update_invocation(self.id)
            return ""
        for record in records:
            record.outcomes.append(copy.deepcopy(outcome))
            self.service.log.update(record)
        return ""

    def keep(self):
        """The result is the caller's original one."""
        self._check_running()
        self._set_result(self.original_result)
        return ""

    def _set_result(self, value):
        if self._result_count:
            raise DecisionError(FailureCode.RESULT)
        try:
            self._result = self.validate_result(value)
        except (asyncio.CancelledError, ControlFlowException):
            raise
        except Exception:
            raise DecisionError(FailureCode.RESULT) from None
        self._result_count += 1
