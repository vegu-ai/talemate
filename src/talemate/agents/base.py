from __future__ import annotations

import asyncio
import re
from abc import ABC
from typing import TYPE_CHECKING, Callable, List, Optional, Union

from blinker import signal

import talemate.instance as instance
import talemate.util as util
from talemate.emit import emit
import dataclasses

__all__ = [
    "Agent",
    "set_processing",
]

def set_processing(fn):
    """
    decorator that emits the agent status as processing while the function
    is running.
    
    Done via a try - final block to ensure the status is reset even if
    the function fails.
    """
    
    async def wrapper(self, *args, **kwargs):
        try:
            await self.emit_status(processing=True)
            return await fn(self, *args, **kwargs)
        finally:
            await self.emit_status(processing=False)
            
    wrapper.__name__ = fn.__name__
            
    return wrapper


class Agent(ABC):
    """
    Base agent class, defines a role
    """

    agent_type = "agent"
    verbose_name = None
    
    set_processing = set_processing

    @property
    def agent_details(self):
        if hasattr(self, "client"):
            if self.client:
                return self.client.name
        return None

    @property
    def verbose_name(self):
        return self.agent_type.capitalize()

    @classmethod
    def config_options(cls):
        return {
            "client": [name for name, _ in instance.client_instances()],
        }

    @property
    def ready(self):
        if not getattr(self.client, "enabled", True):
            return False
        
        
        if self.client.current_status in ["error", "warning"]:
            return False
        
        return self.client is not None

    @property
    def status(self):
        if self.ready:
            return "idle" if getattr(self, "processing", 0) == 0 else "busy"
        else:
            return "uninitialized"

    async def emit_status(self, processing: bool = None):
        
        # should keep a count of processing requests, and when the
        # number is 0 status is "idle", if the number is greater than 0
        # status is "busy"
        #
        # increase / decrease based on value of `processing`
        
        if getattr(self, "processing", None) is None:
            self.processing = 0
            
        if not processing:
            self.processing -= 1
            self.processing = max(0, self.processing)
        else:
            self.processing += 1
            
        status = "busy" if self.processing > 0 else "idle"
        
        emit(
            "agent_status",
            message=self.verbose_name or "",
            id=self.agent_type,
            status=status,
            details=self.agent_details,
            data=self.config_options(),
        )

        await asyncio.sleep(0.01)

    def connect(self, scene):
        self.scene = scene

    def clean_result(self, result):
        if "#" in result:
            result = result.split("#")[0]

        # Removes partial sentence at the end
        result = re.sub(r"[^\.\?\!]+(\n|$)", "", result)
        result = result.strip()

        if ":" in result:
            result = result.split(":")[1].strip()

        return result

    async def get_history_memory_context(
        self,
        memory_history_context_max: int,
        memory_context_max: int,
        exclude: list = [],
        exclude_fn: Callable = None,
    ):
        current_memory_context = []
        memory_helper = self.scene.get_helper("memory")
        if memory_helper:
            history_messages = "\n".join(
                self.scene.recent_history(memory_history_context_max)
            )
            memory_tokens = 0
            for memory in await memory_helper.agent.get(history_messages):
                if memory in exclude:
                    continue

                if exclude_fn:
                    for split in memory.split("\n"):
                        if exclude_fn(split):
                            continue

                memory_tokens += util.count_tokens(memory)

                if memory_tokens > memory_context_max:
                    break

                current_memory_context.append(memory)
        return current_memory_context

@dataclasses.dataclass
class AgentEmission:
    agent: Agent