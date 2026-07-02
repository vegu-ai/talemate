"""Per-scene agent configuration overrides.

Persisted as a JSON file inside an ``agent-settings/`` subdirectory of the
scene's ``save_dir`` (default name ``agent-settings.json``). Referenced by
filename from the scene's main JSON via ``agent_settings_file``. Storage is
*sparse* — only fields that have an active override appear in the file;
everything else falls through to the global agent config at access time via
``Agent.resolve_config`` / ``Agent.resolve_enabled``.

Granularity is **project-level**, not save-file-level: ``save_dir`` is
derived from ``project_name``, so every save file (Save As copies, restore
points, etc.) inside the same project shares the same ``agent-settings/``
folder. Scenes in different projects have independent overlays. The scene
ZIP export/import flow packages the whole ``agent-settings/`` folder so
overlays survive cross-system transfer (see ``talemate.export`` and
``talemate.load``).

The on-disk layout looks like:

    {
        "agents": {
            "conversation": {
                "actions": {
                    "generation_override": {
                        "enabled": false,
                        "config": {
                            "format": {"value": "narrative"},
                            "length": {"value": 384}
                        }
                    }
                }
            }
        }
    }

Any ``.json`` file in the ``agent-settings/`` subdirectory is treated as a
settings file — the dedicated directory is what identifies the role, so the
filename can be anything (the default just stays ``agent-settings.json``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pydantic
import structlog

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.scene_agent_settings")

# `apply_scene_settings_link(filename=UNCHANGED)` means caller did not touch
# the agent-settings link at all (vs. explicit ``None`` which means "opt out").
UNCHANGED: Any = object()

# Subdirectory of ``save_dir`` that holds the agent-settings JSON files.
AGENT_SETTINGS_DIRNAME = "agent-settings"
SETTINGS_FILENAME_SUFFIX = ".json"

# Sentinel meaning "no override is set for this field". Compare with ``is UNSET``.
UNSET: Any = object()


def agent_settings_dir(save_dir: Path | str) -> Path:
    """Return the path to the ``agent-settings/`` subdirectory under ``save_dir``."""
    return Path(save_dir) / AGENT_SETTINGS_DIRNAME


class ConfigOverride(pydantic.BaseModel):
    """A single overridden config value. Presence in the dict == override active."""

    value: Any = None


class ActionOverride(pydantic.BaseModel):
    """Overrides for one action. Sparse: missing fields fall through to global."""

    # None means the container's `enabled` flag is NOT overridden (falls
    # through to global). A real bool means it is.
    enabled: bool | None = None
    config: dict[str, ConfigOverride] = pydantic.Field(default_factory=dict)


class AgentOverride(pydantic.BaseModel):
    """Overrides for one agent. Sparse."""

    actions: dict[str, ActionOverride] = pydantic.Field(default_factory=dict)


class SceneAgentSettings(pydantic.BaseModel):
    """A scene's agent-settings overlay.

    Loaded from / written to a JSON file in the scene's ``agent-settings/``
    subdirectory.
    """

    filepath: Path = pydantic.Field(exclude=True)
    agents: dict[str, AgentOverride] = pydantic.Field(default_factory=dict)

    @property
    def filename(self) -> str:
        return self.filepath.name

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    async def init_from_file(self) -> "SceneAgentSettings":
        with open(self.filepath, "r") as f:
            data = json.load(f)

        agents_raw = data.get("agents", {}) or {}
        self.agents = {
            name: AgentOverride(**override) for name, override in agents_raw.items()
        }
        return self

    async def write_to_file(self) -> None:
        # Prune empty containers so the file stays clean even when callers
        # clear the last override in an action / agent.
        self._prune_empty()

        payload = {
            "agents": {
                name: override.model_dump(exclude_none=True)
                for name, override in self.agents.items()
            },
        }
        # First write into a brand-new project creates the subdir.
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w") as f:
            json.dump(payload, f, indent=2)

    def _prune_empty(self) -> None:
        """Drop action overrides with no enabled flag and no config overrides;
        drop agent overrides with no remaining actions."""
        for agent_name in list(self.agents.keys()):
            agent_override = self.agents[agent_name]
            for action_key in list(agent_override.actions.keys()):
                action = agent_override.actions[action_key]
                if action.enabled is None and not action.config:
                    del agent_override.actions[action_key]
            if not agent_override.actions:
                del self.agents[agent_name]

    # ------------------------------------------------------------------
    # Read accessors (return UNSET when no override is set)
    # ------------------------------------------------------------------

    def get_value(self, agent_type: str, action_key: str, config_key: str):
        agent = self.agents.get(agent_type)
        if not agent:
            return UNSET
        action = agent.actions.get(action_key)
        if not action:
            return UNSET
        override = action.config.get(config_key)
        if override is None:
            return UNSET
        return override.value

    def get_enabled(self, agent_type: str, action_key: str):
        agent = self.agents.get(agent_type)
        if not agent:
            return UNSET
        action = agent.actions.get(action_key)
        if not action or action.enabled is None:
            return UNSET
        return action.enabled

    # ------------------------------------------------------------------
    # Write accessors
    # ------------------------------------------------------------------

    def _ensure_action(self, agent_type: str, action_key: str) -> ActionOverride:
        agent = self.agents.setdefault(agent_type, AgentOverride())
        return agent.actions.setdefault(action_key, ActionOverride())

    def set_value(
        self, agent_type: str, action_key: str, config_key: str, value: Any
    ) -> None:
        action = self._ensure_action(agent_type, action_key)
        action.config[config_key] = ConfigOverride(value=value)

    def clear_value(self, agent_type: str, action_key: str, config_key: str) -> None:
        agent = self.agents.get(agent_type)
        if not agent:
            return
        action = agent.actions.get(action_key)
        if not action:
            return
        action.config.pop(config_key, None)

    def set_enabled(self, agent_type: str, action_key: str, enabled: bool) -> None:
        action = self._ensure_action(agent_type, action_key)
        action.enabled = bool(enabled)

    def clear_enabled(self, agent_type: str, action_key: str) -> None:
        agent = self.agents.get(agent_type)
        if not agent:
            return
        action = agent.actions.get(action_key)
        if not action:
            return
        action.enabled = None

    # ------------------------------------------------------------------
    # Bulk replacement (used by the AgentModal save flow)
    # ------------------------------------------------------------------

    def replace_agent_overrides(self, agent_type: str, override: dict) -> None:
        """Replace ALL overrides for one agent with the supplied dict.

        Caller is expected to pass a sparse dict in the same shape as
        ``AgentOverride.model_dump``. Pass an empty dict to remove all
        overrides for the agent.
        """
        if not override:
            self.agents.pop(agent_type, None)
            return
        self.agents[agent_type] = AgentOverride(**override)


# ----------------------------------------------------------------------
# Discovery helpers
# ----------------------------------------------------------------------


def is_settings_filename(name: str) -> bool:
    """Filename-only check — must be a non-empty ``.json`` name.

    The dedicated ``agent-settings/`` subdirectory carries the role; the
    filename itself just needs to be a .json file.
    """
    return (
        isinstance(name, str)
        and name.endswith(SETTINGS_FILENAME_SUFFIX)
        and len(name) > len(SETTINGS_FILENAME_SUFFIX)
    )


def is_safe_settings_filename(name: str | None) -> bool:
    """True if ``name`` is safe to use as a settings file inside
    ``<save_dir>/agent-settings/``."""
    from talemate.util.path import is_safe_relative_filename

    if not is_safe_relative_filename(name, suffix=SETTINGS_FILENAME_SUFFIX):
        return False
    return is_settings_filename(name)


def list_settings_files(save_dir: Path | str) -> list[str]:
    """Return sorted filenames of all agent-settings JSON files in the
    ``agent-settings/`` subdir under ``save_dir``."""
    settings_dir = agent_settings_dir(save_dir)
    if not settings_dir.exists():
        return []
    return sorted(
        entry.name
        for entry in settings_dir.iterdir()
        if entry.is_file() and is_settings_filename(entry.name)
    )


# ----------------------------------------------------------------------
# Scene wiring helpers
# ----------------------------------------------------------------------
#
# Both load-time auto-linking and user-driven explicit selection live
# here so the scene-side wiring lives in one place and doesn't get
# duplicated between ``load/__init__.py`` and ``world_state/manager.py``.

DEFAULT_SETTINGS_FILENAME = "agent-settings.json"


async def _safe_init_overlay(
    scene: "Scene",
    path: Path,
    filename: str,
) -> bool:
    """Wire ``scene`` to the overlay at ``path`` and try to load it.

    On success populates ``scene.agent_overrides`` and returns True. On any
    load error (unreadable file, malformed JSON, schema mismatch) logs a
    warning, clears the link so the scene falls back to global config, and
    returns False so callers can decide whether to surface the failure.
    """
    scene.agent_settings_file = filename
    scene.agent_overrides = SceneAgentSettings(filepath=path)
    try:
        await scene.agent_overrides.init_from_file()
    except Exception as exc:
        # Broad catch: a corrupt or hand-edited file can raise OSError
        # (disk/perms), ValueError (bad JSON), pydantic.ValidationError
        # (schema), TypeError / AttributeError (e.g. agents value is a
        # string instead of a dict). Whatever the shape, the right fallback
        # is to clear the link and let the scene read global config.
        log.warning(
            "agent settings file unreadable; clearing reference",
            filename=filename,
            error=str(exc),
        )
        scene.agent_settings_file = None
        scene.agent_overrides = None
        return False
    return True


async def _link_default_if_present(scene: "Scene") -> bool:
    """If the default agent-settings file exists, link it.

    Returns True when the link was made. Used by both load-time auto-link
    and the picker's "clear opt-out" path so they stay in sync.
    """
    default_path = agent_settings_dir(scene.save_dir) / DEFAULT_SETTINGS_FILENAME
    if not default_path.exists():
        return False
    return await _safe_init_overlay(scene, default_path, DEFAULT_SETTINGS_FILENAME)


async def resolve_link_on_load(scene: "Scene", scene_data: dict) -> None:
    """Apply the agent-settings link encoded in the loaded scene JSON.

    Rules:
      - ``agent_settings_opted_out: true`` → never auto-link, scene has no overlay.
      - ``agent_settings_file: "..."`` set → load it from ``agent-settings/``.
        Missing file → log a warning and clear the reference; the cleared state
        is persisted on the next scene save.
      - Neither set → auto-link to ``agent-settings/agent-settings.json`` if
        it exists.
    """
    if scene_data.get("agent_settings_opted_out", False):
        scene._agent_settings_opted_out = True
        scene.agent_settings_file = None
        scene.agent_overrides = None
        return

    explicit_file = scene_data.get("agent_settings_file")

    if explicit_file:
        path = agent_settings_dir(scene.save_dir) / explicit_file
        if not path.exists():
            log.warning(
                "agent settings file not found; clearing reference",
                filename=explicit_file,
            )
            scene.agent_settings_file = None
            scene.agent_overrides = None
            return
        if await _safe_init_overlay(scene, path, explicit_file):
            log.info("loaded scene agent overrides", filename=explicit_file)
        return

    if await _link_default_if_present(scene):
        log.info("auto-linked default scene agent overrides")


async def apply_scene_settings_link(
    scene: "Scene",
    filename: str | None | object = UNCHANGED,
    opted_out_clear: bool = False,
) -> None:
    """Apply a user-driven change to the scene's agent-settings link.

    Args:
        filename:
            ``UNCHANGED`` (default) — caller did not touch the link.
            ``None`` — user opted out; no overlay, no auto-link on next load.
            string — link to that file (must exist in
            ``<save_dir>/agent-settings/``).
        opted_out_clear:
            When True (and filename is UNCHANGED), clears any prior opt-out
            so the scene auto-links on next load. Drops any in-memory overlay.
    """
    if filename is not UNCHANGED:
        if filename is None:
            scene._agent_settings_opted_out = True
            scene.agent_settings_file = None
            scene.agent_overrides = None
            return

        if not is_safe_settings_filename(filename):
            raise ValueError(f"Invalid agent settings filename: {filename!r}")

        path = agent_settings_dir(scene.save_dir) / filename
        if not path.exists():
            raise ValueError(f"Agent settings file {filename} does not exist.")
        scene._agent_settings_opted_out = False
        if not await _safe_init_overlay(scene, path, filename):
            raise ValueError(
                f"Failed to load agent settings file {filename}; check the JSON is valid."
            )
        return

    if opted_out_clear:
        scene._agent_settings_opted_out = False
        scene.agent_settings_file = None
        scene.agent_overrides = None
        # If a default file exists, re-link to it immediately so the user
        # sees overrides take effect without reloading the scene.
        await _link_default_if_present(scene)
