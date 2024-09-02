import random
import urllib
import asyncio

import pydantic
import structlog
from openai import AsyncOpenAI, PermissionDeniedError

from talemate.client.base import ClientBase, ExtraField
from talemate.client.registry import register
from talemate.config import Client as BaseClientConfig
from talemate.emit import emit
from talemate.client.model_prompts import model_prompt 

log = structlog.get_logger("talemate.client.infermatic")

# Hardcoded list of models, retrieved from the API
AVAILABLE_MODELS = [
    "MN-12B-Celeste-V1.9",
    "L3.1-70B-Euryale-v2.2-FP8-Dynamic",
    "Meta-Llama-3.1-70B-Instruct-FP8-dynamic",
    "WizardLM-2-8x22B",
    "MN-12B-Starcannon-v2",
    "Llama-3-TenyxChat-DaybreakStorywriter-70B-fp8-dynamic",
    "Mixtral-8x7B-Instruct-v0.1",
    "Llama-3-Lumimaid-70B-v0.1-Instruct-FP8-Dynamic",
    "Qwen2-72B-Instruct",
    "Miquliz-120b-v2.0-FP8-dynamic",
    "gemma-2-27b-it-FP8-Dynamic",
    "llama-3-lumimaid-8b-v0.1",
    "Midnight-Miqu-70B-v1.5",
    "L3-8B-Stheno-v3.3-32K",
    "L3-8B-Lunaris-v1",
    "magnum-v2-72b-FP8-Dynamic",
]


class Defaults(pydantic.BaseModel):
    api_url: str = "https://api.totalgpt.ai/" 
    api_key: str = ""
    max_token_length: int = 8192
    model: str = AVAILABLE_MODELS[0]
    double_coercion: str = None


class ClientConfig(BaseClientConfig):
    pass 


@register()
class InfermaticClient(ClientBase):
    client_type = "infermatic"
    conversation_retries = 0
    config_cls = ClientConfig
    auto_determine_prompt_template: bool = True

    class Meta(ClientBase.Meta):
        title: str = "Infermatic AI"
        name_prefix: str = "Infermatic AI"
        enable_api_auth: bool = True
        manual_model: bool = True
        manual_model_choices: list[str] = AVAILABLE_MODELS
        requires_prompt_template: bool = False 
        defaults: Defaults = Defaults()

    def __init__(self, model=None, api_key=None, **kwargs):
        self.model_name = model or AVAILABLE_MODELS[0] 
        self.api_key = api_key
        self.auto_determine_prompt_template_attempt = None 
        super().__init__(**kwargs)

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "presence_penalty",
            "max_tokens",
        ]

    def set_client(self, **kwargs):
        self.api_key = kwargs.get("api_key", self.api_key)
        url = self.api_url
        self.client = AsyncOpenAI(base_url=url, api_key=self.api_key)
        self.model_name = (
            kwargs.get("model") or kwargs.get("model_name") or self.model_name
        )

    async def get_model_name(self):
        return self.model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """Generates text using the Infermatic API."""
        try:
            self.log.debug(
                "generate (completions)",
                prompt=prompt[:128] + " ...",
                parameters=parameters,
            )
            response = await self.client.completions.create(
                model=self.model_name, prompt=prompt, **parameters
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

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))

        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])

        if "double_coercion" in kwargs:
            self.double_coercion = kwargs["double_coercion"]

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        pass
