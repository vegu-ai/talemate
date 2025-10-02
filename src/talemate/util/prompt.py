import re
import structlog

log = structlog.get_logger("talemate.util.prompt")

__all__ = [
    "condensed",
    "no_chapters",
    "replace_special_tokens",
    "parse_response_section",
    "extract_actions_block",
    "clean_visible_response",
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
    try:
        # Prefer only content after a closed analysis block.</analysis>
        # Find the index right after the first closing </ANALYSIS> (case-insensitive).
        tail_start = 0
        m_after = re.search(r"</ANALYSIS>", response, re.IGNORECASE)
        if m_after:
            tail_start = m_after.end()
        tail = response[tail_start:]

        # Step 1: Greedily capture the last closed <MESSAGE>...</MESSAGE> after </ANALYSIS>.
        # (?is) enables DOTALL and IGNORECASE. We match lazily inside to find each pair, then take the last.
        matches = re.findall(r"(?is)<MESSAGE>\s*([\s\S]*?)\s*</MESSAGE>", tail)
        if matches:
            return matches[-1].strip()

        # Step 2: If no closed block, capture everything after the first <MESSAGE> to the end (still after </ANALYSIS> if present).
        m_open = re.search(r"(?is)<MESSAGE>\s*([\s\S]*)$", tail)
        if m_open:
            return m_open.group(1).strip()

        # Step 3: Fall back to searching the entire response for a closed block and take the last one.
        matches_all = re.findall(
            r"(?is)<MESSAGE>\s*([\s\S]*?)\s*</MESSAGE>", response
        )
        if matches_all:
            return matches_all[-1].strip()

        # Step 4: Last resort, open-ended from <MESSAGE> to the end over the whole response.
        m_open_all = re.search(r"(?is)<MESSAGE>\s*([\s\S]*)$", response)
        if m_open_all:
            return m_open_all.group(1).strip()

        return None
    except Exception:
        log.error("parse_response_section.error", response=response)
        return None


def extract_actions_block(response: str) -> str | None:
    """
    Extract the raw content from an <ACTIONS> section containing a code block.
    - Supports full <ACTIONS>...</ACTIONS>
    - Tolerates a missing </ACTIONS> closing tag if the ACTIONS block is the final block
    - Tolerates a missing closing code fence ``` by capturing to </ACTIONS> or end-of-text
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

        # If still no content and no ANALYSIS block, fall back to searching entire response
        if content is None and tail_start == 0:
            match = re.search(
                r"<ACTIONS>\s*```(?:json|yaml)?\s*([\s\S]*?)\s*```\s*</ACTIONS>",
                response,
                re.IGNORECASE,
            )
            if match:
                content = match.group(1).strip()

        return content if content else None
    except Exception:
        log.error("extract_actions_block.error", response=response)
        return None


def clean_visible_response(text: str) -> str:
    """
    Remove action selection blocks and decision blocks from user-visible text.

    This function strips:
    - <ACTIONS>...</ACTIONS> blocks
    - Legacy ```actions...``` blocks
    - Everything from <DECISION> tag onwards (including the tag)

    Args:
        text: The text to clean

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
        # remove <DECISION> blocks (everything from <DECISION> tag onwards)
        cleaned = re.sub(
            r"<DECISION>[\s\S]*", "", cleaned, flags=re.IGNORECASE
        ).strip()
        return cleaned
    except Exception:
        log.error("clean_visible_response.error", text=text)
        return text.strip()
