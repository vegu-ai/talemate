"""
A unified client base, based on the openai API
"""

import ipaddress
import logging
import re
import random
import time
import traceback
import asyncio
from typing import Callable, Union, Literal, TYPE_CHECKING

import pydantic
import dataclasses
import structlog
import urllib3
from openai import PermissionDeniedError

import talemate.client.presets as presets
import talemate.instance as instance
import talemate.util as util
from talemate.agents.context import active_agent
from talemate.client.context import client_context_attribute
from talemate.client.model_prompts import model_prompt, DEFAULT_TEMPLATE, PromptSpec
from talemate.client.ratelimit import CounterRateLimiter
from talemate.context import active_scene
from talemate.prompts.base import Prompt
from talemate.emit import emit
from talemate.config import get_config, Config
from talemate.config.schema import EmbeddingFunctionPreset, Client as ClientConfig
import talemate.emit.async_signals as async_signals
from talemate.exceptions import (
    SceneInactiveError,
    GenerationCancelled,
    GenerationProcessingError,
    ReasoningResponseError,
)
import talemate.ux.schema as ux_schema

from talemate.client.system_prompts import SystemPrompts

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

# Set up logging level for httpx to WARNING to suppress debug logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

log = structlog.get_logger("client.base")

STOPPING_STRINGS = ["<|im_end|>", "</s>"]

# disable smart quotes until text rendering is refactored
REPLACE_SMART_QUOTES = True


INDIRECT_COERCION_PROMPT = "\nStart your response with: "
INDIRECT_COERCION_PROMPT_REASONING = (
    "\nAfter thinking about it, start your answer with: "
)

DEFAULT_REASONING_PATTERN = r".*?</think>"


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
    preset_group: str | None = None
    reasoning: str | None = None


class ErrorAction(pydantic.BaseModel):
    title: str
    action_name: str
    icon: str = "mdi-error"
    arguments: list = []


class CommonDefaults(pydantic.BaseModel):
    rate_limit: int | None = None
    data_format: Literal["yaml", "json"] | None = None
    preset_group: str | None = None
    reason_enabled: bool = False
    reason_tokens: int = 1024
    reason_response_pattern: str | None = None
    reason_prefill: str | None = None


class Defaults(CommonDefaults, pydantic.BaseModel):
    api_url: str = "http://localhost:5000"
    max_token_length: int = 8192
    double_coercion: str = None
    lock_template: bool = False


class FieldGroup(pydantic.BaseModel):
    name: str
    label: str
    description: str
    icon: str = "mdi-cog"


class ExtraField(pydantic.BaseModel):
    name: str
    type: str
    label: str
    required: bool
    description: str
    group: FieldGroup | None = None
    note: ux_schema.Note | None = None
    choices: list[str | int | float | bool] | None = None


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


class RequestInformation(pydantic.BaseModel):
    start_time: float = pydantic.Field(default_factory=time.time)
    end_time: float | None = None
    first_token_time: float | None = None
    tokens: int = 0
    cancelled: bool = False

    @pydantic.computed_field(description="Duration")
    @property
    def duration(self) -> float:
        end_time = self.end_time or time.time()
        return end_time - self.start_time

    @pydantic.computed_field(description="Tokens per second")
    @property
    def rate(self) -> float:
        try:
            end_time = self.end_time or time.time()
            # Use first_token_time if available, otherwise fall back to start_time
            rate_start_time = self.first_token_time or self.start_time
            denom = end_time - rate_start_time
            if denom <= 0:
                denom = 1e-6
            return self.tokens / denom
        except Exception:
            pass
        return 0

    @pydantic.computed_field(description="Status")
    @property
    def status(self) -> str:
        if self.end_time:
            return "stopped" if self.cancelled else "completed"
        elif self.start_time:
            if self.duration > 1 and self.rate == 0:
                return "stopped"
            return "in progress"
        else:
            return "pending"

    @pydantic.computed_field(description="Age")
    @property
    def age(self) -> float:
        if not self.end_time:
            return -1
        return time.time() - self.end_time


@dataclasses.dataclass
class ClientEmbeddingsStatus:
    client: "ClientBase | None" = None
    embedding_name: str | None = None
    seen: bool = False


@dataclasses.dataclass
class ClientStatus:
    client: "ClientBase | None" = None
    enabled: bool = False


async_signals.register(
    "client.embeddings_available",
    "client.enabled",
    "client.disabled",
)


def clean_client_name(name: str) -> str:
    return name.replace(" ", "_")


def locked_model_template(client_name: str, model_name: str) -> str:
    return f"{clean_client_name(client_name)}__LOCK"


class ClientBase:
    name: str
    remote_model_name: str | None = None
    remote_model_locked: bool = False
    current_status: str = None
    processing: bool = False
    connected: bool = False
    conversation_retries: int = 0
    decensor_enabled: bool = True
    auto_determine_prompt_template: bool = False
    finalizers: list[str] = []
    client_type = "base"
    request_information: RequestInformation | None = None
    status_request_timeout: int = 2
    rate_limit_counter: CounterRateLimiter = None

    class Meta(pydantic.BaseModel):
        experimental: Union[None, str] = None
        defaults: Defaults = Defaults()
        title: str = "Client"
        name_prefix: str = "Client"
        enable_api_auth: bool = False
        requires_prompt_template: bool = True
        unified_api_key_config_path: str | None = None
        # Whether this client is typically self-hosted (you run/control the service)
        # versus a hosted API (3rd-party provider).
        #
        # Set to:
        # - True: self-hosted
        # - False: hosted API
        # - None: either (depends on where you point the endpoint)
        self_hosted: bool | None = False

    def __init__(
        self,
        name: str = None,
        **kwargs,
    ):
        self.name = name or self.client_type
        self.remote_model_name = None
        self.auto_determine_prompt_template_attempt = None
        self.log = structlog.get_logger(f"client.{self.client_type}")

    def __str__(self):
        return f"{self.client_type}Client[{self.api_url}][{self.model_name or ''}]"

    #####

    # config getters

    @property
    def config(self) -> Config:
        return get_config()

    @property
    def client_config(self) -> ClientConfig:
        try:
            return get_config().clients[self.name]
        except KeyError:
            config_cls = getattr(self, "config_cls", ClientConfig)
            return config_cls(type=self.client_type, name=self.name)

    @property
    def model(self) -> str | None:
        return self.client_config.model

    @property
    def model_name(self) -> str | None:
        if self.remote_model_locked:
            return self.remote_model_name
        return self.remote_model_name or self.model

    @property
    def api_key(self) -> str | None:
        return self.client_config.api_key

    @property
    def api_url(self) -> str | None:
        return self.client_config.api_url

    @property
    def max_token_length(self) -> int:
        return self.client_config.max_token_length

    @property
    def double_coercion(self) -> str | None:
        return self.client_config.double_coercion

    @property
    def rate_limit(self) -> int | None:
        return self.client_config.rate_limit

    @property
    def data_format(self) -> Literal["yaml", "json"]:
        return self.client_config.data_format

    @property
    def enabled(self) -> bool:
        return self.client_config.enabled

    @property
    def system_prompts(self) -> SystemPrompts:
        return self.client_config.system_prompts

    @property
    def preset_group(self) -> str | None:
        return self.client_config.preset_group

    @property
    def reason_enabled(self) -> bool:
        return self.client_config.reason_enabled

    @property
    def reason_tokens(self) -> int:
        return self.client_config.reason_tokens

    @property
    def reason_response_pattern(self) -> str:
        return self.client_config.reason_response_pattern or DEFAULT_REASONING_PATTERN

    @property
    def reason_prefill(self) -> str:
        return self.client_config.reason_prefill or ""

    @property
    def reason_failure_behavior(self) -> str:
        return self.client_config.reason_failure_behavior

    @property
    def lock_template(self) -> bool:
        return self.client_config.lock_template

    #####

    @property
    def experimental(self):
        return False

    @property
    def can_be_coerced(self):
        """
        Determines whether or not his client can pass LLM coercion. (e.g., is able
        to predefine partial LLM output in the prompt)
        """
        if self.reason_enabled:
            # We are not able to coerce via pre-filling if reasoning is enabled
            return False
        return self.Meta().requires_prompt_template

    @property
    def can_think(self) -> bool:
        """
        Allow reasoning models to think before responding.
        """
        return False

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

    @property
    def supports_embeddings(self) -> bool:
        return False

    @property
    def can_support_concurrent_inference(self) -> bool:
        """
        Whether the client is technically capable of handling concurrent inference requests.
        This is a read-only property determined by the client implementation.
        """
        return False

    @property
    def concurrent_inference_enabled(self) -> bool:
        """
        Whether concurrent inference is enabled in the configuration.
        Users can only enable this if can_support_concurrent_inference is True.
        """
        return getattr(self.client_config, "concurrent_inference_enabled", False)

    @property
    def supports_concurrent_inference(self) -> bool:
        """
        Final determination of whether concurrent inference is active.
        Considers both capability and user configuration.
        """
        return (
            self.can_support_concurrent_inference and self.concurrent_inference_enabled
        )

    @property
    def embeddings_function(self):
        return None

    @property
    def embeddings_status(self) -> bool:
        return getattr(self, "_embeddings_status", False)

    @property
    def embeddings_model_name(self) -> str | None:
        return getattr(self, "_embeddings_model_name", None)

    @property
    def embeddings_url(self) -> str:
        return None

    @property
    def embeddings_identifier(self) -> str:
        return f"client-api/{self.name}/{self.embeddings_model_name}"

    @property
    def reasoning_response(self) -> str | None:
        return getattr(self, "_reasoning_response", None)

    @property
    def min_reason_tokens(self) -> int:
        return 0

    @property
    def reason_locked(self) -> bool:
        """
        Returns True if the model always requires reasoning and it cannot be disabled.
        """
        return False

    @property
    def validated_reason_tokens(self) -> int:
        return max(self.reason_tokens, self.min_reason_tokens)

    @property
    def default_prompt_template(self) -> str:
        return DEFAULT_TEMPLATE

    @property
    def requires_reasoning_pattern(self) -> bool:
        return True

    async def enable(self):
        self.client_config.enabled = True
        self.emit_status()

        await self.config.set_dirty()
        await self.status()
        await async_signals.get("client.enabled").send(
            ClientStatus(client=self, enabled=True)
        )

    async def disable(self):
        self.client_config.enabled = False
        self.emit_status()

        if self.supports_embeddings:
            await self.reset_embeddings()
        await self.config.set_dirty()
        await self.status()
        await async_signals.get("client.disabled").send(
            ClientStatus(client=self, enabled=False)
        )

    async def destroy(self):
        """
        This is called before the client is removed from talemate.instance.clients

        Use this to perform any cleanup that is necessary.

        If a subclass overrides this method, it should call super().destroy(config) in the
        end of the method.
        """

        if self.supports_embeddings:
            await self.remove_embeddings()

    async def reset_embeddings(self):
        self._embeddings_model_name = None
        self._embeddings_status = False

    async def set_embeddings(self):
        log.debug(
            "setting embeddings",
            client=self.name,
            supports_embeddings=self.supports_embeddings,
            embeddings_status=self.embeddings_status,
        )

        if not self.supports_embeddings or not self.embeddings_status:
            return

        config: Config = get_config()

        key = self.embeddings_identifier

        if key in config.presets.embeddings:
            log.debug("embeddings already set", client=self.name, key=key)
            return config.presets.embeddings[key]

        log.debug("setting embeddings", client=self.name, key=key)

        config.presets.embeddings[key] = EmbeddingFunctionPreset(
            embeddings="client-api",
            client=self.name,
            model=self.embeddings_model_name,
            distance=1,
            distance_function="cosine",
            local=False,
            custom=True,
        )

        await config.set_dirty()

    async def remove_embeddings(self):
        # remove all embeddings for this client
        config: Config = get_config()
        for key, value in list(config.presets.embeddings.items()):
            if value.client == self.name and value.embeddings == "client-api":
                log.warning("!!! removing embeddings", client=self.name, key=key)
                config.presets.embeddings.pop(key)
                await config.set_dirty()

    def prompt_template(self, sys_msg: str, prompt: str):
        """
        Applies the appropriate prompt template for the model.
        """

        if not self.Meta().requires_prompt_template:
            return prompt

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

        if self.reason_enabled and self.reason_prefill:
            # if reasoning is enabled and a reason prefill is set, prepend it to the double coercion
            # its important that it comes first.
            if not double_coercion:
                double_coercion = self.reason_prefill
            else:
                double_coercion = f"{self.reason_prefill}{double_coercion}"

        spec = PromptSpec()

        model_name = self.model_name
        if self.lock_template:
            model_name = locked_model_template(self.name, self.model_name)

        prompt = model_prompt(
            model_name,
            sys_msg,
            prompt,
            double_coercion,
            default_template=self.default_prompt_template,
            reasoning_tokens=self.validated_reason_tokens if self.reason_enabled else 0,
            spec=spec,
        )[0]

        if (
            spec.reasoning_pattern
            and spec.reasoning_pattern != self.reason_response_pattern
        ):
            log.info("reasoning pattern determined from prompt template", spec=spec)
            self.client_config.reason_response_pattern = spec.reasoning_pattern

        return prompt

    def prompt_template_example(self):
        if not getattr(self, "model_name", None):
            return None, None

        if not self.enabled:
            return None, None

        model_name = self.model_name
        if self.lock_template:
            model_name = locked_model_template(self.name, self.model_name)

        return model_prompt(
            model_name,
            "{sysmsg}",
            "{prompt}<|BOT|>{LLM coercion}",
            default_template=self.default_prompt_template,
            reasoning_tokens=self.validated_reason_tokens if self.reason_enabled else 0,
        )

    def split_prompt_for_coercion(self, prompt: str) -> tuple[str, str]:
        """
        Splits the prompt and the prefill/coercion prompt.
        """
        if "<|BOT|>" in prompt:
            prompt, coercion = prompt.split("<|BOT|>", 1)

            if self.double_coercion:
                coercion = f"{self.double_coercion}\n\n{coercion}"

            return prompt, coercion
        return prompt, None

    def rate_limit_update(self):
        """
        Updates the rate limit counter for the client.

        If the rate limit is set to 0, the rate limit counter is set to None.
        """
        if self.rate_limit:
            if not self.rate_limit_counter:
                self.rate_limit_counter = CounterRateLimiter(
                    rate_per_minute=self.rate_limit
                )
            else:
                self.rate_limit_counter.update_rate_limit(self.rate_limit)
        else:
            self.rate_limit_counter = None

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
        config: Config = get_config()
        personas: dict | None = None

        try:
            scene: "Scene" = active_scene.get()
            if scene:
                personas: dict = {
                    agent_type: persona.formatted("instructions", scene, agent_type)
                    for agent_type, persona in scene.agent_personas.items()
                }
        except LookupError:
            pass

        alias = self.system_prompts.alias(kind)
        self.system_prompts.parent = config.system_prompts

        sys_prompt = self.system_prompts.get(kind, self.decensor_enabled)

        if personas and alias in personas:
            log.debug("adding persona instructions", agent=alias)
            sys_prompt = f"{sys_prompt}\n\n{personas[alias]}"

        return sys_prompt

    def emit_status(self, processing: bool = None):
        """
        Sets and emits the client status.
        """
        error_message: str | None = None

        if processing is not None:
            self.processing = processing

        if not self.enabled:
            status = "disabled"
            error_message = "Disabled"
        elif not self.connected:
            status = "error"
            error_message = "Could not connect"
        elif self.model_name:
            status = "busy" if self.processing else "idle"
        else:
            error_message = "No model loaded"
            status = "warning"

        status_change = status != self.current_status
        self.current_status = status

        default_prompt_template = self.default_prompt_template

        prompt_template_example, prompt_template_file = self.prompt_template_example()
        has_prompt_template = (
            prompt_template_file and prompt_template_file != default_prompt_template
        )

        if (
            not has_prompt_template
            and self.auto_determine_prompt_template
            and self.enabled
        ):
            # only attempt to determine the prompt template once per model and
            # only if the model does not already have a prompt template

            if (
                hasattr(self, "model_name")
                and self.auto_determine_prompt_template_attempt != self.model_name
            ):
                log.debug("auto_determine_prompt_template", model_name=self.model_name)
                self.auto_determine_prompt_template_attempt = self.model_name
                self.determine_prompt_template()
                prompt_template_example, prompt_template_file = (
                    self.prompt_template_example()
                )
                has_prompt_template = (
                    prompt_template_file
                    and prompt_template_file != default_prompt_template
                )

        dedicated_default_template = default_prompt_template != DEFAULT_TEMPLATE

        data = {
            "prompt_template_example": prompt_template_example,
            "has_prompt_template": has_prompt_template,
            "dedicated_default_template": dedicated_default_template,
            "template_file": prompt_template_file,
            "meta": self.Meta().model_dump(),
            "error_action": None,
            "double_coercion": self.double_coercion,
            "enabled": self.enabled,
            "error_message": error_message,
        }

        if self.Meta().enable_api_auth:
            data["api_key"] = self.api_key

        data.update(self._common_status_data())

        for field_name in getattr(self.Meta(), "extra_fields", {}).keys():
            data[field_name] = getattr(self, field_name, None)

        data = self.finalize_status(data)

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=self.model_name,
            status=status,
            data=data,
        )

        if status_change:
            instance.emit_agent_status_by_client(self)

    def finalize_status(self, data: dict):
        """
        Finalizes the status data for the client.
        """
        return data

    def _common_status_data(self):
        common_data = {
            "can_be_coerced": self.can_be_coerced,
            "preset_group": self.preset_group or "",
            "rate_limit": self.rate_limit,
            "data_format": self.data_format,
            "manual_model_choices": getattr(self.Meta(), "manual_model_choices", []),
            "supports_embeddings": self.supports_embeddings,
            "embeddings_status": self.embeddings_status,
            "embeddings_model_name": self.embeddings_model_name,
            "can_support_concurrent_inference": self.can_support_concurrent_inference,
            "supports_concurrent_inference": self.supports_concurrent_inference,
            "reason_enabled": self.reason_enabled,
            "reason_tokens": self.reason_tokens,
            "min_reason_tokens": self.min_reason_tokens,
            "reason_response_pattern": self.reason_response_pattern,
            "reason_prefill": self.reason_prefill,
            "reason_failure_behavior": self.reason_failure_behavior,
            "requires_reasoning_pattern": self.requires_reasoning_pattern,
            "reason_locked": self.reason_locked,
            "request_information": self.request_information.model_dump()
            if self.request_information
            else None,
            "lock_template": self.lock_template,
            "system_prompts": self.system_prompts.model_dump(),
        }

        extra_fields = getattr(self.Meta(), "extra_fields", {})
        for field_name in extra_fields.keys():
            common_data[field_name] = getattr(self, field_name, None)

        return common_data

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
        models = await self.client.models.list(timeout=self.status_request_timeout)
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
            self.emit_status()
            return

        if not self.enabled:
            self.connected = False
            self.emit_status()
            return

        try:
            self.remote_model_name = await self.get_model_name()
        except Exception as e:
            self.log.debug(
                "client status error", e=traceback.format_exc(), client=self.name
            )
            self.log.warning("client status error", e=e, client=self.name)
            self.remote_model_name = None
            self.connected = False
            self.emit_status()
            return

        self.connected = True

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

        if self.reason_enabled and self.reason_tokens > 0:
            log.debug(
                "padding for reasoning",
                client=self.client_type,
                reason_tokens=self.reason_tokens,
                validated_reason_tokens=self.validated_reason_tokens,
            )
            parameters["max_tokens"] += self.validated_reason_tokens

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

        requires_active_scene = client_context_attribute("requires_active_scene")

        async def poll():
            while True:
                scene = active_scene.get()
                if requires_active_scene and (
                    not scene or not scene.active or scene.cancel_requested
                ):
                    break
                await asyncio.sleep(0.3)
            return GenerationCancelled("Generation cancelled")

        return asyncio.create_task(poll())

    async def _cancelable_generate(
        self, prompt: str, parameters: dict, kind: str
    ) -> str | GenerationCancelled:
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
            [task_poll, task_generate], return_when=asyncio.FIRST_COMPLETED
        )

        # cancel the remaining task
        for task in pending:
            task.cancel()

        # return the result of the completed task
        return done.pop().result()

    async def abort_generation(self):
        """
        This function can be overwritten to trigger an abortion at the other
        side of the client.

        So a generation is cancelled here, this can be used to cancel a generation
        at the other side of the client.
        """
        pass

    def new_request(self):
        """
        Creates a new request information object.
        """
        self.request_information = RequestInformation()

    def end_request(self):
        """
        Ends the request information object.
        """
        self.request_information.end_time = time.time()

    def update_request_tokens(self, tokens: int, replace: bool = False):
        """
        Updates the request information object with the number of tokens received.
        """
        if self.request_information:
            if replace:
                self.request_information.tokens = tokens
            else:
                self.request_information.tokens += tokens

            # Set first_token_time when tokens first become > 0
            if (
                self.request_information.tokens > 0
                and self.request_information.first_token_time is None
            ):
                self.request_information.first_token_time = time.time()

    def strip_coercion_prompt(self, response: str, coercion_prompt: str = None) -> str:
        """
        Strips the coercion prompt from the response if it is present.
        """
        if not coercion_prompt or not response.startswith(coercion_prompt):
            return response

        return response.replace(coercion_prompt, "").lstrip()

    def strip_reasoning(self, response: str) -> tuple[str, str]:
        """
        Strips the reasoning from the response if the model is reasoning.
        """

        if not self.reason_enabled:
            return response, None

        if not self.requires_reasoning_pattern:
            # reasoning handled automatically during streaming
            return response, None

        pattern = self.reason_response_pattern
        if not pattern:
            pattern = DEFAULT_REASONING_PATTERN

        log.debug("reasoning pattern", pattern=pattern)

        extract_reason = re.search(pattern, response, re.DOTALL)

        if extract_reason:
            reasoning_response = extract_reason.group(0)
            return response.replace(reasoning_response, ""), reasoning_response

        log.warning("reasoning pattern not found", pattern=pattern, response=response)
        if self.reason_failure_behavior == "ignore":
            return response, None
        raise ReasoningResponseError()

    def attach_response_length_instruction(
        self, prompt: str, response_length: int | None
    ) -> str:
        """
        Attaches the response length instruction to the prompt.
        """

        if not response_length or response_length < 0:
            log.warning("response length instruction", response_length=response_length)
            return prompt

        instructions_prompt = Prompt.get(
            "common.response-length",
            vars={
                "response_length": response_length,
                "attach_response_length_instruction": True,
            },
        )

        instructions_prompt = instructions_prompt.render()

        if instructions_prompt.strip() in prompt:
            log.debug(
                "response length instruction already in prompt",
                instructions_prompt=instructions_prompt,
            )
            return prompt

        log.debug(
            "response length instruction", instructions_prompt=instructions_prompt
        )

        if "<|RESPONSE_LENGTH_INSTRUCTIONS|>" in prompt:
            return prompt.replace(
                "<|RESPONSE_LENGTH_INSTRUCTIONS|>", instructions_prompt
            )
        elif "<|BOT|>" in prompt:
            return prompt.replace("<|BOT|>", f"{instructions_prompt}<|BOT|>")
        else:
            return f"{prompt}{instructions_prompt}"

    async def send_prompt(
        self,
        prompt: str,
        kind: str = "conversation",
        finalize: Callable = lambda x: x,
        retries: int = 2,
        data_expected: bool | None = None,
    ) -> str:
        """
        Send a prompt to the AI and return its response.
        :param prompt: The text prompt to send.
        :return: The AI's response text.
        """

        try:
            return await self._send_prompt(
                prompt, kind, finalize, retries, data_expected
            )
        except GenerationCancelled:
            await self.abort_generation()
            raise

    async def _send_prompt(
        self,
        prompt: str,
        kind: str = "conversation",
        finalize: Callable = lambda x: x,
        retries: int = 2,
        data_expected: bool | None = None,
    ) -> str:
        """
        Send a prompt to the AI and return its response.
        :param prompt: The text prompt to send.
        :return: The AI's response text.
        """

        try:
            self.rate_limit_update()
            if self.rate_limit_counter:
                aborted: bool = False
                while not self.rate_limit_counter.increment():
                    log.warn("Rate limit exceeded", client=self.name)
                    emit(
                        "rate_limited",
                        message="Rate limit exceeded",
                        status="error",
                        websocket_passthrough=True,
                        data={
                            "client": self.name,
                            "rate_limit": self.rate_limit,
                            "reset_time": self.rate_limit_counter.reset_time(),
                        },
                    )

                    scene = active_scene.get()
                    if not scene or not scene.active or scene.cancel_requested:
                        log.info(
                            "Rate limit exceeded, generation cancelled",
                            client=self.name,
                        )
                        aborted = True
                        break

                    await asyncio.sleep(1)

                emit(
                    "rate_limit_reset",
                    message="Rate limit reset",
                    status="info",
                    websocket_passthrough=True,
                    data={"client": self.name},
                )

                if aborted:
                    raise GenerationCancelled("Generation cancelled")
        except GenerationCancelled:
            raise
        except Exception:
            log.error("Error during rate limit check", e=traceback.format_exc())

        if client_context_attribute("requires_active_scene"):
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
            self._reasoning_response = None

            self.emit_status(processing=True)
            await self.status()

            prompt_param = self.generate_prompt_parameters(kind)

            if self.reason_enabled and not data_expected:
                prompt = self.attach_response_length_instruction(
                    prompt,
                    (prompt_param.get(self.max_tokens_param_name) or 0)
                    - self.reason_tokens,
                )

            if not self.can_be_coerced:
                prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
                if coercion_prompt:
                    coercion_instruction = (
                        INDIRECT_COERCION_PROMPT_REASONING
                        if self.reason_enabled
                        else INDIRECT_COERCION_PROMPT
                    )
                    prompt += f"{coercion_instruction}{coercion_prompt}"
            else:
                coercion_prompt = None

            finalized_prompt = self.prompt_template(
                self.get_system_message(kind), prompt
            ).strip(" ")

            finalized_prompt = self.finalize(prompt_param, finalized_prompt)

            prompt_param = finalize(prompt_param)

            token_length = self.count_tokens(finalized_prompt)

            time_start = time.time()
            extra_stopping_strings = prompt_param.pop("extra_stopping_strings", [])

            self.clean_prompt_parameters(prompt_param)

            self.log.info(
                "Sending prompt",
                token_length=token_length,
                max_token_length=self.max_token_length,
                parameters=prompt_param,
            )

            if "<|RESPONSE_LENGTH_INSTRUCTIONS|>" in finalized_prompt:
                finalized_prompt = finalized_prompt.replace(
                    "\n<|RESPONSE_LENGTH_INSTRUCTIONS|>", ""
                )

            self.new_request()

            response = await self._cancelable_generate(
                finalized_prompt, prompt_param, kind
            )

            if isinstance(response, GenerationCancelled):
                # generation was cancelled
                raise response

            response, reasoning_response = self.strip_reasoning(response)
            if reasoning_response:
                self._reasoning_response = reasoning_response

            if coercion_prompt:
                response = self.process_response_for_indirect_coercion(
                    finalized_prompt, response, coercion_prompt
                )

            self.end_request()

            if isinstance(response, GenerationCancelled):
                # TODO: is this check necessary? why would the response be a GenerationCancelled at his point?
                # generation was cancelled
                raise response

            if REPLACE_SMART_QUOTES:
                response = (
                    response.replace("“", '"')
                    .replace("”", '"')
                    .replace("‘", "'")
                    .replace("’", "'")
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
                    prompt=finalized_prompt,
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
                    preset_group=self.preset_group,
                    reasoning=self._reasoning_response,
                ).model_dump(),
            )

            return response
        except GenerationCancelled:
            # Finalize request timing so the token rate doesn't decay to ~0 after cancellation.
            # This also ensures the next emitted `client_status` contains stable request stats.
            if self.request_information and self.request_information.end_time is None:
                self.request_information.cancelled = True
                self.end_request()
            raise
        except GenerationProcessingError as e:
            self.log.error("send_prompt error", e=e)
            emit("status", message=str(e), status="error")
            return ""
        except Exception:
            self.log.error("send_prompt error", e=traceback.format_exc())
            emit(
                "status", message="Error during generation (check logs)", status="error"
            )
            return ""
        finally:
            self.emit_status(processing=False)
            self._returned_prompt_tokens = None
            self._returned_response_tokens = None

            if self.rate_limit_counter:
                self.rate_limit_counter.increment()

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

    def process_response_for_indirect_coercion(
        self, prompt: str, response: str, coercion_prompt: str
    ) -> str:
        """
        A lot of remote APIs don't let us control the prompt template and we cannot directly
        append the beginning of the desired response to the prompt.

        With indirect coercion we tell the LLM what the beginning of the response should be
        and then hopefully it will adhere to it and we can strip it off the actual response.
        """

        if coercion_prompt and coercion_prompt.startswith("{"):
            if response.startswith("```json") and response.endswith("```"):
                response = response[7:-3].strip()

        log.debug(
            "process_response_for_indirect_coercion",
            response=f"|{response[:100]}...|",
            coercion_prompt=f"|{coercion_prompt}|",
        )

        if coercion_prompt and response.startswith(coercion_prompt):
            response = response[len(coercion_prompt) :].strip()
        elif coercion_prompt and response.lstrip().startswith(coercion_prompt):
            response = response.lstrip()[len(coercion_prompt) :].strip()

        return response
