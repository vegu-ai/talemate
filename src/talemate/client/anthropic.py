import pydantic
import structlog
from anthropic import AsyncAnthropic, PermissionDeniedError

from talemate.client.base import ClientBase, ErrorAction, CommonDefaults
from talemate.client.registry import register
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers

__all__ = [
    "AnthropicClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "claude-3-haiku-20240307",
    "claude-3-sonnet-20240229",
    "claude-3-opus-20240229",
    "claude-3-5-sonnet-20240620",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
    "claude-3-7-sonnet-latest",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
]


class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "claude-3-5-sonnet-latest"
    double_coercion: str = None

@register()
class AnthropicClient(ClientBase):
    """
    Anthropic client for generating text.
    """

    client_type = "anthropic"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    # TODO: make this configurable?
    decensor_enabled = False

    class Meta(ClientBase.Meta):
        name_prefix: str = "Anthropic"
        title: str = "Anthropic"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

    def __init__(self, model="claude-3-5-sonnet-latest", **kwargs):
        self.model_name = model
        self.api_key_status = None
        self.config = load_config()
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def can_be_coerced(self) -> bool:
        return True

    @property
    def anthropic_api_key(self):
        return self.config.get("anthropic", {}).get("api_key")

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "top_k",
            "max_tokens",
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.anthropic_api_key:
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
                    "anthropic_api",
                ],
            )

        if not self.model_name:
            status = "error"
            model_name = "No model loaded"

        self.current_status = status

        data={
            "error_action": error_action.model_dump() if error_action else None,
            "double_coercion": self.double_coercion,
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
        if not self.anthropic_api_key:
            self.client = AsyncAnthropic(api_key="sk-1111")
            log.error("No anthropic API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "claude-3-opus-20240229"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        model = self.model_name

        self.client = AsyncAnthropic(api_key=self.anthropic_api_key)
        self.max_token_length = max_token_length or 16384

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "anthropic set client",
            max_token_length=self.max_token_length,
            provided_max_token_length=max_token_length,
            model=model,
        )

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))

        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])
            
        if "double_coercion" in kwargs:
            self.double_coercion = kwargs["double_coercion"]
            
        self._reconfigure_common_parameters(**kwargs)

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    def response_tokens(self, response: str):
        return response.usage.output_tokens

    def prompt_tokens(self, response: str):
        return response.usage.input_tokens

    async def status(self):
        self.emit_status()

    def prompt_template(self, system_message: str, prompt: str):
        """
        Anthropic handles the prompt template internally, so we just
        give the prompt as is.
        """
        return prompt

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.anthropic_api_key:
            raise Exception("No anthropic API key set")
        
        prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        
        system_message = self.get_system_message(kind)
        
        messages = [
            {"role": "user", "content": prompt.strip()}
        ]
        
        if coercion_prompt:
            messages.append({"role": "assistant", "content": coercion_prompt.strip()})

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )
        
        completion_tokens = 0
        prompt_tokens = 0

        try:
            stream = await self.client.messages.create(
                model=self.model_name,
                system=system_message,
                messages=messages,
                stream=True,
                **parameters,
            )
            
            response = ""
            
            async for event in stream:
                
                if event.type == "content_block_delta":
                    content = event.delta.text
                    response += content
                    self.update_request_tokens(self.count_tokens(content))
                    
                elif event.type == "message_start":
                    prompt_tokens = event.message.usage.input_tokens
                    
                elif event.type == "message_delta":
                    completion_tokens += event.usage.output_tokens
                

            self._returned_prompt_tokens = prompt_tokens
            self._returned_response_tokens = completion_tokens

            log.debug("generated response", response=response)

            return response
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="anthropic API: Permission Denied", status="error")
            return ""
        except Exception as e:
            raise
