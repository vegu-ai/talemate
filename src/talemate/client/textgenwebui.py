import random
import re
import json
import sseclient
import requests
import asyncio
import httpx
import pydantic
import structlog
from openai import AsyncOpenAI

from talemate.client.api_handles import (
    ApiHandlesPromptTemplateConfig,
    ApiHandlesPromptTemplateMixin,
    api_handles_prompt_template_extra_fields,
)
from talemate.client.base import STOPPING_STRINGS, ClientBase, Defaults
from talemate.client.registry import register
from talemate.client.vision import VisionConfig, vision_extra_fields, OpenAIVisionMixin
from talemate.config.schema import Client as BaseClientConfig

log = structlog.get_logger("talemate.client.textgenwebui")


class TextGeneratorWebuiClientDefaults(Defaults, ApiHandlesPromptTemplateConfig):
    api_key: str = ""


class ClientConfig(ApiHandlesPromptTemplateConfig, VisionConfig, BaseClientConfig):
    pass


@register()
class TextGeneratorWebuiClient(
    ApiHandlesPromptTemplateMixin, OpenAIVisionMixin, ClientBase
):
    auto_determine_prompt_template: bool = True
    remote_model_locked: bool = True
    finalizers: list[str] = [
        "finalize_llama3",
        "finalize_YI",
    ]

    client_type = "textgenwebui"
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "TextGenWebUI"
        title: str = "Text-Generation-WebUI (ooba)"
        enable_api_auth: bool = True
        defaults: TextGeneratorWebuiClientDefaults = TextGeneratorWebuiClientDefaults()
        self_hosted: bool = True
        extra_fields: dict = pydantic.Field(
            default_factory=lambda: {
                **api_handles_prompt_template_extra_fields(
                    description="Requests go to the chat/completions API and text-generation-webui applies the model's prompt template, and the prompt template selection below is ignored. Response pre-filling keeps working. Keep this disabled for full control of the prompt template in Talemate; enable it to trust that the template on the remote end is correct.",
                ),
                **vision_extra_fields(),
            }
        )

    @property
    def requires_reasoning_pattern(self) -> bool:
        # in chat mode the API separates reasoning into reasoning_content
        # deltas, which are captured during streaming
        return not self.api_handles_prompt_template

    def make_client(self) -> AsyncOpenAI:
        api_key = self.api_key or "sk-1234"
        base = self.api_url.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return AsyncOpenAI(base_url=base, api_key=api_key)

    @property
    def request_headers(self):
        headers = {}
        headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def supported_parameters(self):
        # textgenwebui does not error on unsupported parameters
        # but we should still drop them so they don't get passed to the API
        # and show up in our prompt debugging tool.

        # note that this is not the full list of their supported parameters
        # but only those we send.
        return [
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "frequency_penalty",
            "presence_penalty",
            "repetition_penalty",
            "repetition_penalty_range",
            "stopping_strings",
            "skip_special_tokens",
            "max_tokens",
            "stream",
            "do_sample",
            # arethese needed?
            "max_new_tokens",
            "stop",
            "xtc_threshold",
            "xtc_probability",
            "dry_multiplier",
            "dry_base",
            "dry_allowed_length",
            "dry_sequence_breakers",
            "smoothing_factor",
            "smoothing_curve",
            # talemate internal
            # These will be removed before sending to the API
            # but we keep them here since they are used during the prompt finalization
            "extra_stopping_strings",
        ]

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)
        parameters["stopping_strings"] = STOPPING_STRINGS + parameters.get(
            "extra_stopping_strings", []
        )
        # is this needed?
        parameters["max_new_tokens"] = parameters["max_tokens"]
        parameters["stop"] = parameters["stopping_strings"]

        # if min_p is set, do_sample should be True
        if parameters.get("min_p"):
            parameters["do_sample"] = True

    def finalize_llama3(self, parameters: dict, prompt: str) -> tuple[str, bool]:
        # TODO: cruft that can be removed
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

    def finalize_YI(self, parameters: dict, prompt: str) -> tuple[str, bool]:
        # TODO: cruft that can be removed
        if not self.model_name:
            return prompt, False

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
                f"{self.api_url}/v1/internal/model/info",
                timeout=self.status_request_timeout,
                headers=self.request_headers,
            )
        if response.status_code == 404:
            raise Exception("Could not find model info (wrong api version?)")
        response_data = response.json()
        model_name = response_data.get("model_name")

        if model_name == "None":
            model_name = None

        return model_name

    async def abort_generation(self):
        """
        Trigger the stop generation endpoint
        """
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.api_url}/v1/internal/stop-generation",
                headers=self.request_headers,
            )

    async def generate(self, prompt: str, parameters: dict, kind: str):
        loop = asyncio.get_event_loop()
        if self.api_handles_prompt_template:
            # assemble on the event loop - the executor thread cannot see the
            # active_scene contextvar, which would drop persona instructions
            messages, coercion_prompt = self.chat_messages_for_coercion(prompt, kind)
            return await loop.run_in_executor(
                None, self._generate_chat, messages, coercion_prompt, parameters
            )
        return await loop.run_in_executor(
            None, self._generate, prompt, parameters, kind
        )

    def _generate_chat(
        self, messages: list[dict], coercion_prompt: str | None, parameters: dict
    ):
        """
        Generates text via the chat/completions endpoint, letting
        text-generation-webui apply the model's prompt template. Coercion is
        passed as a partial assistant message that the API continues via its
        `continue_` parameter.
        """
        if coercion_prompt:
            parameters["continue_"] = True

        parameters["mode"] = "instruct"
        parameters["messages"] = messages
        parameters["stream"] = True

        response = ""
        reasoning_response = ""
        stream_response = requests.post(
            f"{self.api_url}/v1/chat/completions",
            json=parameters,
            timeout=None,
            headers=self.request_headers,
            stream=True,
        )
        stream_response.raise_for_status()

        sse = sseclient.SSEClient(stream_response)

        for event in sse.events():
            if event.data == "[DONE]":
                break
            payload = json.loads(event.data)
            delta = payload["choices"][0]["delta"]
            reasoning_chunk = delta.get("reasoning_content") or ""
            if reasoning_chunk:
                reasoning_response += reasoning_chunk
                self.update_request_tokens(self.count_tokens(reasoning_chunk))
            chunk = delta.get("content") or ""
            response += chunk
            self.update_request_tokens(self.count_tokens(chunk))

        if reasoning_response:
            self._reasoning_response = reasoning_response

        # the API echoes the coercion pre-fill back at the start of the
        # response - strip it so coerced responses match the completions
        # endpoint behavior (continuation only)
        if coercion_prompt and response.startswith(coercion_prompt):
            response = response[len(coercion_prompt) :]

        return response

    def _generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """
        parameters["prompt"] = prompt.strip(" ")

        response = ""
        parameters["stream"] = True
        stream_response = requests.post(
            f"{self.api_url}/v1/completions",
            json=parameters,
            timeout=None,
            headers=self.request_headers,
            stream=True,
        )
        stream_response.raise_for_status()

        sse = sseclient.SSEClient(stream_response)

        for event in sse.events():
            if event.data == "[DONE]":
                break
            payload = json.loads(event.data)
            chunk = payload["choices"][0]["text"]
            response += chunk
            self.update_request_tokens(self.count_tokens(chunk))

        return response

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
