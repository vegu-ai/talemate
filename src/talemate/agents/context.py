
from typing import Callable, TYPE_CHECKING
import contextvars
import pydantic

__all__ = [
    "active_agent",
]

active_agent = contextvars.ContextVar("active_agent", default=None)

class ActiveAgentContext(pydantic.BaseModel):
    agent: object
    fn: Callable
    
    class Config:
        arbitrary_types_allowed=True
        
    @property
    def action(self):
        return self.fn.__name__

class ActiveAgent:
    
    def __init__(self, agent, fn):
        self.agent = ActiveAgentContext(agent=agent, fn=fn)
    
    def __enter__(self):
        self.token = active_agent.set(self.agent)
    
    def __exit__(self, *args, **kwargs):
        active_agent.reset(self.token)
        return False
