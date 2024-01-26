import json
import pydantic
from openai import AsyncOpenAI, PermissionDeniedError

from talemate.client.base import ClientBase, ErrorAction
from talemate.client.registry import register
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.config import load_config
import structlog
import tiktoken

__all__ = [
    "OpenAIClient",
]
log = structlog.get_logger("talemate")

def num_tokens_from_messages(messages:list[dict], model:str="gpt-3.5-turbo-0613"):
    """Return the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model in {
        "gpt-3.5-turbo-0613",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
        "gpt-4-1106-preview",
    }:
        tokens_per_message = 3
        tokens_per_name = 1
    elif model == "gpt-3.5-turbo-0301":
        tokens_per_message = (
            4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        )
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif "gpt-3.5-turbo" in model:
        print(
            "Warning: gpt-3.5-turbo may update over time. Returning num tokens assuming gpt-3.5-turbo-0613."
        )
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613")
    elif "gpt-4" in model:
        print(
            "Warning: gpt-4 may update over time. Returning num tokens assuming gpt-4-0613."
        )
        return num_tokens_from_messages(messages, model="gpt-4-0613")
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            if value is None:
                continue
            if isinstance(value, dict):
                value = json.dumps(value)
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens

class Defaults(pydantic.BaseModel):
    max_token_length:int = 16384
    model:str = "gpt-4-1106-preview"

@register()
class OpenAIClient(ClientBase):
    """
    OpenAI client for generating text.
    """

    client_type = "openai"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    
    class Meta(ClientBase.Meta):
        name_prefix:str = "OpenAI"
        title:str = "OpenAI"
        manual_model:bool = True
        manual_model_choices:list[str] = [
            "gpt-3.5-turbo", 
            "gpt-3.5-turbo-16k",
            "gpt-4",
            "gpt-4-1106-preview",
            "gpt-4-0125-preview",
            "gpt-4-turbo-preview",
        ]
        requires_prompt_template: bool = False
        defaults:Defaults = Defaults()

    def __init__(self, model="gpt-4-turbo-preview", **kwargs):
        
        self.model_name = model
        self.api_key_status = None
        self.config = load_config()
        super().__init__(**kwargs)
        
        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def openai_api_key(self):
        return self.config.get("openai",{}).get("api_key")


    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.openai_api_key:
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
                    "openai_api",
                ]
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
            }
        )

    def set_client(self, max_token_length:int=None):

        if not self.openai_api_key:
            self.client = AsyncOpenAI(api_key="sk-1111")
            log.error("No OpenAI API key set")
            if self.api_key_status:
                self.api_key_status = False
                emit('request_client_status')
                emit('request_agent_status')
            return
        
        if not self.model_name:
            self.model_name = "gpt-3.5-turbo-16k"
        
        model = self.model_name
        
        self.client = AsyncOpenAI(api_key=self.openai_api_key)
        if model == "gpt-3.5-turbo":
            self.max_token_length = min(max_token_length or 4096, 4096)
        elif model == "gpt-4":
            self.max_token_length = min(max_token_length or 8192, 8192)
        elif model == "gpt-3.5-turbo-16k":
            self.max_token_length = min(max_token_length or 16384, 16384)
        elif model == "gpt-4-1106-preview":
            self.max_token_length = min(max_token_length or 128000, 128000)
        else:
            self.max_token_length = max_token_length or 2048
        
        
        if not self.api_key_status:
            if self.api_key_status is False:
                emit('request_client_status')
                emit('request_agent_status')
            self.api_key_status = True
        
        log.info("openai set client", max_token_length=self.max_token_length, provided_max_token_length=max_token_length, model=model)
            
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
        return num_tokens_from_messages([{"content": content}], model=self.model_name)

    async def status(self):
        self.emit_status()


    def prompt_template(self, system_message:str, prompt:str):
        # only gpt-4-1106-preview supports json_object response coersion
        
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>",  "\nContinue this response: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")
                
        return prompt

    def tune_prompt_parameters(self, parameters:dict, kind:str):
        super().tune_prompt_parameters(parameters, kind)
        
        keys = list(parameters.keys())
        
        valid_keys = ["temperature", "top_p"]
        
        for key in keys:
            if key not in valid_keys:
                del parameters[key]

    async def generate(self, prompt:str, parameters:dict, kind:str):
        
        """
        Generates text from the given prompt and parameters.
        """
        
        if not self.openai_api_key:
            raise Exception("No OpenAI API key set")
        
        # only gpt-4-* supports enforcing json object
        supports_json_object = self.model_name.startswith("gpt-4-")
        right = None
        try:
            _, right = prompt.split("\nContinue this response: ")
            expected_response = right.strip()
            if expected_response.startswith("{") and supports_json_object:
                parameters["response_format"] = {"type": "json_object"}
        except (IndexError, ValueError):
            pass
        
        human_message = {'role': 'user', 'content': prompt.strip()}
        system_message = {'role': 'system', 'content': self.get_system_message(kind)}
        
        self.log.debug("generate", prompt=prompt[:128]+" ...", parameters=parameters)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name, messages=[system_message, human_message], **parameters
            )
            
            response = response.choices[0].message.content
            
            if right and response.startswith(right):
                response = response[len(right):].strip()
                
            return response
        except PermissionDeniedError as e:
            self.log.error("generate error", e=e)
            emit("status", message="OpenAI API: Permission Denied", status="error")
            return ""
        except Exception as e:
            raise