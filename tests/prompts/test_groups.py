"""
Unit tests for prompt template group resolution logic.

Tests the priority-based template resolution system including:
- Scene templates (highest priority)
- Explicit template_sources overrides
- Group priority list
- Default fallback
"""

from unittest.mock import Mock, patch

import pytest

from talemate.prompts import groups


class TestGetDefaultTemplatePath:
    """Tests for get_default_template_path()."""

    def test_returns_correct_path(self):
        """Default path points to prompts/templates/{agent}/."""
        path = groups.get_default_template_path("narrator", "test-template")
        assert path.name == "test-template.jinja2"
        assert "narrator" in path.parts
        assert "templates" in path.parts

    def test_different_agents(self):
        """Different agents have different paths."""
        narrator_path = groups.get_default_template_path("narrator", "foo")
        director_path = groups.get_default_template_path("director", "foo")
        assert narrator_path != director_path
        assert "narrator" in str(narrator_path)
        assert "director" in str(director_path)


class TestGetUserTemplatePath:
    """Tests for get_user_template_path()."""

    def test_returns_correct_path(self):
        """User path points to ./templates/prompts/{agent}/."""
        path = groups.get_user_template_path("narrator", "my-template")
        assert path.name == "my-template.jinja2"
        assert "prompts" in path.parts
        assert "narrator" in path.parts


class TestGetGroupTemplatePath:
    """Tests for get_group_template_path()."""

    def test_user_group(self):
        """User group uses user template path."""
        path = groups.get_group_template_path("user", "narrator", "test")
        user_path = groups.get_user_template_path("narrator", "test")
        assert path == user_path

    def test_default_group(self):
        """Default group uses default template path."""
        path = groups.get_group_template_path("default", "narrator", "test")
        default_path = groups.get_default_template_path("narrator", "test")
        assert path == default_path

    def test_custom_group(self):
        """Custom group uses prompt_groups directory."""
        path = groups.get_group_template_path("my-group", "narrator", "test")
        assert "prompt_groups" in path.parts
        assert "my-group" in path.parts
        assert "narrator" in path.parts


class TestGetSceneTemplatePath:
    """Tests for get_scene_template_path()."""

    def test_agent_subdirectory_preferred(self, tmp_path):
        """Agent-specific subdirectory is preferred when it exists."""
        scene = Mock()
        scene.template_dir = str(tmp_path)

        # Create agent subdirectory with template
        agent_dir = tmp_path / "narrator"
        agent_dir.mkdir()
        template_file = agent_dir / "test.jinja2"
        template_file.write_text("agent template")

        path = groups.get_scene_template_path(scene, "narrator", "test")
        assert path == template_file

    def test_falls_back_to_flat_structure(self, tmp_path):
        """Falls back to flat structure when agent subdir doesn't exist."""
        scene = Mock()
        scene.template_dir = str(tmp_path)

        # Create flat template (no agent subdir)
        flat_template = tmp_path / "test.jinja2"
        flat_template.write_text("flat template")

        path = groups.get_scene_template_path(scene, "narrator", "test")
        assert path == flat_template

    def test_returns_expected_path_even_if_missing(self, tmp_path):
        """Returns the expected path even if template doesn't exist."""
        scene = Mock()
        scene.template_dir = str(tmp_path)

        path = groups.get_scene_template_path(scene, "narrator", "missing")
        # Should return flat path since no agent subdir exists
        assert path == tmp_path / "missing.jinja2"


class TestResolveTemplate:
    """Tests for resolve_template()."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config with prompts settings."""
        config = Mock()
        config.prompts = Mock()
        config.prompts.group_priority = ["user"]
        config.prompts.template_sources = {}
        return config

    def test_scene_has_highest_priority(self, tmp_path, mock_config):
        """Scene templates always take priority over everything else."""
        scene = Mock()
        scene.template_dir = str(tmp_path)

        # Create scene template
        scene_template = tmp_path / "test.jinja2"
        scene_template.write_text("scene template")

        with patch.object(groups, "_get_config", return_value=mock_config):
            path, source = groups.resolve_template("narrator", "test", scene)

        assert source == "scene"
        assert path == scene_template

    def test_explicit_source_override(self, tmp_path, mock_config):
        """Explicit template_sources override is respected."""
        mock_config.prompts.template_sources = {"narrator.test": "my-group"}

        # Create the template in custom group
        custom_group_dir = (
            tmp_path / "templates" / "prompt_groups" / "my-group" / "narrator"
        )
        custom_group_dir.mkdir(parents=True)
        custom_template = custom_group_dir / "test.jinja2"
        custom_template.write_text("custom group template")

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(
                groups, "_CUSTOM_GROUPS_DIR", tmp_path / "templates" / "prompt_groups"
            ):
                path, source = groups.resolve_template("narrator", "test")

        assert source == "my-group"
        assert path == custom_template

    def test_explicit_source_falls_back_if_missing(self, tmp_path, mock_config):
        """Falls back if explicit source template doesn't exist."""
        mock_config.prompts.template_sources = {"narrator.test": "nonexistent-group"}
        mock_config.prompts.group_priority = []

        # Create default template
        default_dir = tmp_path / "default" / "narrator"
        default_dir.mkdir(parents=True)
        default_template = default_dir / "test.jinja2"
        default_template.write_text("default template")

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path / "default"):
                path, source = groups.resolve_template("narrator", "test")

        assert source == "default"
        assert path == default_template

    def test_group_priority_order(self, tmp_path, mock_config):
        """Templates are resolved in group_priority order."""
        mock_config.prompts.group_priority = ["group-a", "group-b", "user"]
        mock_config.prompts.template_sources = {}

        # Create template only in group-b (not in group-a)
        group_b_dir = tmp_path / "prompt_groups" / "group-b" / "narrator"
        group_b_dir.mkdir(parents=True)
        group_b_template = group_b_dir / "test.jinja2"
        group_b_template.write_text("group-b template")

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
                path, source = groups.resolve_template("narrator", "test")

        assert source == "group-b"
        assert path == group_b_template

    def test_falls_back_to_default(self, tmp_path, mock_config):
        """Falls back to default when no other source has the template."""
        mock_config.prompts.group_priority = []
        mock_config.prompts.template_sources = {}

        # Create only default template
        default_dir = tmp_path / "default" / "narrator"
        default_dir.mkdir(parents=True)
        default_template = default_dir / "test.jinja2"
        default_template.write_text("default template")

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path / "default"):
                path, source = groups.resolve_template("narrator", "test")

        assert source == "default"
        assert path == default_template

    def test_returns_none_if_not_found(self, tmp_path, mock_config):
        """Returns (None, None) if template not found anywhere."""
        mock_config.prompts.group_priority = []
        mock_config.prompts.template_sources = {}

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path / "empty"):
                path, source = groups.resolve_template("narrator", "nonexistent")

        assert path is None
        assert source is None

    def test_scene_override_beats_explicit_source(self, tmp_path, mock_config):
        """Scene templates override even explicit template_sources."""
        scene = Mock()
        scene.template_dir = str(tmp_path / "scene")

        mock_config.prompts.template_sources = {"narrator.test": "my-group"}

        # Create both scene template and custom group template
        (tmp_path / "scene").mkdir()
        scene_template = tmp_path / "scene" / "test.jinja2"
        scene_template.write_text("scene template")

        custom_dir = tmp_path / "prompt_groups" / "my-group" / "narrator"
        custom_dir.mkdir(parents=True)
        custom_template = custom_dir / "test.jinja2"
        custom_template.write_text("custom template")

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
                path, source = groups.resolve_template("narrator", "test", scene)

        # Scene should win
        assert source == "scene"
        assert path == scene_template

    def test_backward_compat_no_prompts_config(self, tmp_path):
        """Works correctly when prompts config is not present."""
        config = Mock()
        config.prompts = None

        # Create default template
        default_dir = tmp_path / "default" / "narrator"
        default_dir.mkdir(parents=True)
        default_template = default_dir / "test.jinja2"
        default_template.write_text("default template")

        with patch.object(groups, "_get_config", return_value=config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path / "default"):
                path, source = groups.resolve_template("narrator", "test")

        assert source == "default"
        assert path == default_template


class TestListGroups:
    """Tests for list_groups()."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config with prompts settings."""
        config = Mock()
        config.prompts = Mock()
        config.prompts.group_priority = ["user"]
        return config

    def test_includes_default_group(self, tmp_path, mock_config):
        """Default group is always included."""
        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path):
                with patch.object(groups, "_USER_TEMPLATES_DIR", tmp_path / "user"):
                    with patch.object(
                        groups, "_CUSTOM_GROUPS_DIR", tmp_path / "custom"
                    ):
                        result = groups.list_groups()

        default_groups = [g for g in result if g.name == "default"]
        assert len(default_groups) == 1
        assert default_groups[0].is_readonly is True
        assert default_groups[0].is_active is True

    def test_includes_user_group(self, tmp_path, mock_config):
        """User group is always included."""
        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path):
                with patch.object(groups, "_USER_TEMPLATES_DIR", tmp_path / "user"):
                    with patch.object(
                        groups, "_CUSTOM_GROUPS_DIR", tmp_path / "custom"
                    ):
                        result = groups.list_groups()

        user_groups = [g for g in result if g.name == "user"]
        assert len(user_groups) == 1
        assert user_groups[0].is_readonly is False

    def test_includes_scene_group_when_scene_provided(self, tmp_path, mock_config):
        """Scene group is included only when scene is provided."""
        scene = Mock()
        scene.template_dir = str(tmp_path / "scene")
        (tmp_path / "scene").mkdir()

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path):
                with patch.object(groups, "_USER_TEMPLATES_DIR", tmp_path / "user"):
                    with patch.object(
                        groups, "_CUSTOM_GROUPS_DIR", tmp_path / "custom"
                    ):
                        result_with_scene = groups.list_groups(scene)
                        result_without_scene = groups.list_groups()

        scene_groups_with = [g for g in result_with_scene if g.name == "scene"]
        scene_groups_without = [g for g in result_without_scene if g.name == "scene"]

        assert len(scene_groups_with) == 1
        assert len(scene_groups_without) == 0

    def test_includes_custom_groups(self, tmp_path, mock_config):
        """Custom groups from prompt_groups directory are included."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "my-group").mkdir()
        (custom_dir / "another-group").mkdir()

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path):
                with patch.object(groups, "_USER_TEMPLATES_DIR", tmp_path / "user"):
                    with patch.object(groups, "_CUSTOM_GROUPS_DIR", custom_dir):
                        result = groups.list_groups()

        custom_group_names = {
            g.name for g in result if g.name not in ("default", "user")
        }
        assert "my-group" in custom_group_names
        assert "another-group" in custom_group_names

    def test_active_status_from_priority(self, tmp_path, mock_config):
        """is_active reflects presence in group_priority."""
        mock_config.prompts.group_priority = ["user", "active-group"]

        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "active-group").mkdir()
        (custom_dir / "inactive-group").mkdir()

        with patch.object(groups, "_get_config", return_value=mock_config):
            with patch.object(groups, "_PROMPTS_DIR", tmp_path):
                with patch.object(groups, "_USER_TEMPLATES_DIR", tmp_path / "user"):
                    with patch.object(groups, "_CUSTOM_GROUPS_DIR", custom_dir):
                        result = groups.list_groups()

        active_group = next(g for g in result if g.name == "active-group")
        inactive_group = next(g for g in result if g.name == "inactive-group")
        user_group = next(g for g in result if g.name == "user")

        assert active_group.is_active is True
        assert inactive_group.is_active is False
        assert user_group.is_active is True


class TestGetTemplateContent:
    """Tests for get_template_content()."""

    def test_reads_content_from_group(self, tmp_path):
        """Reads template content from specified group."""
        group_dir = tmp_path / "prompt_groups" / "my-group" / "narrator"
        group_dir.mkdir(parents=True)
        template = group_dir / "test.jinja2"
        template.write_text("template content here")

        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
            content = groups.get_template_content("my-group", "narrator", "test")

        assert content == "template content here"

    def test_returns_none_if_not_found(self, tmp_path):
        """Returns None if template doesn't exist."""
        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
            content = groups.get_template_content("my-group", "narrator", "nonexistent")

        assert content is None

    def test_scene_group_requires_scene(self):
        """Scene group requires scene parameter."""
        content = groups.get_template_content("scene", "narrator", "test")
        assert content is None

    def test_reads_scene_template(self, tmp_path):
        """Reads template from scene when group is 'scene'."""
        scene = Mock()
        scene.template_dir = str(tmp_path)

        # Create template in agent subdir
        agent_dir = tmp_path / "narrator"
        agent_dir.mkdir()
        template = agent_dir / "test.jinja2"
        template.write_text("scene template content")

        content = groups.get_template_content("scene", "narrator", "test", scene)
        assert content == "scene template content"


class TestWriteTemplate:
    """Tests for write_template()."""

    def test_cannot_write_to_default(self):
        """Writing to default group raises ValueError."""
        with pytest.raises(ValueError, match="read-only"):
            groups.write_template("default", "narrator", "test", "content")

    def test_scene_requires_scene(self):
        """Writing to scene group without scene raises ValueError."""
        with pytest.raises(ValueError, match="Scene is required"):
            groups.write_template("scene", "narrator", "test", "content")

    def test_writes_to_custom_group(self, tmp_path):
        """Writes template to custom group directory."""
        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
            groups.write_template("my-group", "narrator", "test", "new content")

        template_path = (
            tmp_path / "prompt_groups" / "my-group" / "narrator" / "test.jinja2"
        )
        assert template_path.exists()
        assert template_path.read_text() == "new content"

    def test_writes_to_scene(self, tmp_path):
        """Writes template to scene directory."""
        scene = Mock()
        scene.template_dir = str(tmp_path)

        groups.write_template("scene", "narrator", "test", "scene content", scene)

        template_path = tmp_path / "narrator" / "test.jinja2"
        assert template_path.exists()
        assert template_path.read_text() == "scene content"

    def test_creates_directories(self, tmp_path):
        """Creates necessary directories when writing."""
        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
            groups.write_template("new-group", "new-agent", "new-template", "content")

        template_path = (
            tmp_path
            / "prompt_groups"
            / "new-group"
            / "new-agent"
            / "new-template.jinja2"
        )
        assert template_path.exists()


class TestDeleteTemplate:
    """Tests for delete_template()."""

    def test_cannot_delete_from_default(self):
        """Deleting from default group raises ValueError."""
        with pytest.raises(ValueError, match="read-only"):
            groups.delete_template("default", "narrator", "test")

    def test_scene_requires_scene(self):
        """Deleting from scene group without scene raises ValueError."""
        with pytest.raises(ValueError, match="Scene is required"):
            groups.delete_template("scene", "narrator", "test")

    def test_deletes_template(self, tmp_path):
        """Deletes template from group."""
        group_dir = tmp_path / "prompt_groups" / "my-group" / "narrator"
        group_dir.mkdir(parents=True)
        template = group_dir / "test.jinja2"
        template.write_text("content")

        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
            result = groups.delete_template("my-group", "narrator", "test")

        assert result is True
        assert not template.exists()

    def test_returns_false_if_not_found(self, tmp_path):
        """Returns False if template doesn't exist."""
        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path / "prompt_groups"):
            result = groups.delete_template("my-group", "narrator", "nonexistent")

        assert result is False


class TestCreateGroup:
    """Tests for create_group()."""

    def test_cannot_create_reserved_names(self):
        """Cannot create groups with reserved names."""
        for name in ("default", "user", "scene"):
            with pytest.raises(ValueError, match="reserved"):
                groups.create_group(name)

    def test_creates_group_directory(self, tmp_path):
        """Creates group directory."""
        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path):
            info = groups.create_group("my-new-group")

        assert (tmp_path / "my-new-group").exists()
        assert info.name == "my-new-group"
        assert info.is_active is False
        assert info.is_readonly is False
        assert info.template_count == 0

    def test_cannot_create_existing_group(self, tmp_path):
        """Cannot create group that already exists."""
        (tmp_path / "existing").mkdir()

        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path):
            with pytest.raises(ValueError, match="already exists"):
                groups.create_group("existing")


class TestDeleteGroup:
    """Tests for delete_group()."""

    def test_cannot_delete_reserved_names(self):
        """Cannot delete groups with reserved names."""
        for name in ("default", "user", "scene"):
            with pytest.raises(ValueError, match="reserved"):
                groups.delete_group(name)

    def test_deletes_empty_group(self, tmp_path):
        """Deletes empty group directory."""
        (tmp_path / "my-group").mkdir()

        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path):
            result = groups.delete_group("my-group")

        assert result is True
        assert not (tmp_path / "my-group").exists()

    def test_requires_force_for_non_empty(self, tmp_path):
        """Requires force=True to delete non-empty group."""
        group_dir = tmp_path / "my-group" / "narrator"
        group_dir.mkdir(parents=True)
        (group_dir / "test.jinja2").write_text("content")

        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path):
            with pytest.raises(ValueError, match="contains"):
                groups.delete_group("my-group")

    def test_force_deletes_non_empty(self, tmp_path):
        """force=True deletes non-empty group."""
        group_dir = tmp_path / "my-group" / "narrator"
        group_dir.mkdir(parents=True)
        (group_dir / "test.jinja2").write_text("content")

        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path):
            result = groups.delete_group("my-group", force=True)

        assert result is True
        assert not (tmp_path / "my-group").exists()

    def test_raises_if_not_found(self, tmp_path):
        """Raises FileNotFoundError if group doesn't exist."""
        with patch.object(groups, "_CUSTOM_GROUPS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError):
                groups.delete_group("nonexistent")
