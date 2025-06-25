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
        Generates text from the given prompt and parameters using a streaming
        request so that token usage can be tracked incrementally via
        `update_request_tokens`.
        """

        prompt, coercion_prompt = self.split_prompt_for_coercion(prompt)
        
        # Prepare messages for chat completion
        messages = [
            {"role": "system", "content": self.get_system_message(kind)},
            {"role": "user", "content": prompt.strip()}
        ]
        
        if coercion_prompt:
            messages.append({"role": "assistant", "content": coercion_prompt.strip()})

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
        )

        try:
            # Send the request in streaming mode so we can update token counts
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=True,
                **parameters,
            )

            response = ""

            # Iterate over streamed chunks and accumulate the response while
            # incrementally updating the token counter
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content_piece = chunk.choices[0].delta.content
                    response += content_piece
                    # Track token usage incrementally
                    self.update_request_tokens(self.count_tokens(content_piece))

            # Store overall token accounting once the stream is finished
            self._returned_prompt_tokens = self.prompt_tokens(messages)
            self._returned_response_tokens = self.response_tokens(response)

            return response
        except Exception as e:
            self.log.error("generate error", e=e)
            return ""

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def response_tokens(self, response: str):
        """Count tokens in a model response string."""
        return self.count_tokens(response)

    def prompt_tokens(self, prompt):
        """Count tokens in a prompt string or messages list."""
        if isinstance(prompt, list):
            # For messages format, concatenate all content
            text = ""
            for msg in prompt:
                text += msg.get("content", "") + " "
            return self.count_tokens(text.strip())
        return self.count_tokens(prompt)
