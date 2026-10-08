import asyncio
import json
from typing import Literal, NoReturn

import pydantic
import httpx
from openai import APIStatusError, AsyncOpenAI

from talemate.client.api_handles import (
    ApiHandlesPromptTemplateConfig,
    ApiHandlesPromptTemplateMixin,
    api_handles_prompt_template_extra_fields,
)
from talemate.client.base import (
    ClientBase,
    ClientStatusValue,
    CommonDefaults,
    ParameterReroute,
)
from talemate.client.model_probe import OpenAIModelListProbeMixin
from talemate.client.model_prompts import model_prompt
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

APPLY_TEMPLATE_TIMEOUT = 30


class Defaults(CommonDefaults, ApiHandlesPromptTemplateConfig):
    # llama.cpp `llama-server` defaults to port 8080 (see ggml-org/llama.cpp README)
    api_url: str = "http://localhost:8080"
    max_token_length: int = 16384


class ClientConfig(
    ConcurrentInference, ApiHandlesPromptTemplateConfig, VisionConfig, BaseClientConfig
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


@register()
class LlamaCppClient(
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

    (The server also offers OpenAI-compatible endpoints under /v1, which we
    still use for model discovery via /v1/models.)
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
                    description="The prompt template is rendered by llama.cpp using the model's built-in chat template, and the prompt template selection below is ignored. Response pre-filling keeps working. Keep this disabled for full control of the prompt template in Talemate; enable it to trust that the template on the remote end is correct.",
                ),
                **vision_extra_fields(),
                **concurrent_inference_extra_fields(),
            }
        )

    @property
    def supported_parameters(self):
        # Talemate inference params (see config.schema.InferenceParameters) that
        # we can map to llama.cpp /completion options.
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

    async def apply_remote_template(
        self, prompt: str, kind: str, model: str | None
    ) -> str:
        """
        Renders the prompt through llama.cpp's POST /apply-template endpoint,
        which applies the model's built-in chat template server-side and
        leaves the final assistant turn open when a prefill (coercion)
        message is included.
        """

        messages, _ = self.chat_messages_for_coercion(prompt, kind)

        payload = {"messages": messages}
        if model is not None:
            payload["model"] = model
        if not self.reason_enabled:
            # best-effort: ask thinking-capable templates (Qwen, GLM, ...)
            # not to open a think block when reasoning is disabled
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        # A routed request can cold-load a model before rendering its template.
        timeout = None if model is not None else APPLY_TEMPLATE_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as http:
            response = await http.post(
                f"{self._base_url()}/apply-template",
                json=payload,
                headers=self.request_headers,
            )
            if response.status_code >= 400:
                self.raise_api_error(response)
            return response.json()["prompt"]

    def raise_api_error(self, response: httpx.Response) -> NoReturn:
        try:
            data = response.json()
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        message = (
            error.get("message") or error.get("type")
            if isinstance(error, dict)
            else None
        )
        status_code = response.status_code
        detail = "Invalid API key" if status_code in (401, 403) else "API error"
        raise GenerationProcessingError(
            f"llama.cpp {detail} ({status_code})" + (f" - {message}" if message else "")
        )

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generate text using llama.cpp's POST /completion endpoint in streaming
        mode so token usage can be tracked incrementally via
        `update_request_tokens`.
        """

        model = await self.request_model()
        if self.api_handles_prompt_template:
            prompt = await self.apply_remote_template(prompt, kind, model)

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
        )

        # Map Talemate settings into llama.cpp /completion payload.
        # The prompt already includes any prompt templating done by Talemate.
        payload = {k: v for k, v in parameters.items() if v is not None}
        payload["prompt"] = prompt.strip(" ")
        payload["stream"] = True
        if model is not None:
            payload["model"] = model

        if "dry_sequence_breakers" in payload:
            payload["dry_sequence_breakers"] = dry_sequence_breakers_list(
                payload["dry_sequence_breakers"]
            )

        try:
            response = ""
            url = f"{self._base_url()}/completion"

            async with httpx.AsyncClient(timeout=None) as http:
                async with http.stream(
                    "POST",
                    url,
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
                            break
                        try:
                            evt = json.loads(raw)
                        except Exception:
                            continue

                        piece = evt.get("content")
                        if piece:
                            response += piece
                            self.update_request_tokens(self.count_tokens(piece))

                        if evt.get("stop") is True:
                            # Don't break immediately; let the server finish the SSE stream
                            # cleanly (avoids noisy generator-close warnings in some runtimes).
                            continue

                    # If we saw a stop event but didn't receive [DONE], the server will still
                    # close the response; exiting the context will clean up the connection.

            # Store overall token accounting once the stream is finished
            self._returned_prompt_tokens = self.prompt_tokens(prompt)
            self._returned_response_tokens = self.response_tokens(response)

            return response
        except GenerationProcessingError:
            raise

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def response_tokens(self, response: str):
        return self.count_tokens(response)

    def prompt_tokens(self, prompt: str):
        return self.count_tokens(prompt)
