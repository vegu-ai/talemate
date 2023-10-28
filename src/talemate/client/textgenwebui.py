import asyncio
import random
import json
import copy
import structlog
import httpx
from abc import ABC, abstractmethod
from typing import Callable, Union
import logging
import talemate.util as util
from talemate.client.registry import register
import talemate.client.system_prompts as system_prompts
from talemate.emit import Emission, emit
from talemate.client.context import client_context_attribute
from talemate.client.model_prompts import model_prompt

import talemate.instance as instance

log = structlog.get_logger(__name__)

__all__ = [
    "TaleMateClient",
    "RestApiTaleMateClient",
    "TextGeneratorWebuiClient",
]

# Set up logging level for httpx to WARNING to suppress debug logs.
logging.getLogger('httpx').setLevel(logging.WARNING)

class DefaultContext(int):
    pass


PRESET_TALEMATE_LEGACY = {
    "temperature": 0.72,
    "top_p": 0.73,
    "top_k": 0,
    "top_a": 0,
    "repetition_penalty": 1.18,
    "repetition_penalty_range": 2048,
    "encoder_repetition_penalty": 1,
    #"encoder_repetition_penalty": 1.2,
    #"no_repeat_ngram_size": 2,
    "do_sample": True,
    "length_penalty": 1,
}

PRESET_TALEMATE_CONVERSATION = {
    "temperature": 0.65,
    "top_p": 0.47,
    "top_k": 42,
    "typical_p": 1,
    "top_a": 0,
    "tfs": 1,
    "epsilon_cutoff": 0,
    "eta_cutoff": 0,
    "repetition_penalty": 1.18,
    "repetition_penalty_range": 2048,
    "no_repeat_ngram_size": 0,
    "penalty_alpha": 0,
    "num_beams": 1,
    "length_penalty": 1,
    "min_length": 0,
    "encoder_rep_pen": 1,
    "do_sample": True,
    "early_stopping": False,
    "mirostat_mode": 0,
    "mirostat_tau": 5,
    "mirostat_eta": 0.1
}

PRESET_TALEMATE_CREATOR = {
    "temperature": 0.7,
    "top_p": 0.9,
    "repetition_penalty": 1.15,
    "repetition_penalty_range": 512,
    "top_k": 20,
    "do_sample": True,
    "length_penalty": 1,
}   

PRESET_LLAMA_PRECISE = {
    'temperature': 0.7,
    'top_p': 0.1,
    'repetition_penalty': 1.18,
    'top_k': 40
}

PRESET_KOBOLD_GODLIKE = {
    'temperature': 0.7,
    'top_p': 0.5,
    'typical_p': 0.19,
    'repetition_penalty': 1.1,
    "repetition_penalty_range": 1024,
}

PRESET_DIVINE_INTELLECT = {
    'temperature': 1.31,
    'top_p': 0.14,
    "repetition_penalty_range": 1024,
    'repetition_penalty': 1.17,
    'top_k': 49,
    "mirostat_mode": 0,
    "mirostat_tau": 5,
    "mirostat_eta": 0.1,
    "tfs": 1,
}

PRESET_SIMPLE_1 = {
    "temperature": 0.7,
    "top_p": 0.9,
    "repetition_penalty": 1.15,
    "top_k": 20,
}

def jiggle_randomness(prompt_config:dict, offset:float=0.3) -> dict:
    """
    adjusts temperature and repetition_penalty
    by random values using the base value as a center
    """
    
    temp = prompt_config["temperature"]
    rep_pen = prompt_config["repetition_penalty"]
    
    copied_config = copy.deepcopy(prompt_config)
    
    min_offset = offset * 0.3

    copied_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
    copied_config["repetition_penalty"] = random.uniform(rep_pen + min_offset * 0.3, rep_pen + offset * 0.3)
    
    return copied_config
    
    
class TaleMateClient:
    """
    An abstract TaleMate client that can be implemented for different communication methods with the AI.
    """
    def __init__(
        self,
        api_url: str,
        max_token_length: Union[int, DefaultContext] = int.__new__(
            DefaultContext, 2048
        ),
    ):
        self.api_url = api_url
        self.name = "generic_client"
        self.model_name = None
        self.last_token_length = 0
        self.max_token_length = max_token_length
        self.original_max_token_length = max_token_length
        self.enabled = True
        self.current_status = None

    @abstractmethod
    def send_message(self, message: dict) -> str:
        """
        Sends a message to the AI. Needs to be implemented by the subclass.
        :param message: The message to be sent.
        :return: The AI's response text.
        """
        pass

    @abstractmethod
    def send_prompt(self, prompt: str) -> str:
        """
        Sends a prompt to the AI. Needs to be implemented by the subclass.
        :param prompt: The text prompt to send.
        :return: The AI's response text.
        """
        pass

    def reconfigure(self, **kwargs):
        if "api_url" in kwargs:
            self.api_url = kwargs["api_url"]

        if "max_token_length" in kwargs:
            self.max_token_length = kwargs["max_token_length"]
            
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])

    def remaining_tokens(self, context: Union[str, list]) -> int:
        return self.max_token_length - util.count_tokens(context)


    def prompt_template(self, sys_msg, prompt):
        return model_prompt(self.model_name, sys_msg, prompt)

class RESTTaleMateClient(TaleMateClient, ABC):
    """
    A RESTful TaleMate client that connects to the REST API endpoint.
    """

    async def send_message(self, message: dict, url: str) -> str:
        """
        Sends a message to the REST API and returns the AI's response.
        :param message: The message to be sent.
        :return: The AI's response text.
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=message, timeout=None)
                response_data = response.json()
                return response_data["results"][0]["text"]
        except KeyError:
            return response_data["results"][0]["history"]["visible"][0][-1]


@register()
class TextGeneratorWebuiClient(RESTTaleMateClient):
    """
    Client that connects to the text-generatior-webui api
    """

    client_type = "textgenwebui"
    conversation_retries = 5

    def __init__(self, api_url: str, max_token_length: int = 2048, **kwargs):
        
        api_url = self.cleanup_api_url(api_url)
        
        self.api_url_base = api_url
        api_url = f"{api_url}/v1/chat"
        super().__init__(api_url, max_token_length=max_token_length)
        self.model_name = None
        self.limited_ram = False
        self.name = kwargs.get("name", "textgenwebui")
        self.processing = False
        self.connected = False

    def __str__(self):
        return f"TextGeneratorWebuiClient[{self.api_url_base}][{self.model_name or ''}]"

    def cleanup_api_url(self, api_url:str):
        """
        Strips trailing / and ensures endpoint is /api
        """
        
        if api_url.endswith("/"):
            api_url = api_url[:-1]
            
        if not api_url.endswith("/api"):
            api_url = api_url + "/api"
            
        return api_url

    def reconfigure(self, **kwargs):
        super().reconfigure(**kwargs)
        if "api_url" in kwargs:
            log.debug("reconfigure", api_url=kwargs["api_url"])
            api_url = kwargs["api_url"]
            api_url = self.cleanup_api_url(api_url)
            self.api_url_base = api_url
            self.api_url = api_url
        
    def toggle_disabled_if_remote(self):
        
        remote_servies = [
            ".runpod.net"
        ]
        
        for service in remote_servies:
            if service in self.api_url_base:
                self.enabled = False
                return

    def emit_status(self, processing: bool = None):
        if processing is not None:
            self.processing = processing

        if not self.enabled:
            status = "disabled"
            model_name = "Disabled"
        elif not self.connected:
            status = "error"
            model_name = "Could not connect"
        elif self.model_name:
            status = "busy" if self.processing else "idle"
            model_name = self.model_name
        else:
            model_name = "No model loaded"
            status = "warning"
            
        status_change = status != self.current_status
        self.current_status = status
        
        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status,
        )


        if status_change:
            instance.emit_agent_status_by_client(self) 


    # Add the 'status' method
    async def status(self):
        """
        Send a request to the API to retrieve the loaded AI model name.
        Raises an error if no model name is returned.
        :return: None
        """
        
        if not self.enabled:
            self.connected = False
            self.emit_status()
            return
        
        try:
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url_base}/v1/model", timeout=2)
            
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

        model_name = response_data.get("result")

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

    def auto_context_length(self):
        """
        Automaticalle sets context length based on LLM
        """

        if not isinstance(self.max_token_length, DefaultContext):
            # context length was specified manually
            return

        model_name = self.model_name.lower()

        if "longchat" in model_name:
            self.max_token_length = 16000
        elif "8k" in model_name:
            if not self.limited_ram or "13b" in model_name:
                self.max_token_length = 6000
            else:
                self.max_token_length = 4096
        elif "4k" in model_name:
            self.max_token_length = 4096
        else:
            self.max_token_length = self.original_max_token_length

    @property
    def instruction_template(self):
        if "vicuna" in self.model_name.lower():
            return "Vicuna-v1.1"
        if "camel" in self.model_name.lower():
            return "Vicuna-v1.1"
        return ""

    def prompt_url(self):
        return self.api_url_base + "/v1/generate"

    def prompt_config_conversation_old(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.BASIC,
            prompt,
        )
        
        config = {
            "prompt": prompt,
            "max_new_tokens": 75,
            "truncation_length": self.max_token_length,
        }
        config.update(PRESET_TALEMATE_CONVERSATION)
        return config

        
    def prompt_config_conversation(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.ROLEPLAY,
            prompt,
        )

        stopping_strings =  ["<|end_of_turn|>"]
        
        conversation_context = client_context_attribute("conversation")
        
        stopping_strings += [
            f"{character}:" for character in conversation_context["other_characters"]
        ]
        
        max_new_tokens = conversation_context.get("length", 96)
        log.debug("prompt_config_conversation", stopping_strings=stopping_strings, conversation_context=conversation_context, max_new_tokens=max_new_tokens)

        config = {
            "prompt": prompt,
            "max_new_tokens": max_new_tokens,
            "truncation_length": self.max_token_length,
            "stopping_strings": stopping_strings,
        }
        config.update(PRESET_TALEMATE_CONVERSATION)
        
        jiggle_randomness(config)
        
        return config

    def prompt_config_conversation_long(self, prompt: str) -> dict:
        config = self.prompt_config_conversation(prompt)
        config["max_new_tokens"] = 300
        return config
    
    def prompt_config_conversation_select_talking_actor(self, prompt: str) -> dict:
        config = self.prompt_config_conversation(prompt)
        config["max_new_tokens"] = 30
        config["stopping_strings"] += [":"]
        return config


    def prompt_config_summarize(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.NARRATOR,
            prompt,
        )
        
        config = {
            "prompt": prompt,
            "max_new_tokens": 500,
            "truncation_length": self.max_token_length,
        }
        
        config.update(PRESET_LLAMA_PRECISE)
        return config

    def prompt_config_analyze(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.ANALYST,
            prompt,
        )
        
        config = {
            "prompt": prompt,
            "max_new_tokens": 500,
            "truncation_length": self.max_token_length,
        }
        
        config.update(PRESET_SIMPLE_1)
        return config
    
    def prompt_config_analyze_creative(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.ANALYST,
            prompt,
        )

        config = {}
        config.update(PRESET_DIVINE_INTELLECT)
        config.update({
            "prompt": prompt, 
            "max_new_tokens": 1024,
            "repetition_penalty_range": 1024,
            "truncation_length": self.max_token_length
        })
        
        return config
    
    def prompt_config_analyze_long(self, prompt: str) -> dict:
        config = self.prompt_config_analyze(prompt)
        config["max_new_tokens"] = 1000
        return config

    def prompt_config_analyze_freeform(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.ANALYST_FREEFORM,
            prompt,
        )
        
        config = {
            "prompt": prompt,
            "max_new_tokens": 500,
            "truncation_length": self.max_token_length,
        }
        
        config.update(PRESET_LLAMA_PRECISE)
        return config


    def prompt_config_analyze_freeform_short(self, prompt: str) -> dict:
        config = self.prompt_config_analyze_freeform(prompt)
        config["max_new_tokens"] = 10
        return config

    def prompt_config_narrate(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.NARRATOR,
            prompt,
        )

        config = {
            "prompt": prompt,
            "max_new_tokens": 500,
            "truncation_length": self.max_token_length,
        }
        config.update(PRESET_LLAMA_PRECISE)
        return config

    def prompt_config_story(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.NARRATOR,
            prompt,
        )
        
        config = {
            "prompt": prompt,
            "max_new_tokens": 300,
            "seed": random.randint(0, 1000000000),
            "truncation_length": self.max_token_length
        }
        config.update(PRESET_DIVINE_INTELLECT)
        config.update({
            "repetition_penalty": 1.3,
            "repetition_penalty_range": 2048,
        })
        return config

    def prompt_config_create(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.CREATOR,
            prompt,
        )
        config = {
            "prompt": prompt,
            "max_new_tokens": min(1024, self.max_token_length * 0.35),
            "truncation_length": self.max_token_length,
        }
        config.update(PRESET_TALEMATE_CREATOR)
        return config

    def prompt_config_create_concise(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.CREATOR,
            prompt,
        )

        config = {
            "prompt": prompt,
            "max_new_tokens": min(400, self.max_token_length * 0.25),
            "truncation_length": self.max_token_length,
            "stopping_strings": ["<|DONE|>", "\n\n"]
        }
        config.update(PRESET_TALEMATE_CREATOR)
        return config
    
    def prompt_config_create_precise(self, prompt: str) -> dict:
        config = self.prompt_config_create_concise(prompt)
        config.update(PRESET_LLAMA_PRECISE)
        return config

    def prompt_config_director(self, prompt: str) -> dict:
        prompt = self.prompt_template(
            system_prompts.DIRECTOR,
            prompt,
        )

        config = {
            "prompt": prompt,
            "max_new_tokens": min(600, self.max_token_length * 0.25),
            "truncation_length": self.max_token_length,
        }
        config.update(PRESET_SIMPLE_1)
        return config
        

    def prompt_config_director_short(self, prompt: str) -> dict:
        config = self.prompt_config_director(prompt)
        config.update(max_new_tokens=25)
        return config
    
    def prompt_config_director_yesno(self, prompt: str) -> dict:
        config = self.prompt_config_director(prompt)
        config.update(max_new_tokens=2)
        return config
         
    def prompt_config_edit_dialogue(self, prompt:str) -> dict:
        prompt = self.prompt_template(
            system_prompts.EDITOR,
            prompt,
        )
        
        conversation_context = client_context_attribute("conversation")
        
        stopping_strings = [
            f"{character}:" for character in conversation_context["other_characters"]
        ]
        
        config = {
            "prompt": prompt,
            "max_new_tokens": 100,
            "truncation_length": self.max_token_length,
            "stopping_strings": stopping_strings,
        }
        
        config.update(PRESET_DIVINE_INTELLECT)

        return config

    def prompt_config_edit_add_detail(self, prompt:str) -> dict:
        
        config = self.prompt_config_edit_dialogue(prompt)
        config.update(max_new_tokens=200)
        return config
    

    def prompt_config_edit_fix_exposition(self, prompt:str) -> dict:
        
        config = self.prompt_config_edit_dialogue(prompt)
        config.update(max_new_tokens=1024)
        return config


    async def send_prompt(
        self, prompt: str, kind: str = "conversation", finalize: Callable = lambda x: x
    ) -> str:
        """
        Send a prompt to the AI and return its response.
        :param prompt: The text prompt to send.
        :return: The AI's response text.
        """
        
        #prompt = prompt.replace("<|BOT|>", "<|BOT|>Certainly! ")

        await self.status()
        self.emit_status(processing=True)

        await asyncio.sleep(0.01)

        fn_prompt_config = getattr(self, f"prompt_config_{kind}")
        fn_url = self.prompt_url
        message = fn_prompt_config(prompt)
                
        if client_context_attribute("nuke_repetition") > 0.0:
            log.info("nuke repetition", offset=client_context_attribute("nuke_repetition"), temperature=message["temperature"], repetition_penalty=message["repetition_penalty"])
            message = jiggle_randomness(message, offset=client_context_attribute("nuke_repetition"))
            log.info("nuke repetition (applied)", offset=client_context_attribute("nuke_repetition"), temperature=message["temperature"], repetition_penalty=message["repetition_penalty"])
        
        message = finalize(message)

        token_length = int(len(message["prompt"]) / 3.6)

        self.last_token_length = token_length
        
        log.debug("send_prompt",  token_length=token_length, max_token_length=self.max_token_length)
        
        message["prompt"] = message["prompt"].strip()
        
        #print(f"prompt: |{message['prompt']}|")
        
        # add <|im_end|> to stopping strings
        if "stopping_strings" in message:
            message["stopping_strings"] += ["<|im_end|>", "</s>"]
        else:
            message["stopping_strings"] = ["<|im_end|>", "</s>"]

        #message["seed"] = -1

        #for k,v in message.items():
        #    if k == "prompt":
        #        continue
        #    print(f"{k}: {v}")

        response = await self.send_message(message, fn_url())

        response = response.split("#")[0]
        self.emit_status(processing=False)
        
        emit("prompt_sent", data={
            "kind": kind,
            "prompt": message["prompt"],
            "response": response,
            "prompt_tokens": token_length,
            "response_tokens": int(len(response) / 3.6)
        })
        
        return response


class OpenAPIClient(RESTTaleMateClient):
    pass


class GPT3Client(OpenAPIClient):
    pass


class GPT4Client(OpenAPIClient):
    pass
