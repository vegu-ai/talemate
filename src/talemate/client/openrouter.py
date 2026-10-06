import pydantic
import structlog
import httpx
import asyncio
import hashlib
import json
import time
from typing import Any, Callable

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
from talemate.emit import emit
from talemate.emit.signals import handlers
import talemate.emit.async_signals as async_signals

__all__ = [
    "OpenRouterClient",
]


class OpenRouterAPIError(Exception):
    """API error with HTTP status code preserved for error handling."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


log = structlog.get_logger("talemate.client.openrouter")

MODELS_URL = "https://openrouter.ai/api/v1/models"
DECISION_MODELS_URL = f"{MODELS_URL}?output_modalities=decisions"
IMAGE_MODELS_URL = "https://openrouter.ai/api/v1/images/models"
PROVIDERS_URL = "https://openrouter.ai/api/v1/providers"

# Failed fetches stay unlatched so the retry triggers (config saves, client
# status refreshes) can recover; the cooldown keeps them from hammering the
# API while it is unreachable.
FETCH_RETRY_COOLDOWN = 30.0

# Available models will be populated when talemate loads - this can be done without an API key
# and doing so improves the initial setup experience since all the models will be available right away.
# MODELS_URL only lists models that output text: its output_modalities filter defaults to "text".
AVAILABLE_MODELS = []

DECISION_MODELS: list["DecisionModel"] = []

# The image generation models of OpenRouter's Image API, keyed by model id in id order
IMAGE_MODELS: dict[str, "ImageModel"] = {}

# Available providers will be populated dynamically from OpenRouter API once a valid API key is set
AVAILABLE_PROVIDERS = []

DEFAULT_MODEL = "google/gemini-3.7-flash"

# Sampler parameters whose inclusion in the request payload is user-toggleable.
# Some OpenRouter providers hard-error when these are sent for certain models
# (e.g. Moonshot rejects non-zero penalties for kimi models), so they need to
# be omitted entirely (not just zeroed out).
TOGGLEABLE_PARAMETERS = (
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "frequency_penalty",
    "presence_penalty",
    "repetition_penalty",
)

ToggleableParametersConfig = toggleable_parameters_config(TOGGLEABLE_PARAMETERS)


class DecisionModel(pydantic.BaseModel):
    id: str
    name: str = ""


class ImageModel(pydantic.BaseModel):
    """What the image backend reads from an entry of the Image API model list."""

    id: str
    input_modalities: list[str] | None = None
    output_modalities: list[str] = pydantic.Field(default_factory=list)
    # the listed values of these parameters, empty when the model lists none
    aspect_ratios: list[str] = pydantic.Field(default_factory=list)
    output_formats: list[str] = pydantic.Field(default_factory=list)
    # the listed input_references range, None when the model lists none
    min_references: int | None = None
    max_references: int | None = None

    @classmethod
    def from_entry(cls, entry: dict) -> "ImageModel":
        parameters = entry.get("supported_parameters") or {}
        min_references, max_references = _range_values(
            parameters.get("input_references")
        )
        return cls(
            id=entry["id"],
            input_modalities=(entry.get("architecture") or {}).get("input_modalities"),
            output_modalities=(entry.get("architecture") or {}).get("output_modalities")
            or [],
            aspect_ratios=_enum_values(parameters.get("aspect_ratio")),
            output_formats=_enum_values(parameters.get("output_format")),
            min_references=min_references,
            max_references=max_references,
        )

    @property
    def outputs_text(self) -> bool:
        return "text" in self.output_modalities

    @property
    def svg_only(self) -> bool:
        return set(self.output_formats) == {"svg"}

    @property
    def needs_references(self) -> bool:
        return bool(self.min_references)

    @property
    def takes_references(self) -> bool:
        return self.max_references != 0


def _enum_values(descriptor: dict | None) -> list[str]:
    if not descriptor or descriptor.get("type") != "enum":
        return []
    return [str(value) for value in descriptor.get("values") or []]


def _range_values(descriptor: dict | None) -> tuple[int | None, int | None]:
    if not descriptor or descriptor.get("type") != "range":
        return None, None
    return descriptor.get("min"), descriptor.get("max")


class ListFetch:
    """Fetch state of one OpenRouter list: the success latch, the retry
    cooldown and the lock that keeps concurrent fetches apart."""

    def __init__(self):
        self.fetched = False
        # None = never attempted; time.monotonic() can be < FETCH_RETRY_COOLDOWN on a
        # freshly-booted host, so a 0.0 sentinel would wrongly cool down the first try.
        self.last_attempt: float | None = None
        self.lock = asyncio.Lock()

    def reset(self):
        self.fetched = False
        self.last_attempt = None

    def begin_attempt(self) -> bool:
        """Record an attempt now, unless the previous one is inside the cooldown."""
        now = time.monotonic()
        if (
            self.last_attempt is not None
            and now - self.last_attempt < FETCH_RETRY_COOLDOWN
        ):
            return False
        self.last_attempt = now
        return True


MODELS_FETCH = ListFetch()
DECISION_MODELS_FETCH = ListFetch()
IMAGE_MODELS_FETCH = ListFetch()
PROVIDERS_FETCH = ListFetch()

# digest of the API key the lists were last fetched for; a config save with
# another key fetches every list again
_lists_key_digest: str | None = None


async def _fetch_list(
    state: ListFetch,
    list_name: str,
    url: str,
    parse: Callable[[list[dict]], Any],
    headers: dict | None = None,
    refresh: bool = False,
) -> Any:
    """One fetch attempt for a list. Returns the parsed list, or None when the
    list is already fetched (and not refreshed), the attempt is cooling down or
    the fetch failed."""
    if state.fetched and not refresh:
        return None

    async with state.lock:
        if (state.fetched and not refresh) or not state.begin_attempt():
            return None

        try:
            log.debug(f"Fetching {list_name} from OpenRouter")
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
            if response.status_code != 200:
                log.error(
                    f"Failed to fetch {list_name} from OpenRouter: HTTP {response.status_code}"
                )
                return None
            result = parse(response.json().get("data", []))
        except Exception as e:
            log.error(f"Error fetching {list_name} from OpenRouter: {e}")
            return None

        state.fetched = True
        log.debug(f"Fetched {len(result)} {list_name} from OpenRouter")
        return result


def _on_list_changed():
    # agent settings carry these lists as field choices, and those reach the
    # frontend with the agent status
    emit("request_agent_status")


async def fetch_available_models(api_key: str = None):
    global AVAILABLE_MODELS
    models = await _fetch_list(
        MODELS_FETCH,
        "models",
        MODELS_URL,
        lambda data: sorted(model["id"] for model in data if model.get("id")),
    )
    if models is not None and models != AVAILABLE_MODELS:
        AVAILABLE_MODELS = models
        _on_list_changed()
    return AVAILABLE_MODELS


def _parse_decision_models(data: list[dict]) -> list[DecisionModel]:
    models = []
    for entry in data:
        try:
            if not entry.get("id"):
                continue
            models.append(DecisionModel(id=entry["id"], name=entry.get("name") or ""))
        except (AttributeError, TypeError, pydantic.ValidationError) as e:
            log.warning(f"Skipped an OpenRouter decision model entry: {e}")
    return sorted(models, key=lambda model: model.id)


async def fetch_available_decision_models() -> list[DecisionModel]:
    global DECISION_MODELS
    models = await _fetch_list(
        DECISION_MODELS_FETCH,
        "decision models",
        DECISION_MODELS_URL,
        _parse_decision_models,
    )
    if models is not None and models != DECISION_MODELS:
        DECISION_MODELS = models
        emit(
            "decision_models_changed",
            data={"models": [model.model_dump() for model in models]},
        )
    return DECISION_MODELS


def _parse_image_models(data: list[dict]) -> dict[str, ImageModel]:
    models = {}
    for entry in data:
        try:
            model = ImageModel.from_entry(entry)
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            # one malformed entry must not take the routing data of every
            # other model down with it
            log.warning(f"Skipped an OpenRouter image model entry: {e}")
            continue
        models[model.id] = model
    return dict(sorted(models.items()))


async def fetch_available_image_models(
    refresh: bool = False,
) -> dict[str, ImageModel]:
    """`refresh` fetches a loaded list again, at most once per retry cooldown."""
    global IMAGE_MODELS
    models = await _fetch_list(
        IMAGE_MODELS_FETCH,
        "image models",
        IMAGE_MODELS_URL,
        _parse_image_models,
        refresh=refresh,
    )
    if models is not None and models != IMAGE_MODELS:
        IMAGE_MODELS = models
        _on_list_changed()
    return IMAGE_MODELS


async def fetch_available_providers(api_key: str = None):
    """Fetch available providers from OpenRouter API"""
    global AVAILABLE_PROVIDERS

    if PROVIDERS_FETCH.fetched:
        return AVAILABLE_PROVIDERS

    if not api_key:
        api_key = get_config().openrouter.api_key

    if not api_key:
        # No key yet (e.g. initial setup) — stay unlatched so the fetch
        # reruns once a key is saved.
        log.warning("No OpenRouter API key available, cannot fetch providers")
        return AVAILABLE_PROVIDERS

    providers = await _fetch_list(
        PROVIDERS_FETCH,
        "providers",
        PROVIDERS_URL,
        lambda data: sorted(
            provider["name"] for provider in data if provider.get("name")
        ),
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if providers is not None and providers != AVAILABLE_PROVIDERS:
        AVAILABLE_PROVIDERS = providers
        _on_list_changed()
    return AVAILABLE_PROVIDERS


async def fetch_lists(api_key: str | None):
    await asyncio.gather(
        fetch_available_models(api_key),
        fetch_available_decision_models(),
        fetch_available_image_models(),
        fetch_available_providers(api_key),
    )


def _key_digest(api_key: str | None) -> str | None:
    return hashlib.sha256(api_key.encode()).hexdigest() if api_key else None


def on_talemate_started(event):
    global _lists_key_digest
    api_key = get_config().openrouter.api_key
    _lists_key_digest = _key_digest(api_key)
    loop = asyncio.get_event_loop()
    loop.create_task(fetch_lists(api_key))


async def on_config_saved(config):
    """Retry the lists that failed; a changed API key fetches every list again."""
    global _lists_key_digest
    api_key = config.openrouter.api_key
    key_digest = _key_digest(api_key)
    if key_digest != _lists_key_digest:
        _lists_key_digest = key_digest
        for state in (MODELS_FETCH, IMAGE_MODELS_FETCH, PROVIDERS_FETCH):
            state.reset()
    await fetch_lists(api_key)


handlers["talemate_started"].connect(on_talemate_started)
async_signals.get("config.saved").connect(on_config_saved)


class Defaults(
    ReasoningEffortConfig,
    ToggleableParametersConfig,
    CommonDefaults,
    pydantic.BaseModel,
):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL
    # Reasoning on by default: with it off the client is coercible, and several
    # providers (Google, Anthropic) reject the coercion prefill outright since
    # the request then ends on a model turn.
    reason_enabled: bool = True
    reason_tokens: int = 2048
    provider_only: list[str] = pydantic.Field(default_factory=list)
    provider_ignore: list[str] = pydantic.Field(default_factory=list)


class ClientConfig(
    ReasoningEffortConfig,
    ToggleableParametersConfig,
    ConcurrentInference,
    BaseClientConfig,
):
    concurrent_inference_enabled: bool = True
    provider_only: list[str] = pydantic.Field(default_factory=list)
    provider_ignore: list[str] = pydantic.Field(default_factory=list)


PROVIDER_FIELD_GROUP = FieldGroup(
    name="provider",
    label="Provider",
    description="Configure OpenRouter provider routing.",
    icon="mdi-server-network",
)


def cache_control_for_model(model_name: str) -> dict | None:
    """
    Return the cache_control parameter needed to enable prompt caching for
    the given OpenRouter model, or None if no parameter is required.

    OpenAI / DeepSeek / Gemini cache automatically on OpenRouter. Anthropic
    models require explicit cache_control or the request is never cached.
    For Anthropic, top-level ephemeral cache_control mirrors the native SDK's
    automatic-cache mode — the breakpoint is auto-placed on the last cacheable
    block. Note: this forces routing to direct Anthropic, excluding Bedrock
    and Vertex endpoints.
    """
    if model_name.startswith("anthropic/"):
        return {"type": "ephemeral"}
    return None


@register()
class OpenRouterClient(
    ReasoningEffortMixin,
    ConcurrentInferenceMixin,
    ToggleableParametersMixin,
    ClientBase,
):
    """
    OpenRouter client for generating text using various models.
    """

    client_type = "openrouter"
    conversation_retries = 0
    # TODO: make this configurable?
    decensor_enabled = False
    config_cls = ClientConfig
    toggleable_parameters = TOGGLEABLE_PARAMETERS

    class Meta(ClientBase.Meta):
        name_prefix: str = "OpenRouter"
        title: str = "OpenRouter"
        manual_model: bool = True
        manual_model_choices: list[str] = pydantic.Field(
            default_factory=lambda: AVAILABLE_MODELS
        )
        unified_api_key_config_path: str = "openrouter.api_key"
        requires_prompt_template: bool = False
        reason_tokens_as_allowance: bool = True
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
            fields.update(reasoning_effort_extra_fields())
            fields.update(toggleable_parameters_extra_fields(TOGGLEABLE_PARAMETERS))
            fields.update(concurrent_inference_extra_fields())
            return fields

        extra_fields: dict[str, ExtraField] = pydantic.Field(
            default_factory=_build_extra_fields
        )

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
    def reasoning_effort_format(self) -> EffortFormat:
        return "reasoning"

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
        # Retry fetches that haven't succeeded yet (e.g. the initial fetch
        # failed, or ran before an API key was configured) — the fetchers
        # latch on success and rate-limit retries internally.
        if not MODELS_FETCH.fetched:
            await fetch_available_models(self.openrouter_api_key)

        if not PROVIDERS_FETCH.fetched and self.openrouter_api_key:
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

        if self.optimize_prompt_caching:
            cache_control = cache_control_for_model(self.model_name)
            if cache_control is not None:
                parameters["cache_control"] = cache_control

        # Prepare request payload
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            **parameters,
        }
        if self.reason_enabled:
            # OpenRouter refuses reasoning.effort and reasoning.max_tokens together.
            payload["reasoning"] = (
                {"effort": self.reasoning_effort}
                if self.reasoning_effort is not None
                else {"enabled": True}
            )

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
                    if response.status_code != 200:
                        error_body = ""
                        async for chunk in response.aiter_text():
                            error_body += chunk
                        error_msg = (
                            f"OpenRouter API returned status {response.status_code}"
                        )
                        try:
                            error_data = json.loads(error_body)
                            if "error" in error_data:
                                error_detail = error_data["error"]
                                if isinstance(error_detail, dict):
                                    error_msg = f"OpenRouter API Error: {error_detail.get('message', error_body)}"
                                else:
                                    error_msg = f"OpenRouter API Error: {error_detail}"
                        except (json.JSONDecodeError, KeyError):
                            error_msg = f"OpenRouter API Error ({response.status_code}): {error_body[:200]}"
                        status_code = response.status_code

                        # Remap 400 "not a valid model ID" to 404
                        if status_code == 400 and "not a valid model" in error_msg:
                            status_code = 404

                        self.log.error(
                            "openrouter_api_error",
                            status=status_code,
                            body=error_body[:500],
                        )
                        raise OpenRouterAPIError(error_msg, status_code)

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

                                    # OpenRouter may send chunks with empty choices
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
