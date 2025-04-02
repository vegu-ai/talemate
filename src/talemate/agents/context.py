import contextvars
import uuid
import hashlib
from typing import TYPE_CHECKING, Callable

import pydantic

if TYPE_CHECKING:
    from talemate.tale_mate import Character

__all__ = [
    "active_agent",
]

active_agent = contextvars.ContextVar("active_agent", default=None)


class ActiveAgentContext(pydantic.BaseModel):
    agent: object
    fn: Callable
    fn_args: tuple = pydantic.Field(default_factory=tuple)
    fn_kwargs: dict = pydantic.Field(default_factory=dict)
    agent_stack: list = pydantic.Field(default_factory=list)
    agent_stack_uid: str | None = None
    state: dict = pydantic.Field(default_factory=dict)
    state_params: dict = pydantic.Field(default_factory=dict)
    previous: "ActiveAgentContext" = None
    

    class Config:
        arbitrary_types_allowed = True

    @property
    def first(self):
        return self.previous.first if self.previous else self

    @property
    def action(self):    
        name = self.fn.__name__
        if name == "delegate":
            return self.fn_args[0].__name__
        return name
    
    @property
    def fingerprint(self) -> int:
        if hasattr(self, "_fingerprint"):
            return self._fingerprint
        self._fingerprint = hash(frozenset(self.state_params.items()))
        return self._fingerprint
    
    def __str__(self):
        return f"{self.agent.verbose_name}.{self.action}"
    

class ActiveAgent:
    def __init__(self, agent, fn, args=None, kwargs=None):
        self.agent = ActiveAgentContext(agent=agent, fn=fn, fn_args=args or tuple(), fn_kwargs=kwargs or {})

    def __enter__(self):

        previous_agent = active_agent.get()

        if previous_agent:
            self.agent.agent_stack = previous_agent.agent_stack + [str(self.agent)]
            self.agent.agent_stack_uid = previous_agent.agent_stack_uid
            self.agent.state = previous_agent.state
            self.agent.previous = previous_agent
        else:
            self.agent.agent_stack = [str(self.agent)]
            self.agent.agent_stack_uid = str(uuid.uuid4())

        self.token = active_agent.set(self.agent)
        
        return self.agent

    def __exit__(self, *args, **kwargs):
        active_agent.reset(self.token)
        return False
