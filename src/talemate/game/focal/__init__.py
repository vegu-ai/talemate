"""
FOCAL (Function Orchestration and Creative Argument Layer) separates structured function execution from creative text generation in AI prompts. It first generates function calls with placeholders, then fills these with creative content in a separate phase, and finally combines them into python function calls.

Talemate uses these for tasks where a structured function call is needed with creative content, such as in the case of generating a story, characters or dialogue.

This does NOT use API specific function calling (like openai or anthropic), but rather builds its own set of instructions, so opensource and private APIs can be used interchangeably (in theory).
"""

import structlog
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
    "current_focal_context",
]

log = structlog.get_logger("talemate.game.focal")

current_focal_context = ContextVar("current_focal_context", default=None)

class FocalContext:
    def __init__(self):
        self.hooks_before_call = []
        self.hooks_after_call = []
        
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
        **kwargs
    ):
        self.client = client
        self.context = kwargs
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
                "max_tokens":self.client.max_token_length
            },
            dedupe_enabled=False,
        )
        
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
        
        for call in calls:
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
        )

        calls = [Call(**call) for call in calls_json.get("calls", [])]
        
        log.debug("focal.extract", calls=calls)
        
        return calls
    
    async def _execute_old(self, response: str, state: State):
        """
        Execute callbacks found in the response text.
        
        Args:
            response (str): The text containing callback instructions
            state (State): State object containing delimiter and prefix/suffix settings
        """
        
        focal_context = current_focal_context.get()
        
        # Continue processing until we don't find any more callback sections
        while True:
            # Find the next callback section
            start = response.find(state.callback_prefix)
            if start == -1:
                break
                
            # Find the end of the callback section
            end = response.find(state.callback_suffix, start)
            if end == -1:
                log.warning("focal.execute.missing_suffix", start_pos=start)
                break
                
            # Extract the callback instruction (excluding prefix/suffix)
            callback_text = response[start + len(state.callback_prefix):end].strip()
            
            # Parse the callback instruction
            try:
                # Split into name and arguments
                callback_parts = callback_text.split(':', 1)
                if len(callback_parts) != 2:
                    log.warning("focal.execute.invalid_format", text=callback_text)
                    continue
                    
                callback_name, args_text = callback_parts
                callback_name = callback_name.strip().lower().replace(" ", "_")
                
                # Get the callback handler
                if callback_name not in self.callbacks:
                    log.warning("focal.execute.unknown_callback", name=callback_name)
                    continue
                    
                callback = self.callbacks[callback_name]
                
                # Parse arguments
                args = [arg.strip() for arg in args_text.split(state.argument_delimiter)]
                
                # Validate argument count
                if len(args) < len(callback.arguments):
                    log.warning(
                        "focal.execute.argument_count_mismatch",
                        expected=len(callback.arguments),
                        received=len(args)
                    )
                    continue
                
                # Execute the callback
                try:
                    args = args[:len(callback.arguments)]
                    
                    # make an arg dict based on order
                    arg_objects = {}
                    for i, arg in enumerate(args):
                        arg_objects[callback.arguments[i].name] = arg
                    
                    call = Call(name=callback_name, arguments=arg_objects)
                    
                    # if we have a focal context, process additional hooks (before call)
                    if focal_context:
                        await focal_context.process_hooks(call)
                                            
                    result = await callback.fn(*args)
                    call.result = result
                    call.called = True
                    
                    self.state.calls.append(call)
                    
                    # if we have a focal context, process additional hooks (after call)
                    if focal_context:
                        await focal_context.process_hooks(call)
                    
                except Exception as e:
                    log.error(
                        "focal.execute.callback_error",
                        callback=callback_name,
                        error=str(e)
                    )
                    
            except Exception as e:
                log.error("focal.execute.parse_error", error=str(e))
            finally:
                # Move past this callback section
                response = response[end + len(state.callback_suffix):]
            

        