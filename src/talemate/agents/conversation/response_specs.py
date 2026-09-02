"""
Response specifications for the conversation agent's knowledge opt-ins.
"""

from talemate.prompts.response import ResponseSpec, AnchorExtractor

__all__ = [
    "KNOWLEDGE_GATE_SPEC",
    "MEMORY_RERANK_SPEC",
    "KNOWLEDGE_LEDGER_SPEC",
]

KNOWLEDGE_GATE_SPEC = ResponseSpec(
    extractors={
        "keep": AnchorExtractor(left="<KEEP>", right="</KEEP>"),
    },
    required=[],
)

MEMORY_RERANK_SPEC = ResponseSpec(
    extractors={
        "order": AnchorExtractor(left="<ORDER>", right="</ORDER>"),
    },
    required=[],
)

KNOWLEDGE_LEDGER_SPEC = ResponseSpec(
    extractors={
        "ledger": AnchorExtractor(left="<LEDGER>", right="</LEDGER>"),
    },
    required=[],
)
