"""Unit tests for the help agent's permissions: what the chat may change, and
what it is handed when it may not."""

import pathlib
import re

import pytest

import talemate
import talemate.agents.help.settings as help_settings
import talemate.agents.help.storage as help_storage
import talemate.config.state as config_state
from conftest import MockClient, bootstrap_engine
from talemate.agents.help import HelpAgent

PROMPT = (
    pathlib.Path(talemate.__file__).parent
    / "prompts"
    / "templates"
    / "help"
    / "chat.jinja2"
)

SETTINGS_WRITES = {
    "update_agent_setting",
    "clear_agent_setting_scene_override",
    "update_app_config",
}
SETTINGS_READS = {"read_agent_settings", "read_app_config", "read_clients"}

TEMPLATE_WRITES = {
    "create_template",
    "update_template",
    "create_theme",
    "update_theme",
}
# applying a theme writes `config.appearance` as well as reading a template,
# so it answers to both permissions
BOTH_REQUIRED = {"apply_theme"}
TEMPLATE_READS = {
    "list_templates",
    "describe_template_type",
    "read_template",
    "list_themes",
    "read_theme",
}


@pytest.fixture
def help_agent(tmp_path, monkeypatch) -> HelpAgent:
    bootstrap_engine()
    monkeypatch.setattr(help_storage, "HELP_CHATS_DIR", tmp_path)
    monkeypatch.setattr(help_storage, "HELP_CHATS_FILE", tmp_path / "help.json")
    agent = HelpAgent(client=MockClient("test_client"))
    agent.scene = None
    return agent


def permit(agent: HelpAgent, **granted):
    for key, value in granted.items():
        agent.actions["permissions"].config[key].value = value


def tool_names(agent: HelpAgent) -> set[str]:
    callbacks = (
        agent._chat_settings_callbacks()
        + agent._chat_theme_callbacks()
        + agent._chat_template_callbacks()
    )
    return {callback.name for callback in callbacks}


class TestDefaults:
    def test_both_permissions_start_off(self, help_agent):
        assert help_agent.allow_settings_changes is False
        assert help_agent.allow_template_changes is False

    def test_the_section_carries_one_warning_for_both(self, help_agent):
        """The recommendation is the same for both switches, so it renders once
        on the section rather than under each of them."""
        action = help_agent.actions["permissions"]

        assert "reasoning model" in action.warning
        for key in ("allow_settings_changes", "allow_template_changes"):
            assert action.config[key].note is None

    def test_a_permission_is_not_scene_overridable(self, help_agent):
        """A scene file is shareable; what the agent may write to the
        installation is not a per-scene decision."""
        config = help_agent.actions["permissions"].config

        assert config["allow_settings_changes"].scene_overridable is False
        assert config["allow_template_changes"].scene_overridable is False


class TestTheChatChipsNameRealPermissions:
    """The chat renders one chip per entry of `PERMISSION_CHIPS` in
    `HelpChat.vue`. A key that no longer exists here would still render a chip,
    report "not allowed", and write a setting the backend ignores - so the two
    lists are pinned to each other rather than to a comment."""

    def _chip_keys(self) -> set[str]:
        source = (
            pathlib.Path(talemate.__file__).parent.parent.parent
            / "talemate_frontend"
            / "src"
            / "components"
            / "HelpChat.vue"
        ).read_text()
        block = re.search(r"const PERMISSION_CHIPS = \[(.*?)\];", source, re.DOTALL)
        assert block, "HelpChat.vue no longer declares PERMISSION_CHIPS"
        return set(re.findall(r"key:\s*'([a-z_]+)'", block.group(1)))

    def test_every_chip_names_a_permission_the_agent_has(self, help_agent):
        assert self._chip_keys() <= set(help_agent.actions["permissions"].config)

    def test_every_permission_has_a_chip(self, help_agent):
        """A permission the chat cannot show is one a user can only find in the
        settings, which is not what the chips are for."""
        assert set(help_agent.actions["permissions"].config) <= self._chip_keys()


class TestToolsAreAbsentNotRefused:
    """The whole matrix, not the diagonal: the mixed cells are where a tool
    ends up on the wrong side of a permission."""

    @pytest.mark.parametrize(
        "settings_on,templates_on",
        [(False, False), (True, False), (False, True), (True, True)],
    )
    def test_each_cell_holds_exactly_the_tools_it_should(
        self, help_agent, settings_on, templates_on
    ):
        permit(
            help_agent,
            allow_settings_changes=settings_on,
            allow_template_changes=templates_on,
        )
        names = tool_names(help_agent)

        assert SETTINGS_READS <= names
        assert TEMPLATE_READS <= names
        assert (SETTINGS_WRITES <= names) is settings_on
        assert not (SETTINGS_WRITES & names) or settings_on
        assert (TEMPLATE_WRITES <= names) is templates_on
        assert not (TEMPLATE_WRITES & names) or templates_on
        assert (BOTH_REQUIRED <= names) is (settings_on and templates_on)

    def test_applying_a_theme_takes_the_settings_permission_too(self, help_agent):
        """It rewrites every message color and style flag in the appearance
        settings, which is what the settings permission covers."""
        permit(help_agent, allow_template_changes=True)
        names = tool_names(help_agent)

        assert "update_theme" in names
        assert "apply_theme" not in names

    def test_the_settings_permission_alone_does_not_hand_over_apply_theme(
        self, help_agent
    ):
        permit(help_agent, allow_settings_changes=True)

        assert "apply_theme" not in tool_names(help_agent)


class TestARevocationReachesTheRoundInFlight:
    """The callbacks are built once per round and stay callable for the whole
    client request; a permission taken away in that window has to reach the
    call rather than only the next round."""

    def _tool(self, help_agent, name):
        callbacks = {
            callback.name: callback
            for callback in (
                help_agent._chat_settings_callbacks()
                + help_agent._chat_template_callbacks()
            )
        }
        return callbacks[name]

    async def test_a_settings_write_refuses_once_the_permission_is_gone(
        self, help_agent
    ):
        permit(help_agent, allow_settings_changes=True)
        callback = self._tool(help_agent, "update_app_config")

        permit(help_agent, allow_settings_changes=False)
        result = await callback.fn("game.general.auto_save", False)

        assert "was turned off while you were answering" in result

    async def test_a_template_write_refuses_once_the_permission_is_gone(
        self, help_agent
    ):
        permit(help_agent, allow_template_changes=True)
        callback = self._tool(help_agent, "create_template")

        permit(help_agent, allow_template_changes=False)
        result = await callback.fn(
            "character_attribute", "Bearing", "My Templates", {"attribute": "Bearing"}
        )

        assert "was turned off while you were answering" in result


class TestAMalformedPermissionReadsAsWithheld:
    """A permission gate is the place for a value of the wrong type to fail
    closed - a hand-edited config holding the string "false" is truthy."""

    @pytest.mark.parametrize("value", ["false", "", 0, 1, "true", None])
    def test_only_a_real_true_grants(self, help_agent, value):
        permit(help_agent, allow_settings_changes=value)

        assert help_agent.allow_settings_changes is (value is True)


class TestTheAgentCannotGrantItself:
    """A settings permission that could grant the template permission - or
    re-grant itself after the user revoked it - is not a permission."""

    async def test_writing_its_own_permissions_is_refused(self):
        result = await help_settings.update_agent_setting(
            "help", "permissions", "allow_template_changes", True
        )

        assert "not yours to change" in result

    async def test_clearing_a_scene_override_on_them_is_refused(self):
        result = await help_settings.clear_agent_setting_scene_override(
            "help", "permissions", "allow_settings_changes"
        )

        assert "not yours to change" in result

    async def test_another_agent_action_is_untouched_by_the_guard(self, help_agent):
        config_state.CONFIG_FILE.unlink(missing_ok=True)
        result = await help_settings.update_agent_setting(
            "help", "chat", "response_length", 2048
        )

        assert result["applied"] is True
        assert config_state.CONFIG_FILE.is_file()


class TestThePromptSaysWhichPermissionToEnable:
    def test_the_rules_name_the_permission_and_where_it_lives(self):
        text = PROMPT.read_text()

        assert '"Allow changes to settings"' in text
        assert '"Allow changes to templates"' in text
        assert "talemate://agent-settings/help/permissions" in text

    def test_the_write_tools_are_rendered_behind_the_permissions(self):
        text = PROMPT.read_text()

        for name in ("update_agent_setting", "update_app_config"):
            assert f"focal.callbacks.{name}.render" in text
        assert "{% if allow_settings_changes %}" in text
        assert "{% if allow_template_changes %}" in text
