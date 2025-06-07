import asyncio
import structlog
import httpx
import ollama
from typing import Union

from talemate.client.base import STOPPING_STRINGS, ClientBase, CommonDefaults, ErrorAction, ParameterReroute, ExtraField
from talemate.client.registry import register
from talemate.config import Client as BaseClientConfig

log = structlog.get_logger("talemate.client.ollama")


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
        manual_model_choices: list[str] = []  # Will be populated dynamically
        defaults: OllamaClientDefaults = OllamaClientDefaults()
        extra_fields: dict[str, ExtraField] = {
            "api_handles_prompt_template": ExtraField(
                name="api_handles_prompt_template",
                type="bool",
                label="API handles prompt template",
                required=False,
                description="Let Ollama handle the prompt template. Only do this if you don't know which prompt template to use. Letting talemate handle the prompt template will generally lead to improved responses.",
            )
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
                client_parameter="repeat_penalty"
            ),
            ParameterReroute(
                talemate_parameter="max_tokens",
                client_parameter="num_predict"
            ),
            "stopping_strings",
            # internal parameters that will be removed before sending
            "extra_stopping_strings",
        ]

    @property
    def can_be_coerced(self):
        """
        Determines whether or not his client can pass LLM coercion. (e.g., is able
        to predefine partial LLM output in the prompt)
        """
        return not self.api_handles_prompt_template

    def __init__(self, model=None, api_handles_prompt_template=False, **kwargs):
        self.model_name = model
        self.api_handles_prompt_template = api_handles_prompt_template
        super().__init__(**kwargs)
        self.client = None
        self._available_models = []

    def set_client(self, **kwargs):
        """
        Initialize the Ollama client with the API URL.
        """
        # Update model if provided
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            
        # Create async client with the configured API URL
        # Ollama's AsyncClient expects just the base URL without any path
        self.client = ollama.AsyncClient(host=self.api_url)
        self.api_handles_prompt_template = kwargs.get(
            "api_handles_prompt_template", self.api_handles_prompt_template
        )   
        log.info(f"Ollama client initialized with URL: {self.api_url}")

    async def fetch_available_models(self):
        """
        Fetch list of available models from Ollama.
        """
        try:
            response = await self.client.list()
            models = response.get("models", [])
            
            # Extract model names (without tags)
            model_names = []
            for model in models:
                name = model.get("name", "")
                # Remove tag if present (e.g., "llama3.2:latest" -> "llama3.2")
                base_name = name.split(":")[0] if ":" in name else name
                if base_name and base_name not in model_names:
                    model_names.append(base_name)
            
            self._available_models = sorted(model_names)
            # Update the Meta class with available models
            self.Meta.manual_model_choices = self._available_models
            
            log.info(f"Fetched {len(self._available_models)} models from Ollama")
            return self._available_models
            
        except Exception as e:
            log.error("Failed to fetch models from Ollama", error=str(e))
            return []

    async def get_model_name(self):
        return self.model_name
    
    def prompt_template(self, system_message: str, prompt: str):

        log.debug(
            "IS API HANDLING PROMPT TEMPLATE",
            api_handles_prompt_template=self.api_handles_prompt_template,
        )

        if not self.api_handles_prompt_template:
            return super().prompt_template(system_message, prompt)

        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>", "\nStart your response with: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")

        return prompt
    
    async def status(self):
        """
        Send status and fetch available models if needed.
        """
        # Call parent status method
        await super().status()

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        """
        Tune parameters for Ollama's generate endpoint.
        """
        super().tune_prompt_parameters(parameters, kind)
        
        # Build stopping strings list
        parameters["stop"] = STOPPING_STRINGS + parameters.get("extra_stopping_strings", [])
        
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
        
        # Prepare options for Ollama
        options = {}
        
        # Map parameters to Ollama's option names
        param_mapping = {
            "temperature": "temperature",
            "top_p": "top_p",
            "top_k": "top_k", 
            "min_p": "min_p",
            "frequency_penalty": "frequency_penalty",
            "presence_penalty": "presence_penalty",
            "repetition_penalty": "repeat_penalty",
            "repetition_penalty_range": "repeat_last_n",
            "num_predict": "num_predict",
            "stop": "stop",
        }
        
        for param_key, ollama_key in param_mapping.items():
            if param_key in parameters:
                options[ollama_key] = parameters[param_key]
        
        try:
            # Use generate endpoint for completion
            response = await self.client.generate(
                model=self.model_name,
                prompt=prompt.strip(),
                stream=False,
                options=options,
                raw=self.can_be_coerced,
            )
            
            # Extract the response text
            return response.get("response", "")
            
        except Exception as e:
            log.error("Ollama generation error", error=str(e), model=self.model_name)
            raise ErrorAction(
                message=f"Ollama generation failed: {str(e)}",
                title="Generation Error"
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

    def reconfigure(self, **kwargs):
        """
        Reconfigure the client with new settings.
        """
        # Handle model update
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            
        super().reconfigure(**kwargs)
        
        # Re-initialize client if API URL changed or model changed
        if "api_url" in kwargs or "model" in kwargs:
            self.set_client(**kwargs)
            
        if "api_handles_prompt_template" in kwargs:
            self.api_handles_prompt_template = kwargs["api_handles_prompt_template"]
