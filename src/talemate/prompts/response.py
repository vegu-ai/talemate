"""
Response extractors for parsing LLM outputs.

This module provides a set of extractor classes for extracting content from
structured LLM responses. These extractors handle various formats including
XML-like tags, code blocks, and regex patterns.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Union

import yaml
from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "ExtractionError",
    "Extractor",
    "AnchorExtractor",
    "AsIsExtractor",
    "AfterAnchorExtractor",
    "RegexExtractor",
    "StripPrefixExtractor",
    "CodeBlockExtractor",
    "ResponseSpec",
]


class ExtractionError(Exception):
    """Exception raised when extraction fails."""

    pass


class Extractor(BaseModel, ABC):
    """Base class for response extractors."""

    model_config = ConfigDict(frozen=False)

    trim: bool = True

    @abstractmethod
    def extract(self, text: str) -> Union[str, list[str], None]:
        """
        Extract content from text.

        Args:
            text: The text to extract content from

        Returns:
            The extracted content, or None if not found
        """
        pass

    def _apply_trim(self, content: str | None) -> str | None:
        """Apply trimming if enabled."""
        if content is None:
            return None
        return content.strip() if self.trim else content


class AnchorExtractor(Extractor):
    """
    Extract content between anchor tags.

    Sophisticated extraction logic:
    - Prefers content after a configurable tag (e.g., </ANALYSIS>)
    - Tries closed <TAG>...</TAG> first (greedy - takes last match)
    - Falls back to open-ended <TAG>... to end
    - Can optionally stop at another tag (e.g., <ACTIONS>)
    - Falls back to full response search if nothing found in tail
    - Optionally returns full response if no anchors found (fallback_to_full)

    Attributes:
        left: Left anchor (e.g., "<MESSAGE>")
        right: Right anchor (e.g., "</MESSAGE>")
        prefer_after: Tag to prefer content after (e.g., "</ANALYSIS>")
        stop_at: Tag to stop at for open-ended matches (e.g., "<ACTIONS>")
        case_insensitive: Whether to use case-insensitive matching
        fallback_to_full: If True, return full response when anchors not found
    """

    left: str
    right: str
    prefer_after: str | None = None
    stop_at: str | None = None
    case_insensitive: bool = True
    fallback_to_full: bool = False

    def _get_flags(self) -> int:
        """Get regex flags based on case_insensitive setting."""
        return re.IGNORECASE | re.DOTALL if self.case_insensitive else re.DOTALL

    def _escape_for_regex(self, text: str) -> str:
        """Escape special regex characters in the text."""
        return re.escape(text)

    def extract(self, text: str) -> str | None:
        """
        Extract content between anchor tags.

        Args:
            text: The text to extract from

        Returns:
            The extracted content, or None if not found
        """
        if not text:
            return None

        flags = self._get_flags()
        left_escaped = self._escape_for_regex(self.left)
        right_escaped = self._escape_for_regex(self.right)

        # Determine the tail to search (prefer content after a specific tag)
        tail_start = 0
        if self.prefer_after:
            prefer_after_escaped = self._escape_for_regex(self.prefer_after)
            m_after = re.search(prefer_after_escaped, text, flags)
            if m_after:
                tail_start = m_after.end()
        tail = text[tail_start:]

        # Step 1: Greedily capture the last closed <TAG>...</TAG> in the tail
        closed_pattern = rf"{left_escaped}\s*([\s\S]*?)\s*{right_escaped}"
        matches = re.findall(closed_pattern, tail, flags)
        if matches:
            return self._apply_trim(matches[-1])

        # Step 2: If no closed block, capture everything after <TAG>
        if self.stop_at:
            stop_at_escaped = self._escape_for_regex(self.stop_at)
            open_pattern = rf"{left_escaped}\s*([\s\S]*?)(?={stop_at_escaped}|$)"
            m_open = re.search(open_pattern, tail, flags)
            if m_open:
                content = m_open.group(1)
                if content and content.strip():
                    return self._apply_trim(content)
        else:
            open_pattern = rf"{left_escaped}\s*([\s\S]*)$"
            m_open = re.search(open_pattern, tail, flags)
            if m_open:
                return self._apply_trim(m_open.group(1))

        # Step 3: Fall back to searching the entire response for a closed block
        matches_all = re.findall(closed_pattern, text, flags)
        if matches_all:
            return self._apply_trim(matches_all[-1])

        # Step 4: Last resort, open-ended over whole response
        if self.stop_at:
            stop_at_escaped = self._escape_for_regex(self.stop_at)
            open_pattern_all = rf"{left_escaped}\s*([\s\S]*?)(?={stop_at_escaped}|$)"
            m_open_all = re.search(open_pattern_all, text, flags)
            if m_open_all:
                content = m_open_all.group(1)
                if content and content.strip():
                    return self._apply_trim(content)
        else:
            open_pattern_all = rf"{left_escaped}\s*([\s\S]*)$"
            m_open_all = re.search(open_pattern_all, text, flags)
            if m_open_all:
                return self._apply_trim(m_open_all.group(1))

        # Step 5: If fallback_to_full is enabled, return the full response
        if self.fallback_to_full:
            return self._apply_trim(text)

        return None


class AsIsExtractor(Extractor):
    """
    Return the entire response as-is (trimmed by default).

    Returns None for empty strings.
    """

    def extract(self, text: str) -> str | None:
        """
        Return the text as-is.

        Args:
            text: The text to return

        Returns:
            The text (trimmed if trim=True), or None if empty
        """
        if not text:
            return None

        result = self._apply_trim(text)

        # Return None for empty strings after trimming
        if result == "":
            return None

        return result


class AfterAnchorExtractor(Extractor):
    """
    Extract everything after a start marker, optionally stopping at an end marker.

    Attributes:
        start: The start marker to search for
        stop_at: Optional end marker to stop at
        case_insensitive: Whether to use case-insensitive matching
        fallback_to_full: If True, return full response when start marker not found
    """

    start: str
    stop_at: str | None = None
    case_insensitive: bool = True
    fallback_to_full: bool = False

    def _get_flags(self) -> int:
        """Get regex flags based on case_insensitive setting."""
        return re.IGNORECASE | re.DOTALL if self.case_insensitive else re.DOTALL

    def extract(self, text: str) -> str | None:
        """
        Extract everything after the start marker.

        Args:
            text: The text to extract from

        Returns:
            The extracted content, or None if start marker not found
        """
        if not text:
            return None

        flags = self._get_flags()
        start_escaped = re.escape(self.start)

        # Find the start marker
        start_match = re.search(start_escaped, text, flags)
        if not start_match:
            if self.fallback_to_full:
                return self._apply_trim(text)
            return None

        # Extract content after the start marker
        content = text[start_match.end() :]

        # If stop_at is specified, truncate at that marker
        if self.stop_at:
            stop_escaped = re.escape(self.stop_at)
            stop_match = re.search(stop_escaped, content, flags)
            if stop_match:
                content = content[: stop_match.start()]

        return self._apply_trim(content)


class RegexExtractor(Extractor):
    """
    Extract content using a regex pattern with a capture group.

    Attributes:
        pattern: The regex pattern to match
        flags: Regex flags (as int, e.g., re.IGNORECASE = 2)
        group: The capture group to extract (default: 1)
        all_matches: If True, return list[str] instead of str
    """

    pattern: str
    flags: int = 0
    group: int = 1
    all_matches: bool = False

    def extract(self, text: str) -> Union[str, list[str], None]:
        """
        Extract content using the regex pattern.

        Args:
            text: The text to extract from

        Returns:
            The extracted content (str or list[str]), or None if not found
        """
        if not text:
            return None

        try:
            if self.all_matches:
                # Find all matches and extract the specified group
                matches = re.finditer(self.pattern, text, self.flags)
                results = []
                for match in matches:
                    try:
                        group_content = match.group(self.group)
                        if group_content is not None:
                            if self.trim:
                                group_content = group_content.strip()
                            results.append(group_content)
                    except IndexError:
                        # Group doesn't exist in this match
                        continue

                return results if results else None
            else:
                # Find first match
                match = re.search(self.pattern, text, self.flags)
                if not match:
                    return None

                try:
                    content = match.group(self.group)
                    return self._apply_trim(content)
                except IndexError:
                    return None

        except re.error:
            return None


class StripPrefixExtractor(Extractor):
    """
    Strip prefixes matching a pattern from the response (using re.sub).

    Attributes:
        pattern: The regex pattern to strip
        replacement: The replacement string (default: "")
    """

    pattern: str
    replacement: str = ""

    def extract(self, text: str) -> str | None:
        """
        Strip the matching pattern from the text.

        Args:
            text: The text to process

        Returns:
            The text with the pattern replaced, or None if text is empty
        """
        if not text:
            return None

        try:
            result = re.sub(self.pattern, self.replacement, text)
            return self._apply_trim(result)
        except re.error:
            return self._apply_trim(text)


class CodeBlockExtractor(Extractor):
    """
    Extract content from inside a tagged section containing a code block.

    Sophisticated extraction logic:
    1. Prefer content after prefer_after tag (e.g., "</ANALYSIS>")
    2. Try full <TAG>```lang...```</TAG> pattern
    3. Fall back to <TAG>```lang...``` (missing closing tag)
    4. Fall back to <TAG>```lang... to end (missing code fence close)
    5. Fall back to <TAG>...</TAG> with JSON/YAML validation (no code fence)

    Attributes:
        left: Left anchor (e.g., "<ACTIONS>")
        right: Right anchor (e.g., "</ACTIONS>")
        prefer_after: Tag to prefer content after (e.g., "</ANALYSIS>")
        validate_structured: Whether to validate content as JSON/YAML for no-fence fallback
        case_insensitive: Whether to use case-insensitive matching
    """

    left: str
    right: str
    prefer_after: str | None = None
    validate_structured: bool = True
    case_insensitive: bool = True

    def _get_flags(self) -> int:
        """Get regex flags based on case_insensitive setting."""
        return re.IGNORECASE if self.case_insensitive else 0

    def _is_valid_structured_data(self, text: str) -> bool:
        """
        Check if text is valid JSON or YAML.

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

    def extract(self, text: str) -> str | None:
        """
        Extract content from a code block inside tagged section.

        Args:
            text: The text to extract from

        Returns:
            The extracted content, or None if not found
        """
        if not text:
            return None

        flags = self._get_flags()
        left_escaped = re.escape(self.left)
        right_escaped = re.escape(self.right)

        # Determine the tail to search (prefer content after a specific tag)
        tail_start = 0
        if self.prefer_after:
            prefer_after_escaped = re.escape(self.prefer_after)
            m_after = re.search(prefer_after_escaped, text, flags)
            if m_after:
                tail_start = m_after.end()
        tail = text[tail_start:]

        content: str | None = None

        # Step 1: Full <TAG>```lang...```</TAG> pattern
        full_pattern = (
            rf"{left_escaped}\s*```(?:json|yaml)?\s*([\s\S]*?)\s*```\s*{right_escaped}"
        )
        match = re.search(full_pattern, tail, flags)
        if match:
            content = match.group(1).strip()

        # Step 2: Missing closing tag - <TAG>```lang...```
        if content is None:
            partial_fenced = rf"{left_escaped}\s*```(?:json|yaml)?\s*([\s\S]*?)\s*```"
            match = re.search(partial_fenced, tail, flags)
            if match:
                content = match.group(1).strip()

        # Step 3: Missing closing code fence - <TAG>```lang... to </TAG> or end
        if content is None:
            open_fence_pattern = (
                rf"{left_escaped}\s*```(?:json|yaml)?\s*([\s\S]*?)(?:{right_escaped}|$)"
            )
            match = re.search(open_fence_pattern, tail, flags)
            if match:
                content = match.group(1).strip()

        # Step 4: No code fence at all - <TAG>...</TAG> with optional structured data validation
        if content is None:
            no_fence_pattern = rf"{left_escaped}\s*([\s\S]*?)\s*{right_escaped}"
            match = re.search(no_fence_pattern, tail, flags)
            if match:
                raw_content = match.group(1).strip()
                if raw_content:
                    if self.validate_structured:
                        if self._is_valid_structured_data(raw_content):
                            content = raw_content
                    else:
                        content = raw_content

        return self._apply_trim(content) if content else None


class ResponseSpec(BaseModel):
    """
    Specification for what to extract from a response.

    Backend specifies WHAT to extract (field names) and HOW (extractors).
    """

    extractors: dict[str, Extractor] = Field(default_factory=dict)
    required: list[str] = Field(
        default_factory=list
    )  # Must be present, error if missing

    def extract_all(self, text: str) -> dict[str, str | list[str] | None]:
        """
        Extract all fields from text.

        Returns dict mapping field names to extracted values (or None if not found).
        Raises ExtractionError if required field not found.
        """
        result = {}
        for name, extractor in self.extractors.items():
            value = extractor.extract(text)
            if name in self.required and value is None:
                raise ExtractionError(f"Required field '{name}' not found in response")
            result[name] = value
        return result

    @classmethod
    def simple(
        cls, name: str, extractor: Extractor, required: bool = True
    ) -> "ResponseSpec":
        """Convenience constructor for single-field extraction."""
        return cls(extractors={name: extractor}, required=[name] if required else [])
