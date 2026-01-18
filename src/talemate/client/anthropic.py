import pydantic
import structlog
from anthropic import AsyncAnthropic, PermissionDeniedError

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
    "AnthropicClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "claude-3-haiku-20240307",
    "claude-3-sonnet-20240229",
    "claude-3-opus-20240229",
    "claude-3-5-sonnet-20240620",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
    "claude-3-7-sonnet-latest",
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-20250514",
    "claude-opus-4-1-20250805",
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-1",
]

DEFAULT_MODEL = "claude-haiku-4-5"
MIN_THINKING_TOKENS = 1024

LIMITED_PARAM_MODELS = [
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-1-20250805",
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-1",
]


class Defaults(EndpointOverride, CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL
    double_coercion: str = None


class ClientConfig(ConcurrentInference, EndpointOverride, BaseClientConfig):
    pass


@register()
class AnthropicClient(ConcurrentInferenceMixin, EndpointOverrideMixin, ClientBase):
    """
    Anthropic client for generating text.
    """

    client_type = "anthropic"
    conversation_retries = 0
    # TODO: make this configurable?
    decensor_enabled = False
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "Anthropic"
        title: str = "Anthropic"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = {}
        extra_fields.update(endpoint_override_extra_fields())
        extra_fields.update(concurrent_inference_extra_fields())
        unified_api_key_config_path: str = "anthropic.api_key"

    @property
    def can_be_coerced(self) -> bool:
        return not self.reason_enabled

    @property
    def anthropic_api_key(self):
        return self.config.anthropic.api_key

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "top_k",
            "max_tokens",
        ]

    @property
    def min_reason_tokens(self) -> int:
        return MIN_THINKING_TOKENS

    @property
    def requires_reasoning_pattern(self) -> bool:
        return False

    def emit_status(self, processing: bool = None):
        error_action = None
        error_message: str | None = None
        if processing is not None:
            self.processing = processing

        if self.anthropic_api_key:
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
                    "anthropic_api",
                ],
            )

        if not self.model_name:
            status = "error"
            error_message = "No model loaded"

        self.current_status = status

        data = {
            "error_action": error_action.model_dump() if error_action else None,
            "double_coercion": self.double_coercion,
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

    def response_tokens(self, response: str):
        return response.usage.output_tokens

    def prompt_tokens(self, response: str):
        return response.usage.input_tokens

    async def status(self):
        self.emit_status()

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if (
            not self.anthropic_api_key
            and not self.endpoint_override_base_url_configured
        ):
            raise Exception("No anthropic API key set")

        client = AsyncAnthropic(api_key=self.api_key, base_url=self.base_url)

        if self.can_be_coerced:
            prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        else:
            coercion_prompt = None

        system_message = self.get_system_message(kind)

        messages = [{"role": "user", "content": prompt.strip()}]

        if coercion_prompt:
            log.debug("Adding coercion pre-fill", coercion_prompt=coercion_prompt)
            messages.append({"role": "assistant", "content": coercion_prompt.strip()})

        if self.reason_enabled:
            parameters["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.validated_reason_tokens,
            }
            # thinking doesn't support temperature, top_p, or top_k
            # and the API will error if they are set
            parameters.pop("temperature", None)
            parameters.pop("top_p", None)
            parameters.pop("top_k", None)

        elif self.model_name in LIMITED_PARAM_MODELS:
            parameters.pop("temperature", None)
            parameters.pop("top_p", None)
            parameters.pop("top_k", None)

        self.log.debug(
            "generate",
            model=self.model_name,
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        completion_tokens = 0
        prompt_tokens = 0

        try:
            stream = await client.messages.create(
                model=self.model_name,
                system=system_message,
                messages=messages,
                stream=True,
                **parameters,
            )

            response = ""
            reasoning = ""

            async for event in stream:
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "text_delta"
                ):
                    content = event.delta.text
                    response += content
                    self.update_request_tokens(self.count_tokens(content))

                elif (
                    event.type == "content_block_delta"
                    and event.delta.type == "thinking_delta"
                ):
                    content = event.delta.thinking
                    reasoning += content
                    self.update_request_tokens(self.count_tokens(content))

                elif event.type == "message_start":
                    prompt_tokens = event.message.usage.input_tokens

                elif event.type == "message_delta":
                    completion_tokens += event.usage.output_tokens

            self._returned_prompt_tokens = prompt_tokens
            self._returned_response_tokens = completion_tokens
            self._reasoning_response = reasoning

            log.debug("generated response", response=response, reasoning=reasoning)

            return response
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="anthropic API: Permission Denied", status="error")
            return ""
        except Exception:
            raise
