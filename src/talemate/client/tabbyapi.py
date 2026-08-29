import random
import json
import httpx
from talemate.client.api_handles import (
    ApiHandlesPromptTemplateConfig,
    ApiHandlesPromptTemplateMixin,
    api_handles_prompt_template_extra_fields,
)
from talemate.client.base import ClientBase, ExtraField, CommonDefaults
from talemate.client.registry import register
from talemate.client.utils import urljoin
from talemate.config.schema import Client as BaseClientConfig

EXPERIMENTAL_DESCRIPTION = """Use this client to use all of TabbyAPI's features. Note on EXL3 models: They seem to be very sensitive to `presence_penalty`, `frequency_penalty` and `repetition_penalty_range`. If you're getting gibberish output, try creating a new inference parameter group and turn those off or way down."""


class Defaults(CommonDefaults, ApiHandlesPromptTemplateConfig):
    api_url: str = "http://localhost:5000/v1"
    api_key: str = ""
    max_token_length: int = 8192
    model: str = ""
    double_coercion: str = None


class ClientConfig(ApiHandlesPromptTemplateConfig, BaseClientConfig):
    pass


@register()
class TabbyAPIClient(ApiHandlesPromptTemplateMixin, ClientBase):
    client_type = "tabbyapi"
    conversation_retries = 0
    config_cls = ClientConfig
    remote_model_locked: bool = True

    class Meta(ClientBase.Meta):
        title: str = "TabbyAPI"
        name_prefix: str = "TabbyAPI"
        experimental: str = EXPERIMENTAL_DESCRIPTION
        enable_api_auth: bool = True
        manual_model: bool = False
        defaults: Defaults = Defaults()
        self_hosted: bool = True
        extra_fields: dict[str, ExtraField] = api_handles_prompt_template_extra_fields(
            description="The API handles the prompt template, meaning your choice in the UI for the prompt template below will be ignored. This is not recommended and should only be used if the API does not support the `completions` endpoint or you don't know which prompt template to use.",
        )

    @property
    def experimental(self):
        return EXPERIMENTAL_DESCRIPTION

    @property
    def can_be_coerced(self):
        """
        Determines whether or not this client can pass LLM coercion. (e.g., is able to predefine partial LLM output in the prompt)
        """
        return not self.reason_enabled

    @property
    def supported_parameters(self):
        return [
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "repetition_penalty_range",
            "min_p",
            "top_p",
            "xtc_threshold",
            "xtc_probability",
            "dry_multiplier",
            "dry_base",
            "dry_allowed_length",
            "dry_sequence_breakers",
            # dry_range ?
            "smoothing_factor",
            "temperature_last",
            "temperature",
        ]

    async def get_model_name(self):
        url = urljoin(self.api_url, "model")
        headers = {
            "x-api-key": self.api_key,
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            if response.status_code != 200:
                raise Exception(f"Request failed: {response.status_code}")
            response_data = response.json()
            model_name = response_data.get("id")
            # split by "/" and take last
            if model_name:
                model_name = model_name.split("/")[-1]
            return model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters using streaming responses.
        """

        # Determine whether we are using chat or completions endpoint
        is_chat = self.api_handles_prompt_template

        if is_chat:
            # Chat completions endpoint
            self.log.debug(
                "generate (chat/completions)",
                prompt=prompt[:128] + " ...",
                parameters=parameters,
            )

            messages, coercion_prompt = self.chat_messages_for_coercion(prompt, kind)

            if coercion_prompt:
                # TabbyAPI continues the pre-fill via its prefix flag
                messages[-1]["prefix"] = True

            payload = {
                "model": self.model_name,
                "messages": messages,
                "stream": True,
                "stream_options": {
                    "include_usage": True,
                },
                **parameters,
            }
            endpoint = "chat/completions"
        else:
            # Completions endpoint
            self.log.debug(
                "generate (completions)",
                prompt=prompt[:128] + " ...",
                parameters=parameters,
            )

            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": True,
                "stream_options": {
                    "include_usage": True,
                },
                **parameters,
            }
            endpoint = "completions"

        url = urljoin(self.api_url, endpoint)

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        response_text = ""
        buffer = ""
        completion_tokens = 0
        prompt_tokens = 0

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", url, headers=headers, json=payload, timeout=120.0
            ) as response:
                async for chunk in response.aiter_text():
                    buffer += chunk

                    while True:
                        line_end = buffer.find("\n")
                        if line_end == -1:
                            break

                        line = buffer[:line_end].strip()
                        buffer = buffer[line_end + 1 :]

                        if not line:
                            continue

                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break

                            try:
                                data_obj = json.loads(data)

                                choice = data_obj.get("choices", [{}])[0]

                                # Chat completions use delta -> content.
                                delta = choice.get("delta", {})
                                content = (
                                    delta.get("content")
                                    or delta.get("text")
                                    or choice.get("text")
                                )

                                if content:
                                    response_text += content
                                    self.update_request_tokens(
                                        self.count_tokens(content)
                                    )

                                usage = data_obj.get("usage") or {}
                                if usage:
                                    completion_tokens = usage.get(
                                        "completion_tokens", completion_tokens
                                    )
                                    prompt_tokens = usage.get(
                                        "prompt_tokens", prompt_tokens
                                    )
                            except (json.JSONDecodeError, IndexError):
                                # ignore malformed json chunks
                                pass

        # Save token stats for logging
        self._returned_prompt_tokens = prompt_tokens
        self._returned_response_tokens = completion_tokens

        return response_text

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        adjusts temperature and presence penalty by random values using the base value as a center
        """

        temp = prompt_config["temperature"]

        min_offset = offset * 0.3

        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)

        # keep min_p in a tight range to avoid unwanted tokens
        prompt_config["min_p"] = random.uniform(0.05, 0.15)

        try:
            presence_penalty = prompt_config["presence_penalty"]
            adjusted_presence_penalty = round(
                random.uniform(presence_penalty + 0.1, presence_penalty + offset), 1
            )
            # Ensure presence_penalty does not exceed 0.5 and does not fall below 0.1
            prompt_config["presence_penalty"] = min(
                0.5, max(0.1, adjusted_presence_penalty)
            )
        except KeyError:
            pass
