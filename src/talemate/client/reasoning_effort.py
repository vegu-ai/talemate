from typing import Literal

import pydantic

from .base import ExtraField, FieldGroup, ReasoningDisplay
from .context import client_context_attribute
from .effort import EFFORT_LEVELS, EffortLevel

__all__ = [
    "COMPLETION_TOKEN_PARAMETER_CHOICES",
    "EFFORT_FORMAT_CHOICES",
    "EFFORT_LEVELS",
    "EffortLevel",
    "ReasoningEffortConfig",
    "ReasoningEffortMixin",
    "reasoning_effort_extra_fields",
]

EffortFormat = Literal["none", "reasoning_effort", "reasoning"]

EFFORT_FORMAT_CHOICES = [
    {
        "label": "none",
        "value": "none",
        "description": "Sends no effort field; the server uses its own default.",
    },
    {
        "label": "reasoning_effort",
        "value": "reasoning_effort",
        "description": 'Sends "reasoning_effort": "<effort>" (OpenAI, llama.cpp, most servers).',
    },
    {
        "label": "reasoning",
        "value": "reasoning",
        "description": 'Sends "reasoning": {"effort": "<effort>"} (OpenRouter-style servers).',
    },
]

COMPLETION_TOKEN_PARAMETER_CHOICES = [
    {
        "label": "max_tokens",
        "value": "max_tokens",
        "description": "The traditional limit; most servers and text completions.",
    },
    {
        "label": "max_completion_tokens",
        "value": "max_completion_tokens",
        "description": "OpenAI chat completions and servers that require it.",
    },
]

EFFORT_LEVEL_DESCRIPTIONS = {
    "default": "Sends no effort setting; the model decides.",
    "none": "Asks for no reasoning, where the model supports it.",
}


class ReasoningEffortConfig(pydantic.BaseModel):
    effort_level: EffortLevel = "default"


def reasoning_effort_extra_fields() -> dict[str, ExtraField]:
    return {
        "effort_level": ExtraField(
            name="effort_level",
            type="text",
            label="Reasoning Effort",
            choices=[
                {
                    "label": level,
                    "value": level,
                    **(
                        {"description": EFFORT_LEVEL_DESCRIPTIONS[level]}
                        if level in EFFORT_LEVEL_DESCRIPTIONS
                        else {}
                    ),
                }
                for level in EFFORT_LEVELS
            ],
            description="Controls reasoning depth. Supported levels depend on the model. 'default' sends no effort setting; 'none' requests no reasoning where supported. Unsupported levels may be rejected by the server. Sent only while Reasoning is on.",
            group=FieldGroup(name="reasoning", label="Reasoning", icon="mdi-brain"),
            required=False,
        ),
    }


class ReasoningEffortMixin:
    @property
    def effort_level(self) -> EffortLevel:
        return self.client_config.effort_level

    @property
    def reasoning_effort_format(self) -> EffortFormat:
        return "reasoning_effort"

    @property
    def reasoning_effort_configured(self) -> EffortLevel | None:
        if (
            not self.reason_enabled_configured
            or self.reasoning_effort_format == "none"
            or self.effort_level == "default"
        ):
            return None
        return self.effort_level

    @property
    def reasoning_effort(self) -> EffortLevel | None:
        if self.reasoning_disabled_for_action:
            return None
        requested = client_context_attribute("reasoning_effort")
        if (
            requested
            and self.reason_enabled_configured
            and self.reasoning_effort_format != "none"
        ):
            return None if requested == "default" else requested
        return self.reasoning_effort_configured

    @property
    def reasoning_display(self) -> ReasoningDisplay | None:
        if not self.reason_enabled_configured:
            return None
        if self.reasoning_effort_format == "none":
            return ReasoningDisplay(control="tokens")
        return ReasoningDisplay(control="effort", effort_choices=EFFORT_LEVELS)
