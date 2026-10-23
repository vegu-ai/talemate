"""
Agent actions learned from the requests they sent, keyed the way
``config.agent_actions.overrides`` keys them (``{agent_type}.{action}``).
"""

import inspect

import pydantic

import talemate.instance as instance
from talemate.emit import emit

__all__ = ["ObservedAgentAction", "record_context", "snapshot", "reset"]


class ObservedAgentAction(pydantic.BaseModel):
    key: str
    agent_type: str
    action: str
    client_name: str | None = None
    # the agent whose context sent the request — another agent's when the
    # action delegates, which is the client the override then reaches
    served_by: str | None = None
    description: str | None = None


_observed: dict[str, ObservedAgentAction] = {}


def action_description(agent_type: str, action: str) -> str | None:
    try:
        agent = instance.get_agent(agent_type)
    except KeyError:
        return None

    fn = getattr(agent, action, None)
    if not callable(fn):
        return None

    doc = inspect.getdoc(fn)
    if not doc:
        return None

    return " ".join(doc.split("\n\n")[0].split()) or None


def _touch(
    agent_type: str, action: str, client_name: str | None, served_by: str
) -> bool:
    """Returns True when the entry is new or its client / server changed."""
    key = f"{agent_type}.{action}"
    entry = _observed.get(key)

    if entry is None:
        _observed[key] = ObservedAgentAction(
            key=key,
            agent_type=agent_type,
            action=action,
            client_name=client_name,
            served_by=served_by,
            description=action_description(agent_type, action),
        )
        return True

    changed = (entry.client_name, entry.served_by) != (client_name, served_by)
    entry.client_name = client_name
    entry.served_by = served_by
    return changed


def record_context(agent_context, client_name: str | None) -> list[str]:
    """Learn the whole action chain behind a request, outermost included.

    The innermost action sends the request, but an override on an outer
    action reaches it too, so the outer action must be learnable as well.
    """
    changed_keys: list[str] = []
    served_by = agent_context.agent.agent_type if agent_context else None
    context = agent_context
    while context is not None:
        agent_type = context.agent.agent_type
        if _touch(agent_type, context.action, client_name, served_by):
            changed_keys.append(f"{agent_type}.{context.action}")
        context = context.previous

    if changed_keys:
        emit("agent_actions_observed", data={"actions": snapshot()})
    return changed_keys


def snapshot() -> list[dict]:
    return [_observed[key].model_dump() for key in sorted(_observed)]


def reset():
    _observed.clear()
