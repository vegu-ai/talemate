import json

import pydantic
import structlog
import httpx
from openai import AsyncOpenAI

from talemate.client.base import (
    STOPPING_STRINGS,
    ClientBase,
    CommonDefaults,
    ParameterReroute,
)
from talemate.client.registry import register
from talemate.exceptions import GenerationProcessingError

log = structlog.get_logger("talemate.client.llamacpp")


class Defaults(CommonDefaults, pydantic.BaseModel):
    # llama.cpp `llama-server` defaults to port 8080 (see ggml-org/llama.cpp README)
    api_url: str = "http://localhost:8080"
    max_token_length: int = 8192


@register()
class LlamaCppClient(ClientBase):
    """
    Client for ggml-org/llama.cpp `llama-server`.

    This client uses llama.cpp's richer, non-OpenAI endpoint:
      POST /completion

    (The server also offers OpenAI-compatible endpoints under /v1, which we
    still use for model discovery via /v1/models.)
    """

    auto_determine_prompt_template: bool = True
    client_type = "llamacpp"
    remote_model_locked: bool = True

    class Meta(ClientBase.Meta):
        name_prefix: str = "llama.cpp"
        title: str = "llama.cpp"
        enable_api_auth: bool = True
        defaults: Defaults = Defaults()
        self_hosted: bool = True

    @property
    def supported_parameters(self):
        # Talemate inference params (see config.schema.InferenceParameters) that
        # we can map to llama.cpp /completion options.
        return [
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "presence_penalty",
            "frequency_penalty",
            "xtc_threshold",
            "xtc_probability",
            "dry_multiplier",
            "dry_base",
            "dry_allowed_length",
            "dry_sequence_breakers",
            "stop",
            "adaptive_target",
            "adaptive_decay",
            ParameterReroute(
                talemate_parameter="repetition_penalty",
                client_parameter="repeat_penalty",
            ),
            ParameterReroute(
                talemate_parameter="repetition_penalty_range",
                client_parameter="repeat_last_n",
            ),
            ParameterReroute(
                talemate_parameter="max_tokens", client_parameter="n_predict"
            ),
        ]

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)

        # Feed llama.cpp stop strings explicitly so generation halts early.
        # extra_stopping_strings is injected by Talemate (e.g. conversation agent).
        stop = STOPPING_STRINGS + parameters.get("extra_stopping_strings", [])
        parameters["stop"] = stop

        # We always stream in generate() (to track incremental tokens), so remove
        # any upstream stream flag to avoid confusion in debugging.
        if "stream" in parameters:
            parameters.pop("stream", None)

    @property
    def request_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _base_url_v1(self) -> str | None:
        if not self.api_url:
            return None
        base = self.api_url.strip().rstrip("/")
        if base.endswith("/v1"):
            return base
        return base + "/v1"

    def make_client(self) -> AsyncOpenAI:
        # OpenAI SDK requires an api_key. llama.cpp may ignore auth; if the user
        # didn't configure a key, use a dummy value (same idea as LMStudioClient).
        api_key = self.api_key or "sk-1234"
        return AsyncOpenAI(base_url=self._base_url_v1(), api_key=api_key)

    async def get_model_name(self):
        if not self.api_url:
            return None

        client = self.make_client()
        models = await client.models.list(timeout=self.status_request_timeout)
        try:
            model_name = models.data[0].id
        except IndexError:
            return None

        # model id can be a file path; normalize to basename (windows or linux)
        if model_name:
            model_name = model_name.replace("\\", "/").split("/")[-1]

        return model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generate text using llama.cpp's POST /completion endpoint in streaming
        mode so token usage can be tracked incrementally via
        `update_request_tokens`.
        """

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
        )

        # Map Talemate settings into llama.cpp /completion payload.
        # The prompt already includes any prompt templating done by Talemate.
        payload = {k: v for k, v in parameters.items() if v is not None}
        payload["prompt"] = prompt.strip(" ")
        payload["stream"] = True

        # dry_sequence_breakers in Talemate presets is stored as a string like:
        #   '"\\n", ":", "\\\"", "*"'
        # llama.cpp expects an array of strings.
        dsb = payload.get("dry_sequence_breakers")
        if isinstance(dsb, str):
            try:
                payload["dry_sequence_breakers"] = json.loads(f"[{dsb}]")
            except Exception:
                # Fall back to a conservative default on parse errors
                payload["dry_sequence_breakers"] = ["\n", ":", '"', "*"]

        try:
            response = ""
            base = self.api_url.strip().rstrip("/")
            url = f"{base}/completion"

            async with httpx.AsyncClient(timeout=None) as http:
                async with http.stream(
                    "POST",
                    url,
                    json=payload,
                    headers=self.request_headers,
                ) as r:
                    if r.status_code >= 400:
                        # llama.cpp returns OAI-style errors (see tools/server/README.md).
                        raw_body = await r.aread()
                        message = None
                        try:
                            data = json.loads(
                                raw_body.decode("utf-8", errors="replace")
                            )
                            message = (data.get("error") or {}).get("message") or (
                                data.get("error") or {}
                            ).get("type")
                        except Exception:
                            pass

                        if r.status_code in (401, 403):
                            raise GenerationProcessingError(
                                f"llama.cpp API: Invalid API key ({r.status_code})"
                                + (f" - {message}" if message else "")
                            )

                        raise GenerationProcessingError(
                            f"llama.cpp API error ({r.status_code})"
                            + (f" - {message}" if message else "")
                        )
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[len("data:") :].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            evt = json.loads(raw)
                        except Exception:
                            continue

                        piece = evt.get("content")
                        if piece:
                            response += piece
                            self.update_request_tokens(self.count_tokens(piece))

                        if evt.get("stop") is True:
                            # Don't break immediately; let the server finish the SSE stream
                            # cleanly (avoids noisy generator-close warnings in some runtimes).
                            continue

                    # If we saw a stop event but didn't receive [DONE], the server will still
                    # close the response; exiting the context will clean up the connection.

            # Store overall token accounting once the stream is finished
            self._returned_prompt_tokens = self.prompt_tokens(prompt)
            self._returned_response_tokens = self.response_tokens(response)

            return response
        except GenerationProcessingError:
            raise
        except Exception as e:
            self.log.error("generate error", e=e)
            return ""

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def response_tokens(self, response: str):
        return self.count_tokens(response)

    def prompt_tokens(self, prompt: str):
        return self.count_tokens(prompt)
