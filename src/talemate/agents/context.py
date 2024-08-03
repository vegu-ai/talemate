import contextvars
import uuid
from typing import TYPE_CHECKING, Callable

import pydantic

__all__ = [
    "active_agent",
]

active_agent = contextvars.ContextVar("active_agent", default=None)


class ActiveAgentContext(pydantic.BaseModel):
    agent: object
    fn: Callable
    agent_stack: list = pydantic.Field(default_factory=list)
    agent_stack_uid: str | None = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def action(self):
        return self.fn.__name__

    def __str__(self):
        return f"{self.agent.verbose_name}.{self.action}"


class ActiveAgent:
    def __init__(self, agent, fn):
        self.agent = ActiveAgentContext(agent=agent, fn=fn)

    def __enter__(self):

        previous_agent = active_agent.get()

        if previous_agent:
            self.agent.agent_stack = previous_agent.agent_stack + [str(self.agent)]
            self.agent.agent_stack_uid = previous_agent.agent_stack_uid
        else:
            self.agent.agent_stack = [str(self.agent)]
            self.agent.agent_stack_uid = str(uuid.uuid4())

        self.token = active_agent.set(self.agent)

    def __exit__(self, *args, **kwargs):
        active_agent.reset(self.token)
        return False
