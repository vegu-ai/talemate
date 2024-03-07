import json

import pydantic
import structlog
import tiktoken
from openai import AsyncOpenAI, PermissionDeniedError

from talemate.client.base import ClientBase, ErrorAction
from talemate.client.registry import register
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers

__all__ = [
    "MistralAIClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "open-mistral-7b",
    "open-mixtral-8x7b",
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-latest",
]


class Defaults(pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "open-mixtral-8x7b"


@register()
class MistralAIClient(ClientBase):
    """
    OpenAI client for generating text.
    """

    client_type = "mistral"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    # TODO: make this configurable?
    decensor_enabled = False

    class Meta(ClientBase.Meta):
        name_prefix: str = "MistralAI"
        title: str = "MistralAI"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

    def __init__(self, model="open-mixtral-8x7b", **kwargs):
        self.model_name = model
        self.api_key_status = None
        self.config = load_config()
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def mistralai_api_key(self):
        return self.config.get("mistralai", {}).get("api_key")

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.mistralai_api_key:
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
                    "mistralai_api",
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
        if not self.mistralai_api_key:
            self.client = AsyncOpenAI(api_key="sk-1111")
            log.error("No mistral.ai API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "open-mixtral-8x7b"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        model = self.model_name

        self.client = AsyncOpenAI(api_key=self.mistralai_api_key, base_url="https://api.mistral.ai/v1/")
        self.max_token_length = max_token_length or 16384

        if not self.api_key_status:
            if self.api_key_status is False:
                emit("request_client_status")
                emit("request_agent_status")
            self.api_key_status = True

        log.info(
            "mistral.ai set client",
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

    def count_tokens(self, content: str):
        if not self.model_name:
            return 0
        return 0

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

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)

        keys = list(parameters.keys())

        valid_keys = ["temperature", "top_p"]

        # GPT-3.5 models tend to run away with the generated
        # response size so we allow talemate to set the max_tokens
        #
        # GPT-4 on the other hand seems to benefit from letting it
        # decide the generation length naturally and it will generally
        # produce reasonably sized responses
        if self.model_name.startswith("gpt-3.5-"):
            valid_keys.append("max_tokens")

        for key in keys:
            if key not in valid_keys:
                del parameters[key]

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.mistralai_api_key:
            raise Exception("No mistral.ai API key set")

        right = None
        expected_response = None
        try:
            _, right = prompt.split("\nStart your response with: ")
            expected_response = right.strip()
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
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[system_message, human_message],
                **parameters,
            )

            response = response.choices[0].message.content

            # older models don't support json_object response coersion
            # and often like to return the response wrapped in ```json
            # so we strip that out if the expected response is a json object
            if (
                expected_response
                and expected_response.startswith("{")
            ):
                if response.startswith("```json") and response.endswith("```"):
                    response = response[7:-3].strip()

            if right and response.startswith(right):
                response = response[len(right) :].strip()

            return response
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="mistral.ai API: Permission Denied", status="error")
            return ""
        except Exception as e:
            raise
