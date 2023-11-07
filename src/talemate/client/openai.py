import asyncio
import os
from typing import Callable

from openai import AsyncOpenAI

from talemate.client.registry import register
from talemate.emit import emit
from talemate.config import load_config
import talemate.client.system_prompts as system_prompts
import structlog
import tiktoken

__all__ = [
    "OpenAIClient",
]

log = structlog.get_logger("talemate")

def num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613"):
    """Return the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model in {
        "gpt-3.5-turbo-0613",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
        "gpt-4-1106-preview",
    }:
        tokens_per_message = 3
        tokens_per_name = 1
    elif model == "gpt-3.5-turbo-0301":
        tokens_per_message = (
            4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        )
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif "gpt-3.5-turbo" in model:
        print(
            "Warning: gpt-3.5-turbo may update over time. Returning num tokens assuming gpt-3.5-turbo-0613."
        )
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613")
    elif "gpt-4" in model:
        print(
            "Warning: gpt-4 may update over time. Returning num tokens assuming gpt-4-0613."
        )
        return num_tokens_from_messages(messages, model="gpt-4-0613")
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            if value is None:
                continue
            if isinstance(value, dict):
                value = json.dumps(value)
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens

@register()
class OpenAIClient:
    """
    OpenAI client for generating text.
    """

    client_type = "openai"
    conversation_retries = 0

    def __init__(self, model="gpt-4-1106-preview", **kwargs):
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
        
        self.client = AsyncOpenAI()
        if model == "gpt-3.5-turbo":
            self.max_token_length = min(max_token_length or 4096, 4096)
        elif model == "gpt-4":
            self.max_token_length = min(max_token_length or 8192, 8192)
        elif model == "gpt-3.5-turbo-16k":
            self.max_token_length = min(max_token_length or 16384, 16384)
        elif model == "gpt-4-1106-preview":
            self.max_token_length = min(max_token_length or 128000, 128000)
        else:
            self.max_token_length = max_token_length or 2048
            
    def reconfigure(self, **kwargs):
        if "model" in kwargs:
            self.model_name = kwargs["model"]
            self.set_client(self.model_name, kwargs.get("max_token_length"))

    async def status(self):
        self.emit_status()

    def get_system_message(self, kind: str) -> str:
       
        if "narrate" in kind:
            return system_prompts.NARRATOR
        if "story" in kind:
            return system_prompts.NARRATOR
        if "director" in kind:
            return system_prompts.DIRECTOR
        if "create" in kind:
            return system_prompts.CREATOR
        if "roleplay" in kind:
            return system_prompts.ROLEPLAY
        if "conversation" in kind:
            return system_prompts.ROLEPLAY
        if "editor" in kind:
            return system_prompts.EDITOR
        if "world_state" in kind:
            return system_prompts.WORLD_STATE
        if "analyst" in kind:
            return system_prompts.ANALYST
        if "analyze" in kind:
            return system_prompts.ANALYST
       
        return system_prompts.BASIC
                  
    async def send_prompt(
        self, prompt: str, kind: str = "conversation", finalize: Callable = lambda x: x
    ) -> str:
        
        right = ""
        opts = {}
        
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>",  "\nContinue this response: ")
                expected_response = prompt.split("\nContinue this response: ")[1].strip()
                if expected_response.startswith("{"):
                    opts["response_format"] = {"type": "json_object"}
            else:
                prompt = prompt.replace("<|BOT|>", "")
                
        self.emit_status(processing=True)
        await asyncio.sleep(0.1)

        sys_message = {'role': 'system', 'content': self.get_system_message(kind)}
        
        human_message = {'role': 'user', 'content': prompt}

        log.debug("openai send", kind=kind, sys_message=sys_message, opts=opts)

        response = await self.client.chat.completions.create(model=self.model_name, messages=[sys_message, human_message], **opts)
        
        response = response.choices[0].message.content
        
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
            "prompt_tokens": num_tokens_from_messages([sys_message, human_message], model=self.model_name),
            "response_tokens": num_tokens_from_messages([{"role": "assistant", "content": response}], model=self.model_name),
        })

        self.emit_status(processing=False)
        return response
