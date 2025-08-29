"""
Auto backup functionality for scenes.

Similar to auto save, but creates rolling backup files instead of overwriting the main save.
"""

import json
import os
import datetime
from typing import TYPE_CHECKING

import structlog

from talemate.config import get_config
from talemate import save

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.auto_backup")


async def auto_backup(scene: "Scene") -> None:
    """
    Creates an automatic backup of the scene.

    Unlike save_as, this function:
    - Does not create a new memory database
    - Saves to a dedicated backups directory
    - Maintains a rolling set of backup files
    - Only proceeds if auto_backup is enabled in config

    Args:
        scene: The scene instance to backup
    """
    config = get_config()

    # Check if auto backup is enabled
    if not config.game.general.auto_backup:
        log.debug("Auto backup disabled, skipping")
        return

    # Skip if scene has never been saved (no filename or name)
    if not scene.filename or not scene.name:
        log.debug("Scene has never been saved, skipping auto backup")
        return

    max_backups = config.game.general.auto_backup_max_backups
    log.debug("Creating auto backup", filename=scene.filename, max_backups=max_backups)

    # Create backups directory structure
    backups_dir = os.path.join(scene.save_dir, "backups")
    os.makedirs(backups_dir, exist_ok=True)

    # Generate backup filename with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(scene.filename)[0]
    backup_filename = f"{base_name}_backup_{timestamp}.json"
    backup_filepath = os.path.join(backups_dir, backup_filename)

    # Get scene data (same as normal save)
    scene_data = scene.serialize

    # Write backup file
    try:
        with open(backup_filepath, "w") as f:
            json.dump(scene_data, f, indent=2, cls=save.SceneEncoder)

        log.info("Auto backup created", backup_file=backup_filename)

        # Clean up old backups
        await _cleanup_old_backups(backups_dir, base_name, max_backups)
    except OSError as e:
        log.error("Failed to create auto backup", backup_file=backup_filename, error=e)


async def _cleanup_old_backups(
    backups_dir: str, base_name: str, max_backups: int
) -> None:
    """
    Removes old backup files, keeping only the most recent max_backups files.

    Args:
        backups_dir: Directory containing backup files
        base_name: Base name of the scene file (without extension)
        max_backups: Maximum number of backup files to keep
    """
    if max_backups <= 0:
        return

    try:
        # Find all backup files for this scene
        backup_files = []
        for filename in os.listdir(backups_dir):
            if filename.startswith(f"{base_name}_backup_") and filename.endswith(
                ".json"
            ):
                filepath = os.path.join(backups_dir, filename)
                # Get modification time for sorting
                mtime = os.path.getmtime(filepath)
                backup_files.append((mtime, filepath))

        # Sort by modification time (newest first)
        backup_files.sort(reverse=True)

        # Remove excess backup files
        for _, filepath in backup_files[max_backups:]:
            try:
                os.remove(filepath)
                log.debug("Removed old backup", filepath=filepath)
            except OSError as e:
                log.warning("Failed to remove old backup", filepath=filepath, error=e)

    except OSError as e:
        log.warning("Failed to cleanup old backups", backups_dir=backups_dir, error=e)


def get_backup_files(scene: "Scene") -> list[dict]:
    """
    Returns a list of backup files for the given scene.

    Args:
        scene: The scene instance

    Returns:
        List of dicts with backup file information (name, path, timestamp)
    """
    if not scene.filename or not scene.name:
        return []

    backups_dir = os.path.join(scene.save_dir, "backups")
    if not os.path.exists(backups_dir):
        return []

    base_name = os.path.splitext(scene.filename)[0]
    backup_files = []

    try:
        for filename in os.listdir(backups_dir):
            if filename.startswith(f"{base_name}_backup_") and filename.endswith(
                ".json"
            ):
                filepath = os.path.join(backups_dir, filename)
                mtime = os.path.getmtime(filepath)
                backup_files.append(
                    {
                        "name": filename,
                        "path": filepath,
                        "timestamp": datetime.datetime.fromtimestamp(mtime).isoformat(),
                        "size": os.path.getsize(filepath),
                    }
                )

        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x["timestamp"], reverse=True)

    except OSError as e:
        log.warning("Failed to list backup files", backups_dir=backups_dir, error=e)

    return backup_files
