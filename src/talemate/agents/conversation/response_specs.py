"""
Response specifications for the conversation agent's knowledge opt-ins.
"""

from talemate.prompts.response import ResponseSpec, AnchorExtractor

__all__ = [
    "MEMORY_PASS_SPEC",
    "KNOWLEDGE_LEDGER_SPEC",
]

MEMORY_PASS_SPEC = ResponseSpec(
    extractors={
        "items": AnchorExtractor(left="<ITEMS>", right="</ITEMS>"),
    },
    required=[],
)

KNOWLEDGE_LEDGER_SPEC = ResponseSpec(
    extractors={
        "ledger": AnchorExtractor(left="<LEDGER>", right="</LEDGER>"),
    },
    required=[],
)
