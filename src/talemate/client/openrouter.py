import pydantic
import structlog
import asyncio
from openai import AsyncOpenAI

from talemate.client.base import ClientBase, ErrorAction, CommonDefaults
from talemate.client.registry import register
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers

__all__ = [
    "OpenRouterClient",
]

log = structlog.get_logger("talemate.client.openrouter")

# Available models will be populated when first client with API key is initialized
AVAILABLE_MODELS = []
DEFAULT_MODEL = ""
MODELS_FETCHED = False

async def fetch_available_models(api_key: str = None):
    """Fetch available models from OpenRouter API"""
    global AVAILABLE_MODELS, DEFAULT_MODEL, MODELS_FETCHED
    
    if not api_key:
        return []
    
    if MODELS_FETCHED:
        return AVAILABLE_MODELS
    
    # Only fetch if we haven't already or if explicitly requested
    if AVAILABLE_MODELS and not api_key:
        return AVAILABLE_MODELS
    
    try:
        # Use OpenAI client to fetch models
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1"
        )
        models_response = await client.models.list()
        models = []
        for model in models_response.data:
            if hasattr(model, 'id') and model.id:
                models.append(model.id)
        AVAILABLE_MODELS = sorted(models)
        log.debug(f"Fetched {len(AVAILABLE_MODELS)} models from OpenRouter")
    except Exception as e:
        log.error(f"Error fetching models from OpenRouter: {e}")
    
    MODELS_FETCHED = True
    return AVAILABLE_MODELS



def fetch_models_sync(event):
    api_key = event.data.get("openrouter", {}).get("api_key")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(fetch_available_models(api_key))

handlers["config_saved"].connect(fetch_models_sync)
handlers["talemate_started"].connect(fetch_models_sync)

class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = DEFAULT_MODEL


@register()
class OpenRouterClient(ClientBase):
    """
    OpenRouter client for generating text using various models.
    """

    client_type = "openrouter"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    # TODO: make this configurable?
    decensor_enabled = False

    class Meta(ClientBase.Meta):
        name_prefix: str = "OpenRouter"
        title: str = "OpenRouter"
        manual_model: bool = True
        manual_model_choices: list[str] = pydantic.Field(default_factory=lambda: AVAILABLE_MODELS)
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

    def __init__(self, model=None, **kwargs):
        self.model_name = model or DEFAULT_MODEL
        self.api_key_status = None
        self.config = load_config()
        self._models_fetched = False
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def can_be_coerced(self) -> bool:
        return True

    @property
    def openrouter_api_key(self):
        return self.config.get("openrouter", {}).get("api_key")

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
        if processing is not None:
            self.processing = processing

        if self.openrouter_api_key:
            status = "busy" if self.processing else "idle"
            model_name = self.model_name
        else:
            status = "error"
            model_name = "No API key set"
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
            model_name = "No model loaded"

        self.current_status = status

        data = {
            "error_action": error_action.model_dump() if error_action else None,
            "meta": self.Meta().model_dump(),
            "enabled": self.enabled,
        }
        data.update(self._common_status_data())

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status if self.enabled else "disabled",
            data=data,
        )

    def set_client(self, max_token_length: int = None):
        if not self.openrouter_api_key:
            log.error("No OpenRouter API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = DEFAULT_MODEL

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)
        
        # Set max token length (default to 16k if not specified)
        self.max_token_length = max_token_length or 16384

        # Initialize the OpenAI client with OpenRouter's base URL
        self.client = AsyncOpenAI(
            api_key=self.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1"
        )

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "openrouter set client",
            max_token_length=self.max_token_length,
            provided_max_token_length=max_token_length,
            model=self.model_name,
        )

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))

        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])

        self._reconfigure_common_parameters(**kwargs)

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    async def status(self):
        # Fetch models if we have an API key and haven't fetched yet
        if self.openrouter_api_key and not self._models_fetched:
            self._models_fetched = True
            # Update the Meta class with new model choices
            self.Meta.manual_model_choices = AVAILABLE_MODELS
        
        self.emit_status()

    def prompt_template(self, system_message: str, prompt: str):
        """
        Open-router handles the prompt template internally, so we just
        give the prompt as is.
        """
        return prompt

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters using OpenRouter API.
        """

        if not self.openrouter_api_key:
            raise Exception("No OpenRouter API key set")

        prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        
        # Prepare messages for chat completion
        messages = [
            {"role": "system", "content": self.get_system_message(kind)},
            {"role": "user", "content": prompt.strip()}
        ]
        
        if coercion_prompt:
            messages.append({"role": "assistant", "content": coercion_prompt.strip()})

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            model=self.model_name,
        )
        
        response_text = ""
        completion_tokens = 0
        prompt_tokens = 0
        
        try:
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=True,
                **parameters
            )
            
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    response_text += content
                    # Update tokens as content streams in
                    self.update_request_tokens(self.count_tokens(content))
                
                # OpenRouter may include usage data in chunks
                if hasattr(chunk, 'usage') and chunk.usage:
                    if hasattr(chunk.usage, 'completion_tokens'):
                        completion_tokens = chunk.usage.completion_tokens
                    if hasattr(chunk.usage, 'prompt_tokens'):
                        prompt_tokens = chunk.usage.prompt_tokens
            
            self._returned_prompt_tokens = prompt_tokens
            self._returned_response_tokens = completion_tokens
            
            return response_text
                
        except Exception as e:
            self.log.error("generate error", e=e)
            if "timeout" in str(e).lower():
                emit("status", message="OpenRouter API: Request timed out", status="error")
                return ""
            else:
                emit("status", message=f"OpenRouter API Error: {str(e)}", status="error")
                raise