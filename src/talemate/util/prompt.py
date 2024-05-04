import re

__all__ = [
    "condensed",
    "replace_special_tokens"
]


def replace_special_tokens(prompt: str):
    """
    Replaces the following special tokens

    <|TRAILING_NEW_LINE|> -> \n
    <|TRAILING_SPACE|> -> " "
    """

    return prompt.replace("<|TRAILING_NEW_LINE|>", "\n").replace(
        "<|TRAILING_SPACE|>", " "
    )


def condensed(s):
    """Replace all line breaks in a string with spaces."""
    r = s.replace("\n", " ").replace("\r", "")

    # also replace multiple spaces with a single space
    return re.sub(r"\s+", " ", r)