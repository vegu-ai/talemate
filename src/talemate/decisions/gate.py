from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, RootModel, StrictBool, StrictStr

from talemate.prompts.base import send_outside_render

from .policy import ActionBudget, PolicyAction, PolicyInvocation
from .service import decision_service


class GateAnswers(RootModel[dict[str, StrictBool | StrictStr | None]]):
    pass


class DecisionGateResolved(BaseModel):
    """
    A decision gate settled its candidates. `decided` holds the answers the
    decision model gave; `fallback_ids` went to the usual request, which is
    every candidate when the gate was not enabled or the model failed.
    """

    uid: str
    gate_enabled: bool
    candidates: list[str]
    decided: dict[str, Any]
    fallback_ids: list[str]
    result: dict[str, Any]


async def _resolved(uid, gate_enabled, ids, fallback_ids, result):
    fallback = set(fallback_ids)
    await send_outside_render(
        "decision.gate.resolved",
        DecisionGateResolved(
            uid=uid,
            gate_enabled=gate_enabled,
            candidates=list(ids),
            decided={k: v for k, v in result.items() if k not in fallback},
            fallback_ids=list(dict.fromkeys(fallback_ids)),
            result=dict(result),
        ),
    )


def decision_gate_enabled(enabled: bool) -> bool:
    return bool(
        enabled
        and decision_service.enabled
        and decision_service.provider is not None
        and decision_service.provider.ready
    )


async def decision_gate(
    uid: str,
    *,
    enabled: bool,
    candidates: dict[str, list[bool | str]],
    variables: Callable[[], dict],
    fallback: Callable[[list[str]], Awaitable[dict]],
    accept: Callable[[bool | str], Any] = lambda value: value,
    is_current: Callable[[], bool] = lambda: True,
) -> dict:
    ids = list(candidates)
    if not ids:
        return {}
    if not decision_gate_enabled(enabled):
        result = await fallback(ids)
        await _resolved(uid, False, ids, ids, result)
        return result

    fallback_ids = []
    fallback_error = None
    original_result = {}
    resolved_result = None
    resolved_snapshot = {}
    fallback_result = None
    fallback_snapshot = {}

    def validate_result(value):
        # Only gate.resolve produces results; the copies keep later policy edits out.
        if value is original_result:
            return original_result.copy()
        if value is resolved_result and isinstance(value, dict):
            return resolved_snapshot.copy()
        if value is fallback_result and isinstance(value, dict):
            return fallback_snapshot.copy()
        raise ValueError("Gate results must come from gate.resolve")

    async def run_fallback(keys):
        nonlocal fallback_error, fallback_result, fallback_snapshot
        fallback_ids.extend(keys)
        try:
            fallback_result = await fallback(keys)
            fallback_snapshot = fallback_result.copy()
            return fallback_result
        except Exception as exc:
            # Policy recovery preserves results after an action starts; callers
            # must still receive failures from their original operation.
            fallback_error = exc
            raise

    async def resolve(answers=None, **kwargs):
        nonlocal resolved_result, resolved_snapshot
        try:
            if kwargs:
                raise ValueError("Unexpected gate arguments")
            routes = GateAnswers.model_validate(answers, strict=True).root
            if routes.keys() != candidates.keys() or any(
                value is not None
                and not any(
                    type(value) is type(option) and value == option
                    for option in candidates[key]
                )
                for key, value in routes.items()
            ):
                raise ValueError("Gate answers must use the declared candidates")
        except ValueError:
            result = await run_fallback(ids)
        else:
            unresolved = [key for key, value in routes.items() if value is None]
            result = await run_fallback(unresolved) if unresolved else {}
            result.update(
                {
                    key: accept(value)
                    for key, value in routes.items()
                    if value is not None
                }
            )
        resolved_snapshot = result.copy()
        invocation.original_result.update(resolved_snapshot)
        resolved_result = result
        return result

    async def disabled_path():
        return await run_fallback(ids)

    invocation = PolicyInvocation(
        uid,
        service=decision_service,
        variables=variables(),
        validate_result=validate_result,
        disabled_path=disabled_path,
        original_result=original_result,
        is_current=is_current,
        actions={
            "resolve": PolicyAction(
                name="gate.resolve",
                call=resolve,
                enabled=lambda: True,
                budget=ActionBudget(limit=1),
                serialize_result=lambda value: {
                    "fallback_ran": bool(fallback_ids),
                    "fallback_ids": fallback_ids,
                    "answers": value,
                },
            ),
        },
    )
    result = await invocation.run()
    if fallback_error is not None:
        raise fallback_error
    await _resolved(uid, True, ids, fallback_ids, result)
    return result
