import asyncio
import os
from typing import Callable

from langchain.chat_models import ChatOpenAI
from langchain.schema import AIMessage, HumanMessage, SystemMessage

from talemate.client.registry import register
from talemate.emit import emit
from talemate.config import load_config
import talemate.client.system_prompts as system_prompts
import structlog

__all__ = [
    "OpenAIClient",
]

log = structlog.get_logger("talemate")

@register()
class OpenAIClient:
    """
    OpenAI client for generating text.
    """

    client_type = "openai"
    conversation_retries = 0

    def __init__(self, model="gpt-3.5-turbo", **kwargs):
        self.name = kwargs.get("name", "openai")
        self.model_name = model
        self.last_token_length = 0
        self.max_token_length = 2048
        self.processing = False
        self.current_status = "idle"
        self.config = load_config()
        
        # if os.environ.get("OPENAI_API_KEY") is not set, look in the config file
        # and set it
        
        if not os.environ.get("OPENAI_API_KEY"):
            if self.config.get("openai", {}).get("api_key"):
                os.environ["OPENAI_API_KEY"] = self.config["openai"]["api_key"]

        self.set_client(model)


    @property
    def openai_api_key(self):
        return os.environ.get("OPENAI_API_KEY")


    def emit_status(self, processing: bool = None):
        if processing is not None:
            self.processing = processing

        if os.environ.get("OPENAI_API_KEY"):
            status = "busy" if self.processing else "idle"
            model_name = self.model_name or "No model loaded"
        else:
            status = "error"
            model_name = "No API key set"
            
        self.current_status = status

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status,
        )

    def set_client(self, model:str, max_token_length:int=None):

        if not self.openai_api_key:
            log.error("No OpenAI API key set")
            return
        
        self.chat = ChatOpenAI(model=model, verbose=True)
        if model == "gpt-3.5-turbo":
            self.max_token_length = min(max_token_length or 4096, 4096)
        elif model == "gpt-4":
            self.max_token_length = min(max_token_length or 8192, 8192)
        elif model == "gpt-3.5-turbo-16k":
            self.max_token_length = min(max_token_length or 16384, 16384)
        else:
            self.max_token_length = max_token_length or 2048

    def reconfigure(self, **kwargs):
        if "model" in kwargs:
            self.model_name = kwargs["model"]
            self.set_client(self.model_name, kwargs.get("max_token_length"))

    async def status(self):
        self.emit_status()

    def get_system_message(self, kind: str) -> str:
       
       if kind in ["narrate", "story"]:
           return system_prompts.NARRATOR
       if kind == "director":
           return system_prompts.DIRECTOR
       if kind in ["create", "creator"]:
           return system_prompts.CREATOR
       if kind in ["roleplay", "conversation"]:
           return system_prompts.ROLEPLAY
       return system_prompts.BASIC
                  
    async def send_prompt(
        self, prompt: str, kind: str = "conversation", finalize: Callable = lambda x: x
    ) -> str:
        
        right = ""
        
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>",  "\nContinue this response: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")
                
        self.emit_status(processing=True)
        await asyncio.sleep(0.1)

        sys_message = SystemMessage(content=self.get_system_message(kind))
        
        human_message = HumanMessage(content=prompt)

        log.debug("openai send", kind=kind, sys_message=sys_message)

        response = self.chat([sys_message, human_message])
        
        response = response.content
        
        if right and response.startswith(right):
            response = response[len(right):].strip()
            
        if kind == "conversation":
            response = response.replace("\n", " ").strip()

        log.debug("openai response", response=response)

        emit("prompt_sent", data={
            "kind": kind,
            "prompt": prompt,
            "response": response,
            # TODO use tiktoken
            "prompt_tokens": 0,
            "response_tokens": 0,
        })

        self.emit_status(processing=False)
        return response
