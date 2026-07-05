"""
Shared pieces for clients that expose the `api_handles_prompt_template`
config flag, which routes generation through the remote API's own
prompt-template rendering (chat-style) instead of Talemate's local
prompt template.
"""

import pydantic

from .base import ExtraField

__all__ = [
    "ApiHandlesPromptTemplateConfig",
    "ApiHandlesPromptTemplateMixin",
    "api_handles_prompt_template_extra_fields",
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
