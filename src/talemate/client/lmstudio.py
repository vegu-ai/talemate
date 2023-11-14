import asyncio
import os
import time
from typing import Callable

from openai import AsyncOpenAI

from talemate.client.registry import register
from talemate.client.textgenwebui import TextGeneratorWebuiClient, client_context_attribute, jiggle_enabled_for, jiggle_randomness
from talemate.emit import emit
from talemate.config import load_config
import talemate.client.system_prompts as system_prompts
import structlog
import os
import httpx
import json

__all__ = [
    "LMStudioClient",
]

log = structlog.get_logger("talemate")

PRESET_TALEMATE_CONVERSATION = {
    "temperature": 0.65,
    "top_p": 0.47,
    "top_k": 42,
    "repeat_penalty": 1.18,
}

PRESET_TALEMATE_CREATOR = {
    "temperature": 0.7,
    "top_p": 0.9,
    "repeat_penalty": 1.15,
    "top_k": 20,
}   
PRESET_DIVINE_INTELLECT = {
    "temperature": 1.31,
    "top_p": 0.14,
    "repeat_penalty": 1.17,
    "top_k": 49,
}

PRESET_SIMPLE_1 = {
    "temperature": 0.7,
    "top_p": 0.9,
    "repeat_penalty": 1.15,
    "top_k": 20,
}

PRESET_LLAMA_PRECISE = {
    'temperature': 0.7,
    'top_p': 0.1,
    'repeat_penalty': 1.18,
    'top_k': 40
}

@register()
class LMStudioClient(TextGeneratorWebuiClient):
    """
    LMStudio client for generating text.
    """

    client_type = "lmstudio"
    conversation_retries = 5
    
    def __str__(self):
        return f"LMStudioClient[{self.api_url_base}][{self.model_name or ''}]"
    
    @property
    def api_url_base(self):
        return self.api_url + "/v1"
    
    # Add the 'status' method
    async def status(self):
        """
        Send a request to the API to retrieve the loaded AI model name.
        Raises an error if no model name is returned.
        :return: None
        """
        if self.processing:
            return
        
        if not self.enabled:
            self.connected = False
            self.emit_status()
            return
        
        
        try:
            log.debug("lmstudio status", url=f"{self.api_url_base}/models")
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url_base}/models", timeout=2)
            
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
        ):
            self.model_name = None
            self.connected = False
            self.toggle_disabled_if_remote()
            self.emit_status()
            return

        self.connected = True
        
        try:
            response_data = response.json()
            self.enabled = True
        except json.decoder.JSONDecodeError as e:
            self.connected = False
            self.toggle_disabled_if_remote()
            if not self.enabled:
                log.warn("remote service unreachable, disabling client", name=self.name)
            else:
                log.error("client response error", name=self.name, e=e)
                
            self.emit_status()
            return

        model_list = response_data.get("data", [])
        if model_list:
            model_id = model_list[0]["id"]
            # modelname is file name parsed from model_id which is a file path
            # where path might come from a windows system or a linux system so both
            # forward and backward slashes are possible
            model_name = model_id.split("/")[-1].split("\\")[-1]
        else:
            model_name = None
        
        if not model_name or model_name == "None":
            log.warning("client model not loaded", client=self.name)
            self.emit_status()
            return

        model_changed = model_name != self.model_name

        self.model_name = model_name

        if model_changed:
            self.auto_context_length()

            log.info(f"{self} [{self.max_token_length} ctx]: ready")
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
        
        client = AsyncOpenAI(base_url=self.api_url_base)
        
        right = ""
        fn_prompt_config = getattr(self, f"prompt_config_{kind}")
        _opts = fn_prompt_config(prompt)
        
        prompt = _opts["prompt"]
        
        if client_context_attribute("nuke_repetition") > 0.0 and jiggle_enabled_for(kind):
            log.info("nuke repetition", offset=client_context_attribute("nuke_repetition"), temperature=_opts["temperature"], repetition_penalty=_opts["repetition_penalty"])
            _opts = jiggle_randomness(_opts, offset=client_context_attribute("nuke_repetition"))
            log.info("nuke repetition (applied)", offset=client_context_attribute("nuke_repetition"), temperature=_opts["temperature"], repetition_penalty=_opts["repetition_penalty"])
        
        
        valid_options = ["temperature", "top_p"]
        
        opts = {k: v for k, v in _opts.items() if k in valid_options}
        
        if "max_new_tokens" in _opts:
            opts["max_tokens"] = _opts["max_new_tokens"]
        
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>",  "\nContinue this response: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")
                
        self.emit_status(processing=True)

        sys_message = {'role': 'system', 'content': self.get_system_message(kind)}
        
        human_message = {'role': 'user', 'content': prompt}

        log.debug("lmstudio send", kind=kind, sys_message=sys_message, opts=opts)

        time_start = time.time()
        
        response = await client.chat.completions.create(model=self.model_name, messages=[sys_message, human_message], timeout=1000, **opts)
        
        time_end = time.time()
        
        response = response.choices[0].message.content
        
        if right and response.startswith(right):
            response = response[len(right):].strip()

        stopping_strings = ["<|im_end|>", "</s>"]
        for stopping_string in stopping_strings:
            if stopping_string in response:
                response = response.split(stopping_string)[0].strip()
                break

        log.debug("lmstudio response", response=response)

        emit("prompt_sent", data={
            "kind": kind,
            "prompt": prompt,
            "response": response,
            "prompt_tokens": "?",
            "response_tokens": "?",
            "time": time_end - time_start,
        })

        self.emit_status(processing=False)
        return response
