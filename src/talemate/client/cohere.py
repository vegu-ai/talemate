import pydantic
import structlog
from openai import AsyncOpenAI

from talemate.client.base import ClientBase, ErrorAction, ParameterReroute, CommonDefaults, ExtraField
from talemate.client.registry import register
from talemate.client.remote import (
    EndpointOverride,
    EndpointOverrideMixin,
    endpoint_override_extra_fields,
)
from talemate.config import Client as BaseClientConfig, load_config
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.util import count_tokens

__all__ = [
    "CohereClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "command",
    "command-light",
    "command-r",
    "command-r-plus",
    "command-r-plus-08-2024",
    "command-r7b-12-2024",
    "command-a-03-2025",
]


class Defaults(EndpointOverride, CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "command-r-plus"


class ClientConfig(EndpointOverride, BaseClientConfig):
    pass


@register()
class CohereClient(EndpointOverrideMixin, ClientBase):
    """
    Cohere client for generating text.
    """

    client_type = "cohere"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    decensor_enabled = True
    config_cls = ClientConfig
    
    class Meta(ClientBase.Meta):
        name_prefix: str = "Cohere"
        title: str = "Cohere"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        extra_fields: dict[str, ExtraField] = endpoint_override_extra_fields()
        defaults: Defaults = Defaults()

    def __init__(self, model="command-r-plus", **kwargs):
        self.model_name = model
        self.api_key_status = None
        self._reconfigure_endpoint_override(**kwargs)
        self.config = load_config()
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def cohere_api_key(self):
        return self.config.get("cohere", {}).get("api_key")

    @property
    def supported_parameters(self):
        return [
            "temperature",
            ParameterReroute(talemate_parameter="top_p", client_parameter="p"),
            ParameterReroute(talemate_parameter="top_k", client_parameter="k"),
            ParameterReroute(
                talemate_parameter="stopping_strings", client_parameter="stop_sequences"
            ),
            "frequency_penalty",
            "presence_penalty",
            "max_tokens",
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.cohere_api_key:
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
                    "cohere_api",
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
        if not self.cohere_api_key and not self.endpoint_override_base_url_configured:
            log.error("No cohere API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "command-r-plus"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        model = self.model_name

        # Use AsyncOpenAI with Cohere's base URL
        # Cohere provides an OpenAI-compatible API
        cohere_base_url = self.base_url or "https://api.cohere.com/v1"
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=cohere_base_url
        )
        self.max_token_length = max_token_length or 16384

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "cohere set client",
            max_token_length=self.max_token_length,
            provided_max_token_length=max_token_length,
            model=model,
        )

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))

        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])
            
        self._reconfigure_common_parameters(**kwargs)
        self._reconfigure_endpoint_override(**kwargs)

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    def response_tokens(self, response: str):
        return count_tokens(response)

    def prompt_tokens(self, prompt: str):
        return count_tokens(prompt)

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

        # if temperature is set, it needs to be clamped between 0 and 1.0
        if "temperature" in parameters:
            parameters["temperature"] = max(0.0, min(1.0, parameters["temperature"]))

        # if stop_sequences is set, max 5 items
        if "stop_sequences" in parameters:
            parameters["stop_sequences"] = parameters["stop_sequences"][:5]

        # if both frequency_penalty and presence_penalty are set, drop frequency_penalty
        if "presence_penalty" in parameters and "frequency_penalty" in parameters:
            del parameters["frequency_penalty"]

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters using OpenAI-compatible API.
        """

        if not self.cohere_api_key and not self.endpoint_override_base_url_configured:
            raise Exception("No cohere API key set")

        # Check for coercion
        prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        
        # Prepare messages for chat completion
        system_message = self.get_system_message(kind)
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt.strip()}
        ]
        
        if coercion_prompt:
            messages.append({"role": "assistant", "content": coercion_prompt.strip()})

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        # Convert stop_sequences to stop for OpenAI API
        if "stop_sequences" in parameters:
            parameters["stop"] = parameters.pop("stop_sequences")

        try:
            # Use streaming for token tracking
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=True,
                **parameters
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

            self._returned_prompt_tokens = prompt_tokens or self.prompt_tokens(prompt)
            self._returned_response_tokens = completion_tokens or self.response_tokens(response)

            log.debug("generated response", response=response)

            # Handle JSON response formatting
            if coercion_prompt and coercion_prompt.strip().startswith("{"):
                if response.startswith("```json") and response.endswith("```"):
                    response = response[7:-3].strip()

            return response
            
        except Exception as e:
            self.log.error("generate error", e=e)
            if hasattr(e, '__class__') and hasattr(e.__class__, '__name__'):
                if 'permission' in str(e).lower() or e.__class__.__name__ == 'PermissionDeniedError':
                    emit("status", message="cohere API: Permission Denied", status="error")
                    return ""
            raise
