import random
import re

# import urljoin
from urllib.parse import urljoin
import httpx
import structlog

from talemate.client.base import STOPPING_STRINGS, ClientBase, Defaults, ExtraField
from talemate.client.registry import register

log = structlog.get_logger("talemate.client.koboldcpp")


class KoboldCppClientDefaults(Defaults):
    api_key: str = ""


@register()
class KoboldCppClient(ClientBase):
    auto_determine_prompt_template: bool = True
    client_type = "koboldcpp"

    class Meta(ClientBase.Meta):
        name_prefix: str = "KoboldCpp"
        title: str = "KoboldCpp"
        enable_api_auth: bool = True
        defaults: KoboldCppClientDefaults = KoboldCppClientDefaults()

    @property
    def request_headers(self):
        headers = {}
        headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def is_openai(self) -> bool:
        """
        kcpp has two apis

        open-ai implementation at /v1
        their own implenation at /api/v1
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
            # join /api/v1/generate
            return urljoin(self.api_url, "generate")

    def api_endpoint_specified(self, url: str) -> bool:
        return "/v1" in self.api_url

    def ensure_api_endpoint_specified(self):
        if not self.api_endpoint_specified(self.api_url):
            # url doesn't specify the api endpoint
            # use the koboldcpp openai api
            self.api_url = urljoin(self.api_url.rstrip("/") + "/", "/api/v1/")
        if not self.api_url.endswith("/"):
            self.api_url += "/"

    def __init__(self, **kwargs):
        self.api_key = kwargs.pop("api_key", "")
        super().__init__(**kwargs)
        self.ensure_api_endpoint_specified()

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)
        log.debug("PARAMS", parameters=parameters)
        if not self.is_openai:
            # adjustments for united api
            parameters["max_length"] = parameters.pop("max_tokens")
            parameters["max_context_length"] = self.max_token_length
            if "repetition_penalty_range" in parameters:
                parameters["rep_pen_range"] = parameters.pop("repetition_penalty_range")
            if "repetition_penalty" in parameters:
                parameters["rep_pen"] = parameters.pop("repetition_penalty")
            if parameters.get("stop_sequence"):
                parameters["stop_sequence"] = parameters.pop("stopping_strings")
                
            if parameters.get("extra_stopping_strings"):
                if "stop_sequence" in parameters:
                    parameters["stop_sequence"] += parameters.pop("extra_stopping_strings")
                else:
                    parameters["stop_sequence"] = parameters.pop("extra_stopping_strings")
                
                
            allowed_params = [
                "max_length",
                "max_context_length",
                "rep_pen",
                "rep_pen_range",
                "top_p",
                "top_k",
                "temperature",
                "stop_sequence",
            ]
        else:
            # adjustments for openai api
            if "repetition_penalty" in parameters:
                parameters["presence_penalty"] = parameters.pop(
                    "repetition_penalty"
                )

            allowed_params = ["max_tokens", "presence_penalty", "top_p", "temperature"]

        # drop unsupported params
        for param in list(parameters.keys()):
            if param not in allowed_params:
                del parameters[param]

    def set_client(self, **kwargs):
        self.api_key = kwargs.get("api_key", self.api_key)
        self.ensure_api_endpoint_specified()

    async def get_model_name(self):
        self.ensure_api_endpoint_specified()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.api_url_for_model,
                timeout=2,
                headers=self.request_headers,
            )

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

        return model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        parameters["prompt"] = prompt.strip(" ")
        
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
                    return response_data["choices"][0]["text"]
                else:
                    return response_data["results"][0]["text"]
            except (TypeError, KeyError) as exc:
                log.error("Failed to generate text", exc=exc, response_data=response_data, response_status=response.status_code)
                return ""

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        adjusts temperature and repetition_penalty
        by random values using the base value as a center
        """

        temp = prompt_config["temperature"]
        rep_pen = prompt_config["rep_pen"]

        min_offset = offset * 0.3

        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
        prompt_config["rep_pen"] = random.uniform(
            rep_pen + min_offset * 0.3, rep_pen + offset * 0.3
        )

    def reconfigure(self, **kwargs):
        if "api_key" in kwargs:
            self.api_key = kwargs.pop("api_key")

        super().reconfigure(**kwargs)
