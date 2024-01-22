import pydantic
from talemate.client.base import ClientBase
from talemate.client.registry import register

from openai import AsyncOpenAI, PermissionDeniedError, NotFoundError
from talemate.emit import emit

EXPERIMENTAL_DESCRIPTION = """Use this client if you want to connect to a service implementing an OpenAI-compatible API. Success is going to depend on the level of compatibility. Use the actual OpenAI client if you want to connect to OpenAI's API."""

class Defaults(pydantic.BaseModel):
    api_url:str = "http://localhost:5000"
    api_key:str = ""
    max_token_length:int = 4096
    model:str = ""

@register()
class OpenAICompatibleClient(ClientBase):
    
    client_type = "openai_compat"
    conversation_retries = 5
    
    class Meta(ClientBase.Meta):
        title:str = "OpenAI Compatible API"
        name_prefix:str = "OpenAI Compatible API"
        experimental:str = EXPERIMENTAL_DESCRIPTION
        enable_api_auth:bool = True
        manual_model:bool = True
        defaults:Defaults = Defaults()
    
    def __init__(self, model=None, **kwargs):
        self.model_name = model
        super().__init__(**kwargs)

    @property
    def experimental(self):
        return EXPERIMENTAL_DESCRIPTION

    def set_client(self, **kwargs):
        self.api_key = kwargs.get("api_key")
        self.client = AsyncOpenAI(base_url=self.api_url+"/v1", api_key=self.api_key)
        self.model_name = kwargs.get("model") or kwargs.get("model_name") or self.model_name
        
    def tune_prompt_parameters(self, parameters:dict, kind:str):
        super().tune_prompt_parameters(parameters, kind)
        
        keys = list(parameters.keys())
        
        valid_keys = ["temperature", "top_p"]
        
        for key in keys:
            if key not in valid_keys:
                del parameters[key]
        
        
    async def get_model_name(self):
        
        try:
            model_name = await super().get_model_name()
        except NotFoundError as e:
            # api does not implement model listing
            return self.model_name
        except Exception as e:
            self.log.error("get_model_name error", e=e)
            return self.model_name

        # model name may be a file path, so we need to extract the model name
        # the path could be windows or linux so it needs to handle both backslash and forward slash
        
        is_filepath = "/" in model_name
        is_filepath_windows = "\\" in model_name
        
        if is_filepath or is_filepath_windows:
            model_name = model_name.replace("\\", "/").split("/")[-1]

        return model_name

    async def generate(self, prompt:str, parameters:dict, kind:str):
        
        """
        Generates text from the given prompt and parameters.
        """
        human_message = {'role': 'user', 'content': prompt.strip()}
        
        self.log.debug("generate", prompt=prompt[:128]+" ...", parameters=parameters)
        
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
            emit("status", message="Error during generation (check logs)", status="error")
            return ""

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
        if "api_url" in kwargs:
            self.api_url = kwargs["api_url"]
        if "max_token_length" in kwargs:
            self.max_token_length = kwargs["max_token_length"]
        if "api_key" in kwargs:
            self.api_auth = kwargs["api_key"]
        
        self.set_client(**kwargs)