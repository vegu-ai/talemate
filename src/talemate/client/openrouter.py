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
from talemate.client.remote import (
    ConcurrentInferenceMixin,
    concurrent_inference_extra_fields,
    ConcurrentInference,
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

# Available models will be populated when talemate loads - this can be done without an API key
# and doing so imrpoves the initial setup experience since all the models will be available right away
AVAILABLE_MODELS = []

# Available providers will be populated dynamically from OpenRouter API once a valid API key is set
AVAILABLE_PROVIDERS = []

DEFAULT_MODEL = "google/gemini-3-flash-preview"
MODELS_FETCHED = False
PROVIDERS_FETCHED = False


async def fetch_available_models(api_key: str = None):
    """Fetch available models from OpenRouter API"""
    global AVAILABLE_MODELS, DEFAULT_MODEL, MODELS_FETCHED

    if MODELS_FETCHED:
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


async def fetch_available_providers(api_key: str = None):
    """Fetch available providers from OpenRouter API"""
    global AVAILABLE_PROVIDERS, PROVIDERS_FETCHED

    if PROVIDERS_FETCHED:
        return AVAILABLE_PROVIDERS

    if not api_key:
        api_key = get_config().openrouter.api_key

    if not api_key:
        log.warning("No OpenRouter API key available, cannot fetch providers")
        PROVIDERS_FETCHED = True
        return AVAILABLE_PROVIDERS

    try:
        log.debug("Fetching providers from OpenRouter")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/providers",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                providers = []
                for provider in data.get("data", []):
                    provider_name = provider.get("name")
                    if provider_name:
                        providers.append(provider_name)
                AVAILABLE_PROVIDERS = sorted(providers)
                log.info(
                    f"Fetched {len(AVAILABLE_PROVIDERS)} providers from OpenRouter"
                )
            else:
                log.error(
                    f"Failed to fetch providers from OpenRouter: HTTP {response.status_code}"
                )
    except Exception as e:
        log.error(f"Error fetching providers from OpenRouter: {e}")

    PROVIDERS_FETCHED = True
    return AVAILABLE_PROVIDERS


def on_talemate_started(event):
    """Spawn background tasks to fetch models and providers"""
    api_key = get_config().openrouter.api_key
    loop = asyncio.get_event_loop()
    loop.create_task(fetch_available_models(api_key))
    loop.create_task(fetch_available_providers(api_key))


async def on_config_saved(config):
    api_key = config.openrouter.api_key
    await fetch_available_models(api_key)
    await fetch_available_providers(api_key)


handlers["talemate_started"].connect(on_talemate_started)
async_signals.get("config.saved").connect(on_config_saved)


class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL
    provider_only: list[str] = pydantic.Field(default_factory=list)
    provider_ignore: list[str] = pydantic.Field(default_factory=list)


class ClientConfig(ConcurrentInference, BaseClientConfig):
    provider_only: list[str] = pydantic.Field(default_factory=list)
    provider_ignore: list[str] = pydantic.Field(default_factory=list)


PROVIDER_FIELD_GROUP = FieldGroup(
    name="provider",
    label="Provider",
    description="Configure OpenRouter provider routing.",
    icon="mdi-server-network",
)

MIN_THINKING_TOKENS = 1024


@register()
class OpenRouterClient(ConcurrentInferenceMixin, ClientBase):
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

        @staticmethod
        def _build_extra_fields():
            """Build extra_fields dynamically so choices reflect current AVAILABLE_PROVIDERS"""
            fields = {
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
            fields.update(concurrent_inference_extra_fields())
            return fields

        extra_fields: dict[str, ExtraField] = pydantic.Field(
            default_factory=_build_extra_fields
        )

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
    def min_reason_tokens(self) -> int:
        return MIN_THINKING_TOKENS

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
        # Fetch models and providers if we have an API key and haven't fetched yet
        if not self._models_fetched:
            self._models_fetched = True
            # Update the Meta class with new model choices
            self.Meta.manual_model_choices = AVAILABLE_MODELS

        # Fetch providers if not already fetched
        if not PROVIDERS_FETCHED and self.openrouter_api_key:
            await fetch_available_providers(self.openrouter_api_key)

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
                        response=response_content[:128] + " ..."
                        if len(response_content) > 128
                        else response_content,
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
