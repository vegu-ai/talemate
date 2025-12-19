import pydantic
import structlog
import httpx
import asyncio
import json

from talemate.client.base import (
    ClientBase,
    ErrorAction,
    CommonDefaults,
    ExtraField,
    FieldGroup,
)
from talemate.config.schema import Client as BaseClientConfig
from talemate.config import get_config

from talemate.client.registry import register
from talemate.emit import emit
from talemate.emit.signals import handlers
import talemate.emit.async_signals as async_signals

__all__ = [
    "OpenRouterClient",
]

log = structlog.get_logger("talemate.client.openrouter")

# Available models will be populated when first client with API key is initialized
AVAILABLE_MODELS = []

# Static list of providers that are supported by OpenRouter
# https://openrouter.ai/docs/features/provider-routing#json-schema-for-provider-preferences


AVAILABLE_PROVIDERS = [
    "AnyScale",
    "Cent-ML",
    "HuggingFace",
    "Hyperbolic 2",
    "Lepton",
    "Lynn 2",
    "Lynn",
    "Mancer",
    "Modal",
    "OctoAI",
    "Recursal",
    "Reflection",
    "Replicate",
    "SambaNova 2",
    "SF Compute",
    "Together 2",
    "01.AI",
    "AI21",
    "AionLabs",
    "Alibaba",
    "Amazon Bedrock",
    "Anthropic",
    "AtlasCloud",
    "Atoma",
    "Avian",
    "Azure",
    "BaseTen",
    "Cerebras",
    "Chutes",
    "Cloudflare",
    "Cohere",
    "CrofAI",
    "Crusoe",
    "DeepInfra",
    "DeepSeek",
    "Enfer",
    "Featherless",
    "Fireworks",
    "Friendli",
    "GMICloud",
    "Google",
    "Google AI Studio",
    "Groq",
    "Hyperbolic",
    "Inception",
    "InferenceNet",
    "Infermatic",
    "Inflection",
    "InoCloud",
    "Kluster",
    "Lambda",
    "Liquid",
    "Mancer 2",
    "Meta",
    "Minimax",
    "Mistral",
    "Moonshot AI",
    "Morph",
    "NCompass",
    "Nebius",
    "NextBit",
    "Nineteen",
    "Novita",
    "OpenAI",
    "OpenInference",
    "Parasail",
    "Perplexity",
    "Phala",
    "SambaNova",
    "Stealth",
    "Switchpoint",
    "Targon",
    "Together",
    "Ubicloud",
    "Venice",
    "xAI",
]
AVAILABLE_PROVIDERS.sort()

DEFAULT_MODEL = ""
MODELS_FETCHED = False


async def fetch_available_models(api_key: str = None):
    """Fetch available models from OpenRouter API"""
    global AVAILABLE_MODELS, DEFAULT_MODEL, MODELS_FETCHED
    if not api_key:
        return []

    if MODELS_FETCHED:
        return AVAILABLE_MODELS

    # Only fetch if we haven't already or if explicitly requested
    if AVAILABLE_MODELS and not api_key:
        return AVAILABLE_MODELS

    try:
        log.debug("Fetching models from OpenRouter")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models", timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get("data", []):
                    model_id = model.get("id")
                    if model_id:
                        models.append(model_id)
                AVAILABLE_MODELS = sorted(models)
                log.debug(f"Fetched {len(AVAILABLE_MODELS)} models from OpenRouter")
            else:
                log.warning(
                    f"Failed to fetch models from OpenRouter: {response.status_code}"
                )
    except Exception as e:
        log.error(f"Error fetching models from OpenRouter: {e}")

    MODELS_FETCHED = True
    return AVAILABLE_MODELS


def fetch_models_sync(api_key: str):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(fetch_available_models(api_key))


def on_talemate_started(event):
    fetch_models_sync(get_config().openrouter.api_key)


async def on_config_saved(config):
    api_key = config.openrouter.api_key
    await fetch_available_models(api_key)


handlers["talemate_started"].connect(on_talemate_started)
async_signals.get("config.saved").connect(on_config_saved)


class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL
    provider_only: list[str] = pydantic.Field(default_factory=list)
    provider_ignore: list[str] = pydantic.Field(default_factory=list)


class ClientConfig(BaseClientConfig):
    provider_only: list[str] = pydantic.Field(default_factory=list)
    provider_ignore: list[str] = pydantic.Field(default_factory=list)


PROVIDER_FIELD_GROUP = FieldGroup(
    name="provider",
    label="Provider",
    description="Configure OpenRouter provider routing.",
    icon="mdi-server-network",
)


@register()
class OpenRouterClient(ClientBase):
    """
    OpenRouter client for generating text using various models.
    """

    client_type = "openrouter"
    conversation_retries = 0
    # TODO: make this configurable?
    decensor_enabled = False
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "OpenRouter"
        title: str = "OpenRouter"
        manual_model: bool = True
        manual_model_choices: list[str] = pydantic.Field(
            default_factory=lambda: AVAILABLE_MODELS
        )
        unified_api_key_config_path: str = "openrouter.api_key"
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = {
            "provider_only": ExtraField(
                name="provider_only",
                type="flags",
                label="Only use these providers",
                choices=AVAILABLE_PROVIDERS,
                description="Manually limit the providers to use for the selected model. This will override the default provider selection for this model.",
                group=PROVIDER_FIELD_GROUP,
                required=False,
            ),
            "provider_ignore": ExtraField(
                name="provider_ignore",
                type="flags",
                label="Ignore these providers",
                choices=AVAILABLE_PROVIDERS,
                description="Ignore these providers for the selected model. This will override the default provider selection for this model.",
                group=PROVIDER_FIELD_GROUP,
                required=False,
            ),
        }

    def __init__(self, **kwargs):
        self._models_fetched = False
        super().__init__(**kwargs)

    @property
    def provider_only(self) -> list[str]:
        return self.client_config.provider_only

    @property
    def provider_ignore(self) -> list[str]:
        return self.client_config.provider_ignore

    @property
    def can_be_coerced(self) -> bool:
        return not self.reason_enabled

    @property
    def openrouter_api_key(self):
        return self.config.openrouter.api_key
    
    @property
    def requires_reasoning_pattern(self) -> bool:
        return False

    @property
    def requires_reasoning_pattern(self) -> bool:
        return False

    @property
    def requires_reasoning_pattern(self) -> bool:
        return False

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "frequency_penalty",
            "presence_penalty",
            "repetition_penalty",
            "max_tokens",
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        error_message = None
        if processing is not None:
            self.processing = processing

        if self.openrouter_api_key:
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
                    "openrouter_api",
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

    async def status(self):
        # Fetch models if we have an API key and haven't fetched yet
        if self.openrouter_api_key and not self._models_fetched:
            self._models_fetched = True
            # Update the Meta class with new model choices
            self.Meta.manual_model_choices = AVAILABLE_MODELS

        self.emit_status()

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters using OpenRouter API.
        """

        if not self.openrouter_api_key:
            raise Exception("No OpenRouter API key set")

        if self.can_be_coerced:
            prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        else:
            coercion_prompt = None

        # Prepare messages for chat completion
        messages = [
            {"role": "system", "content": self.get_system_message(kind)},
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

        provider = {}
        if self.provider_only:
            provider["only"] = self.provider_only
        if self.provider_ignore:
            provider["ignore"] = self.provider_ignore

        if provider:
            parameters["provider"] = provider

        # Prepare request payload
        payload = {
            "model": self.model_name,
            "messages": messages,
            "reasoning": {
                "max_tokens": self.validated_reason_tokens,
            },
            "stream": True,
            **parameters,
        }

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            model=self.model_name,
        )

        response_text = ""
        reasoning_text = ""
        buffer = ""
        completion_tokens = 0
        prompt_tokens = 0
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=120.0,  # 2 minute timeout for generation
                ) as response:
                    async for chunk in response.aiter_text():
                        buffer += chunk

                        while True:
                            # Find the next complete SSE line
                            line_end = buffer.find("\n")
                            if line_end == -1:
                                break

                            line = buffer[:line_end].strip()
                            buffer = buffer[line_end + 1 :]

                            if line.startswith("data: "):
                                data = line[6:]
                                if data == "[DONE]":
                                    break

                                try:
                                    data_obj = json.loads(data)
                                    delta = data_obj["choices"][0]["delta"]
                                    content = delta.get("content")
                                    reasoning = delta.get("reasoning")
                                    usage = data_obj.get("usage", {})
                                    completion_tokens += usage.get(
                                        "completion_tokens", 0
                                    )
                                    prompt_tokens += usage.get("prompt_tokens", 0)
                                    
                                    if reasoning:
                                        reasoning_text += reasoning
                                        self.update_request_tokens(
                                            self.count_tokens(reasoning)
                                        )
                                    
                                    if content:
                                        response_text += content
                                        # Update tokens as content streams in
                                        self.update_request_tokens(
                                            self.count_tokens(content)
                                        )

                                except (json.JSONDecodeError, KeyError):
                                    pass

                    # Extract the response content
                    response_content = response_text
                    self._returned_prompt_tokens = prompt_tokens
                    self._returned_response_tokens = completion_tokens
                    self._reasoning_response = reasoning_text

                    self.log.debug(
                        "generated response",
                        response=response_content[:128] + " ..." if len(response_content) > 128 else response_content,
                        reasoning_length=len(reasoning_text),
                    )

                    return response_content

        except httpx.ConnectTimeout:
            self.log.error("OpenRouter API timeout")
            emit("status", message="OpenRouter API: Request timed out", status="error")
            return ""
        except Exception as e:
            self.log.error("generate error", e=e)
            emit("status", message=f"OpenRouter API Error: {str(e)}", status="error")
            raise
