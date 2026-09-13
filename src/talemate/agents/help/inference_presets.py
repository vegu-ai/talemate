import math
from typing import Any

import pydantic

from talemate.config import commit_config, get_config
from talemate.config.schema import InferenceParameters, InferencePresets

from .settings import _settings_dirty_conflict


NUMERIC_PARAMETERS = {
    "temperature": (0.1, 2.0, 0.01),
    "top_p": (0.1, 1.0, 0.01),
    "top_k": (0, 1024, 1),
    "min_p": (0, 1.0, 0.01),
    "presence_penalty": (0, 1.0, 0.01),
    "frequency_penalty": (0, 1.0, 0.01),
    "repetition_penalty": (1.0, 1.20, 0.01),
    "repetition_penalty_range": (0, 8192, 256),
    "xtc_threshold": (0, 1.0, 0.01),
    "xtc_probability": (0, 1.0, 0.01),
    "dry_multiplier": (0, 4.0, 0.1),
    "dry_base": (1.0, 3.0, 0.01),
    "dry_allowed_length": (1, 10, 1),
    "smoothing_factor": (0, 1.0, 0.01),
    "smoothing_curve": (0, 1.0, 0.01),
    "adaptive_target": (-0.01, 1.0, 0.01),
    "adaptive_decay": (0, 1.0, 0.01),
}
OTHER_PARAMETERS = {
    "temperature_last": "boolean",
    "extra_stopping_strings": "array of strings",
    "dry_sequence_breakers": "string",
}


def describe_inference_parameters() -> dict:
    return {
        "parameters": {
            **{
                key: {
                    "type": "integer" if step >= 1 else "number",
                    "min": low,
                    "max": high,
                    "step": step,
                }
                for key, (low, high, step) in NUMERIC_PARAMETERS.items()
            },
            **{key: {"type": kind} for key, kind in OTHER_PARAMETERS.items()},
        },
        "preset_keys": list(InferencePresets.model_fields),
        "defaults": "Read section=presets, path=['inference_defaults', preset_key]. Reset uses each selected preset's own defaults.",
        "groups": "Read section=presets, path=['inference_groups'], mode=index; pass an exact group key with group_is_key=true. The empty key explicitly selects built-in Default (path=['inference']); a named Default group has its own nonempty key.",
        "client_support": "Saved parameters are shared by clients using the group. Each client continues to filter unsupported parameters when generating.",
    }


def _resolve_group(group: str, group_is_key: bool = False) -> tuple[str, str] | str:
    if type(group_is_key) is not bool:
        return "group_is_key must be a boolean."
    if not isinstance(group, str):
        return (
            "Group must be an existing group key/name; use an empty string for Default."
        )
    if group == "":
        return "", "Default"
    groups = get_config().presets.inference_groups
    if group_is_key:
        if group not in groups:
            return "Unknown group key. Read the group index and use an exact key; no group was created."
        return group, groups[group].name
    name = group.strip().casefold()
    candidates = {
        key: item.name
        for key, item in groups.items()
        if name in (key.strip().casefold(), item.name.strip().casefold())
    }
    if name == "default":
        candidates[""] = "Default"
    if len(candidates) > 1:
        return "Ambiguous group name. Ask the user which group they mean; read the group index and pass its exact key with group_is_key=true."
    if not candidates:
        return "Unknown group. Read the group index and ask the user to identify an existing group; no group was created."
    return next(iter(candidates.items()))


def _validate_values(values: Any) -> dict:
    if not isinstance(values, dict):
        raise ValueError(
            "Parameters must be an object of existing parameter names and values."
        )
    cleaned = {}
    for key, value in values.items():
        if key in NUMERIC_PARAMETERS:
            low, high, step = NUMERIC_PARAMETERS[key]
            if type(value) not in (int, float) or (
                isinstance(value, float) and not math.isfinite(value)
            ):
                raise ValueError(f"{key} must be a finite number.")
            if not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}.")
            steps = (value - low) / step
            if abs(steps - round(steps)) > 1e-7:
                raise ValueError(f"{key} must use steps of {step} from {low}.")
            cleaned[key] = int(value) if step >= 1 else float(value)
        elif key == "temperature_last" and type(value) is bool:
            cleaned[key] = value
        elif key == "dry_sequence_breakers" and isinstance(value, str):
            cleaned[key] = value
        elif (
            key == "extra_stopping_strings"
            and isinstance(value, list)
            and all(isinstance(item, str) for item in value)
        ):
            cleaned[key] = value
        elif key in OTHER_PARAMETERS:
            raise ValueError(f"{key} must be a {OTHER_PARAMETERS[key]}.")
        else:
            raise ValueError(
                "Unknown or read-only parameter. Use describe_inference_parameters for writable names."
            )
    return cleaned


async def update_inference_presets(
    group: str,
    preset: str,
    parameters: dict,
    reset_rest: bool = False,
    app_settings_dirty: bool = False,
    group_is_key: bool = False,
) -> dict | str:
    conflict = _settings_dirty_conflict(app_settings_dirty)
    if conflict:
        return conflict
    target = _resolve_group(group, group_is_key)
    if isinstance(target, str):
        return target
    group_key, group_name = target
    if not isinstance(preset, str):
        return "Preset must be an existing action preset key or 'all'."
    preset = preset.strip().lower().replace(" ", "_")
    if preset != "all" and preset not in InferencePresets.model_fields:
        return "Unknown preset. Use describe_inference_parameters for the existing action preset keys."
    if type(reset_rest) is not bool:
        return (
            "reset_rest must be a boolean; set true only for an explicit reset request."
        )
    try:
        values = _validate_values(parameters)
    except ValueError as exc:
        return str(exc)
    if not values and not reset_rest:
        return "No parameters supplied and no reset requested. Nothing changed."

    config = get_config()
    updated = config.presets.model_copy(deep=True)
    scope = (
        updated.inference_groups[group_key].presets if group_key else updated.inference
    )
    keys = list(InferencePresets.model_fields) if preset == "all" else [preset]
    applied = {}
    for key in keys:
        source = getattr(updated.inference_defaults if reset_rest else scope, key)
        data = {**source.model_dump(), **values, "changed": True}
        try:
            row = InferenceParameters.model_validate(data)
        except pydantic.ValidationError:
            return "Invalid inference parameters. Nothing changed."
        setattr(scope, key, row)
        applied[key] = (
            row.model_dump(exclude={"changed"})
            if reset_rest
            else {field: getattr(row, field) for field in values}
        )

    config.presets = updated
    result = {
        "group_key": group_key,
        "group_name": group_name,
        "presets": keys,
        "reset_rest": reset_rest,
    }
    try:
        await config.set_dirty()
        await commit_config()
    except Exception as exc:
        return {
            **result,
            "applied": False,
            "in_memory_applied": True,
            "persistence": "unconfirmed",
            "error": f"{type(exc).__name__}: values changed in memory but saving/broadcasting failed. Do not report success; disk persistence is unconfirmed.",
        }
    return {**result, "applied": True, "values": applied}
