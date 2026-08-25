import pydantic
from openai import AsyncOpenAI

from talemate.client.base import (
    ClientBase,
    ParameterReroute,
    CommonDefaults,
)
from talemate.client.model_probe import OpenAIModelListProbeMixin
from talemate.client.registry import register

# LMStudio defers parameter semantics to the OpenAI API reference, which
# documents up to 4 stop sequences.
MAX_STOPPING_STRINGS = 4


class Defaults(CommonDefaults, pydantic.BaseModel):
    api_url: str = "http://localhost:1234"
    max_token_length: int = 8192


@register()
class LMStudioClient(OpenAIModelListProbeMixin, ClientBase):
    auto_determine_prompt_template: bool = True
    client_type = "lmstudio"
    remote_model_locked: bool = True

    class Meta(ClientBase.Meta):
        name_prefix: str = "LMStudio"
        title: str = "LMStudio"
        defaults: Defaults = Defaults()
        self_hosted: bool = True

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

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)

        # warn=False: with only 4 slots any scene with a couple of other
        # characters overflows on every conversation generation, and the user
        # has nothing to act on
        parameters["stopping_strings"] = self.build_stopping_strings(
            parameters, cap=MAX_STOPPING_STRINGS, warn=False
        )

    @property
    def api_key(self):
        # LMStudio doesn't currently support API keys so we'll just use a dummy key
        # since the openai client requires it.
        return "sk-1234"

    def make_client(self):
        return AsyncOpenAI(base_url=self.require_api_url_v1(), api_key=self.api_key)

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters using a streaming
        request so that token usage can be tracked incrementally via
        `update_request_tokens`.
        """

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
        )

        client = self.make_client()

        # Send the request in streaming mode so we can update token counts
        stream = await client.completions.create(
            model=self.model_name,
            prompt=prompt,
            stream=True,
            **parameters,
        )

        response = ""

        # Iterate over streamed chunks and accumulate the response while
        # incrementally updating the token counter
        async for chunk in stream:
            if not chunk.choices:
                continue
            content_piece = chunk.choices[0].text
            response += content_piece
            # Track token usage incrementally
            self.update_request_tokens(self.count_tokens(content_piece))

        # Store overall token accounting once the stream is finished
        self._returned_prompt_tokens = self.prompt_tokens(prompt)
        self._returned_response_tokens = self.response_tokens(response)

        return response

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def response_tokens(self, response: str):
        """Count tokens in a model response string."""
        return self.count_tokens(response)

    def prompt_tokens(self, prompt: str):
        """Count tokens in a prompt string."""
        return self.count_tokens(prompt)
