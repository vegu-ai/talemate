"""
Audio tags mixin for the TTS agent.

Provides AI-assisted injection of audio tags (e.g. [laughing], [whispering])
into dialogue text for TTS providers that support inline vocal markers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import json
import re

import structlog

from talemate.agents.base import AgentAction, AgentActionConfig
from .schema import Chunk

if TYPE_CHECKING:
    from talemate.agents.summarize import SummarizeAgent

log = structlog.get_logger("talemate.agents.tts.audio_tags")


def only_tags_inserted(original: str, tagged: str, tag_format: str) -> bool:
    """
    Whether `tagged` is `original` with audio tags added and nothing else changed.

    The original's own tags must stay, unchanged and in order. Whitespace is
    ignored entirely: a tag placed after an opening quote leaves `" We` where
    the original had `"We`. A format without both a prefix and a suffix cannot
    be checked, so it never passes.
    """
    prefix, sep, suffix = tag_format.partition("{{ tag }}")
    if not (sep and prefix and suffix):
        return False
    delimiters = re.escape(prefix) + "|" + re.escape(suffix)
    pattern = re.compile(
        re.escape(prefix) + rf"(?:(?!{delimiters})[^\n])+" + re.escape(suffix)
    )

    def bare(text: str) -> str:
        return "".join(pattern.sub("", text).split())

    remaining = iter(pattern.findall(tagged))
    return bare(original) == bare(tagged) and all(
        span in remaining for span in pattern.findall(original)
    )


class AudioTagsMixin:
    """
    Mixin that adds audio-tag injection capabilities to the TTS agent.

    Audio tags are inline markers like [laughing] or [whispering] placed within
    spoken dialogue. An LLM analyses the dialogue and injects tags at natural
    points. Only providers that explicitly support audio tags are eligible.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["audio_tags"] = AgentActionConfig(
            type="bool",
            value=False,
            label="Audio tags",
            description="Use AI to inject audio tags (e.g. [laughing], [whispering]) into dialogue for supported TTS providers. Requires the Summarizer agent.",
            scene_overridable=False,
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

        # Legacy fallback for callers/templates; each entry carries its own format.
        tag_format = self.get_audio_tag_format(eligible_chunks[0][1].api)

        # Build context for the LLM: all chunks for context,
        # but only eligible ones get tagged
        chunk_entries = []
        for i, chunk in enumerate(chunks):
            is_eligible = any(idx == i for idx, _ in eligible_chunks)
            supported_tags = getattr(self, f"{chunk.api}_supported_audio_tags", None)
            style_tags = getattr(self, f"{chunk.api}_style_audio_tags", None)
            chunk_entries.append(
                {
                    "index": i,
                    "text": chunk.text[0] if chunk.text else "",
                    "type": chunk.type,
                    "character_name": chunk.character_name,
                    "eligible": is_eligible,
                    "tag_format": self.get_audio_tag_format(chunk.api),
                    "allowed_tags": supported_tags(model=chunk.model)
                    if is_eligible and supported_tags
                    else None,
                    "style_tags": style_tags(model=chunk.model)
                    if is_eligible and style_tags
                    else None,
                }
            )

        cache_key = json.dumps([tag_format, chunk_entries], sort_keys=True)

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
                    tagged = tagged_chunks[idx]
                    if not only_tags_inserted(
                        chunk.text[0], tagged, chunk_entries[idx]["tag_format"]
                    ):
                        log.warning(
                            "Audio tag response changed the chunk text, keeping the original",
                            chunk_index=idx,
                            original=chunk.text[0],
                            tagged=tagged,
                        )
                        continue
                    allowed_tags = chunk_entries[idx]["allowed_tags"]
                    if allowed_tags is not None:
                        original_tags = set(
                            re.findall(r"\[([^\[\]]+)\]", chunk.text[0])
                        )
                        tagged = re.sub(
                            r"\[([^\[\]]+)\]",
                            lambda match: match[0]
                            if match[1] in allowed_tags or match[1] in original_tags
                            else "",
                            tagged,
                        )
                    log.debug(
                        "Audio tags injected",
                        chunk_index=idx,
                        original=chunk.text[0],
                        tagged=tagged,
                    )
                    chunk.text = [tagged]
