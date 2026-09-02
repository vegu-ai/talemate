"""
Response specifications for the conversation agent's knowledge opt-ins.
"""

from talemate.prompts.response import ResponseSpec, AnchorExtractor

__all__ = [
    "KNOWLEDGE_GATE_SPEC",
    "MEMORY_RERANK_SPEC",
    "KNOWLEDGE_LEDGER_SPEC",
]

# conversation/knowledge-gate.jinja2: the numbers of the candidates the
# character would know, or "none"
KNOWLEDGE_GATE_SPEC = ResponseSpec(
    extractors={
        "keep": AnchorExtractor(left="<KEEP>", right="</KEEP>"),
    },
    required=[],
)

# conversation/memory-rerank.jinja2: the candidate numbers, most useful first
MEMORY_RERANK_SPEC = ResponseSpec(
    extractors={
        "order": AnchorExtractor(left="<ORDER>", right="</ORDER>"),
    },
    required=[],
)

# conversation/knowledge-ledger.jinja2: {"Name": ["F3", ...]} per present character
KNOWLEDGE_LEDGER_SPEC = ResponseSpec(
    extractors={
        "ledger": AnchorExtractor(left="<LEDGER>", right="</LEDGER>"),
    },
    required=[],
)
