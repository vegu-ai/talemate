import json
from talemate.util.prompt import (
    parse_response_section,
    extract_actions_block,
    clean_visible_response,
    auto_close_tags,
)


# Helper to parse extracted content (since extract_actions_block now returns raw string)
def parse_actions_content(content: str | None) -> list[dict] | None:
    """Parse the raw actions content string into a list of dicts."""
    if not content:
        return None
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return None

        normalized = []
        for item in data:
            if isinstance(item, list):
                for sub in item:
                    if isinstance(sub, dict):
                        name = sub.get("name") or sub.get("function")
                        instructions = sub.get("instructions") or ""
                        if name:
                            normalized.append(
                                {"name": str(name), "instructions": str(instructions)}
                            )
                continue
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("function")
            instructions = item.get("instructions") or ""
            if name:
                normalized.append(
                    {"name": str(name), "instructions": str(instructions)}
                )
        return normalized or None
    except json.JSONDecodeError:
        return None


# ============================================================================
# Tests for parse_response_section
# ============================================================================


class TestParseResponseSection:
    """Tests for the parse_response_section function."""

    def test_basic_message_with_analysis(self):
        """Test extracting a MESSAGE after ANALYSIS block."""
        response = """
<ANALYSIS>
This is some analysis text.
</ANALYSIS>
<MESSAGE>
This is the response message.
</MESSAGE>
"""
        result = parse_response_section(response)
        assert result == "This is the response message."

    def test_message_without_analysis(self):
        """Test extracting MESSAGE when no ANALYSIS block present."""
        response = """
<MESSAGE>
Simple message without analysis.
</MESSAGE>
"""
        result = parse_response_section(response)
        assert result == "Simple message without analysis."

    def test_actions_in_analysis_ignored(self):
        """Test that <ACTION> tags within ANALYSIS don't interfere."""
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
        result = parse_response_section(response)
        assert result == "This is the actual message."

    def test_nested_message_like_text_in_analysis(self):
        """Test MESSAGE-like text in ANALYSIS doesn't confuse parser."""
        response = """
<ANALYSIS>
The user might want to see <MESSAGE>this</MESSAGE> but that's just analysis.
We could also say "<MESSAGE>something else</MESSAGE>" in quotes.
</ANALYSIS>
<MESSAGE>
Real message here.
</MESSAGE>
"""
        result = parse_response_section(response)
        assert result == "Real message here."

    def test_decision_tag_in_analysis_ignored(self):
        """Test that <DECISION> tags within ANALYSIS don't interfere with MESSAGE parsing."""
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
        result = parse_response_section(response)
        assert result == "This is the actual message."

    def test_decision_block_in_message_extracted(self):
        """Test that DECISION blocks within MESSAGE are extracted (but will be stripped later)."""
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
        result = parse_response_section(response)
        assert "Here is my response" in result
        assert "<DECISION>" in result
        # Note: The actual stripping happens in chat_clean_visible_response
        # This test just verifies the MESSAGE is extracted with DECISION intact


# ============================================================================
# Tests for extract_actions_block
# ============================================================================


class TestExtractActionsBlock:
    """Tests for the extract_actions_block function."""

    def test_basic_actions_json(self):
        """Test extracting basic ACTIONS block with JSON."""
        response = """
<ACTIONS>
```json
[
    {"name": "test_action", "instructions": "Do something"}
]
```
</ACTIONS>
"""
        content = extract_actions_block(response)
        assert content is not None
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "test_action"
        assert result[0]["instructions"] == "Do something"

    def test_actions_in_analysis_ignored(self):
        """Test that ACTIONS blocks within ANALYSIS are not extracted."""
        response = """
<ANALYSIS>
We could perform <ACTIONS>
```json
[{"name": "fake", "instructions": "This is just analysis"}]
```
</ACTIONS>
but that's just analysis.
</ANALYSIS>
<MESSAGE>
Here's the real response.
</MESSAGE>
<ACTIONS>
```json
[{"name": "real_action", "instructions": "This is the real action"}]
```
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "real_action"
        assert "real action" in result[0]["instructions"]

    def test_only_actions_in_analysis_returns_none(self):
        """
        Test that if ACTIONS only appears within ANALYSIS (and not after),
        we return None since those are not real actions.
        """
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
        result = extract_actions_block(response)
        assert result is None

    def test_actions_with_action_tag_in_analysis(self):
        """Test the edge case where <ACTION> tags appear in <ANALYSIS> before <ACTIONS>."""
        response = """
<ANALYSIS>
Looking at the scene, I notice several things:
- The character could <ACTION>move</ACTION> to the door
- Or they could <ACTION>speak</ACTION> to the other character
- Maybe even <ACTION>hide</ACTION> behind something
Based on this analysis, I recommend we proceed.
</ANALYSIS>
<MESSAGE>
I think the best course of action is to have them move cautiously.
</MESSAGE>
<ACTIONS>
```json
[
    {"name": "move", "instructions": "Move slowly toward the door"}
]
```
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "move"
        assert "door" in result[0]["instructions"]

    def test_decision_in_analysis_ignored(self):
        """Test that DECISION blocks within ANALYSIS are ignored when extracting ACTIONS."""
        response = """
<ANALYSIS>
I need to decide on the approach <DECISION>cautious_approach</DECISION>.
Also considering <DECISION>aggressive_approach</DECISION> as alternative.
</ANALYSIS>
<MESSAGE>
Based on my analysis, here's the plan.
</MESSAGE>
<ACTIONS>
```json
[{"name": "proceed", "instructions": "Move forward"}]
```
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "proceed"

    def test_actions_and_decision_in_message(self):
        """Test that both ACTIONS and DECISION can appear in MESSAGE after ANALYSIS."""
        response = """
<ANALYSIS>
Analyzing the scene with potential <DECISION>test</DECISION> and <ACTIONS>```json
[{"name": "fake", "instructions": "fake"}]
```</ACTIONS> blocks.
</ANALYSIS>
<MESSAGE>
My decision: <DECISION>proceed_with_caution</DECISION>
And here are the actions to take:
<ACTIONS>
```json
[{"name": "real_action", "instructions": "Do this"}]
```
</ACTIONS>
</MESSAGE>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "real_action"

    def test_actions_without_code_fence(self):
        """Test extracting ACTIONS block without code fence wrapper."""
        response = """
<ACTIONS>
[
  {"name": "update_context", "instructions": "Create a character"},
  {"name": "start_roleplay", "instructions": ""}
]
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 2
        assert result[0]["name"] == "update_context"
        assert result[1]["name"] == "start_roleplay"

    def test_actions_without_code_fence_single_object(self):
        """Test extracting ACTIONS block without code fence, single object."""
        response = """
<ACTIONS>
{"name": "test_action", "instructions": "Do something"}
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "test_action"

    def test_actions_without_code_fence_after_analysis(self):
        """Test ACTIONS without code fence after ANALYSIS block."""
        response = """
<ANALYSIS>
Some analysis here.
</ANALYSIS>
<MESSAGE>
Response text.
</MESSAGE>
<ACTIONS>
[{"name": "real_action", "instructions": "Do this"}]
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "real_action"

    def test_actions_without_code_fence_realistic_example(self):
        """Test with the realistic example from user."""
        response = """
<ACTIONS>
[
  {
    "name": "update_context",
    "instructions": "Create a new player-controlled character named Veyla. Description: 'Veyla is a lean, mid-twenties rogue with travel-stained clothes and eyes that flicker between wariness and quiet hope. Her hands move like smoke – calloused from travel but never raised in violence. A satchel bulging with stolen trinkets hangs at her hip, and she carries the scent of rain and Qeynos cobbles. She's been on the road for months, with Freeport as her last desperate hope. She'll steal bread but won't break a neck.' Set as active in scene with no entry narration needed."
  },
  {
    "name": "start_roleplay",
    "instructions": ""
  }
]
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 2
        assert result[0]["name"] == "update_context"
        assert "Veyla" in result[0]["instructions"]
        assert result[1]["name"] == "start_roleplay"

    def test_actions_prefers_code_fence_over_no_fence(self):
        """Test that code-fenced content is preferred over non-fenced."""
        response = """
<ACTIONS>
```json
[{"name": "fenced_action", "instructions": "From fence"}]
```
</ACTIONS>
"""
        content = extract_actions_block(response)
        result = parse_actions_content(content)
        assert result is not None
        assert result[0]["name"] == "fenced_action"

    def test_actions_without_code_fence_ignores_non_json(self):
        """Test that non-JSON/YAML content without code fence is not extracted."""
        response = """
<ACTIONS>
This is just plain text, not JSON or YAML.
</ACTIONS>
"""
        content = extract_actions_block(response)
        # Should return None because content doesn't look like structured data
        assert content is None

    def test_actions_without_code_fence_yaml_list(self):
        """Test extracting ACTIONS block with YAML list format (no code fence)."""
        response = """
<ACTIONS>
- name: update_context
  instructions: Create a character named Veyla
- name: start_roleplay
  instructions: ""
</ACTIONS>
"""
        content = extract_actions_block(response)
        assert content is not None
        assert "- name: update_context" in content
        assert "- name: start_roleplay" in content

    def test_actions_without_code_fence_yaml_object(self):
        """Test extracting ACTIONS block with YAML object format (no code fence)."""
        response = """
<ACTIONS>
name: test_action
instructions: Do something important
</ACTIONS>
"""
        content = extract_actions_block(response)
        assert content is not None
        assert "name: test_action" in content
        assert "instructions: Do something important" in content

    def test_actions_with_yaml_code_fence(self):
        """Test extracting ACTIONS block with YAML code fence."""
        response = """
<ACTIONS>
```yaml
- name: yaml_action
  instructions: This is YAML
```
</ACTIONS>
"""
        content = extract_actions_block(response)
        assert content is not None
        assert "- name: yaml_action" in content


# ============================================================================
# Tests for clean_visible_response
# ============================================================================


class TestCleanVisibleResponse:
    """Tests for the clean_visible_response function."""

    def test_removes_actions_block(self):
        """Test that ACTIONS blocks are removed."""
        text = """Here is my response.
<ACTIONS>
```json
[{"name": "test"}]
```
</ACTIONS>
More text after."""
        result = clean_visible_response(text)
        assert result == "Here is my response.\n\nMore text after."

    def test_removes_decision_and_everything_after(self):
        """Test that everything from DECISION tag onwards is removed."""
        text = """Here is my response.
<DECISION>
Choose option A
</DECISION>
This text should be removed too."""
        result = clean_visible_response(text)
        assert result == "Here is my response."

    def test_removes_legacy_actions_block(self):
        """Test that legacy ```actions``` blocks are removed."""
        text = """Here is my response.
```actions
some action data
```
More text after."""
        result = clean_visible_response(text)
        assert result == "Here is my response.\n\nMore text after."

    def test_removes_actions_then_decision(self):
        """Test removing both ACTIONS and DECISION blocks."""
        text = """Here is my response.
<ACTIONS>
```json
[{"name": "test"}]
```
</ACTIONS>
<DECISION>Everything from here onwards is removed</DECISION>"""
        result = clean_visible_response(text)
        assert result == "Here is my response."

    def test_no_special_tags(self):
        """Test text without special tags is unchanged."""
        text = "Just a message with no decision or actions."
        result = clean_visible_response(text)
        assert result == "Just a message with no decision or actions."

    def test_case_insensitive(self):
        """Test that tag matching is case insensitive."""
        text = """My response.
<actions>
```json
[{"name": "test"}]
```
</actions>
<decision>removed</decision>"""
        result = clean_visible_response(text)
        assert result == "My response."

    def test_decision_without_closing_tag(self):
        """Test that DECISION without closing tag removes everything after."""
        text = """Here is my response.
<DECISION>
This is my decision and all this text
continues for many lines
and should all be removed."""
        result = clean_visible_response(text)
        assert result == "Here is my response."

    def test_multiple_actions_blocks(self):
        """Test that multiple ACTIONS blocks are all removed."""
        text = """Start.
<ACTIONS>
```json
[{"name": "first"}]
```
</ACTIONS>
Middle.
<ACTIONS>
```json
[{"name": "second"}]
```
</ACTIONS>
End."""
        result = clean_visible_response(text)
        assert "Start." in result
        assert "Middle." in result
        assert "End." in result
        assert "<ACTIONS>" not in result
        assert "first" not in result
        assert "second" not in result


# ============================================================================
# Tests for auto_close_tags
# ============================================================================


class TestAutoCloseTags:
    """Tests for the auto_close_tags function."""

    def test_unclosed_analysis_before_message(self):
        """Test that unclosed ANALYSIS is closed before MESSAGE."""
        text = "<ANALYSIS>Some analysis text<MESSAGE>Hello</MESSAGE>"
        result = auto_close_tags(text)
        assert "</ANALYSIS>" in result
        assert result.index("</ANALYSIS>") < result.index("<MESSAGE>")

    def test_unclosed_analysis_before_decision(self):
        """Test that unclosed ANALYSIS is closed before DECISION."""
        text = "<ANALYSIS>Some analysis<DECISION>Option A</DECISION>"
        result = auto_close_tags(text)
        assert "</ANALYSIS>" in result
        assert result.index("</ANALYSIS>") < result.index("<DECISION>")

    def test_unclosed_analysis_before_actions(self):
        """Test that unclosed ANALYSIS is closed before ACTIONS."""
        text = "<ANALYSIS>Some analysis<ACTIONS>```json\n[]\n```</ACTIONS>"
        result = auto_close_tags(text)
        assert "</ANALYSIS>" in result
        assert result.index("</ANALYSIS>") < result.index("<ACTIONS>")

    def test_unclosed_message_before_decision(self):
        """Test that unclosed MESSAGE is closed before DECISION."""
        text = "<MESSAGE>Hello<DECISION>Option A</DECISION>"
        result = auto_close_tags(text)
        assert "</MESSAGE>" in result
        assert result.index("</MESSAGE>") < result.index("<DECISION>")

    def test_unclosed_message_before_actions(self):
        """Test that unclosed MESSAGE is closed before ACTIONS."""
        text = "<MESSAGE>Hello<ACTIONS>```json\n[]\n```</ACTIONS>"
        result = auto_close_tags(text)
        assert "</MESSAGE>" in result
        assert result.index("</MESSAGE>") < result.index("<ACTIONS>")

    def test_multiple_unclosed_tags(self):
        """Test that multiple unclosed tags are all closed."""
        text = "<ANALYSIS>Analysis<MESSAGE>Hello<DECISION>Choice<ACTIONS>```json\n[]\n```</ACTIONS>"
        result = auto_close_tags(text)
        assert "</ANALYSIS>" in result
        assert "</MESSAGE>" in result
        assert "</DECISION>" in result
        # Verify order
        assert result.index("</ANALYSIS>") < result.index("<MESSAGE>")
        assert result.index("</MESSAGE>") < result.index("<DECISION>")
        assert result.index("</DECISION>") < result.index("<ACTIONS>")

    def test_properly_closed_tags_unchanged(self):
        """Test that properly closed tags are not modified."""
        text = "<ANALYSIS>Some analysis</ANALYSIS><MESSAGE>Hello</MESSAGE>"
        result = auto_close_tags(text)
        assert result == text

    def test_case_insensitive_tags(self):
        """Test that tag matching is case insensitive."""
        text = "<analysis>Some analysis<message>Hello</message>"
        result = auto_close_tags(text)
        assert "</ANALYSIS>" in result
        assert result.lower().index("</analysis>") < result.lower().index("<message>")

    def test_empty_string(self):
        """Test that empty string returns empty string."""
        assert auto_close_tags("") == ""

    def test_no_tags(self):
        """Test that text without tags is unchanged."""
        text = "Just plain text without any tags."
        assert auto_close_tags(text) == text

    def test_single_unclosed_tag_no_next_tag(self):
        """Test that single unclosed tag without following tag is unchanged."""
        text = "<ANALYSIS>Some analysis that never closes"
        result = auto_close_tags(text)
        # No closing tag should be added because there's no next opening tag
        assert "</ANALYSIS>" not in result

    def test_realistic_llm_response(self):
        """Test with a realistic LLM response format from the user's example."""
        text = """<ANALYSIS>
1. Current scene state: We're in startup mode.
2. Story need: The narrative must immediately establish Veyla.

<MESSAGE>
Character created and setup complete. Transitioning to roleplay phase.

<DECISION>
Taking three actions: create character, update game state, start roleplay.

<ACTIONS>
[
  {"name": "update_context", "instructions": "Create persistent character"}
]
</ACTIONS>"""
        result = auto_close_tags(text)
        # ANALYSIS should be closed before MESSAGE
        assert "</ANALYSIS>" in result
        assert result.index("</ANALYSIS>") < result.index("<MESSAGE>")
        # MESSAGE should be closed before DECISION
        assert "</MESSAGE>" in result
        assert result.index("</MESSAGE>") < result.index("<DECISION>")
        # DECISION should be closed before ACTIONS
        assert "</DECISION>" in result
        assert result.index("</DECISION>") < result.index("<ACTIONS>")

    def test_parse_response_with_auto_close(self):
        """Test that auto_close_tags enables parse_response_section to work correctly."""
        # Without auto_close_tags, the MESSAGE wouldn't be properly extracted
        text = """<ANALYSIS>
Some analysis here.

<MESSAGE>
This is the actual message.
</MESSAGE>"""
        fixed_text = auto_close_tags(text)
        result = parse_response_section(fixed_text)
        assert result == "This is the actual message."

    def test_extract_actions_with_auto_close(self):
        """Test that auto_close_tags enables extract_actions_block to work correctly."""
        text = """<ANALYSIS>
Some analysis here.

<ACTIONS>
```json
[{"name": "test_action", "instructions": "Do something"}]
```
</ACTIONS>"""
        fixed_text = auto_close_tags(text)
        content = extract_actions_block(fixed_text)
        result = parse_actions_content(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "test_action"

    def test_preserves_content_between_tags(self):
        """Test that content between tags is preserved correctly."""
        text = "<ANALYSIS>Line1\nLine2\nLine3<MESSAGE>Response text</MESSAGE>"
        result = auto_close_tags(text)
        assert "Line1\nLine2\nLine3" in result
        assert "Response text" in result
