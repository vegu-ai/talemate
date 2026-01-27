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

# Guide scene methods - extracts <GUIDANCE> section
GUIDANCE_SPEC = ResponseSpec(
    extractors={
        "guidance": AnchorExtractor(
            left="<GUIDANCE>",
            right="</GUIDANCE>",
            prefer_after="</ANALYSIS>",
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
            prefer_after="</ANALYSIS>",
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
            prefer_after="</ANALYSIS>",
            stop_at="<ACTIONS>",
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
            prefer_after="</ANALYSIS>",
            validate_structured=True,
        ),
    },
    required=[],
)
