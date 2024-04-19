import random
import re

import httpx
import structlog
from openai import AsyncOpenAI

from talemate.client.base import STOPPING_STRINGS, ClientBase
from talemate.client.registry import register

log = structlog.get_logger("talemate.client.textgenwebui")


@register()
class TextGeneratorWebuiClient(ClientBase):
    auto_determine_prompt_template: bool = True
    finalizers: list[str] = [
        "finalize_llama3",
        "finalize_YI",
    ]

    client_type = "textgenwebui"

    class Meta(ClientBase.Meta):
        name_prefix: str = "TextGenWebUI"
        title: str = "Text-Generation-WebUI (ooba)"

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)
        parameters["stopping_strings"] = STOPPING_STRINGS + parameters.get(
            "extra_stopping_strings", []
        )
        # is this needed?
        parameters["max_new_tokens"] = parameters["max_tokens"]
        parameters["stop"] = parameters["stopping_strings"]


    def set_client(self, **kwargs):
        self.client = AsyncOpenAI(base_url=self.api_url + "/v1", api_key="sk-1111")

    def finalize_llama3(self, parameters:dict, prompt:str) -> tuple[str, bool]:
        
        if "<|eot_id|>" not in prompt:
            return prompt, False
        
        # llama3 instruct models need to add  "<|eot_id|>", "<|end_of_text|>" to the stopping strings
        parameters["stopping_strings"] += ["<|eot_id|>", "<|end_of_text|>"]
        
        # also needs to add `skip_special_tokens`= False to the parameters
        parameters["skip_special_tokens"] = False
        log.debug("finalizing llama3 instruct parameters", parameters=parameters)

        if prompt.endswith("<|end_header_id|>"):
            # append two linebreaks
            prompt += "\n\n"
            log.debug("adjusting llama3 instruct prompt: missing linebreaks")
            
        return prompt, True
    
    def finalize_YI(self, parameters:dict, prompt:str) -> tuple[str, bool]:
        model_name = self.model_name.lower()
        # regex match for yi encased by non-word characters
        if not bool(re.search(r"[\-_]yi[\-_]", model_name)):
            return prompt, False
        
        parameters["smoothing_factor"] = 0.1
        # also half the temperature
        parameters["temperature"] = max(0.1, parameters["temperature"] / 2)
        log.debug(
            "finalizing YI parameters",
            parameters=parameters,
        )
        return prompt, True
    
    async def get_model_name(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_url}/v1/internal/model/info", timeout=2
            )
        if response.status_code == 404:
            raise Exception("Could not find model info (wrong api version?)")
        response_data = response.json()
        model_name = response_data.get("model_name")

        if model_name == "None":
            model_name = None

        return model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        headers = {}
        headers["Content-Type"] = "application/json"

        parameters["prompt"] = prompt.strip(" ")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/v1/completions",
                json=parameters,
                timeout=None,
                headers=headers,
            )
            response_data = response.json()
            return response_data["choices"][0]["text"]

    def jiggle_randomness(self, prompt_config: dict, offset: float = 0.3) -> dict:
        """
        adjusts temperature and repetition_penalty
        by random values using the base value as a center
        """

        temp = prompt_config["temperature"]
        rep_pen = prompt_config["repetition_penalty"]

        min_offset = offset * 0.3

        prompt_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
        prompt_config["repetition_penalty"] = random.uniform(
            rep_pen + min_offset * 0.3, rep_pen + offset * 0.3
        )
