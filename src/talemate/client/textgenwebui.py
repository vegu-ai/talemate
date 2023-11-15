from talemate.client.base import ClientBase, STOPPING_STRINGS
from talemate.client.registry import register
from openai import AsyncOpenAI
import httpx
import copy
import random


@register()
class TextGeneratorWebuiClient(ClientBase):
    
    client_type = "textgenwebui"
    
    def tune_prompt_parameters(self, parameters:dict, kind:str):
        super().tune_prompt_parameters(parameters, kind)
        parameters["stopping_strings"] = STOPPING_STRINGS

    def set_client(self):
        self.client = AsyncOpenAI(base_url=self.api_url+"/v1", api_key="sk-1111")
    
    async def get_model_name(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.api_url}/v1/internal/model/info", timeout=2)
        response_data = response.json()
        model_name = response_data.get("model_name")
        return model_name
    
    
    async def generate(self, prompt:str, parameters:dict, kind:str):
        
        """
        Generates text from the given prompt and parameters.
        """
        
        headers = {}
        headers["Content-Type"] = "application/json"
        
        parameters["prompt"] = prompt
        
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.api_url}/v1/completions", json=parameters, timeout=None, headers=headers)
            response_data = response.json()
            return response_data["choices"][0]["text"]
        
    def jiggle_randomness(self, prompt_config:dict, offset:float=0.3) -> dict:
        """
        adjusts temperature and repetition_penalty
        by random values using the base value as a center
        """
        
        temp = prompt_config["temperature"]
        rep_pen = prompt_config["repetition_penalty"]
        
        copied_config = copy.deepcopy(prompt_config)
        
        min_offset = offset * 0.3

        copied_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
        copied_config["repetition_penalty"] = random.uniform(rep_pen + min_offset * 0.3, rep_pen + offset * 0.3)
        
        return copied_config