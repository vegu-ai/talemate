"""
Response specifications for Director agent prompt responses.

This module defines ResponseSpecs for extracting structured content from
LLM responses in the Director agent.
"""

from talemate.prompts.response import (
    ResponseSpec,
    AnchorExtractor,
    ComplexAnchorExtractor,
    AfterAnchorExtractor,
    ComplexCodeBlockExtractor,
)

__all__ = [
    "GUIDANCE_SPEC",
    "CHOICES_SPEC",
    "MESSAGE_SPEC",
    "DECISION_SPEC",
    "ACTIONS_SPEC",
]

# Common tracked tags for nesting awareness
COMMON_TRACKED_TAGS = ["ANALYSIS", "MESSAGE", "DECISION", "ACTIONS"]

# Guide scene methods - extracts <GUIDANCE> section
GUIDANCE_SPEC = ResponseSpec(
    extractors={
        "guidance": AnchorExtractor(
            left="<GUIDANCE>",
            right="</GUIDANCE>",
        ),
    },
    required=[],  # Falls back to full response if not found
)

# Generate choices - extracts content after "ACTIONS:" marker
CHOICES_SPEC = ResponseSpec(
    extractors={
        "actions": AfterAnchorExtractor(start="ACTIONS:"),
    },
    required=[],
)

# Director chat/action_core - extracts <MESSAGE> section
# Uses ComplexAnchorExtractor to handle nesting (MESSAGE inside ANALYSIS should be ignored)
MESSAGE_SPEC = ResponseSpec(
    extractors={
        "message": ComplexAnchorExtractor(
            left="<MESSAGE>",
            right="</MESSAGE>",
            tracked_tags=COMMON_TRACKED_TAGS,
        ),
    },
    required=[],
)

# Scene direction - extracts <DECISION> section
# Uses ComplexAnchorExtractor with tracked_tags (replaces stop_at behavior)
DECISION_SPEC = ResponseSpec(
    extractors={
        "decision": ComplexAnchorExtractor(
            left="<DECISION>",
            right="</DECISION>",
            tracked_tags=COMMON_TRACKED_TAGS,
        ),
    },
    required=[],
)

# Action extraction - extracts <ACTIONS> code block
# Uses ComplexCodeBlockExtractor for nesting-aware extraction
ACTIONS_SPEC = ResponseSpec(
    extractors={
        "actions": ComplexCodeBlockExtractor(
            left="<ACTIONS>",
            right="</ACTIONS>",
            validate_structured=True,
            tracked_tags=COMMON_TRACKED_TAGS,
        ),
    },
    required=[],
)
