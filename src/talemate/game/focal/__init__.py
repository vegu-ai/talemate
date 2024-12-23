"""
FOCAL (Function Orchestration and Creative Argument Layer) separates structured function execution from creative text generation in AI prompts. It first generates function calls with placeholders, then fills these with creative content in a separate phase, and finally combines them into python function calls.

Talemate uses these for tasks where a structured function call is needed with creative content, such as in the case of generating a story, characters or dialogue.

This does NOT use API specific function calling (like openai or anthropic), but rather builds its own set of instructions,
so opensource and private APIs can be used interchangeably.

Function Orchestration:

The AI will be given instructions to call functions using a strict JSON schema.

Creative argument injection:

The AI will be given instructions to fill in the arguments of the functions with creative content. This is done
on a separate phase to SEPARATE the structured function call from the creative content.
"""

import structlog

from talemate.client.base import ClientBase
from talemate.prompts.base import Prompt

from .schema import Argument, Callback, State

__all__ = [
    "Argument",
    "Callback",
    "Focal",
]

log = structlog.get_logger("talemate.game.focal")

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
            "create",
            vars={
                **self.context, 
                "focal": self,
                "max_tokens":self.client.max_token_length
            }
        )
        
        log.debug("focal.request", template_name=template_name, context=self.context, response=response)
        
        await self._execute(response, State())
        
        return response
    
    async def _execute(self, response: str, state: State):
        """
        Execute callbacks found in the response text.
        
        Args:
            response (str): The text containing callback instructions
            state (State): State object containing delimiter and prefix/suffix settings
        """
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
                if len(args) != len(callback.arguments):
                    log.warning(
                        "focal.execute.argument_count_mismatch",
                        expected=len(callback.arguments),
                        received=len(args)
                    )
                    continue
                
                # Execute the callback
                try:
                    callback.fn(*args)
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
            

        