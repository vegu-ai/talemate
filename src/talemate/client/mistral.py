import pydantic
import structlog
from mistralai.client import Mistral
from mistralai.client.errors import SDKError
from mistralai.client.models import TextChunk, ThinkChunk

from talemate.client.base import (
    ClientBase,
    ErrorAction,
    CommonDefaults,
    ExtraField,
    ReasoningDisplay,
)
from talemate.client.effort import EffortLevel
from talemate.client.reasoning_effort import (
    ReasoningEffortConfig,
    ReasoningEffortMixin,
    reasoning_effort_extra_fields,
)
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
    "MistralAIClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-latest",
    "mistral-large-4",
]

# Models that accept reasoning_effort, probed live on 2026-10-14 by sending
# effort=high to every SUPPORTED_MODELS entry plus magistral-medium-latest;
# mistral-large-latest rejects the field with HTTP 400 (code 3051).
EFFORT_MODELS = [
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-4",
    "magistral-medium-latest",
]

# Effort levels offered for the listed models, probed live on 2026-10-14:
# the server accepts only "high" and "none" on them ("default" sends
# nothing). Any other requested level is sent as "high" at send time.
EFFORT_CHOICES = ["default", "none", "high"]


class Defaults(
    ReasoningEffortConfig, EndpointOverride, CommonDefaults, pydantic.BaseModel
):
    max_token_length: int = 16384
    # mistral-large-4 accepts reasoning_effort; mistral-large-latest rejects it
    model: str = "mistral-large-4"


class ClientConfig(
    ReasoningEffortConfig, ConcurrentInference, EndpointOverride, BaseClientConfig
):
    concurrent_inference_enabled: bool = True


@register()
class MistralAIClient(
    ReasoningEffortMixin, ConcurrentInferenceMixin, EndpointOverrideMixin, ClientBase
):
    """
    MistralAI client for generating text.
    """

    client_type = "mistral"
    conversation_retries = 0
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
        # Mistral has no reasoning token budget; the token field is extra
        # completion allowance while the effort control sets reasoning depth.
        reason_tokens_as_allowance: bool = True
        extra_fields: dict[str, ExtraField] = reasoning_effort_extra_fields()
        # Offer only the levels the listed models accept; the shared field
        # carries every EFFORT_LEVELS entry.
        extra_fields["effort_level"].choices = [
            choice
            for choice in extra_fields["effort_level"].choices
            if choice["value"] in EFFORT_CHOICES
        ]
        extra_fields.update(endpoint_override_extra_fields())
        extra_fields.update(concurrent_inference_extra_fields())
        unified_api_key_config_path: str = "mistralai.api_key"

    @property
    def can_be_coerced(self) -> bool:
        return not self.reason_enabled

    @property
    def requires_reasoning_pattern(self) -> bool:
        # Reasoning streams in as ThinkChunks beside the content and is
        # captured during generation; the response text itself never
        # carries think tags.
        return False

    @property
    def model_accepts_effort(self) -> bool:
        """Whether the selected model accepts reasoning_effort."""
        if self.model_name and any(model in self.model_name for model in EFFORT_MODELS):
            return True
        return False

    @property
    def reasoning_effort(self) -> EffortLevel | None:
        # Models outside EFFORT_MODELS reject the field (HTTP 400, code
        # 3051); they never get it.
        if not self.model_accepts_effort:
            return None
        return super().reasoning_effort

    @property
    def reasoning_display(self) -> ReasoningDisplay | None:
        if not self.model_accepts_effort:
            # Fall back to the base client's token-budget display.
            return super(ReasoningEffortMixin, self).reasoning_display
        if not self.reason_enabled_configured:
            return None
        return ReasoningDisplay(control="effort", effort_choices=EFFORT_CHOICES)

    @property
    def mistral_api_key(self):
        return self.config.mistralai.api_key

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "max_tokens",
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        error_message = None
        if processing is not None:
            self.processing = processing

        if self.mistral_api_key:
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
                    "mistralai_api",
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

    def response_tokens(self, response: str):
        return response.usage.completion_tokens

    def prompt_tokens(self, response: str):
        return response.usage.prompt_tokens

    async def status(self):
        self.emit_status()

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

        client = Mistral(api_key=self.api_key, server_url=self.base_url)

        if self.can_be_coerced:
            prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        else:
            coercion_prompt = None

        system_message = self.get_system_message(kind)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt.strip()},
        ]

        if coercion_prompt:
            log.debug("Adding coercion pre-fill", coercion_prompt=coercion_prompt)
            messages.append(
                {
                    "role": "assistant",
                    "content": coercion_prompt.strip(),
                    "prefix": True,
                }
            )

        effort = self.reasoning_effort
        if effort is not None and effort not in ("none", "high"):
            # Mistral's listed models take only "none"/"high" (probed live);
            # send "high" for any other requested level rather than get a 400.
            self.log.debug(
                "unsupported reasoning effort, sending high", requested=effort
            )
            effort = "high"
        # Request-local: the caller's parameters dict is reused across retries,
        # so the effort must not be written into it.
        request_parameters = dict(parameters)
        if effort is not None:
            request_parameters["reasoning_effort"] = effort

        self.log.debug(
            "generate",
            base_url=self.base_url,
            prompt=prompt[:128] + " ...",
            parameters=request_parameters,
            system_message=system_message,
        )

        event_stream = await client.chat.stream_async(
            model=self.model_name,
            messages=messages,
            **request_parameters,
        )

        response = ""
        reasoning = ""
        # generate() is also called without a prompt request (the prompt
        # editor's Test button), where nothing resets this between calls.
        self._reasoning_response = None

        completion_tokens = 0
        prompt_tokens = 0

        async for event in event_stream:
            if event.data.choices:
                text, thinking = self._split_delta_content(
                    event.data.choices[0].delta.content
                )
                response += text
                reasoning += thinking
            if event.data.usage:
                completion_tokens += event.data.usage.completion_tokens
                prompt_tokens += event.data.usage.prompt_tokens

        self._returned_prompt_tokens = prompt_tokens
        self._returned_response_tokens = completion_tokens
        self._reasoning_response = reasoning or None

        return response

    def _split_delta_content(self, content) -> tuple[str, str]:
        """Split one streamed delta content into response text and reasoning.

        ThinkChunks carry the model's thinking; the other chunk variants
        (image, reference, file, audio) carry no text for a chat response.
        """
        text = ""
        reasoning = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for chunk in content:
                if isinstance(chunk, TextChunk):
                    text += chunk.text
                elif isinstance(chunk, ThinkChunk):
                    for thinking in chunk.thinking:
                        if isinstance(thinking, TextChunk):
                            reasoning += thinking.text
        for part in (text, reasoning):
            if part:
                self.update_request_tokens(self.count_tokens(part))
        return text, reasoning

    def _extract_status_code(self, error: Exception) -> int | None:
        if isinstance(error, SDKError) and hasattr(error, "status_code"):
            return error.status_code
        return super()._extract_status_code(error)
