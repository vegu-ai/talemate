import structlog
from talemate.agents.base import (
    set_processing,
)
from talemate.prompts import Prompt
from talemate.status import set_loading
from talemate.util.dialogue import separate_dialogue_from_exposition

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

        response = await Prompt.request(
            "summarizer.markup-context-for-tts",
            self.client,
            "investigate_1024",
            vars={
                "text": text,
                "max_tokens": self.client.max_token_length,
                "scene": self.scene,
            },
        )

        try:
            response = response.split("<MARKUP>")[1].split("</MARKUP>")[0].strip()
            return response
        except IndexError:
            log.error("Failed to extract markup from response", response=response)
            return original_text
