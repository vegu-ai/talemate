import random
from typing import Literal
import json
import httpx
import pydantic
import structlog
from openai import AsyncOpenAI, PermissionDeniedError

from talemate.client.base import ClientBase, ExtraField, CommonDefaults
from talemate.client.registry import register
from talemate.client.utils import urljoin
from talemate.config import Client as BaseClientConfig
from talemate.emit import emit

log = structlog.get_logger("talemate.client.tabbyapi")

EXPERIMENTAL_DESCRIPTION = """Use this client to use all of TabbyAPI's features"""


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

    class Meta(ClientBase.Meta):
        title: str = "TabbyAPI"
        name_prefix: str = "TabbyAPI"
        experimental: str = EXPERIMENTAL_DESCRIPTION
        enable_api_auth: bool = True
        manual_model: bool = False
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = {
            "api_handles_prompt_template": ExtraField(
                name="api_handles_prompt_template",
                type="bool",
                label="API handles prompt template (chat/completions)",
                required=False,
                description="The API handles the prompt template, meaning your choice in the UI for the prompt template below will be ignored. This is not recommended and should only be used if the API does not support the `completions` endpoint or you don't know which prompt template to use.",
            )
        }

    def __init__(
        self, model=None, api_key=None, api_handles_prompt_template=False, **kwargs
    ):
        self.model_name = model
        self.api_key = api_key
        self.api_handles_prompt_template = api_handles_prompt_template
        self.client = None
        super().__init__(**kwargs)

    @property
    def experimental(self):
        return EXPERIMENTAL_DESCRIPTION

    @property
    def can_be_coerced(self):
        """
        Determines whether or not this client can pass LLM coercion. (e.g., is able to predefine partial LLM output in the prompt)
        """
        return not self.api_handles_prompt_template

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

    def set_client(self, **kwargs):
        self.api_key = kwargs.get("api_key", self.api_key)
        self.api_handles_prompt_template = kwargs.get(
            "api_handles_prompt_template", self.api_handles_prompt_template
        )
        self.model_name = (
            kwargs.get("model") or kwargs.get("model_name") or self.model_name
        )
        
        # Initialize AsyncOpenAI client
        self.client = AsyncOpenAI(
            api_key=self.api_key or "dummy-key",  # TabbyAPI may not require API key
            base_url=self.api_url,
            default_headers={"x-api-key": self.api_key} if self.api_key else None
        )

    def prompt_template(self, system_message: str, prompt: str):

        log.debug(
            "IS API HANDLING PROMPT TEMPLATE",
            api_handles_prompt_template=self.api_handles_prompt_template,
        )

        if not self.api_handles_prompt_template:
            return super().prompt_template(system_message, prompt)

        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>", "\nStart your response with: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")

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
        Generates text from the given prompt and parameters using AsyncOpenAI.
        """
        if not self.client:
            self.set_client()
            
        # Get model name if not already set
        if not self.model_name:
            self.model_name = await self.get_model_name()

        # Determine whether we are using chat or completions endpoint
        is_chat = self.api_handles_prompt_template

        try:
            response_text = ""
            completion_tokens = 0
            prompt_tokens = 0
            
            if is_chat:
                # Chat completions endpoint
                self.log.debug(
                    "generate (chat/completions)",
                    prompt=prompt[:128] + " ...",
                    parameters=parameters,
                )

                system_message = self.get_system_message(kind)
                messages = [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt.strip()}
                ]

                stream = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    stream=True,
                    **parameters
                )
                
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        response_text += content
                        self.update_request_tokens(self.count_tokens(content))
                    
                    # Some providers include usage data in chunks
                    if hasattr(chunk, 'usage') and chunk.usage:
                        if hasattr(chunk.usage, 'completion_tokens'):
                            completion_tokens = chunk.usage.completion_tokens
                        if hasattr(chunk.usage, 'prompt_tokens'):
                            prompt_tokens = chunk.usage.prompt_tokens
                
            else:
                # Completions endpoint (for raw prompt without chat formatting)
                self.log.debug(
                    "generate (completions)",
                    prompt=prompt[:128] + " ...",
                    parameters=parameters,
                )
                
                # Check for coercion
                prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
                
                # For completions endpoint, we need to use a different approach
                # Some providers might support completions, but we'll use chat completions
                # with a minimal system message
                messages = [
                    {"role": "system", "content": self.get_system_message(kind)},
                    {"role": "user", "content": prompt.strip()}
                ]
                
                if coercion_prompt:
                    messages.append({"role": "assistant", "content": coercion_prompt.strip()})

                stream = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    stream=True,
                    **parameters
                )
                
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        response_text += content
                        self.update_request_tokens(self.count_tokens(content))

            # Save token stats for logging
            self._returned_prompt_tokens = prompt_tokens or self.count_tokens(prompt)
            self._returned_response_tokens = completion_tokens or self.count_tokens(response_text)

            if is_chat:
                # Process indirect coercion
                response_text = self.process_response_for_indirect_coercion(prompt, response_text)

            return response_text

        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="Client API: Permission Denied", status="error")
            return ""
        except Exception as e:
            self.log.error("generate error", e=e)
            if "timeout" in str(e).lower():
                emit("status", message="TabbyAPI: Request timed out", status="error")
            else:
                emit("status", message="Error during generation (check logs)", status="error")
            return ""

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
        if "api_url" in kwargs:
            self.api_url = kwargs["api_url"]
        if "max_token_length" in kwargs:
            self.max_token_length = (
                int(kwargs["max_token_length"]) if kwargs["max_token_length"] else 8192
            )
        if "api_key" in kwargs:
            self.api_key = kwargs["api_key"]
        if "api_handles_prompt_template" in kwargs:
            self.api_handles_prompt_template = kwargs["api_handles_prompt_template"]
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])
        if "double_coercion" in kwargs:
            self.double_coercion = kwargs["double_coercion"]

        self._reconfigure_common_parameters(**kwargs)
        
        self.set_client(**kwargs)

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
