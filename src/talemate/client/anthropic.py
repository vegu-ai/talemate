from typing import Literal

import pydantic
import structlog
from anthropic import AsyncAnthropic

from talemate.client.base import (
    ClientBase,
    ErrorAction,
    CommonDefaults,
    ExtraField,
    FieldGroup,
    ReasoningDisplay,
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
    "AnthropicClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-1",
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
]

DEFAULT_MODEL = "claude-haiku-4-5"
MIN_THINKING_TOKENS = 1024

LIMITED_PARAM_MODELS = [
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-1",
    # Opus 4.7 rejects any non-default temperature/top_p/top_k with a 400.
    "claude-opus-4-7",
]

# Models that support adaptive thinking + effort control (Opus 4.6+)
ADAPTIVE_THINKING_MODELS = [
    "claude-opus-4-6",
    "claude-opus-4-7",
]

# Models that ONLY accept adaptive thinking. Sending thinking.type="enabled"
# (budget_tokens) returns a 400 — Opus 4.7 dropped budget-mode support.
ADAPTIVE_ONLY_THINKING_MODELS = [
    "claude-opus-4-7",
]

# Maximum output tokens per model family, matching Anthropic API limits.
# Used as the max_tokens value when response length capping is disabled.
MAX_OUTPUT_TOKENS = {
    "claude-opus-4-7": 128000,
    "claude-opus-4-6": 128000,
    "claude-sonnet-4-6": 64000,
    "claude-opus-4-5": 64000,
    "claude-sonnet-4-5": 64000,
    "claude-opus-4-1": 32000,
    "claude-opus-4": 32000,
    "claude-sonnet-4": 64000,
    "claude-haiku-4-5": 64000,
}

# Fallback when model isn't in the lookup
DEFAULT_MAX_OUTPUT_TOKENS = 32000


class Defaults(EndpointOverride, CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL
    double_coercion: str = None
    effort_level: str = "high"
    thinking_mode: str = "budget"


class ClientConfig(ConcurrentInference, EndpointOverride, BaseClientConfig):
    effort_level: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    thinking_mode: Literal["budget", "adaptive"] = "budget"


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
        extra_fields: dict[str, ExtraField] = {
            "thinking_mode": ExtraField(
                name="thinking_mode",
                type="select",
                label="Thinking Mode",
                choices=["budget", "adaptive"],
                description="'budget' uses fixed token budget (legacy), 'adaptive' lets the model decide when to think. Adaptive is recommended for Opus 4.6+ and required for Opus 4.7+ (budget mode is ignored on those models).",
                group=FieldGroup(
                    name="reasoning",
                    label="Reasoning",
                    description="",
                    icon="mdi-brain",
                ),
                required=False,
            ),
            "effort_level": ExtraField(
                name="effort_level",
                type="select",
                label="Effort Level",
                choices=["low", "medium", "high", "xhigh", "max"],
                description="Controls thinking depth and cost trade-off. Higher effort = better quality but more cost/latency. Only applies with adaptive thinking mode. The 'xhigh' option (between high and max) is supported on Opus 4.7+.",
                group=FieldGroup(
                    name="reasoning",
                    label="Reasoning",
                    description="",
                    icon="mdi-brain",
                ),
                required=False,
            ),
        }
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
    def api_max_output_tokens(self) -> int:
        """Returns the Anthropic API's max output token limit for the current model."""
        # Check longest prefixes first to avoid e.g. "claude-opus-4" matching "claude-opus-4-6"
        for prefix in sorted(MAX_OUTPUT_TOKENS, key=len, reverse=True):
            if self.model_name.startswith(prefix):
                return MAX_OUTPUT_TOKENS[prefix]
        return DEFAULT_MAX_OUTPUT_TOKENS

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

    @property
    def effort_level(self) -> str:
        return self.client_config.effort_level

    @property
    def thinking_mode(self) -> str:
        return self.client_config.thinking_mode

    @property
    def supports_adaptive_thinking(self) -> bool:
        return any(model in self.model_name for model in ADAPTIVE_THINKING_MODELS)

    @property
    def requires_adaptive_thinking(self) -> bool:
        """True if the model only accepts adaptive thinking (rejects budget mode)."""
        return any(model in self.model_name for model in ADAPTIVE_ONLY_THINKING_MODELS)

    @property
    def reasoning_display(self) -> ReasoningDisplay | None:
        """Returns reasoning display config based on what's actually used at runtime."""
        if not self.reason_enabled_configured:
            return None

        # Only show effort display if adaptive will ACTUALLY be used.
        # Either the model forces adaptive (4.7+) or the user opted in and the
        # model supports it.
        adaptive_active = self.requires_adaptive_thinking or (
            self.thinking_mode == "adaptive" and self.supports_adaptive_thinking
        )
        if adaptive_active:
            return ReasoningDisplay(
                indicator_value=self.effort_level,
                indicator_tooltip="Effort level",
                show_token_slider=False,
                show_effort_selector=True,
                effort_level=self.effort_level,
                effort_choices=["low", "medium", "high", "xhigh", "max"],
            )

        # Fallback to budget display (even if adaptive is configured but model doesn't support it)
        return super().reasoning_display

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
            # Opus 4.7+ rejects budget-mode thinking outright, so force adaptive
            # whenever the model demands it.
            use_adaptive = self.requires_adaptive_thinking or (
                self.thinking_mode == "adaptive" and self.supports_adaptive_thinking
            )
            if use_adaptive:
                # Opus 4.6+ adaptive thinking with effort control
                parameters["thinking"] = {"type": "adaptive"}
                parameters["output_config"] = {"effort": self.effort_level}
            else:
                # Legacy budget-based thinking for older models
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

        # Anthropic API always requires max_tokens, even when response length
        # capping is disabled. Use the model's API limit as the default.
        if "max_tokens" not in parameters:
            parameters["max_tokens"] = self.api_max_output_tokens

        # Prompt caching is opt-in on the Anthropic API — without cache_control
        # the request is never cached. Top-level cache_control auto-places the
        # breakpoint on the last cacheable block, which pairs with the
        # after_history volatile-context placement that optimize_prompt_caching
        # already enables in the prompt builder.
        if self.optimize_prompt_caching:
            parameters["cache_control"] = {"type": "ephemeral"}

        self.log.debug(
            "generate",
            model=self.model_name,
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        completion_tokens = 0
        prompt_tokens = 0

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
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
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
