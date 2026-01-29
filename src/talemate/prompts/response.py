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
    "AnchorExtractorBase",
    "AnchorExtractor",
    "ComplexAnchorExtractor",
    "AsIsExtractor",
    "AfterAnchorExtractor",
    "RegexExtractor",
    "StripPrefixExtractor",
    "CodeBlockExtractor",
    "ComplexCodeBlockExtractor",
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


class AnchorExtractorBase(Extractor):
    """
    Base class for anchor-based extractors with shared functionality.

    Provides case-insensitive marker finding and common configuration.

    Attributes:
        left: Left anchor (e.g., "<MESSAGE>")
        right: Right anchor (e.g., "</MESSAGE>")
        fallback_to_full: If True, return full response when anchors not found
    """

    left: str
    right: str
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


class AnchorExtractor(AnchorExtractorBase):
    """
    Extract content between anchor tags (case-insensitive).

    Simple extraction that only tracks the target tag (left/right).
    Uses stack-based matching for same-tag nesting.

    Extraction logic:
    - Returns the last complete block found
    - Falls back to open-ended <TAG>... to end if no closing tag
    - Optionally returns full response if no anchors found (fallback_to_full)

    Attributes:
        left: Left anchor (e.g., "<MESSAGE>")
        right: Right anchor (e.g., "</MESSAGE>")
        fallback_to_full: If True, return full response when anchors not found
    """

    def _find_root_level_blocks(self, text: str) -> list[str]:
        """
        Find all complete blocks between left and right anchors using stack-based matching.

        Uses a stack-based approach to match opening and closing tags,
        handling nested same-type tags correctly.

        Returns:
            List of content strings from complete blocks
        """
        # Find all positions of left and right anchors
        left_positions = self._find_all_markers(text, self.left)
        right_positions = self._find_all_markers(text, self.right)

        # Build events list: (position, is_open, tag_length)
        events: list[tuple[int, bool, int]] = []
        for pos in left_positions:
            events.append((pos, True, len(self.left)))
        for pos in right_positions:
            events.append((pos, False, len(self.right)))

        # Sort by position
        events.sort(key=lambda x: x[0])

        # Use stack to match opening/closing tags
        blocks = []
        stack: list[int] = []  # Stack of content start positions

        for pos, is_open, tag_len in events:
            if is_open:
                # Push content start position (after the opening tag)
                stack.append(pos + tag_len)
            elif stack:
                # Pop and capture block
                content_start = stack.pop()
                content = text[content_start:pos]
                blocks.append(content)

        return blocks

    def _extract_open_ended(self, text: str) -> str | None:
        """
        Extract content after the last opening tag to end of text.

        Used as fallback when no closing tag is found.
        """
        open_positions = self._find_all_markers(text, self.left)

        if not open_positions:
            return None

        # Use the last opening tag
        last_open = open_positions[-1]
        content_start = last_open + len(self.left)
        content = text[content_start:]

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

        # Step 1: Find root-level blocks
        blocks = self._find_root_level_blocks(text)
        if blocks:
            # Return the last block
            return self._apply_trim(blocks[-1])

        # Step 2: Try open-ended extraction (no closing tag)
        open_ended = self._extract_open_ended(text)
        if open_ended is not None:
            return self._apply_trim(open_ended)

        # Step 3: If fallback_to_full is enabled, return the full response
        if self.fallback_to_full:
            return self._apply_trim(text)

        return None


class ComplexAnchorExtractor(AnchorExtractorBase):
    """
    Extract content between anchor tags with nesting awareness (case-insensitive).

    Tracks multiple tags and only extracts target blocks when at root level
    (not nested inside other tracked tags).

    Extraction logic:
    - Only extracts from root-level tags (nested same-type tags are ignored)
    - Returns the last complete root-level block found
    - Falls back to open-ended <TAG>... to next tracked tag or end if no closing tag
    - Optionally returns full response if no anchors found (fallback_to_full)

    Attributes:
        left: Left anchor (e.g., "<MESSAGE>")
        right: Right anchor (e.g., "</MESSAGE>")
        tracked_tags: List of tag names to track for nesting (e.g., ["ANALYSIS", "MESSAGE", "ACTIONS"])
        fallback_to_full: If True, return full response when anchors not found
    """

    tracked_tags: list[str] = Field(default_factory=list)

    def _get_target_tag_name(self) -> str:
        """Extract the tag name from the left anchor (e.g., '<MESSAGE>' -> 'message')."""
        match = re.match(r"<([A-Za-z_][A-Za-z0-9_]*)>", self.left, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return self.left.lower()

    def _find_root_level_blocks(self, text: str) -> list[str]:
        """
        Find all complete blocks between left and right anchors at root level.

        Uses tracked_tags to find ALL tags, tracks nesting depth by matching
        tag names, and only extracts target blocks when at root level (nesting_depth == 0).

        Returns:
            List of content strings from complete root-level blocks
        """
        target_tag = self._get_target_tag_name()
        tracked_tags_lower = [tag.lower() for tag in self.tracked_tags]

        # Build regex patterns for tracked tags
        opening_pattern = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>", re.IGNORECASE)
        closing_pattern = re.compile(r"</([A-Za-z_][A-Za-z0-9_]*)>", re.IGNORECASE)

        # Build list of events: (position, event_type, tag_name, tag_length)
        # event_type: 'open', 'close', 'target_open', 'target_close'
        events: list[tuple[int, str, str, int]] = []

        # Find all opening tags
        for match in opening_pattern.finditer(text):
            tag_name = match.group(1).lower()
            if tag_name not in tracked_tags_lower:
                continue

            pos = match.start()
            tag_length = len(match.group(0))

            if tag_name == target_tag:
                events.append((pos, "target_open", tag_name, tag_length))
            else:
                events.append((pos, "open", tag_name, tag_length))

        # Find all closing tags
        for match in closing_pattern.finditer(text):
            tag_name = match.group(1).lower()
            if tag_name not in tracked_tags_lower:
                continue

            pos = match.start()
            tag_length = len(match.group(0))

            if tag_name == target_tag:
                events.append((pos, "target_close", tag_name, tag_length))
            else:
                events.append((pos, "close", tag_name, tag_length))

        # Sort by position
        events.sort(key=lambda x: x[0])

        # Track nesting and extract root-level blocks
        blocks = []
        nesting_depth = 0  # Depth of non-target tracked tags
        target_open_pos: int | None = None  # Position where content starts (after opening tag)

        for pos, event_type, tag_name, tag_len in events:
            if event_type == "open":
                nesting_depth += 1
            elif event_type == "close":
                nesting_depth = max(0, nesting_depth - 1)
            elif event_type == "target_open":
                # Only track if we're at root level
                if nesting_depth == 0 and target_open_pos is None:
                    target_open_pos = pos + tag_len
            elif event_type == "target_close":
                # Only capture if we have an open at root level
                if target_open_pos is not None:
                    content = text[target_open_pos:pos]
                    blocks.append(content)
                    target_open_pos = None

        return blocks

    def _extract_open_ended(self, text: str) -> str | None:
        """
        Extract content after the last root-level opening tag to next tracked tag or end.

        Used as fallback when no closing tag is found.
        When tracked_tags are provided, stops at the next tracked tag opening.
        """
        target_tag = self._get_target_tag_name()
        tracked_tags_lower = [tag.lower() for tag in self.tracked_tags]

        # Build regex patterns for tracked tags
        opening_pattern = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>", re.IGNORECASE)
        closing_pattern = re.compile(r"</([A-Za-z_][A-Za-z0-9_]*)>", re.IGNORECASE)

        # Build list of events
        events: list[tuple[int, str, str, int]] = []

        # Find all opening tags
        for match in opening_pattern.finditer(text):
            tag_name = match.group(1).lower()
            if tag_name not in tracked_tags_lower:
                continue

            pos = match.start()
            tag_length = len(match.group(0))

            if tag_name == target_tag:
                events.append((pos, "target_open", tag_name, tag_length))
            else:
                events.append((pos, "open", tag_name, tag_length))

        # Find all closing tags
        for match in closing_pattern.finditer(text):
            tag_name = match.group(1).lower()
            if tag_name not in tracked_tags_lower:
                continue

            pos = match.start()
            tag_length = len(match.group(0))
            events.append((pos, "close", tag_name, tag_length))

        # Sort by position
        events.sort(key=lambda x: x[0])

        # Find root-level target opens
        root_level_opens: list[tuple[int, int]] = []  # (position, tag_length)
        nesting_depth = 0

        for pos, event_type, tag_name, tag_len in events:
            if event_type == "open":
                nesting_depth += 1
            elif event_type == "close":
                nesting_depth = max(0, nesting_depth - 1)
            elif event_type == "target_open":
                if nesting_depth == 0:
                    root_level_opens.append((pos, tag_len))

        if not root_level_opens:
            return None

        # Use the last root-level target open
        last_open, tag_len = root_level_opens[-1]
        content_start = last_open + tag_len

        # Find the next tracked tag after content_start (for stop_at behavior)
        next_tag_pos = None
        for match in opening_pattern.finditer(text[content_start:]):
            tag_name = match.group(1).lower()
            if tag_name in tracked_tags_lower and tag_name != target_tag:
                next_tag_pos = content_start + match.start()
                break

        if next_tag_pos is not None:
            content = text[content_start:next_tag_pos]
        else:
            content = text[content_start:]

        return content if content.strip() else None

    def extract(self, text: str) -> str | None:
        """
        Extract content between anchor tags with nesting awareness.

        Args:
            text: The text to extract from

        Returns:
            The extracted content, or None if not found
        """
        if not text:
            return None

        # Step 1: Find root-level blocks
        blocks = self._find_root_level_blocks(text)
        if blocks:
            # Return the last block
            return self._apply_trim(blocks[-1])

        # Step 2: Try open-ended extraction (no closing tag)
        open_ended = self._extract_open_ended(text)
        if open_ended is not None:
            return self._apply_trim(open_ended)

        # Step 3: If fallback_to_full is enabled, return the full response
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


class CodeBlockExtractorMixin:
    """
    Mixin providing code fence extraction logic for code block extractors.

    Classes using this mixin should define:
        validate_structured: bool = True
    """

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

    def _extract_code_block_from_content(self, block_content: str) -> str | None:
        """
        Extract code block content from inside a tagged block.

        Args:
            block_content: The content between the tags (without the tags themselves)

        Returns:
            The extracted code block content, or None if not found
        """
        if not block_content:
            return None

        # Step 1: Try ```lang...``` pattern (complete code fence)
        fenced_pattern = r"```(?:json|yaml)?\s*([\s\S]*?)\s*```"
        match = re.search(fenced_pattern, block_content, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Step 2: Try ```lang... to end (missing closing fence)
        open_fence_pattern = r"```(?:json|yaml)?\s*([\s\S]*?)$"
        match = re.search(open_fence_pattern, block_content, re.IGNORECASE)
        if match:
            content = match.group(1).strip()
            if content:
                return content

        # Step 3: No code fence - validate as structured data if enabled
        raw_content = block_content.strip()
        if raw_content:
            if self.validate_structured:
                if self._is_valid_structured_data(raw_content):
                    return raw_content
            else:
                return raw_content

        return None


class CodeBlockExtractor(AnchorExtractor, CodeBlockExtractorMixin):
    """
    Extract content from inside a tagged section containing a code block.

    All matching is case-insensitive. Extends AnchorExtractor for simple extraction.

    Extraction logic:
    1. Try full <TAG>```lang...```</TAG> pattern
    2. Fall back to <TAG>```lang...``` (missing closing tag)
    3. Fall back to <TAG>```lang... to end (missing code fence close)
    4. Fall back to <TAG>...</TAG> with JSON/YAML validation (no code fence)

    Attributes:
        left: Left anchor (e.g., "<ACTIONS>")
        right: Right anchor (e.g., "</ACTIONS>")
        validate_structured: Whether to validate content as JSON/YAML for no-fence fallback
    """

    validate_structured: bool = True

    def extract(self, text: str) -> str | None:
        """
        Extract content from a code block inside tagged section.

        Uses parent's root-level block detection to find the correct tag,
        then extracts the code block content from within.

        Args:
            text: The text to extract from

        Returns:
            The extracted content, or None if not found
        """
        if not text:
            return None

        # Step 1: Find root-level blocks using parent's logic
        blocks = self._find_root_level_blocks(text)
        if blocks:
            # Try to extract code block from the last root-level block
            content = self._extract_code_block_from_content(blocks[-1])
            if content:
                return self._apply_trim(content)

        # Step 2: Try open-ended extraction (no closing tag)
        open_ended = self._extract_open_ended(text)
        if open_ended is not None:
            content = self._extract_code_block_from_content(open_ended)
            if content:
                return self._apply_trim(content)

        return None


class ComplexCodeBlockExtractor(ComplexAnchorExtractor, CodeBlockExtractorMixin):
    """
    Extract content from inside a tagged section containing a code block, with nesting awareness.

    All matching is case-insensitive. Extends ComplexAnchorExtractor for nesting-aware extraction.

    Extraction logic:
    1. Try full <TAG>```lang...```</TAG> pattern (at root level only)
    2. Fall back to <TAG>```lang...``` (missing closing tag)
    3. Fall back to <TAG>```lang... to end (missing code fence close)
    4. Fall back to <TAG>...</TAG> with JSON/YAML validation (no code fence)

    Attributes:
        left: Left anchor (e.g., "<ACTIONS>")
        right: Right anchor (e.g., "</ACTIONS>")
        tracked_tags: List of tag names to track for nesting
        validate_structured: Whether to validate content as JSON/YAML for no-fence fallback
    """

    validate_structured: bool = True

    def extract(self, text: str) -> str | None:
        """
        Extract content from a code block inside tagged section with nesting awareness.

        Uses parent's root-level block detection to find the correct tag,
        then extracts the code block content from within.

        Args:
            text: The text to extract from

        Returns:
            The extracted content, or None if not found
        """
        if not text:
            return None

        # Step 1: Find root-level blocks using parent's logic
        blocks = self._find_root_level_blocks(text)
        if blocks:
            # Try to extract code block from the last root-level block
            content = self._extract_code_block_from_content(blocks[-1])
            if content:
                return self._apply_trim(content)

        # Step 2: Try open-ended extraction (no closing tag)
        open_ended = self._extract_open_ended(text)
        if open_ended is not None:
            content = self._extract_code_block_from_content(open_ended)
            if content:
                return self._apply_trim(content)

        return None


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
