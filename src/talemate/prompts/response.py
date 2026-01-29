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
    - Returns the last complete block found
    - Falls back to open-ended <TAG>... to end if no closing tag
    - Can optionally stop at another tag (e.g., <ACTIONS>)
    - Optionally returns full response if no anchors found (fallback_to_full)

    Nesting awareness (opt-in):
    - By default (patterns=None), uses simple extraction that only tracks the target tag
    - If both opening_tag_pattern and closing_tag_pattern are provided, uses them
      to detect ALL tags and only extracts target blocks when at root level (depth=0)

    Attributes:
        left: Left anchor (e.g., "<MESSAGE>")
        right: Right anchor (e.g., "</MESSAGE>")
        stop_at: Tag to stop at for open-ended matches (e.g., "<ACTIONS>")
        fallback_to_full: If True, return full response when anchors not found
        opening_tag_pattern: Optional regex pattern to match opening tags (group 1 = tag name).
            Example: r"<([A-Za-z_][A-Za-z0-9_]*)[^>]*>" for XML-style tags.
        closing_tag_pattern: Optional regex pattern to match closing tags (group 1 = tag name).
            Example: r"</([A-Za-z_][A-Za-z0-9_]*)[^>]*>" for XML-style tags.
    """

    left: str
    right: str
    stop_at: str | None = None
    fallback_to_full: bool = False
    opening_tag_pattern: str | None = None
    closing_tag_pattern: str | None = None

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
        Find all complete blocks between left and right anchors at root level.

        Behavior depends on whether tag patterns are provided:
        - If patterns are None (default): Simple extraction that only tracks the target tag.
          Finds all occurrences of left/right anchors and matches them with a stack.
        - If both patterns are provided: Uses them to find ALL tags, tracks nesting depth,
          and only extracts target blocks when at root level (nesting_depth == 0).

        Returns:
            List of content strings from complete root-level blocks
        """
        if self.opening_tag_pattern is None or self.closing_tag_pattern is None:
            return self._find_root_level_blocks_simple(text)
        else:
            return self._find_root_level_blocks_nesting_aware(text)

    def _find_root_level_blocks_simple(self, text: str) -> list[str]:
        """
        Simple extraction that only tracks the target tag (left/right).

        Uses a stack-based approach to match opening and closing tags,
        handling nested same-type tags correctly.

        Returns:
            List of content strings from complete blocks
        """
        left_lower = self.left.lower()
        right_lower = self.right.lower()

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

    def _find_root_level_blocks_nesting_aware(self, text: str) -> list[str]:
        """
        Nesting-aware extraction using custom tag patterns.

        Uses opening_tag_pattern and closing_tag_pattern to find ALL tags,
        tracks nesting depth by matching tag names, and only extracts
        target blocks when at root level (nesting_depth == 0).

        Returns:
            List of content strings from complete root-level blocks
        """
        opening_pattern = re.compile(self.opening_tag_pattern, re.IGNORECASE)
        closing_pattern = re.compile(self.closing_tag_pattern, re.IGNORECASE)

        left_lower = self.left.lower()
        right_lower = self.right.lower()

        # Build list of events: (position, event_type, tag_name, tag_length)
        # event_type: 'open', 'close', 'target_open', 'target_close'
        events: list[tuple[int, str, str, int]] = []

        # Find all opening tags
        for match in opening_pattern.finditer(text):
            pos = match.start()
            tag_name = match.group(1).lower()
            tag_length = len(match.group(0))
            full_tag = match.group(0).lower()

            # Check if this is our target opening tag
            if full_tag == left_lower:
                events.append((pos, "target_open", tag_name, tag_length))
            else:
                events.append((pos, "open", tag_name, tag_length))

        # Find all closing tags
        for match in closing_pattern.finditer(text):
            pos = match.start()
            tag_name = match.group(1).lower()
            tag_length = len(match.group(0))
            full_tag = match.group(0).lower()

            # Check if this is our target closing tag
            if full_tag == right_lower:
                events.append((pos, "target_close", tag_name, tag_length))
            else:
                events.append((pos, "close", tag_name, tag_length))

        # Sort by position
        events.sort(key=lambda x: x[0])

        # Track nesting and extract root-level blocks
        blocks = []
        nesting_depth = 0  # Depth of non-target tags
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
        Extract content after the last opening tag to end of text (or stop_at).

        Used as fallback when no closing tag is found.
        When nesting patterns are provided, only considers opening tags at root level.
        """
        if self.opening_tag_pattern is not None and self.closing_tag_pattern is not None:
            # Use nesting-aware logic to find root-level open positions
            open_positions = self._find_root_level_open_positions(text)
        else:
            # Simple text search
            open_positions = self._find_all_markers(text, self.left)

        if not open_positions:
            return None

        # Use the last opening tag (position, tag_length)
        if isinstance(open_positions[0], tuple):
            last_open, tag_len = open_positions[-1]
            content_start = last_open + tag_len
        else:
            last_open = open_positions[-1]
            content_start = last_open + len(self.left)

        content = text[content_start:]

        # Apply stop_at if configured
        if self.stop_at:
            stop_idx = self._find_marker(content, self.stop_at)
            if stop_idx is not None:
                content = content[:stop_idx]

        return content if content.strip() else None

    def _find_root_level_open_positions(self, text: str) -> list[tuple[int, int]]:
        """
        Find positions of target opening tags that are at root level (nesting depth = 0).

        Returns:
            List of (position, tag_length) tuples for root-level target opening tags
        """
        opening_pattern = re.compile(self.opening_tag_pattern, re.IGNORECASE)
        closing_pattern = re.compile(self.closing_tag_pattern, re.IGNORECASE)

        left_lower = self.left.lower()

        # Build list of events: (position, event_type, tag_name, tag_length)
        events: list[tuple[int, str, str, int]] = []

        # Find all opening tags
        for match in opening_pattern.finditer(text):
            pos = match.start()
            tag_name = match.group(1).lower()
            tag_length = len(match.group(0))
            full_tag = match.group(0).lower()

            if full_tag == left_lower:
                events.append((pos, "target_open", tag_name, tag_length))
            else:
                events.append((pos, "open", tag_name, tag_length))

        # Find all closing tags
        for match in closing_pattern.finditer(text):
            pos = match.start()
            tag_name = match.group(1).lower()
            tag_length = len(match.group(0))
            events.append((pos, "close", tag_name, tag_length))

        # Sort by position
        events.sort(key=lambda x: x[0])

        # Track nesting and find root-level target opens
        root_level_opens: list[tuple[int, int]] = []
        nesting_depth = 0

        for pos, event_type, tag_name, tag_len in events:
            if event_type == "open":
                nesting_depth += 1
            elif event_type == "close":
                nesting_depth = max(0, nesting_depth - 1)
            elif event_type == "target_open":
                if nesting_depth == 0:
                    root_level_opens.append((pos, tag_len))

        return root_level_opens

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


class CodeBlockExtractor(AnchorExtractor):
    """
    Extract content from inside a tagged section containing a code block.

    All matching is case-insensitive. Extends AnchorExtractor.

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
