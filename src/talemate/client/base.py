"""
A unified client base, based on the openai API
"""
import copy
import random
import time
from typing import Callable

import structlog
import logging
from openai import AsyncOpenAI

from talemate.emit import emit
import talemate.instance as instance
import talemate.client.presets as presets
import talemate.client.system_prompts as system_prompts
import talemate.util as util
from talemate.client.context import client_context_attribute
from talemate.client.model_prompts import model_prompt
from talemate.agents.context import active_agent

# Set up logging level for httpx to WARNING to suppress debug logs.
logging.getLogger('httpx').setLevel(logging.WARNING)

REMOTE_SERVICES = [
    # TODO: runpod.py should add this to the list
    ".runpod.net"
]

STOPPING_STRINGS = ["<|im_end|>", "</s>"]

class ClientBase:
    
    api_url: str
    model_name: str
    name:str = None
    enabled: bool = True
    current_status: str = None
    max_token_length: int = 4096
    processing: bool = False
    connected: bool = False
    conversation_retries: int = 5
    auto_break_repetition_enabled: bool = True

    client_type = "base"

    
    def __init__(
        self,
        api_url: str = None,
        name = None,
        **kwargs,
    ):
        self.api_url = api_url
        self.name = name or self.client_type
        self.log = structlog.get_logger(f"client.{self.client_type}")
        self.set_client()
        
    def __str__(self):
        return f"{self.client_type}Client[{self.api_url}][{self.model_name or ''}]"
        
    def set_client(self):
        self.client = AsyncOpenAI(base_url=self.api_url, api_key="sk-1111")

    def prompt_template(self, sys_msg, prompt):
        
        """
        Applies the appropriate prompt template for the model.
        """
        
        if not self.model_name:
            self.log.warning("prompt template not applied", reason="no model loaded")
            return f"{sys_msg}\n{prompt}"
        
        return model_prompt(self.model_name, sys_msg, prompt)   
    
    def reconfigure(self, **kwargs):
        
        """
        Reconfigures the client.
        
        Keyword Arguments:
        
        - api_url: the API URL to use
        - max_token_length: the max token length to use
        - enabled: whether the client is enabled
        """
        
        if "api_url" in kwargs:
            self.api_url = kwargs["api_url"]

        if "max_token_length" in kwargs:
            self.max_token_length = kwargs["max_token_length"]
            
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])


    def toggle_disabled_if_remote(self):
        
        """
        If the client is targeting a remote recognized service, this
        will disable the client.
        """
        
        for service in REMOTE_SERVICES:
            if service in self.api_url:
                if self.enabled:
                    self.log.warn("remote service unreachable, disabling client", client=self.name)
                self.enabled = False
                
                return True
            
        return False
            

    def get_system_message(self, kind: str) -> str:
        
        """
        Returns the appropriate system message for the given kind of generation
        
        Arguments:
        
        - kind: the kind of generation
        """
        
        # TODO: make extensible
       
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
        if "analyze_freeform" in kind:
            return system_prompts.ANALYST_FREEFORM
        if "analyst" in kind:
            return system_prompts.ANALYST
        if "analyze" in kind:
            return system_prompts.ANALYST
       
        return system_prompts.BASIC
    
    
    def emit_status(self, processing: bool = None):
        
        """
        Sets and emits the client status.
        """
        
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
            
            
    async def get_model_name(self):
        models = await self.client.models.list()
        try:
            return models.data[0].id
        except IndexError:
            return None
            
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
            self.model_name = await self.get_model_name()
        except Exception as e:
            self.log.warning("client status error", e=e, client=self.name)
            self.model_name = None
            self.connected = False
            self.toggle_disabled_if_remote()
            self.emit_status()
            return
        
        self.connected = True
        
        if not self.model_name or self.model_name == "None":
            self.log.warning("client model not loaded", client=self)
            self.emit_status()
            return
        
        self.emit_status()
        
    
    def generate_prompt_parameters(self, kind:str):
        parameters = {}
        self.tune_prompt_parameters(
            presets.configure(parameters, kind, self.max_token_length),
            kind
        )
        return parameters
    
    def tune_prompt_parameters(self, parameters:dict, kind:str):
        parameters["stream"] = False
        if client_context_attribute("nuke_repetition") > 0.0 and self.jiggle_enabled_for(kind):
            self.jiggle_randomness(parameters, offset=client_context_attribute("nuke_repetition"))
            
        fn_tune_kind = getattr(self, f"tune_prompt_parameters_{kind}", None)
        if fn_tune_kind:
            fn_tune_kind(parameters)

        agent_context = active_agent.get()
        if agent_context.agent:
            agent_context.agent.inject_prompt_paramters(parameters, kind, agent_context.action)
        
    def tune_prompt_parameters_conversation(self, parameters:dict):
        conversation_context = client_context_attribute("conversation")
        parameters["max_tokens"] = conversation_context.get("length", 96)
        
        dialog_stopping_strings = [
            f"{character}:" for character in conversation_context["other_characters"]
        ]
        
        if "extra_stopping_strings" in parameters:
            parameters["extra_stopping_strings"] += dialog_stopping_strings
        else:
            parameters["extra_stopping_strings"] = dialog_stopping_strings
            
            
    async def generate(self, prompt:str, parameters:dict, kind:str):
        
        """
        Generates text from the given prompt and parameters.
        """
        
        self.log.debug("generate", prompt=prompt[:128]+" ...", parameters=parameters)
        
        try:
            response = await self.client.completions.create(prompt=prompt.strip(), **parameters)
            return response.get("choices", [{}])[0].get("text", "")
        except Exception as e:
            self.log.error("generate error", e=e)
            return ""
        
    async def send_prompt(
        self, prompt: str, kind: str = "conversation", finalize: Callable = lambda x: x, retries:int=2
    ) -> str:
        """
        Send a prompt to the AI and return its response.
        :param prompt: The text prompt to send.
        :return: The AI's response text.
        """
        
        try:
            self.emit_status(processing=True)
            await self.status()

            prompt_param = self.generate_prompt_parameters(kind)

            finalized_prompt = self.prompt_template(self.get_system_message(kind), prompt).strip()
            prompt_param = finalize(prompt_param)

            token_length = self.count_tokens(finalized_prompt)

            
            time_start = time.time()
            extra_stopping_strings = prompt_param.pop("extra_stopping_strings", [])

            self.log.debug("send_prompt", token_length=token_length, max_token_length=self.max_token_length, parameters=prompt_param)
            response = await self.generate(
                self.repetition_adjustment(finalized_prompt), 
                prompt_param, 
                kind
            )
            
            response, finalized_prompt = await self.auto_break_repetition(finalized_prompt, prompt_param, response, kind, retries)
            
            time_end = time.time()
            
            # stopping strings sometimes get appended to the end of the response anyways
            # split the response by the first stopping string and take the first part
            
            
            for stopping_string in STOPPING_STRINGS + extra_stopping_strings:
                if stopping_string in response:
                    response = response.split(stopping_string)[0]
                    break
            
            emit("prompt_sent", data={
                "kind": kind,
                "prompt": finalized_prompt,
                "response": response,
                "prompt_tokens": token_length,
                "response_tokens": self.count_tokens(response),
                "time": time_end - time_start,
            })
            
            return response
        finally:
            self.emit_status(processing=False)
            
            
    async def auto_break_repetition(
        self, 
        finalized_prompt:str, 
        prompt_param:dict, 
        response:str, 
        kind:str, 
        retries:int,
        pad_max_tokens:int=32,
    ) -> str:
        
        """
        If repetition breaking is enabled, this will retry the prompt if its
        response is too similar to other messages in the prompt
        
        This requires the agent to have the allow_repetition_break method
        and the jiggle_enabled_for method and the client to have the
        auto_break_repetition_enabled attribute set to True
        
        Arguments:

        - finalized_prompt: the prompt that was sent
        - prompt_param: the parameters that were used
        - response: the response that was received
        - kind: the kind of generation
        - retries: the number of retries left
        - pad_max_tokens: increase response max_tokens by this amount per iteration
                
        Returns:
        
        - the response
        """
        
        if not self.auto_break_repetition_enabled:
            return response
        
        agent_context = active_agent.get()
        if self.jiggle_enabled_for(kind, auto=True):
            
            # check if the response is a repetition
            # using the default similarity threshold of 98, meaning it needs
            # to be really similar to be considered a repetition
            
            is_repetition, similarity_score, matched_line = util.similarity_score(
                response, 
                finalized_prompt.split("\n"), 
            )
            
            if not is_repetition:
                
                # not a repetition, return the response
                
                self.log.debug("send_prompt no similarity", similarity_score=similarity_score)
                return response
            
            while is_repetition and retries > 0:
                
                # it's a repetition, retry the prompt with adjusted parameters
                
                self.log.warn(
                    "send_prompt similarity retry", 
                    agent=agent_context.agent.agent_type, 
                    similarity_score=similarity_score, 
                    retries=retries
                )
                
                # first we apply the client's randomness jiggle which will adjust
                # parameters like temperature and repetition_penalty, depending
                # on the client
                #
                # this is a cumulative adjustment, so it will add to the previous
                # iteration's adjustment, this also means retries should be kept low
                # otherwise it will get out of hand and start generating nonsense
                
                self.jiggle_randomness(prompt_param, offset=0.5)
                
                # then we pad the max_tokens by the pad_max_tokens amount
                
                prompt_param["max_tokens"] += pad_max_tokens
                
                # send the prompt again
                # we use the repetition_adjustment method to further encourage
                # the AI to break the repetition on its own as well.
                
                finalized_prompt = self.repetition_adjustment(finalized_prompt, is_repetitive=True)
                
                response = retried_response = await self.generate(
                    finalized_prompt, 
                    prompt_param, 
                    kind
                )
                
                self.log.debug("send_prompt dedupe sentences", response=response, matched_line=matched_line)
                
                # a lot of the times the response will now contain the repetition + something new
                # so we dedupe the response to remove the repetition on sentences level
                
                response = util.dedupe_sentences(response, matched_line, similarity_threshold=85, debug=True)
                self.log.debug("send_prompt dedupe sentences (after)", response=response)
                
                # deduping may have removed the entire response, so we check for that
                
                if not util.strip_partial_sentences(response).strip():
                    
                    # if the response is empty, we set the response to the original
                    # and try again next loop
                    
                    response = retried_response
                
                # check if the response is a repetition again
                
                is_repetition, similarity_score, matched_line = util.similarity_score(
                    response, 
                    finalized_prompt.split("\n"), 
                )
                retries -= 1
                
        return response, finalized_prompt
        
    def count_tokens(self, content:str):
        return util.count_tokens(content)

    def jiggle_randomness(self, prompt_config:dict, offset:float=0.3) -> dict:
        """
        adjusts temperature and repetition_penalty
        by random values using the base value as a center
        """
        
        temp = prompt_config["temperature"]
        min_offset = offset * 0.3
        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
        
    def jiggle_enabled_for(self, kind:str, auto:bool=False) -> bool:
        
        agent_context = active_agent.get()
        agent = agent_context.agent
        
        if not agent:
            return False
        
        return agent.allow_repetition_break(kind, agent_context.action, auto=auto)
    
    def repetition_adjustment(self, prompt:str, is_repetitive:bool=False):
        """
        Breaks the prompt into lines and checkse each line for a match with
        [$REPETITION|{repetition_adjustment}].
        
        On match and if is_repetitive is True, the line is removed from the prompt and
        replaced with the repetition_adjustment.
        
        On match and if is_repetitive is False, the line is removed from the prompt.        
        """
        
        lines = prompt.split("\n")
        new_lines = []
        
        for line in lines:
            if line.startswith("[$REPETITION|"):
                if is_repetitive:
                    new_lines.append(line.split("|")[1][:-1])
            else:
                new_lines.append(line)
        
        return "\n".join(new_lines)