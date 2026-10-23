"""
Tests for talemate.prompts.compatibility: markers read from the shipped default
and checked against an override.
"""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from structlog.testing import capture_logs

from talemate.prompts import contracts, groups
from talemate.prompts.base import prepended_template_dirs
from talemate.prompts.compatibility import (
    check_override,
    log_override_status,
    override_status,
    response_anchors,
)
from talemate.prompts.groups import (
    MissingMarker,
    TemplateInfo,
    get_default_template_path,
)

DATA_DIR = Path(__file__).parent.parent / "data" / "prompt_compatibility"
SHIPPED_DIR = Path(groups.__file__).parent / "templates"


def _write(path: Path, content: str, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def partials_dir(tmp_path):
    """A template directory searched first when partials are resolved."""
    directory = tmp_path / "partials"
    directory.mkdir()
    token = prepended_template_dirs.set([str(directory)])
    yield directory
    prepended_template_dirs.reset(token)


@pytest.fixture
def pair(tmp_path):
    def _pair(default: str, override: str) -> tuple[Path, Path]:
        return (
            _write(tmp_path / "default.jinja2", default),
            _write(tmp_path / "override.jinja2", override),
        )

    return _pair


def _markers(report) -> set[tuple[str, str]]:
    return {(marker.kind, marker.name) for marker in report.missing_markers}


def test_identical_override_is_compatible(pair):
    default, override = pair(
        '{% include "x.jinja2" %}{% if flag %}<ANSWER>{% endif %}',
        '{% include "x.jinja2" %}{% if flag %}<ANSWER>{% endif %}',
    )
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "compatible"
    assert report.missing_markers == []


def test_missing_template_extractor_is_incompatible(pair):
    default, override = pair(
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write <OUT>.',
        "Write <OUT>.",
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "incompatible"
    assert _markers(report) == {("extractor", "response")}


def test_extractor_with_dynamic_key_is_not_a_marker(pair):
    default, override = pair(
        '{{ set_anchor_extractor("chunk_" ~ n, "<C>", "</C>") }}', "plain"
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_missing_response_anchor_is_incompatible(pair):
    default, override = pair(
        "Answer inside <ANSWER>...</ANSWER>.", "Answer with ANSWER: prefix."
    )
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "incompatible"
    assert _markers(report) == {("anchor", "<ANSWER>")}


def test_anchor_matching_ignores_case(pair):
    default, override = pair("Use <ANSWER>.", "use <answer>.")
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "compatible"


def test_anchor_only_in_default_comment_is_not_a_marker(pair):
    default, override = pair("{# extractor reads <ANSWER> #}Answer.", "Answer.")
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "compatible"


def test_anchor_in_override_comment_does_not_count(pair):
    default, override = pair("Use <ANSWER>.", "{# <ANSWER> #}Answer.")
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert _markers(report) == {("anchor", "<ANSWER>")}


def test_anchor_in_string_constant_counts(pair):
    default, override = pair(
        '{% set tag = "<ANSWER>" %}{{ tag }}', '{% set tag = "<ANSWER>" %}{{ tag }}'
    )
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "compatible"


def test_unknown_anchor_is_not_a_marker(pair):
    default, override = pair("Use <SOMETHING>.", "Plain.")
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "compatible"


def test_missing_include_is_incomplete(pair):
    default, override = pair('{% include "findings.jinja2" %}Fix it.', "Fix it.")
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "incomplete"
    assert _markers(report) == {("include", "findings.jinja2")}


def test_include_reached_through_another_partial(pair, partials_dir):
    _write(partials_dir / "wrapper.jinja2", '{% include "findings.jinja2" %}')
    _write(partials_dir / "findings.jinja2", "Findings")
    default, override = pair(
        '{% include "findings.jinja2" %}', '{% include "wrapper.jinja2" %}'
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_anchor_in_included_partial_counts_for_both(pair, partials_dir):
    _write(partials_dir / "format.jinja2", "Answer inside <ANSWER>.")
    default, override = pair(
        '{% include "format.jinja2" %}', '{% include "format.jinja2" %}'
    )
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "compatible"


def test_anchor_from_default_partial_missing_in_override(pair, partials_dir):
    _write(partials_dir / "format.jinja2", "Answer inside <ANSWER>.")
    default, override = pair('{% include "format.jinja2" %}', "Answer.")
    report = check_override("narrator", override, default, {"<ANSWER>": frozenset()})
    assert report.compatibility == "incompatible"
    assert _markers(report) == {
        ("anchor", "<ANSWER>"),
        ("include", "format.jinja2"),
    }


def test_missing_context_flag_is_incomplete(pair):
    default, override = pair(
        "{% if audience_summary %}Only what they saw.{% endif %}Summarize.",
        "Summarize.",
    )
    report = check_override("summarizer", override, default, {})
    assert report.compatibility == "incomplete"
    assert _markers(report) == {("flag", "audience_summary")}


def test_flag_referenced_outside_a_condition_counts(pair):
    default, override = pair(
        "{% if decision_findings %}{{ decision_findings }}{% endif %}",
        "{{ decision_findings }}",
    )
    report = check_override("editor", override, default, {})
    assert report.compatibility == "compatible"


def test_flag_in_inline_if(pair):
    default, override = pair("{{ 'x' if evidence else 'y' }}", "y")
    report = check_override("director", override, default, {})
    assert _markers(report) == {("flag", "evidence")}


@pytest.mark.parametrize(
    "default",
    [
        "{% if llm_can_be_coerced() %}x{% endif %}",
        "{% for item in items %}{% if item %}x{% endif %}{% endfor %}",
        "{% for item in [1] %}{% if loop.first %}x{% endif %}{% endfor %}",
        "{% set local = 1 %}{% if local %}x{% endif %}",
        "{% macro m(arg) %}{% if arg %}x{% endif %}{% endmacro %}",
        "{% with w = 1 %}{% if w %}x{% endif %}{% endwith %}",
        "{% if range(2) %}x{% endif %}",
    ],
)
def test_globals_and_local_names_are_not_flags(pair, default):
    default_path, override = pair(default, "plain")
    report = check_override("narrator", override, default_path, {})
    assert not [m for m in report.missing_markers if m.kind == "flag"]


def test_extractor_outranks_include(pair):
    default, override = pair(
        '{% include "x.jinja2" %}{{ set_as_is_extractor("summary") }}', "plain"
    )
    report = check_override("summarizer", override, default, {})
    assert report.compatibility == "incompatible"
    assert _markers(report) == {("extractor", "summary"), ("include", "x.jinja2")}


def test_unparsable_override_is_left_to_the_renderer(pair):
    default, override = pair('{% include "x.jinja2" %}', "{% if %}")
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_edited_file_is_read_again(pair):
    default, override = pair('{% include "x.jinja2" %}', "plain")
    assert check_override("narrator", override, default).compatibility == ("incomplete")
    _write(override, '{% include "x.jinja2" %}', mtime=override.stat().st_mtime + 5)
    assert check_override("narrator", override, default).compatibility == ("compatible")


def test_anchor_argument_of_a_template_setter_is_a_marker(pair):
    default, override = pair(
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write inside <OUT>.',
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write inside <OTHER>.',
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "incompatible"
    assert _markers(report) == {("anchor", "<OUT>")}


def test_setter_argument_alone_does_not_ask_for_the_anchor(pair):
    default, override = pair(
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write it.',
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write it plainly.',
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_extractor_key_given_by_keyword(pair):
    default, override = pair('{{ set_as_is_extractor(name="summary") }}', "plain")
    report = check_override("summarizer", override, default, {})
    assert _markers(report) == {("extractor", "summary")}


def test_extractor_set_in_a_partial(pair, partials_dir):
    _write(
        partials_dir / "format.jinja2",
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write inside <OUT>.',
    )
    default, override = pair('{% include "format.jinja2" %}', "Write inside <OUT>.")
    report = check_override("narrator", override, default, {})
    assert ("extractor", "response") in _markers(report)
    assert report.compatibility == "incompatible"


def test_override_moving_the_setter_into_its_own_partial(pair, partials_dir):
    _write(
        partials_dir / "my-format.jinja2",
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write inside <OUT>.',
    )
    default, override = pair(
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write inside <OUT>.',
        '{% include "my-format.jinja2" %}',
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_scene_plan_outline_with_other_instructions_is_incompatible(tmp_path):
    default = get_default_template_path("director", "scene-plan-create-outline")
    lines = default.read_text().split("\n")
    rewritten = [
        line if "set_anchor_extractor" in line else line.replace("<OUTLINE>", "<PLAN>")
        for line in lines
    ]
    override = _write(tmp_path / "override.jinja2", "\n".join(rewritten))
    report = check_override("director", override, default)
    assert report.compatibility == "incompatible"
    assert ("anchor", "<OUTLINE>") in _markers(report)


def test_contextual_generate_without_its_response_scaffolding(tmp_path):
    # the task partials still set `response`, so only the scaffolding's marker is lost
    default = get_default_template_path("creator", "contextual-generate")
    source = default.read_text()
    include = '{%- include "contextual-generate/response-scaffolding.jinja2" -%}'
    assert include in source
    override = _write(tmp_path / "override.jinja2", source.replace(include, ""))
    report = check_override("creator", override, default)
    assert report.compatibility == "incompatible"
    assert ("anchor", "<COMPLETION>") in _markers(report)
    assert ("extractor", "response") not in _markers(report)


def _close_arc_section(source: str) -> tuple[int, int, int]:
    start = source.index("{%- if close_arc %}")
    middle = source.index("{%- else %}", start)
    end = source.index("{%- endif %}", middle) + len("{%- endif %}")
    return start, middle, end


def test_dropping_a_flag_section_but_keeping_its_rebinding(tmp_path):
    default = get_default_template_path("director", "scene-plan-create-outline")
    source = default.read_text()
    assert "{% set close_arc = close_arc | default(false) %}" in source
    start, middle, end = _close_arc_section(source)
    else_body = source[middle + len("{%- else %}") : end - len("{%- endif %}")]

    for rewritten in (
        source[:start] + source[end:],
        source[:start] + else_body + source[end:],
    ):
        override = _write(tmp_path / "override.jinja2", rewritten)
        report = check_override("director", override, default)
        assert report.compatibility == "incomplete"
        assert ("flag", "close_arc") in _markers(report)


@pytest.mark.parametrize(
    "override",
    [
        "{% for line in lines if feature %}{{ line }}{% endfor %}",
        "{% macro m(on=feature) %}{{ on }}{% endmacro %}{{ m() }}",
        "{% set feature = feature | default(false) %}{{ 'x' if feature }}",
    ],
)
def test_flag_moved_into_other_uses_stays_satisfied(pair, override):
    default_path, override_path = pair("{% if feature %}FEATURE{% endif %}", override)
    report = check_override("narrator", override_path, default_path, {})
    assert report.compatibility == "compatible"


def test_retagging_setter_and_instructions_together(tmp_path):
    default = get_default_template_path("director", "scene-plan-create-outline")
    source = default.read_text()
    retagged = source.replace("OUTLINE>", "PLAN>")
    override = _write(tmp_path / "override.jinja2", retagged)
    report = check_override("director", override, default)
    assert report.compatibility == "compatible", report.missing_markers


def test_following_the_header_override_example(tmp_path):
    # a code-owned anchor (<ANSWER>, REINFORCEMENT_ANSWER_SPEC `response`) replaced
    # by the template's own extractor for the same key
    default = get_default_template_path("world_state", "update-reinforcements")
    source = default.read_text().replace("ANSWER>", "MY_TAG>")
    override = _write(
        tmp_path / "override.jinja2",
        '{{ set_anchor_extractor("response", "<MY_TAG>", "</MY_TAG>") }}\n' + source,
    )
    report = check_override("world_state", override, default)
    assert report.compatibility == "compatible", report.missing_markers


def test_added_setter_above_the_default_one_does_not_replace_it(tmp_path):
    # the last setter call for a key wins; the default's <OUTLINE> setter still runs
    default = get_default_template_path("director", "scene-plan-create-outline")
    source = default.read_text()
    lines = source.split("\n")
    body = "\n".join(
        line if "set_anchor_extractor" in line else line.replace("<OUTLINE>", "<PLAN>")
        for line in lines
    )
    override = _write(
        tmp_path / "override.jinja2",
        '{{ set_anchor_extractor("response", "<PLAN>", "</PLAN>") }}\n' + body,
    )
    report = check_override("director", override, default)
    assert report.compatibility == "incompatible"
    assert ("anchor", "<OUTLINE>") in _markers(report)


def test_last_setter_in_the_file_decides(pair):
    default, override = pair(
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}Write inside <OUT>.',
        '{{ set_anchor_extractor("response", "<OUT>", "</OUT>") }}'
        '{{ set_anchor_extractor("response", "<NEW>", "</NEW>") }}Write inside <NEW>.',
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_setters_for_a_key_in_several_files_are_not_certified(pair, partials_dir):
    _write(
        partials_dir / "mine.jinja2",
        '{{ set_anchor_extractor("response", "<NEW>", "</NEW>") }}',
    )
    default, override = pair(
        "Write inside <OUT>.",
        '{% include "mine.jinja2" %}'
        '{{ set_anchor_extractor("response", "<NEW>", "</NEW>") }}Write inside <NEW>.',
    )
    report = check_override(
        "narrator", override, default, {"<OUT>": frozenset({"response"})}
    )
    assert _markers(report) == {("anchor", "<OUT>")}


def test_computed_anchor_is_unknown(pair):
    default, override = pair(
        "Write inside <OUT>.",
        '{{ set_anchor_extractor("response", "<" ~ "NEW>", "</NEW>") }}Write inside <NEW>.',
    )
    report = check_override(
        "narrator", override, default, {"<OUT>": frozenset({"response"})}
    )
    assert _markers(report) == {("anchor", "<OUT>")}


def test_as_is_replacement_is_compatible(pair):
    default, override = pair(
        "Write inside <OUT>.",
        '{{ set_as_is_extractor("response") }}Write the answer.',
    )
    report = check_override(
        "narrator", override, default, {"<OUT>": frozenset({"response"})}
    )
    assert report.compatibility == "compatible"


def test_retagged_setter_without_asking_for_it_is_still_incompatible(pair):
    default, override = pair(
        "Answer inside <ANSWER>.",
        '{{ set_anchor_extractor("response", "<MY_TAG>", "</MY_TAG>") }}Answer plainly.',
    )
    report = check_override(
        "world_state", override, default, {"<ANSWER>": frozenset({"response"})}
    )
    assert _markers(report) == {("anchor", "<ANSWER>")}


def test_retagging_under_another_key_does_not_count(pair):
    default, override = pair(
        "Answer inside <ANSWER>.",
        '{{ set_anchor_extractor("other", "<MY_TAG>", "</MY_TAG>") }}Answer in <MY_TAG>.',
    )
    report = check_override(
        "world_state", override, default, {"<ANSWER>": frozenset({"response"})}
    )
    assert _markers(report) == {("anchor", "<ANSWER>")}


def test_macro_parameter_does_not_hide_a_context_flag(pair):
    default, override = pair(
        "{% if x %}FEATURE{% endif %}{% macro m(x) %}{{ x }}{% endmacro %}", "plain"
    )
    report = check_override("narrator", override, default, {})
    assert _markers(report) == {("flag", "x")}


def test_loop_variable_outside_its_loop_is_a_flag(pair):
    default, override = pair(
        "{% for item in items %}{{ item }}{% endfor %}{% if item %}x{% endif %}",
        "plain",
    )
    report = check_override("narrator", override, default, {})
    assert _markers(report) == {("flag", "item")}


def test_non_utf8_override_is_left_to_the_renderer(tmp_path):
    default = get_default_template_path("summarizer", "summarize-dialogue")
    override = tmp_path / "override.jinja2"
    override.write_bytes("Résumé ’ {{ dialogue }}".encode("cp1252"))
    report = check_override("summarizer", override, default)
    assert report.compatibility == "compatible"
    assert report.missing_markers == []


def test_non_utf8_partial_does_not_break_the_check(pair, partials_dir):
    (partials_dir / "bad.jinja2").write_bytes("Résumé <OUT>".encode("cp1252"))
    default, override = pair("Write inside <OUT>.", '{% include "bad.jinja2" %}')
    report = check_override("narrator", override, default, {"<OUT>": frozenset()})
    assert _markers(report) == {("anchor", "<OUT>")}


def test_snapshot_override_from_0_39_breaks_the_snapshot_contract():
    default = get_default_template_path("world_state", "request-world-state-v2")
    override = DATA_DIR / "request-world-state-v2-0.39.jinja2"
    report = check_override("world_state", override, default)
    assert report.compatibility == "incompatible"
    markers = _markers(report)
    assert ("contract", "snapshot_request.context_history") in markers
    assert ("flag", "snapshot_request") not in markers
    [contract] = [m for m in report.missing_markers if m.kind == "contract"]
    assert "discards the world snapshot" in contract.detail


@pytest.fixture
def contract(monkeypatch):
    monkeypatch.setattr(contracts, "_contracts", dict(contracts._contracts))
    return contracts.require_template_call(
        "ledger.read", reason="the result is refused without the ledger read"
    )


def test_declared_contract_is_a_breaking_marker(pair, contract):
    default, override = pair(
        "{% set rows = ledger.read(limit=5) %}{{ rows }}", "{{ scene.history }}"
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "incompatible"
    assert _markers(report) == {("contract", "ledger.read")}
    assert report.missing_markers[0].detail == contract.reason


def test_contract_kept_in_an_override_partial(pair, partials_dir, contract):
    _write(partials_dir / "rows.jinja2", "{{ ledger.read(limit=5) }}")
    default, override = pair(
        "{{ ledger.read(limit=5) }}", '{% include "rows.jinja2" %}'
    )
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_contract_only_applies_where_the_default_makes_the_call(pair, contract):
    default, override = pair("{{ ledger.total }}", "plain")
    report = check_override("narrator", override, default, {})
    assert report.compatibility == "compatible"


def test_contract_call_must_be_name_dot_attribute():
    with pytest.raises(ValueError):
        contracts.TemplateContract(call="ledger", reason="x")
    with pytest.raises(ValueError):
        contracts.TemplateContract(call="a.b.c", reason="x")


def test_response_anchors_come_from_loaded_specs():
    anchors = response_anchors()
    # module-level ResponseSpecs of the director, summarizer and world state agents
    assert {"<GUIDANCE>", "SUMMARY:", "<EXAMINE>", "<ANSWER>"} <= set(anchors)
    assert "" not in anchors
    assert anchors["<GUIDANCE>"] == {"guidance"}
    assert "response" in anchors["<ANSWER>"]


@pytest.mark.parametrize(
    "default_path",
    sorted(SHIPPED_DIR.rglob("*.jinja2")),
    ids=lambda path: str(path.relative_to(SHIPPED_DIR)),
)
def test_every_shipped_default_is_compatible_with_itself(default_path, tmp_path):
    agent = default_path.relative_to(SHIPPED_DIR).parts[0]
    override = _write(tmp_path / default_path.name, default_path.read_text())
    report = check_override(agent, override, default_path)
    assert report.missing_markers == []


def test_guide_conversation_from_0_34_is_incompatible():
    default = get_default_template_path("director", "guide-conversation")
    override = DATA_DIR / "guide-conversation-0.34.jinja2"
    report = check_override("director", override, default)
    assert report.compatibility == "incompatible"
    # it asks for a "GUIDANCE:" prefix; GUIDANCE_SPEC parses <GUIDANCE>
    assert ("anchor", "<GUIDANCE>") in _markers(report)


def test_summarize_dialogue_from_0_39_is_incomplete():
    default = get_default_template_path("summarizer", "summarize-dialogue")
    override = DATA_DIR / "summarize-dialogue-0.39.jinja2"
    report = check_override("summarizer", override, default)
    assert report.compatibility == "incomplete"
    assert {
        ("include", "audience-summary-instructions.jinja2"),
        ("flag", "audience_summary"),
    } <= _markers(report)


class TestOverrideStatus:
    @pytest.fixture
    def dirs(self, tmp_path, monkeypatch):
        default_dir = tmp_path / "default"
        user_dir = tmp_path / "user"
        custom_dir = tmp_path / "custom"
        monkeypatch.setattr(groups, "_PROMPTS_DIR", default_dir)
        monkeypatch.setattr(groups, "_USER_TEMPLATES_DIR", user_dir)
        monkeypatch.setattr(groups, "_CUSTOM_GROUPS_DIR", custom_dir)
        config = Mock()
        config.prompts.group_priority = ["user", "mine"]
        config.prompts.template_sources = {}
        monkeypatch.setattr(groups, "_get_config", lambda: config)
        return default_dir, user_dir, custom_dir

    def test_default_group_has_no_status(self, dirs):
        default_dir, _, _ = dirs
        _write(default_dir / "narrator" / "t.jinja2", "x")
        assert override_status("default", "narrator", "t").has_default is False

    def test_template_without_default(self, dirs):
        _, user_dir, _ = dirs
        _write(user_dir / "narrator" / "t.jinja2", "x")
        assert override_status("user", "narrator", "t").has_default is False

    def test_group_without_its_own_copy(self, dirs):
        default_dir, _, _ = dirs
        _write(default_dir / "narrator" / "t.jinja2", "x")
        status = override_status("user", "narrator", "t")
        assert status.has_default is True
        assert status.fallback_group is None
        assert status.compatibility == "compatible"
        assert status.is_outdated is False

    def test_outdated_and_incomplete_override(self, dirs):
        default_dir, user_dir, _ = dirs
        _write(default_dir / "narrator" / "t.jinja2", '{% include "x.jinja2" %}', 2000)
        _write(user_dir / "narrator" / "t.jinja2", "plain", 1000)
        status = override_status("user", "narrator", "t")
        assert status.has_default is True
        assert status.fallback_group == "default"
        assert status.is_outdated is True
        assert status.compatibility == "incomplete"
        assert [(m.kind, m.name) for m in status.missing_markers] == [
            ("include", "x.jinja2")
        ]

    def test_fallback_is_the_next_group_with_a_copy(self, dirs):
        default_dir, user_dir, custom_dir = dirs
        _write(default_dir / "narrator" / "t.jinja2", "x")
        _write(user_dir / "narrator" / "t.jinja2", "x")
        _write(custom_dir / "mine" / "narrator" / "t.jinja2", "x")
        assert override_status("user", "narrator", "t").fallback_group == "mine"
        assert override_status("mine", "narrator", "t").fallback_group == "user"


def _info(uid: str, **fields) -> TemplateInfo:
    agent, name = uid.split(".", 1)
    return TemplateInfo(
        agent=agent,
        name=name,
        uid=uid,
        source_group="user",
        available_in=["default", "user"],
        **fields,
    )


def test_startup_log_levels():
    templates = [
        _info("narrator.current"),
        _info("narrator.old", is_outdated=True),
        _info(
            "summarizer.summarize-dialogue",
            is_outdated=True,
            compatibility="incomplete",
            missing_markers=[
                MissingMarker(
                    kind="include", name="audience-summary-instructions.jinja2"
                )
            ],
        ),
        _info(
            "director.guide-conversation",
            compatibility="incompatible",
            missing_markers=[
                MissingMarker(kind="anchor", name="<GUIDANCE>"),
                MissingMarker(
                    kind="contract",
                    name="snapshot_request.context_history",
                    detail="Talemate discards the snapshot.",
                ),
            ],
        ),
    ]

    with capture_logs() as logs:
        log_override_status(templates)

    assert [
        (entry["log_level"], entry["event"], entry["template"]) for entry in logs
    ] == [
        ("info", "Outdated template override", "narrator.old"),
        ("warning", "Incomplete template override", "summarizer.summarize-dialogue"),
        ("warning", "Incompatible template override", "director.guide-conversation"),
    ]
    assert logs[1]["missing"] == ["include audience-summary-instructions.jinja2"]
    assert logs[2]["group"] == "user"
    assert logs[2]["missing"] == [
        "anchor <GUIDANCE>",
        "contract snapshot_request.context_history (Talemate discards the snapshot.)",
    ]
