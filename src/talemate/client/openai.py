import json
from typing import Literal

import pydantic
import structlog
import tiktoken
from openai import AsyncOpenAI

from talemate.client.base import (
    ClientBase,
    ErrorAction,
    CommonDefaults,
    ExtraField,
    FieldGroup,
)
from talemate.client.registry import register
from talemate.client.reasoning_effort import (
    ReasoningEffortConfig,
    ReasoningEffortMixin,
    reasoning_effort_extra_fields,
)
from talemate.client.toggleable_parameters import (
    PARAMETERS_FIELD_GROUP,
    ToggleableParametersMixin,
    toggleable_parameters_config,
    toggleable_parameters_extra_fields,
)
from talemate.client.remote import (
    EndpointOverride,
    EndpointOverrideMixin,
    endpoint_override_extra_fields,
    ConcurrentInferenceMixin,
    ConcurrentInference,
    concurrent_inference_extra_fields,
)
from talemate.config.schema import Client as BaseClientConfig
from talemate.emit import emit

__all__ = [
    "OpenAIClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo",
    "gpt-4",
    "gpt-4-turbo",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "o1",
    "o3",
    "o3-mini",
    "o4-mini",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5.1",
    "gpt-5.2",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.5",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-6-astra",
    "gpt-6-luna",
    "gpt-6-sol",
    "chat-latest",
]


def num_tokens_from_messages(messages: list[dict], model: str = "gpt-3.5-turbo-0613"):
    """Estimate message tokens using the model encoding or a cl100k_base fallback."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    tokens_per_message = 3
    tokens_per_name = 1
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


DEFAULT_MODEL = "gpt-4o"
TOGGLEABLE_PARAMETERS = ("temperature", "top_p", "presence_penalty")
ToggleableParametersConfig = toggleable_parameters_config(
    TOGGLEABLE_PARAMETERS, default=False
)


class OpenAIRequestConfig(pydantic.BaseModel):
    stream: bool = True
    send_system_message: bool = True
    completion_token_parameter: Literal["max_tokens", "max_completion_tokens"] = (
        "max_completion_tokens"
    )


class Defaults(
    OpenAIRequestConfig,
    ReasoningEffortConfig,
    ToggleableParametersConfig,
    EndpointOverride,
    CommonDefaults,
    pydantic.BaseModel,
):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL
    # Seed new clients with room for reasoning; saved clients retain their setting.
    reason_enabled: bool = True
    reason_tokens: int = 1024


class ClientConfig(
    OpenAIRequestConfig,
    ReasoningEffortConfig,
    ToggleableParametersConfig,
    ConcurrentInference,
    EndpointOverride,
    BaseClientConfig,
):
    concurrent_inference_enabled: bool = True


@register()
class OpenAIClient(
    ReasoningEffortMixin,
    ToggleableParametersMixin,
    ConcurrentInferenceMixin,
    EndpointOverrideMixin,
    ClientBase,
):
    """
    OpenAI client for generating text.
    """

    client_type = "openai"
    conversation_retries = 0
    # TODO: make this configurable?
    decensor_enabled = False
    config_cls = ClientConfig
    toggleable_parameters = TOGGLEABLE_PARAMETERS

    class Meta(ClientBase.Meta):
        name_prefix: str = "OpenAI"
        title: str = "OpenAI"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        reason_tokens_as_allowance: bool = True
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = reasoning_effort_extra_fields()
        extra_fields.update(toggleable_parameters_extra_fields(TOGGLEABLE_PARAMETERS))
        extra_fields.update(
            send_system_message=ExtraField(
                name="send_system_message",
                type="bool",
                label="Send System Message",
                description="Include the system message. Disable for a server that rejects the system role; Talemate will send only the user message.",
                group=PARAMETERS_FIELD_GROUP,
                required=False,
            ),
            stream=ExtraField(
                name="stream",
                type="bool",
                label="Stream",
                description="Stream responses as they arrive. Disable if your organization or server does not support streaming for the selected model.",
                group=PARAMETERS_FIELD_GROUP,
                required=False,
            ),
            completion_token_parameter=ExtraField(
                name="completion_token_parameter",
                type="text",
                label="Completion Token Parameter",
                choices=["max_tokens", "max_completion_tokens"],
                description="Choose the parameter your server accepts for the total completion limit. Keep 'max_completion_tokens' for OpenAI; an Override Base URL server may need 'max_tokens'. Includes extra completion tokens when reasoning is enabled.",
                group=FieldGroup(name="reasoning", label="Reasoning", icon="mdi-brain"),
                required=False,
            ),
        )
        extra_fields.update(endpoint_override_extra_fields())
        extra_fields.update(concurrent_inference_extra_fields())
        unified_api_key_config_path: str = "openai.api_key"

    @property
    def openai_api_key(self):
        return self.config.openai.api_key

    @property
    def stream(self) -> bool:
        return self.client_config.stream

    @property
    def send_system_message(self) -> bool:
        return self.client_config.send_system_message

    @property
    def completion_token_parameter(
        self,
    ) -> Literal["max_tokens", "max_completion_tokens"]:
        return self.client_config.completion_token_parameter

    @property
    def requires_reasoning_pattern(self) -> bool:
        return False

    @property
    def reasoning_effort_enabled_configured(self) -> bool:
        return True

    @property
    def reason_locked(self) -> bool:
        return (self.model_name or "").startswith(("gpt-5", "gpt-6"))

    @property
    def reason_enabled_configured(self) -> bool:
        return self.reason_locked or super().reason_enabled_configured

    def emit_status(self, processing: bool = None):
        error_action = None
        error_message = None
        if processing is not None:
            self.processing = processing

        if self.openai_api_key:
            status = "busy" if self.processing else "idle"
        else:
            status = "error"
            error_message = "No API key set"
            error_action = ErrorAction(
                title="Set API Key",
                action_name="openAppConfig",
                icon="mdi-key-variant",
                arguments=[
                    "application",
                    "openai_api",
                ],
            )

        if not self.model_name:
            status = "error"
            error_message = "No model loaded"

        self.current_status = status

        data = {
            "error_action": error_action.model_dump() if error_action else None,
            "meta": self.Meta().model_dump(),
            "enabled": self.enabled,
            "error_message": error_message,
        }
        data.update(self._common_status_data())

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=self.model_name,
            status=status if self.enabled else "disabled",
            data=data,
        )

    def count_tokens(self, content: str):
        if not self.model_name:
            return 0
        return num_tokens_from_messages([{"content": content}], model=self.model_name)

    async def status(self):
        self.emit_status()

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.openai_api_key and not self.endpoint_override_base_url_configured:
            raise Exception("No OpenAI API key set")

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

        human_message = {"role": "user", "content": prompt.strip()}
        system_message = {"role": "system", "content": self.get_system_message(kind)}

        messages = (
            [system_message, human_message]
            if self.send_system_message
            else [human_message]
        )
        if (
            self.completion_token_parameter == "max_completion_tokens"
            and "max_tokens" in parameters
        ):
            parameters["max_completion_tokens"] = parameters.pop("max_tokens")

        if self.reasoning_effort is not None:
            parameters["reasoning_effort"] = self.reasoning_effort

        self.log.debug(
            "generate",
            model=self.model_name,
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        stream_enabled = self.stream
        completion = await client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=stream_enabled,
            **parameters,
        )
        if not stream_enabled:
            if not completion.choices:
                return ""
            return self.record_whole_response(completion.choices[0].message.content)

        response = ""
        async for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and getattr(delta, "content", None):
                response += delta.content
                self.update_request_tokens(self.count_tokens(delta.content))
        return response
