"""
Additional unit tests for talemate.prompts.groups, covering branches not
exercised by tests/prompts/test_groups.py.

Focus areas:
- ``get_scene_template_path`` returns None for non-string template_dir (line 145)
- ``_get_file_mtime`` exception handling (lines 327-330)
- ``list_templates`` (the entire 349-489 region)
- ``delete_template`` fallback to flat scene-template structure (591-593)
"""

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from talemate.prompts import groups

from ._groups_test_helpers import make_template_dir_scene


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_template(path: Path, content: str = "x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def isolated_groups_dirs(tmp_path):
    """
    Patch all of groups' module-level directories at once and create fresh dirs.

    Returns a dict with the four key Paths so tests can populate them with
    fixture templates without touching the real repo dirs.
    """
    default_dir = tmp_path / "default"
    user_dir = tmp_path / "user"
    custom_dir = tmp_path / "custom_groups"
    scene_dir = tmp_path / "scene"

    # The `default` dir is treated as the *root* of agent subdirs (mirrors
    # ``src/talemate/prompts/templates/{agent}/``), so create it now.
    default_dir.mkdir()
    user_dir.mkdir()
    custom_dir.mkdir()
    scene_dir.mkdir()

    with (
        patch.object(groups, "_PROMPTS_DIR", default_dir),
        patch.object(groups, "_USER_TEMPLATES_DIR", user_dir),
        patch.object(groups, "_CUSTOM_GROUPS_DIR", custom_dir),
    ):
        yield {
            "default": default_dir,
            "user": user_dir,
            "custom": custom_dir,
            "scene": scene_dir,
            "tmp": tmp_path,
        }


@pytest.fixture
def patched_config():
    """Install a Mock config with the typical prompts attributes."""
    config = Mock()
    config.prompts = Mock()
    config.prompts.group_priority = ["user"]
    config.prompts.template_sources = {}

    with patch.object(groups, "_get_config", return_value=config):
        yield config


# ---------------------------------------------------------------------------
# get_scene_template_path — non-string template_dir branch (line 145)
# ---------------------------------------------------------------------------


class TestGetSceneTemplatePathInvalidDir:
    """Cover the early-return for a non-string ``template_dir``."""

    def test_returns_none_when_template_dir_is_none(self):
        scene = make_template_dir_scene(template_dir=None)

        result = groups.get_scene_template_path(scene, "narrator", "anything")

        assert result is None

    def test_returns_none_when_template_dir_is_path_object(self, tmp_path):
        # The function specifically checks ``isinstance(template_dir, str)`` —
        # a Path (which is otherwise valid) hits the early return.
        scene = make_template_dir_scene(template_dir=tmp_path)  # Path, not str

        result = groups.get_scene_template_path(scene, "narrator", "anything")

        assert result is None

    def test_returns_none_when_template_dir_attr_missing(self):
        # ``getattr(scene, "template_dir", None)`` defaults to None which
        # falls through to the same early return.
        class _NoAttrScene:
            pass

        result = groups.get_scene_template_path(_NoAttrScene(), "narrator", "x")

        assert result is None


# ---------------------------------------------------------------------------
# _get_file_mtime — OSError branch (lines 327-330)
# ---------------------------------------------------------------------------


class TestGetFileMtime:
    """Cover the helper directly, including its exception handler."""

    def test_returns_none_for_missing_file(self, tmp_path):
        result = groups._get_file_mtime(tmp_path / "nope.jinja2")
        assert result is None

    def test_returns_mtime_for_existing_file(self, tmp_path):
        path = _write_template(tmp_path / "real.jinja2", mtime=1_234_567.0)
        result = groups._get_file_mtime(path)

        assert result == pytest.approx(1_234_567.0)

    def test_oserror_returns_none(self, tmp_path):
        """If stat() raises OSError unexpectedly, _get_file_mtime swallows it."""
        path = _write_template(tmp_path / "blow.jinja2")

        # Force the inner stat() call to raise OSError. We only patch stat
        # (not Path.exists), so the existence check passes and we hit the
        # except branch.
        original_stat = Path.stat

        def boom(self, *args, **kwargs):
            if self == path:
                raise OSError("simulated failure")
            return original_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", boom):
            result = groups._get_file_mtime(path)

        assert result is None


# ---------------------------------------------------------------------------
# list_templates (lines 349-489) — the big function
# ---------------------------------------------------------------------------


class TestListTemplatesEmpty:
    """Empty-state checks for list_templates."""

    def test_returns_empty_when_no_templates_anywhere(
        self, isolated_groups_dirs, patched_config
    ):
        result = groups.list_templates()
        assert result == []


class TestListTemplatesDefaultOnly:
    """A template only in default appears as source_group='default', not outdated."""

    def test_default_only_template(self, isolated_groups_dirs, patched_config):
        d = isolated_groups_dirs["default"]
        _write_template(d / "narrator" / "hello.jinja2")

        result = groups.list_templates()

        # Filter to just our template (others may exist if some scan picks them up)
        ours = [t for t in result if t.uid == "narrator.hello"]
        assert len(ours) == 1
        info = ours[0]

        assert info.agent == "narrator"
        assert info.name == "hello"
        assert info.source_group == "default"
        assert info.is_outdated is False
        assert info.is_unresolvable is False
        assert info.default_mtime is None  # Not calculated for default-only templates
        assert info.override_mtime is None
        # available_in always includes default for default-resident templates
        assert "default" in info.available_in


class TestListTemplatesUserOverride:
    """Template overridden in user group resolves to user, with mtime info."""

    def test_user_override_resolves_to_user_when_active(
        self, isolated_groups_dirs, patched_config
    ):
        d = isolated_groups_dirs["default"]
        u = isolated_groups_dirs["user"]

        # Default older than user → not outdated.
        _write_template(d / "narrator" / "x.jinja2", mtime=1_000_000.0)
        _write_template(u / "narrator" / "x.jinja2", mtime=2_000_000.0)

        # User group is active by default in patched_config.
        result = groups.list_templates()

        info = next(t for t in result if t.uid == "narrator.x")
        assert info.source_group == "user"
        assert info.is_unresolvable is False
        # Both groups present in available_in.
        assert "default" in info.available_in
        assert "user" in info.available_in
        # Mtime fields populated since override exists.
        assert info.default_mtime == pytest.approx(1_000_000.0)
        assert info.override_mtime == pytest.approx(2_000_000.0)
        assert info.is_outdated is False  # override newer than default

    def test_outdated_when_override_older_than_default(
        self, isolated_groups_dirs, patched_config
    ):
        d = isolated_groups_dirs["default"]
        u = isolated_groups_dirs["user"]

        # User override is OLDER than default → is_outdated=True.
        _write_template(d / "narrator" / "y.jinja2", mtime=2_000_000.0)
        _write_template(u / "narrator" / "y.jinja2", mtime=1_000_000.0)

        result = groups.list_templates()
        info = next(t for t in result if t.uid == "narrator.y")

        assert info.source_group == "user"
        assert info.is_outdated is True
        assert info.default_mtime > info.override_mtime

    def test_override_missing_include_is_incomplete(
        self, isolated_groups_dirs, patched_config
    ):
        d = isolated_groups_dirs["default"]
        u = isolated_groups_dirs["user"]

        # A newer file can still miss what the default needs.
        _write_template(
            d / "narrator" / "z.jinja2", '{% include "x.jinja2" %}', 1_000_000.0
        )
        _write_template(u / "narrator" / "z.jinja2", "plain", 2_000_000.0)

        result = groups.list_templates()
        info = next(t for t in result if t.uid == "narrator.z")

        assert info.is_outdated is False
        assert info.compatibility == "incomplete"
        assert [(m.kind, m.name) for m in info.missing_markers] == [
            ("include", "x.jinja2")
        ]

    def test_default_template_is_not_checked(
        self, isolated_groups_dirs, patched_config
    ):
        _write_template(
            isolated_groups_dirs["default"] / "narrator" / "d.jinja2",
            '{% include "x.jinja2" %}',
        )

        result = groups.list_templates()
        info = next(t for t in result if t.uid == "narrator.d")

        assert info.source_group == "default"
        assert info.compatibility == "compatible"
        assert info.missing_markers == []


class TestListTemplatesUnresolvable:
    """Template only in an inactive custom group is marked unresolvable."""

    def test_inactive_custom_group_marks_template_unresolvable(
        self, isolated_groups_dirs, patched_config
    ):
        custom = isolated_groups_dirs["custom"]
        # Group exists on disk but is NOT in group_priority → inactive.
        _write_template(custom / "ghost-group" / "narrator" / "z.jinja2")
        # Default has nothing for narrator/z.

        # Make sure ghost-group is NOT active.
        patched_config.prompts.group_priority = ["user"]

        result = groups.list_templates()
        info = next(t for t in result if t.uid == "narrator.z")

        assert info.is_unresolvable is True
        # Falls back to first available_in when unresolvable.
        assert info.source_group == "ghost-group"
        assert "ghost-group" in info.available_in
        # Not outdated because no default, no override mtime calc.
        assert info.is_outdated is False
        assert info.default_mtime is None
        assert info.override_mtime is None


class TestListTemplatesNestedNames:
    """Nested template subdirs produce slash-joined template names."""

    def test_nested_template_name_includes_subpath(
        self, isolated_groups_dirs, patched_config
    ):
        d = isolated_groups_dirs["default"]
        _write_template(d / "narrator" / "sub" / "deep.jinja2")

        result = groups.list_templates()
        nested = [t for t in result if t.name.endswith("deep")]

        assert len(nested) == 1
        info = nested[0]
        # Subpath is preserved in the template name.
        assert info.name == "sub/deep"
        assert info.uid == "narrator.sub/deep"
        assert info.agent == "narrator"

    def test_template_at_group_root_is_skipped(
        self, isolated_groups_dirs, patched_config
    ):
        """Templates dropped directly into the group root (no agent dir) are skipped."""
        d = isolated_groups_dirs["default"]
        # No agent subdir — the function's IndexError-on-empty path skips it.
        _write_template(d / "rootless.jinja2")

        result = groups.list_templates()

        # Should NOT produce a TemplateInfo for this rootless file.
        assert all("rootless" not in t.name for t in result)


class TestListTemplatesScene:
    """Scene templates are scanned (agent subdirs and flat structure)."""

    def test_scene_agent_subdir_template(self, isolated_groups_dirs, patched_config):
        scene_dir = isolated_groups_dirs["scene"]
        _write_template(scene_dir / "narrator" / "scene-only.jinja2")

        scene = make_template_dir_scene(template_dir=str(scene_dir))

        result = groups.list_templates(scene=scene)

        info = next(t for t in result if t.uid == "narrator.scene-only")
        assert info.source_group == "scene"
        assert "scene" in info.available_in

    def test_scene_flat_template_uses_empty_agent(
        self, isolated_groups_dirs, patched_config
    ):
        """Flat scene template (no agent subdir) gets a uid of '.<name>'."""
        scene_dir = isolated_groups_dirs["scene"]
        _write_template(scene_dir / "flat-only.jinja2")

        scene = make_template_dir_scene(template_dir=str(scene_dir))

        result = groups.list_templates(scene=scene)

        info = next(t for t in result if t.name == "flat-only")
        assert info.agent == ""
        assert info.uid == ".flat-only"
        assert info.source_group == "scene"
        assert "scene" in info.available_in

    def test_scene_flat_template_appends_to_existing_entry(
        self, isolated_groups_dirs, patched_config
    ):
        """If a flat-name uid was already discovered, scene gets added to available_in."""
        scene_dir = isolated_groups_dirs["scene"]
        # Create the scene dir with both an agent subdir AND a flat file with same name.
        _write_template(scene_dir / "narrator" / "shared.jinja2")
        _write_template(scene_dir / "shared.jinja2")  # flat

        scene = make_template_dir_scene(template_dir=str(scene_dir))

        result = groups.list_templates(scene=scene)

        # Two distinct entries: 'narrator.shared' (agent subdir) and '.shared' (flat).
        agent_entry = next(t for t in result if t.uid == "narrator.shared")
        flat_entry = next(t for t in result if t.uid == ".shared")

        assert agent_entry.agent == "narrator"
        assert flat_entry.agent == ""
        assert "scene" in flat_entry.available_in

    def test_no_scene_returns_default_for_flat_only_branch(
        self, isolated_groups_dirs, patched_config
    ):
        """Without a scene, no flat scene templates exist → only agent-bound templates."""
        # Pure regression check: no scene means no '.<name>' entries are created.
        result = groups.list_templates(scene=None)

        # No flat-uid entries should ever appear.
        assert all(not t.uid.startswith(".") for t in result)


class TestListTemplatesIncludeSourcesFlag:
    """include_sources=False suppresses available_in tracking."""

    def test_include_sources_false_yields_empty_available_in(
        self, isolated_groups_dirs, patched_config
    ):
        d = isolated_groups_dirs["default"]
        _write_template(d / "narrator" / "skip.jinja2")

        result = groups.list_templates(include_sources=False)

        # Find our template — available_in is not populated.
        info = next(t for t in result if t.uid == "narrator.skip")
        assert info.available_in == []
        # Without "default" in available_in, mtime is not populated either.
        assert info.default_mtime is None
        assert info.override_mtime is None


class TestListTemplatesScanDirNonExistent:
    """If a directory doesn't exist, scan_directory returns early without crashing."""

    def test_missing_user_dir_does_not_crash(self, tmp_path, patched_config):
        # User dir is set to a path that does NOT exist.
        default_dir = tmp_path / "default"
        default_dir.mkdir()
        _write_template(default_dir / "narrator" / "ok.jinja2")

        with (
            patch.object(groups, "_PROMPTS_DIR", default_dir),
            patch.object(groups, "_USER_TEMPLATES_DIR", tmp_path / "missing-user"),
            patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "missing-custom"),
        ):
            result = groups.list_templates()

        # Default template still discovered.
        assert any(t.uid == "narrator.ok" for t in result)


class TestListTemplatesScanCustomGroups:
    """Custom group directories are walked when CUSTOM_GROUPS_DIR exists."""

    def test_template_in_custom_group_visible_in_available_in(
        self, isolated_groups_dirs, patched_config
    ):
        custom = isolated_groups_dirs["custom"]
        d = isolated_groups_dirs["default"]
        _write_template(d / "narrator" / "ct.jinja2", mtime=1_000_000.0)
        _write_template(
            custom / "my-group" / "narrator" / "ct.jinja2", mtime=2_000_000.0
        )

        # Activate my-group so it actually resolves there.
        patched_config.prompts.group_priority = ["my-group"]

        result = groups.list_templates()
        info = next(t for t in result if t.uid == "narrator.ct")

        assert info.source_group == "my-group"
        assert "my-group" in info.available_in
        assert "default" in info.available_in
        assert info.override_mtime == pytest.approx(2_000_000.0)


class TestListTemplatesScenePriorityForOverrideMtime:
    """When source_group is 'scene', override mtime comes from scene path."""

    def test_scene_override_mtime_uses_scene_template_path(
        self, isolated_groups_dirs, patched_config
    ):
        d = isolated_groups_dirs["default"]
        scene_dir = isolated_groups_dirs["scene"]

        _write_template(d / "narrator" / "ovr.jinja2", mtime=1_000_000.0)
        _write_template(scene_dir / "narrator" / "ovr.jinja2", mtime=3_000_000.0)

        scene = make_template_dir_scene(template_dir=str(scene_dir))

        result = groups.list_templates(scene=scene)
        info = next(t for t in result if t.uid == "narrator.ovr")

        # Scene wins (highest priority).
        assert info.source_group == "scene"
        assert info.default_mtime == pytest.approx(1_000_000.0)
        assert info.override_mtime == pytest.approx(3_000_000.0)
        assert info.is_outdated is False


# ---------------------------------------------------------------------------
# delete_template — flat scene-template fallback (lines 591-593)
# ---------------------------------------------------------------------------


class TestDeleteTemplateSceneFlatFallback:
    """If the agent subdir path doesn't exist, fall back to the flat scene path."""

    def test_falls_back_to_flat_scene_path_when_agent_subdir_empty(self, tmp_path):
        # Only a flat-structure scene template exists; no narrator/ subdir.
        scene = make_template_dir_scene(template_dir=str(tmp_path))
        flat_template = tmp_path / "flat.jinja2"
        flat_template.write_text("flat content")

        # Sanity: agent subdir path does NOT exist.
        assert not (tmp_path / "narrator" / "flat.jinja2").exists()

        result = groups.delete_template("scene", "narrator", "flat", scene=scene)

        assert result is True
        assert not flat_template.exists()

    def test_returns_false_when_neither_path_exists(self, tmp_path):
        """No agent subdir AND no flat file → returns False, raises nothing."""
        scene = make_template_dir_scene(template_dir=str(tmp_path))

        result = groups.delete_template("scene", "narrator", "missing", scene=scene)

        assert result is False


class TestIdentifyTemplateFile:
    def test_group_directories(self, isolated_groups_dirs):
        d = isolated_groups_dirs
        assert groups.identify_template_file(
            d["default"] / "narrator" / "a.jinja2"
        ) == (
            "default",
            "narrator",
            "a",
        )
        assert groups.identify_template_file(d["user"] / "common" / "b.jinja2") == (
            "user",
            "common",
            "b",
        )
        assert groups.identify_template_file(
            d["custom"] / "mine" / "creator" / "sub" / "c.jinja2"
        ) == ("mine", "creator", "sub/c")

    def test_scene_directory(self, isolated_groups_dirs):
        scene = make_template_dir_scene(str(isolated_groups_dirs["scene"]))
        path = isolated_groups_dirs["scene"] / "narrator" / "d.jinja2"
        assert groups.identify_template_file(path, scene) == ("scene", "narrator", "d")

    def test_flat_scene_file_takes_the_rendered_agent(self, isolated_groups_dirs):
        scene = make_template_dir_scene(str(isolated_groups_dirs["scene"]))
        path = isolated_groups_dirs["scene"] / "e.jinja2"
        assert groups.identify_template_file(path, scene) is None
        assert groups.identify_template_file(path, scene, flat_agent="director") == (
            "scene",
            "director",
            "e",
        )

    def test_unknown_or_flat_files(self, isolated_groups_dirs, tmp_path):
        assert groups.identify_template_file(tmp_path / "elsewhere.jinja2") is None
        assert (
            groups.identify_template_file(isolated_groups_dirs["user"] / "flat.jinja2")
            is None
        )
