import re
import structlog
from typing import Literal

log = structlog.get_logger("talemate.util.prompt")

__all__ = [
    "condensed",
    "no_chapters",
    "replace_special_tokens",
    "clean_visible_response",
    "auto_close_tags",
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

    if not isinstance(s, str):
        return s

    r = s.replace("\n", " ").replace("\r", "")

    # also replace multiple spaces with a single space
    return re.sub(r"\s+", " ", r)


def no_chapters(text: str, replacement: str = "chapter") -> str:
    """
    Takes a text that may contain mentions of 'Chapter X.Y' and replaces them
    with the provided replacement, maintaining the original casing pattern.

    Takes into account that the chapters may be in the format of:

    - Chapter X.Y -> Chapter
    - chapter X.Y -> chapter
    - CHAPTER X -> CHAPTER
    - ChapterX -> Chapter

    Args:
        text (str): The input text containing chapter references
        replacement (str): The text to replace chapter references with

    Returns:
        str: Text with chapter references replaced, maintaining casing

    Examples:
        >>> no_chapters("In Chapter 1.2 we see", "chapter")
        "In chapter we see"
        >>> no_chapters("CHAPTER2 begins", "chapter")
        "chapter begins"
        >>> no_chapters("chapter 3 shows", "chapter")
        "chapter shows"
    """
    import re

    def replace_with_case(match):
        original = match.group(0)

        # Check if the original is all uppercase
        if original.isupper():
            return replacement.upper()

        # Check if the original starts with a capital letter
        if original[0].isupper():
            return replacement.capitalize()

        # Default to lowercase
        return replacement.lower()

    # Pattern explanation:
    # (?i) - case insensitive flag
    # chapter\s* - matches "chapter" followed by optional whitespace
    # (?:\d+(?:\.\d+)?)? - optionally matches:
    #   \d+ - one or more digits
    #   (?:\.\d+)? - optionally followed by a decimal point and more digits
    pattern = r"(?i)chapter\s*(?:\d+(?:\.\d+)?)?"

    return re.sub(pattern, replace_with_case, text)


def clean_visible_response(
    text: str, section: Literal["message", "decision"] = "message"
) -> str:
    """
    Remove action selection blocks and optionally decision blocks from user-visible text.

    This function strips:
    - <ACTIONS>...</ACTIONS> blocks
    - Legacy ```actions...``` blocks
    - Everything from <DECISION> tag onwards (when section="message")

    When section="decision", DECISION content is the primary output so we don't strip it,
    only the ACTIONS blocks are removed.

    Args:
        text: The text to clean
        section: Which section is the primary output ("message" or "decision")

    Returns:
        Cleaned text with special blocks removed
    """
    try:
        # remove new-style <ACTIONS> blocks
        cleaned = re.sub(
            r"<ACTIONS>[\s\S]*?</ACTIONS>", "", text, flags=re.IGNORECASE
        ).strip()
        # also remove any legacy ```actions``` blocks if present
        cleaned = re.sub(
            r"```actions[\s\S]*?```", "", cleaned, flags=re.IGNORECASE
        ).strip()
        # remove <DECISION> blocks only when MESSAGE is the primary section
        # (when DECISION is primary, we want to keep it)
        if section == "message":
            cleaned = re.sub(
                r"<DECISION>[\s\S]*", "", cleaned, flags=re.IGNORECASE
            ).strip()
        return cleaned
    except Exception:
        log.error("clean_visible_response.error", text=text)
        return text.strip()


# Known tags in parsing order (typically ANALYSIS -> MESSAGE -> DECISION -> ACTIONS)
_KNOWN_TAGS = ["ANALYSIS", "MESSAGE", "DECISION", "ACTIONS"]


def auto_close_tags(text: str) -> str:
    """
    Auto-close unclosed XML-like tags in LLM responses.

    LLMs sometimes forget to close tags like <ANALYSIS> before starting the next
    section (e.g., <MESSAGE>). This function detects such cases and inserts the
    missing closing tag just before the next opening tag.

    The function handles these tags: ANALYSIS, MESSAGE, DECISION, ACTIONS

    Logic:
        For each tag, if the opening tag exists without a closing tag, and there
        is a subsequent opening tag for a different section, insert the closing
        tag just before that subsequent opening tag.

    Args:
        text: The response text that may have unclosed tags

    Returns:
        Text with missing closing tags inserted

    Examples:
        >>> auto_close_tags("<ANALYSIS>Some analysis<MESSAGE>Hello</MESSAGE>")
        '<ANALYSIS>Some analysis</ANALYSIS><MESSAGE>Hello</MESSAGE>'
    """
    if not text:
        return text

    result = text

    for tag in _KNOWN_TAGS:
        close_tag = f"</{tag}>"

        # Find opening tag (case-insensitive)
        open_match = re.search(rf"<{tag}>", result, re.IGNORECASE)
        if not open_match:
            continue

        # Check if closing tag exists after the opening tag
        close_match = re.search(rf"</{tag}>", result[open_match.end() :], re.IGNORECASE)
        if close_match:
            # Tag is properly closed, skip
            continue

        # Tag is unclosed - find the next opening tag of a different type
        # Build pattern for other opening tags
        other_tags = [t for t in _KNOWN_TAGS if t != tag]
        if not other_tags:
            continue

        # Search for next opening tag after current opening tag
        other_pattern = "|".join(rf"<{t}>" for t in other_tags)
        next_open_match = re.search(
            other_pattern, result[open_match.end() :], re.IGNORECASE
        )

        if next_open_match:
            # Insert closing tag just before the next opening tag
            insert_pos = open_match.end() + next_open_match.start()
            result = result[:insert_pos] + close_tag + result[insert_pos:]

    return result
