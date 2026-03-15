"""
Audio tags mixin for the TTS agent.

Provides AI-assisted injection of audio tags (e.g. [laughing], [whispering])
into dialogue text for TTS providers that support inline vocal markers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from talemate.agents.base import AgentAction, AgentActionConfig
from .schema import Chunk

if TYPE_CHECKING:
    from talemate.agents.summarize import SummarizeAgent

log = structlog.get_logger("talemate.agents.tts.audio_tags")


class AudioTagsMixin:
    """
    Mixin that adds audio-tag injection capabilities to the TTS agent.

    Audio tags are inline markers like [laughing] or [whispering] placed within
    spoken dialogue. An LLM analyses the dialogue and injects tags at natural
    points. Only providers that explicitly support audio tags (currently
    ElevenLabs v3) are eligible.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["audio_tags"] = AgentActionConfig(
            type="bool",
            value=False,
            label="Audio tags",
            description="Use AI to inject audio tags (e.g. [laughing], [whispering]) into dialogue for supported TTS providers. Requires the Summarizer agent.",
        )
        return actions

    # -- config property --

    @property
    def audio_tags(self) -> bool:
        return self.actions["_config"].config["audio_tags"].value

    # -- cache --

    async def get_audio_tags_cache(self, key: str) -> dict[int, str] | None:
        """
        Returns the cached audio tag results for the given cache key.
        """
        fp = hash(key)
        cached = self.get_scene_state("tts_audio_tags_cache")
        if cached and cached.get("fp") == fp:
            return cached.get("tagged")
        return None

    async def set_audio_tags_cache(self, key: str, tagged: dict[int, str]):
        fp = hash(key)
        self.set_scene_states(
            tts_audio_tags_cache={
                "fp": fp,
                "tagged": tagged,
            }
        )

    # -- helpers --

    def _api_supports_audio_tags(self, api: str) -> bool:
        """Check if an API supports audio tags using its default model."""
        fn = getattr(self, f"{api}_supports_audio_tags", None)
        if fn is None:
            return False
        return fn()

    def chunk_supports_audio_tags(self, chunk: Chunk) -> bool:
        """Check if a chunk's target provider supports audio tags.

        Takes into account the per-voice model override (chunk.model)
        which may differ from the provider's default model.
        """
        if not chunk.api:
            return False
        fn = getattr(self, f"{chunk.api}_supports_audio_tags", None)
        if fn is None:
            return False
        return fn(model=chunk.model)

    def get_audio_tag_format(self, api: str) -> str:
        """Get the audio tag format template for a provider."""
        return getattr(self, f"{api}_audio_tag_format", "[{{ tag }}]")

    # -- pipeline step --

    async def _inject_audio_tags(
        self, chunks: list[Chunk], summarizer: "SummarizeAgent"
    ):
        """
        Inject audio tags into eligible dialogue chunks.

        Runs after speaker separation and voice routing, before size-chunking.
        Modifies chunk text in-place.
        """

        if not self.audio_tags or not chunks:
            return

        eligible_chunks = [
            (i, chunk)
            for i, chunk in enumerate(chunks)
            if chunk.type == "dialogue" and self.chunk_supports_audio_tags(chunk)
        ]

        if not eligible_chunks:
            return

        # Determine the tag format from the first eligible provider
        tag_format = self.get_audio_tag_format(eligible_chunks[0][1].api)

        # Build context for the LLM: all chunks for context,
        # but only eligible ones get tagged
        chunk_entries = []
        for i, chunk in enumerate(chunks):
            is_eligible = any(idx == i for idx, _ in eligible_chunks)
            chunk_entries.append(
                {
                    "index": i,
                    "text": chunk.text[0] if chunk.text else "",
                    "type": chunk.type,
                    "character_name": chunk.character_name,
                    "eligible": is_eligible,
                }
            )

        # Cache key based on eligible chunk texts
        cache_key = "|".join(chunk.text[0] for _, chunk in eligible_chunks)

        tagged_chunks = await self.get_audio_tags_cache(cache_key)

        if tagged_chunks is None:
            tagged_chunks = await summarizer.inject_audio_tags_for_tts(
                chunk_entries=chunk_entries,
                tag_format=tag_format,
            )
            if tagged_chunks:
                await self.set_audio_tags_cache(cache_key, tagged_chunks)

        if tagged_chunks:
            for idx, chunk in eligible_chunks:
                if idx in tagged_chunks:
                    log.debug(
                        "Audio tags injected",
                        chunk_index=idx,
                        original=chunk.text[0],
                        tagged=tagged_chunks[idx],
                    )
                    chunk.text = [tagged_chunks[idx]]
