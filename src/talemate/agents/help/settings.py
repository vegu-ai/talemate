"""
Settings access tools for the help agent.

Exposes Talemate's configuration to the LLM through focal callbacks: reading
and updating agent settings (globally or as per-scene overrides), reading and
updating application config sections, and a read-only view of the configured
clients. Secret values (API keys) are never exposed and cannot be written.

Write operations mirror the frontend save paths: agent settings persist via
``Agent.save_config`` + ``commit_config`` and re-emit the agent status; app
config writes re-validate the whole section through its pydantic model and
fire ``config.changed`` so the frontend receives a fresh ``app_config``
payload.
"""

from typing import TYPE_CHECKING, Any, Literal

import pydantic
import structlog

import talemate.instance as instance
from talemate.agents.base import DYNAMIC_CHILDREN_FIELD
from talemate.client.registry import get_client_class
from talemate.config import commit_config, get_config
from talemate.scene_agent_settings import (
    DEFAULT_SETTINGS_FILENAME,
    SceneAgentSettings,
    UNSET,
    agent_settings_dir,
)
from talemate.util.encryption import SENSITIVE_FIELD_NAMES

if TYPE_CHECKING:
    from talemate.agents.base import Agent, AgentAction, AgentActionConfig

__all__ = [
    "read_agent_settings",
    "update_agent_setting",
    "clear_agent_setting_scene_override",
    "read_app_config",
    "update_app_config",
    "read_clients",
]

log = structlog.get_logger("talemate.agents.help.settings")

REDACTED = "(hidden)"

# field types whose values must never be shown to (or written by) the LLM
SECRET_FIELD_TYPES = ("password", "unified_api_key")

# field types the update tool can write - everything else (tables, weights,
# vectors, template pickers, ...) is UI-only
WRITABLE_FIELD_TYPES = ("bool", "number", "text", "autocomplete", "blob", "flags")

READABLE_CONFIG_SECTIONS = ("game", "appearance", "creator", "presets", "prompts")
WRITABLE_CONFIG_SECTIONS = ("game", "appearance", "creator")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _get_agent(agent_type: str) -> "Agent | None":
    return instance.AGENTS.get(agent_type)


def _unknown_agent(agent_type: str) -> str:
    return (
        f"Unknown agent '{agent_type}'. "
        f"Valid agents: {', '.join(sorted(instance.AGENTS.keys()))}"
    )


def _is_secret_field(field: "AgentActionConfig") -> bool:
    return field.type in SECRET_FIELD_TYPES


def _redact_sensitive(data: Any) -> Any:
    """Recursively replace values of sensitive keys (api_key etc.)."""
    if isinstance(data, dict):
        return {
            key: (
                (REDACTED if value else None)
                if key in SENSITIVE_FIELD_NAMES
                else _redact_sensitive(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_redact_sensitive(item) for item in data]
    return data


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in (
        "true",
        "false",
        "yes",
        "no",
        "on",
        "off",
    ):
        return value.strip().lower() in ("true", "yes", "on")
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise ValueError(f"Expected a boolean (true/false), got {value!r}.")


def _resolve_choice(field: "AgentActionConfig", value: Any) -> Any:
    """Validate ``value`` against the field's choices, returning the canonical
    choice value. Raises ValueError when it matches neither a value nor a label."""
    valid_values = [choice["value"] for choice in field.choices]
    if value in valid_values:
        return value
    # the LLM may have supplied the choice label instead of the value
    for choice in field.choices:
        if str(choice["label"]).strip().lower() == str(value).strip().lower():
            return choice["value"]
    raise ValueError(f"Invalid choice {value!r}. Valid values: {valid_values}")


def _coerce_value(field: "AgentActionConfig", value: Any) -> Any:
    """Coerce a raw LLM-supplied value to the field's type.

    Raises ValueError with an LLM-readable message when the value cannot be
    coerced or fails choice / range validation.
    """
    if field.type == "bool":
        coerced = _coerce_bool(value)
    elif field.type == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Expected a number, got {value!r}.")
        coerced = int(number) if number == int(number) else number
        if field.min is not None and coerced < field.min:
            raise ValueError(f"Value {coerced} is below the minimum of {field.min}.")
        if field.max is not None and coerced > field.max:
            raise ValueError(f"Value {coerced} is above the maximum of {field.max}.")
    elif field.type == "flags":
        # flags fields hold a list of selected choice values
        if not isinstance(value, list):
            raise ValueError(
                f"This setting holds a list of values - pass the FULL new list, got {value!r}."
            )
        return [_resolve_choice(field, item) for item in value]
    else:
        coerced = value if isinstance(value, str) else str(value)

    if field.choices:
        return _resolve_choice(field, coerced)

    return coerced


def _field_payload(
    agent: "Agent", action_key: str, config_key: str, field: "AgentActionConfig"
) -> dict:
    """LLM-facing description of a single agent setting field."""
    payload: dict[str, Any] = {
        "label": field.label,
        "type": field.type,
        "value": REDACTED if _is_secret_field(field) else field.value,
    }
    if field.description:
        payload["description"] = field.description
    if field.choices:
        payload["choices"] = [
            {"label": choice["label"], "value": choice["value"]}
            for choice in field.choices
        ]
    if field.min is not None:
        payload["min"] = field.min
    if field.max is not None:
        payload["max"] = field.max
    if field.type not in WRITABLE_FIELD_TYPES or _is_secret_field(field):
        payload["read_only"] = "can only be changed through the settings dialog"
    if not field.scene_overridable:
        payload["scene_overridable"] = False

    overrides = agent.scene_overrides()
    if overrides is not None and not _is_secret_field(field):
        override_value = overrides.get_value(agent.agent_type, action_key, config_key)
        if override_value is not UNSET:
            payload["scene_override"] = override_value

    return payload


def _action_payload(agent: "Agent", action_key: str, action: "AgentAction") -> dict:
    payload: dict[str, Any] = {
        "label": action.label,
        "enabled": action.enabled,
    }
    if action.description:
        payload["description"] = action.description
    if action.can_be_disabled:
        payload["can_be_disabled"] = True

    overrides = agent.scene_overrides()
    if overrides is not None:
        enabled_override = overrides.get_enabled(agent.agent_type, action_key)
        if enabled_override is not UNSET:
            payload["enabled_scene_override"] = enabled_override

    if action.config:
        payload["settings"] = {
            config_key: _field_payload(agent, action_key, config_key, field)
            for config_key, field in action.config.items()
            if config_key != DYNAMIC_CHILDREN_FIELD
        }
    return payload


# ---------------------------------------------------------------------------
# agent settings
# ---------------------------------------------------------------------------


def read_agent_settings(agent_type: str) -> dict | str:
    """Return the full settings state of one agent."""
    agent = _get_agent(agent_type)
    if not agent:
        return _unknown_agent(agent_type)

    payload: dict[str, Any] = {
        "agent": agent.agent_type,
        "label": agent.verbose_name,
        "enabled": agent.enabled,
    }
    if getattr(agent, "client", None):
        payload["client"] = agent.client.name

    actions = getattr(agent, "actions", None) or {}
    payload["actions"] = {
        action_key: _action_payload(agent, action_key, action)
        for action_key, action in actions.items()
    }

    overrides = agent.scene_overrides()
    if overrides is not None:
        payload["note"] = (
            "This scene has an agent-settings override file linked "
            f"({overrides.filename}). Fields with a 'scene_override' value are "
            "currently masked by it; the effective value is the override."
        )

    return payload


def _resolve_setting(
    agent_type: str, action_key: str, setting_key: str
) -> "tuple[Agent, AgentAction, AgentActionConfig | None] | str":
    """Resolve agent/action/setting, returning an error string on failure.

    ``setting_key`` may be ``"enabled"`` to target the action's enabled flag,
    in which case the returned field is None.
    """
    agent = _get_agent(agent_type)
    if not agent:
        return _unknown_agent(agent_type)

    actions = getattr(agent, "actions", None) or {}
    action = actions.get(action_key)
    if not action:
        return (
            f"Agent '{agent_type}' has no action '{action_key}'. "
            f"Valid actions: {', '.join(sorted(actions.keys()))}"
        )

    if setting_key == "enabled":
        return agent, action, None

    field = (action.config or {}).get(setting_key)
    if not field or setting_key == DYNAMIC_CHILDREN_FIELD:
        valid = sorted(k for k in (action.config or {}) if k != DYNAMIC_CHILDREN_FIELD)
        return (
            f"Action '{action_key}' has no setting '{setting_key}'. "
            f"Valid settings: {', '.join(valid) or '(none)'}"
        )

    return agent, action, field


def _open_modal_conflict(agent_type: str, open_agent_modal: str | None) -> str | None:
    """Refusal message when the target agent's settings dialog is open.

    The dialog holds its own copy of the agent's settings: it will not show
    an external change, and closing it with pending edits writes the stale
    copy back - silently reverting anything changed while it was open.
    """
    if not open_agent_modal or open_agent_modal != agent_type:
        return None
    return (
        f"The settings dialog for the '{agent_type}' agent is currently open in "
        "the interface - it holds its own copy of the settings, so it would not "
        "show this change and could overwrite it when it closes. Ask the user to "
        "close the dialog first, then apply the change again."
    )


def _scene_for_overrides(agent: "Agent") -> "tuple[Any, str | None]":
    """Return (scene, error) for scene-override writes on ``agent``."""
    scene = getattr(agent, "scene", None)
    if scene is None or not getattr(scene, "name", None):
        return (
            None,
            "No scene is currently loaded - scene overrides need a loaded scene.",
        )
    if not getattr(scene, "filename", None) or not getattr(scene, "project_name", None):
        return (
            None,
            "The scene has not been saved yet - save it before adding scene overrides.",
        )
    if getattr(scene, "_agent_settings_opted_out", False):
        return None, (
            "This scene has explicitly opted out of agent-settings overrides. "
            "The user can change that under World Editor > Scene > Settings."
        )
    return scene, None


def _ensure_scene_overlay(scene) -> SceneAgentSettings:
    """Return the scene's overlay, creating the default-named one if missing.

    Unlike the AgentModal flow, no scene save is forced to persist the link:
    a file with the default name is auto-linked on every scene load
    (scene_agent_settings.resolve_link_on_load).
    """
    if scene.agent_overrides is None:
        target_path = agent_settings_dir(scene.save_dir) / DEFAULT_SETTINGS_FILENAME
        scene.agent_overrides = SceneAgentSettings(filepath=target_path)
        scene.agent_settings_file = DEFAULT_SETTINGS_FILENAME
        scene._agent_settings_opted_out = False
    return scene.agent_overrides


async def _persist_agent_config(agent: "Agent") -> None:
    # same sequence as the frontend-driven save paths
    # (server.agent_config._persist_and_broadcast)
    await agent.save_config()
    await commit_config()
    await agent.emit_status()


async def update_agent_setting(
    agent_type: str,
    action_key: str,
    setting_key: str,
    value: Any,
    scope: Literal["global", "scene"] = "global",
    open_agent_modal: str | None = None,
) -> dict | str:
    """Update one agent setting - the global value or a per-scene override.

    ``setting_key`` may be ``"enabled"`` to toggle the action itself.
    ``open_agent_modal`` names the agent whose settings dialog is open in the
    frontend (from the UX snapshot) - writes targeting it are refused.
    """
    if scope not in ("global", "scene"):
        return f"Invalid scope '{scope}'. Use 'global' or 'scene'."

    resolved = _resolve_setting(agent_type, action_key, setting_key)
    if isinstance(resolved, str):
        return resolved
    agent, action, field = resolved

    conflict = _open_modal_conflict(agent_type, open_agent_modal)
    if conflict:
        return conflict

    result: dict[str, Any] = {
        "applied": True,
        "agent": agent_type,
        "action": action_key,
        "setting": setting_key,
        "scope": scope,
    }

    if field is None:
        try:
            coerced = _coerce_bool(value)
        except ValueError as exc:
            return str(exc)

        if scope == "global":
            if not action.can_be_disabled:
                return f"Action '{action_key}' of agent '{agent_type}' is always enabled and cannot be toggled."
            result["previous_value"] = action.enabled
            action.enabled = coerced
            await _persist_agent_config(agent)
        else:
            if not action.enabled_scene_overridable:
                return f"The enabled flag of action '{action_key}' cannot be overridden per scene."
            scene, error = _scene_for_overrides(agent)
            if error:
                return error
            overlay = _ensure_scene_overlay(scene)
            previous = overlay.get_enabled(agent_type, action_key)
            result["previous_value"] = None if previous is UNSET else previous
            overlay.set_enabled(agent_type, action_key, coerced)
            await overlay.write_to_file()
            await agent.emit_status()

        result["new_value"] = coerced
        return result

    # regular config field
    if _is_secret_field(field):
        return (
            f"Setting '{setting_key}' holds an API key or password and can only be "
            "changed through the settings dialog."
        )
    if field.type not in WRITABLE_FIELD_TYPES:
        return (
            f"Setting '{setting_key}' ({field.type}) is too complex to change here - "
            "the user should edit it in the agent's settings dialog."
        )

    try:
        coerced = _coerce_value(field, value)
    except ValueError as exc:
        return str(exc)

    if scope == "global":
        result["previous_value"] = field.value
        field.value = coerced
        await _persist_agent_config(agent)

        overrides = agent.scene_overrides()
        if (
            overrides is not None
            and overrides.get_value(agent_type, action_key, setting_key) is not UNSET
        ):
            result["warning"] = (
                "A scene override is active for this setting and masks the "
                "global value in the current scene."
            )
    else:
        if not field.scene_overridable:
            return f"Setting '{setting_key}' cannot be overridden per scene."
        scene, error = _scene_for_overrides(agent)
        if error:
            return error
        overlay = _ensure_scene_overlay(scene)
        previous = overlay.get_value(agent_type, action_key, setting_key)
        result["previous_value"] = None if previous is UNSET else previous
        overlay.set_value(agent_type, action_key, setting_key, coerced)
        await overlay.write_to_file()
        await agent.emit_status()

    result["new_value"] = coerced
    return result


async def clear_agent_setting_scene_override(
    agent_type: str,
    action_key: str,
    setting_key: str,
    open_agent_modal: str | None = None,
) -> dict | str:
    """Remove a per-scene override so the setting falls back to its global value."""
    resolved = _resolve_setting(agent_type, action_key, setting_key)
    if isinstance(resolved, str):
        return resolved
    agent, _action, field = resolved

    conflict = _open_modal_conflict(agent_type, open_agent_modal)
    if conflict:
        return conflict

    overrides = agent.scene_overrides()
    if overrides is None:
        return "No scene overrides are linked to the current scene."

    if field is None:
        previous = overrides.get_enabled(agent_type, action_key)
        if previous is UNSET:
            return f"No scene override is set for the enabled flag of '{action_key}'."
        overrides.clear_enabled(agent_type, action_key)
    else:
        previous = overrides.get_value(agent_type, action_key, setting_key)
        if previous is UNSET:
            return f"No scene override is set for '{action_key}.{setting_key}'."
        overrides.clear_value(agent_type, action_key, setting_key)

    await overrides.write_to_file()
    await agent.emit_status()

    return {
        "cleared": True,
        "agent": agent_type,
        "action": action_key,
        "setting": setting_key,
        "removed_override_value": previous,
    }


# ---------------------------------------------------------------------------
# app config
# ---------------------------------------------------------------------------


def read_app_config(section: str) -> dict | str:
    """Return one application config section (secrets redacted)."""
    section = (section or "").strip().lower()
    if section not in READABLE_CONFIG_SECTIONS:
        return (
            f"Unknown or unavailable config section '{section}'. "
            f"Readable sections: {', '.join(READABLE_CONFIG_SECTIONS)}. "
            "Use read_agent_settings for agents and read_clients for clients."
        )

    config = get_config()
    data = getattr(config, section).model_dump()

    if section == "presets":
        # the *_defaults entries mirror the shipped defaults and double the
        # payload without adding information
        data.pop("inference_defaults", None)
        data.pop("embeddings_defaults", None)

    return {
        "section": section,
        "writable": section in WRITABLE_CONFIG_SECTIONS,
        "values": _redact_sensitive(data),
    }


def _walk_to_leaf(data: dict, keys: list[str]) -> "tuple[dict, str] | str":
    """Walk ``data`` down ``keys``, returning (parent_container, leaf_key)."""
    container = data
    for i, key in enumerate(keys[:-1]):
        if not isinstance(container, dict) or key not in container:
            return f"Path segment '{'.'.join(keys[: i + 1])}' does not exist."
        container = container[key]
    leaf = keys[-1]
    if not isinstance(container, dict) or leaf not in container:
        return f"Setting '{'.'.join(keys)}' does not exist."
    return container, leaf


def _coerce_config_leaf(current: Any, value: Any, path: str) -> Any:
    """Coerce ``value`` to the type of the existing leaf value."""
    if isinstance(current, bool):
        try:
            return _coerce_bool(value)
        except ValueError:
            raise ValueError(f"'{path}' expects a boolean (true/false), got {value!r}.")
    if isinstance(current, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"'{path}' expects a number, got {value!r}.")
        return (
            int(number)
            if isinstance(current, int) and number == int(number)
            else number
        )
    if isinstance(current, list):
        if not isinstance(value, list):
            raise ValueError(
                f"'{path}' is a list and must be replaced with a full list value."
            )
        return value
    if isinstance(current, dict):
        raise ValueError(
            f"'{path}' is a nested section, not a setting. Target one of its settings instead."
        )
    return value if isinstance(value, str) or value is None else str(value)


async def update_app_config(
    path: str, value: Any, open_app_settings: bool = False
) -> dict | str:
    """Update one application config setting by dotted path.

    The whole section is re-validated through its pydantic model, so invalid
    values are rejected with the validation error. ``open_app_settings``
    flags that the application settings dialog is open in the frontend -
    writes are refused then, since the config push they trigger re-hydrates
    the dialog and discards the user's unsaved edits.
    """
    if open_app_settings:
        return (
            "The application settings dialog is currently open in the interface - "
            "applying this change now would discard any unsaved edits the user has "
            "in it. Ask the user to close the dialog first, then apply the change "
            "again."
        )

    keys = [key for key in (path or "").strip().split(".") if key]
    if len(keys) < 2:
        return (
            "Provide a dotted path with at least a section and a setting, "
            "e.g. 'game.general.auto_save'."
        )

    section = keys[0].lower()
    if section not in WRITABLE_CONFIG_SECTIONS:
        return (
            f"Config section '{section}' is not writable here. "
            f"Writable sections: {', '.join(WRITABLE_CONFIG_SECTIONS)}."
        )
    if any(key in SENSITIVE_FIELD_NAMES for key in keys):
        return "API keys and passwords cannot be read or changed through the help chat."

    config = get_config()
    section_model = getattr(config, section)
    data = section_model.model_dump()

    walked = _walk_to_leaf(data, keys[1:])
    if isinstance(walked, str):
        return walked
    container, leaf = walked

    previous = container[leaf]
    try:
        container[leaf] = _coerce_config_leaf(previous, value, path)
    except ValueError as exc:
        return str(exc)

    try:
        validated = type(section_model).model_validate(data)
    except pydantic.ValidationError as exc:
        first = exc.errors()[0]
        return f"Invalid value for '{path}': {first.get('msg', 'validation failed')}"

    setattr(config, section, validated)
    await config.set_dirty()
    await commit_config()

    return {
        "applied": True,
        "path": path,
        "previous_value": previous,
        "new_value": container[leaf],
    }


# ---------------------------------------------------------------------------
# clients
# ---------------------------------------------------------------------------


def _unified_api_key_state(config, client_type: str) -> str | None:
    """Key-state string for clients whose API key lives at an app-level
    unified config path (openai.api_key, openrouter.api_key, ...) instead of
    on the client entry."""
    client_cls = get_client_class(client_type)
    path = (
        getattr(client_cls.Meta(), "unified_api_key_config_path", None)
        if client_cls
        else None
    )
    if not path:
        return None
    value = config
    for part in path.split("."):
        # `not value` (rather than `is None`) also catches a key cleared to ""
        # in Application Settings, which clients treat as unset; intermediate
        # config sections are always-truthy pydantic models, so only the leaf
        # key value is affected
        value = getattr(value, part, None)
        if not value:
            return None
    return f"set (unified API key from application settings: {path})"


def read_clients() -> list[dict] | str:
    """Read-only summary of the configured LLM clients (API keys redacted)."""
    config = get_config()
    if not config.clients:
        return "No clients are configured yet."

    payload = []
    for name, client_config in config.clients.items():
        entry = {
            "name": name,
            "type": client_config.type,
            "model": client_config.model,
            "enabled": client_config.enabled,
            "max_token_length": client_config.max_token_length,
            "reason_enabled": client_config.reason_enabled,
        }
        if client_config.preset_group:
            entry["preset_group"] = client_config.preset_group
        if client_config.api_key:
            entry["api_key"] = "set"
        else:
            entry["api_key"] = (
                _unified_api_key_state(config, client_config.type) or "not set"
            )

        client_instance = instance.CLIENTS.get(name)
        if client_instance is not None:
            entry["status"] = client_instance.current_status

        payload.append(entry)

    return payload
