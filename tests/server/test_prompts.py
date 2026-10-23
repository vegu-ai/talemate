"""
Unit tests for WebSocket prompts handler.

Tests the PromptsPlugin handlers for template management API.
"""

import pytest
from unittest.mock import ANY, Mock, patch, MagicMock, AsyncMock

from talemate.prompts.compatibility import OverrideStatus
from talemate.prompts.groups import MissingMarker
from talemate.server.prompts import (
    PromptsPlugin,
    parse_template_uid,
    validate_jinja2_syntax,
)
from talemate.tale_mate import Scene


class TestParseTemplateUid:
    """Tests for parse_template_uid helper."""

    def test_parses_valid_uid(self):
        """Parses agent.template_name format correctly."""
        agent, name = parse_template_uid("narrator.narrate-scene")
        assert agent == "narrator"
        assert name == "narrate-scene"

    def test_handles_multiple_dots(self):
        """Handles template names with dots."""
        agent, name = parse_template_uid("narrator.my.template.name")
        assert agent == "narrator"
        assert name == "my.template.name"

    def test_raises_on_invalid_format(self):
        """Raises ValueError on invalid UID format."""
        with pytest.raises(ValueError, match="Invalid template UID"):
            parse_template_uid("no-dot-here")


class TestValidateJinja2Syntax:
    """Tests for validate_jinja2_syntax helper."""

    def test_valid_template(self):
        """Returns True for valid Jinja2 syntax."""
        valid, errors = validate_jinja2_syntax("Hello {{ name }}!")
        assert valid is True
        assert errors == []

    def test_invalid_template(self):
        """Returns False with errors for invalid syntax."""
        valid, errors = validate_jinja2_syntax("Hello {{ name }!")
        assert valid is False
        assert len(errors) > 0

    def test_complex_valid_template(self):
        """Handles complex valid templates."""
        template = """
        {% for item in items %}
            {{ item.name }}: {{ item.value }}
        {% endfor %}
        """
        valid, errors = validate_jinja2_syntax(template)
        assert valid is True
        assert errors == []

    def test_unclosed_block(self):
        """Detects unclosed blocks."""
        valid, errors = validate_jinja2_syntax("{% for x in y %}")
        assert valid is False
        assert len(errors) > 0


class MockWebsocketHandler:
    """Mock websocket handler for testing."""

    def __init__(self, scene=None):
        self._scene = scene
        self.messages = []

    @property
    def scene(self):
        return self._scene

    def queue_put(self, data):
        self.messages.append(data)


class TestPromptsPluginListGroups:
    """Tests for handle_list_groups handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_lists_groups_without_scene(self, plugin, tmp_path):
        """Lists groups when no scene is loaded."""
        mock_groups = [
            Mock(
                name="user",
                is_active=True,
                is_readonly=False,
                template_count=5,
                path=str(tmp_path / "user"),
                model_dump=lambda: {
                    "name": "user",
                    "is_active": True,
                    "is_readonly": False,
                    "template_count": 5,
                    "path": str(tmp_path / "user"),
                },
            ),
            Mock(
                name="default",
                is_active=True,
                is_readonly=True,
                template_count=100,
                path=str(tmp_path / "default"),
                model_dump=lambda: {
                    "name": "default",
                    "is_active": True,
                    "is_readonly": True,
                    "template_count": 100,
                    "path": str(tmp_path / "default"),
                },
            ),
        ]

        with patch("talemate.server.prompts.list_groups", return_value=mock_groups):
            await plugin.handle_list_groups({})

        assert len(plugin.websocket_handler.messages) == 1
        response = plugin.websocket_handler.messages[0]
        assert response["type"] == "prompts"
        assert response["action"] == "list_groups"
        assert response["data"]["scene_loaded"] is False
        assert len(response["data"]["groups"]) == 2

    @pytest.mark.asyncio
    async def test_lists_groups_with_scene(self, tmp_path):
        """Lists groups when scene is loaded."""
        # Real ``Scene`` — ``handle_list_groups`` reads ``scene.name`` to decide
        # whether scene context is loaded (truthy => scene_loaded True), then
        # delegates to the patched ``list_groups``. ``template_dir`` is never
        # touched here because ``list_groups`` itself is patched out.
        scene = Scene()
        scene.name = "test-scene"

        handler = MockWebsocketHandler(scene=scene)
        plugin = PromptsPlugin(handler)

        # Create mock groups - need to use MagicMock and configure_mock for 'name'
        # because Mock uses 'name' internally
        scene_group_mock = MagicMock()
        scene_group_mock.configure_mock(name="scene")
        scene_group_mock.is_active = True
        scene_group_mock.is_readonly = False
        scene_group_mock.template_count = 2
        scene_group_mock.path = str(tmp_path)
        scene_group_mock.model_dump = lambda: {
            "name": "scene",
            "is_active": True,
            "is_readonly": False,
            "template_count": 2,
            "path": str(tmp_path),
        }

        user_group_mock = MagicMock()
        user_group_mock.configure_mock(name="user")
        user_group_mock.is_active = True
        user_group_mock.is_readonly = False
        user_group_mock.template_count = 5
        user_group_mock.path = str(tmp_path / "user")
        user_group_mock.model_dump = lambda: {
            "name": "user",
            "is_active": True,
            "is_readonly": False,
            "template_count": 5,
            "path": str(tmp_path / "user"),
        }

        mock_groups = [scene_group_mock, user_group_mock]

        with patch("talemate.server.prompts.list_groups", return_value=mock_groups):
            await plugin.handle_list_groups({})

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["scene_loaded"] is True
        # Scene group should have is_scene flag
        scene_group = next(
            g for g in response["data"]["groups"] if g["name"] == "scene"
        )
        assert scene_group["is_scene"] is True


class TestPromptsPluginCreateGroup:
    """Tests for handle_create_group handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_creates_group_successfully(self, plugin, tmp_path):
        """Creates a new group successfully."""
        mock_group = Mock(
            name="my-new-group",
            is_active=False,
            is_readonly=False,
            template_count=0,
            path=str(tmp_path),
            model_dump=lambda: {
                "name": "my-new-group",
                "is_active": False,
                "is_readonly": False,
                "template_count": 0,
                "path": str(tmp_path),
            },
        )

        with patch("talemate.server.prompts.create_group", return_value=mock_group):
            await plugin.handle_create_group({"name": "my-new-group"})

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True
        assert response["data"]["group"]["name"] == "my-new-group"

    @pytest.mark.asyncio
    async def test_handles_reserved_name_error(self, plugin):
        """Handles error when trying to create reserved group name."""
        with patch(
            "talemate.server.prompts.create_group",
            side_effect=ValueError("Cannot create reserved"),
        ):
            await plugin.handle_create_group({"name": "default"})

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is False
        assert "error" in response["data"]


class TestPromptsPluginDeleteGroup:
    """Tests for handle_delete_group handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_deletes_group_successfully(self, plugin):
        """Deletes a group successfully."""
        mock_config = Mock()
        mock_config.prompts.group_priority = ["user"]
        mock_config.set_dirty = AsyncMock()

        with patch("talemate.server.prompts.delete_group", return_value=True):
            with patch("talemate.server.prompts.get_config", return_value=mock_config):
                await plugin.handle_delete_group({"name": "my-group", "force": True})

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_removes_from_priority_on_delete(self, plugin):
        """Removes deleted group from priority list."""
        mock_config = Mock()
        mock_config.prompts.group_priority = ["user", "my-group"]
        mock_config.set_dirty = AsyncMock()

        with patch("talemate.server.prompts.delete_group", return_value=True):
            with patch("talemate.server.prompts.get_config", return_value=mock_config):
                await plugin.handle_delete_group({"name": "my-group"})

        assert "my-group" not in mock_config.prompts.group_priority
        mock_config.set_dirty.assert_called_once()


class TestPromptsPluginSetGroupPriority:
    """Tests for handle_set_group_priority handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_sets_priority_order(self, plugin):
        """Sets group priority order."""
        mock_config = Mock()
        mock_config.prompts.group_priority = []
        mock_config.set_dirty = AsyncMock()

        with patch("talemate.server.prompts.get_config", return_value=mock_config):
            await plugin.handle_set_group_priority({"priority": ["user", "my-group"]})

        assert mock_config.prompts.group_priority == ["user", "my-group"]
        mock_config.set_dirty.assert_called_once()
        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True


class TestPromptsPluginListTemplates:
    """Tests for handle_list_templates handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_lists_all_templates(self, plugin):
        """Lists all templates with source info."""
        mock_templates = [
            Mock(
                uid="narrator.narrate-scene",
                agent="narrator",
                name="narrate-scene",
                source_group="default",
                available_in=["default", "user"],
                model_dump=lambda: {
                    "uid": "narrator.narrate-scene",
                    "agent": "narrator",
                    "name": "narrate-scene",
                    "source_group": "default",
                    "available_in": ["default", "user"],
                },
            ),
        ]

        with patch(
            "talemate.server.prompts.list_templates", return_value=mock_templates
        ):
            await plugin.handle_list_templates({})

        response = plugin.websocket_handler.messages[0]
        assert response["type"] == "prompts"
        assert response["action"] == "list_templates"
        assert len(response["data"]["templates"]) == 1
        assert response["data"]["templates"][0]["uid"] == "narrator.narrate-scene"


class TestPromptsPluginListGroupTemplates:
    """Tests for handle_list_group_templates handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_lists_templates_for_group(self, plugin):
        """Lists templates showing which exist in specific group."""
        mock_templates = [
            Mock(
                uid="narrator.narrate-scene",
                agent="narrator",
                available_in=["default", "user"],
                model_dump=lambda: {
                    "uid": "narrator.narrate-scene",
                    "available_in": ["default", "user"],
                },
            ),
            Mock(
                uid="narrator.other-template",
                agent="narrator",
                available_in=["default"],
                model_dump=lambda: {
                    "uid": "narrator.other-template",
                    "available_in": ["default"],
                },
            ),
        ]

        mock_templates[0].name = "narrate-scene"
        status = OverrideStatus(
            has_default=True,
            compatibility="incomplete",
            missing_markers=[MissingMarker(kind="flag", name="perspective")],
        )

        with (
            patch(
                "talemate.server.prompts.list_templates", return_value=mock_templates
            ),
            patch(
                "talemate.server.prompts.override_status", return_value=status
            ) as mock_status,
        ):
            await plugin.handle_list_group_templates({"group": "user"})

        mock_status.assert_called_once_with(
            "user", "narrator", "narrate-scene", None, ANY
        )
        response = plugin.websocket_handler.messages[0]
        templates = response["data"]["templates"]
        assert len(templates) == 2

        narrate_scene = next(
            t for t in templates if t["uid"] == "narrator.narrate-scene"
        )
        other_template = next(
            t for t in templates if t["uid"] == "narrator.other-template"
        )

        assert narrate_scene["exists"] is True  # exists in user
        assert other_template["exists"] is False  # doesn't exist in user
        # status of the user copy, not of whichever copy resolves
        assert narrate_scene["compatibility"] == "incomplete"
        assert narrate_scene["missing_markers"] == [
            {"kind": "flag", "name": "perspective", "detail": None}
        ]
        assert "compatibility" not in other_template


class TestPromptsPluginGetTemplate:
    """Tests for handle_get_template handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_gets_template_from_specific_group(self, plugin):
        """Gets template content from specified group."""
        with patch(
            "talemate.server.prompts.get_template_content",
            return_value="template content",
        ):
            await plugin.handle_get_template({"uid": "narrator.test", "group": "user"})

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["content"] == "template content"
        assert response["data"]["group"] == "user"
        assert response["data"]["readonly"] is False

    @pytest.mark.asyncio
    async def test_default_group_is_readonly(self, plugin):
        """Default group templates are marked readonly."""
        with patch(
            "talemate.server.prompts.get_template_content",
            return_value="template content",
        ):
            await plugin.handle_get_template(
                {"uid": "narrator.test", "group": "default"}
            )

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["readonly"] is True

    @pytest.mark.asyncio
    async def test_resolves_template_when_no_group(self, plugin, tmp_path):
        """Resolves template when no group specified."""
        mock_path = tmp_path / "test.jinja2"
        mock_path.write_text("resolved content")

        with patch(
            "talemate.server.prompts.resolve_template",
            return_value=(mock_path, "default"),
        ):
            await plugin.handle_get_template({"uid": "narrator.test"})

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["content"] == "resolved content"
        assert response["data"]["readonly"] is True

    @pytest.mark.asyncio
    async def test_includes_override_status(self, plugin):
        """The reply carries the group copy's status against the default."""
        status = OverrideStatus(
            has_default=True,
            is_outdated=True,
            compatibility="incomplete",
            missing_markers=[MissingMarker(kind="include", name="x.jinja2")],
        )
        with (
            patch(
                "talemate.server.prompts.get_template_content",
                return_value="template content",
            ),
            patch(
                "talemate.server.prompts.override_status", return_value=status
            ) as mock_status,
        ):
            await plugin.handle_get_template({"uid": "narrator.test", "group": "user"})

        mock_status.assert_called_once_with("user", "narrator", "test", None)
        response = plugin.websocket_handler.messages[0]
        assert response["data"]["status"] == status.model_dump()

    @pytest.mark.asyncio
    async def test_handles_not_found(self, plugin):
        """Handles template not found."""
        with patch("talemate.server.prompts.get_template_content", return_value=None):
            await plugin.handle_get_template(
                {"uid": "narrator.nonexistent", "group": "user"}
            )

        response = plugin.websocket_handler.messages[0]
        assert "error" in response["data"]
        assert response["data"]["uid"] == "narrator.nonexistent"
        assert response["data"]["group"] == "user"


class TestPromptsPluginSaveTemplate:
    """Tests for handle_save_template handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_saves_template_successfully(self, plugin):
        """Saves template content successfully."""
        with patch("talemate.server.prompts.write_template") as mock_write:
            await plugin.handle_save_template(
                {
                    "uid": "narrator.test",
                    "group": "user",
                    "content": "new content {{ var }}",
                }
            )

        mock_write.assert_called_once()
        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True
        assert response["data"]["syntax_valid"] is True
        assert response["data"]["uid"] == "narrator.test"
        assert response["data"]["group"] == "user"
        assert response["data"]["status"]["has_default"] is False

    @pytest.mark.asyncio
    async def test_reports_syntax_errors(self, plugin):
        """Reports syntax errors but still saves."""
        with patch("talemate.server.prompts.write_template") as mock_write:
            await plugin.handle_save_template(
                {"uid": "narrator.test", "group": "user", "content": "invalid {{ var"}
            )

        mock_write.assert_called_once()  # Still saved
        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True
        assert response["data"]["syntax_valid"] is False
        assert len(response["data"]["syntax_errors"]) > 0

    @pytest.mark.asyncio
    async def test_handles_write_error(self, plugin):
        """Handles error when writing template."""
        with patch(
            "talemate.server.prompts.write_template",
            side_effect=ValueError("Cannot write to default"),
        ):
            await plugin.handle_save_template(
                {"uid": "narrator.test", "group": "default", "content": "content"}
            )

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is False
        assert "error" in response["data"]


class TestPromptsPluginDeleteTemplate:
    """Tests for handle_delete_template handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_deletes_template_successfully(self, plugin):
        """Deletes template override successfully."""
        with patch("talemate.server.prompts.delete_template", return_value=True):
            await plugin.handle_delete_template(
                {"uid": "narrator.test", "group": "user"}
            )

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True
        assert response["data"]["uid"] == "narrator.test"
        assert response["data"]["group"] == "user"

    @pytest.mark.asyncio
    async def test_handles_not_found(self, plugin):
        """Handles template not found."""
        with patch("talemate.server.prompts.delete_template", return_value=False):
            await plugin.handle_delete_template(
                {"uid": "narrator.nonexistent", "group": "user"}
            )

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is False
        assert response["data"]["error"] == "Template not found"
        assert response["data"]["uid"] == "narrator.nonexistent"


class TestPromptsPluginCreateTemplate:
    """Tests for handle_create_template handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_creates_new_template(self, plugin):
        """Creates a new template file."""
        with patch("talemate.server.prompts.get_template_content", return_value=None):
            with patch("talemate.server.prompts.write_template") as mock_write:
                await plugin.handle_create_template(
                    {
                        "uid": "narrator.my-helper",
                        "group": "user",
                        "content": "helper content",
                    }
                )

        mock_write.assert_called_once()
        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_cannot_create_in_default(self, plugin):
        """Cannot create template in default group."""
        await plugin.handle_create_template(
            {"uid": "narrator.test", "group": "default", "content": "content"}
        )

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is False
        assert "default" in response["data"]["error"]

    @pytest.mark.asyncio
    async def test_cannot_create_existing(self, plugin):
        """Cannot create template that already exists."""
        with patch(
            "talemate.server.prompts.get_template_content",
            return_value="existing content",
        ):
            await plugin.handle_create_template(
                {"uid": "narrator.existing", "group": "user", "content": "new content"}
            )

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is False
        assert "already exists" in response["data"]["error"]


class _TemplateDirScene(Scene):
    template_dir = None

    def __init__(self, template_dir):
        super().__init__()
        self.name = "test-scene"
        self.template_dir = str(template_dir)


class TestPromptsPluginSceneGroupFiles:
    """Root-level scene files (agent "") against agent subfolders."""

    @pytest.fixture
    def plugin(self, tmp_path):
        handler = MockWebsocketHandler(scene=_TemplateDirScene(tmp_path))
        return PromptsPlugin(handler)

    async def _call(self, plugin, name, **data):
        plugin.websocket_handler.messages.clear()
        await getattr(plugin, f"handle_{name}")(data)
        return plugin.websocket_handler.messages[0]["data"]

    @pytest.mark.asyncio
    async def test_empty_agent_creates_a_root_level_file(self, plugin, tmp_path):
        reply = await self._call(
            plugin,
            "create_template",
            uid=".scene-include",
            group="scene",
            content="{# new #}",
        )

        assert reply["success"] is True
        assert (tmp_path / "scene-include.jinja2").read_text() == "{# new #}"
        assert not (tmp_path / "scene").exists()

    @pytest.mark.asyncio
    async def test_an_agent_category_creates_in_its_subfolder(self, plugin, tmp_path):
        reply = await self._call(
            plugin,
            "create_template",
            uid="director.scene-override",
            group="scene",
            content="{# new #}",
        )

        assert reply["success"] is True
        assert (tmp_path / "director" / "scene-override.jinja2").exists()
        assert not (tmp_path / "scene-override.jinja2").exists()

    @pytest.mark.asyncio
    async def test_root_level_file_opens_saves_and_deletes(self, plugin, tmp_path):
        uid = ".scene-include"
        await self._call(
            plugin, "create_template", uid=uid, group="scene", content="first"
        )

        opened = await self._call(plugin, "get_template", uid=uid, group="scene")
        assert opened["content"] == "first"
        assert opened["group"] == "scene"
        assert opened["readonly"] is False

        saved = await self._call(
            plugin, "save_template", uid=uid, group="scene", content="second"
        )
        assert saved["success"] is True
        assert (tmp_path / "scene-include.jinja2").read_text() == "second"

        deleted = await self._call(plugin, "delete_template", uid=uid, group="scene")
        assert deleted["success"] is True
        assert not (tmp_path / "scene-include.jinja2").exists()

    @pytest.mark.asyncio
    async def test_root_level_file_is_listed_with_an_empty_agent(
        self, plugin, tmp_path
    ):
        await self._call(
            plugin, "create_template", uid=".scene-include", group="scene", content="x"
        )

        listed = await self._call(plugin, "list_templates")

        [template] = [t for t in listed["templates"] if t["name"] == "scene-include"]
        assert template["agent"] == ""
        assert template["uid"] == ".scene-include"
        assert template["available_in"] == ["scene"]


class TestPromptsPluginSetTemplateSource:
    """Tests for handle_set_template_source handler."""

    @pytest.fixture
    def plugin(self):
        handler = MockWebsocketHandler()
        return PromptsPlugin(handler)

    @pytest.mark.asyncio
    async def test_sets_explicit_source(self, plugin):
        """Sets explicit source for template."""
        mock_config = Mock()
        mock_config.prompts.template_sources = {}
        mock_config.set_dirty = AsyncMock()

        with patch("talemate.server.prompts.get_config", return_value=mock_config):
            with patch(
                "talemate.server.prompts.get_template_content", return_value="content"
            ):
                await plugin.handle_set_template_source(
                    {"uid": "narrator.test", "group": "my-custom"}
                )

        assert mock_config.prompts.template_sources["narrator.test"] == "my-custom"
        mock_config.set_dirty.assert_called_once()
        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_removes_override_with_null_group(self, plugin):
        """Removes override when group is null."""
        mock_config = Mock()
        mock_config.prompts.template_sources = {"narrator.test": "my-custom"}
        mock_config.set_dirty = AsyncMock()

        with patch("talemate.server.prompts.get_config", return_value=mock_config):
            await plugin.handle_set_template_source(
                {"uid": "narrator.test", "group": None}
            )

        assert "narrator.test" not in mock_config.prompts.template_sources
        mock_config.set_dirty.assert_called_once()

    @pytest.mark.asyncio
    async def test_validates_template_exists_in_group(self, plugin):
        """Validates template exists in target group before setting source."""
        mock_config = Mock()
        mock_config.prompts.template_sources = {}
        mock_config.set_dirty = AsyncMock()

        with patch("talemate.server.prompts.get_config", return_value=mock_config):
            with patch(
                "talemate.server.prompts.get_template_content", return_value=None
            ):
                await plugin.handle_set_template_source(
                    {"uid": "narrator.test", "group": "nonexistent-group"}
                )

        response = plugin.websocket_handler.messages[0]
        assert response["data"]["success"] is False
        assert "not found" in response["data"]["error"]
