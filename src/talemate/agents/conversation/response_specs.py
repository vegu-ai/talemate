"""
Response specifications for the conversation agent's knowledge opt-ins.
"""

import re

from talemate.prompts.response import AnchorExtractor, Extractor, ResponseSpec

__all__ = [
    "ItemBlockExtractor",
    "MEMORY_PASS_SPEC",
    "KNOWLEDGE_LEDGER_SPEC",
]

ITEMS_CONTAINER = AnchorExtractor(left="<ITEMS>", right="</ITEMS>")

# an item ends at its closing tag or at the next opener; one still open at the
# end of the container is a truncation and yields no match
_ITEM_BLOCK = re.compile(
    r'<ITEM n="(?P<n>\d+)">(?P<content>.*?)(?:</ITEM>|(?=<ITEM n="))',
    re.IGNORECASE | re.DOTALL,
)


class ItemBlockExtractor(Extractor):
    """
    `<ITEM n="…">…</ITEM>` blocks read only inside the `<ITEMS>` container, so
    a tagged aside after `</ITEMS>` is not an item.
    """

    def extract(self, text: str) -> list[dict]:
        content = ITEMS_CONTAINER.extract(text or "")
        if not content:
            return []
        return [
            {"n": match.group("n"), "content": match.group("content").strip()}
            for match in _ITEM_BLOCK.finditer(content)
        ]


MEMORY_PASS_SPEC = ResponseSpec(
    extractors={
        "answer": ITEMS_CONTAINER,
        "items": ItemBlockExtractor(),
    },
    required=[],
)

KNOWLEDGE_LEDGER_SPEC = ResponseSpec(
    extractors={
        "ledger": AnchorExtractor(left="<LEDGER>", right="</LEDGER>"),
    },
    required=[],
)
