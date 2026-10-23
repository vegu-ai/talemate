import pydantic

from .base import ExtraField
from .toggleable_parameters import PARAMETERS_FIELD_GROUP

__all__ = ["StreamingConfig", "streaming_extra_fields"]


class StreamingConfig(pydantic.BaseModel):
    stream: bool = True


def streaming_extra_fields() -> dict[str, ExtraField]:
    return {
        "stream": ExtraField(
            name="stream",
            type="bool",
            label="Stream",
            description="Stream responses as they arrive. Disable if your organization or server does not support streaming for the selected model.",
            group=PARAMETERS_FIELD_GROUP,
            required=False,
        )
    }
