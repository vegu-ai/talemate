"""
Response specifications for the conversation agent's knowledge opt-ins.
"""

import re

from talemate.prompts.response import (
    AnchorExtractor,
    BlockListExtractor,
    RegexExtractor,
    ResponseSpec,
)

__all__ = [
    "MEMORY_PASS_SPEC",
]

# a truncated last item is dropped: a rewrite cut mid-sentence can state the
# opposite of its candidate, and it would reach the speaker as knowledge;
# none counts only as the whole <ITEMS> content, so a contradictory or cut-off
# answer reads as unreadable and keeps the candidates
MEMORY_PASS_SPEC = ResponseSpec(
    extractors={
        "items": BlockListExtractor(
            blocks=[("item", r'<ITEM\s+n\s*=\s*"(?P<n>\d+)"\s*>', "</ITEM>")],
            container=AnchorExtractor(left="<ITEMS>", right="</ITEMS>"),
            unclosed="drop_last",
        ),
        "none": RegexExtractor(
            pattern=r"\A\s*<NONE\s*/>\s*\Z",
            flags=re.IGNORECASE,
            group=0,
            container=AnchorExtractor(left="<ITEMS>", right="</ITEMS>"),
        ),
    },
    required=[],
)
