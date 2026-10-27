"""
Response specifications for World State agent prompt responses.
"""

from talemate.prompts.response import AnchorExtractor, ResponseSpec

__all__ = [
    "EXAMINE_SPEC",
    "REINFORCEMENT_ANSWER_SPEC",
]

EXAMINE_SPEC = ResponseSpec(
    extractors={
        "response": AnchorExtractor(
            left="<EXAMINE>",
            right="</EXAMINE>",
            fallback_to_full=True,
        ),
    },
)

REINFORCEMENT_ANSWER_SPEC = ResponseSpec(
    extractors={
        "response": AnchorExtractor(
            left="<ANSWER>",
            right="</ANSWER>",
            fallback_to_full=True,
        ),
    },
)
