import pydantic
import structlog
from typing import Literal
from openai import AsyncOpenAI

from talemate.client.base import ClientBase, ErrorAction, ParameterReroute, CommonDefaults, ExtraField
from talemate.client.instructor_mixin import InstructorMixin
from talemate.client.registry import register
from talemate.client.remote import (
    EndpointOverride,
    EndpointOverrideMixin,
    endpoint_override_extra_fields,
)
from talemate.config import Client as BaseClientConfig, load_config
from talemate.emit import emit
from talemate.emit.signals import handlers

__all__ = [
    "MistralAIClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "open-mistral-7b",
    "open-mixtral-8x7b",
    "open-mixtral-8x22b",
    "open-mistral-nemo",
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-latest",
]

JSON_OBJECT_RESPONSE_MODELS = [
    "open-mixtral-8x22b",
    "open-mistral-nemo",
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-latest",
]


class Defaults(EndpointOverride, CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "open-mixtral-8x22b"

class ClientConfig(EndpointOverride, BaseClientConfig):
    pass

@register()
class MistralAIClient(InstructorMixin, EndpointOverrideMixin, ClientBase):
    """
    OpenAI client for generating text.
    """

    client_type = "mistral"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    # TODO: make this configurable?
    decensor_enabled = True
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "MistralAI"
        title: str = "MistralAI"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = endpoint_override_extra_fields()
    
    def __init__(self, model="open-mixtral-8x22b", **kwargs):
        self.model_name = model
        self.api_key_status = None
        self._reconfigure_endpoint_override(**kwargs)
        self.config = load_config()
        super().__init__(**kwargs)
        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def mistral_api_key(self):
        return self.config.get("mistralai", {}).get("api_key")

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "max_tokens",
            ParameterReroute(
                talemate_parameter="stopping_strings", client_parameter="stop"
            ),
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.mistral_api_key:
            status = "busy" if self.processing else "idle"
            model_name = self.model_name
        else:
            status = "error"
            model_name = "No API key set"
            error_action = ErrorAction(
                title="Set API Key",
                action_name="openAppConfig",
                icon="mdi-key-variant",
                arguments=[
                    "application",
                    "mistralai_api",
                ],
            )

        if not self.model_name:
            status = "error"
            model_name = "No model loaded"

        self.current_status = status
        data={
            "error_action": error_action.model_dump() if error_action else None,
            "meta": self.Meta().model_dump(),
            "enabled": self.enabled,
        }
        data.update(self._common_status_data())
        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status if self.enabled else "disabled",
            data=data,
        )

    def set_client(self, max_token_length: int = None):
        if not self.mistral_api_key and not self.endpoint_override_base_url_configured:
            log.error("No mistral.ai API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "open-mixtral-8x22b"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        model = self.model_name

        # Use AsyncOpenAI with Mistral's base URL
        mistral_base_url = self.base_url or "https://api.mistral.ai/v1"
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=mistral_base_url)
        self.max_token_length = max_token_length or 16384
        
        # Setup instructor support
        self.setup_instructor()

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "mistral.ai set client",
            max_token_length=self.max_token_length,
            provided_max_token_length=max_token_length,
            model=model,
        )

    def reconfigure(self, **kwargs):
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])
        
        self._reconfigure_common_parameters(**kwargs)
        self._reconfigure_endpoint_override(**kwargs)
        
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    def response_tokens(self, response: str):
        return response.usage.completion_tokens

    def prompt_tokens(self, response: str):
        return response.usage.prompt_tokens

    async def status(self):
        self.emit_status()

    def prompt_template(self, system_message: str, prompt: str):
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>", "\nStart your response with: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")

        return prompt

    def clean_prompt_parameters(self, parameters: dict):
        super().clean_prompt_parameters(parameters)
        # clamp temperature to 0.1 and 1.0
        # Unhandled Error: Status: 422. Message: {"object":"error","message":{"detail":[{"type":"less_than_equal","loc":["body","temperature"],"msg":"Input should be less than or equal to 1","input":1.31,"ctx":{"le":1.0},"url":"https://errors.pydantic.dev/2.6/v/less_than_equal"}]},"type":"invalid_request_error","param":null,"code":null}
        if "temperature" in parameters:
            parameters["temperature"] = min(1.0, max(0.1, parameters["temperature"]))

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.mistral_api_key:
            raise Exception("No mistral.ai API key set")

        supports_json_object = self.model_name in JSON_OBJECT_RESPONSE_MODELS
        right = None
        expected_response = None
        try:
            _, right = prompt.split("\nStart your response with: ")
            expected_response = right.strip()
            if expected_response.startswith("{") and supports_json_object:
                parameters["response_format"] = {"type": "json_object"}
        except (IndexError, ValueError):
            pass

        system_message = self.get_system_message(kind)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt.strip()},
        ]

        self.log.debug(
            "generate",
            base_url=self.base_url,
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        try:
            # Clean parameters before sending
            self.clean_prompt_parameters(parameters)
            
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=True,
                **parameters,
            )

            response = ""
            completion_tokens = 0
            prompt_tokens = 0

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    response += content
                    self.update_request_tokens(self.count_tokens(content))
                
                # Some providers include usage data in chunks
                if hasattr(chunk, 'usage') and chunk.usage:
                    if hasattr(chunk.usage, 'completion_tokens'):
                        completion_tokens = chunk.usage.completion_tokens
                    if hasattr(chunk.usage, 'prompt_tokens'):
                        prompt_tokens = chunk.usage.prompt_tokens

            self._returned_prompt_tokens = prompt_tokens
            self._returned_response_tokens = completion_tokens

            # older models don't support json_object response coersion
            # and often like to return the response wrapped in ```json
            # so we strip that out if the expected response is a json object
            if (
                not supports_json_object
                and expected_response
                and expected_response.startswith("{")
            ):
                if response.startswith("```json") and response.endswith("```"):
                    response = response[7:-3].strip()

            if right and response.startswith(right):
                response = response[len(right) :].strip()

            return response
        except Exception as e:
            self.log.error("generate error", e=e)
            if hasattr(e, '__class__') and hasattr(e.__class__, '__name__'):
                if 'permission' in str(e).lower() or e.__class__.__name__ == 'PermissionDeniedError':
                    emit(
                        "status",
                        message="mistral.ai API: Permission Denied",
                        status="error",
                    )
                    return ""
            raise
