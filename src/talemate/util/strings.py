"""String normalization helpers shared across the app."""

__all__ = [
    "normalize_name",
    "replace_smart_quotes",
]

# Typographic quotes mapped to their ascii equivalents. Talemate uses the
# straight `"` as the dialogue delimiter throughout (scene message rendering,
# dialogue/exposition separation, tts markup), so smart quotes have to be
# normalized away before text is stored or displayed.
#
# Both marks of a pair have to be mapped together: mapping only one of them
# leaves a single unbalanced straight quote behind, which the dialogue parsers
# then pair with whatever follows - worse than leaving the pair alone. The
# low-9 marks are the opening quotes of the German-style `„…“` / `‚…‘`
# convention, so they belong with the marks that close them.
SMART_QUOTE_TRANSLATION = str.maketrans(
    {
        "“": '"',  # left double quotation mark
        "”": '"',  # right double quotation mark
        "„": '"',  # double low-9 quotation mark
        "‘": "'",  # left single quotation mark
        "’": "'",  # right single quotation mark
        "‚": "'",  # single low-9 quotation mark
    }
)


def normalize_name(raw: str | None, max_length: int) -> str | None:
    """
    Normalize a free-form user-entered name.

    Trims whitespace, collapses empty / whitespace-only input to ``None``, and
    truncates to at most ``max_length`` characters.

    Args:
        raw: The input string, or ``None``.
        max_length: Maximum length of the returned string.

    Returns:
        The normalized name, or ``None`` if the input was empty.
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return trimmed[:max_length]


def replace_smart_quotes(text: str) -> str:
    """
    Replace typographic quotes with their ascii equivalents.

    Args:
        text: The input string.

    Returns:
        The string with smart quotes replaced.
    """
    return text.translate(SMART_QUOTE_TRANSLATION)
