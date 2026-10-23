"""
Settings access tools for the help agent.

Exposes Talemate's configuration to the LLM through focal callbacks: reading
and updating agent settings (globally or as per-scene overrides), reading and
updating application config sections, and a read-only view of the configured
clients. Secret values (API keys) are never exposed and cannot be written.

Write operations mirror the frontend save paths: global agent settings reach
the running agent through ``Agent.apply_config`` as a settings page save does
(a failed apply keeps the change stored for retry on the next save), persist
via ``Agent.save_config`` + ``commit_config`` and re-emit the agent status,
app config writes re-validate the whole section through its pydantic model,
and both fire ``config.changed`` so every frontend receives a fresh
``app_config`` payload instead of keeping a snapshot that predates the write.
"""

import json
from typing import TYPE_CHECKING, Any, Literal

import pydantic
import structlog

import talemate.config.schema as config_schema
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
from talemate.util.encryption import REDACTED, is_sensitive_field, redact_sensitive
from talemate.ux.schema import SECRET_FIELD_TYPES

from .config_read import read_value

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

MAX_INLINE_CHOICES = 20
MAX_INLINE_CHOICES_BYTES = 2048

# field types the update tool can write - everything else (tables, weights,
# vectors, template pickers, ...) is UI-only
WRITABLE_FIELD_TYPES = (
    "bool",
    "number",
    "text",
    "autocomplete",
    "combobox",
    "blob",
    "flags",
)

READABLE_CONFIG_SECTIONS = ("game", "appearance", "creator", "presets", "prompts")
WRITABLE_CONFIG_SECTIONS = ("game", "appearance", "creator")

# the permissions that decide what this agent may write are not writable by it:
# a settings permission that could grant the template permission (or re-grant
# itself after the user revoked it) is not a permission
OWN_PERMISSIONS = ("help", "permissions")


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


def _choice_guidance(config_key: str, field: "AgentActionConfig") -> str | None:
    if config_key in ("model", "model_name"):
        return "Use a model id chosen by the user; ask for the id or point to the settings dropdown. Never list or recommend models."
    if config_key in ("provider_only", "provider_ignore"):
        return "Use provider ids chosen by the user in the settings dropdown; pass the full list of selected ids."
    if (
        len(field.choices or []) > MAX_INLINE_CHOICES
        or len(json.dumps(field.choices or [], ensure_ascii=False).encode("utf-8"))
        > MAX_INLINE_CHOICES_BYTES
    ):
        return "Use a value chosen by the user from the settings dropdown."
    return None


def _resolve_choice(
    field: "AgentActionConfig", value: Any, guidance: str | None = None
) -> Any:
    """Validate ``value`` against the field's choices, returning the canonical
    choice value. Raises ValueError when it matches neither a value nor a label."""
    valid_values = [choice["value"] for choice in field.choices]
    if value in valid_values:
        return value
    # the LLM may have supplied the choice label instead of the value
    for choice in field.choices:
        if str(choice["label"]).strip().lower() == str(value).strip().lower():
            return choice["value"]
    if guidance:
        raise ValueError(f"Invalid choice {value!r}. {guidance}")
    raise ValueError(f"Invalid choice {value!r}. Valid values: {valid_values}")


def _coerce_value(
    field: "AgentActionConfig", value: Any, guidance: str | None = None
) -> Any:
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
        return [_resolve_choice(field, item, guidance) for item in value]
    else:
        coerced = value if isinstance(value, str) else str(value)

    # a combobox offers its choices as suggestions and keeps any other value
    if field.choices and field.type != "combobox":
        return _resolve_choice(field, coerced, guidance)

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
    guidance = _choice_guidance(config_key, field)
    if guidance:
        payload["choices_omitted"] = True
        payload["value_guidance"] = guidance
    elif field.choices:
        payload["choices"] = [
            {"label": choice["label"], "value": choice["value"]}
            for choice in field.choices
        ]
    if field.type == "combobox":
        payload["other_values"] = (
            "accepted; suggestions do not restrict the value"
            if guidance
            else "accepted, the choices are suggestions"
        )
    if field.min is not None:
        payload["min"] = field.min
    if field.max is not None:
        payload["max"] = field.max
    if field.type not in WRITABLE_FIELD_TYPES or _is_secret_field(field):
        payload["read_only"] = "can only be changed on the agent settings page"
    if not field.scene_overridable:
        payload["scene_overridable"] = False

    # A stored value for a non-overridable field is inert — `resolve_config`
    # ignores it — so reporting it would name an effective value that is not in
    # effect. Secret types are covered by this: the validator forces them
    # non-overridable.
    overrides = agent.scene_overrides()
    if overrides is not None and field.scene_overridable:
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

    # `resolve_enabled` ignores a stored flag for a non-disableable action
    overrides = agent.scene_overrides()
    if overrides is not None and action.can_be_disabled:
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


def _settings_dirty_conflict(app_settings_dirty: bool) -> str | None:
    """Refusal message when the settings view holds unsaved edits.

    Agent configuration is edited on the settings tab, which holds a working
    copy of the WHOLE configuration and saves all of it at once from whatever
    page is showing - so unsaved edits anywhere in that view (including the
    per-page extra changes folded into its dirty state) would push the
    pre-change values back over whatever is written here. A merely open
    settings view is fine: it adopts an incoming config cleanly, and edits
    kept while the user is on another tab still count (the frontend reports
    ``dirty`` off-screen). Same gating as ``update_app_config``.

    Best-effort by construction: the flag rides on the UX snapshot taken when
    the message was sent, so edits made while the agent is answering are not
    seen.
    """
    if not app_settings_dirty:
        return None
    return (
        "The application settings view has unsaved edits - saving them would "
        "overwrite this change. Ask the user to save or discard their settings "
        "changes first, then apply the change again."
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

    Unlike the websocket flow, no scene save is forced to persist the link:
    a file with the default name is auto-linked on every scene load
    (scene_agent_settings.resolve_link_on_load).
    """
    if scene.agent_overrides is None:
        target_path = agent_settings_dir(scene.save_dir) / DEFAULT_SETTINGS_FILENAME
        scene.agent_overrides = SceneAgentSettings(filepath=target_path)
        scene.agent_settings_file = DEFAULT_SETTINGS_FILENAME
        scene._agent_settings_opted_out = False
    return scene.agent_overrides


async def _broadcast_agent_config(agent: "Agent") -> None:
    # same sequence as the frontend-driven save paths
    # (server.agent_config._persist_and_broadcast) — including the app_config
    # broadcast, without which every frontend keeps a config snapshot that
    # predates this write and reverts it on its next full-config save
    await get_config().set_dirty()
    await commit_config()
    await agent.emit_status()


async def _apply_global_setting(
    agent: "Agent", action_key: str, setting_key: str, value: Any
) -> str | None:
    """Change one global setting (``"enabled"`` for the action's flag) the way
    a settings page save does: store it, apply it to the running agent and
    persist it. Returns the error when the apply failed; the change then stays
    stored for retry on the next save."""
    # the stored config gets the new value while the agent still holds the old
    # one: agents compare the two to rebuild what the change affects (the
    # Visualizer's backends, the memory agent's embeddings)
    await agent.save_config()
    stored = get_config().agents[agent.agent_type]
    stored_action = stored.actions[action_key]
    if setting_key == "enabled":
        stored_action.enabled = value
    else:
        stored_action.config[setting_key] = config_schema.AgentActionConfig(value=value)
    try:
        await instance.apply_agent_config(agent, **stored.model_dump())
    except Exception as exc:
        log.error(
            "applying a help chat setting change failed",
            agent=agent.agent_type,
            action=action_key,
            setting=setting_key,
            error=str(exc),
        )
        error = str(exc) or type(exc).__name__
    else:
        # apply_config can change values too: a new ComfyUI workflow clears
        # the model
        await agent.save_config()
        error = None
    await _broadcast_agent_config(agent)
    return error


def _saved_not_applied(
    action_key: str, setting_key: str, value: Any, error: str
) -> str:
    return (
        f"Saved {action_key}.{setting_key} = {value!r}, but applying it to the "
        f"running agent failed: {error}. Open Settings and press Save to retry "
        "(Apply pending keeps Save available without edits), or ask me to set "
        "this setting again. If the error persists, correct its cause before retrying."
    )


def _own_permission_conflict(agent_type: str, action_key: str) -> str | None:
    if (agent_type, action_key) != OWN_PERMISSIONS:
        return None
    return (
        "The help agent's own permissions are not yours to change - they are what "
        "decides what you may write. The user changes them under Settings > "
        "Connections > Agents > Help > Permissions."
    )


async def update_agent_setting(
    agent_type: str,
    action_key: str,
    setting_key: str,
    value: Any,
    scope: Literal["global", "scene"] = "global",
    app_settings_dirty: bool = False,
) -> dict | str:
    """Update one agent setting - the global value or a per-scene override.

    ``setting_key`` may be ``"enabled"`` to toggle the action itself.
    ``app_settings_dirty`` flags that the settings view in the frontend has
    unsaved edits (from the UX snapshot) - agent writes are refused then.
    """
    if scope not in ("global", "scene"):
        return f"Invalid scope '{scope}'. Use 'global' or 'scene'."

    own = _own_permission_conflict(agent_type, action_key)
    if own:
        return own

    resolved = _resolve_setting(agent_type, action_key, setting_key)
    if isinstance(resolved, str):
        return resolved
    agent, action, field = resolved

    conflict = _settings_dirty_conflict(app_settings_dirty)
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
            error = await _apply_global_setting(agent, action_key, "enabled", coerced)
            if error:
                return _saved_not_applied(action_key, "enabled", coerced, error)
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
            "changed on the agent settings page."
        )
    if field.type not in WRITABLE_FIELD_TYPES:
        return (
            f"Setting '{setting_key}' ({field.type}) is too complex to change here - "
            "the user should edit it on the agent settings page."
        )

    try:
        coerced = _coerce_value(field, value, _choice_guidance(setting_key, field))
    except ValueError as exc:
        return str(exc)

    if scope == "global":
        result["previous_value"] = field.value
        error = await _apply_global_setting(agent, action_key, setting_key, coerced)
        if error:
            return _saved_not_applied(action_key, setting_key, coerced, error)

        # a stored value for a non-overridable field masks nothing — the
        # resolver ignores it, so the global write is already effective
        overrides = agent.scene_overrides()
        if (
            overrides is not None
            and field.scene_overridable
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
    app_settings_dirty: bool = False,
) -> dict | str:
    """Remove a per-scene override so the setting falls back to its global value."""
    own = _own_permission_conflict(agent_type, action_key)
    if own:
        return own

    resolved = _resolve_setting(agent_type, action_key, setting_key)
    if isinstance(resolved, str):
        return resolved
    agent, _action, field = resolved

    conflict = _settings_dirty_conflict(app_settings_dirty)
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
        "removed_override_value": (
            REDACTED if field is not None and _is_secret_field(field) else previous
        ),
    }


# ---------------------------------------------------------------------------
# app config
# ---------------------------------------------------------------------------


def read_app_config(
    section: str = "",
    path: list[str | int] | None = None,
    fields: list[str] | None = None,
    mode: Literal["auto", "index", "value"] = "auto",
    offset: int = 0,
    limit: int = 20,
    revision: str | None = None,
) -> dict | str:
    """Read exact config values or a bounded, explicitly navigable page."""
    if not isinstance(section, str):
        return {"error": "Section must be a string."}
    section = (section or "").strip().lower()
    if not section:
        return {"sections": list(READABLE_CONFIG_SECTIONS)}
    if section not in READABLE_CONFIG_SECTIONS:
        return (
            "Unknown or unavailable config section. "
            f"Readable sections: {', '.join(READABLE_CONFIG_SECTIONS)}. "
            "Use read_agent_settings for agents and read_clients for clients."
        )

    config = get_config()
    data = getattr(config, section).model_dump()

    return read_value(
        redact_sensitive(data),
        path=path,
        fields=fields,
        mode=mode,
        offset=offset,
        limit=limit,
        revision=revision,
        metadata={"section": section, "writable": section in WRITABLE_CONFIG_SECTIONS},
    )


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
    path: str, value: Any, app_settings_dirty: bool = False
) -> dict | str:
    """Update one application config setting by dotted path.

    The whole section is re-validated through its pydantic model, so invalid
    values are rejected with the validation error. ``app_settings_dirty``
    flags that the settings view in the frontend has unsaved edits - writes
    are refused then, since the user's pending changes and the agent's write
    would conflict (whichever saves last would overwrite the other). A merely
    open settings view is fine: the frontend handles the config push cleanly.
    """
    if app_settings_dirty:
        return (
            "The application settings view has unsaved edits - applying this "
            "change now would conflict with them. Ask the user to save or "
            "discard their settings changes first, then apply the change again."
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
    if any(is_sensitive_field(key) for key in keys):
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
