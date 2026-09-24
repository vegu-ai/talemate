"""
Unit tests for src/talemate/game/engine/nodes/string.py.

Standard pattern: instantiate node, pre-load inputs as properties via the
shared helper, run the node, assert outputs.
"""

import pytest

from talemate.game.engine.nodes.core import (
    InputValueError,
    UNRESOLVED,
)
from talemate.game.engine.nodes.string import (
    AdvancedFormat,
    AsString,
    Case,
    Condensed,
    Excerpt,
    Extract,
    Format,
    Jinja2Format,
    Join,
    MakeString,
    MakeText,
    Replace,
    Split,
    StringCheck,
    Substring,
    Trim,
    unescape_delimiter,
)

from _node_test_helpers import build_graph, make_constant, run_node


# ---------------------------------------------------------------------------
# AsString
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as_string_converts_int():
    out = await run_node(AsString(), inputs={"value": 42})
    assert out["value"] == "42"


@pytest.mark.asyncio
async def test_as_string_converts_dict():
    out = await run_node(AsString(), inputs={"value": {"a": 1}})
    assert out["value"] == str({"a": 1})


@pytest.mark.asyncio
async def test_as_string_unresolved_input_renders_as_none():
    """normalized_input_value coerces UNRESOLVED -> None."""
    node = AsString()
    node.properties["value"] = UNRESOLVED
    out = await run_node(node)
    # normalized -> None -> str(None) == "None"
    assert out["value"] == "None"


# ---------------------------------------------------------------------------
# MakeString / MakeText
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_string_outputs_property_value():
    out = await run_node(MakeString(), inputs={"value": "hello"})
    assert out["value"] == "hello"


@pytest.mark.asyncio
async def test_make_text_inherits_make_string_behavior():
    """MakeText is a UI subclass — it still emits the stored property."""
    out = await run_node(MakeText(), inputs={"value": "multi\nline"})
    assert out["value"] == "multi\nline"


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("delimiter", "expected"),
    [
        ("\\n", "\n"),
        ("\\t", "\t"),
        ("\\\\", "\\"),
        ("abc\\", "abc\\"),
        ("\\", "\\"),
        ("\\d", "\\d"),
        ("\\x41", "\\x41"),
        ("\\\\n", "\\n"),
        (", ", ", "),
    ],
)
def test_unescape_delimiter(delimiter, expected):
    assert unescape_delimiter(delimiter) == expected


@pytest.mark.asyncio
async def test_split_basic_with_default_delimiter():
    out = await run_node(Split(), inputs={"string": "a b c", "delimiter": " "})
    assert out["parts"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_split_max_splits_limits_count():
    """max_splits=1 produces at most 2 parts."""
    node = Split()
    node.set_property("max_splits", 1)
    out = await run_node(node, inputs={"string": "a b c d", "delimiter": " "})
    assert out["parts"] == ["a", "b c d"]


@pytest.mark.asyncio
async def test_split_treats_backslash_n_as_real_newline():
    """The literal '\\n' delimiter is translated to a real newline."""
    node = Split()
    node.set_property("max_splits", -1)
    out = await run_node(node, inputs={"string": "a\nb\nc", "delimiter": "\\n"})
    assert out["parts"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_split_treats_backslash_t_as_real_tab():
    out = await run_node(Split(), inputs={"string": "a\tb\tc", "delimiter": "\\t"})
    assert out["parts"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_split_connected_none_delimiter_splits_on_whitespace():
    producer = make_constant(string="a  b\nc", delimiter=None)
    split = Split()
    graph = build_graph(producer, split)
    graph.connect(
        producer.get_output_socket("string"), split.get_input_socket("string")
    )
    graph.connect(
        producer.get_output_socket("delimiter"), split.get_input_socket("delimiter")
    )

    async def assert_parts(state):
        assert split.get_output_socket("parts").value == ["a", "b", "c"]

    graph.callbacks.append(assert_parts)
    await graph.execute()


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_concatenates_with_delimiter():
    out = await run_node(Join(), inputs={"strings": ["a", "b", "c"], "delimiter": "-"})
    assert out["result"] == "a-b-c"


@pytest.mark.asyncio
async def test_join_translates_escaped_newline_delimiter():
    out = await run_node(Join(), inputs={"strings": ["x", "y"], "delimiter": "\\n"})
    assert out["result"] == "x\ny"


@pytest.mark.asyncio
async def test_join_rejects_non_string_items():
    with pytest.raises(InputValueError):
        await run_node(Join(), inputs={"strings": ["a", 1, "c"], "delimiter": ","})


# ---------------------------------------------------------------------------
# Replace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_default_count_replaces_all():
    out = await run_node(
        Replace(),
        inputs={"string": "aaa", "old": "a", "new": "b"},
    )
    assert out["result"] == "bbb"


@pytest.mark.asyncio
async def test_replace_count_limits_replacements():
    node = Replace()
    node.set_property("count", 2)
    out = await run_node(node, inputs={"string": "aaaa", "old": "a", "new": "b"})
    assert out["result"] == "bbaa"


@pytest.mark.asyncio
async def test_replace_handles_empty_string():
    """Empty string passes through unchanged."""
    out = await run_node(
        Replace(),
        inputs={"string": "", "old": "x", "new": "y"},
    )
    assert out["result"] == ""


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_substitutes_named_placeholders():
    out = await run_node(
        Format(),
        inputs={
            "template": "Hello, {name}! You are {age}.",
            "variables": {"name": "Alice", "age": 30},
        },
    )
    assert out["result"] == "Hello, Alice! You are 30."


@pytest.mark.asyncio
async def test_format_missing_key_raises_input_error():
    with pytest.raises(InputValueError):
        await run_node(
            Format(),
            inputs={"template": "Hi {name}!", "variables": {}},
        )


# ---------------------------------------------------------------------------
# AdvancedFormat (no dynamic sockets — base case)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advanced_format_uses_base_variables_dict():
    """With no dynamic sockets connected, AdvancedFormat == Format."""
    node = AdvancedFormat()
    out = await run_node(
        node,
        inputs={
            "template": "Hello, {name}!",
            "variables": {"name": "Bob"},
        },
    )
    assert out["result"] == "Hello, Bob!"


@pytest.mark.asyncio
async def test_advanced_format_missing_key_raises_input_error():
    node = AdvancedFormat()
    with pytest.raises(InputValueError):
        await run_node(
            node,
            inputs={"template": "Hi {name}!", "variables": {}},
        )


@pytest.mark.asyncio
async def test_advanced_format_with_dynamic_input_value_tuple():
    """A connected dynamic socket carrying a (key, value) tuple is unpacked
    into the variables dict."""
    node = AdvancedFormat()
    # Manually register a dynamic input as if the user added one through the UI
    node.dynamic_inputs = [{"name": "item1", "type": "any"}]
    node.setup()  # rebuild inputs to include the dynamic one
    # Connect a producer so the dynamic socket has a `source`. We use a
    # real Node with an output socket.
    from talemate.game.engine.nodes.core import Node, Graph

    class _ProducerNode(Node):
        def __init__(self, **kwargs):
            super().__init__(title="Producer", **kwargs)

        def setup(self):
            self.add_output("value")

        async def run(self, state):
            self.set_output_values({"value": ("name", "Carol")})

    producer = _ProducerNode()
    graph = Graph()
    graph.add_node(producer)
    graph.add_node(node)
    graph.connect(
        producer.get_output_socket("value"),
        node.get_input_socket("item1"),
    )

    node.set_property("template", "Hi {name}!")
    # variables intentionally empty to force lookup via dynamic input
    node.set_property("variables", {})

    async def assert_state(state):
        assert node.get_output_socket("result").value == "Hi Carol!"

    graph.callbacks.append(assert_state)
    await graph.execute()


# ---------------------------------------------------------------------------
# Jinja2Format (no scope)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jinja2_format_renders_simple_template():
    """A minimal jinja template with no agent scope must render variables."""
    node = Jinja2Format()
    out = await run_node(
        node,
        inputs={
            "template": "Hello {{ name }}!",
            "variables": {"name": "Eve"},
            "scope": "",
        },
    )
    assert out["result"] == "Hello Eve!"


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operation,inp,expected",
    [
        ("upper", "Hello World", "HELLO WORLD"),
        ("lower", "Hello World", "hello world"),
        ("title", "hello world", "Hello World"),
        ("capitalize", "hello world", "Hello world"),
    ],
)
@pytest.mark.asyncio
async def test_case_operations(operation, inp, expected):
    out = await run_node(Case(), inputs={"string": inp, "operation": operation})
    assert out["result"] == expected


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trim_both_strips_whitespace_by_default():
    out = await run_node(Trim(), inputs={"string": "  hello  "})
    assert out["result"] == "hello"


@pytest.mark.asyncio
async def test_trim_left_only():
    node = Trim()
    node.set_property("mode", "left")
    out = await run_node(node, inputs={"string": "  hello  "})
    assert out["result"] == "hello  "


@pytest.mark.asyncio
async def test_trim_right_only():
    node = Trim()
    node.set_property("mode", "right")
    out = await run_node(node, inputs={"string": "  hello  "})
    assert out["result"] == "  hello"


@pytest.mark.asyncio
async def test_trim_uses_explicit_chars():
    out = await run_node(Trim(), inputs={"string": "xxxhelloxxx", "chars": "x"})
    assert out["result"] == "hello"


@pytest.mark.asyncio
async def test_trim_translates_escaped_newline_in_chars():
    """If chars contains backslash-n, treat as real newline."""
    out = await run_node(
        Trim(),
        inputs={"string": "\nhello\n", "chars": "\\n"},
    )
    assert out["result"] == "hello"


# ---------------------------------------------------------------------------
# Substring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_substring_extracts_range():
    out = await run_node(Substring(), inputs={"string": "abcdef", "start": 1, "end": 4})
    assert out["result"] == "bcd"


@pytest.mark.asyncio
async def test_substring_default_end_uses_remainder():
    """When end is None (default property), use the rest of the string."""
    node = Substring()
    node.set_property("end", None)
    out = await run_node(node, inputs={"string": "abcdef", "start": 2})
    assert out["result"] == "cdef"


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_first_block_between_anchors():
    """For a clean block, return content between the anchors."""
    out = await run_node(
        Extract(),
        inputs={
            "string": "<TAG>value</TAG>",
            "left_anchor": "<TAG>",
            "right_anchor": "</TAG>",
            "trim": True,
        },
    )
    assert out["result"] == "value"


@pytest.mark.asyncio
async def test_extract_skips_segments_with_nested_left_anchor():
    """The first segment that lacks a closing anchor is skipped — we want
    the first *clean* block."""
    out = await run_node(
        Extract(),
        inputs={
            "string": "<TAG>nested<TAG>real</TAG>",
            "left_anchor": "<TAG>",
            "right_anchor": "</TAG>",
            "trim": True,
        },
    )
    assert out["result"] == "real"


@pytest.mark.asyncio
async def test_extract_falls_back_to_post_anchor_when_no_closing():
    """If no segment has the right anchor, return everything after the last
    left anchor."""
    out = await run_node(
        Extract(),
        inputs={
            "string": "<TAG>partial",
            "left_anchor": "<TAG>",
            "right_anchor": "</TAG>",
            "trim": True,
        },
    )
    assert out["result"] == "partial"


@pytest.mark.asyncio
async def test_extract_returns_empty_when_left_anchor_missing():
    out = await run_node(
        Extract(),
        inputs={
            "string": "no anchor here",
            "left_anchor": "<TAG>",
            "right_anchor": "</TAG>",
            "trim": True,
        },
    )
    assert out["result"] == ""


@pytest.mark.asyncio
async def test_extract_trim_false_preserves_whitespace():
    out = await run_node(
        Extract(),
        inputs={
            "string": "<TAG>  spaced  </TAG>",
            "left_anchor": "<TAG>",
            "right_anchor": "</TAG>",
            "trim": False,
        },
    )
    assert out["result"] == "  spaced  "


# ---------------------------------------------------------------------------
# StringCheck
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,string,substring,expected",
    [
        ("startswith", "Hello world", "Hello", True),
        ("startswith", "Hello world", "world", False),
        ("endswith", "Hello world", "world", True),
        ("endswith", "Hello world", "Hello", False),
        ("contains", "Hello world", "lo wo", True),
        ("contains", "Hello world", "abc", False),
        ("exact", "abc", "abc", True),
        ("exact", "abc", "abcd", False),
    ],
)
@pytest.mark.asyncio
async def test_string_check_operations(mode, string, substring, expected):
    out = await run_node(
        StringCheck(),
        inputs={"string": string, "substring": substring, "mode": mode},
    )
    assert out["result"] is expected


@pytest.mark.asyncio
async def test_string_check_case_insensitive():
    out = await run_node(
        StringCheck(),
        inputs={
            "string": "Hello",
            "substring": "HELLO",
            "mode": "exact",
            "case_sensitive": False,
        },
    )
    assert out["result"] is True


@pytest.mark.asyncio
async def test_string_check_empty_string_short_circuits_to_false():
    """An empty input string yields `False` regardless of mode."""
    out = await run_node(
        StringCheck(),
        inputs={"string": "", "substring": "", "mode": "exact"},
    )
    assert out["result"] is False


# ---------------------------------------------------------------------------
# Excerpt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_excerpt_truncates_and_appends_ellipsis():
    node = Excerpt()
    node.set_property("length", 5)
    node.set_property("add_ellipsis", True)
    out = await run_node(node, inputs={"string": "abcdefghij"})
    assert out["result"] == "abcde..."


@pytest.mark.asyncio
async def test_excerpt_short_input_returns_unchanged():
    node = Excerpt()
    node.set_property("length", 100)
    node.set_property("add_ellipsis", True)
    out = await run_node(node, inputs={"string": "short"})
    assert out["result"] == "short"


@pytest.mark.asyncio
async def test_excerpt_no_ellipsis_when_disabled():
    node = Excerpt()
    node.set_property("length", 3)
    node.set_property("add_ellipsis", False)
    out = await run_node(node, inputs={"string": "abcdef"})
    assert out["result"] == "abc"


# ---------------------------------------------------------------------------
# Condensed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condensed_collapses_extra_whitespace():
    """Condensed must collapse repeated whitespace and line breaks. The
    condensed util preserves words but reduces inter-word whitespace."""
    out = await run_node(Condensed(), inputs={"string": "hello   world\n\n\nfoo"})
    # condensed should produce a clean single-spaced single-line string
    assert "hello" in out["result"]
    assert "world" in out["result"]
    assert "foo" in out["result"]
    # No triple-newlines
    assert "\n\n\n" not in out["result"]
    # No triple-space runs either
    assert "   " not in out["result"]
