import pydantic
from openai import AsyncOpenAI

from talemate.client.base import ClientBase, ParameterReroute, CommonDefaults
from talemate.client.registry import register


class Defaults(CommonDefaults, pydantic.BaseModel):
    api_url: str = "http://localhost:1234"
    max_token_length: int = 8192


@register()
class LMStudioClient(ClientBase):
    auto_determine_prompt_template: bool = True
    client_type = "lmstudio"

    class Meta(ClientBase.Meta):
        name_prefix: str = "LMStudio"
        title: str = "LMStudio"
        defaults: Defaults = Defaults()

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            ParameterReroute(
                talemate_parameter="stopping_strings", client_parameter="stop"
            ),
        ]

    def set_client(self, **kwargs):
        self.client = AsyncOpenAI(base_url=self.api_url + "/v1", api_key="sk-1111")

    def reconfigure(self, **kwargs):
        super().reconfigure(**kwargs)
        
        if self.client and self.client.base_url != self.api_url:
            self.set_client()

    async def get_model_name(self):
        model_name = await super().get_model_name()
        
        # model name comes back as a file path, so we need to extract the model name
        # the path could be windows or linux so it needs to handle both backslash and forward slash

        if model_name:
            model_name = model_name.replace("\\", "/").split("/")[-1]

        return model_name

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
        except Exception as e:
            self.log.error("generate error", e=e)
            return ""
