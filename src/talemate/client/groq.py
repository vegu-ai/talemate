import pydantic
import structlog
from groq import AsyncGroq, PermissionDeniedError

from talemate.client.base import ClientBase, ErrorAction, ParameterReroute, ExtraField
from talemate.client.registry import register
from talemate.config.schema import Client as BaseClientConfig
from talemate.emit import emit
from talemate.client.remote import (
    EndpointOverride,
    EndpointOverrideMixin,
    endpoint_override_extra_fields,
)

__all__ = [
    "GroqClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "mixtral-8x7b-32768",
    "llama3-8b-8192",
    "llama3-70b-8192",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "moonshotai/kimi-k2-instruct",
    "deepseek-r1-distill-llama-70b",
]

JSON_OBJECT_RESPONSE_MODELS = []


class Defaults(EndpointOverride, pydantic.BaseModel):
    max_token_length: int = 8192
    model: str = "moonshotai/kimi-k2-instruct"


class ClientConfig(EndpointOverride, BaseClientConfig):
    pass


@register()
class GroqClient(EndpointOverrideMixin, ClientBase):
    """
    OpenAI client for generating text.
    """

    client_type = "groq"
    conversation_retries = 0
    # TODO: make this configurable?
    decensor_enabled = True
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "Groq"
        title: str = "Groq"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = endpoint_override_extra_fields()
        unified_api_key_config_path: str = "groq.api_key"

    @property
    def can_be_coerced(self) -> bool:
        return not self.reason_enabled

    @property
    def groq_api_key(self):
        return self.config.groq.api_key

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            ParameterReroute(
                talemate_parameter="stopping_strings", client_parameter="stop"
            ),
            "max_tokens",
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        error_message = None
        if processing is not None:
            self.processing = processing

        if self.groq_api_key:
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
                    "groq_api",
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
        # Include shared/common status data (rate limit, etc.)
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
        return response.usage.completion_tokens

    def prompt_tokens(self, response: str):
        return response.usage.prompt_tokens

    async def status(self):
        self.emit_status()

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.groq_api_key and not self.endpoint_override_base_url_configured:
            raise Exception("No groq.ai API key set")

        client = AsyncGroq(api_key=self.api_key, base_url=self.base_url)

        if self.can_be_coerced:
            prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        else:
            coercion_prompt = None

        system_message = self.get_system_message(kind)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        if coercion_prompt:
            log.debug("Adding coercion pre-fill", coercion_prompt=coercion_prompt)
            messages.append({"role": "assistant", "content": coercion_prompt.strip()})

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
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
