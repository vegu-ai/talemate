"""
Response specifications for the director chat agent.
"""

from talemate.prompts.response import (
    AnchorExtractor,
    ResponseSpec,
)

__all__ = [
    "CHAT_TITLE_SPEC",
]

CHAT_TITLE_SPEC = ResponseSpec(
    extractors={
        "title": AnchorExtractor(left="<TITLE>", right="</TITLE>"),
    },
    required=[],
)
