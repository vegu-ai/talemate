from talemate.client.base import ClientBase
from talemate.client.registry import register

from openai import AsyncOpenAI


@register()
class LMStudioClient(ClientBase):
    
    client_type = "lmstudio"
    conversation_retries = 5

    def set_client(self):
        self.client = AsyncOpenAI(base_url=self.api_url+"/v1", api_key="sk-1111")
        
    def tune_prompt_parameters(self, parameters:dict, kind:str):
        super().tune_prompt_parameters(parameters, kind)
        
        keys = list(parameters.keys())
        
        valid_keys = ["temperature", "top_p"]
        
        for key in keys:
            if key not in valid_keys:
                del parameters[key]
        
        
    async def get_model_name(self):
        model_name = await super().get_model_name()

        # model name comes back as a file path, so we need to extract the model name
        # the path could be windows or linux so it needs to handle both backslash and forward slash
        
        if model_name:
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
        except Exception as e:
            self.log.error("generate error", e=e)
            return ""