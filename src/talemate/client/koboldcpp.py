import random
import json
import sseclient
import asyncio
from typing import TYPE_CHECKING
import requests
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

# import urljoin
from urllib.parse import urljoin, urlparse

import httpx
import pydantic
import structlog
from openai import AsyncOpenAI

import talemate.util as util
from talemate.client.base import (
    ClientBase,
    Defaults,
    ParameterReroute,
    ClientEmbeddingsStatus,
)
from talemate.client.registry import register
from talemate.client.vision import VisionConfig, vision_extra_fields, OpenAIVisionMixin
from talemate.config.schema import Client as BaseClientConfig
import talemate.emit.async_signals as async_signals


if TYPE_CHECKING:
    from talemate.agents.visual import VisualBase
    from talemate.agents.tts import TTSAgent

log = structlog.get_logger("talemate.client.koboldcpp")

# koboldcpp's documented stop sequence limit since v1.45.2; older builds
# cap lower, newer versions allow more.
MAX_STOPPING_STRINGS = 16


class KoboldCppClientDefaults(Defaults):
    api_url: str = "http://localhost:5001"
    api_key: str = ""


class ClientConfig(VisionConfig, BaseClientConfig):
    pass


class KoboldEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_url: str, model_name: str = None):
        """
        Initialize the embedding function with the KoboldCPP API endpoint.
        """
        self.api_url = api_url
        self.model_name = model_name

    def __call__(self, texts: Documents) -> Embeddings:
        """
        Embed a list of input texts using the KoboldCPP embeddings endpoint.
        """

        log.debug(
            "KoboldCppEmbeddingFunction",
            api_url=self.api_url,
            model_name=self.model_name,
        )

        # Prepare the request payload for KoboldCPP. Include model name if required.
        payload = {"input": texts}
        if self.model_name is not None:
            payload["model"] = self.model_name  # e.g. the model's name/ID if needed

        # Send POST request to the local KoboldCPP embeddings endpoint
        response = requests.post(self.api_url, json=payload)
        response.raise_for_status()  # Throw an error if the request failed (e.g., connection issue)

        # Parse the JSON response to extract embedding vectors
        data = response.json()
        # The 'data' field contains a list of embeddings (one per input)
        embedding_results = data.get("data", [])
        embeddings = [item["embedding"] for item in embedding_results]

        return embeddings


@register()
class KoboldCppClient(OpenAIVisionMixin, ClientBase):
    auto_determine_prompt_template: bool = True
    client_type = "koboldcpp"
    remote_model_locked: bool = True
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "KoboldCpp"
        title: str = "KoboldCpp"
        enable_api_auth: bool = True
        defaults: KoboldCppClientDefaults = KoboldCppClientDefaults()
        self_hosted: bool = True
        extra_fields: dict = pydantic.Field(
            default_factory=lambda: vision_extra_fields()
        )

    def make_client(self) -> AsyncOpenAI:
        """Return an AsyncOpenAI client for the /v1 endpoint.

        KoboldCpp always serves an OpenAI-compatible API at /v1 regardless
        of which API mode is used for text generation.
        """
        self.require_api_url()
        api_key = self.api_key or "sk-1234"
        return AsyncOpenAI(base_url=f"{self.url}/v1", api_key=api_key)

    @property
    def request_headers(self):
        headers = {}
        headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def url(self) -> str:
        parts = urlparse(self.api_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def is_openai(self) -> bool:
        """
        kcpp has two apis

        open-ai implementation at /v1
        their own implementation at /api/v1
        """
        return "/api/v1" not in self.api_url

    @property
    def api_url_for_model(self) -> str:
        if self.is_openai:
            # join /model to url
            return urljoin(self.api_url, "models")
        else:
            # join /models to url
            return urljoin(self.api_url, "model")

    @property
    def api_url_for_generation(self) -> str:
        if self.is_openai:
            # join /v1/completions
            return urljoin(self.api_url, "completions")
        else:
            # join /api/extra/generate/stream
            return urljoin(self.api_url.replace("v1", "extra"), "generate/stream")

    @property
    def max_tokens_param_name(self):
        if self.is_openai:
            return "max_tokens"
        else:
            return "max_length"

    @property
    def supported_parameters(self):
        if not self.is_openai:
            # koboldcpp united api

            return [
                ParameterReroute(
                    talemate_parameter="max_tokens", client_parameter="max_length"
                ),
                "max_context_length",
                ParameterReroute(
                    talemate_parameter="repetition_penalty", client_parameter="rep_pen"
                ),
                ParameterReroute(
                    talemate_parameter="repetition_penalty_range",
                    client_parameter="rep_pen_range",
                ),
                "top_p",
                "top_k",
                ParameterReroute(
                    talemate_parameter="stopping_strings",
                    client_parameter="stop_sequence",
                ),
                "xtc_threshold",
                "xtc_probability",
                "dry_multiplier",
                "dry_base",
                "dry_allowed_length",
                "dry_sequence_breakers",
                "smoothing_factor",
                "temperature",
                "adaptive_target",
                "adaptive_decay",
                "min_p",
                "frequency_penalty",
                "presence_penalty",
            ]

        else:
            # openai api

            return [
                "max_tokens",
                "presence_penalty",
                "top_p",
                "temperature",
            ]

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)

        if self.is_openai:
            # openai mode's supported parameters carry no stopping_strings
            # reroute, so a built list would be dropped at clean - whether
            # that mode should gain native stop is a separate scope decision
            return

        parameters["stopping_strings"] = self.build_stopping_strings(
            parameters, cap=MAX_STOPPING_STRINGS
        )

    @property
    def supports_embeddings(self) -> bool:
        return True

    @property
    def embeddings_url(self) -> str:
        if self.is_openai:
            return urljoin(self.api_url, "embeddings")
        else:
            return urljoin(self.api_url, "api/extra/embeddings")

    @property
    def embeddings_function(self):
        return KoboldEmbeddingFunction(self.embeddings_url, self.embeddings_model_name)

    @property
    def default_prompt_template(self) -> str:
        return "KoboldAI.jinja2"

    @property
    def api_url(self) -> str:
        return self.client_config.api_url

    @api_url.setter
    def api_url(self, value: str):
        self.client_config.api_url = value

    def api_endpoint_specified(self, url: str) -> bool:
        return "/v1" in self.api_url

    def ensure_api_endpoint_specified(self):
        if not (self.api_url or "").strip():
            return

        if not self.api_endpoint_specified(self.api_url):
            # url doesn't specify the api endpoint
            # use the koboldcpp united api
            self.api_url = urljoin(self.api_url.rstrip("/") + "/", "/api/v1/")
        if not self.api_url.endswith("/"):
            self.api_url += "/"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ensure_api_endpoint_specified()
        self._visual_setup_task: asyncio.Task | None = None
        self._visual_setup_lock: asyncio.Lock = asyncio.Lock()
        self._tts_setup_task: asyncio.Task | None = None
        self._tts_setup_lock: asyncio.Lock = asyncio.Lock()

    async def get_embeddings_model_name(self):
        # if self._embeddings_model_name is set, return it
        if self.embeddings_model_name:
            return self.embeddings_model_name

        # otherwise, get the model name by doing a request to
        # the embeddings endpoint with a single character

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.embeddings_url,
                json={"input": ["test"]},
                timeout=2,
                headers=self.request_headers,
            )

        response_data = response.json()
        self._embeddings_model_name = response_data.get("model")
        return self._embeddings_model_name

    async def get_embeddings_status(self):
        url_version = urljoin(self.api_url, "api/extra/version")
        async with httpx.AsyncClient() as client:
            response = await client.get(url_version, timeout=2)
            response_data = response.json()
            self._embeddings_status = response_data.get("embeddings", False)

            if not self.embeddings_status or self.embeddings_model_name:
                return

            await self.get_embeddings_model_name()

            log.debug(
                "KoboldCpp embeddings are enabled, suggesting embeddings",
                model_name=self.embeddings_model_name,
            )

            await self.set_embeddings()

            emission = ClientEmbeddingsStatus(
                client=self,
                embedding_name=self.embeddings_model_name,
            )

            await async_signals.get("client.embeddings_available").send(emission)

            if not emission.seen:
                # the suggestion has not been seen by the memory agent
                # yet, so we unset the embeddings model name so it will
                # get suggested again
                self._embeddings_model_name = None

    async def get_model_name(self):
        self.ensure_api_endpoint_specified()
        self.require_api_url()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.api_url_for_model,
                    timeout=2,
                    headers=self.request_headers,
                )
        except Exception:
            self._embeddings_model_name = None
            raise

        if response.status_code == 404:
            raise KeyError(f"Could not find model info at: {self.api_url_for_model}")

        response_data = response.json()
        if self.is_openai:
            # {"object": "list", "data": [{"id": "koboldcpp/dolphin-2.8-mistral-7b", "object": "model", "created": 1, "owned_by": "koboldcpp", "permission": [], "root": "koboldcpp"}]}
            model_name = response_data.get("data")[0].get("id")
        else:
            # {"result": "koboldcpp/dolphin-2.8-mistral-7b"}
            model_name = response_data.get("result")

        # split by "/" and take last
        if model_name:
            model_name = model_name.split("/")[-1]

        await self.get_embeddings_status()

        return model_name

    async def tokencount(self, content: str) -> int:
        """
        KoboldCpp has a tokencount endpoint we can use to count tokens
        for the prompt and response

        If the endpoint is not available, we will use the default token count estimate
        """

        # extract scheme and host from api url

        parts = urlparse(self.api_url)

        url_tokencount = f"{parts.scheme}://{parts.netloc}/api/extra/tokencount"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url_tokencount,
                json={"prompt": content},
                timeout=None,
                headers=self.request_headers,
            )

            if response.status_code == 404:
                # kobold united doesn't have tokencount endpoint
                return util.count_tokens(content)

            tokencount = len(response.json().get("ids", []))
            return tokencount

    async def abort_generation(self):
        """
        Trigger the stop generation endpoint
        """
        if self.is_openai:
            # openai api endpoint doesn't support abort
            return

        parts = urlparse(self.api_url)
        url_abort = f"{parts.scheme}://{parts.netloc}/api/extra/abort"
        async with httpx.AsyncClient() as client:
            await client.post(
                url_abort,
                headers=self.request_headers,
            )

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """
        if self.is_openai:
            return await self._generate_openai(prompt, parameters, kind)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._generate_kcpp_stream, prompt, parameters, kind
            )

    def _generate_kcpp_stream(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """
        parameters["prompt"] = prompt.strip(" ")

        response = ""
        parameters["stream"] = True
        stream_response = requests.post(
            self.api_url_for_generation,
            json=parameters,
            timeout=None,
            headers=self.request_headers,
            stream=True,
        )
        stream_response.raise_for_status()

        sse = sseclient.SSEClient(stream_response)

        for event in sse.events():
            if event.data == "[DONE]":
                break
            payload = json.loads(event.data)
            chunk = payload["token"]
            response += chunk
            self.update_request_tokens(self.count_tokens(chunk))

        return response

    async def _generate_openai(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        parameters["prompt"] = prompt.strip(" ")

        self._returned_prompt_tokens = await self.tokencount(parameters["prompt"])

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.api_url_for_generation,
                json=parameters,
                timeout=None,
                headers=self.request_headers,
            )
            response_data = response.json()
            if self.is_openai:
                response_text = response_data["choices"][0]["text"]
            else:
                response_text = response_data["results"][0]["text"]

            self._returned_response_tokens = await self.tokencount(response_text)
            return response_text

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        adjusts temperature and repetition_penalty
        by random values using the base value as a center
        """

        temp = prompt_config["temperature"]

        if "rep_pen" in prompt_config:
            rep_pen_key = "rep_pen"
        elif "presence_penalty" in prompt_config:
            rep_pen_key = "presence_penalty"
        else:
            rep_pen_key = "repetition_penalty"

        min_offset = offset * 0.3

        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
        try:
            if rep_pen_key == "presence_penalty":
                presence_penalty = prompt_config["presence_penalty"]
                prompt_config["presence_penalty"] = round(
                    random.uniform(presence_penalty + 0.1, presence_penalty + offset), 1
                )
            else:
                rep_pen = prompt_config[rep_pen_key]
                prompt_config[rep_pen_key] = random.uniform(
                    rep_pen + min_offset * 0.3, rep_pen + offset * 0.3
                )
        except KeyError:
            pass

    async def visual_automatic1111_setup(self, visual_agent: "VisualBase") -> bool:
        """
        Automatically configure the visual agent for automatic1111
        if the koboldcpp server has a SD model available and no backend is currently configured.

        Uses an asyncio task to ensure only one setup check runs at a time.
        """

        # Ensure only one setup check runs at a time
        async with self._visual_setup_lock:
            # If a task is already running, wait for it to complete and return its result
            if self._visual_setup_task and not self._visual_setup_task.done():
                try:
                    return await self._visual_setup_task
                except Exception as exc:
                    log.error("Visual setup task failed", exc=exc)
                    # Task failed, will create a new one below
                    self._visual_setup_task = None

            # Create and start a new setup task
            self._visual_setup_task = asyncio.create_task(
                self._visual_automatic1111_setup_impl(visual_agent)
            )

            # Wait for the task to complete and return its result
            try:
                return await self._visual_setup_task
            except Exception as exc:
                log.error("Visual setup task failed", exc=exc)
                return False

    async def _visual_automatic1111_setup_impl(
        self, visual_agent: "VisualBase"
    ) -> bool:
        """
        Internal implementation of the automatic1111 setup check.
        This runs in a separate task to avoid blocking.
        """
        if not self.connected:
            return False

        # Check if the koboldcpp automatic1111 backend is already configured
        if visual_agent.backend:
            try:
                backend_api_url = visual_agent.backend.api_url
            except AttributeError:
                return False

            backend_name = visual_agent.backend.name
            if backend_api_url == self.url and backend_name == "automatic1111":
                return False

        # Check if the koboldcpp server has a SD model available
        sd_models_url = urljoin(self.url, "/sdapi/v1/sd-models")
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url=sd_models_url, timeout=2)
            except Exception as exc:
                log.error(f"Failed to fetch sd models from {sd_models_url}", exc=exc)
                return False

            if response.status_code != 200:
                return False

            response_data = response.json()

            sd_model = response_data[0].get("model_name") if response_data else None

        # no SD model available, no setup needed
        if not sd_model:
            return False

        log.info("KoboldCpp AUTOMATIC1111 setup", sd_model=sd_model)

        # Set the backend to automatic1111 and configure its API URL
        visual_agent.actions["_config"].config["backend"].value = "automatic1111"
        visual_agent.actions["automatic1111_image_create"].config[
            "api_url"
        ].value = self.url
        return True

    async def tts_openai_compatible_setup(self, tts_agent: "TTSAgent") -> bool:
        """Auto-register a TTS backend pointing at this KoboldCpp instance
        if it currently has a TTS model loaded.

        Mirrors the visual auto-setup pattern: serialized via a lock,
        idempotent (skips if a backend already targets this URL), and a
        no-op when KoboldCpp has no TTS model loaded (the voice list is
        empty). On first successful setup it also auto-refreshes the
        backend's voices so the user opens a populated library.
        """
        async with self._tts_setup_lock:
            if self._tts_setup_task and not self._tts_setup_task.done():
                try:
                    return await self._tts_setup_task
                except Exception as exc:
                    log.error("TTS setup task failed", exc=exc)
                    self._tts_setup_task = None

            self._tts_setup_task = asyncio.create_task(
                self._tts_openai_compatible_setup_impl(tts_agent)
            )
            try:
                return await self._tts_setup_task
            except Exception as exc:
                log.error("TTS setup task failed", exc=exc)
                return False

    async def _tts_openai_compatible_setup_impl(self, tts_agent: "TTSAgent") -> bool:
        """Internal: keep the TTS agent's enabled-apis state in sync with
        what this KoboldCpp instance currently has loaded.

        Three kinds of state changes can happen here:

          * **First-time register** — kobold has TTS loaded and we don't yet
            track it: add a backend, enable it in apis, refresh voices.
          * **Re-enable** — backend already exists (matched by api_url) but
            isn't in apis.value; kobold reports voices: add it back.
          * **Auto-disable** — backend exists and is in apis.value; kobold is
            up and definitively reports no voices (e.g. restarted without a
            TTS model): drop the slug from apis.value, keep the backend so
            the user's saved config (key, model overrides, etc.) survives.

        Connectivity failures are *uncertain* — they don't trigger a state
        change in either direction, so a brief network blip can't toggle
        the user's setup off.
        """
        # Lazy imports to avoid circular dependencies at module load time.
        from talemate.agents.tts.openai_compatible import (
            REGISTRY_KEY as OPENAI_COMPAT_REGISTRY_KEY,
        )
        from talemate.util import slugify

        if not self.connected:
            return False

        target_url = f"{self.url}/v1"

        # Find any existing backend tracking this kobold (matched by api_url).
        existing_slug: str | None = None
        for slug in tts_agent.dynamic_child_slugs(OPENAI_COMPAT_REGISTRY_KEY):
            action = tts_agent.actions.get(slug)
            if action and action.config["api_url"].value == target_url:
                existing_slug = slug
                break

        # Tristate probe: True (voices loaded), False (definitively no voices),
        # None (couldn't tell — leave state alone).
        voices_loaded = await self._probe_kcpp_tts_loaded()
        if voices_loaded is None:
            return False

        apis_value = list(tts_agent.actions["_config"].config["apis"].value or [])

        if voices_loaded:
            if existing_slug is None:
                # First-time register.
                base_slug = slugify(self.name) or "kobold-tts"
                reserved = tts_agent.reserved_slugs_for_registry(
                    OPENAI_COMPAT_REGISTRY_KEY
                )
                taken = set(tts_agent.dynamic_child_slugs(OPENAI_COMPAT_REGISTRY_KEY))
                slug, n = base_slug, 2
                while slug in taken or slug in reserved:
                    slug = f"{base_slug}-{n}"
                    n += 1

                log.info(
                    "KoboldCpp TTS auto-setup",
                    client=self.name,
                    slug=slug,
                    url=target_url,
                )
                tts_agent.register_dynamic_child(
                    OPENAI_COMPAT_REGISTRY_KEY, slug, self.name
                )
                tts_agent.actions[slug].config["api_url"].value = target_url
                if slug not in apis_value:
                    apis_value.append(slug)
                    tts_agent.actions["_config"].config["apis"].value = apis_value
                # Best-effort voice refresh; failure doesn't undo setup.
                # Bounded so a hung server can't pin the periodic status
                # loop that calls into setup_check.
                try:
                    await asyncio.wait_for(
                        tts_agent.refresh_backend_voices(slug), timeout=15
                    )
                except Exception as exc:
                    log.warning(
                        "Voice refresh after TTS auto-setup failed",
                        client=self.name,
                        slug=slug,
                        error=str(exc),
                    )
                return True

            # Backend already tracking this kobold — re-enable if disabled.
            if existing_slug not in apis_value:
                log.info(
                    "KoboldCpp TTS auto-enable",
                    client=self.name,
                    slug=existing_slug,
                )
                apis_value.append(existing_slug)
                tts_agent.actions["_config"].config["apis"].value = apis_value
                return True

            # Already tracking and enabled. If two distinct clients ever end
            # up with the same configured URL, the first to register owns
            # the backend
            return False

        # voices_loaded is False (definitive: kobold up, no TTS model). Auto-
        # disable the matching backend if we have one, but keep its config.
        if existing_slug is None:
            return False
        if existing_slug in apis_value:
            log.info(
                "KoboldCpp TTS auto-disable",
                client=self.name,
                slug=existing_slug,
            )
            apis_value.remove(existing_slug)
            tts_agent.actions["_config"].config["apis"].value = apis_value
            return True
        return False

    async def _probe_kcpp_tts_loaded(self) -> bool | None:
        """Probe KoboldCpp's capabilities endpoint to determine TTS state.

        Uses ``GET /api/extra/version`` and reads the ``tts`` flag — the
        only reliable signal for whether a TTS model is currently loaded.
        ``/v1/audio/voices`` is *not* usable here: it always returns the
        hardcoded default voice list (``kobo``, ``cheery``, etc.) even when
        no TTS model is loaded, so a non-empty response there does not
        prove TTS is available.

        Returns:
            * ``True`` — capabilities report ``tts: true``.
            * ``False`` — capabilities report ``tts: false`` (definitive
              answer; backend should be auto-disabled).
            * ``None`` — probe was inconclusive (network error, non-JSON
              body, missing field, unexpected status, older kobold build
              without the endpoint). State is left alone.
        """
        version_url = urljoin(self.url, "/api/extra/version")
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url=version_url, timeout=2)
            except Exception as exc:
                log.debug(
                    "KoboldCpp TTS probe failed",
                    url=version_url,
                    error=str(exc),
                )
                return None

        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict) or "tts" not in payload:
            return None
        # Strict: only a real boolean answers the probe. Anything else
        # (string "true", number, None) is treated as inconclusive so a
        # weird payload can't accidentally flip backend state.
        flag = payload["tts"]
        if flag is True:
            return True
        if flag is False:
            return False
        return None
