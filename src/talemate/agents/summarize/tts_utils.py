import structlog
from talemate.agents.base import (
    set_processing,
)
from talemate.prompts import Prompt
from talemate.status import set_loading
from talemate.util import count_tokens
from talemate.util.dialogue import separate_dialogue_from_exposition
from .response_specs import MARKUP_SPEC, AUDIO_TAGS_SPEC

log = structlog.get_logger("talemate.agents.summarize.tts_utils")


class TTSUtilsMixin:
    """
    Summarizer Mixin for text-to-speech utilities.
    """

    @set_loading("Preparing TTS context")
    @set_processing
    async def markup_context_for_tts(self, text: str) -> str:
        """
        Markup the context for text-to-speech.
        """

        original_text = text

        log.debug("Markup context for TTS", text=text)

        # if there are no quotes in the text, there is nothing to separate
        if '"' not in text:
            return original_text

        # here we separate dialogue from exposition because into
        # obvious segments. It seems to have a positive effect on some
        # LLMs returning the complete text.
        separate_chunks = separate_dialogue_from_exposition(text)

        numbered_chunks = []
        for i, chunk in enumerate(separate_chunks):
            numbered_chunks.append(f"[{i + 1}] {chunk.text.strip()}")

        text = "\n".join(numbered_chunks)

        response, extracted = await Prompt.request(
            "summarizer.markup-context-for-tts",
            self.client,
            "investigate_1024",
            vars={
                "text": text,
                "max_tokens": self.client.max_token_length,
                "scene": self.scene,
            },
            response_spec=MARKUP_SPEC,
        )

        markup = extracted["markup"]
        if not markup:
            log.error("Failed to extract markup from response", response=response)
            return original_text
        return markup

    @set_loading("Injecting audio tags")
    @set_processing
    async def inject_audio_tags_for_tts(
        self,
        chunk_entries: list[dict],
        tag_format: str = "[{{ tag }}]",
    ) -> dict[int, str] | None:
        """
        Analyze dialogue chunks and inject audio tags for TTS providers
        that support them.

        Args:
            chunk_entries: List of dicts with keys: index, text, type,
                          character_name, eligible
            tag_format: Jinja2 template for formatting tags

        Returns:
            Dict mapping chunk index to tagged text, or None if injection failed.
        """

        if not any(entry["eligible"] for entry in chunk_entries):
            return None

        # Response needs enough room for the text plus tags overhead
        text_tokens = count_tokens([entry["text"] for entry in chunk_entries])
        response_tokens = text_tokens + 1024

        log.debug(
            "Injecting audio tags for TTS",
            tag_format=tag_format,
            response_tokens=response_tokens,
        )

        response, extracted = await Prompt.request(
            "summarizer.inject-audio-tags-for-tts",
            self.client,
            f"investigate_{response_tokens}",
            vars={
                "chunk_entries": chunk_entries,
                "tag_format": tag_format,
                "max_tokens": self.client.max_token_length,
                "scene": self.scene,
            },
            response_spec=AUDIO_TAGS_SPEC,
        )

        # Template defines per-chunk extractors: chunk_0, chunk_2, etc.
        result = {}
        for key, value in extracted.items():
            if key.startswith("chunk_") and value:
                try:
                    idx = int(key.split("_", 1)[1])
                    result[idx] = value
                except (ValueError, IndexError):
                    continue

        if not result:
            log.error("Failed to extract audio tags from response", response=response)
            return None
        return result
