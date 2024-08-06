"""
Context manager that collects and tracks memory agent requests 
for profiling and debugging purposes
"""

import contextvars
import pydantic
import structlog
import time

from talemate.emit import emit
from talemate.agents.context import active_agent

__all__ =  [
    "MemoryRequest",
    "start_memory_request"
    "MemoryRequestState"
    "memory_request"
]

log = structlog.get_logger()

DEBUG_MEMORY_REQUESTS = False

class MemoryRequestResult(pydantic.BaseModel):
    doc: str
    distance: float
    meta: dict = pydantic.Field(default_factory=dict)
    
class MemoryRequestState(pydantic.BaseModel):
    query:str
    results: list[MemoryRequestResult] = pydantic.Field(default_factory=list)
    accepted_results: list[MemoryRequestResult] = pydantic.Field(default_factory=list)
    query_params: dict = pydantic.Field(default_factory=dict)
    closest_distance: float | None = None
    furthest_distance: float | None = None
    max_distance: float | None = None
    
    def add_result(self, doc:str, distance:float, meta:dict):
        self.results.append(MemoryRequestResult(doc=doc, distance=distance, meta=meta))
        self.closest_distance = min(self.closest_distance, distance) if self.closest_distance is not None else distance
        self.furthest_distance = max(self.furthest_distance, distance) if self.furthest_distance is not None else distance
        
    def accept_result(self, doc:str, distance:float, meta:dict):
        self.accepted_results.append(MemoryRequestResult(doc=doc, distance=distance, meta=meta))
        
    @property
    def closest_text(self):
        return str(self.results[0].doc) if self.results else None
    
memory_request = contextvars.ContextVar("memory_request", default=None)


class MemoryRequest:
    
    def __init__(self, query:str, query_params:dict=None):
        self.query = query
        self.query_params = query_params
    
    def __enter__(self):
        self.state = MemoryRequestState(query=self.query, query_params=self.query_params)
        self.token = memory_request.set(self.state)
        self.time_start = time.time()
        return self.state
        
    def __exit__(self, *args):
        
        self.time_end = time.time()
        
        if DEBUG_MEMORY_REQUESTS:
            max_length = 50
            query = self.state.query[:max_length]+"..." if len(self.state.query) > max_length else self.state.query
            log.debug("MemoryRequest", number_of_results=len(self.state.results), query=query)
            log.debug("MemoryRequest", number_of_accepted_results=len(self.state.accepted_results), query=query)
            
            for result in self.state.results:
                # distance to 2 decimal places
                log.debug("MemoryRequest RESULT", distance=f"{result.distance:.2f}", doc=result.doc[:max_length]+"...")
                
        agent_context = active_agent.get()
                
        emit("memory_request", data=self.state.model_dump(), meta={
            "agent_stack": agent_context.agent_stack if agent_context else [],
            "agent_stack_uid": agent_context.agent_stack_uid if agent_context else None,
            "duration": self.time_end - self.time_start,
            }, websocket_passthrough=True)
        
        memory_request.reset(self.token)
        return False
    

# decorator that opens a memory request context
async def start_memory_request(query):
    async def decorator(fn):
        async def wrapper(*args, **kwargs):
            with MemoryRequest(query):
                return await fn(*args, **kwargs)
        return wrapper
    return decorator