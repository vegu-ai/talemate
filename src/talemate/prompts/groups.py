"""
Prompt template group management.

This module provides functionality for managing prompt template groups,
including group discovery, template listing, and resolution logic that
determines which template to use based on priority settings.

Groups are collections of templates that can override the default templates.
The resolution order is:
1. Scene templates (highest priority when scene is loaded)
2. Explicit template_sources override (if set in config)
3. Walk group_priority list
4. Fall back to default

Directory structure:
- default: src/talemate/prompts/templates/{agent}/
- user: ./templates/prompts/{agent}/
- Custom groups: ./templates/prompt_groups/{group}/{agent}/
- Scene templates: {scene.template_dir}/{agent}/ (with fallback to flat structure)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.prompts.groups")

# Directory containing the default templates
_PROMPTS_DIR = Path(__file__).parent / "templates"

# User templates directory (relative to CWD)
_USER_TEMPLATES_DIR = Path("./templates/prompts")

# Custom groups directory (relative to CWD)
_CUSTOM_GROUPS_DIR = Path("./templates/prompt_groups")


class TemplateInfo(BaseModel):
    """Information about a single template."""

    agent: str
    name: str  # without .jinja2
    uid: str  # "{agent}.{name}"
    source_group: str  # which group it's currently loaded from
    available_in: list[str]  # all groups that have this template
    is_outdated: bool = False
    is_unresolvable: bool = False  # True when template only exists in inactive groups
    default_mtime: float | None = None
    override_mtime: float | None = None


class GroupInfo(BaseModel):
    """Information about a template group."""

    name: str
    path: str  # path as string for JSON serialization
    is_active: bool
    is_readonly: bool  # True for "default"
    template_count: int


def _get_config():
    """Get the application config. Lazy import to avoid circular dependencies."""
    from talemate.config import get_config

    return get_config()


def get_default_template_path(agent: str, template_name: str) -> Path:
    """
    Get template path from built-in defaults.

    Args:
        agent: The agent type (e.g., "narrator", "director")
        template_name: The template name without .jinja2 extension

    Returns:
        Path to the template file
    """
    return _PROMPTS_DIR / agent / f"{template_name}.jinja2"


def get_user_template_path(agent: str, template_name: str) -> Path:
    """
    Get template path from user templates directory.

    Args:
        agent: The agent type (e.g., "narrator", "director")
        template_name: The template name without .jinja2 extension

    Returns:
        Path to the template file
    """
    return _USER_TEMPLATES_DIR / agent / f"{template_name}.jinja2"


def get_group_template_path(group: str, agent: str, template_name: str) -> Path:
    """
    Get template path for a specific group.

    Args:
        group: The group name ("user" or a custom group name)
        agent: The agent type (e.g., "narrator", "director")
        template_name: The template name without .jinja2 extension

    Returns:
        Path to the template file
    """
    if group == "user":
        return get_user_template_path(agent, template_name)
    elif group == "default":
        return get_default_template_path(agent, template_name)
    else:
        return _CUSTOM_GROUPS_DIR / group / agent / f"{template_name}.jinja2"


def get_scene_template_path(
    scene: "Scene", agent: str, template_name: str
) -> Path | None:
    """
    Get template path from scene-specific templates.

    Checks for templates in {scene.template_dir}/{agent}/ first,
    then falls back to {scene.template_dir}/ for backward compatibility.

    Args:
        scene: The active scene
        agent: The agent type (e.g., "narrator", "director")
        template_name: The template name without .jinja2 extension

    Returns:
        Path to the template file (may not exist), or None if scene.template_dir is invalid
    """
    # Validate that template_dir is a valid string path
    template_dir = getattr(scene, "template_dir", None)
    if not isinstance(template_dir, str):
        return None

    # First, try the agent-specific subdirectory (new structure)
    agent_path = Path(template_dir) / agent / f"{template_name}.jinja2"
    if agent_path.exists():
        return agent_path

    # Fall back to flat structure (backward compatibility)
    flat_path = Path(template_dir) / f"{template_name}.jinja2"
    return flat_path


def resolve_template(
    agent: str, template_name: str, scene: "Scene | None" = None
) -> tuple[Path | None, str | None]:
    """
    Resolve template path using priority order.

    Args:
        agent: The agent type (e.g., "narrator", "director")
        template_name: The template name without .jinja2 extension
        scene: The active scene (optional)

    Returns:
        Tuple of (path, source_group) or (None, None) if not found

    Priority:
    1. Scene templates (always highest when scene loaded)
    2. Explicit template_sources override
    3. Walk group_priority list
    4. Fall back to default group
    """
    uid = f"{agent}.{template_name}"
    config = _get_config()

    # Get prompts config, with safe defaults if not present
    prompts_config = getattr(config, "prompts", None)

    # 1. Scene templates (highest priority)
    if scene:
        path = get_scene_template_path(scene, agent, template_name)
        if path is not None and path.exists():
            return path, "scene"

    # 2. Explicit override in template_sources?
    if prompts_config:
        template_sources = getattr(prompts_config, "template_sources", {}) or {}
        if uid in template_sources:
            group = template_sources[uid]
            path = get_group_template_path(group, agent, template_name)
            if path.exists():
                return path, group
            # Configured source missing - log warning, continue resolution
            log.warning(
                "Template configured for group but not found, falling back",
                template=uid,
                group=group,
            )

    # 3. Walk priority list
    if prompts_config:
        group_priority = getattr(prompts_config, "group_priority", []) or []
        for group in group_priority:
            path = get_group_template_path(group, agent, template_name)
            if path.exists():
                return path, group

    # 4. Fall back to default
    path = get_default_template_path(agent, template_name)
    if path.exists():
        return path, "default"

    return None, None


def list_groups(scene: "Scene | None" = None) -> list[GroupInfo]:
    """
    List all available template groups.

    Args:
        scene: The active scene (optional). If provided, includes scene group.

    Returns:
        List of GroupInfo objects describing available groups
    """
    config = _get_config()
    prompts_config = getattr(config, "prompts", None)
    group_priority = (
        getattr(prompts_config, "group_priority", []) if prompts_config else []
    ) or []

    groups = []

    # Scene group (only when scene loaded)
    if scene:
        scene_template_dir = Path(scene.template_dir)
        template_count = _count_templates_in_directory(scene_template_dir)
        groups.append(
            GroupInfo(
                name="scene",
                path=str(scene_template_dir),
                is_active=True,  # Scene group is always active when present
                is_readonly=False,
                template_count=template_count,
            )
        )

    # User group
    user_path = _USER_TEMPLATES_DIR.resolve()
    user_template_count = _count_templates_in_directory(user_path)
    groups.append(
        GroupInfo(
            name="user",
            path=str(user_path),
            is_active="user" in group_priority,
            is_readonly=False,
            template_count=user_template_count,
        )
    )

    # Custom groups from prompt_groups directory
    if _CUSTOM_GROUPS_DIR.exists():
        for group_dir in sorted(_CUSTOM_GROUPS_DIR.iterdir()):
            if group_dir.is_dir():
                template_count = _count_templates_in_directory(group_dir)
                groups.append(
                    GroupInfo(
                        name=group_dir.name,
                        path=str(group_dir.resolve()),
                        is_active=group_dir.name in group_priority,
                        is_readonly=False,
                        template_count=template_count,
                    )
                )

    # Default group (always present, always last)
    default_path = _PROMPTS_DIR.resolve()
    default_template_count = _count_templates_in_directory(default_path)
    groups.append(
        GroupInfo(
            name="default",
            path=str(default_path),
            is_active=True,  # Default is always active (implicit fallback)
            is_readonly=True,
            template_count=default_template_count,
        )
    )

    return groups


def _count_templates_in_directory(directory: Path) -> int:
    """
    Count .jinja2 template files in a directory and its subdirectories.

    Args:
        directory: The directory to search

    Returns:
        Count of .jinja2 files
    """
    if not directory.exists():
        return 0

    count = 0
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".jinja2"):
                count += 1
    return count


def _get_file_mtime(path: Path) -> float | None:
    """
    Safely get file modification time.

    Args:
        path: The file path to check

    Returns:
        Modification time as float, or None if file doesn't exist
    """
    try:
        return path.stat().st_mtime if path.exists() else None
    except OSError:
        return None


def list_templates(
    scene: "Scene | None" = None, include_sources: bool = True
) -> list[TemplateInfo]:
    """
    List all templates with their current source group.

    Walks all groups and default to build complete template list.

    Args:
        scene: The active scene (optional)
        include_sources: If True, includes available_in info (default True)

    Returns:
        List of TemplateInfo objects describing all available templates
    """
    # Build a map of all templates and where they're available
    template_map: dict[str, dict] = {}  # uid -> {agent, name, available_in}

    # Helper to scan a directory for templates
    def scan_directory(directory: Path, group: str, is_flat: bool = False):
        if not directory.exists():
            return

        for root, _, files in os.walk(directory):
            root_path = Path(root)

            for filename in files:
                if not filename.endswith(".jinja2"):
                    continue

                template_name = filename[:-7]  # Remove .jinja2

                if is_flat:
                    # Flat structure (scene templates backward compatibility)
                    # Use empty string for agent since we don't know the agent
                    agent = ""
                else:
                    # Agent subdirectory structure
                    try:
                        relative_parts = root_path.relative_to(directory).parts
                        agent = relative_parts[0]
                        # Include subdirectory path in template_name for nested templates
                        subpath = "/".join(relative_parts[1:])
                        if subpath:
                            template_name = f"{subpath}/{template_name}"
                    except (ValueError, IndexError):
                        # Template is directly in the group directory, not in agent subdir
                        continue

                uid = f"{agent}.{template_name}" if agent else template_name

                if uid not in template_map:
                    template_map[uid] = {
                        "agent": agent,
                        "name": template_name,
                        "available_in": [],
                    }

                if include_sources:
                    template_map[uid]["available_in"].append(group)

    # Scan default templates first (to establish baseline)
    scan_directory(_PROMPTS_DIR, "default")

    # Scan user templates
    scan_directory(_USER_TEMPLATES_DIR, "user")

    # Scan custom groups
    if _CUSTOM_GROUPS_DIR.exists():
        for group_dir in _CUSTOM_GROUPS_DIR.iterdir():
            if group_dir.is_dir():
                scan_directory(group_dir, group_dir.name)

    # Scan scene templates if scene is loaded
    if scene:
        scene_template_dir = Path(scene.template_dir)
        # Scan agent subdirectories
        scan_directory(scene_template_dir, "scene")
        # Also scan flat structure for backward compatibility
        if scene_template_dir.exists():
            for filename in os.listdir(scene_template_dir):
                filepath = scene_template_dir / filename
                if filepath.is_file() and filename.endswith(".jinja2"):
                    template_name = filename[:-7]
                    # For flat scene templates, we don't know the agent
                    # They will be found via the prepended_template_dirs mechanism
                    # Just add them with empty agent for now
                    uid = f".{template_name}"
                    if uid not in template_map:
                        template_map[uid] = {
                            "agent": "",
                            "name": template_name,
                            "available_in": ["scene"] if include_sources else [],
                        }
                    elif "scene" not in template_map[uid].get("available_in", []):
                        template_map[uid]["available_in"].append("scene")

    # Build result list with resolved source groups
    templates = []
    for uid, info in sorted(template_map.items()):
        agent = info["agent"]
        template_name = info["name"]
        available_in = info.get("available_in", [])

        # Resolve which group this template will actually load from
        if agent:
            _, source_group = resolve_template(agent, template_name, scene)
        else:
            # For flat scene templates, source is always scene
            source_group = "scene" if scene else "default"

        # Mark templates that can't be resolved (only exist in inactive groups)
        is_unresolvable = not source_group
        if is_unresolvable:
            source_group = available_in[0] if available_in else "unknown"

        # Calculate mtime and outdated status for overrides
        is_outdated = False
        default_mtime = None
        override_mtime = None

        # Only calculate mtimes for templates that have overrides
        # (where source_group != "default" and "default" is in available_in)
        if source_group != "default" and "default" in available_in and agent:
            default_path = get_default_template_path(agent, template_name)
            default_mtime = _get_file_mtime(default_path)

            # Get the override path from the source group
            if source_group == "scene" and scene:
                override_path = get_scene_template_path(scene, agent, template_name)
            else:
                override_path = get_group_template_path(
                    source_group, agent, template_name
                )

            if override_path:
                override_mtime = _get_file_mtime(override_path)

            # Determine if outdated: override is older than default
            if default_mtime is not None and override_mtime is not None:
                is_outdated = override_mtime < default_mtime

        templates.append(
            TemplateInfo(
                agent=agent,
                name=template_name,
                uid=uid,
                source_group=source_group,
                available_in=available_in,
                is_outdated=is_outdated,
                is_unresolvable=is_unresolvable,
                default_mtime=default_mtime,
                override_mtime=override_mtime,
            )
        )

    return templates


def get_template_content(
    group: str, agent: str, template_name: str, scene: "Scene | None" = None
) -> str | None:
    """
    Get template content from a specific group.

    Args:
        group: The group name ("default", "user", "scene", or custom group)
        agent: The agent type
        template_name: The template name without .jinja2 extension
        scene: The active scene (required if group is "scene")

    Returns:
        Template content as string, or None if not found
    """
    if group == "scene":
        if not scene:
            return None
        path = get_scene_template_path(scene, agent, template_name)
    else:
        path = get_group_template_path(group, agent, template_name)

    if path is not None and path.exists():
        return path.read_text(encoding="utf-8")
    return None


def write_template(
    group: str,
    agent: str,
    template_name: str,
    content: str,
    scene: "Scene | None" = None,
) -> None:
    """
    Write template to a group (creates override if needed).

    Args:
        group: The group name (cannot be "default")
        agent: The agent type
        template_name: The template name without .jinja2 extension
        content: The template content
        scene: The active scene (required if group is "scene")

    Raises:
        ValueError: If trying to write to "default" group
        ValueError: If group is "scene" but no scene provided
    """
    if group == "default":
        raise ValueError("Cannot write to default group (read-only)")

    if group == "scene":
        if not scene:
            raise ValueError("Scene is required when writing to scene group")
        # Use agent subdirectory for new scene templates
        path = Path(scene.template_dir) / agent / f"{template_name}.jinja2"
    else:
        path = get_group_template_path(group, agent, template_name)

    # Create directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write the template
    path.write_text(content, encoding="utf-8")
    log.info(
        "Template written",
        group=group,
        agent=agent,
        template=template_name,
        path=str(path),
    )


def delete_template(
    group: str, agent: str, template_name: str, scene: "Scene | None" = None
) -> bool:
    """
    Delete template override from a group.

    Args:
        group: The group name (cannot be "default")
        agent: The agent type
        template_name: The template name without .jinja2 extension
        scene: The active scene (required if group is "scene")

    Returns:
        True if deleted, False if not found

    Raises:
        ValueError: If trying to delete from "default" group
        ValueError: If group is "scene" but no scene provided
    """
    if group == "default":
        raise ValueError("Cannot delete from default group (read-only)")

    if group == "scene":
        if not scene:
            raise ValueError("Scene is required when deleting from scene group")
        # Check both agent subdirectory and flat structure
        path = Path(scene.template_dir) / agent / f"{template_name}.jinja2"
        if not path.exists():
            path = Path(scene.template_dir) / f"{template_name}.jinja2"
    else:
        path = get_group_template_path(group, agent, template_name)

    if path.exists():
        path.unlink()
        log.info(
            "Template deleted",
            group=group,
            agent=agent,
            template=template_name,
            path=str(path),
        )
        return True

    return False


def create_group(name: str) -> GroupInfo:
    """
    Create a new template group.

    Args:
        name: The group name (must not be "default", "user", or "scene")

    Returns:
        GroupInfo for the created group

    Raises:
        ValueError: If name is reserved or group already exists
    """
    if name in ("default", "user", "scene"):
        raise ValueError(f"Cannot create group with reserved name: {name}")

    group_path = _CUSTOM_GROUPS_DIR / name
    if group_path.exists():
        raise ValueError(f"Group already exists: {name}")

    group_path.mkdir(parents=True, exist_ok=True)
    log.info("Group created", group=name, path=str(group_path))

    return GroupInfo(
        name=name,
        path=str(group_path.resolve()),
        is_active=False,
        is_readonly=False,
        template_count=0,
    )


def delete_group(name: str, force: bool = False) -> bool:
    """
    Delete a template group.

    Args:
        name: The group name (must not be "default", "user", or "scene")
        force: If True, delete even if group contains templates

    Returns:
        True if deleted

    Raises:
        ValueError: If name is reserved
        ValueError: If group has templates and force is False
        FileNotFoundError: If group doesn't exist
    """
    if name in ("default", "user", "scene"):
        raise ValueError(f"Cannot delete reserved group: {name}")

    group_path = _CUSTOM_GROUPS_DIR / name
    if not group_path.exists():
        raise FileNotFoundError(f"Group not found: {name}")

    template_count = _count_templates_in_directory(group_path)
    if template_count > 0 and not force:
        raise ValueError(
            f"Group '{name}' contains {template_count} templates. Use force=True to delete."
        )

    import shutil

    shutil.rmtree(group_path)
    log.info("Group deleted", group=name, path=str(group_path))

    return True
