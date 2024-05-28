import urllib
import aiohttp
import random
import pydantic
import structlog
from openai import AsyncOpenAI, NotFoundError, PermissionDeniedError

from talemate.client.base import ClientBase, ExtraField
from talemate.client.registry import register
from talemate.config import Client as BaseClientConfig
from talemate.emit import emit
from talemate.client.utils import urljoin

log = structlog.get_logger("talemate.client.tabbyapi")

EXPERIMENTAL_DESCRIPTION = """Use this client to use all of TabbyAPI's features"""

class CustomAPIClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        
    async def get_model_name(self):
        url = urljoin(self.base_url, "model")
        headers = {
            "x-api-key": self.api_key,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"Request failed: {response.status}")
                response_data = await response.json()
                model_name = response_data.get("id")
                # split by "/" and take last
                if model_name:
                    model_name = model_name.split("/")[-1]
                return model_name

    async def create_chat_completion(self, model, messages, **parameters):
        url = urljoin(self.base_url, "chat/completions")
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            "messages": messages,
            **parameters,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status != 200:
                    raise Exception(f"Request failed: {response.status}")
                return await response.json()

    async def create_completion(self, model, **parameters):
        url = urljoin(self.base_url, "completions")
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            **parameters,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status != 200:
                    raise Exception(f"Request failed: {response.status}")
                return await response.json()



class Defaults(pydantic.BaseModel):
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

    def __init__(self, model=None, api_key=None, api_handles_prompt_template=False, **kwargs):
        self.model_name = model
        self.api_key = api_key
        self.api_handles_prompt_template = api_handles_prompt_template
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
            "temperature_last",
            "temperature"
        ]

    def set_client(self, **kwargs):
        self.api_key = kwargs.get("api_key", self.api_key)
        self.api_handles_prompt_template = kwargs.get("api_handles_prompt_template", self.api_handles_prompt_template)
        self.client = CustomAPIClient(base_url=self.api_url, api_key=self.api_key)
        self.model_name = kwargs.get("model") or kwargs.get("model_name") or self.model_name

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
        return await self.client.get_model_name()

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """
        try:
            if self.api_handles_prompt_template:
                # Custom API handles prompt template
                # Use the chat completions endpoint
                self.log.debug("generate (chat/completions)", prompt=prompt[:128] + " ...", parameters=parameters)
                human_message = {"role": "user", "content": prompt.strip()}
                response = await self.client.create_chat_completion(self.model_name, [human_message], **parameters)
                response = response['choices'][0]['message']['content']
                return self.process_response_for_indirect_coercion(prompt, response)
            else:
                # Talemate handles prompt template
                # Use the completions endpoint
                self.log.debug("generate (completions)", prompt=prompt[:128] + " ...", parameters=parameters)
                parameters["prompt"] = prompt
                response = await self.client.create_completion(self.model_name, **parameters)
                return response['choices'][0]['text']
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="Client API: Permission Denied", status="error")
            return ""
        except Exception as e:
            self.log.error("generate error", e=e)
            emit("status", message="Error during generation (check logs)", status="error")
            return ""

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
        if "api_url" in kwargs:
            self.api_url = kwargs["api_url"]
        if "max_token_length" in kwargs:
            self.max_token_length = int(kwargs["max_token_length"]) if kwargs["max_token_length"] else 8192
        if "api_key" in kwargs:
            self.api_key = kwargs["api_key"]
        if "api_handles_prompt_template" in kwargs:
            self.api_handles_prompt_template = kwargs["api_handles_prompt_template"]
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])
        if "double_coercion" in kwargs:
            self.double_coercion = kwargs["double_coercion"]

        log.warning("reconfigure", kwargs=kwargs)
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
            adjusted_presence_penalty = round(random.uniform(
                presence_penalty + 0.1, presence_penalty + offset
            ),1)
            # Ensure presence_penalty does not exceed 0.5 and does not fall below 0.1
            prompt_config["presence_penalty"] = min(0.5, max(0.1, adjusted_presence_penalty))
        except KeyError:
            pass