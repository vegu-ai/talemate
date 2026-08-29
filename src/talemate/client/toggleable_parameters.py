"""
Shared pieces for clients that expose per-parameter `send_*` toggles for
sampler parameters. Some APIs hard-error when they receive a parameter
they don't support for the selected model, so a disabled parameter needs
to be omitted from the request payload entirely (not just zeroed out).
"""

import pydantic

from .base import ExtraField, FieldGroup

__all__ = [
    "PARAMETERS_FIELD_GROUP",
    "ToggleableParametersMixin",
    "toggleable_parameters_config",
    "toggleable_parameters_extra_fields",
]


PARAMETERS_FIELD_GROUP = FieldGroup(
    name="parameters",
    label="Parameters",
    description=(
        "Toggle individual sampler parameters. When a parameter is disabled it is "
        "omitted from the request payload entirely. Useful for APIs that hard-error "
        "when receiving parameters they don't support for the selected model."
    ),
    icon="mdi-tune-vertical",
)


def _send_parameter_field(param: str) -> ExtraField:
    return ExtraField(
        name=f"send_{param}",
        type="bool",
        label=f"Send {param}",
        required=False,
        description=(
            f"When enabled, `{param}` is included in the request. Disable for "
            f"models/APIs that reject it."
        ),
        group=PARAMETERS_FIELD_GROUP,
    )


def toggleable_parameters_extra_fields(
    params: tuple[str, ...],
) -> dict[str, ExtraField]:
    return {f"send_{p}": _send_parameter_field(p) for p in params}


def toggleable_parameters_config(params: tuple[str, ...]) -> type[pydantic.BaseModel]:
    """
    Build a pydantic model with a `send_<param>: bool = True` field per
    parameter, for use as a base of a client's Defaults / ClientConfig.
    """
    return pydantic.create_model(
        "ToggleableParametersConfig",
        **{f"send_{p}": (bool, True) for p in params},
    )


class ToggleableParametersMixin:
    """
    Provides `supported_parameters` filtered by the `send_*` config flags,
    plus client-level `send_<param>` accessor properties — the client status
    payload reads extra-field values off the client instance
    (ClientBase._common_status_data / populate_extra_fields), and the frontend
    falls back to the Meta defaults for missing values, so without these the
    toggles would render as enabled and be reverted on the next save.

    Set `toggleable_parameters` on the client class; mix in before ClientBase.
    """

    toggleable_parameters: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for param in cls.toggleable_parameters:
            field_name = f"send_{param}"
            if not hasattr(cls, field_name):
                setattr(
                    cls,
                    field_name,
                    property(
                        lambda self, _field_name=field_name: getattr(
                            self.client_config, _field_name
                        )
                    ),
                )

    @property
    def supported_parameters(self):
        return [
            param
            for param in self.toggleable_parameters
            if getattr(self.client_config, f"send_{param}")
        ] + ["max_tokens"]
