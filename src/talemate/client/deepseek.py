import pydantic
import structlog
from openai import AsyncOpenAI, PermissionDeniedError

from talemate.client.base import ClientBase, ErrorAction, CommonDefaults
from talemate.client.registry import register
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.util import count_tokens

__all__ = [
    "DeepSeekClient",
]
log = structlog.get_logger("talemate")

BASE_URL = "https://api.deepseek.com"

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
]

JSON_OBJECT_RESPONSE_MODELS = [
    "deepseek-chat",
]


class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "deepseek-chat"


@register()
class DeepSeekClient(ClientBase):
    """
    DeepSeek client for generating text.
    """

    client_type = "deepseek"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    # TODO: make this configurable?
    decensor_enabled = False

    class Meta(ClientBase.Meta):
        name_prefix: str = "DeepSeek"
        title: str = "DeepSeek"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

    def __init__(self, model="deepseek-chat", **kwargs):
        self.model_name = model
        self.api_key_status = None
        self.config = load_config()
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def deepseek_api_key(self):
        return self.config.get("deepseek", {}).get("api_key")

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "presence_penalty",
            "max_tokens",
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.deepseek_api_key:
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
                    "deepseek_api",
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
        if not self.deepseek_api_key:
            self.client = AsyncOpenAI(api_key="sk-1111", base_url=BASE_URL)
            log.error("No DeepSeek API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "deepseek-chat"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        model = self.model_name

        self.client = AsyncOpenAI(api_key=self.deepseek_api_key, base_url=BASE_URL)
        self.max_token_length = max_token_length or 16384

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "deepseek set client",
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

        self._reconfigure_common_parameters(**kwargs)

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    def count_tokens(self, content: str):
        if not self.model_name:
            return 0
        return count_tokens(content)

    async def status(self):
        self.emit_status()

    def prompt_template(self, system_message: str, prompt: str):
        # only gpt-4-1106-preview supports json_object response coersion

        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>", "\nStart your response with: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")

        return prompt

    def response_tokens(self, response: str):
        # Count tokens in a response string using the util.count_tokens helper
        return self.count_tokens(response)

    def prompt_tokens(self, prompt: str):
        # Count tokens in a prompt string using the util.count_tokens helper
        return self.count_tokens(prompt)

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.deepseek_api_key:
            raise Exception("No DeepSeek API key set")

        # only gpt-4-* supports enforcing json object
        supports_json_object = (
            self.model_name.startswith("gpt-4-")
            or self.model_name in JSON_OBJECT_RESPONSE_MODELS
        )
        right = None
        expected_response = None
        try:
            _, right = prompt.split("\nStart your response with: ")
            expected_response = right.strip()
            if expected_response.startswith("{") and supports_json_object:
                parameters["response_format"] = {"type": "json_object"}
        except (IndexError, ValueError):
            pass

        human_message = {"role": "user", "content": prompt.strip()}
        system_message = {"role": "system", "content": self.get_system_message(kind)}

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
        )

        try:
            # Use streaming so we can update_Request_tokens incrementally
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[system_message, human_message],
                stream=True,
                **parameters,
            )

            response = ""

            # Iterate over streamed chunks
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and getattr(delta, "content", None):
                    content_piece = delta.content
                    response += content_piece
                    # Incrementally track token usage
                    self.update_request_tokens(self.count_tokens(content_piece))

            # Save token accounting for whole request
            self._returned_prompt_tokens = self.prompt_tokens(prompt)
            self._returned_response_tokens = self.response_tokens(response)

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
            emit("status", message="DeepSeek API: Permission Denied", status="error")
            return ""
        except Exception:
            raise
