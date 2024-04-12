import pydantic
import structlog
from cohere import AsyncClient

from talemate.client.base import ClientBase, ErrorAction
from talemate.client.registry import register
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.util import count_tokens

__all__ = [
    "CohereClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "command",
    "command-r",
    "command-r-plus",
]


class Defaults(pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "command-r-plus"


@register()
class CohereClient(ClientBase):
    """
    Cohere client for generating text.
    """

    client_type = "cohere"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    decensor_enabled = True

    class Meta(ClientBase.Meta):
        name_prefix: str = "Cohere"
        title: str = "Cohere"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

    def __init__(self, model="command-r-plus", **kwargs):
        self.model_name = model
        self.api_key_status = None
        self.config = load_config()
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def cohere_api_key(self):
        return self.config.get("cohere", {}).get("api_key")

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.cohere_api_key:
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
                    "cohere_api",
                ],
            )

        if not self.model_name:
            status = "error"
            model_name = "No model loaded"

        self.current_status = status

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status,
            data={
                "error_action": error_action.model_dump() if error_action else None,
                "meta": self.Meta().model_dump(),
            },
        )

    def set_client(self, max_token_length: int = None):
        if not self.cohere_api_key:
            self.client = AsyncClient("sk-1111")
            log.error("No cohere API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "command-r-plus"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        model = self.model_name

        self.client = AsyncClient(self.cohere_api_key)
        self.max_token_length = max_token_length or 16384

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "cohere set client",
            max_token_length=self.max_token_length,
            provided_max_token_length=max_token_length,
            model=model,
        )

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    def response_tokens(self, response: str):
        return count_tokens(response.text)

    def prompt_tokens(self, prompt: str):
        return count_tokens(prompt)

    async def status(self):
        self.emit_status()

    def prompt_template(self, system_message: str, prompt: str):
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>", "\nStart your response with: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")

        return prompt

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)
        keys = list(parameters.keys())
        valid_keys = ["temperature", "max_tokens"]
        for key in keys:
            if key not in valid_keys:
                del parameters[key]

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.cohere_api_key:
            raise Exception("No cohere API key set")

        right = None
        expected_response = None
        try:
            _, right = prompt.split("\nStart your response with: ")
            expected_response = right.strip()
        except (IndexError, ValueError):
            pass

        human_message = prompt.strip()
        system_message = self.get_system_message(kind)

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        try:
            response = await self.client.chat(
                model=self.model_name,
                preamble=system_message,
                message=human_message,
                **parameters,
            )

            self._returned_prompt_tokens = self.prompt_tokens(prompt)
            self._returned_response_tokens = self.response_tokens(response)

            log.debug("generated response", response=response.text)

            response = response.text

            if expected_response and expected_response.startswith("{"):
                if response.startswith("```json") and response.endswith("```"):
                    response = response[7:-3].strip()

            if right and response.startswith(right):
                response = response[len(right) :].strip()

            return response
        #except PermissionDeniedError as e:
        #    self.log.error("generate error", e=e)
        #    emit("status", message="cohere API: Permission Denied", status="error")
        #    return ""
        except Exception as e:
            raise
