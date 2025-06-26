import random
import urllib

import pydantic
import structlog
from openai import AsyncOpenAI, NotFoundError, PermissionDeniedError

from talemate.client.base import ClientBase, ExtraField, ParameterReroute
from talemate.client.instructor_mixin import InstructorMixin
from talemate.client.registry import register
from talemate.config import Client as BaseClientConfig
from talemate.emit import emit

log = structlog.get_logger("talemate.client.openai_compat")

EXPERIMENTAL_DESCRIPTION = """Use this client if you want to connect to a service implementing an OpenAI-compatible API. Success is going to depend on the level of compatibility. Use the actual OpenAI client if you want to connect to OpenAI's API."""


class Defaults(pydantic.BaseModel):
    api_url: str = "http://localhost:5000"
    api_key: str = ""
    max_token_length: int = 8192
    model: str = ""
    api_handles_prompt_template: bool = False
    double_coercion: str = None
    rate_limit: int | None = None


class ClientConfig(BaseClientConfig):
    api_handles_prompt_template: bool = False

@register()
class OpenAICompatibleClient(InstructorMixin, ClientBase):
    client_type = "openai_compat"
    conversation_retries = 0
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        title: str = "OpenAI Compatible API"
        name_prefix: str = "OpenAI Compatible API"
        experimental: str = EXPERIMENTAL_DESCRIPTION
        enable_api_auth: bool = True
        manual_model: bool = True
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = {
            "api_handles_prompt_template": ExtraField(
                name="api_handles_prompt_template",
                type="bool",
                label="API handles prompt template (chat/completions)",
                required=False,
                description="The API handles the prompt template, meaning your choice in the UI for the prompt template below will be ignored. This is not recommended and should only be used if the API does not support the `completions` andpoint or you don't know which prompt template to use.",
            )
        }

    def __init__(
        self, model=None, api_key=None, api_handles_prompt_template=False, **kwargs
    ):
        self.model_name = model
        self.api_key = api_key
        self.api_handles_prompt_template = api_handles_prompt_template
        super().__init__(**kwargs)

    @property
    def experimental(self):
        return EXPERIMENTAL_DESCRIPTION

    @property
    def can_be_coerced(self):
        """
        Determines whether or not his client can pass LLM coercion. (e.g., is able
        to predefine partial LLM output in the prompt)
        """
        return not self.api_handles_prompt_template

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "max_tokens",
            ParameterReroute(
                talemate_parameter="stopping_strings", client_parameter="stop"
            ),
        ]

    def set_client(self, **kwargs):
        self.api_key = kwargs.get("api_key", self.api_key)
        self.api_handles_prompt_template = kwargs.get(
            "api_handles_prompt_template", self.api_handles_prompt_template
        )
        url = self.api_url
        self.client = AsyncOpenAI(base_url=url, api_key=self.api_key)
        self.model_name = (
            kwargs.get("model") or kwargs.get("model_name") or self.model_name
        )
        
        # Setup instructor support
        self.setup_instructor()

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

    async def get_model_name(self):
        return self.model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters using streaming.
        """
        try:
            if self.api_handles_prompt_template:
                # API handles prompt template - use chat completions
                self.log.debug(
                    "generate (chat/completions)",
                    prompt=prompt[:128] + " ...",
                    parameters=parameters,
                )
                
                system_message = self.get_system_message(kind)
                messages = [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt.strip()}
                ]
                
                # Clean parameters before sending
                self.clean_prompt_parameters(parameters)
                
                stream = await self.client.chat.completions.create(
                    model=self.model_name, 
                    messages=messages, 
                    stream=True, 
                    **parameters
                )
                
                response = ""
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        response += content
                        self.update_request_tokens(self.count_tokens(content))
                
                return self.process_response_for_indirect_coercion(prompt, response)
            else:
                # Talemate handles prompt template - use chat completions with coercion
                self.log.debug(
                    "generate (completions via chat)",
                    prompt=prompt[:128] + " ...",
                    parameters=parameters,
                )
                
                # Check for coercion
                prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
                
                system_message = self.get_system_message(kind)
                messages = [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt.strip()}
                ]
                
                if coercion_prompt:
                    messages.append({"role": "assistant", "content": coercion_prompt.strip()})
                
                # Clean parameters before sending
                self.clean_prompt_parameters(parameters)
                
                stream = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    stream=True,
                    **parameters
                )
                
                response = ""
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        response += content
                        self.update_request_tokens(self.count_tokens(content))
                
                return response
                
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
                int(kwargs["max_token_length"]) if kwargs["max_token_length"] else 8192
            )
        if "api_key" in kwargs:
            self.api_key = kwargs["api_key"]
        if "api_handles_prompt_template" in kwargs:
            self.api_handles_prompt_template = kwargs["api_handles_prompt_template"]
        # TODO: why isn't this calling super()?
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])

        if "double_coercion" in kwargs:
            self.double_coercion = kwargs["double_coercion"]
            
        if "rate_limit" in kwargs:
            self.rate_limit = kwargs["rate_limit"]

        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])

        self.set_client(**kwargs)

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        adjusts temperature and presence penalty
        by random values using the base value as a center
        """

        temp = prompt_config["temperature"]

        min_offset = offset * 0.3

        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)

        try:
            presence_penalty = prompt_config["presence_penalty"]
            prompt_config["presence_penalty"] = round(
                random.uniform(presence_penalty + 0.1, presence_penalty + offset), 1
            )
        except KeyError:
            pass
