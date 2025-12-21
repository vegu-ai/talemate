import random

import pydantic
import structlog
from openai import AsyncOpenAI, PermissionDeniedError

from talemate.client.base import ClientBase, ExtraField
from talemate.client.registry import register
from talemate.config.schema import Client as BaseClientConfig
from talemate.emit import emit

log = structlog.get_logger("talemate.client.openai_compat")

EXPERIMENTAL_DESCRIPTION = """Use this client if you want to connect to a service implementing an OpenAI-compatible API. Success is going to depend on the level of compatibility. Use the actual OpenAI client if you want to connect to OpenAI's API."""


class Defaults(pydantic.BaseModel):
    api_url: str = "http://localhost:5000"
    api_key: str = ""
    max_token_length: int = 8192
    model: str = ""
    api_handles_prompt_template: bool = False
    double_coercion: str = None
    rate_limit: int | None = None


class ClientConfig(BaseClientConfig):
    api_handles_prompt_template: bool = False


@register()
class OpenAICompatibleClient(ClientBase):
    client_type = "openai_compat"
    conversation_retries = 0
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        title: str = "OpenAI Compatible API"
        name_prefix: str = "OpenAI Compatible API"
        experimental: str = EXPERIMENTAL_DESCRIPTION
        enable_api_auth: bool = True
        manual_model: bool = True
        defaults: Defaults = Defaults()
        self_hosted: bool | None = None
        extra_fields: dict[str, ExtraField] = {
            "api_handles_prompt_template": ExtraField(
                name="api_handles_prompt_template",
                type="bool",
                label="API handles prompt template (chat/completions)",
                required=False,
                description="The API handles the prompt template, meaning your choice in the UI for the prompt template below will be ignored. This is not recommended and should only be used if the API does not support the `completions` andpoint or you don't know which prompt template to use.",
            )
        }

    @property
    def api_handles_prompt_template(self) -> bool:
        return self.client_config.api_handles_prompt_template

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

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "presence_penalty",
            "max_tokens",
        ]

    def prompt_template(self, system_message: str, prompt: str):
        if not self.api_handles_prompt_template:
            return super().prompt_template(system_message, prompt)
        return prompt

    async def get_model_name(self):
        return self.model

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        client = AsyncOpenAI(base_url=self.api_url, api_key=self.api_key)

        try:
            if self.api_handles_prompt_template:
                # OpenAI API handles prompt template
                # Use the chat completions endpoint
                self.log.debug(
                    "generate (chat/completions)",
                    prompt=prompt[:128] + " ...",
                    parameters=parameters,
                )

                if self.can_be_coerced:
                    prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
                else:
                    coercion_prompt = None

                messages = [
                    {"role": "system", "content": self.get_system_message(kind)},
                    {"role": "user", "content": prompt.strip()},
                ]

                if coercion_prompt:
                    log.debug(
                        "Adding coercion pre-fill", coercion_prompt=coercion_prompt
                    )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": coercion_prompt.strip(),
                            "prefix": True,
                        }
                    )

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
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="Client API: Permission Denied", status="error")
            return ""
        except Exception as e:
            self.log.error("generate error", e=e)
            emit(
                "status", message="Error during generation (check logs)", status="error"
            )
            return ""

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
