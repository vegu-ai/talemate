import random
from typing import Literal, get_args

from openai import AsyncOpenAI

from talemate.client.api_handles import (
    ApiHandlesPromptTemplateConfig,
    ApiHandlesPromptTemplateMixin,
    api_handles_prompt_template_extra_fields,
)
from talemate.client.base import ClientBase, ExtraField, FieldGroup
from talemate.client.reasoning_effort import (
    EffortFormat,
    ReasoningEffortConfig,
    ReasoningEffortMixin,
    reasoning_effort_extra_fields,
)
from talemate.client.registry import register
from talemate.client.toggleable_parameters import (
    ToggleableParametersMixin,
    toggleable_parameters_config,
    toggleable_parameters_extra_fields,
)
from talemate.config.schema import Client as BaseClientConfig

EXPERIMENTAL_DESCRIPTION = """Use this client if you want to connect to a service implementing an OpenAI-compatible API. Success is going to depend on the level of compatibility. Use the actual OpenAI client if you want to connect to OpenAI's API."""

# Sampler parameters whose inclusion in the request payload is user-toggleable.
# Some OpenAI-compatible APIs hard-error when these are sent for certain models,
# so they need to be omitted entirely (not just zeroed out).
TOGGLEABLE_PARAMETERS = ("temperature", "top_p", "presence_penalty")

ToggleableParametersConfig = toggleable_parameters_config(TOGGLEABLE_PARAMETERS)


class CompatibleReasoningConfig(ReasoningEffortConfig):
    reasoning_effort_format: EffortFormat = "none"
    completion_token_parameter: Literal["max_tokens", "max_completion_tokens"] = (
        "max_tokens"
    )


class Defaults(
    CompatibleReasoningConfig,
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
    ToggleableParametersConfig,
    ApiHandlesPromptTemplateConfig,
    BaseClientConfig,
):
    pass


@register()
class OpenAICompatibleClient(
    ReasoningEffortMixin,
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
            **reasoning_effort_extra_fields(),
            "reasoning_effort_format": ExtraField(
                name="reasoning_effort_format",
                type="text",
                label="Reasoning Effort Format",
                choices=list(get_args(EffortFormat)),
                description="Choose what your server accepts: 'reasoning_effort' sends a field, 'reasoning' sends an object with effort, and 'none' sends neither. Applies to both chat and text completions. Omitting effort leaves the server's default behavior.",
                group=FieldGroup(name="reasoning", label="Reasoning", icon="mdi-brain"),
                required=False,
            ),
            "completion_token_parameter": ExtraField(
                name="completion_token_parameter",
                type="text",
                label="Completion Token Parameter",
                choices=["max_tokens", "max_completion_tokens"],
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
        return AsyncOpenAI(base_url=self.require_api_url(), api_key=self.api_key)

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        client = self.make_client()

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

            response = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=False,
                **parameters,
            )
            response = response.choices[0].message.content
            return response
        else:
            # Talemate handles prompt template
            # Use the completions endpoint
            self.log.debug(
                "generate (completions)",
                prompt=prompt[:128] + " ...",
                parameters=parameters,
            )
            parameters["prompt"] = prompt
            response = await client.completions.create(
                model=self.model_name, stream=False, **parameters
            )
            return response.choices[0].text

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
