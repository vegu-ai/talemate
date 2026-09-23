from typing import Literal, get_args

import pydantic

from .base import ExtraField, FieldGroup, ReasoningDisplay


EffortLevel = Literal[
    "default", "none", "minimal", "low", "medium", "high", "xhigh", "max"
]
EFFORT_LEVELS = list(get_args(EffortLevel))
EffortFormat = Literal["none", "reasoning_effort", "reasoning"]


class ReasoningEffortConfig(pydantic.BaseModel):
    effort_level: EffortLevel = "default"


def reasoning_effort_extra_fields() -> dict[str, ExtraField]:
    return {
        "effort_level": ExtraField(
            name="effort_level",
            type="text",
            label="Reasoning Effort",
            choices=EFFORT_LEVELS,
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
        return self.reasoning_effort_configured

    @property
    def reasoning_display(self) -> ReasoningDisplay | None:
        if not self.reason_enabled_configured:
            return None
        if self.reasoning_effort_format == "none":
            return ReasoningDisplay(show_token_slider=True)
        return ReasoningDisplay(
            show_token_slider=False,
            show_effort_selector=True,
            effort_choices=EFFORT_LEVELS,
        )
