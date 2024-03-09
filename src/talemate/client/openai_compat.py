import pydantic
import structlog
import urllib
from openai import AsyncOpenAI, NotFoundError, PermissionDeniedError

from talemate.client.base import ClientBase
from talemate.client.registry import register
from talemate.emit import emit

log = structlog.get_logger("talemate.client.openai_compat")

EXPERIMENTAL_DESCRIPTION = """Use this client if you want to connect to a service implementing an OpenAI-compatible API. Success is going to depend on the level of compatibility. Use the actual OpenAI client if you want to connect to OpenAI's API."""


class Defaults(pydantic.BaseModel):
    api_url: str = "http://localhost:5000"
    api_key: str = ""
    max_token_length: int = 4096
    model: str = ""


@register()
class OpenAICompatibleClient(ClientBase):
    client_type = "openai_compat"
    conversation_retries = 5

    class Meta(ClientBase.Meta):
        title: str = "OpenAI Compatible API"
        name_prefix: str = "OpenAI Compatible API"
        experimental: str = EXPERIMENTAL_DESCRIPTION
        enable_api_auth: bool = True
        manual_model: bool = True
        defaults: Defaults = Defaults()

    def __init__(self, model=None, api_key=None, **kwargs):
        self.model_name = model
        self.api_key = api_key
        super().__init__(**kwargs)

    @property
    def experimental(self):
        return EXPERIMENTAL_DESCRIPTION

    def set_client(self, **kwargs):
        self.api_key = kwargs.get("api_key", self.api_key)
        url = self.api_url
        self.client = AsyncOpenAI(base_url=url, api_key=self.api_key)
        self.model_name = (
            kwargs.get("model") or kwargs.get("model_name") or self.model_name
        )

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)

        keys = list(parameters.keys())

        valid_keys = ["temperature", "top_p", "max_tokens"]

        for key in keys:
            if key not in valid_keys:
                del parameters[key]

    async def get_model_name(self):
        return self.model_name
    
    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """
        human_message = {"role": "user", "content": prompt.strip()}

        self.log.debug("generate", prompt=prompt[:128] + " ...", parameters=parameters)

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name, messages=[human_message], **parameters
            )

            return response.choices[0].message.content
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="Client API: Permission Denied", status="error")
            return ""
        except Exception as e:
            self.log.error("generate error", e=e)
            emit(
                "status", message="Error during generation (check logs)", status="error"
            )
            return ""

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
        if "api_url" in kwargs:
            self.api_url = kwargs["api_url"]
        if "max_token_length" in kwargs:
            self.max_token_length = (
                int(kwargs["max_token_length"]) if kwargs["max_token_length"] else 4096
            )
        if "api_key" in kwargs:
            self.api_auth = kwargs["api_key"]

        log.warning("reconfigure", kwargs=kwargs)

        self.set_client(**kwargs)
