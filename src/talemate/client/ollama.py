import structlog
import httpx
import ollama
import time

from talemate.client.base import (
    STOPPING_STRINGS,
    ClientBase,
    CommonDefaults,
    ErrorAction,
    ParameterReroute,
    ExtraField,
)
from talemate.client.registry import register
from talemate.config.schema import Client as BaseClientConfig

log = structlog.get_logger("talemate.client.ollama")


FETCH_MODELS_INTERVAL = 15


class OllamaClientDefaults(CommonDefaults):
    api_url: str = "http://localhost:11434"  # Default Ollama URL
    model: str = ""  # Allow empty default, will fetch from Ollama
    api_handles_prompt_template: bool = False


class ClientConfig(BaseClientConfig):
    api_handles_prompt_template: bool = False


@register()
class OllamaClient(ClientBase):
    """
    Ollama client for generating text using locally hosted models.
    """

    auto_determine_prompt_template: bool = True
    client_type = "ollama"
    conversation_retries = 0
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "Ollama"
        title: str = "Ollama"
        enable_api_auth: bool = False
        manual_model: bool = True
        manual_model_choices: list[str] = []  # Will be overridden by finalize_status
        defaults: OllamaClientDefaults = OllamaClientDefaults()
        self_hosted: bool = True
        extra_fields: dict[str, ExtraField] = {
            "api_handles_prompt_template": ExtraField(
                name="api_handles_prompt_template",
                type="bool",
                label="API handles prompt template",
                required=False,
                description="Let Ollama handle the prompt template. Only do this if you don't know which prompt template to use. Letting talemate handle the prompt template will generally lead to improved responses.",
            ),
        }

    @property
    def supported_parameters(self):
        # Parameters supported by Ollama's generate endpoint
        # Based on the API documentation
        return [
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "frequency_penalty",
            "presence_penalty",
            ParameterReroute(
                talemate_parameter="repetition_penalty",
                client_parameter="repeat_penalty",
            ),
            ParameterReroute(
                talemate_parameter="max_tokens", client_parameter="num_predict"
            ),
            "stopping_strings",
            # internal parameters that will be removed before sending
            "extra_stopping_strings",
        ]

    def __init__(
        self,
        **kwargs,
    ):
        self._available_models = []
        self._models_last_fetched = 0
        super().__init__(**kwargs)

    @property
    def can_be_coerced(self):
        """
        Determines whether or not his client can pass LLM coercion. (e.g., is able
        to predefine partial LLM output in the prompt)
        """
        return not self.api_handles_prompt_template and not self.reason_enabled

    @property
    def api_handles_prompt_template(self) -> bool:
        return self.client_config.api_handles_prompt_template

    async def status(self):
        """
        Send a request to the API to retrieve the loaded AI model name.
        Raises an error if no model name is returned.
        :return: None
        """

        if self.processing:
            self.emit_status()
            return

        if not self.enabled:
            self.connected = False
            self.emit_status()
            return

        try:
            # instead of using the client (which apparently cannot set a timeout per endpoint)
            # we use httpx to check {api_url}/api/version to see if the server is running
            # use a timeout of 2 seconds
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url}/api/version", timeout=2)
                response.raise_for_status()

            # if the server is running, fetch the available models
            await self.fetch_available_models()
        except Exception as e:
            log.error("Failed to fetch models from Ollama", error=str(e))
            self.connected = False
            self.emit_status()
            return

        await super().status()

    async def fetch_available_models(self):
        """
        Fetch list of available models from Ollama.
        """
        if time.time() - self._models_last_fetched < FETCH_MODELS_INTERVAL:
            return self._available_models

        client = ollama.AsyncClient(host=self.api_url)

        response = await client.list()
        models = response.get("models", [])
        model_names = [model.model for model in models]
        self._available_models = sorted(model_names)
        self._models_last_fetched = time.time()
        return self._available_models

    def finalize_status(self, data: dict):
        """
        Finalizes the status data for the client.
        """
        data["manual_model_choices"] = self._available_models
        return data

    async def get_model_name(self):
        return self.model

    def prompt_template(self, system_message: str, prompt: str):
        if not self.api_handles_prompt_template:
            return super().prompt_template(system_message, prompt)
        return prompt

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        """
        Tune parameters for Ollama's generate endpoint.
        """
        super().tune_prompt_parameters(parameters, kind)

        # Build stopping strings list
        parameters["stop"] = STOPPING_STRINGS + parameters.get(
            "extra_stopping_strings", []
        )

        # Ollama uses num_predict instead of max_tokens
        if "max_tokens" in parameters:
            parameters["num_predict"] = parameters["max_tokens"]

    def clean_prompt_parameters(self, parameters: dict):
        """
        Clean and prepare parameters for Ollama API.
        """
        # First let parent class handle parameter reroutes and cleanup
        super().clean_prompt_parameters(parameters)

        # Remove our internal parameters
        if "extra_stopping_strings" in parameters:
            del parameters["extra_stopping_strings"]
        if "stopping_strings" in parameters:
            del parameters["stopping_strings"]
        if "stream" in parameters:
            del parameters["stream"]

        # Remove max_tokens as we've already converted it to num_predict
        if "max_tokens" in parameters:
            del parameters["max_tokens"]

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generate text using Ollama's generate endpoint.
        """
        if not self.model_name:
            # Try to get a model name
            await self.get_model_name()
            if not self.model_name:
                raise Exception("No model specified or available in Ollama")

        client = ollama.AsyncClient(host=self.api_url)

        # Prepare options for Ollama
        options = parameters

        options["num_ctx"] = self.max_token_length

        try:
            # Use generate endpoint for completion
            stream = await client.generate(
                model=self.model_name,
                prompt=prompt.strip(),
                options=options,
                raw=self.can_be_coerced,
                stream=True,
            )

            response = ""

            async for part in stream:
                content = part.response
                response += content
                self.update_request_tokens(self.count_tokens(content))

            # Extract the response text
            return response

        except Exception as e:
            log.error("Ollama generation error", error=str(e), model=self.model_name)
            raise ErrorAction(
                message=f"Ollama generation failed: {str(e)}", title="Generation Error"
            )

    async def abort_generation(self):
        """
        Ollama doesn't have a direct abort endpoint, but we can try to stop the model.
        """
        # This is a no-op for now as Ollama doesn't expose an abort endpoint
        # in the Python client
        pass

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        Adjusts temperature and repetition_penalty by random values.
        """
        import random

        temp = prompt_config["temperature"]
        rep_pen = prompt_config.get("repetition_penalty", 1.0)

        min_offset = offset * 0.3

        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
        prompt_config["repetition_penalty"] = random.uniform(
            rep_pen + min_offset * 0.3, rep_pen + offset * 0.3
        )
