import structlog
import time
import httpx

from talemate.client.openai_compat import (
    OpenAICompatibleClient as BaseOpenAICompatClient,
    ClientConfig as OpenAICompatClientConfig,
    Defaults as OpenAICompatDefaults,
)
from talemate.client.registry import register

log = structlog.get_logger("talemate.client.arliai")

FETCH_MODELS_INTERVAL = 15


@register()
class ArliAIClient(BaseOpenAICompatClient):
    client_type = "arliai"
    conversation_retries = 0
    config_cls = OpenAICompatClientConfig

    class Meta(BaseOpenAICompatClient.Meta):
        title: str = "Arli AI"
        name_prefix: str = "Arli AI"
        enable_api_auth: bool = True
        manual_model: bool = True
        defaults: OpenAICompatDefaults = OpenAICompatDefaults(
            api_url="https://api.arliai.com/v1",
            api_key="",
            max_token_length=8192,
            model="",
            api_handles_prompt_template=True,
        )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._available_models: list[str] = []
        self._models_last_fetched: float = 0

    @property
    def request_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def fetch_available_models(self) -> list[str]:
        if time.time() - self._models_last_fetched < FETCH_MODELS_INTERVAL:
            return self._available_models

        url = f"{self.api_url.rstrip('/')}/models/textgen-models"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=2, headers=self.request_headers)
            response.raise_for_status()

        data = response.json()

        model_names: list[str] = []
        try:
            items = data.get("data", []) if isinstance(data, dict) else data
            for item in items:
                if isinstance(item, dict):
                    model_id = item.get("id") or item.get("name") or item.get("model")
                    if isinstance(model_id, str):
                        model_names.append(model_id)
                elif isinstance(item, str):
                    model_names.append(item)
        except Exception:
            log.warning("unexpected models response format", data=data)

        self._available_models = sorted(set(model_names))
        self._models_last_fetched = time.time()
        return self._available_models

    async def status(self):
        if self.processing:
            self.emit_status()
            return

        if not self.enabled:
            self.connected = False
            self.emit_status()
            return

        try:
            await self.fetch_available_models()
            self.connected = True
        except Exception as e:
            log.error("Failed to fetch models from Arli AI", error=str(e))
            self.connected = False
            self.emit_status()
            return

        await super().status()

    def finalize_status(self, data: dict):
        data = super().finalize_status(data)
        data["manual_model_choices"] = self._available_models
        return data

    async def get_model_name(self):
        return self.model

    async def visual_arliai_image_setup(self, agent):
        try:
            agent.actions["_config"].config["backend"].value = "arliai_image"
            api_url = self.api_url or "https://api.arliai.com/v1"
            if api_url.endswith("/v1"):
                api_url = api_url[: -len("/v1")]
            agent.actions["arliai_image"].config["api_url"].value = api_url
            agent.actions["arliai_image"].config["api_key"].value = self.api_key or ""
        except Exception as e:
            log.warning("visual_arliai_image_setup", e=e)

    async def generate(self, prompt: str, parameters: dict, kind: str):
        params = dict(parameters or {})
        if "max_tokens" in params and "max_completion_tokens" not in params:
            params["max_completion_tokens"] = params.pop("max_tokens")
        return await super().generate(prompt, params, kind)
