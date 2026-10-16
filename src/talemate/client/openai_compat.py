import random
from typing import Literal

import httpx
import pydantic
from openai import AsyncOpenAI, NotFoundError

from talemate.client.api_handles import (
    ApiHandlesPromptTemplateConfig,
    ApiHandlesPromptTemplateMixin,
    ChatReasoningMixin,
    api_handles_prompt_template_extra_fields,
    strip_echoed_prefill,
)
from talemate.client.base import ClientBase, ExtraField, FieldGroup
from talemate.client.reasoning_effort import (
    COMPLETION_TOKEN_PARAMETER_CHOICES,
    EFFORT_FORMAT_CHOICES,
    EffortFormat,
    ReasoningEffortConfig,
    ReasoningEffortMixin,
    reasoning_effort_extra_fields,
)
from talemate.client.registry import register
from talemate.client.streaming import StreamingConfig, streaming_extra_fields
from talemate.client.toggleable_parameters import (
    ToggleableParametersMixin,
    toggleable_parameters_config,
    toggleable_parameters_extra_fields,
)
from talemate.config.schema import Client as BaseClientConfig
from talemate.exceptions import GenerationProcessingError

EXPERIMENTAL_DESCRIPTION = """Use this client if you want to connect to a service implementing an OpenAI-compatible API. Success is going to depend on the level of compatibility. Use the actual OpenAI client if you want to connect to OpenAI's API."""

# The SDK refuses to build a client without a key; local servers need none.
KEYLESS_PLACEHOLDER = "not-needed"

# Request parameters whose inclusion in the payload is user-toggleable.
# Some OpenAI-compatible APIs hard-error when these are sent for certain models,
# so they need to be omitted entirely (not just zeroed out).
TOGGLEABLE_PARAMETERS = ("temperature", "top_p", "presence_penalty", "stop")

# Request toggles added in 0.40. A client saved before 0.40 lacks them and
# keeps sending what it sent before; new clients get them on from Defaults.
REQUEST_TOGGLES_ADDED_IN_0_40 = ("send_enable_thinking", "send_stop")

ToggleableParametersConfig = toggleable_parameters_config(TOGGLEABLE_PARAMETERS)


class CompatibleReasoningConfig(ReasoningEffortConfig):
    reasoning_effort_format: EffortFormat = "none"
    completion_token_parameter: Literal["max_tokens", "max_completion_tokens"] = (
        "max_tokens"
    )
    send_enable_thinking: bool = True


class Defaults(
    CompatibleReasoningConfig,
    StreamingConfig,
    ToggleableParametersConfig,
    ApiHandlesPromptTemplateConfig,
):
    api_url: str = "http://localhost:5000"
    api_key: str = ""
    max_token_length: int = 16384
    model: str = ""
    double_coercion: str = None
    rate_limit: int | None = None


class ClientConfig(
    CompatibleReasoningConfig,
    StreamingConfig,
    ToggleableParametersConfig,
    ApiHandlesPromptTemplateConfig,
    BaseClientConfig,
):
    @pydantic.model_validator(mode="before")
    @classmethod
    def keep_saved_request_shape(cls, data):
        if isinstance(data, dict):
            data = {**{key: False for key in REQUEST_TOGGLES_ADDED_IN_0_40}, **data}
        return data


def reasoning_text(message) -> str | None:
    """Reasoning a chat-completions server returns beside the content.

    llama.cpp and vLLM name the field `reasoning_content`; OpenRouter-style
    servers name it `reasoning`. The SDK keeps both as extra attributes.
    """
    return getattr(message, "reasoning_content", None) or getattr(
        message, "reasoning", None
    )


@register()
class OpenAICompatibleClient(
    ReasoningEffortMixin,
    ChatReasoningMixin,
    ApiHandlesPromptTemplateMixin,
    ToggleableParametersMixin,
    ClientBase,
):
    client_type = "openai_compat"
    conversation_retries = 0
    config_cls = ClientConfig
    toggleable_parameters = TOGGLEABLE_PARAMETERS

    class Meta(ClientBase.Meta):
        title: str = "OpenAI Compatible API"
        name_prefix: str = "OpenAI Compatible API"
        experimental: str = EXPERIMENTAL_DESCRIPTION
        enable_api_auth: bool = True
        manual_model: bool = True
        defaults: Defaults = Defaults()
        self_hosted: bool | None = None
        reason_tokens_as_allowance: bool = True
        extra_fields: dict[str, ExtraField] = {
            **api_handles_prompt_template_extra_fields(
                description="The API handles the prompt template, meaning your choice in the UI for the prompt template below will be ignored. This is not recommended and should only be used if the API does not support the `completions` andpoint or you don't know which prompt template to use.",
            ),
            **toggleable_parameters_extra_fields(TOGGLEABLE_PARAMETERS),
            **streaming_extra_fields(),
            **reasoning_effort_extra_fields(),
            "reasoning_effort_format": ExtraField(
                name="reasoning_effort_format",
                type="text",
                label="Reasoning Effort Format",
                choices=EFFORT_FORMAT_CHOICES,
                description="Choose what your server accepts: 'reasoning_effort' sends a field, 'reasoning' sends an object with effort, and 'none' sends neither. Applies to both chat and text completions. Omitting effort leaves the server's default behavior.",
                group=FieldGroup(name="reasoning", label="Reasoning", icon="mdi-brain"),
                required=False,
            ),
            "send_enable_thinking": ExtraField(
                name="send_enable_thinking",
                type="bool",
                label="Send enable_thinking",
                description='With API handles prompt template on, send `chat_template_kwargs: {"enable_thinking": ...}` following the Reasoning setting, so hybrid reasoning models (Qwen3, Qwen3.5, ...) only think when reasoning is enabled. Understood by llama.cpp, vLLM and SGLang; disable it for servers that reject unknown fields.',
                group=FieldGroup(name="reasoning", label="Reasoning", icon="mdi-brain"),
                required=False,
            ),
            "completion_token_parameter": ExtraField(
                name="completion_token_parameter",
                type="text",
                label="Completion Token Parameter",
                choices=COMPLETION_TOKEN_PARAMETER_CHOICES,
                description="Choose the parameter your server accepts for the total completion limit. OpenAI chat completions use 'max_completion_tokens'; other servers and text completions commonly use 'max_tokens'. Includes extra completion tokens when reasoning is enabled.",
                group=FieldGroup(name="reasoning", label="Reasoning", icon="mdi-brain"),
                required=False,
            ),
        }

    @property
    def reasoning_effort_format(self) -> EffortFormat:
        return self.client_config.reasoning_effort_format

    @property
    def completion_token_parameter(
        self,
    ) -> Literal["max_tokens", "max_completion_tokens"]:
        return self.client_config.completion_token_parameter

    @property
    def stream(self) -> bool:
        return self.client_config.stream

    @property
    def send_enable_thinking(self) -> bool:
        return self.client_config.send_enable_thinking

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)
        parameters["stop"] = self.build_stopping_strings(parameters)

    @property
    def experimental(self):
        return EXPERIMENTAL_DESCRIPTION

    @property
    def can_be_coerced(self):
        """
        Determines whether or not his client can pass LLM coercion. (e.g., is able
        to predefine partial LLM output in the prompt)
        """
        return not self.reason_enabled

    async def get_model_name(self):
        self.require_api_url()
        return self.model

    def make_client(self) -> AsyncOpenAI:
        api_key = self.api_key or KEYLESS_PLACEHOLDER
        return AsyncOpenAI(base_url=self.require_api_url(), api_key=api_key)

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        client = self.make_client()

        if not self.api_handles_prompt_template and "max_tokens" not in parameters:
            # text completions read an absent (or null) max_tokens as 16 tokens
            # (OpenAI spec, vLLM); fill the remaining context instead
            limit = await self.uncapped_completion_tokens(prompt)
            if limit is not None:
                parameters["max_tokens"] = limit

        if (
            self.completion_token_parameter == "max_completion_tokens"
            and "max_tokens" in parameters
        ):
            # Text completions do not expose this extension as an SDK keyword.
            parameters.setdefault("extra_body", {})["max_completion_tokens"] = (
                parameters.pop("max_tokens")
            )

        effort = self.reasoning_effort
        if effort is not None:
            # extra_body supports both formats on chat and text completion endpoints.
            if self.reasoning_effort_format == "reasoning":
                parameters.setdefault("extra_body", {})["reasoning"] = {
                    "effort": effort
                }
            elif self.reasoning_effort_format == "reasoning_effort":
                parameters.setdefault("extra_body", {})["reasoning_effort"] = effort

        if self.api_handles_prompt_template:
            # OpenAI API handles prompt template
            # Use the chat completions endpoint
            self.log.debug(
                "generate (chat/completions)",
                prompt=prompt[:128] + " ...",
                parameters=parameters,
            )

            messages, coercion_prompt = self.chat_messages_for_coercion(prompt, kind)

            if coercion_prompt:
                # continue the pre-fill via the (non-standard) prefix flag
                messages[-1]["prefix"] = True

            if self.send_enable_thinking:
                parameters.setdefault("extra_body", {})["chat_template_kwargs"] = {
                    "enable_thinking": self.reason_enabled
                }

            response = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=self.stream,
                **parameters,
            )
            if not self.stream:
                if not response.choices:
                    return ""
                message = response.choices[0].message
                reasoning = reasoning_text(message)
                self._record_reasoning(reasoning)
                content = self.record_whole_response(message.content, reasoning)
                return strip_echoed_prefill(content, coercion_prompt)

            content = ""
            reasoning = ""
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if not delta:
                    continue
                if reasoning_chunk := reasoning_text(delta):
                    reasoning += reasoning_chunk
                    self.update_request_tokens(self.count_tokens(reasoning_chunk))
                if delta.content:
                    content += delta.content
                    self.update_request_tokens(self.count_tokens(delta.content))
            self._record_reasoning(reasoning)
            return strip_echoed_prefill(content, coercion_prompt)
        else:
            # Talemate handles prompt template
            # Use the completions endpoint
            self.log.debug(
                "generate (completions)",
                prompt=prompt[:128] + " ...",
                parameters=parameters,
            )
            parameters["prompt"] = prompt
            try:
                response = await client.completions.create(
                    model=self.model_name, stream=self.stream, **parameters
                )
            except NotFoundError as exc:
                raise GenerationProcessingError(
                    f"{exc.request.method} {exc.request.url.path} returned 404: the"
                    " server has no text completions endpoint or does not know model"
                    f" '{self.model_name}'. If it only offers chat completions, turn on"
                    " API handles prompt template."
                ) from exc
            if not self.stream:
                if not response.choices:
                    return ""
                return self.record_whole_response(response.choices[0].text)

            text = ""
            async for chunk in response:
                if not chunk.choices or not chunk.choices[0].text:
                    continue
                text += chunk.choices[0].text
                self.update_request_tokens(self.count_tokens(chunk.choices[0].text))
            return text

    async def server_prompt_tokens(self, prompt: str) -> int | None:
        # llama.cpp and vLLM both serve /tokenize at the server root, with the
        # text under different keys ("content" and "prompt"); llama.cpp leaves
        # out BOS unless asked, completions tokenize with it
        root = self.require_api_url().rstrip("/").removesuffix("/v1")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                response = await http.post(
                    f"{root}/tokenize",
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "content": prompt,
                        "add_special": True,
                    },
                    headers=headers,
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.log.debug("server prompt token count unavailable", error=repr(exc))
            return None
        if not isinstance(data, dict):
            return None
        count = data.get("count")
        if type(count) is int and count >= 0:
            return count
        if isinstance(data.get("tokens"), list):
            return len(data["tokens"])
        return None

    def _record_reasoning(self, reasoning: str | None):
        if reasoning:
            self._reasoning_response = reasoning

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        adjusts temperature and presence penalty
        by random values using the base value as a center
        """

        temp = prompt_config["temperature"]

        min_offset = offset * 0.3

        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)

        try:
            presence_penalty = prompt_config["presence_penalty"]
            prompt_config["presence_penalty"] = round(
                random.uniform(presence_penalty + 0.1, presence_penalty + offset), 1
            )
        except KeyError:
            pass
