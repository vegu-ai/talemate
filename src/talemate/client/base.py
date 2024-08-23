"""
A unified client base, based on the openai API
"""

import ipaddress
import logging
import random
import time
import asyncio
from typing import Callable, Union

import pydantic
import structlog
import urllib3
from openai import AsyncOpenAI, PermissionDeniedError

import talemate.client.presets as presets
import talemate.client.system_prompts as system_prompts
import talemate.instance as instance
import talemate.util as util
from talemate.agents.context import active_agent
from talemate.client.context import client_context_attribute
from talemate.client.model_prompts import model_prompt
from talemate.context import active_scene
from talemate.emit import emit
from talemate.exceptions import SceneInactiveError, GenerationCancelled

# Set up logging level for httpx to WARNING to suppress debug logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

log = structlog.get_logger("client.base")

STOPPING_STRINGS = ["<|im_end|>", "</s>"]


class ClientDisabledError(OSError):
    def __init__(self, client: "ClientBase"):
        self.client = client
        self.message = f"Client {client.name} is disabled"
        super().__init__(self.message)


class PromptData(pydantic.BaseModel):
    kind: str
    prompt: str
    response: str
    prompt_tokens: int
    response_tokens: int
    client_name: str
    client_type: str
    time: Union[float, int]
    agent_stack: list[str] = pydantic.Field(default_factory=list)
    generation_parameters: dict = pydantic.Field(default_factory=dict)
    inference_preset: str = None


class ErrorAction(pydantic.BaseModel):
    title: str
    action_name: str
    icon: str = "mdi-error"
    arguments: list = []


class Defaults(pydantic.BaseModel):
    api_url: str = "http://localhost:5000"
    max_token_length: int = 8192
    double_coercion: str = None


class ExtraField(pydantic.BaseModel):
    name: str
    type: str
    label: str
    required: bool
    description: str


class ParameterReroute(pydantic.BaseModel):
    talemate_parameter: str
    client_parameter: str

    def reroute(self, parameters: dict):
        if self.talemate_parameter in parameters:
            parameters[self.client_parameter] = parameters[self.talemate_parameter]
            del parameters[self.talemate_parameter]

    def __str__(self):
        return self.client_parameter

    def __eq__(self, other):
        return str(self) == str(other)


class ClientBase:
    api_url: str
    model_name: str
    api_key: str = None
    name: str = None
    enabled: bool = True
    current_status: str = None
    max_token_length: int = 8192
    processing: bool = False
    connected: bool = False
    conversation_retries: int = 0
    auto_break_repetition_enabled: bool = True
    decensor_enabled: bool = True
    auto_determine_prompt_template: bool = False
    finalizers: list[str] = []
    double_coercion: Union[str, None] = None
    client_type = "base"

    class Meta(pydantic.BaseModel):
        experimental: Union[None, str] = None
        defaults: Defaults = Defaults()
        title: str = "Client"
        name_prefix: str = "Client"
        enable_api_auth: bool = False
        requires_prompt_template: bool = True

    def __init__(
        self,
        api_url: str = None,
        name=None,
        **kwargs,
    ):
        self.api_url = api_url
        self.name = name or self.client_type
        self.auto_determine_prompt_template_attempt = None
        self.log = structlog.get_logger(f"client.{self.client_type}")
        self.double_coercion = kwargs.get("double_coercion", None)
        self.enabled = kwargs.get("enabled", True)
        if "max_token_length" in kwargs:
            self.max_token_length = (
                int(kwargs["max_token_length"]) if kwargs["max_token_length"] else 8192
            )
        self.set_client(max_token_length=self.max_token_length)

    def __str__(self):
        return f"{self.client_type}Client[{self.api_url}][{self.model_name or ''}]"

    @property
    def experimental(self):
        return False

    @property
    def can_be_coerced(self):
        """
        Determines whether or not his client can pass LLM coercion. (e.g., is able
        to predefine partial LLM output in the prompt)
        """
        return self.Meta().requires_prompt_template

    @property
    def max_tokens_param_name(self):
        return "max_tokens"

    @property
    def supported_parameters(self):
        # each client should override this with the parameters it supports
        return [
            "temperature",
            "max_tokens",
        ]

    def set_client(self, **kwargs):
        self.client = AsyncOpenAI(base_url=self.api_url, api_key="sk-1111")

    def prompt_template(self, sys_msg: str, prompt: str):
        """
        Applies the appropriate prompt template for the model.
        """

        if not self.model_name:
            self.log.warning("prompt template not applied", reason="no model loaded")
            return f"{sys_msg}\n{prompt}"

        # is JSON coercion active?
        # Check for <|BOT|>{ in the prompt
        json_coercion = "<|BOT|>{" in prompt

        if self.can_be_coerced and self.double_coercion and not json_coercion:
            double_coercion = self.double_coercion
            double_coercion = f"{double_coercion}\n\n"
        else:
            double_coercion = None

        return model_prompt(self.model_name, sys_msg, prompt, double_coercion)[0]

    def prompt_template_example(self):
        if not getattr(self, "model_name", None):
            return None, None
        return model_prompt(
            self.model_name, "{sysmsg}", "{prompt}<|BOT|>{LLM coercion}"
        )

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

        if kwargs.get("max_token_length"):
            self.max_token_length = int(kwargs["max_token_length"])

        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])

        if "double_coercion" in kwargs:
            self.double_coercion = kwargs["double_coercion"]

    def host_is_remote(self, url: str) -> bool:
        """
        Returns whether or not the host is a remote service.

        It checks common local hostnames / ip prefixes.

        - localhost
        """

        host = urllib3.util.parse_url(url).host

        if host.lower() == "localhost":
            return False

        # use ipaddress module to check for local ip prefixes
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return True

        if ip.is_loopback or ip.is_private:
            return False

        return True

    def toggle_disabled_if_remote(self):
        """
        If the client is targeting a remote recognized service, this
        will disable the client.
        """

        if not self.api_url:
            return False

        if self.host_is_remote(self.api_url) and self.enabled:
            self.log.warn(
                "remote service unreachable, disabling client", client=self.name
            )
            self.enabled = False
            return True

        return False

    def get_system_message(self, kind: str) -> str:
        """
        Returns the appropriate system message for the given kind of generation

        Arguments:

        - kind: the kind of generation
        """

        if self.decensor_enabled:

            if "narrate" in kind:
                return system_prompts.NARRATOR
            if "director" in kind:
                return system_prompts.DIRECTOR
            if "create" in kind:
                return system_prompts.CREATOR
            if "roleplay" in kind:
                return system_prompts.ROLEPLAY
            if "conversation" in kind:
                return system_prompts.ROLEPLAY
            if "basic" in kind:
                return system_prompts.BASIC
            if "editor" in kind:
                return system_prompts.EDITOR
            if "edit" in kind:
                return system_prompts.EDITOR
            if "world_state" in kind:
                return system_prompts.WORLD_STATE
            if "analyze_freeform" in kind:
                return system_prompts.ANALYST_FREEFORM
            if "analyst" in kind:
                return system_prompts.ANALYST
            if "analyze" in kind:
                return system_prompts.ANALYST
            if "summarize" in kind:
                return system_prompts.SUMMARIZE
            if "visualize" in kind:
                return system_prompts.VISUALIZE

        else:

            if "narrate" in kind:
                return system_prompts.NARRATOR_NO_DECENSOR
            if "director" in kind:
                return system_prompts.DIRECTOR_NO_DECENSOR
            if "create" in kind:
                return system_prompts.CREATOR_NO_DECENSOR
            if "roleplay" in kind:
                return system_prompts.ROLEPLAY_NO_DECENSOR
            if "conversation" in kind:
                return system_prompts.ROLEPLAY_NO_DECENSOR
            if "basic" in kind:
                return system_prompts.BASIC
            if "editor" in kind:
                return system_prompts.EDITOR_NO_DECENSOR
            if "edit" in kind:
                return system_prompts.EDITOR_NO_DECENSOR
            if "world_state" in kind:
                return system_prompts.WORLD_STATE_NO_DECENSOR
            if "analyze_freeform" in kind:
                return system_prompts.ANALYST_FREEFORM_NO_DECENSOR
            if "analyst" in kind:
                return system_prompts.ANALYST_NO_DECENSOR
            if "analyze" in kind:
                return system_prompts.ANALYST_NO_DECENSOR
            if "summarize" in kind:
                return system_prompts.SUMMARIZE_NO_DECENSOR
            if "visualize" in kind:
                return system_prompts.VISUALIZE_NO_DECENSOR

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

        prompt_template_example, prompt_template_file = self.prompt_template_example()
        has_prompt_template = (
            prompt_template_file and prompt_template_file != "default.jinja2"
        )

        if not has_prompt_template and self.auto_determine_prompt_template:

            # only attempt to determine the prompt template once per model and
            # only if the model does not already have a prompt template

            if (
                hasattr(self, "model_name")
                and self.auto_determine_prompt_template_attempt != self.model_name
            ):
                log.info("auto_determine_prompt_template", model_name=self.model_name)
                self.auto_determine_prompt_template_attempt = self.model_name
                self.determine_prompt_template()
                prompt_template_example, prompt_template_file = (
                    self.prompt_template_example()
                )
                has_prompt_template = (
                    prompt_template_file and prompt_template_file != "default.jinja2"
                )

        data = {
            "api_key": self.api_key,
            "prompt_template_example": prompt_template_example,
            "has_prompt_template": has_prompt_template,
            "template_file": prompt_template_file,
            "meta": self.Meta().model_dump(),
            "error_action": None,
            "double_coercion": self.double_coercion,
            "enabled": self.enabled,
        }

        for field_name in getattr(self.Meta(), "extra_fields", {}).keys():
            data[field_name] = getattr(self, field_name, None)

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status,
            data=data,
        )

        if status_change:
            instance.emit_agent_status_by_client(self)

    def populate_extra_fields(self, data: dict):
        """
        Updates data with the extra fields from the client's Meta
        """

        for field_name in getattr(self.Meta(), "extra_fields", {}).keys():
            data[field_name] = getattr(self, field_name, None)

    def determine_prompt_template(self):
        if not self.model_name:
            return

        template = model_prompt.query_hf_for_prompt_template_suggestion(self.model_name)

        if template:
            model_prompt.create_user_override(template, self.model_name)

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
            self.emit_status()
            return

        self.connected = True

        if not self.model_name or self.model_name == "None":
            self.emit_status()
            return

        self.emit_status()

    def generate_prompt_parameters(self, kind: str):
        parameters = {}
        self.tune_prompt_parameters(
            presets.configure(parameters, kind, self.max_token_length, self), kind
        )
        return parameters

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        parameters["stream"] = False

        fn_tune_kind = getattr(self, f"tune_prompt_parameters_{kind}", None)
        if fn_tune_kind:
            fn_tune_kind(parameters)

        agent_context = active_agent.get()
        if agent_context.agent:
            agent_context.agent.inject_prompt_paramters(
                parameters, kind, agent_context.action
            )
            
        if client_context_attribute(
            "nuke_repetition"
        ) > 0.0 and self.jiggle_enabled_for(kind):
            self.jiggle_randomness(
                parameters, offset=client_context_attribute("nuke_repetition")
            )

    def tune_prompt_parameters_conversation(self, parameters: dict):
        conversation_context = client_context_attribute("conversation")
        parameters["max_tokens"] = conversation_context.get("length", 96)

        dialog_stopping_strings = [
            f"{character}:" for character in conversation_context["other_characters"]
        ]

        dialog_stopping_strings += [
            f"{character.upper()}\n"
            for character in conversation_context["other_characters"]
        ]

        if "extra_stopping_strings" in parameters:
            parameters["extra_stopping_strings"] += dialog_stopping_strings
        else:
            parameters["extra_stopping_strings"] = dialog_stopping_strings

    def clean_prompt_parameters(self, parameters: dict):
        """
        Does some final adjustments to the prompt parameters before sending
        """

        # apply any parameter reroutes
        for param in self.supported_parameters:
            if isinstance(param, ParameterReroute):
                param.reroute(parameters)

        # drop any parameters that are not supported by the client
        for key in list(parameters.keys()):
            if key not in self.supported_parameters:
                del parameters[key]

    def finalize(self, parameters: dict, prompt: str):

        prompt = util.replace_special_tokens(prompt)

        for finalizer in self.finalizers:
            fn = getattr(self, finalizer, None)
            prompt, applied = fn(parameters, prompt)
            if applied:
                return prompt

        return prompt

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        self.log.debug("generate", prompt=prompt[:128] + " ...", parameters=parameters)

        try:
            response = await self.client.completions.create(
                prompt=prompt.strip(" "), **parameters
            )
            return response.get("choices", [{}])[0].get("text", "")
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="Client API: Permission Denied", status="error")
            return ""
        except Exception as e:
            self.log.error("generate error", e=e)
            emit(
                "status", message="Error during generation (check logs)", status="error"
            )
            return ""
        
        
    def _generate_task(self, prompt: str, parameters: dict, kind: str):
        """
        Creates an asyncio task to generate text from the given prompt and parameters.
        """
        
        return asyncio.create_task(self.generate(prompt, parameters, kind))
    

    def _poll_interrupt(self):
        """
        Creatates a task that continiously checks active_scene.cancel_requested and
        will complete the task if it is requested.
        """
        
        async def poll():
            while True:
                scene = active_scene.get()
                if not scene or not scene.active or scene.cancel_requested:
                    break
                await asyncio.sleep(0.3)
            return GenerationCancelled("Generation cancelled")
        
        return asyncio.create_task(poll())
        
    async def _cancelable_generate(self, prompt: str, parameters: dict, kind: str) -> str | GenerationCancelled:
        
        """
        Queues the generation task and the poll task to be run concurrently.
        
        If the poll task completes before the generation task, the generation task
        will be cancelled.
        
        If the generation task completes before the poll task, the poll task will
        be cancelled.
        """
        
        task_poll = self._poll_interrupt()
        task_generate = self._generate_task(prompt, parameters, kind)
        
        done, pending = await asyncio.wait(
            [task_poll, task_generate],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # cancel the remaining task
        for task in pending:
            task.cancel()
        
        # return the result of the completed task
        return done.pop().result()
        

    async def send_prompt(
        self,
        prompt: str,
        kind: str = "conversation",
        finalize: Callable = lambda x: x,
        retries: int = 2,
    ) -> str:
        """
        Send a prompt to the AI and return its response.
        :param prompt: The text prompt to send.
        :return: The AI's response text.
        """

        if not active_scene.get():
            log.error("SceneInactiveError", scene=active_scene.get())
            raise SceneInactiveError("No active scene context")

        if not active_scene.get().active:
            log.error("SceneInactiveError", scene=active_scene.get())
            raise SceneInactiveError("Scene is no longer active")

        if not self.enabled:
            raise ClientDisabledError(self)

        try:
            self._returned_prompt_tokens = None
            self._returned_response_tokens = None

            self.emit_status(processing=True)
            await self.status()

            prompt_param = self.generate_prompt_parameters(kind)

            finalized_prompt = self.prompt_template(
                self.get_system_message(kind), prompt
            ).strip(" ")

            finalized_prompt = self.finalize(prompt_param, finalized_prompt)

            prompt_param = finalize(prompt_param)

            token_length = self.count_tokens(finalized_prompt)

            time_start = time.time()
            extra_stopping_strings = prompt_param.pop("extra_stopping_strings", [])

            self.clean_prompt_parameters(prompt_param)

            self.log.debug(
                "send_prompt",
                token_length=token_length,
                max_token_length=self.max_token_length,
                parameters=prompt_param,
            )
            prompt_sent = self.repetition_adjustment(finalized_prompt)
            
            response = await self._cancelable_generate(prompt_sent, prompt_param, kind)
            
            if isinstance(response, GenerationCancelled):
                # generation was cancelled
                raise response
            
            #response = await self.generate(prompt_sent, prompt_param, kind)
            
            response, finalized_prompt = await self.auto_break_repetition(
                finalized_prompt, prompt_param, response, kind, retries
            )

            time_end = time.time()

            # stopping strings sometimes get appended to the end of the response anyways
            # split the response by the first stopping string and take the first part

            for stopping_string in STOPPING_STRINGS + extra_stopping_strings:
                if stopping_string in response:
                    response = response.split(stopping_string)[0]
                    break

            agent_context = active_agent.get()

            emit(
                "prompt_sent",
                data=PromptData(
                    kind=kind,
                    prompt=prompt_sent,
                    response=response,
                    prompt_tokens=self._returned_prompt_tokens or token_length,
                    response_tokens=self._returned_response_tokens
                    or self.count_tokens(response),
                    agent_stack=agent_context.agent_stack if agent_context else [],
                    client_name=self.name,
                    client_type=self.client_type,
                    time=time_end - time_start,
                    generation_parameters=prompt_param,
                    inference_preset=client_context_attribute("inference_preset"),
                ).model_dump(),
            )

            return response
        except GenerationCancelled as e:
            raise
        except Exception as e:
            self.log.exception("send_prompt error", e=e)
            emit(
                "status", message="Error during generation (check logs)", status="error"
            )
            return ""
        finally:
            self.emit_status(processing=False)
            self._returned_prompt_tokens = None
            self._returned_response_tokens = None

    async def auto_break_repetition(
        self,
        finalized_prompt: str,
        prompt_param: dict,
        response: str,
        kind: str,
        retries: int,
        pad_max_tokens: int = 32,
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

        if not self.auto_break_repetition_enabled or not response.strip():
            return response, finalized_prompt

        agent_context = active_agent.get()
        if self.jiggle_enabled_for(kind, auto=True):
            # check if the response is a repetition
            # using the default similarity threshold of 98, meaning it needs
            # to be really similar to be considered a repetition

            is_repetition, similarity_score, matched_line = util.similarity_score(
                response, finalized_prompt.split("\n"), similarity_threshold=80
            )

            if not is_repetition:
                # not a repetition, return the response

                self.log.debug(
                    "send_prompt no similarity", similarity_score=similarity_score
                )
                finalized_prompt = self.repetition_adjustment(
                    finalized_prompt, is_repetitive=False
                )
                return response, finalized_prompt

            while is_repetition and retries > 0:
                # it's a repetition, retry the prompt with adjusted parameters

                self.log.warn(
                    "send_prompt similarity retry",
                    agent=agent_context.agent.agent_type,
                    similarity_score=similarity_score,
                    retries=retries,
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

                prompt_param[self.max_tokens_param_name] += pad_max_tokens

                # send the prompt again
                # we use the repetition_adjustment method to further encourage
                # the AI to break the repetition on its own as well.

                finalized_prompt = self.repetition_adjustment(
                    finalized_prompt, is_repetitive=True
                )

                response = retried_response = await self.generate(
                    finalized_prompt, prompt_param, kind
                )

                self.log.debug(
                    "send_prompt dedupe sentences",
                    response=response,
                    matched_line=matched_line,
                )

                # a lot of the times the response will now contain the repetition + something new
                # so we dedupe the response to remove the repetition on sentences level

                response = util.dedupe_sentences(
                    response, matched_line, similarity_threshold=85, debug=True
                )
                self.log.debug(
                    "send_prompt dedupe sentences (after)", response=response
                )

                # deduping may have removed the entire response, so we check for that

                if not util.strip_partial_sentences(response).strip():
                    # if the response is empty, we set the response to the original
                    # and try again next loop

                    response = retried_response

                # check if the response is a repetition again

                is_repetition, similarity_score, matched_line = util.similarity_score(
                    response, finalized_prompt.split("\n"), similarity_threshold=80
                )
                retries -= 1

        return response, finalized_prompt

    def count_tokens(self, content: str):
        return util.count_tokens(content)

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        adjusts temperature and repetition_penalty
        by random values using the base value as a center
        """

        temp = prompt_config["temperature"]
        min_offset = offset * 0.3
        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)

    def jiggle_enabled_for(self, kind: str, auto: bool = False) -> bool:
        agent_context = active_agent.get()
        agent = agent_context.agent

        if not agent:
            return False

        return agent.allow_repetition_break(kind, agent_context.action, auto=auto)

    def repetition_adjustment(self, prompt: str, is_repetitive: bool = False):
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
                    new_lines.append("")
            else:
                new_lines.append(line)

        return "\n".join(new_lines)

    def process_response_for_indirect_coercion(self, prompt: str, response: str) -> str:
        """
        A lot of remote APIs don't let us control the prompt template and we cannot directly
        append the beginning of the desired response to the prompt.

        With indirect coercion we tell the LLM what the beginning of the response should be
        and then hopefully it will adhere to it and we can strip it off the actual response.
        """

        _, right = prompt.split("\nStart your response with: ")
        expected_response = right.strip()
        if expected_response and expected_response.startswith("{"):
            if response.startswith("```json") and response.endswith("```"):
                response = response[7:-3].strip()

        if right and response.startswith(right):
            response = response[len(right) :].strip()

        return response
