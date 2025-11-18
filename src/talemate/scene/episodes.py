"""
Episode management for scenes.

Episodes are stored in episodes.json in the project directory and can be used
to create new scenes from predefined introductions.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pydantic
import structlog

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.scene.episodes")


class Episode(pydantic.BaseModel):
    """A single episode/intro version."""

    intro: str
    title: str | None = None
    description: str | None = None


class EpisodesManager:
    """Manages episodes stored in episodes.json in the project directory."""

    def __init__(self, scene: "Scene"):
        self.scene = scene

    @property
    def episodes_file_path(self) -> Path:
        """Returns the path to episodes.json in the project directory."""
        return Path(self.scene.save_dir) / "episodes.json"

    def _load_episodes(self) -> list[Episode]:
        """Load episodes from episodes.json. Returns empty list if file doesn't exist."""
        episodes_path = self.episodes_file_path

        if not episodes_path.exists():
            return []

        try:
            with open(episodes_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                episodes = data.get("episodes", [])
                return [Episode(**episode) for episode in episodes]
        except (json.JSONDecodeError, IOError, KeyError) as e:
            log.warning(
                "Failed to load episodes",
                error=str(e),
                path=str(episodes_path),
            )
            return []

    def _save_episodes(self, episodes: list[Episode]) -> None:
        """Save episodes to episodes.json."""
        episodes_path = self.episodes_file_path

        # Ensure directory exists
        episodes_path.parent.mkdir(parents=True, exist_ok=True)

        data = {"episodes": [episode.model_dump() for episode in episodes]}

        try:
            with open(episodes_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            log.error("Failed to save episodes", error=str(e), path=str(episodes_path))
            raise

    def get_episodes(self) -> list[Episode]:
        """Get all episodes."""
        return self._load_episodes()

    def add_episode(
        self, intro: str, title: str | None = None, description: str | None = None
    ) -> Episode | None:
        """Add a new episode if it doesn't already exist.

        Checks for duplicates by comparing the intro text (normalized by stripping whitespace).
        Returns the episode if added, or None if a duplicate was found.
        """
        episodes = self._load_episodes()

        # Normalize intro text for comparison (strip whitespace)
        normalized_intro = intro.strip()

        # Check if an episode with the same intro already exists
        for existing_episode in episodes:
            if existing_episode.intro.strip() == normalized_intro:
                log.debug(
                    "Episode with same intro already exists, skipping",
                    intro_preview=normalized_intro[:50] + "..."
                    if len(normalized_intro) > 50
                    else normalized_intro,
                )
                return None

        episode = Episode(intro=intro, title=title, description=description)
        episodes.append(episode)
        self._save_episodes(episodes)
        return episode

    def remove_episode(self, index: int) -> bool:
        """Remove an episode by index. Returns True if successful."""
        episodes = self._load_episodes()
        if 0 <= index < len(episodes):
            episodes.pop(index)
            self._save_episodes(episodes)
            return True
        return False

    def update_episode(
        self,
        index: int,
        intro: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> bool:
        """Update an episode by index. Returns True if successful."""
        episodes = self._load_episodes()
        if 0 <= index < len(episodes):
            episode = episodes[index]
            if intro is not None:
                episode.intro = intro
            if title is not None:
                episode.title = title
            if description is not None:
                episode.description = description
            self._save_episodes(episodes)
            return True
        return False

    def get_episode(self, index: int) -> Episode | None:
        """Get an episode by index. Returns None if index is out of bounds."""
        episodes = self._load_episodes()
        if 0 <= index < len(episodes):
            return episodes[index]
        return None
