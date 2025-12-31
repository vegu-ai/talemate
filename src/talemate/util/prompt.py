import json
import re
import structlog
import yaml
from typing import Literal

log = structlog.get_logger("talemate.util.prompt")

__all__ = [
    "condensed",
    "no_chapters",
    "replace_special_tokens",
    "parse_response_section",
    "parse_decision_section",
    "extract_actions_block",
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


def _parse_section(
    response: str, tag: str, stop_at_actions: bool = False
) -> str | None:
    """
    Generic section extractor using greedy regex preference:
    1) last <TAG>...</TAG> after </ANALYSIS>
    2) open-ended <TAG>... to end (optionally stop before <ACTIONS>) after </ANALYSIS>
    3) same two fallbacks over entire response.

    Args:
        response: The response text to parse
        tag: The tag name to extract (e.g., "MESSAGE", "DECISION")
        stop_at_actions: If True, stop at <ACTIONS> tag for open-ended matches

    Returns:
        The extracted content, or None if not found
    """
    try:
        # Prefer only content after a closed analysis block
        tail_start = 0
        m_after = re.search(r"</ANALYSIS>", response, re.IGNORECASE)
        if m_after:
            tail_start = m_after.end()
        tail = response[tail_start:]

        # Step 1: Greedily capture the last closed <TAG>...</TAG> after </ANALYSIS>
        pattern = rf"(?is)<{tag}>\s*([\s\S]*?)\s*</{tag}>"
        matches = re.findall(pattern, tail)
        if matches:
            return matches[-1].strip()

        # Step 2: If no closed block, capture everything after <TAG>
        if stop_at_actions:
            # Stop at <ACTIONS> or end of string
            m_open = re.search(rf"(?is)<{tag}>\s*([\s\S]*?)(?=<ACTIONS>|$)", tail)
            if m_open:
                content = m_open.group(1).strip()
                if content:
                    return content
        else:
            # Go to end of string
            m_open = re.search(rf"(?is)<{tag}>\s*([\s\S]*)$", tail)
            if m_open:
                return m_open.group(1).strip()

        # Step 3: Fall back to searching the entire response for a closed block
        matches_all = re.findall(pattern, response)
        if matches_all:
            return matches_all[-1].strip()

        # Step 4: Last resort, open-ended over whole response
        if stop_at_actions:
            m_open_all = re.search(
                rf"(?is)<{tag}>\s*([\s\S]*?)(?=<ACTIONS>|$)", response
            )
            if m_open_all:
                content = m_open_all.group(1).strip()
                if content:
                    return content
        else:
            m_open_all = re.search(rf"(?is)<{tag}>\s*([\s\S]*)$", response)
            if m_open_all:
                return m_open_all.group(1).strip()

        return None
    except Exception:
        log.error("_parse_section.error", tag=tag, response=response)
        return None


def parse_response_section(response: str) -> str | None:
    """
    Extract the <MESSAGE> section using greedy regex preference:
    1) last <MESSAGE>...</MESSAGE> after </ANALYSIS>
    2) open-ended <MESSAGE>... to end after </ANALYSIS>
    3) same two fallbacks over entire response.

    Args:
        response: The response text to parse

    Returns:
        The extracted message content, or None if not found
    """
    return _parse_section(response, "MESSAGE", stop_at_actions=False)


def parse_decision_section(response: str) -> str | None:
    """
    Extract the <DECISION> section using greedy regex preference:
    1) last <DECISION>...</DECISION> after </ANALYSIS>
    2) open-ended <DECISION>... to end (but stop before <ACTIONS>) after </ANALYSIS>
    3) same fallbacks over entire response.

    Used for scene direction mode where DECISION is the primary output
    instead of MESSAGE.

    Args:
        response: The response text to parse

    Returns:
        The extracted decision content, or None if not found
    """
    return _parse_section(response, "DECISION", stop_at_actions=True)


def _is_valid_structured_data(text: str) -> bool:
    """
    Check if text is valid JSON or YAML by attempting to parse it.

    Args:
        text: The text to check

    Returns:
        True if it parses as JSON or YAML, False otherwise
    """
    if not text:
        return False

    # Try JSON first
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        pass

    # Try YAML
    try:
        result = yaml.safe_load(text)
        # YAML will parse plain strings, so check it's actually structured
        if isinstance(result, (dict, list)):
            return True
    except yaml.YAMLError:
        pass

    return False


def extract_actions_block(response: str) -> str | None:
    """
    Extract the raw content from an <ACTIONS> section containing a code block.
    - Supports full <ACTIONS>...</ACTIONS>
    - Tolerates a missing </ACTIONS> closing tag if the ACTIONS block is the final block
    - Tolerates a missing closing code fence ``` by capturing to </ACTIONS> or end-of-text
    - Tolerates missing code fences entirely if content looks like JSON/YAML
    - Skips ACTIONS blocks that appear within ANALYSIS sections

    This function only extracts the raw string content - parsing is left to the caller.

    Args:
        response: The response text to parse

    Returns:
        The raw content string from within the ACTIONS code block, or None if not found
    """
    try:
        # First, prefer content after </ANALYSIS> if present
        tail_start = 0
        m_after = re.search(r"</ANALYSIS>", response, re.IGNORECASE)
        if m_after:
            tail_start = m_after.end()
        tail = response[tail_start:]

        content: str | None = None

        # Prefer new <ACTIONS> ... ```(json|yaml) ... ``` ... </ACTIONS>
        match = re.search(
            r"<ACTIONS>\s*```(?:json|yaml)?\s*([\s\S]*?)\s*```\s*</ACTIONS>",
            tail,
            re.IGNORECASE,
        )
        if match:
            content = match.group(1).strip()

        if content is None:
            # Accept missing </ACTIONS> if it's the final block and we at least have a closing code fence
            partial_fenced = re.search(
                r"<ACTIONS>\s*```(?:json|yaml)?\s*([\s\S]*?)\s*```",
                tail,
                re.IGNORECASE,
            )
            if partial_fenced:
                content = partial_fenced.group(1).strip()

        if content is None:
            # Accept missing closing code fence by capturing to </ACTIONS> or end-of-text
            open_fence_to_end = re.search(
                r"<ACTIONS>\s*```(?:json|yaml)?\s*([\s\S]*?)(?:</ACTIONS>|$)",
                tail,
                re.IGNORECASE,
            )
            if open_fence_to_end:
                content = open_fence_to_end.group(1).strip()

        # Fallback: No code fence at all - extract raw content from <ACTIONS>...</ACTIONS>
        # and validate it looks like JSON or YAML (starts with [, {, or - for YAML lists)
        if content is None:
            no_fence_match = re.search(
                r"<ACTIONS>\s*([\s\S]*?)\s*</ACTIONS>",
                tail,
                re.IGNORECASE,
            )
            if no_fence_match:
                raw_content = no_fence_match.group(1).strip()
                if raw_content and _is_valid_structured_data(raw_content):
                    content = raw_content

        return content if content else None
    except Exception:
        log.error("extract_actions_block.error", response=response)
        return None


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
