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
    "RequestyClient",
]


class RequestyAPIError(Exception):
    """API error with HTTP status code preserved for error handling."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


log = structlog.get_logger("talemate.client.requesty")

# Available models will be populated when talemate loads - this can be done without an API key
# and doing so imrpoves the initial setup experience since all the models will be available right away
AVAILABLE_MODELS = []

DEFAULT_MODEL = "openai/gpt-4o-mini"
MODELS_FETCHED = False

_MODELS_LOCK = asyncio.Lock()


async def fetch_available_models(api_key: str = None):
    """Fetch available models from Requesty API"""
    global AVAILABLE_MODELS, DEFAULT_MODEL, MODELS_FETCHED

    if MODELS_FETCHED:
        return AVAILABLE_MODELS

    async with _MODELS_LOCK:
        if MODELS_FETCHED:
            return AVAILABLE_MODELS

        try:
            log.debug("Fetching models from Requesty")
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://router.requesty.ai/v1/models", timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for model in data.get("data", []):
                        model_id = model.get("id")
                        if model_id:
                            models.append(model_id)
                    AVAILABLE_MODELS = sorted(models)
                    log.debug(f"Fetched {len(AVAILABLE_MODELS)} models from Requesty")
                else:
                    log.warning(
                        f"Failed to fetch models from Requesty: {response.status_code}"
                    )
        except Exception as e:
            log.error(f"Error fetching models from Requesty: {e}")

        MODELS_FETCHED = True
        return AVAILABLE_MODELS


def on_talemate_started(event):
    """Spawn background tasks to fetch models"""
    api_key = get_config().requesty.api_key
    loop = asyncio.get_event_loop()
    loop.create_task(fetch_available_models(api_key))


async def on_config_saved(config):
    api_key = config.requesty.api_key
    await fetch_available_models(api_key)


handlers["talemate_started"].connect(on_talemate_started)
async_signals.get("config.saved").connect(on_config_saved)


class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL


class ClientConfig(ConcurrentInference, BaseClientConfig):
    pass


MIN_THINKING_TOKENS = 256


@register()
class RequestyClient(ConcurrentInferenceMixin, ClientBase):
    """
    Requesty client for generating text using various models.
    """

    client_type = "requesty"
    conversation_retries = 0
    # TODO: make this configurable?
    decensor_enabled = False
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "Requesty"
        title: str = "Requesty"
        manual_model: bool = True
        manual_model_choices: list[str] = pydantic.Field(
            default_factory=lambda: AVAILABLE_MODELS
        )
        unified_api_key_config_path: str = "requesty.api_key"
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

        @staticmethod
        def _build_extra_fields():
            fields = {}
            fields.update(concurrent_inference_extra_fields())
            return fields

        extra_fields: dict[str, ExtraField] = pydantic.Field(
            default_factory=_build_extra_fields
        )

    def __init__(self, **kwargs):
        self._models_fetched = False
        super().__init__(**kwargs)

    @property
    def can_be_coerced(self) -> bool:
        return not self.reason_enabled

    @property
    def requesty_api_key(self):
        return self.config.requesty.api_key

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

        if self.requesty_api_key:
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
                    "requesty_api",
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
        if not self._models_fetched:
            self._models_fetched = True
            # Update the Meta class with new model choices
            self.Meta.manual_model_choices = AVAILABLE_MODELS

        self.emit_status()

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters using Requesty API.
        """

        if not self.requesty_api_key:
            raise Exception("No Requesty API key set")

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
                    "https://router.requesty.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.requesty_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=120.0,  # 2 minute timeout for generation
                ) as response:
                    if response.status_code != 200:
                        error_body = ""
                        async for chunk in response.aiter_text():
                            error_body += chunk
                        error_msg = (
                            f"Requesty API returned status {response.status_code}"
                        )
                        try:
                            error_data = json.loads(error_body)
                            if "error" in error_data:
                                error_detail = error_data["error"]
                                if isinstance(error_detail, dict):
                                    error_msg = f"Requesty API Error: {error_detail.get('message', error_body)}"
                                else:
                                    error_msg = f"Requesty API Error: {error_detail}"
                        except (json.JSONDecodeError, KeyError):
                            error_msg = f"Requesty API Error ({response.status_code}): {error_body[:200]}"
                        status_code = response.status_code

                        # Remap 400 "not a valid model ID" to 404
                        if status_code == 400 and "not a valid model" in error_msg:
                            status_code = 404

                        self.log.error(
                            "requesty_api_error",
                            status=status_code,
                            body=error_body[:500],
                        )
                        raise RequestyAPIError(error_msg, status_code)

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

                                    usage = data_obj.get("usage", {})
                                    completion_tokens += usage.get(
                                        "completion_tokens", 0
                                    )
                                    prompt_tokens += usage.get("prompt_tokens", 0)

                                    # Requesty may send chunks with empty choices
                                    # (e.g. usage-only or debug chunks)
                                    choices = data_obj.get("choices", [])
                                    if not choices:
                                        continue

                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    reasoning = delta.get("reasoning")

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

        except Exception:
            raise
