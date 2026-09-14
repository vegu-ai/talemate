"""
Response specifications for the conversation agent's knowledge opt-ins.
"""

import re

from talemate.prompts.response import (
    AnchorExtractor,
    Extractor,
    ResponseSpec,
    StrictAnchorExtractor,
)

__all__ = [
    "ItemBlockExtractor",
    "ENTRY_BRIEFING_SPEC",
    "MEMORY_PASS_SPEC",
    "KNOWLEDGE_LEDGER_SPEC",
]

ITEMS_CONTAINER = AnchorExtractor(left="<ITEMS>", right="</ITEMS>")

# an item ends at its closing tag or at the next opener; one still open at the
# end of the container is a truncation and yields no match
_ITEM_BLOCK = re.compile(
    r'<ITEM\s+n\s*=\s*"(?P<n>\d+)"\s*>(?P<content>.*?)'
    r"(?:</\s*ITEM(?:\s[^>]*)?>|(?=<ITEM\s))",
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


class IsolatedStrictAnchorExtractor(StrictAnchorExtractor):
    """Strict extraction that rejects markup from a sibling response section."""

    forbidden_anchors: tuple[str, ...] = ()

    def extract(self, text: str) -> str | None:
        content = super().extract(text)
        if content is None:
            return None
        lowered = content.lower()
        if any(anchor.lower() in lowered for anchor in self.forbidden_anchors):
            return None
        return content


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


ENTRY_BRIEFING_SPEC = ResponseSpec(
    extractors={
        "briefing": IsolatedStrictAnchorExtractor(
            left="<BRIEFING>",
            right="</BRIEFING>",
            forbidden_anchors=("<OFFSCREEN", "</OFFSCREEN", "</BRIEFING"),
        ),
        "offscreen": IsolatedStrictAnchorExtractor(
            left="<OFFSCREEN>",
            right="</OFFSCREEN>",
            forbidden_anchors=("<BRIEFING", "</BRIEFING", "</OFFSCREEN"),
        ),
    },
    required=[],
)
