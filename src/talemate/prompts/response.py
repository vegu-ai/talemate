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
    Extract content between anchor tags (case-insensitive).

    Extraction logic:
    - Only extracts from root-level tags (nested same-type tags are ignored)
    - Prefers content after a configurable tag (e.g., </ANALYSIS>)
    - Returns the last complete block found
    - Falls back to open-ended <TAG>... to end if no closing tag
    - Can optionally stop at another tag (e.g., <ACTIONS>)
    - Falls back to full response search if nothing found in tail
    - Optionally returns full response if no anchors found (fallback_to_full)

    Attributes:
        left: Left anchor (e.g., "<MESSAGE>")
        right: Right anchor (e.g., "</MESSAGE>")
        prefer_after: Tag to prefer content after (e.g., "</ANALYSIS>")
        stop_at: Tag to stop at for open-ended matches (e.g., "<ACTIONS>")
        fallback_to_full: If True, return full response when anchors not found
    """

    left: str
    right: str
    prefer_after: str | None = None
    stop_at: str | None = None
    fallback_to_full: bool = False

    def _find_marker(self, text: str, marker: str) -> int | None:
        """
        Find the position of a marker in text (case-insensitive).

        Returns the index where the marker starts, or None if not found.
        """
        idx = text.lower().find(marker.lower())
        return idx if idx >= 0 else None

    def _find_all_markers(self, text: str, marker: str) -> list[int]:
        """Find all positions where marker appears in text (case-insensitive)."""
        positions = []
        search_text = text.lower()
        search_marker = marker.lower()

        start = 0
        while True:
            idx = search_text.find(search_marker, start)
            if idx < 0:
                break
            positions.append(idx)
            start = idx + 1

        return positions

    def _find_root_level_blocks(self, text: str) -> list[str]:
        """
        Find all complete blocks between left and right anchors.

        Uses a stack to match each closing tag with its nearest opening tag.
        This correctly handles nested/malformed cases like <TAG>nested<TAG>value</TAG>
        by extracting "value" (the innermost complete block).

        Returns:
            List of content strings from complete blocks
        """
        # Find all positions of opening and closing tags
        open_positions = self._find_all_markers(text, self.left)
        close_positions = self._find_all_markers(text, self.right)

        if not open_positions or not close_positions:
            return []

        # Create sorted list of events: (position, is_open, tag_length)
        events: list[tuple[int, bool, int]] = []
        for pos in open_positions:
            events.append((pos, True, len(self.left)))
        for pos in close_positions:
            events.append((pos, False, len(self.right)))

        # Sort by position
        events.sort(key=lambda x: x[0])

        # Use a stack to match closes with their nearest opens
        blocks = []
        open_stack: list[int] = []  # Stack of content start positions

        for pos, is_open, tag_len in events:
            if is_open:
                # Push the position where content starts (after the tag)
                open_stack.append(pos + tag_len)
            else:
                if open_stack:
                    # Pop the most recent open and capture content
                    capture_start = open_stack.pop()
                    content = text[capture_start:pos]
                    blocks.append(content)

        return blocks

    def _extract_open_ended(self, text: str) -> str | None:
        """
        Extract content after the last opening tag to end of text (or stop_at).

        Used as fallback when no closing tag is found.
        """
        open_positions = self._find_all_markers(text, self.left)
        if not open_positions:
            return None

        # Use the last opening tag
        last_open = open_positions[-1]
        content_start = last_open + len(self.left)
        content = text[content_start:]

        # Apply stop_at if configured
        if self.stop_at:
            stop_idx = self._find_marker(content, self.stop_at)
            if stop_idx is not None:
                content = content[:stop_idx]

        return content if content.strip() else None

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

        # Determine the search region (prefer content after a specific tag)
        tail_start = 0
        if self.prefer_after:
            idx = self._find_marker(text, self.prefer_after)
            if idx is not None:
                tail_start = idx + len(self.prefer_after)

        tail = text[tail_start:]

        # Step 1: Find root-level blocks in the tail
        blocks = self._find_root_level_blocks(tail)
        if blocks:
            # Return the last block (original behavior)
            return self._apply_trim(blocks[-1])

        # Step 2: Try open-ended extraction in tail (no closing tag)
        open_ended = self._extract_open_ended(tail)
        if open_ended is not None:
            return self._apply_trim(open_ended)

        # Step 3: Fall back to searching the full response
        if tail_start > 0:
            blocks = self._find_root_level_blocks(text)
            if blocks:
                return self._apply_trim(blocks[-1])

            open_ended = self._extract_open_ended(text)
            if open_ended is not None:
                return self._apply_trim(open_ended)

        # Step 4: If fallback_to_full is enabled, return the full response
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

    All matching is case-insensitive.

    Attributes:
        start: The start marker to search for
        stop_at: Optional end marker to stop at
        fallback_to_full: If True, return full response when start marker not found
    """

    start: str
    stop_at: str | None = None
    fallback_to_full: bool = False

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

        flags = re.IGNORECASE | re.DOTALL
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

    All matching is case-insensitive.

    Extraction logic:
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
    """

    left: str
    right: str
    prefer_after: str | None = None
    validate_structured: bool = True

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

        flags = re.IGNORECASE
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
