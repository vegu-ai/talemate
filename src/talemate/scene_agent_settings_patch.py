"""Validated sparse mutations shared by scene creation and live settings."""

from talemate.scene_agent_settings import SceneAgentSettings


class SceneOverridePatchError(ValueError):
    """A sparse hub patch that does not match the patch contract."""


def _validate_patch_envelope(patch) -> None:
    """Reject a malformed ``{set, clear}`` envelope before anything is read."""
    if not isinstance(patch, dict):
        raise SceneOverridePatchError("'patch' must be an object")
    unknown = set(patch.keys()) - {"set", "clear"}
    if unknown:
        raise SceneOverridePatchError(
            f"unknown patch keys: {', '.join(sorted(unknown))}"
        )
    set_part = patch.get("set") or {}
    if not isinstance(set_part, dict):
        raise SceneOverridePatchError("'set' must be an object")
    actions = set_part.get("actions") or {}
    if not isinstance(actions, dict):
        raise SceneOverridePatchError("'set.actions' must be an object")
    clear = patch.get("clear") or []
    if not isinstance(clear, list):
        raise SceneOverridePatchError("'clear' must be an array")
    for entry in clear:
        if not isinstance(entry, dict):
            raise SceneOverridePatchError("each 'clear' entry must be an object")
        if not entry.get("action") or not isinstance(entry["action"], str):
            raise SceneOverridePatchError("each 'clear' entry needs an 'action' string")
        if entry.get("config") is not None and not isinstance(entry["config"], str):
            raise SceneOverridePatchError("'clear[].config' must be a string")


def plan_scene_override_patch(agent, patch: dict) -> dict:
    """Validate a sparse patch against the agent's declared actions and return
    the writes/clears to apply.

    The whole patch is checked before anything is planned, so a malformed entry
    anywhere refuses the request instead of leaving the earlier entries applied.
    Unknown actions and config keys are refused here (the hub only ever names
    declared fields); declared-but-non-overridable fields are planned as
    stripped, matching the replacement API's liveness behaviour.
    """
    _validate_patch_envelope(patch)
    sets: list[tuple[str, str, str | None, object]] = []
    strips: list[str] = []
    actions = (patch.get("set") or {}).get("actions") or {}
    for action_key, action_set in actions.items():
        if not isinstance(action_set, dict):
            raise SceneOverridePatchError(f"'{action_key}' must be an object")
        declared_action = agent.actions.get(action_key)
        if declared_action is None:
            raise SceneOverridePatchError(f"unknown action '{action_key}'")
        if action_set.get("enabled") is not None:
            if declared_action.can_be_disabled:
                sets.append(("enabled", action_key, None, bool(action_set["enabled"])))
            else:
                strips.append(f"{action_key}.enabled")
        config_set = action_set.get("config") or {}
        if not isinstance(config_set, dict):
            raise SceneOverridePatchError(f"'{action_key}.config' must be an object")
        declared_config = declared_action.config or {}
        for config_key, entry in config_set.items():
            if not isinstance(entry, dict) or "value" not in entry:
                raise SceneOverridePatchError(
                    f"'{action_key}.{config_key}' must be an object with a 'value'"
                )
            field = declared_config.get(config_key)
            if field is None:
                raise SceneOverridePatchError(
                    f"unknown config '{action_key}.{config_key}'"
                )
            if not field.scene_overridable:
                strips.append(f"{action_key}.{config_key}")
                continue
            sets.append(("config", action_key, config_key, entry["value"]))
    clears = [
        (entry["action"], entry.get("config")) for entry in patch.get("clear") or []
    ]
    return {"sets": sets, "clears": clears, "stripped": strips}


def apply_scene_override_plan(
    overrides: SceneAgentSettings, agent_type: str, plan: dict
) -> list[str]:
    """Merge a validated patch plan into one agent's overlay slice.

    Unlike the replacement form, this touches only the keys named, so a slower
    hub patch never wipes an unrelated edit that landed in the same slice
    first. ``clear`` entries with no ``config`` drop the action's enable
    override; entries with one drop that config field.
    """
    for kind, action_key, config_key, value in plan["sets"]:
        if kind == "enabled":
            overrides.set_enabled(agent_type, action_key, value)
        else:
            overrides.set_value(agent_type, action_key, config_key, value)
    for action_key, config_key in plan["clears"]:
        if config_key is None:
            overrides.clear_enabled(agent_type, action_key)
        else:
            overrides.clear_value(agent_type, action_key, config_key)
    return plan["stripped"]
