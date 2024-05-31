import pydantic
import structlog
from groq import AsyncGroq, PermissionDeniedError

from talemate.client.base import ClientBase, ErrorAction, ParameterReroute
from talemate.client.registry import register
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers

__all__ = [
    "GroqClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "mixtral-8x7b-32768",
    "llama3-8b-8192",
    "llama3-70b-8192",
]

JSON_OBJECT_RESPONSE_MODELS = []


class Defaults(pydantic.BaseModel):
    max_token_length: int = 8192
    model: str = "llama3-70b-8192"


@register()
class GroqClient(ClientBase):
    """
    OpenAI client for generating text.
    """

    client_type = "groq"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    # TODO: make this configurable?
    decensor_enabled = True

    class Meta(ClientBase.Meta):
        name_prefix: str = "Groq"
        title: str = "Groq"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

    def __init__(self, model="llama3-70b-8192", **kwargs):
        self.model_name = model
        self.api_key_status = None
        self.config = load_config()
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def groq_api_key(self):
        return self.config.get("groq", {}).get("api_key")

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            ParameterReroute(talemate_parameter="stopping_strings",  client_parameter="stop"),
            "max_tokens",
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.groq_api_key:
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
                    "groq_api",
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
            status=status if self.enabled else "disabled",
            data={
                "error_action": error_action.model_dump() if error_action else None,
                "meta": self.Meta().model_dump(),
                "enabled": self.enabled,
            },
        )

    def set_client(self, max_token_length: int = None):
        if not self.groq_api_key:
            self.client = AsyncGroq(api_key="sk-1111")
            log.error("No groq.ai API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "llama3-70b-8192"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        model = self.model_name

        self.client = AsyncGroq(api_key=self.groq_api_key)
        self.max_token_length = max_token_length or 16384

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "groq.ai set client",
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

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    def response_tokens(self, response: str):
        return response.usage.completion_tokens

    def prompt_tokens(self, response: str):
        return response.usage.prompt_tokens

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

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.groq_api_key:
            raise Exception("No groq.ai API key set")

        supports_json_object = self.model_name in JSON_OBJECT_RESPONSE_MODELS
        right = None
        expected_response = None
        try:
            _, right = prompt.split("\nStart your response with: ")
            expected_response = right.strip()
            if expected_response.startswith("{") and supports_json_object:
                parameters["response_format"] = {"type": "json_object"}
        except (IndexError, ValueError):
            pass

        system_message = self.get_system_message(kind)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                **parameters,
            )

            response = response.choices[0].message.content

            # older models don't support json_object response coersion
            # and often like to return the response wrapped in ```json
            # so we strip that out if the expected response is a json object
            if (
                not supports_json_object
                and expected_response
                and expected_response.startswith("{")
            ):
                if response.startswith("```json") and response.endswith("```"):
                    response = response[7:-3].strip()

            if right and response.startswith(right):
                response = response[len(right) :].strip()

            return response
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="OpenAI API: Permission Denied", status="error")
            return ""
        except Exception as e:
            raise
