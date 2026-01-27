"""
Response specifications for the creator agent.

Defines ResponseSpec objects for extracting structured data from LLM responses.
"""

import re

from talemate.prompts.response import (
    AnchorExtractor,
    RegexExtractor,
    ResponseSpec,
)

__all__ = [
    "TITLE_SPEC",
    "NAME_SPEC",
    "COMPLETION_SPEC",
]

# For <TITLE>...</TITLE> extraction (used in generate_title)
TITLE_SPEC = ResponseSpec(
    extractors={
        "title": AnchorExtractor(left="<TITLE>", right="</TITLE>"),
    },
    required=[],  # Handle None case in code - may fall back to raw response
)

# For <NAME>...</NAME> extraction (used in determine_character_name)
# Uses RegexExtractor with all_matches=True to find multiple name tags
NAME_SPEC = ResponseSpec(
    extractors={
        "names": RegexExtractor(
            pattern=r"<NAME>(.*?)</NAME>",
            flags=re.DOTALL,
            all_matches=True,
        ),
    },
    required=[],  # Handle None case in code - may fall back to other parsing
)

# For <COMPLETION>...</COMPLETION> extraction (used in autocomplete_dialogue/narrative)
COMPLETION_SPEC = ResponseSpec(
    extractors={
        "response": AnchorExtractor(left="<COMPLETION>", right="</COMPLETION>"),
    },
    required=[],  # Handle None case in code - will fall back to raw response
)
