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
import structlog

import talemate.util as util
from talemate.client.base import (
    ClientBase,
    Defaults,
    ParameterReroute,
    ClientEmbeddingsStatus,
)
from talemate.client.registry import register
import talemate.emit.async_signals as async_signals


if TYPE_CHECKING:
    from talemate.agents.visual import VisualBase

log = structlog.get_logger("talemate.client.koboldcpp")


class KoboldCppClientDefaults(Defaults):
    api_url: str = "http://localhost:5001"
    api_key: str = ""


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
class KoboldCppClient(ClientBase):
    auto_determine_prompt_template: bool = True
    client_type = "koboldcpp"
    remote_model_locked: bool = True

    class Meta(ClientBase.Meta):
        name_prefix: str = "KoboldCpp"
        title: str = "KoboldCpp"
        enable_api_auth: bool = True
        defaults: KoboldCppClientDefaults = KoboldCppClientDefaults()
        self_hosted: bool = True

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
        if not self.api_url:
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

        if not self.api_url:
            return None

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
            try:
                if self.is_openai:
                    response_text = response_data["choices"][0]["text"]
                else:
                    response_text = response_data["results"][0]["text"]
            except (TypeError, KeyError) as exc:
                log.error(
                    "Failed to generate text",
                    exc=exc,
                    response_data=response_data,
                    response_status=response.status_code,
                )
                response_text = ""

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
