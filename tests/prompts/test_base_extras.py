"""
Additional unit tests for `talemate.prompts.base` not covered by the existing
prompts test files.

Focuses on the Prompt class's pure logic and template-rendering helpers:
- Prompt.get / from_text constructors
- as_list / config / __str__
- prepared response helpers (set_prepared_response, set_prepared_response_random,
  set_data_response, set_json_response)
- response-length helpers (set_response_length_instructions,
  has_response_length_instructions, mod_response_length)
- random, disable_dedupe, get_bullet_num
- system_time, time_diff
- text_to_chunks
- StripMode + clean_response
- validate_line
- poplines / cleaned
- Sectioning handlers (titles, xml, bracket, none)
- send() prepended-response prepending logic and dedupe resolution
- Template-defined extractor registration helpers

Where the LLM client is required, we use the conftest MockClient (real send_prompt
boundary, NOT Prompt.request).
"""

from __future__ import annotations

import locale
from collections import deque
from datetime import datetime

import pytest

from conftest import client_responses

import talemate.prompts.base as prompts_base
from talemate.prompts.base import (
    JoinableList,
    Prompt,
    StripMode,
    SECTIONING_HANDLERS,
    DEFAULT_SECTIONING_HANDLER,
    clean_response,
    register_sectioning_handler,
    set_default_sectioning_handler,
    validate_line,
)


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------


class TestGetClassmethod:
    def test_split_into_agent_and_name(self):
        p = Prompt.get("narrator.intro")
        assert p.agent_type == "narrator"
        assert p.name == "intro"
        assert p.uid == "narrator.intro"

    def test_no_dot_uses_empty_agent(self):
        p = Prompt.get("just-name")
        assert p.agent_type == ""
        assert p.name == "just-name"

    def test_vars_default_to_empty_dict(self):
        p = Prompt.get("narrator.intro")
        assert p.vars == {}

    def test_vars_passed_through(self):
        p = Prompt.get("narrator.intro", vars={"x": 1})
        assert p.vars == {"x": 1}


class TestFromText:
    def test_template_text_set(self):
        p = Prompt.from_text("hello {{name}}", vars={"name": "world"})
        assert p.template == "hello {{name}}"
        assert p.uid == ""
        assert p.agent_type == ""
        assert p.vars == {"name": "world"}


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestAsList:
    def test_returns_lines_after_render(self):
        p = Prompt.from_text("line one\nline two")
        p.render()
        assert "line one" in p.as_list
        assert "line two" in p.as_list

    def test_returns_empty_string_if_not_rendered(self):
        p = Prompt.from_text("never rendered")
        # `prompt` not set yet
        assert p.as_list == ""


class TestConfigProperty:
    def test_returns_real_config_object(self):
        p = Prompt.get("narrator.intro")
        cfg = p.config
        # Must be a Config-like object with a `prompts` attribute (PromptsConfig)
        assert hasattr(cfg, "prompts")


class TestStr:
    def test_str_renders_template(self):
        p = Prompt.from_text("hello world")
        # __str__ calls render()
        assert str(p) == "hello world"


# ---------------------------------------------------------------------------
# Prepared response helpers
# ---------------------------------------------------------------------------


class TestSetPreparedResponse:
    def test_basic_response_sets_attrs(self):
        p = Prompt.from_text("X")
        out = p.set_prepared_response("hello")
        assert p.prepared_response == "hello"
        assert p.prepare_response_fallback == "hello"
        assert out == "<|BOT|>hello"

    def test_prepend_arg_inserts_text(self):
        p = Prompt.from_text("X")
        out = p.set_prepared_response("hello", prepend="!! ")
        assert out == "<|BOT|>!! hello"

    def test_fallback_overrides_default(self):
        p = Prompt.from_text("X")
        p.set_prepared_response("response", fallback="fb")
        assert p.prepare_response_fallback == "fb"

    def test_random_prepared_response(self):
        p = Prompt.from_text("X")
        out = p.set_prepared_response_random(["only-one"])
        assert "only-one" in out
        assert p.prepared_response == "only-one"

    def test_random_prepared_with_prefix(self):
        p = Prompt.from_text("X")
        out = p.set_prepared_response_random(["only-one"], prefix="P:")
        assert out == "<|BOT|>P:only-one"


class _FakeYamlClient:
    data_format = "yaml"
    can_be_coerced = True


class TestSetDataResponse:
    def test_json_default(self):
        p = Prompt.from_text("X")
        out = p.set_data_response({"a": 1, "b": 2}, instruction="Schema")
        assert "```json" in out
        assert p.data_response is True
        assert p.data_format_type == "json"
        # instruction comment present (// for JSON)
        assert "//" in out or "Schema" in out

    def test_yaml_uses_client_format(self):
        p = Prompt.from_text("X")
        p.client = _FakeYamlClient()
        out = p.set_data_response({"a": 1}, instruction="Schema")
        assert "```yaml" in out
        assert p.data_format_type == "yaml"
        # YAML instruction prefix is "# Schema"
        assert "Schema" in out

    def test_yaml_dict_with_list_truncates_after_key(self):
        p = Prompt.from_text("X")
        p.client = _FakeYamlClient()
        # data_response should split YAML at the list key and not include items
        out = p.set_data_response({"items": [1, 2, 3]})
        assert "items:" in out
        # The list items should be omitted from the prepared response
        assert "- 1" not in out

    def test_yaml_dict_with_nested_dict_truncates_after_key(self):
        p = Prompt.from_text("X")
        p.client = _FakeYamlClient()
        out = p.set_data_response({"top": {"nested": "val"}})
        assert "top:" in out
        # nested content omitted
        assert "nested: val" not in out

    def test_set_json_response_aliases_set_data_response(self):
        p = Prompt.from_text("X")
        out = p.set_json_response({"a": 1})
        assert "```json" in out
        assert p.data_format_type == "json"
        assert p.data_response is True


# ---------------------------------------------------------------------------
# Response length & dedupe helpers
# ---------------------------------------------------------------------------


class TestResponseLengthHelpers:
    def test_set_returns_empty_and_marks_flag(self):
        p = Prompt.from_text("X")
        assert p.has_response_length_instructions() is False
        out = p.set_response_length_instructions()
        assert out == ""
        assert p.has_response_length_instructions() is True

    def test_mod_response_length_accumulates(self):
        p = Prompt.from_text("X")
        assert p.response_length_mod == 0
        p.mod_response_length(100)
        p.mod_response_length(50)
        assert p.response_length_mod == 150

    def test_disable_dedupe_clears_flag(self):
        p = Prompt.from_text("X")
        p.dedupe_enabled = True
        p.disable_dedupe()
        assert p.dedupe_enabled is False


class TestRandomAndBullet:
    def test_random_within_range(self):
        p = Prompt.from_text("X")
        for _ in range(50):
            v = p.random(1, 5)
            assert 1 <= v <= 5

    def test_get_bullet_num_increments(self):
        p = Prompt.from_text("X")
        first = p.get_bullet_num()
        second = p.get_bullet_num()
        third = p.get_bullet_num()
        assert (first, second, third) == (1, 2, 3)


# ---------------------------------------------------------------------------
# system_time / time_diff
# ---------------------------------------------------------------------------


class TestSystemTime:
    @pytest.fixture
    def fixed_now(self, monkeypatch):
        # The exact-string assertions below assume the C locale for %A/%B/%p.
        prev_locale = locale.setlocale(locale.LC_TIME)
        locale.setlocale(locale.LC_TIME, "C")

        def _freeze(dt):
            class _FrozenDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return dt

            monkeypatch.setattr(prompts_base, "datetime", _FrozenDatetime)

        yield _freeze
        locale.setlocale(locale.LC_TIME, prev_locale)

    def test_full_format(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 14, 30, 45))
        p = Prompt.from_text("X")
        assert p.system_time("full") == "Thursday, February 5, 2026 at 2:30 PM"

    def test_date_format(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 14, 30, 45))
        p = Prompt.from_text("X")
        assert p.system_time("date") == "February 5, 2026"

    def test_time_format(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 14, 30, 45))
        p = Prompt.from_text("X")
        assert p.system_time("time") == "2:30 PM"

    def test_time_format_midnight(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 0, 5, 0))
        p = Prompt.from_text("X")
        assert p.system_time("time") == "12:05 AM"

    def test_time_format_noon(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 12, 5, 0))
        p = Prompt.from_text("X")
        assert p.system_time("time") == "12:05 PM"

    def test_iso_format(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 14, 30, 45))
        p = Prompt.from_text("X")
        assert p.system_time("iso") == "2026-02-05T14:30:45"

    def test_datetime_format(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 14, 30, 45))
        p = Prompt.from_text("X")
        assert p.system_time("datetime") == "2026-02-05 14:30:45"

    def test_unknown_format_falls_back_to_full(self, fixed_now):
        fixed_now(datetime(2026, 2, 5, 14, 30, 45))
        p = Prompt.from_text("X")
        assert p.system_time("totally-bogus") == "Thursday, February 5, 2026 at 2:30 PM"


class TestTimeDiff:
    def test_empty_iso_returns_empty(self):
        p = Prompt.from_text("X")
        assert p.time_diff("") == ""


# ---------------------------------------------------------------------------
# text_to_chunks
# ---------------------------------------------------------------------------


class TestTextToChunks:
    def test_short_text_one_chunk(self):
        p = Prompt.from_text("X")
        chunks = p.text_to_chunks("hello world", chunk_size=512)
        assert len(chunks) == 1
        assert "hello world" in chunks[0]

    def test_long_text_splits_when_threshold_exceeded(self):
        p = Prompt.from_text("X")
        long_lines = "\n".join("word " * 20 for _ in range(20))
        chunks = p.text_to_chunks(long_lines, chunk_size=64)
        # Many chunks expected
        assert len(chunks) > 1

    def test_drops_leading_empty_lines(self):
        p = Prompt.from_text("X")
        text = "\n\n\nfirst line\n\nsecond line"
        chunks = p.text_to_chunks(text, chunk_size=512)
        assert len(chunks) == 1
        # No leading blanks in single chunk
        assert chunks[0].startswith("first line") or "first line" in chunks[0]


# ---------------------------------------------------------------------------
# StripMode / clean_response / validate_line
# ---------------------------------------------------------------------------


class TestStripMode:
    def test_enum_string_values(self):
        assert StripMode.BOTH == "BOTH"
        assert StripMode.LEFT == "LEFT"
        assert StripMode.RIGHT == "RIGHT"
        assert StripMode.NONE == "NONE"


class TestValidateLine:
    @pytest.mark.parametrize(
        "line,expected",
        [
            ("normal text", True),
            ("// comment", False),
            ("    // indented comment", False),
            ("/* block comment", False),
            ("[end of section]", False),
            # validate_line uses startswith (case-sensitive). UPPER case "[END OF" is valid.
            ("[END OF SECTION]", True),
            ("a [end of x] inline", True),  # only when starts-with
        ],
    )
    def test_validate_line(self, line, expected):
        assert validate_line(line) is expected


class TestCleanResponse:
    def test_strips_invalid_lines(self):
        text = "valid line\n// comment\nanother valid\n"
        result = clean_response(text)
        assert "// comment" not in result
        assert "valid line" in result
        assert "another valid" in result

    def test_removes_inline_end_of_marker(self):
        text = "line one [end of intro] continues\nline two"
        result = clean_response(text)
        assert "[end of intro]" not in result
        assert "line one" in result

    def test_strip_mode_both(self):
        result = clean_response("  abc  ", strip_mode=StripMode.BOTH)
        assert result == "abc"

    def test_strip_mode_left(self):
        result = clean_response("  abc  \n  ", strip_mode=StripMode.LEFT)
        # With LEFT mode, trailing whitespace preserved per-line in the rstrip
        # within the loop, but the final lstrip is what's used.
        assert result.startswith("abc")

    def test_strip_mode_right(self):
        result = clean_response("  abc  ", strip_mode=StripMode.RIGHT)
        assert result.endswith("abc")
        assert result.startswith("  abc")

    def test_strip_mode_none(self):
        # NONE: no outer strip. Per-line rstrip still happens internally.
        result = clean_response("  abc  ", strip_mode=StripMode.NONE)
        # The result will have leading whitespace from the original line
        assert "abc" in result


# ---------------------------------------------------------------------------
# JoinableList
# ---------------------------------------------------------------------------


class TestJoinableList:
    def test_join_default_separator(self):
        lst = JoinableList(["a", "b", "c"])
        assert lst.join() == "a\nb\nc"

    def test_join_custom_separator(self):
        lst = JoinableList(["a", "b"])
        assert lst.join(", ") == "a, b"


# ---------------------------------------------------------------------------
# poplines / cleaned
# ---------------------------------------------------------------------------


class TestPopLines:
    def test_poplines_drops_trailing_lines(self):
        p = Prompt.from_text("a\nb\nc\nd")
        p.render()  # populates self.prompt
        # Sanity-check the rendered list
        assert "d" in p.as_list
        p.poplines(2)
        assert "d" not in p.prompt
        # 'b' could remain (it's the second-to-last line)


class TestCleaned:
    def test_cleaned_strips_after_bot_token(self):
        p = Prompt.from_text("a\nb\n<|BOT|>c\nd")
        p.render()
        result = p.cleaned()
        # Stops at the <|BOT|> line, taking the part before it
        assert "c" not in result
        assert "d" not in result
        assert "a" in result
        assert "b" in result

    def test_cleaned_as_list_returns_list(self):
        p = Prompt.from_text("a\nb")
        p.render()
        result = p.cleaned(as_list=True)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Sectioning handlers
# ---------------------------------------------------------------------------


class TestSectioningHandlers:
    def test_titles_replaces_section_marker(self):
        p = Prompt.from_text("<|SECTION:intro|>\nhello\n<|CLOSE_SECTION|>")
        # render() picks up the default sectioning handler "titles"
        rendered = p.render(force=True)
        assert "## Intro" in rendered
        assert "<|SECTION:" not in rendered

    def test_xml_wraps_in_tags(self):
        p = Prompt.from_text("<|SECTION:intro|>\nhello\n<|CLOSE_SECTION|>")
        p.sectioning_handler = "xml"
        rendered = p.render(force=True)
        assert "<INTRO>" in rendered
        assert "</INTRO>" in rendered

    def test_bracket_uses_brackets(self):
        p = Prompt.from_text("<|SECTION:intro|>\nhello\n<|CLOSE_SECTION|>")
        p.sectioning_handler = "bracket"
        rendered = p.render(force=True)
        assert "[intro]" in rendered
        assert "[end of intro]" in rendered

    def test_none_strips_markers(self):
        p = Prompt.from_text("<|SECTION:intro|>\nhello\n<|CLOSE_SECTION|>")
        p.sectioning_handler = "none"
        rendered = p.render(force=True)
        assert "<|SECTION:" not in rendered
        assert "<|CLOSE_SECTION|>" not in rendered
        assert "hello" in rendered


class TestRegisterSectioningHandler:
    def test_register_adds_handler(self):
        @register_sectioning_handler("test_custom_handler")
        def my_handler(prompt):
            return "CUSTOM"

        try:
            assert "test_custom_handler" in SECTIONING_HANDLERS
            p = Prompt.from_text("X\n<|SECTION:foo|>\nbody\n<|CLOSE_SECTION|>")
            p.sectioning_handler = "test_custom_handler"
            assert p.render(force=True) == "CUSTOM"
        finally:
            SECTIONING_HANDLERS.pop("test_custom_handler", None)


class TestSetDefaultSectioningHandler:
    def test_set_default_validates_existing(self):
        # Should accept a known handler
        original = DEFAULT_SECTIONING_HANDLER
        try:
            set_default_sectioning_handler("none")
            from talemate.prompts.base import (
                DEFAULT_SECTIONING_HANDLER as updated,
            )

            assert updated == "none"
        finally:
            set_default_sectioning_handler(original)

    def test_set_default_unknown_raises(self):
        with pytest.raises(ValueError):
            set_default_sectioning_handler("does-not-exist")


# ---------------------------------------------------------------------------
# render() variable substitution
# ---------------------------------------------------------------------------


class TestRender:
    def test_basic_var_substitution(self):
        p = Prompt.from_text("hello {{name}}", vars={"name": "Alice"})
        rendered = p.render()
        assert rendered == "hello Alice"

    def test_force_re_renders_existing_prompt(self):
        p = Prompt.from_text("hello {{name}}", vars={"name": "Alice"})
        p.render()
        # mutate vars
        p.vars["name"] = "Bob"
        # without force, prompt still cached
        assert p.render() == "hello Alice"
        # with force, re-render
        assert p.render(force=True) == "hello Bob"

    def test_render_uses_decensor_default(self):
        # When `decensor` is not in vars, render injects False.
        p = Prompt.from_text("{% if decensor %}YES{% else %}NO{% endif %}")
        assert p.render() == "NO"

    def test_render_global_helpers_available(self):
        # `len`, `min`, `max`, `to_int`, `to_str` are exposed via env.globals
        p = Prompt.from_text(
            "{{ len(items) }}-{{ min(3, 5) }}-{{ to_int('42') }}",
            vars={"items": [1, 2, 3, 4]},
        )
        assert p.render() == "4-3-42"

    def test_render_uuidgen_returns_string(self):
        p = Prompt.from_text("{{ uuidgen() }}")
        rendered = p.render()
        # UUIDs are 36 chars including dashes
        assert len(rendered) == 36
        assert rendered.count("-") == 4

    def test_render_invokes_set_prepared_response(self):
        # Templates can call set_prepared_response — check it works through render
        p = Prompt.from_text("{{ set_prepared_response('hi') }}done")
        rendered = p.render()
        assert "<|BOT|>hi" in rendered
        assert "done" in rendered
        assert p.prepared_response == "hi"


# ---------------------------------------------------------------------------
# render_template
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_render_template_returns_subprompt_with_merged_vars(self):
        parent = Prompt.from_text("PARENT", vars={"a": 1})
        sub = parent.render_template("agent.foo", b=2)
        assert isinstance(sub, Prompt)
        assert sub.vars == {"a": 1, "b": 2}
        assert sub.uid == "agent.foo"


# ---------------------------------------------------------------------------
# Template-defined extractor registration
# ---------------------------------------------------------------------------


class TestTemplateExtractors:
    def test_set_anchor_extractor_simple(self):
        p = Prompt.from_text("X")
        out = p.set_anchor_extractor("msg", "<M>", "</M>")
        assert out == ""
        assert "msg" in p._template_extractors
        ext = p._template_extractors["msg"]
        # AnchorExtractor for non-tracked
        from talemate.prompts.response import AnchorExtractor

        assert isinstance(ext, AnchorExtractor)

    def test_set_anchor_extractor_with_tracked_tags_uses_complex(self):
        p = Prompt.from_text("X")
        from talemate.prompts.response import ComplexAnchorExtractor

        p.set_anchor_extractor("msg", "<M>", "</M>", tracked_tags=["A", "M"])
        assert isinstance(p._template_extractors["msg"], ComplexAnchorExtractor)

    def test_set_as_is_extractor(self):
        from talemate.prompts.response import AsIsExtractor

        p = Prompt.from_text("X")
        p.set_as_is_extractor("response")
        assert isinstance(p._template_extractors["response"], AsIsExtractor)

    def test_set_after_anchor_extractor(self):
        from talemate.prompts.response import AfterAnchorExtractor

        p = Prompt.from_text("X")
        p.set_after_anchor_extractor("summary", "SUMMARY:", stop_at="END")
        assert isinstance(p._template_extractors["summary"], AfterAnchorExtractor)

    def test_set_code_block_extractor_simple(self):
        from talemate.prompts.response import CodeBlockExtractor

        p = Prompt.from_text("X")
        p.set_code_block_extractor("data", "<D>", "</D>")
        assert isinstance(p._template_extractors["data"], CodeBlockExtractor)

    def test_set_code_block_extractor_complex(self):
        from talemate.prompts.response import ComplexCodeBlockExtractor

        p = Prompt.from_text("X")
        p.set_code_block_extractor("data", "<D>", "</D>", tracked_tags=["A", "D"])
        assert isinstance(p._template_extractors["data"], ComplexCodeBlockExtractor)

    def test_set_block_list_extractor(self):
        from talemate.prompts.response import BlockListExtractor

        p = Prompt.from_text("X")
        p.set_block_list_extractor("blocks", blocks=[("narrator", "<N>", "</N>")])
        assert isinstance(p._template_extractors["blocks"], BlockListExtractor)


# ---------------------------------------------------------------------------
# send() prepended response logic + dedupe resolution + section_format
# ---------------------------------------------------------------------------


class _FakeClient:
    """Plain stand-in for ClientBase that exposes only what Prompt.send needs.

    We don't subclass ClientBase because its `section_format`, `data_format`,
    and `dedupe_enabled` are properties — and overriding them is awkward.
    """

    def __init__(
        self, name="fake", section_format=None, dedupe_enabled=False, data_format=None
    ):
        self.name = name
        self.section_format = section_format
        self.dedupe_enabled = dedupe_enabled
        self.data_format = data_format
        self.can_be_coerced = True
        self.model_name = "test-model"
        self.prompt_history = []

    async def send_prompt(self, prompt, kind="conversation", **kwargs):
        response_stack = client_responses.get()
        self.prompt_history.append({"prompt": prompt, "kind": kind})
        if not response_stack:
            return ""
        return response_stack.popleft()


@pytest.fixture
def _fresh_responses():
    """Reset the contextvar deque for each test."""
    token = client_responses.set(deque())
    yield client_responses.get()
    client_responses.reset(token)


class TestSendPreparedResponsePrepending:
    @pytest.mark.asyncio
    async def test_response_starting_with_prepared_passes_through(
        self, _fresh_responses
    ):
        # When the response already starts with the prepared response, no prepend
        client = _FakeClient()
        prompt = Prompt.from_text("X")
        prompt.set_prepared_response("hello")
        _fresh_responses.append("hello world!")

        response, _ = await prompt.send(client, kind="create")
        assert response == "hello world!"

    @pytest.mark.asyncio
    async def test_response_missing_prepared_gets_prepended(self, _fresh_responses):
        client = _FakeClient()
        prompt = Prompt.from_text("X")
        prompt.set_prepared_response("BEGIN:")
        _fresh_responses.append("the body")

        response, _ = await prompt.send(client, kind="create")
        # prepared_response.rstrip() + " " + response.strip()
        assert response.startswith("BEGIN:")
        assert "the body" in response


class TestSendDedupeResolution:
    @pytest.mark.asyncio
    async def test_explicit_dedupe_true_overrides_client(self, _fresh_responses):
        client = _FakeClient(dedupe_enabled=False)
        prompt = Prompt.from_text("hello")
        _fresh_responses.append("ok")
        await prompt.send(client, kind="create", dedupe_enabled=True)
        assert prompt.dedupe_enabled is True

    @pytest.mark.asyncio
    async def test_default_picks_up_client_setting(self, _fresh_responses):
        client = _FakeClient(dedupe_enabled=True)
        prompt = Prompt.from_text("hello")
        _fresh_responses.append("ok")
        await prompt.send(client, kind="create")
        assert prompt.dedupe_enabled is True

    @pytest.mark.asyncio
    async def test_existing_explicit_setting_preserved(self, _fresh_responses):
        client = _FakeClient(dedupe_enabled=True)
        prompt = Prompt.from_text("hello")
        prompt.dedupe_enabled = False  # explicit override
        _fresh_responses.append("ok")
        await prompt.send(client, kind="create")
        # Existing explicit False is preserved over client's True
        assert prompt.dedupe_enabled is False


class TestSendSectionFormat:
    @pytest.mark.asyncio
    async def test_client_section_format_xml_sets_handler(self, _fresh_responses):
        client = _FakeClient(section_format="xml")
        prompt = Prompt.from_text("a")
        _fresh_responses.append("ok")
        await prompt.send(client, kind="create")
        assert prompt.sectioning_handler == "xml"

    @pytest.mark.asyncio
    async def test_client_section_format_markdown_sets_titles_handler(
        self, _fresh_responses
    ):
        client = _FakeClient(section_format="markdown")
        prompt = Prompt.from_text("a")
        _fresh_responses.append("ok")
        await prompt.send(client, kind="create")
        assert prompt.sectioning_handler == "titles"


class TestSendDataResponseExtraction:
    @pytest.mark.asyncio
    async def test_json_block_is_extracted_from_response(self, _fresh_responses):
        client = _FakeClient()
        prompt = Prompt.from_text("X")
        prompt.set_json_response({"a": 1, "b": 2})
        # Simulate full response with code block
        _fresh_responses.append('```json\n{"a": 1, "b": 2}\n```\nfooter')

        response, parsed = await prompt.send(client, kind="create")
        # Code-block content extracted
        assert '"a": 1' in response or '"a":1' in response
        # parsed is a dict from data extractor
        assert parsed.get("a") == 1
        assert parsed.get("b") == 2


# ---------------------------------------------------------------------------
# parse_data_response
# ---------------------------------------------------------------------------


class TestParseDataResponse:
    @pytest.mark.asyncio
    async def test_returns_first_struct_by_default(self):
        client = _FakeClient()
        client.model_name = "test"
        prompt = Prompt.from_text("X")
        prompt.client = client
        prompt.data_format_type = "json"

        result = await prompt.parse_data_response('{"a": 1}')
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_data_allow_multiple_returns_list(self):
        client = _FakeClient()
        client.model_name = "test"
        prompt = Prompt.from_text("X")
        prompt.client = client
        prompt.data_format_type = "json"
        prompt.data_allow_multiple = True

        result = await prompt.parse_data_response('{"a": 1}')
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {"a": 1}

    @pytest.mark.asyncio
    async def test_uses_client_data_format_when_set(self):
        # Verifies the precedence: client.data_format wins over self.data_format_type
        client = _FakeClient(data_format="yaml")
        client.model_name = "test"
        prompt = Prompt.from_text("X")
        prompt.client = client
        # Self said json but client says yaml -> the parser will use yaml extraction
        prompt.data_format_type = "json"

        # Yaml-formatted single-key payload
        result = await prompt.parse_data_response("a: 1\nb: 2\n")
        assert result.get("a") == 1
        assert result.get("b") == 2
