"""
Shared pieces for clients that expose per-parameter `send_*` toggles for
sampler parameters. Some APIs hard-error when they receive a parameter
they don't support for the selected model, so a disabled parameter needs
to be omitted from the request payload entirely (not just zeroed out).
"""

import pydantic

from .base import ExtraField, FieldGroup, ParameterReroute

__all__ = [
    "PARAMETERS_FIELD_GROUP",
    "ParameterSet",
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


class ParameterSet(pydantic.BaseModel):
    """
    Parameters that act as one sampler and share a single `send_<name>` toggle.
    """

    name: str
    parameters: tuple[str, ...]
    label: str
    description: str


def parameter_name(param: str | ParameterReroute) -> str:
    return param.talemate_parameter if isinstance(param, ParameterReroute) else param


def toggle_name(
    param: str | ParameterReroute, sets: tuple[ParameterSet, ...] = ()
) -> str:
    name = parameter_name(param)
    return next((s.name for s in sets if name in s.parameters), name)


def toggle_names(
    params: tuple[str | ParameterReroute, ...],
    sets: tuple[ParameterSet, ...] = (),
) -> list[str]:
    names = []
    for param in params:
        name = toggle_name(param, sets)
        if name not in names:
            names.append(name)
    return names


def _send_parameter_field(
    name: str, label: str, description: str, group: FieldGroup
) -> ExtraField:
    return ExtraField(
        name=f"send_{name}",
        type="bool",
        label=label,
        required=False,
        description=description,
        group=group,
    )


def toggleable_parameters_extra_fields(
    params: tuple[str | ParameterReroute, ...],
    sets: tuple[ParameterSet, ...] = (),
    *,
    group: FieldGroup = PARAMETERS_FIELD_GROUP,
    descriptions: dict[str, str] | None = None,
) -> dict[str, ExtraField]:
    descriptions = descriptions or {}
    fields = {}
    for name in toggle_names(params, sets):
        parameter_set = next((s for s in sets if s.name == name), None)
        if parameter_set:
            label, description = parameter_set.label, parameter_set.description
        else:
            label = f"Send {name}"
            description = descriptions.get(
                name,
                f"When enabled, {name} is included in the request. Disable for "
                f"models/APIs that reject it.",
            )
        fields[f"send_{name}"] = _send_parameter_field(name, label, description, group)
    return fields


def toggleable_parameters_config(
    params: tuple[str | ParameterReroute, ...],
    sets: tuple[ParameterSet, ...] = (),
    *,
    default: bool = True,
) -> type[pydantic.BaseModel]:
    """
    Build a pydantic model with a `send_<param>` flag per toggle,
    for use as a base of a client's Defaults / ClientConfig.
    """
    return pydantic.create_model(
        "ToggleableParametersConfig",
        **{f"send_{name}": (bool, default) for name in toggle_names(params, sets)},
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
    An entry is a Talemate parameter name or a ParameterReroute (toggled by its
    Talemate name). Parameters listed in a `parameter_sets` entry share that
    set's toggle. `always_sent_parameters` have no toggle.
    """

    toggleable_parameters: tuple[str | ParameterReroute, ...] = ()
    parameter_sets: tuple[ParameterSet, ...] = ()
    always_sent_parameters: tuple[str | ParameterReroute, ...] = ("max_tokens",)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name in toggle_names(cls.toggleable_parameters, cls.parameter_sets):
            field_name = f"send_{name}"
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
            if getattr(
                self.client_config, f"send_{toggle_name(param, self.parameter_sets)}"
            )
        ] + list(self.always_sent_parameters)
