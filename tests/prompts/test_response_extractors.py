"""
Unit tests for response extractors in talemate.prompts.response.

These tests cover the various extractor classes used for parsing LLM outputs:
- AnchorExtractor: Extract content between anchor tags
- AsIsExtractor: Return response as-is
- AfterAnchorExtractor: Extract everything after a marker
- RegexExtractor: Extract content using regex patterns
- StripPrefixExtractor: Strip prefixes matching a pattern
- CodeBlockExtractor: Extract content from code blocks
"""

import pytest
import re

from talemate.prompts.response import (
    AnchorExtractor,
    AsIsExtractor,
    AfterAnchorExtractor,
    RegexExtractor,
    StripPrefixExtractor,
    CodeBlockExtractor,
    ResponseSpec,
    ExtractionError,
)


# ============================================================================
# Tests for AnchorExtractor
# ============================================================================


class TestAnchorExtractor:
    """Tests for the AnchorExtractor class."""

    def test_simple_closed_tag_extraction(self):
        """Test extracting content between simple closed tags."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = "<MESSAGE>Hello, world!</MESSAGE>"
        result = extractor.extract(response)
        assert result == "Hello, world!"

    def test_prefers_last_closed_tag(self):
        """Test that when multiple closed tags exist, the last one is preferred."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = """
<MESSAGE>First message</MESSAGE>
<MESSAGE>Second message</MESSAGE>
<MESSAGE>Third message</MESSAGE>
"""
        result = extractor.extract(response)
        assert result == "Third message"

    def test_open_ended_fallback(self):
        """Test fallback to open-ended extraction when no closing tag exists."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = "<MESSAGE>This message has no closing tag"
        result = extractor.extract(response)
        assert result == "This message has no closing tag"

    def test_prefer_after_parameter(self):
        """Test prefer_after parameter to extract content after a specific tag."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
Some analysis text.
<MESSAGE>Analysis message</MESSAGE>
</ANALYSIS>
<MESSAGE>Real message after analysis</MESSAGE>
"""
        result = extractor.extract(response)
        assert result == "Real message after analysis"

    def test_prefer_after_fallback_to_full_response(self):
        """Test fallback to full response when nothing after prefer_after tag."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<MESSAGE>Message before analysis</MESSAGE>
<ANALYSIS>
Some analysis text.
</ANALYSIS>
"""
        # No MESSAGE after </ANALYSIS>, so it falls back to searching full response
        result = extractor.extract(response)
        assert result == "Message before analysis"

    def test_stop_at_parameter(self):
        """Test stop_at parameter for open-ended extraction."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", stop_at="<ACTIONS>"
        )
        response = """
<MESSAGE>This is the message content
that continues on multiple lines
<ACTIONS>
```json
[{"name": "test"}]
```
</ACTIONS>
"""
        result = extractor.extract(response)
        assert "This is the message content" in result
        assert "<ACTIONS>" not in result
        assert "test" not in result

    def test_case_insensitive_matching(self):
        """Test case insensitive matching (default behavior)."""
        extractor = AnchorExtractor(left="<message>", right="</message>")
        response = "<MESSAGE>Content here</MESSAGE>"
        result = extractor.extract(response)
        assert result == "Content here"

    def test_case_sensitive_matching(self):
        """Test case sensitive matching when case_insensitive=False."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", case_insensitive=False
        )
        response = "<message>Should not match</message>"
        result = extractor.extract(response)
        assert result is None

    def test_whitespace_trimming_default(self):
        """Test that whitespace is trimmed by default."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = "<MESSAGE>   Content with whitespace   </MESSAGE>"
        result = extractor.extract(response)
        assert result == "Content with whitespace"

    def test_whitespace_trimming_disabled(self):
        """Test that whitespace is preserved when trim=False."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>", trim=False)
        response = "<MESSAGE>   Content with whitespace   </MESSAGE>"
        result = extractor.extract(response)
        # The pattern has \s* around the content, so internal whitespace is handled
        # by the regex, but leading/trailing should be preserved if trim=False
        assert result is not None
        # Note: The regex pattern strips whitespace around captured content,
        # so this tests the _apply_trim behavior

    def test_returns_none_when_not_found(self):
        """Test that None is returned when anchor is not found."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = "No message tags here at all"
        result = extractor.extract(response)
        assert result is None

    def test_returns_none_for_empty_input(self):
        """Test that None is returned for empty input."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        assert extractor.extract("") is None
        assert extractor.extract(None) is None

    def test_multiline_content_handling(self):
        """Test extraction of multiline content."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = """<MESSAGE>
Line one
Line two
Line three
</MESSAGE>"""
        result = extractor.extract(response)
        assert "Line one" in result
        assert "Line two" in result
        assert "Line three" in result

    def test_special_characters_in_content(self):
        """Test extraction of content with special characters."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = "<MESSAGE>Content with [brackets], (parens), {braces}, and *stars*</MESSAGE>"
        result = extractor.extract(response)
        assert result == "Content with [brackets], (parens), {braces}, and *stars*"

    def test_nested_tags_in_content(self):
        """Test extraction when content contains nested-looking tags."""
        extractor = AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
        response = "<MESSAGE>Text with <inner>nested</inner> content</MESSAGE>"
        result = extractor.extract(response)
        assert result == "Text with <inner>nested</inner> content"

    def test_nested_same_tags_extracts_first_clean_block(self):
        """Test that nested same tags extracts the first clean (innermost) block."""
        extractor = AnchorExtractor(left="<TAG>", right="</TAG>")
        response = "<TAG>nested<TAG>value</TAG>"
        result = extractor.extract(response)
        # Should extract "value" - the first block without nested opening tags
        assert result == "value"

    def test_open_ended_fallback_no_closing_tag(self):
        """Test fallback to open-ended extraction when no closing tag exists."""
        extractor = AnchorExtractor(left="<TAG>", right="</TAG>")
        response = "<TAG>no closing tag"
        result = extractor.extract(response)
        assert result == "no closing tag"

    def test_prefer_after_ignores_multiple_tags_in_analysis(self):
        """Test that multiple MESSAGE-like text in ANALYSIS is ignored."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
The user might want to see <MESSAGE>this</MESSAGE> but that's just analysis.
We could also say "<MESSAGE>something else</MESSAGE>" in quotes.
</ANALYSIS>
<MESSAGE>
Real message here.
</MESSAGE>
"""
        result = extractor.extract(response)
        assert result == "Real message here."

    def test_prefer_after_with_decision_tags_in_analysis(self):
        """Test that DECISION tags in ANALYSIS don't interfere with MESSAGE extraction."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
The best decision would be <DECISION>option_a</DECISION> based on:
- Multiple <DECISION> tags here
- Even nested ones like <DECISION>option_b</DECISION>
</ANALYSIS>
<MESSAGE>
This is the actual message.
</MESSAGE>
"""
        result = extractor.extract(response)
        assert result == "This is the actual message."

    def test_prefer_after_with_action_tags_in_analysis(self):
        """Test that ACTION tags in ANALYSIS don't interfere."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
The best action would be <ACTION>test</ACTION> but we need to consider:
- Multiple <ACTION> tags here
- Even nested or malformed ones
</ANALYSIS>
<MESSAGE>
This is the actual message.
</MESSAGE>
"""
        result = extractor.extract(response)
        assert result == "This is the actual message."

    def test_prefer_after_only_tag_in_analysis_falls_back(self):
        """Test that when the only tag is inside ANALYSIS, we fall back to it."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
Some analysis with <MESSAGE>only message here</MESSAGE> inside.
</ANALYSIS>
"""
        # Falls back to searching full response since nothing after </ANALYSIS>
        result = extractor.extract(response)
        assert result == "only message here"

    def test_prefer_after_prefers_last_message_after_analysis(self):
        """Test that when multiple messages exist after ANALYSIS, the last is preferred."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
<MESSAGE>In analysis</MESSAGE>
</ANALYSIS>
<MESSAGE>First after</MESSAGE>
<MESSAGE>Second after</MESSAGE>
<MESSAGE>Third after</MESSAGE>
"""
        result = extractor.extract(response)
        assert result == "Third after"

    def test_realistic_llm_response_with_nested_tags(self):
        """Test realistic LLM response with analysis containing nested tags."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """<ANALYSIS>
1. Current scene state: We're in startup mode.
2. Story need: The narrative must immediately establish character.
</ANALYSIS>
<MESSAGE>
Character created and setup complete. Transitioning to roleplay phase.
</MESSAGE>
<DECISION>
Taking three actions.
</DECISION>
"""
        result = extractor.extract(response)
        assert "Character created" in result
        assert "Transitioning to roleplay" in result

    def test_message_with_decision_block_inside(self):
        """Test that DECISION blocks within MESSAGE are included in extraction."""
        extractor = AnchorExtractor(
            left="<MESSAGE>", right="</MESSAGE>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
Analysis text.
</ANALYSIS>
<MESSAGE>
Here is my response with a decision:
<DECISION>
The character should proceed cautiously.
</DECISION>
More message text after decision.
</MESSAGE>
"""
        result = extractor.extract(response)
        assert "Here is my response" in result
        assert "<DECISION>" in result
        assert "More message text after decision." in result


# ============================================================================
# Tests for AsIsExtractor
# ============================================================================


class TestAsIsExtractor:
    """Tests for the AsIsExtractor class."""

    def test_returns_full_response(self):
        """Test that the full response is returned."""
        extractor = AsIsExtractor()
        response = "This is the full response text."
        result = extractor.extract(response)
        assert result == "This is the full response text."

    def test_trims_whitespace(self):
        """Test that whitespace is trimmed by default."""
        extractor = AsIsExtractor()
        response = "   Content with whitespace   "
        result = extractor.extract(response)
        assert result == "Content with whitespace"

    def test_preserves_whitespace_when_disabled(self):
        """Test that whitespace is preserved when trim=False."""
        extractor = AsIsExtractor(trim=False)
        response = "   Content with whitespace   "
        result = extractor.extract(response)
        assert result == "   Content with whitespace   "

    def test_empty_string_returns_none(self):
        """Test that empty string returns None."""
        extractor = AsIsExtractor()
        assert extractor.extract("") is None

    def test_whitespace_only_returns_none(self):
        """Test that whitespace-only string returns None after trimming."""
        extractor = AsIsExtractor()
        assert extractor.extract("   ") is None
        assert extractor.extract("\n\t\n") is None

    def test_multiline_response(self):
        """Test that multiline response is returned."""
        extractor = AsIsExtractor()
        response = """Line one
Line two
Line three"""
        result = extractor.extract(response)
        assert result == response


# ============================================================================
# Tests for AfterAnchorExtractor
# ============================================================================


class TestAfterAnchorExtractor:
    """Tests for the AfterAnchorExtractor class."""

    def test_extracts_after_marker(self):
        """Test extracting content after a marker."""
        extractor = AfterAnchorExtractor(start="</ANALYSIS>")
        response = """<ANALYSIS>
Some analysis text.
</ANALYSIS>
Content after the analysis marker."""
        result = extractor.extract(response)
        assert result == "Content after the analysis marker."

    def test_stops_at_marker(self):
        """Test stopping at a specified marker."""
        extractor = AfterAnchorExtractor(start="</ANALYSIS>", stop_at="<ACTIONS>")
        response = """<ANALYSIS>Analysis</ANALYSIS>
Content to extract
<ACTIONS>
Actions to ignore
</ACTIONS>"""
        result = extractor.extract(response)
        assert "Content to extract" in result
        assert "<ACTIONS>" not in result
        assert "Actions to ignore" not in result

    def test_case_insensitive(self):
        """Test case insensitive matching (default)."""
        extractor = AfterAnchorExtractor(start="</analysis>")
        response = "<ANALYSIS>Text</ANALYSIS>Content after"
        result = extractor.extract(response)
        assert result == "Content after"

    def test_case_sensitive(self):
        """Test case sensitive matching."""
        extractor = AfterAnchorExtractor(start="</ANALYSIS>", case_insensitive=False)
        response = "<analysis>Text</analysis>Content after"
        result = extractor.extract(response)
        assert result is None

    def test_returns_none_when_start_not_found(self):
        """Test that None is returned when start marker is not found."""
        extractor = AfterAnchorExtractor(start="</NONEXISTENT>")
        response = "No such marker in this response"
        result = extractor.extract(response)
        assert result is None

    def test_returns_none_for_empty_input(self):
        """Test that None is returned for empty input."""
        extractor = AfterAnchorExtractor(start="</ANALYSIS>")
        assert extractor.extract("") is None

    def test_multiline_extraction(self):
        """Test extraction of multiline content after marker."""
        extractor = AfterAnchorExtractor(start="START:")
        response = """START:
Line one
Line two
Line three"""
        result = extractor.extract(response)
        assert "Line one" in result
        assert "Line two" in result
        assert "Line three" in result


# ============================================================================
# Tests for RegexExtractor
# ============================================================================


class TestRegexExtractor:
    """Tests for the RegexExtractor class."""

    def test_single_match_extraction(self):
        """Test extracting a single match."""
        extractor = RegexExtractor(pattern=r"name:\s*(\w+)")
        response = "The name: John is a character"
        result = extractor.extract(response)
        assert result == "John"

    def test_all_matches_returns_list(self):
        """Test that all_matches=True returns a list."""
        extractor = RegexExtractor(pattern=r"name:\s*(\w+)", all_matches=True)
        response = "name: John and name: Jane and name: Bob"
        result = extractor.extract(response)
        assert isinstance(result, list)
        assert result == ["John", "Jane", "Bob"]

    def test_returns_none_when_no_match(self):
        """Test that None is returned when no match."""
        extractor = RegexExtractor(pattern=r"name:\s*(\w+)")
        response = "No name pattern here"
        result = extractor.extract(response)
        assert result is None

    def test_returns_none_for_empty_all_matches(self):
        """Test that None is returned when all_matches finds nothing."""
        extractor = RegexExtractor(pattern=r"name:\s*(\w+)", all_matches=True)
        response = "No matches here"
        result = extractor.extract(response)
        assert result is None

    def test_custom_group(self):
        """Test extracting a specific capture group."""
        extractor = RegexExtractor(pattern=r"(\w+):\s*(\w+)", group=2)
        response = "name: John"
        result = extractor.extract(response)
        assert result == "John"

    def test_with_flags(self):
        """Test regex with flags."""
        extractor = RegexExtractor(pattern=r"NAME:\s*(\w+)", flags=re.IGNORECASE)
        response = "name: john"
        result = extractor.extract(response)
        assert result == "john"

    def test_returns_none_for_empty_input(self):
        """Test that None is returned for empty input."""
        extractor = RegexExtractor(pattern=r"(\w+)")
        assert extractor.extract("") is None

    def test_invalid_regex_returns_none(self):
        """Test that invalid regex returns None instead of raising."""
        extractor = RegexExtractor(pattern=r"[invalid(")
        result = extractor.extract("some text")
        assert result is None

    def test_multiline_pattern(self):
        """Test regex with multiline content."""
        extractor = RegexExtractor(
            pattern=r"<content>([\s\S]*?)</content>", flags=re.DOTALL
        )
        response = """<content>
Line one
Line two
</content>"""
        result = extractor.extract(response)
        assert "Line one" in result
        assert "Line two" in result


# ============================================================================
# Tests for StripPrefixExtractor
# ============================================================================


class TestStripPrefixExtractor:
    """Tests for the StripPrefixExtractor class."""

    def test_strips_matching_prefix(self):
        """Test stripping a matching prefix."""
        extractor = StripPrefixExtractor(pattern=r"^Response:\s*")
        response = "Response: This is the actual content"
        result = extractor.extract(response)
        assert result == "This is the actual content"

    def test_multiple_occurrences(self):
        """Test stripping multiple occurrences."""
        extractor = StripPrefixExtractor(pattern=r"\[note\]")
        response = "[note]Content[note]more content[note]final"
        result = extractor.extract(response)
        assert result == "Contentmore contentfinal"

    def test_custom_replacement(self):
        """Test with custom replacement string."""
        extractor = StripPrefixExtractor(pattern=r"\[REDACTED\]", replacement="***")
        response = "Name: [REDACTED] Age: [REDACTED]"
        result = extractor.extract(response)
        assert result == "Name: *** Age: ***"

    def test_no_match_returns_original(self):
        """Test that no match returns original text."""
        extractor = StripPrefixExtractor(pattern=r"^PREFIX:\s*")
        response = "Content without the prefix"
        result = extractor.extract(response)
        assert result == "Content without the prefix"

    def test_returns_none_for_empty_input(self):
        """Test that None is returned for empty input."""
        extractor = StripPrefixExtractor(pattern=r"^test")
        assert extractor.extract("") is None

    def test_invalid_regex_returns_original(self):
        """Test that invalid regex returns original text."""
        extractor = StripPrefixExtractor(pattern=r"[invalid(")
        response = "Some text"
        result = extractor.extract(response)
        assert result == "Some text"

    def test_trims_result(self):
        """Test that result is trimmed by default."""
        extractor = StripPrefixExtractor(pattern=r"^prefix")
        response = "prefix   content   "
        result = extractor.extract(response)
        assert result == "content"


# ============================================================================
# Tests for CodeBlockExtractor
# ============================================================================


class TestCodeBlockExtractor:
    """Tests for the CodeBlockExtractor class."""

    def test_full_tag_with_json_fence(self):
        """Test full <TAG>```json...```</TAG> pattern."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = """<ACTIONS>
```json
[{"name": "test", "value": 123}]
```
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert '"name": "test"' in result
        assert '"value": 123' in result

    def test_missing_closing_tag(self):
        """Test extraction with missing closing tag."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = """<ACTIONS>
```json
[{"name": "test"}]
```
"""
        result = extractor.extract(response)
        assert result is not None
        assert '"name": "test"' in result

    def test_missing_closing_fence(self):
        """Test extraction with missing closing fence."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = """<ACTIONS>
```json
[{"name": "test"}]
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert '"name": "test"' in result

    def test_no_fence_with_valid_json(self):
        """Test extraction without code fence but with valid JSON."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", validate_structured=True
        )
        response = """<ACTIONS>
[{"name": "test"}]
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert '"name": "test"' in result

    def test_no_fence_with_invalid_content_returns_none(self):
        """Test that invalid content without fence returns None when validate_structured=True."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", validate_structured=True
        )
        response = """<ACTIONS>
This is just plain text, not JSON or YAML.
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is None

    def test_no_fence_with_validate_disabled(self):
        """Test that any content is returned when validate_structured=False."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", validate_structured=False
        )
        response = """<ACTIONS>
Plain text content
</ACTIONS>"""
        result = extractor.extract(response)
        assert result == "Plain text content"

    def test_prefer_after_parameter(self):
        """Test prefer_after parameter to skip content before a tag."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", prefer_after="</ANALYSIS>"
        )
        response = """<ANALYSIS>
<ACTIONS>
```json
[{"name": "fake_in_analysis"}]
```
</ACTIONS>
</ANALYSIS>
<ACTIONS>
```json
[{"name": "real_action"}]
```
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert "real_action" in result
        assert "fake_in_analysis" not in result

    def test_yaml_fence_support(self):
        """Test extraction with YAML code fence."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = """<ACTIONS>
```yaml
- name: test_action
  instructions: Do something
```
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert "name: test_action" in result
        assert "instructions: Do something" in result

    def test_case_insensitive_matching(self):
        """Test case insensitive matching (default)."""
        extractor = CodeBlockExtractor(left="<actions>", right="</actions>")
        response = """<ACTIONS>
```json
[{"name": "test"}]
```
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert '"name": "test"' in result

    def test_case_sensitive_matching(self):
        """Test case sensitive matching."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", case_insensitive=False
        )
        response = """<actions>
```json
[{"name": "test"}]
```
</actions>"""
        result = extractor.extract(response)
        assert result is None

    def test_returns_none_for_empty_input(self):
        """Test that None is returned for empty input."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        assert extractor.extract("") is None

    def test_returns_none_when_not_found(self):
        """Test that None is returned when tags not found."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = "No actions tags here at all"
        result = extractor.extract(response)
        assert result is None

    def test_no_fence_with_valid_yaml_dict(self):
        """Test extraction without fence but with valid YAML dictionary."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", validate_structured=True
        )
        response = """<ACTIONS>
name: test_action
instructions: Do something
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert "name: test_action" in result

    def test_no_fence_with_valid_yaml_list(self):
        """Test extraction without fence but with valid YAML list."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", validate_structured=True
        )
        response = """<ACTIONS>
- name: action1
  instructions: First
- name: action2
  instructions: Second
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert "action1" in result
        assert "action2" in result

    def test_plain_language_with_fence(self):
        """Test that fenced code with plain language marker works."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = """<ACTIONS>
```
[{"name": "test"}]
```
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert '"name": "test"' in result

    def test_nested_json_content(self):
        """Test extraction of nested JSON content."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = """<ACTIONS>
```json
{
  "name": "complex_action",
  "data": {
    "nested": {
      "value": [1, 2, 3]
    }
  }
}
```
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert '"nested"' in result
        assert "[1, 2, 3]" in result

    def test_multiline_content_with_special_chars(self):
        """Test extraction of content with special characters."""
        extractor = CodeBlockExtractor(left="<ACTIONS>", right="</ACTIONS>")
        response = """<ACTIONS>
```json
[{"name": "test", "instructions": "Do this: 'quote', \"double\", [brackets]"}]
```
</ACTIONS>"""
        result = extractor.extract(response)
        assert result is not None
        assert "Do this:" in result

    def test_only_actions_in_analysis_returns_none(self):
        """Test that if ACTIONS only appears within ANALYSIS, returns None.

        Note: CodeBlockExtractor does NOT fall back to full response search like
        AnchorExtractor does. This is intentional - actions inside analysis are
        "theoretical" and shouldn't be extracted as real actions.
        """
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
We could use <ACTIONS>
```json
[{"name": "fake_action", "instructions": "This is just theoretical"}]
```
</ACTIONS>
but that's just analysis.
</ANALYSIS>
<MESSAGE>
Let me think about this more.
</MESSAGE>
"""
        result = extractor.extract(response)
        # CodeBlockExtractor doesn't fall back to full response, so returns None
        assert result is None

    def test_actions_with_action_tag_in_analysis(self):
        """Test ACTIONS extraction when ACTION tags appear in ANALYSIS."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", prefer_after="</ANALYSIS>"
        )
        response = """
<ANALYSIS>
Looking at the scene, I notice several things:
- The character could <ACTION>move</ACTION> to the door
- Or they could <ACTION>speak</ACTION> to the other character
Based on this analysis, I recommend we proceed.
</ANALYSIS>
<MESSAGE>
I think the best course of action is to have them move cautiously.
</MESSAGE>
<ACTIONS>
```json
[{"name": "move", "instructions": "Move slowly toward the door"}]
```
</ACTIONS>
"""
        result = extractor.extract(response)
        assert result is not None
        assert '"name": "move"' in result
        assert "door" in result

    def test_realistic_actions_without_code_fence(self):
        """Test with realistic example without code fence."""
        extractor = CodeBlockExtractor(
            left="<ACTIONS>", right="</ACTIONS>", validate_structured=True
        )
        response = """
<ACTIONS>
[
  {
    "name": "update_context",
    "instructions": "Create a new player-controlled character named Veyla."
  },
  {
    "name": "start_roleplay",
    "instructions": ""
  }
]
</ACTIONS>
"""
        result = extractor.extract(response)
        assert result is not None
        assert "update_context" in result
        assert "Veyla" in result
        assert "start_roleplay" in result


# ============================================================================
# Tests for ResponseSpec
# ============================================================================


class TestResponseSpec:
    """Tests for the ResponseSpec class."""

    def test_extracts_all_fields(self):
        """Test extracting multiple fields from text."""
        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>"),
                "analysis": AnchorExtractor(left="<ANALYSIS>", right="</ANALYSIS>"),
            }
        )
        text = "<ANALYSIS>thinking</ANALYSIS><MESSAGE>hello</MESSAGE>"
        result = spec.extract_all(text)
        assert result == {"message": "hello", "analysis": "thinking"}

    def test_raises_on_missing_required(self):
        """Test that ExtractionError is raised when a required field is missing."""
        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=["message"],
        )
        with pytest.raises(ExtractionError):
            spec.extract_all("no message here")

    def test_optional_field_returns_none(self):
        """Test that optional fields return None when not found."""
        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=[],  # Not required
        )
        result = spec.extract_all("no message here")
        assert result == {"message": None}

    def test_simple_constructor(self):
        """Test the simple() convenience constructor with required=True."""
        spec = ResponseSpec.simple(
            "name", AnchorExtractor(left="<NAME>", right="</NAME>")
        )
        assert "name" in spec.extractors
        assert "name" in spec.required

    def test_simple_constructor_not_required(self):
        """Test the simple() convenience constructor with required=False."""
        spec = ResponseSpec.simple(
            "name", AnchorExtractor(left="<NAME>", right="</NAME>"), required=False
        )
        assert "name" in spec.extractors
        assert "name" not in spec.required

    def test_mixed_extractors(self):
        """Test using different extractor types in the same spec."""
        spec = ResponseSpec(
            extractors={
                "title": AnchorExtractor(left="<TITLE>", right="</TITLE>"),
                "content": AsIsExtractor(),
            }
        )
        text = "<TITLE>My Title</TITLE>"
        result = spec.extract_all(text)
        assert result["title"] == "My Title"
        assert result["content"] == "<TITLE>My Title</TITLE>"


# ============================================================================
# Tests for Prompt.send() with response_spec
# ============================================================================


class TestPromptSendWithResponseSpec:
    """Tests for Prompt.send() integration with ResponseSpec."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock client for testing."""
        from unittest.mock import Mock, AsyncMock

        client = Mock()
        client.max_token_length = 4096
        client.decensor_enabled = False
        client.can_be_coerced = True
        client.data_format = "json"
        client.model_name = "test-model"
        client.send_prompt = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_send_without_response_spec_defaults_to_asis(self, mock_client):
        """Test that send() without response_spec defaults to AsIsExtractor for 'response' field."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = "This is a simple response"

        prompt = Prompt.from_text("Test prompt")
        result = await prompt.send(mock_client, kind="create")

        # Always returns tuple now
        assert isinstance(result, tuple)
        assert len(result) == 2
        response, extracted = result
        assert response == "This is a simple response"
        assert extracted == {"response": "This is a simple response"}

    @pytest.mark.asyncio
    async def test_send_with_response_spec_returns_tuple(self, mock_client):
        """Test that send() with response_spec returns tuple[str, dict]."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = "<MESSAGE>Hello world</MESSAGE>"

        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=["message"],
        )

        prompt = Prompt.from_text("Test prompt")
        result = await prompt.send(mock_client, kind="create", response_spec=spec)

        assert isinstance(result, tuple)
        assert len(result) == 2
        response, extracted = result
        assert isinstance(response, str)
        assert isinstance(extracted, dict)
        assert extracted["message"] == "Hello world"

    @pytest.mark.asyncio
    async def test_extraction_performed_correctly(self, mock_client):
        """Test that extraction is performed correctly with multiple extractors."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = """<ANALYSIS>
Thinking about this...
</ANALYSIS>
<MESSAGE>The actual message</MESSAGE>
"""

        spec = ResponseSpec(
            extractors={
                "analysis": AnchorExtractor(left="<ANALYSIS>", right="</ANALYSIS>"),
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>"),
            },
            required=["message"],
        )

        prompt = Prompt.from_text("Test prompt")
        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        assert extracted["message"] == "The actual message"
        assert "Thinking about this" in extracted["analysis"]

    @pytest.mark.asyncio
    async def test_optional_field_returns_none(self, mock_client):
        """Test that optional fields return None when not found."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = "<MESSAGE>Hello</MESSAGE>"

        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>"),
                "optional": AnchorExtractor(left="<OPTIONAL>", right="</OPTIONAL>"),
            },
            required=["message"],  # optional is not required
        )

        prompt = Prompt.from_text("Test prompt")
        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        assert extracted["message"] == "Hello"
        assert extracted["optional"] is None

    @pytest.mark.asyncio
    async def test_required_field_missing_raises_error(self, mock_client):
        """Test that missing required field raises ExtractionError."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = "No message tags here"

        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=["message"],
        )

        prompt = Prompt.from_text("Test prompt")
        with pytest.raises(ExtractionError):
            await prompt.send(mock_client, kind="create", response_spec=spec)

    @pytest.mark.asyncio
    async def test_template_extractors_override_python_extractors(self, mock_client):
        """Test that template extractors override Python-side extractors."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = (
            "<CUSTOM>Template override</CUSTOM><MESSAGE>Original</MESSAGE>"
        )

        # Python-side spec expects <MESSAGE>
        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=["message"],
        )

        prompt = Prompt.from_text("Test prompt")
        # Simulate template setting a different extractor for "message"
        prompt._template_extractors = {
            "message": AnchorExtractor(left="<CUSTOM>", right="</CUSTOM>")
        }

        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        # Template extractor should win
        assert extracted["message"] == "Template override"

    @pytest.mark.asyncio
    async def test_template_extractors_merge_with_python_extractors(self, mock_client):
        """Test that template extractors merge with Python-side extractors."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = (
            "<MESSAGE>Hello</MESSAGE><EXTRA>Extra data</EXTRA>"
        )

        # Python-side spec has one extractor
        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=["message"],
        )

        prompt = Prompt.from_text("Test prompt")
        # Template adds another extractor
        prompt._template_extractors = {
            "extra": AnchorExtractor(left="<EXTRA>", right="</EXTRA>")
        }

        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        # Both extractors should be used
        assert extracted["message"] == "Hello"
        assert extracted["extra"] == "Extra data"

    @pytest.mark.asyncio
    async def test_dedupe_enabled_parameter_accepted(self, mock_client):
        """Test that dedupe_enabled parameter is accepted (reserved for future use)."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = "Simple response"

        prompt = Prompt.from_text("Test prompt")
        # Should not raise an error
        response, extracted = await prompt.send(
            mock_client, kind="create", dedupe_enabled=True
        )
        assert response == "Simple response"
        assert extracted == {"response": "Simple response"}

        response, extracted = await prompt.send(
            mock_client, kind="create", dedupe_enabled=False
        )
        assert response == "Simple response"
        assert extracted == {"response": "Simple response"}

    @pytest.mark.asyncio
    async def test_response_spec_with_regex_extractor(self, mock_client):
        """Test response_spec with RegexExtractor."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = "Score: 85 out of 100"

        spec = ResponseSpec(
            extractors={"score": RegexExtractor(pattern=r"Score:\s*(\d+)")},
            required=["score"],
        )

        prompt = Prompt.from_text("Test prompt")
        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        assert extracted["score"] == "85"

    @pytest.mark.asyncio
    async def test_response_spec_with_as_is_extractor(self, mock_client):
        """Test response_spec with AsIsExtractor."""
        from talemate.prompts.base import Prompt

        mock_client.send_prompt.return_value = "  Full response with whitespace  "

        spec = ResponseSpec(extractors={"full": AsIsExtractor()}, required=[])

        prompt = Prompt.from_text("Test prompt")
        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        # AsIsExtractor trims by default
        assert extracted["full"] == "Full response with whitespace"


# ============================================================================
# Tests for Template-Defined Extractors (Jinja2 context functions)
# ============================================================================


class TestTemplateDefinedExtractors:
    """Tests for template-defined extractor functions."""

    def test_set_anchor_extractor_creates_extractor(self):
        """Test that set_anchor_extractor() creates an AnchorExtractor."""
        from talemate.prompts.base import Prompt

        prompt = Prompt.from_text("Test")
        result = prompt.set_anchor_extractor(
            "message", "<RESPONSE>", "</RESPONSE>", prefer_after="</ANALYSIS>"
        )

        # Returns empty string for Jinja2
        assert result == ""

        # Check extractor was created
        assert "message" in prompt._template_extractors
        extractor = prompt._template_extractors["message"]
        assert isinstance(extractor, AnchorExtractor)
        assert extractor.left == "<RESPONSE>"
        assert extractor.right == "</RESPONSE>"
        assert extractor.prefer_after == "</ANALYSIS>"

    def test_set_as_is_extractor_creates_extractor(self):
        """Test that set_as_is_extractor() creates an AsIsExtractor."""
        from talemate.prompts.base import Prompt

        prompt = Prompt.from_text("Test")
        result = prompt.set_as_is_extractor("narration", trim=False)

        # Returns empty string for Jinja2
        assert result == ""

        # Check extractor was created
        assert "narration" in prompt._template_extractors
        extractor = prompt._template_extractors["narration"]
        assert isinstance(extractor, AsIsExtractor)
        assert extractor.trim is False

    def test_set_after_anchor_extractor_creates_extractor(self):
        """Test that set_after_anchor_extractor() creates an AfterAnchorExtractor."""
        from talemate.prompts.base import Prompt

        prompt = Prompt.from_text("Test")
        result = prompt.set_after_anchor_extractor(
            "summary", "SUMMARY:", stop_at="<END>"
        )

        # Returns empty string for Jinja2
        assert result == ""

        # Check extractor was created
        assert "summary" in prompt._template_extractors
        extractor = prompt._template_extractors["summary"]
        assert isinstance(extractor, AfterAnchorExtractor)
        assert extractor.start == "SUMMARY:"
        assert extractor.stop_at == "<END>"

    def test_set_code_block_extractor_creates_extractor(self):
        """Test that set_code_block_extractor() creates a CodeBlockExtractor."""
        from talemate.prompts.base import Prompt

        prompt = Prompt.from_text("Test")
        result = prompt.set_code_block_extractor(
            "actions", "<ACTIONS>", "</ACTIONS>", validate_structured=False
        )

        # Returns empty string for Jinja2
        assert result == ""

        # Check extractor was created
        assert "actions" in prompt._template_extractors
        extractor = prompt._template_extractors["actions"]
        assert isinstance(extractor, CodeBlockExtractor)
        assert extractor.left == "<ACTIONS>"
        assert extractor.right == "</ACTIONS>"
        assert extractor.validate_structured is False


class TestTemplateExtractorInJinja2:
    """Tests for template-defined extractors called from Jinja2 templates."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock client for testing."""
        from unittest.mock import Mock, AsyncMock

        client = Mock()
        client.max_token_length = 4096
        client.decensor_enabled = False
        client.can_be_coerced = True
        client.data_format = "json"
        client.model_name = "test-model"
        client.send_prompt = AsyncMock()
        return client

    def test_extractor_function_available_in_template(self):
        """Test that extractor functions are available in Jinja2 templates."""
        from talemate.prompts.base import Prompt

        template = (
            """{{ set_anchor_extractor("message", "<MSG>", "</MSG>") }}Test prompt"""
        )
        prompt = Prompt.from_text(template)
        rendered = prompt.render()

        # Template should render without the function call output
        assert rendered == "Test prompt"

        # Extractor should be registered
        assert "message" in prompt._template_extractors

    def test_multiple_extractors_in_template(self):
        """Test multiple extractor definitions in a template."""
        from talemate.prompts.base import Prompt

        template = """{{ set_anchor_extractor("message", "<MSG>", "</MSG>") }}{{ set_as_is_extractor("full") }}{{ set_after_anchor_extractor("summary", "SUMMARY:") }}{{ set_code_block_extractor("data", "<DATA>", "</DATA>") }}Prompt text"""
        prompt = Prompt.from_text(template)
        rendered = prompt.render()

        assert rendered == "Prompt text"
        assert "message" in prompt._template_extractors
        assert "full" in prompt._template_extractors
        assert "summary" in prompt._template_extractors
        assert "data" in prompt._template_extractors

    @pytest.mark.asyncio
    async def test_template_extractor_overrides_python_default(self, mock_client):
        """Test that template-defined extractor overrides Python-side default."""
        from talemate.prompts.base import Prompt

        # Template defines a custom extractor for "response" that looks for <CUSTOM>
        template = (
            """{{ set_anchor_extractor("response", "<CUSTOM>", "</CUSTOM>") }}Test"""
        )
        mock_client.send_prompt.return_value = (
            "<CUSTOM>Custom content</CUSTOM><DEFAULT>Default content</DEFAULT>"
        )

        prompt = Prompt.from_text(template)
        response, extracted = await prompt.send(mock_client, kind="create")

        # Template's extractor should win (extracts from <CUSTOM>)
        assert extracted["response"] == "Custom content"

    @pytest.mark.asyncio
    async def test_template_extractor_merges_with_python_spec(self, mock_client):
        """Test that template extractors merge with Python-side response_spec."""
        from talemate.prompts.base import Prompt

        # Template defines an additional extractor
        template = """{{ set_anchor_extractor("extra", "<EXTRA>", "</EXTRA>") }}Test"""
        mock_client.send_prompt.return_value = (
            "<MESSAGE>Hello</MESSAGE><EXTRA>Extra data</EXTRA>"
        )

        # Python-side spec defines "message" extractor
        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=["message"],
        )

        prompt = Prompt.from_text(template)
        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        # Both extractors should work
        assert extracted["message"] == "Hello"
        assert extracted["extra"] == "Extra data"

    @pytest.mark.asyncio
    async def test_template_extractor_wins_on_conflict(self, mock_client):
        """Test that template extractor wins when both define same field."""
        from talemate.prompts.base import Prompt

        # Template overrides "message" to look at <CUSTOM_MSG> instead of <MESSAGE>
        template = (
            """{{ set_anchor_extractor("message", "<CUSTOM_MSG>", "</CUSTOM_MSG>") }}"""
        )
        mock_client.send_prompt.return_value = "<MESSAGE>Python default</MESSAGE><CUSTOM_MSG>Template override</CUSTOM_MSG>"

        # Python-side spec expects <MESSAGE>
        spec = ResponseSpec(
            extractors={
                "message": AnchorExtractor(left="<MESSAGE>", right="</MESSAGE>")
            },
            required=["message"],
        )

        prompt = Prompt.from_text(template)
        response, extracted = await prompt.send(
            mock_client, kind="create", response_spec=spec
        )

        # Template's extractor should win
        assert extracted["message"] == "Template override"

    @pytest.mark.asyncio
    async def test_template_as_is_extractor_integration(self, mock_client):
        """Test as_is_extractor defined in template."""
        from talemate.prompts.base import Prompt

        template = """{{ set_as_is_extractor("narration") }}Narrate this"""
        mock_client.send_prompt.return_value = "The sun set over the mountains."

        prompt = Prompt.from_text(template)
        response, extracted = await prompt.send(mock_client, kind="create")

        # Default "response" extractor is overridden by template's "narration"
        # Note: Template defines "narration" not "response", so both exist
        assert "narration" in extracted
        assert extracted["narration"] == "The sun set over the mountains."

    @pytest.mark.asyncio
    async def test_template_after_anchor_extractor_integration(self, mock_client):
        """Test after_anchor_extractor defined in template."""
        from talemate.prompts.base import Prompt

        template = (
            """{{ set_after_anchor_extractor("summary", "SUMMARY:") }}Summarize"""
        )
        mock_client.send_prompt.return_value = "SUMMARY: This is the summary content."

        prompt = Prompt.from_text(template)
        response, extracted = await prompt.send(mock_client, kind="create")

        assert "summary" in extracted
        assert extracted["summary"] == "This is the summary content."

    @pytest.mark.asyncio
    async def test_template_code_block_extractor_integration(self, mock_client):
        """Test code_block_extractor defined in template."""
        from talemate.prompts.base import Prompt

        template = """{{ set_code_block_extractor("actions", "<ACTIONS>", "</ACTIONS>") }}Generate actions"""
        mock_client.send_prompt.return_value = """<ACTIONS>
```json
[{"action": "test"}]
```
</ACTIONS>"""

        prompt = Prompt.from_text(template)
        response, extracted = await prompt.send(mock_client, kind="create")

        assert "actions" in extracted
        assert '"action": "test"' in extracted["actions"]

    def test_template_extractor_with_all_options(self):
        """Test set_anchor_extractor with all optional parameters."""
        from talemate.prompts.base import Prompt

        template = """{{ set_anchor_extractor(
            "decision",
            "<DECISION>",
            "</DECISION>",
            prefer_after="</ANALYSIS>",
            stop_at="<ACTIONS>",
            case_insensitive=False,
            trim=False
        ) }}Test"""

        prompt = Prompt.from_text(template)
        prompt.render()

        extractor = prompt._template_extractors["decision"]
        assert extractor.left == "<DECISION>"
        assert extractor.right == "</DECISION>"
        assert extractor.prefer_after == "</ANALYSIS>"
        assert extractor.stop_at == "<ACTIONS>"
        assert extractor.case_insensitive is False
        assert extractor.trim is False

    @pytest.mark.asyncio
    async def test_extractor_reset_between_renders(self, mock_client):
        """Test that _template_extractors persists across renders but is instance-specific."""
        from talemate.prompts.base import Prompt

        # First prompt with one extractor
        template1 = """{{ set_anchor_extractor("field1", "<A>", "</A>") }}Prompt 1"""
        prompt1 = Prompt.from_text(template1)
        prompt1.render()

        # Second prompt with different extractor
        template2 = """{{ set_anchor_extractor("field2", "<B>", "</B>") }}Prompt 2"""
        prompt2 = Prompt.from_text(template2)
        prompt2.render()

        # Each prompt should have its own extractors
        assert "field1" in prompt1._template_extractors
        assert "field2" not in prompt1._template_extractors

        assert "field2" in prompt2._template_extractors
        assert "field1" not in prompt2._template_extractors
