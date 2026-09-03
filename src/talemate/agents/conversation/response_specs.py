"""
Response specifications for the conversation agent's knowledge opt-ins.
"""

from talemate.prompts.response import (
    AnchorExtractor,
    BlockListExtractor,
    ResponseSpec,
)

__all__ = [
    "MEMORY_PASS_SPEC",
    "KNOWLEDGE_LEDGER_SPEC",
]

MEMORY_PASS_SPEC = ResponseSpec(
    extractors={
        "answer": AnchorExtractor(left="<ITEMS>", right="</ITEMS>"),
        "items": BlockListExtractor(
            blocks=[("item", r'<ITEM n="(?P<n>\d+)">', "</ITEM>")]
        ),
    },
    required=[],
)

KNOWLEDGE_LEDGER_SPEC = ResponseSpec(
    extractors={
        "ledger": AnchorExtractor(left="<LEDGER>", right="</LEDGER>"),
    },
    required=[],
)
