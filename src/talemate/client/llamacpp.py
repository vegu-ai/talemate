import asyncio
import json
from typing import Literal, NoReturn

import pydantic
import httpx
from openai import APIStatusError, AsyncOpenAI

from talemate.client.api_handles import (
    ApiHandlesPromptTemplateConfig,
    ApiHandlesPromptTemplateMixin,
    ChatReasoningMixin,
    api_handles_prompt_template_extra_fields,
    strip_echoed_prefill,
)
from talemate.client.base import (
    ClientBase,
    ClientStatusValue,
    CommonDefaults,
    ExtraField,
    ParameterReroute,
)
from talemate.client.model_probe import OpenAIModelListProbeMixin
from talemate.client.model_prompts import model_prompt
from talemate.client.reasoning_effort import (
    EffortFormat,
    ReasoningEffortConfig,
    ReasoningEffortMixin,
    reasoning_effort_extra_fields,
)
from talemate.client.registry import register
from talemate.client.utils import dry_sequence_breakers_list
from talemate.client.remote import (
    ConcurrentInference,
    ConcurrentInferenceMixin,
    concurrent_inference_extra_fields,
)
from talemate.client.vision import VisionConfig, vision_extra_fields, OpenAIVisionMixin
from talemate.config.schema import Client as BaseClientConfig
from talemate.exceptions import GenerationProcessingError
from talemate.ux.schema import Condition, Note


REASONING_MODE_CHOICES = [
    {
        "label": "effort",
        "value": "effort",
        "description": "Sends the Reasoning Effort level to the model's chat template.",
    },
    {
        "label": "tokens",
        "value": "tokens",
        "description": "Cuts the thinking off once it reaches Reasoning Tokens; a small budget can push the reasoning into the answer.",
    },
]


ReasoningMode = Literal["effort", "tokens"]


class LlamaCppReasoningConfig(ReasoningEffortConfig):
    reasoning_mode: ReasoningMode = "effort"


def reasoning_extra_fields() -> dict[str, ExtraField]:
    fields = reasoning_effort_extra_fields()
    effort = fields["effort_level"]
    return {
        "reasoning_mode": ExtraField(
            name="reasoning_mode",
            type="text",
            label="Reasoning Mode",
            choices=REASONING_MODE_CHOICES,
            description="How the thinking is controlled while API handles prompt template is on: 'effort' sends the Reasoning Effort below, 'tokens' cuts the thinking off once it reaches the Reasoning Tokens. Without API handles prompt template neither is sent, and Reasoning Tokens only adds room to the response limit.",
            note_on_value={
                "tokens": Note(
                    text="While API handles prompt template is on, a very small budget can push the thinking into the answer.",
                ),
            },
            group=effort.group,
            required=False,
        ),
        "effort_level": effort.model_copy(
            update={
                "condition": Condition(attribute="reasoning_mode", value="effort"),
                "description": "Sent to the model's chat template while Reasoning is on. 'default' sends nothing and 'none' turns the thinking off; the other levels only change the output if the model's chat template uses them. Applies only while API handles prompt template is on.",
            }
        ),
    }


class Defaults(CommonDefaults, LlamaCppReasoningConfig, ApiHandlesPromptTemplateConfig):
    # llama.cpp `llama-server` defaults to port 8080 (see ggml-org/llama.cpp README)
    api_url: str = "http://localhost:8080"
    max_token_length: int = 16384
    api_handles_prompt_template: bool = True


class ClientConfig(
    ConcurrentInference,
    LlamaCppReasoningConfig,
    ApiHandlesPromptTemplateConfig,
    VisionConfig,
    BaseClientConfig,
):
    router_mode: bool = False


class ServerProperties(pydantic.BaseModel):
    role: str | None = None
    models_autoload: pydantic.StrictBool | None = None

    @pydantic.field_validator("models_autoload", mode="before")
    @classmethod
    def known_autoload_setting(cls, value):
        return value if isinstance(value, bool) else None


class ModelStatus(pydantic.BaseModel):
    value: str | None = None


class RouterModel(pydantic.BaseModel):
    id: str
    aliases: list[str] = pydantic.Field(default_factory=list)
    status: ModelStatus = pydantic.Field(default_factory=ModelStatus)


class RouterModels(pydantic.BaseModel):
    data: list[RouterModel]


class ChatDelta(pydantic.BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    reasoning: str | None = None

    @property
    def reasoning_text(self) -> str | None:
        return self.reasoning_content or self.reasoning


class ChatChoice(pydantic.BaseModel):
    delta: ChatDelta | None = None


class ChatChunk(pydantic.BaseModel):
    choices: list[ChatChoice] = pydantic.Field(default_factory=list)


@register()
class LlamaCppClient(
    ReasoningEffortMixin,
    ChatReasoningMixin,
    ApiHandlesPromptTemplateMixin,
    ConcurrentInferenceMixin,
    OpenAIVisionMixin,
    OpenAIModelListProbeMixin,
    ClientBase,
):
    """
    Client for ggml-org/llama.cpp `llama-server`.

    This client uses llama.cpp's richer, non-OpenAI endpoint:
      POST /completion

    With "API handles prompt template" it uses POST /v1/chat/completions.
    """

    auto_determine_prompt_template: bool = True
    client_type = "llamacpp"
    remote_model_locked: bool = True
    config_cls = ClientConfig

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._server_url = None
        self._server_role: Literal["unknown", "router"] = "unknown"
        self._router_detected = False
        self._models_autoload = None
        self._available_models: list[RouterModel] | None = None
        self._probe_error = None
        self._prompt_template_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def router_mode(self) -> bool:
        return self.client_config.router_mode

    @property
    def reasoning_mode(self) -> ReasoningMode:
        return self.client_config.reasoning_mode

    @property
    def reasoning_effort_format(self) -> EffortFormat:
        if self.reasoning_mode == "effort" and self.api_handles_prompt_template:
            return "reasoning_effort"
        return "none"

    @property
    def reasoning_budget_tokens(self) -> int | None:
        if self.reasoning_mode != "tokens":
            return None
        return self.validated_reason_tokens

    @property
    def server_url_is_current(self) -> bool:
        return self._server_url == (self.api_url or "").strip().rstrip("/")

    @property
    def model_name(self) -> str | None:
        if self.router_mode:
            return self.model
        if self.server_url_is_current and self._router_detected:
            return None
        return super().model_name

    async def detect_server_mode(self):
        url = self._base_url()
        if not self.server_url_is_current:
            self._router_detected = False
            self._available_models = None
        self._server_url = url
        self._server_role = "unknown"
        self._models_autoload = None
        try:
            async with httpx.AsyncClient(timeout=self.status_request_timeout) as http:
                response = await http.get(f"{url}/props", headers=self.request_headers)
            if response.status_code in (401, 403):
                response.raise_for_status()
            if response.status_code >= 400:
                return
            props = ServerProperties.model_validate(response.json())
        except (httpx.RequestError, ValueError):
            # An optional metadata failure must not undo a confirmed router.
            return
        self._router_detected = props.role == "router"
        if self._router_detected:
            self._server_role = "router"
            self._models_autoload = props.models_autoload

    async def get_model_name(self) -> str | None:
        self._probe_error = None
        try:
            await self.detect_server_mode()
            if not self.router_mode and not (
                self.server_url_is_current and self._router_detected
            ):
                self._available_models = None
                return await self.probe_model_name()
            async with httpx.AsyncClient(timeout=self.status_request_timeout) as http:
                response = await http.get(
                    f"{self._base_url()}/v1/models", headers=self.request_headers
                )
            response.raise_for_status()
            self._available_models = RouterModels.model_validate(response.json()).data
            return self.model if self.router_mode else None
        except (APIStatusError, httpx.HTTPStatusError) as exc:
            code = exc.response.status_code
            if code in (401, 403):
                self._probe_error = f"Invalid API key ({code})"
            raise

    @property
    def selected_router_model(self) -> RouterModel | None:
        if not self.server_url_is_current:
            return None
        return next(
            (
                model
                for model in self._available_models or []
                if self.model == model.id or self.model in model.aliases
            ),
            None,
        )

    def status_details(self) -> tuple[ClientStatusValue, str | None]:
        status, message = super().status_details()
        if not self.enabled:
            return status, message
        if not self.connected:
            return status, self._probe_error or message
        if self.processing:
            return status, message
        if not self.router_mode:
            if self.server_url_is_current and self._router_detected:
                return (
                    "warning",
                    "Router detected. Turn on Router mode to pick a model.",
                )
            return status, message
        if not self.model or not self.model.strip():
            return "warning", "Select a router model"
        model = self.selected_router_model
        if self._available_models is not None and model is None:
            return "warning", "Selected model is not available on this router"
        if model and model.status.value == "loading":
            return "busy", "Model is loading"
        if (
            model
            and model.status.value == "unloaded"
            and self._models_autoload is False
        ):
            return "warning", "Model is unloaded and server autoload is disabled"
        return status, message

    def finalize_status(self, data: dict):
        data = super().finalize_status(data)
        current = self.server_url_is_current
        data["configured_model"] = self.model
        data["router_mode"] = self.router_mode
        data["router_detected"] = current and self._router_detected
        data["server_role"] = self._server_role if current else "unknown"
        data["models_autoload"] = self._models_autoload if current else None
        data["manual_model_choices"] = (
            [m.id for m in self._available_models or []] if current else []
        )
        return data

    async def request_model(self) -> str | None:
        if not self.server_url_is_current:
            await self.detect_server_mode()
        if not self.router_mode:
            return None
        if not self.model or not self.model.strip():
            raise GenerationProcessingError("llama.cpp router: select a model first")
        return self.model

    def determine_prompt_template(self):
        if not self.router_mode:
            return super().determine_prompt_template()
        model = self.model_name
        if model and model not in self._prompt_template_tasks:
            self._prompt_template_tasks[model] = asyncio.create_task(
                self._determine_router_prompt_template(model, self.api_url)
            )

    async def _determine_router_prompt_template(self, model: str, api_url: str | None):
        try:
            template = await asyncio.to_thread(
                model_prompt.query_hf_for_prompt_template_suggestion, model
            )
            if (
                not template
                or not self.enabled
                or not self.router_mode
                or self.model_name != model
                or self.api_url != api_url
            ):
                if template and self.auto_determine_prompt_template_attempt == model:
                    self.auto_determine_prompt_template_attempt = None
                return
            _, current_template, _ = self.prompt_template_example()
            if not current_template or current_template == self.default_prompt_template:
                model_prompt.create_user_override(template, model)
            elif self.auto_determine_prompt_template_attempt == model:
                self.auto_determine_prompt_template_attempt = None
        except Exception:
            self.log.warning("router prompt template lookup failed", exc_info=True)
        finally:
            if self._prompt_template_tasks.get(model) is asyncio.current_task():
                self._prompt_template_tasks.pop(model)

    async def destroy(self):
        tasks = list(self._prompt_template_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._prompt_template_tasks.clear()
        await super().destroy()

    async def analyze_image(self, image_bytes: bytes, prompt: str) -> str:
        await self.request_model()
        return await super().analyze_image(image_bytes, prompt)

    class Meta(ClientBase.Meta):
        name_prefix: str = "llama.cpp"
        title: str = "llama.cpp"
        enable_api_auth: bool = True
        defaults: Defaults = Defaults()
        self_hosted: bool = True
        extra_fields: dict = pydantic.Field(
            default_factory=lambda: {
                **api_handles_prompt_template_extra_fields(
                    label="API handles prompt template",
                    description="The prompt template is rendered by llama.cpp using the model's built-in chat template, and the prompt template selection below is ignored. Response pre-filling keeps working. Turn this off for full control of the prompt template in Talemate; leave it on to trust that the template on the remote end is correct.",
                ),
                **vision_extra_fields(),
                **concurrent_inference_extra_fields(),
                **reasoning_extra_fields(),
            }
        )

    @property
    def supported_parameters(self):
        # Talemate inference params (see config.schema.InferenceParameters) that
        # we can map to llama.cpp request options.
        return [
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "presence_penalty",
            "frequency_penalty",
            "xtc_threshold",
            "xtc_probability",
            "dry_multiplier",
            "dry_base",
            "dry_allowed_length",
            "dry_sequence_breakers",
            "stop",
            "adaptive_target",
            "adaptive_decay",
            ParameterReroute(
                talemate_parameter="repetition_penalty",
                client_parameter="repeat_penalty",
            ),
            ParameterReroute(
                talemate_parameter="repetition_penalty_range",
                client_parameter="repeat_last_n",
            ),
            ParameterReroute(
                talemate_parameter="max_tokens", client_parameter="n_predict"
            ),
        ]

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)

        # Feed llama.cpp stop strings explicitly so generation halts early.
        # extra_stopping_strings is injected by Talemate (e.g. conversation agent).
        parameters["stop"] = self.build_stopping_strings(parameters)

        # We always stream in generate() (to track incremental tokens), so remove
        # any upstream stream flag to avoid confusion in debugging.
        if "stream" in parameters:
            parameters.pop("stream", None)

    @property
    def request_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _base_url(self) -> str:
        return self.require_api_url().rstrip("/")

    def make_client(self) -> AsyncOpenAI:
        # OpenAI SDK requires an api_key. llama.cpp may ignore auth; if the user
        # didn't configure a key, use a dummy value (same idea as LMStudioClient).
        api_key = self.api_key or "sk-1234"
        return AsyncOpenAI(base_url=self.require_api_url_v1(), api_key=api_key)

    def api_error_text(self, status_code: int | None, error) -> str:
        message = (
            error.get("message") or error.get("type")
            if isinstance(error, dict)
            else None
        )
        detail = "Invalid API key" if status_code in (401, 403) else "API error"
        code = f" ({status_code})" if isinstance(status_code, int) else ""
        return f"llama.cpp {detail}{code}" + (f" - {message}" if message else "")

    def raise_api_error(self, response: httpx.Response) -> NoReturn:
        try:
            data = response.json()
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        status_code = response.status_code
        text = self.api_error_text(status_code, error)
        if status_code == 404:
            request = response.request
            text += (
                f": {request.method} {request.url.path} was not found on the server."
            )
            if self._base_url().endswith("/v1"):
                text += (
                    " The API URL ends in /v1: remove it, this client adds its own"
                    " paths."
                )
            elif self.api_handles_prompt_template:
                text += (
                    " If the server has no chat endpoint, turn off API handles"
                    " prompt template."
                )
            else:
                text += (
                    " If the server does not implement it, use the OpenAI Compatible"
                    " client with API handles prompt template turned on and /v1 at the"
                    " end of its API URL."
                )
        raise GenerationProcessingError(text)

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Streams the response so token usage can be tracked incrementally via
        `update_request_tokens`.
        """

        model = await self.request_model()

        payload = {k: v for k, v in parameters.items() if v is not None}
        payload["stream"] = True
        if model is not None:
            payload["model"] = model

        if "dry_sequence_breakers" in payload:
            payload["dry_sequence_breakers"] = dry_sequence_breakers_list(
                payload["dry_sequence_breakers"]
            )

        if self.api_handles_prompt_template:
            return await self._generate_chat(prompt, payload, kind)
        return await self._generate_completion(prompt, payload)

    async def _stream_events(self, path: str, payload: dict):
        async with httpx.AsyncClient(timeout=None) as http:
            async with http.stream(
                "POST",
                f"{self._base_url()}{path}",
                json=payload,
                headers=self.request_headers,
            ) as r:
                if r.status_code >= 400:
                    # llama.cpp returns OAI-style errors (see tools/server/README.md).
                    await r.aread()
                    self.raise_api_error(r)
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if raw == "[DONE]":
                        continue
                    try:
                        evt = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(evt, dict) and evt.get("error"):
                        error = evt["error"]
                        code = error.get("code") if isinstance(error, dict) else None
                        raise GenerationProcessingError(
                            self.api_error_text(code, error)
                        )
                    yield evt

    async def _generate_completion(self, prompt: str, payload: dict) -> str:
        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=payload,
        )

        payload["prompt"] = prompt.strip(" ")

        response = ""
        async for evt in self._stream_events("/completion", payload):
            piece = evt.get("content")
            if piece:
                response += piece
                self.update_request_tokens(self.count_tokens(piece))

        self._returned_prompt_tokens = self.prompt_tokens(prompt)
        self._returned_response_tokens = self.response_tokens(response)

        return response

    async def _generate_chat(self, prompt: str, payload: dict, kind: str) -> str:
        self.log.debug(
            "generate (chat/completions)",
            prompt=prompt[:128] + " ...",
            parameters=payload,
        )

        messages, coercion_prompt = self.chat_messages_for_coercion(prompt, kind)
        payload["messages"] = messages
        effort = self.reasoning_effort
        # an explicit enable_thinking overrides reasoning_effort "none" on the server
        payload["chat_template_kwargs"] = {
            "enable_thinking": self.reason_enabled and effort != "none"
        }
        if self.reason_enabled:
            # overrides a server started with --reasoning-format none
            payload["reasoning_format"] = "deepseek"
            if effort not in (None, "none"):
                payload["reasoning_effort"] = effort
            if (budget := self.reasoning_budget_tokens) is not None:
                payload["reasoning_budget_tokens"] = budget

        response = ""
        reasoning = ""
        async for evt in self._stream_events("/v1/chat/completions", payload):
            try:
                chunk = ChatChunk.model_validate(evt)
            except pydantic.ValidationError:
                continue
            if not chunk.choices or not chunk.choices[0].delta:
                continue
            delta = chunk.choices[0].delta
            if delta.reasoning_text:
                reasoning += delta.reasoning_text
                self.update_request_tokens(self.count_tokens(delta.reasoning_text))
            if delta.content:
                response += delta.content
                self.update_request_tokens(self.count_tokens(delta.content))

        if reasoning:
            self._reasoning_response = reasoning

        self._returned_prompt_tokens = self.prompt_tokens(prompt)
        self._returned_response_tokens = self.response_tokens(response)

        return strip_echoed_prefill(response, coercion_prompt)

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def response_tokens(self, response: str):
        return self.count_tokens(response)

    def prompt_tokens(self, prompt: str):
        return self.count_tokens(prompt)
