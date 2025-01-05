"""
FOCAL (Function Orchestration and Creative Argument Layer) separates structured function execution from creative text generation in AI prompts. It first generates function calls with placeholders, then fills these with creative content in a separate phase, and finally combines them into python function calls.

Talemate uses these for tasks where a structured function call is needed with creative content, such as in the case of generating a story, characters or dialogue.

This does NOT use API specific function calling (like openai or anthropic), but rather builds its own set of instructions, so opensource and private APIs can be used interchangeably (in theory).
"""

import structlog
from typing import Callable
from contextvars import ContextVar

from talemate.client.base import ClientBase
from talemate.prompts.base import Prompt

from .schema import Argument, Call, Callback, State

__all__ = [
    "Argument",
    "Call",
    "Callback",
    "Focal",
    "FocalContext",
    "collect_calls",
    "current_focal_context",
]

log = structlog.get_logger("talemate.game.focal")

current_focal_context = ContextVar("current_focal_context", default=None)

class FocalContext:
    def __init__(self):
        self.hooks_before_call = []
        self.hooks_after_call = []
        self.value = {}
        
    def __enter__(self):
        self.token = current_focal_context.set(self)
        return self
    
    def __exit__(self, *args):
        current_focal_context.reset(self.token)
        
    async def process_hooks(self, call:Call):
        for hook in self.hooks_after_call:
            await hook(call)

class Focal:
    
    def __init__(
        self, 
        client: ClientBase,
        callbacks: list[Callback],
        max_calls: int = 5,
        **kwargs
    ):
        self.client = client
        self.context = kwargs
        self.max_calls = max_calls
        self.state = State()
        self.callbacks = {
            callback.name: callback
            for callback in callbacks
        }
        
        # set state on each callback
        for callback in self.callbacks.values():
            callback.state = self.state
        
    def render_instructions(self) -> str:
        prompt = Prompt.get(
            "focal.instructions",
            {
                "max_calls": self.max_calls,
                "state": self.state,
            }
        )
        return prompt.render()
        
    async def request(
        self,
        template_name: str,
    ) -> str:
        
        log.debug("focal.request", template_name=template_name, callbacks=self.callbacks)
        
        response = await Prompt.request(
            template_name,
            self.client,
            "analyze_long",
            vars={
                **self.context, 
                "focal": self,
                "max_tokens":self.client.max_token_length,
                "max_calls": self.max_calls,
            },
            dedupe_enabled=False,
        )
        
        if not response.strip():
            log.warning("focal.request.empty_response")
            return response
        
        log.debug("focal.request", template_name=template_name, context=self.context, response=response)
        
        await self._execute(response, State())
        
        return response
    
    async def _execute(self, response: str, state: State):
        try:
            calls: list[Call] = await self._extract(response)
        except Exception as e:
            log.error("focal.extract_error", error=str(e))
            return
        
        focal_context = current_focal_context.get()
        
        calls_made = 0
        
        for call in calls:
            
            if calls_made >= self.max_calls:
                log.warning("focal.execute.max_calls_reached", max_calls=self.max_calls)
                break
            
            if call.name not in self.callbacks:
                log.warning("focal.execute.unknown_callback", name=call.name)
                continue
                
            callback = self.callbacks[call.name]
            
            try:
                
                # if we have a focal context, process additional hooks (before call)
                if focal_context:
                    await focal_context.process_hooks(call)
                
                result = await callback.fn(**call.arguments)
                call.result = result
                call.called = True
                calls_made += 1
                
                # if we have a focal context, process additional hooks (after call)
                if focal_context:
                    await focal_context.process_hooks(call)
                
            except Exception as e:
                log.error(
                    "focal.execute.callback_error",
                    callback=call.name,
                    error=str(e)
                )
                
            self.state.calls.append(call)
    
    async def _extract(self, response:str) -> list[Call]:
        _, calls_json = await Prompt.request(
            "focal.extract_calls",
            self.client,
            "analyze_long",
            vars={
                **self.context,
                "text": response,
                "focal": self,
                "max_tokens": self.client.max_token_length,
            },
            dedupe_enabled=False,
        )

        calls = [Call(**call) for call in calls_json.get("calls", [])]
        
        log.debug("focal.extract", calls=calls)
        
        return calls
    
    
def collect_calls(calls:list[Call], nested:bool=False, filter: Callable=None) -> list:
    
    """
    Takes a list of calls and collects into a list.
    
    If nested is True and call result is a list of calls, it will also collect those.
    
    If a filter function is provided, it will be used to filter the results.
    """
    
    results = []
    
    for call in calls:
        
        result_is_list_of_calls = isinstance(call.result, list) and all([isinstance(result, Call) for result in call.result])
        
        # we need to filter the results
        # but if nested is True, we need to collect nested results regardless
        
        if not filter or filter(call):
            results.append(call)
            
        if nested and result_is_list_of_calls:
            results.extend(collect_calls(call.result, nested=True, filter=filter))
        
    
    return results