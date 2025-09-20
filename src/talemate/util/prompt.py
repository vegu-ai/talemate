import re

__all__ = ["condensed", "no_chapters", "replace_special_tokens"]


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
