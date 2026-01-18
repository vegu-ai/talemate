import random
import json
import httpx
import pydantic
import structlog
from openai import PermissionDeniedError

from talemate.client.base import ClientBase, ExtraField, CommonDefaults
from talemate.client.registry import register
from talemate.client.utils import urljoin
from talemate.config.schema import Client as BaseClientConfig
from talemate.emit import emit

log = structlog.get_logger("talemate.client.tabbyapi")

EXPERIMENTAL_DESCRIPTION = """Use this client to use all of TabbyAPI's features. Note on EXL3 models: They seem to be very sensitive to `presence_penalty`, `frequency_penalty` and `repetition_penalty_range`. If you're getting gibberish output, try creating a new inference parameter group and turn those off or way down."""


class Defaults(CommonDefaults, pydantic.BaseModel):
    api_url: str = "http://localhost:5000/v1"
    api_key: str = ""
    max_token_length: int = 8192
    model: str = ""
    api_handles_prompt_template: bool = False
    double_coercion: str = None


class ClientConfig(BaseClientConfig):
    api_handles_prompt_template: bool = False


@register()
class TabbyAPIClient(ClientBase):
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
        extra_fields: dict[str, ExtraField] = {
            "api_handles_prompt_template": ExtraField(
                name="api_handles_prompt_template",
                type="bool",
                label="API handles prompt template (chat/completions)",
                required=False,
                description="The API handles the prompt template, meaning your choice in the UI for the prompt template below will be ignored. This is not recommended and should only be used if the API does not support the `completions` endpoint or you don't know which prompt template to use.",
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

    def prompt_template(self, system_message: str, prompt: str):
        if not self.api_handles_prompt_template:
            return super().prompt_template(system_message, prompt)
        return prompt

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

        try:
            if is_chat:
                # Chat completions endpoint
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

                                    usage = data_obj.get("usage", {})

                                    if not usage:
                                        continue

                                    completion_tokens = usage.get(
                                        "completion_tokens", 0
                                    )
                                    prompt_tokens = usage.get("prompt_tokens", 0)

                                    if content:
                                        response_text += content
                                        self.update_request_tokens(
                                            self.count_tokens(content)
                                        )
                                except (json.JSONDecodeError, IndexError):
                                    # ignore malformed json chunks
                                    pass

            # Save token stats for logging
            self._returned_prompt_tokens = prompt_tokens
            self._returned_response_tokens = completion_tokens

            return response_text

        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="Client API: Permission Denied", status="error")
            return ""
        except httpx.ConnectTimeout:
            self.log.error("API timeout")
            emit("status", message="TabbyAPI: Request timed out", status="error")
            return ""
        except Exception as e:
            import traceback

            print(traceback.format_exc())
            self.log.error("generate error", e=e)
            emit(
                "status", message="Error during generation (check logs)", status="error"
            )
            return ""

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
