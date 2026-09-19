"""
Response specifications for Summarizer agent prompt responses.

This module defines ResponseSpecs for extracting structured content from
LLM responses in the Summarizer agent.
"""

from talemate.prompts.response import (
    ResponseSpec,
    AnchorExtractor,
    AfterAnchorExtractor,
    StripPrefixExtractor,
)

__all__ = [
    "SUMMARY_SPEC",
    "MARKUP_SPEC",
    "AUDIO_TAGS_SPEC",
    "CHUNK_CLEAN_SPEC",
]

# For extracting content after "SUMMARY:" prefix
# Used in summarize() and summarize_director_chat()
SUMMARY_SPEC = ResponseSpec(
    extractors={
        "summary": AfterAnchorExtractor(start="SUMMARY:"),
    },
    required=[],  # Falls back to full response if not found
)

# For extracting content from <MARKUP>...</MARKUP> tags
# Used in markup_context_for_tts()
MARKUP_SPEC = ResponseSpec(
    extractors={
        "markup": AnchorExtractor(left="<MARKUP>", right="</MARKUP>"),
    },
    required=[],  # Handle None case in code - will fall back to original text
)

# Base spec for audio tag injection responses.
# The template extends this with per-chunk extractors (chunk_0, chunk_2, etc.)
# via set_anchor_extractor() calls.
AUDIO_TAGS_SPEC = ResponseSpec(
    extractors={},
    required=[],
)

# For cleaning up chunk prefixes like "CHUNK 1:", "CHAPTER 2:" from responses
# Used in summarize_events()
CHUNK_CLEAN_SPEC = ResponseSpec(
    extractors={
        "cleaned": StripPrefixExtractor(pattern=r"(CHUNK|CHAPTER) \d+:\s+"),
    },
    required=[],
)
