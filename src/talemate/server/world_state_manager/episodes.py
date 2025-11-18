import pydantic
import structlog

log = structlog.get_logger("talemate.server.world_state_manager.episodes")


class EpisodesPayload(pydantic.BaseModel):
    episodes: list[dict] = pydantic.Field(default_factory=list)


class SetIntroPayload(pydantic.BaseModel):
    intro: str


class AddEpisodePayload(pydantic.BaseModel):
    intro: str
    title: str | None = None
    description: str | None = None


class RemoveEpisodePayload(pydantic.BaseModel):
    index: int


class UpdateEpisodePayload(pydantic.BaseModel):
    index: int
    intro: str | None = None
    title: str | None = None
    description: str | None = None


class EpisodesMixin:
    """Mixin adding websocket handlers for episode management."""

    async def handle_get_episodes(self, data):
        """Get the list of episodes."""
        episodes = self.scene.episodes.get_episodes()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "episodes",
                "data": {"episodes": [episode.model_dump() for episode in episodes]},
            }
        )

    async def handle_set_intro(self, data):
        """Set the scene intro from a selected episode."""
        payload = SetIntroPayload(**data)
        self.scene.intro = payload.intro

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "intro_set",
                "data": payload.model_dump(),
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_add_episode(self, data):
        """Add a new episode."""
        payload = AddEpisodePayload(**data)
        self.scene.episodes.add_episode(
            intro=payload.intro,
            title=payload.title,
            description=payload.description,
        )

        episodes = self.scene.episodes.get_episodes()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "episodes",
                "data": {"episodes": [ep.model_dump() for ep in episodes]},
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_remove_episode(self, data):
        """Remove an episode by index."""
        payload = RemoveEpisodePayload(**data)
        self.scene.episodes.remove_episode(payload.index)

        episodes = self.scene.episodes.get_episodes()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "episodes",
                "data": {"episodes": [ep.model_dump() for ep in episodes]},
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_update_episode(self, data):
        """Update an episode by index."""
        payload = UpdateEpisodePayload(**data)
        self.scene.episodes.update_episode(
            index=payload.index,
            intro=payload.intro,
            title=payload.title,
            description=payload.description,
        )

        episodes = self.scene.episodes.get_episodes()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "episodes",
                "data": {"episodes": [ep.model_dump() for ep in episodes]},
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_add_episode_from_current(self, data):
        """Add the current scene intro as a new episode."""
        current_intro = self.scene.intro or ""
        self.scene.episodes.add_episode(intro=current_intro)

        episodes = self.scene.episodes.get_episodes()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "episodes",
                "data": {"episodes": [ep.model_dump() for ep in episodes]},
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()
