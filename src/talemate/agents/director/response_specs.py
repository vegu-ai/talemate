"""
Response specifications for Director agent prompt responses.

This module defines ResponseSpecs for extracting structured content from
LLM responses in the Director agent.
"""

from talemate.prompts.response import (
    ResponseSpec,
    AnchorExtractor,
    AfterAnchorExtractor,
    CodeBlockExtractor,
)

__all__ = [
    "GUIDANCE_SPEC",
    "CHOICES_SPEC",
    "MESSAGE_SPEC",
    "DECISION_SPEC",
    "ACTIONS_SPEC",
]

# Common patterns for XML-style tag nesting detection
XML_OPENING_TAG_PATTERN = r"<([A-Za-z_][A-Za-z0-9_]*)[^>]*>"
XML_CLOSING_TAG_PATTERN = r"</([A-Za-z_][A-Za-z0-9_]*)[^>]*>"

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
MESSAGE_SPEC = ResponseSpec(
    extractors={
        "message": AnchorExtractor(
            left="<MESSAGE>",
            right="</MESSAGE>",
            opening_tag_pattern=XML_OPENING_TAG_PATTERN,
            closing_tag_pattern=XML_CLOSING_TAG_PATTERN,
        ),
    },
    required=[],
)

# Scene direction - extracts <DECISION> section
DECISION_SPEC = ResponseSpec(
    extractors={
        "decision": AnchorExtractor(
            left="<DECISION>",
            right="</DECISION>",
            stop_at="<ACTIONS>",
            opening_tag_pattern=XML_OPENING_TAG_PATTERN,
            closing_tag_pattern=XML_CLOSING_TAG_PATTERN,
        ),
    },
    required=[],
)

# Action extraction - extracts <ACTIONS> code block
ACTIONS_SPEC = ResponseSpec(
    extractors={
        "actions": CodeBlockExtractor(
            left="<ACTIONS>",
            right="</ACTIONS>",
            validate_structured=True,
            opening_tag_pattern=XML_OPENING_TAG_PATTERN,
            closing_tag_pattern=XML_CLOSING_TAG_PATTERN,
        ),
    },
    required=[],
)
