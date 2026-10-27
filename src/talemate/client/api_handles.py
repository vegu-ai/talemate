"""
Shared pieces for clients that expose the `api_handles_prompt_template`
config flag, which routes generation through the remote API's own
prompt-template rendering (chat-style) instead of Talemate's local
prompt template.
"""

import pydantic

from talemate.exceptions import ReasoningResponseError

from .base import ExtraField

__all__ = [
    "ApiHandlesPromptTemplateConfig",
    "ApiHandlesPromptTemplateMixin",
    "ChatReasoningMixin",
    "api_handles_prompt_template_extra_fields",
    "strip_echoed_prefill",
]


class ApiHandlesPromptTemplateConfig(pydantic.BaseModel):
    api_handles_prompt_template: bool = False


def api_handles_prompt_template_extra_fields(
    description: str,
    label: str = "API handles prompt template (chat/completions)",
) -> dict[str, ExtraField]:
    return {
        "api_handles_prompt_template": ExtraField(
            name="api_handles_prompt_template",
            type="bool",
            label=label,
            required=False,
            description=description,
        ),
    }


class ApiHandlesPromptTemplateMixin:
    """
    Provides the `api_handles_prompt_template` flag property and bypasses
    local prompt-template rendering when the API applies the model's own
    template. Mix in before ClientBase.
    """

    @property
    def api_handles_prompt_template(self) -> bool:
        return self.client_config.api_handles_prompt_template

    def prompt_template(self, system_message: str, prompt: str):
        if self.api_handles_prompt_template:
            return prompt
        return super().prompt_template(system_message, prompt)


def strip_echoed_prefill(content: str, coercion_prompt: str | None) -> str:
    """Some chat APIs (llama.cpp, text-generation-webui) return a continued
    pre-fill together with the continuation; the caller expects the
    continuation only."""
    if coercion_prompt and content.startswith(coercion_prompt):
        return content[len(coercion_prompt) :]
    return content


class ChatReasoningMixin:
    """
    In chat mode a server may return the reasoning in its own field or leave
    it in the content, depending on whether it recognised the model's
    reasoning tags. The strip pattern is skipped only when the reasoning
    arrived separately; a missing pattern only fails when reasoning is known
    to have started (a validation pattern or a reason prefill). Mix in before
    ClientBase.
    """

    def strip_reasoning(self, response: str) -> tuple[str, str | None]:
        if not self.api_handles_prompt_template:
            return super().strip_reasoning(response)
        if self._reasoning_response:
            return response, None
        try:
            return super().strip_reasoning(response)
        except ReasoningResponseError:
            if self.reason_prefill or self.reason_validation_pattern:
                raise
            return response, None
