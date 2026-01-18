import json

import pydantic
import structlog
import tiktoken
from openai import AsyncOpenAI, PermissionDeniedError

from talemate.client.base import ClientBase, ErrorAction, CommonDefaults, ExtraField
from talemate.client.registry import register
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
    "gpt-3.5-turbo-0613",
    "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo",
    "gpt-4",
    "gpt-4-1106-preview",
    "gpt-4-0125-preview",
    "gpt-4-turbo-preview",
    "gpt-4-turbo-2024-04-09",
    "gpt-4-turbo",
    "gpt-4o-2024-05-13",
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-11-20",
    "gpt-4o-realtime-preview",
    "gpt-4o-mini-realtime-preview",
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o1-preview",
    "o1-mini",
    "o3-mini",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
]


def num_tokens_from_messages(messages: list[dict], model: str = "gpt-3.5-turbo-0613"):
    # TODO this whole function probably needs to be rewritten at this point

    """Return the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
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
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613")
    elif "gpt-4" in model or "o1" in model or "o3" in model or "gpt-5" in model:
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


DEFAULT_MODEL = "gpt-4o"


class Defaults(EndpointOverride, CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL
    reason_tokens: int = 1024


class ClientConfig(ConcurrentInference, EndpointOverride, BaseClientConfig):
    pass


@register()
class OpenAIClient(ConcurrentInferenceMixin, EndpointOverrideMixin, ClientBase):
    """
    OpenAI client for generating text.
    """

    client_type = "openai"
    conversation_retries = 0
    # TODO: make this configurable?
    decensor_enabled = False
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "OpenAI"
        title: str = "OpenAI"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = {}
        extra_fields.update(endpoint_override_extra_fields())
        extra_fields.update(concurrent_inference_extra_fields())
        unified_api_key_config_path: str = "openai.api_key"

    @property
    def openai_api_key(self):
        return self.config.openai.api_key

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "presence_penalty",
            "max_tokens",
        ]

    @property
    def requires_reasoning_pattern(self) -> bool:
        return False

    def emit_status(self, processing: bool = None):
        error_action = None
        error_message = None
        if processing is not None:
            self.processing = processing

        # Auto-toggle reasoning based on selected model (OpenAI-specific)
        # o1/o3/gpt-5 families are reasoning models
        try:
            if self.model_name:
                is_reasoning_model = (
                    "o1" in self.model_name
                    or "o3" in self.model_name
                    or "gpt-5" in self.model_name
                )
                if self.client_config.reason_enabled != is_reasoning_model:
                    self.client_config.reason_enabled = is_reasoning_model
        except Exception:
            pass

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

        # o1 and o3 models don't support system_message
        if (
            "o1" in self.model_name
            or "o3" in self.model_name
            or "gpt-5" in self.model_name
        ):
            messages = [human_message]
            # paramters need to be munged
            # `max_tokens` becomes `max_completion_tokens`
            if "max_tokens" in parameters:
                parameters["max_completion_tokens"] = parameters.pop("max_tokens")

            # temperature forced to 1
            if "temperature" in parameters:
                log.debug(
                    f"{self.model_name} does not support temperature, forcing to 1"
                )
                parameters["temperature"] = 1

            unsupported_params = [
                "presence_penalty",
                "top_p",
            ]

            for param in unsupported_params:
                if param in parameters:
                    log.debug(f"{self.model_name} does not support {param}, removing")
                    parameters.pop(param)

        else:
            messages = [system_message, human_message]

        self.log.debug(
            "generate",
            model=self.model_name,
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        # GPT-5 models do not allow streaming for non-verified orgs; use non-streaming path
        if "gpt-5" in self.model_name:
            return await self._generate_non_streaming_completion(
                client, messages, parameters
            )

        try:
            stream = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=True,
                **parameters,
            )

            response = ""

            # Iterate over streamed chunks
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and getattr(delta, "content", None):
                    content_piece = delta.content
                    response += content_piece
                    # Incrementally track token usage
                    self.update_request_tokens(self.count_tokens(content_piece))

            return response
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="OpenAI API: Permission Denied", status="error")
            return ""
        except Exception:
            raise

    async def _generate_non_streaming_completion(
        self, client: AsyncOpenAI, messages: list[dict], parameters: dict
    ) -> str:
        """Perform a non-streaming chat completion request and return the content.

        This is used for GPT-5 models which disallow streaming for non-verified orgs.
        """
        try:
            response = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                # No stream flag -> non-streaming
                **parameters,
            )

            if not response.choices:
                return ""

            message = response.choices[0].message
            content = getattr(message, "content", "") or ""

            if content:
                # Update token usage based on the full content
                self.update_request_tokens(self.count_tokens(content))

            return content
        except PermissionDeniedError as e:
            self.log.error("generate (non-streaming) error", e=e)
            emit("status", message="OpenAI API: Permission Denied", status="error")
            return ""
        except Exception:
            raise
