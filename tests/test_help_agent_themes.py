"""
Unit tests for `talemate.agents.help.themes`, the theme tools the help chat
calls.

Covers:
- the read tools: the theme list with its group, lock and active markers, and
  the full read of one theme
- `create_theme`: seeding every slot from the base theme, creating the group it
  names, and the refusals (shipped group, duplicate name, invalid name)
- `update_theme`: patching only what was named, and refusing a shipped theme
  with the copy route
- `apply_theme`: the config write and the styling copied into the appearance
  settings
- the unsaved-edit refusals driven by the UX snapshot
- the websocket pushes that carry a theme write to the running frontend
"""

import json
import os
import pathlib

import pytest

import talemate

import talemate.agents.help.storage as help_storage
import talemate.agents.help.themes as help_themes
import talemate.config.state as config_state
import talemate.world_state.templates as world_state_templates
from conftest import (
    MockClient,
    MockClientContext,
    MockScene,
    bootstrap_engine,
    client_responses,
)
from talemate.agents.help import HelpAgent
from talemate.agents.help.websocket_handler import HelpWebsocketHandler
from talemate.config.schema import Config
from talemate.world_state.templates.base import (
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
)
from talemate.util.colors import contrast_ratio, describe_color
from talemate.world_state.templates.theme import (
    Theme,
    invalidate_theme_cache,
)

SHIPPED_THEMES_PATH = os.path.join(TEMPLATE_PATH_TALEMATE, "themes.yaml")
SHIPPED_GROUP = "Themes"
USER_GROUP = "My Themes"


class MockWebsocketHandler:
    """Stand-in for `WebsocketHandler` - the theme pushes only need these."""

    def __init__(self, scene):
        self.scene = scene
        self.messages: list[dict] = []

    def queue_put(self, data: dict):
        self.messages.append(data)

    @property
    def actions(self) -> list[str]:
        return [message.get("action", message["type"]) for message in self.messages]

    def find(self, action: str) -> dict | None:
        for message in self.messages:
            if message.get("action", message["type"]) == action:
                return message
        return None


def theme_id(template: Theme) -> str:
    return f"{template.group}__{template.uid}"


@pytest.fixture
def shipped_dir(template_dir) -> str:
    path = os.path.join(template_dir, "talemate")
    os.makedirs(path)
    return path


@pytest.fixture
def config(monkeypatch, tmp_path, template_dir, shipped_dir, isolate_signals) -> Config:
    """A throwaway app config plus a template directory of the test's own.

    Both the group files the tools write and the shipped directory they refuse
    to write into are redirected into the test's directory, so nothing here
    touches the installation's templates.
    """
    isolate_signals("config.changed", "config.changed.follow", "config.saved")

    # `resolve_theme` loads the collection itself, with no path - it has to
    # find the test's themes rather than the installation's
    load_collection = Collection.load

    def _load(path: str = template_dir):
        return load_collection(path)

    monkeypatch.setattr(Collection, "load", _load)

    original = config_state.CONFIG
    cfg = Config()
    cfg.dirty = False
    config_state.CONFIG = cfg
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(world_state_templates, "TEMPLATE_PATH", template_dir)
    monkeypatch.setattr(help_themes, "TEMPLATE_PATH_TALEMATE", shipped_dir)
    invalidate_theme_cache()

    yield cfg

    config_state.CONFIG = original
    invalidate_theme_cache()


@pytest.fixture
def shipped_theme() -> Theme:
    return Theme(
        name="Talemate Dark", locked=True, colors={"app": {"primary": "#9575CD"}}
    )


@pytest.fixture
def user_theme() -> Theme:
    return Theme(name="Midnight", colors={"app": {"primary": "#123456"}})


@pytest.fixture
def scene(config, template_dir, shipped_dir, shipped_theme, user_theme) -> MockScene:
    """A scene whose template collection holds a shipped and a user group."""
    shipped = Group(author="Talemate", name=SHIPPED_GROUP, description="")
    shipped.insert_template(shipped_theme, save=False)
    shipped.path = os.path.join(shipped_dir, "themes.yaml")
    shipped.save()

    user = Group(author="You", name=USER_GROUP, description="")
    user.insert_template(user_theme, save=False)
    user.save(template_dir)

    scene = MockScene()
    scene._world_state_templates = Collection(groups=[shipped, user])
    config.appearance.theme = theme_id(shipped_theme)
    return scene


@pytest.fixture
def help_agent(tmp_path, monkeypatch, scene) -> HelpAgent:
    # focal reaches for the director agent to log its calls
    bootstrap_engine()
    monkeypatch.setattr(help_storage, "HELP_CHATS_DIR", tmp_path)
    monkeypatch.setattr(help_storage, "HELP_CHATS_FILE", tmp_path / "help.json")
    agent = HelpAgent(client=MockClient("test_client"))
    agent.scene = scene
    return agent


def created_theme(scene, name: str) -> Theme:
    for group in scene._world_state_templates.groups:
        for template in group.templates.values():
            if template.name == name:
                return template
    raise AssertionError(f"no theme named {name}")


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


class TestListThemes:
    def test_lists_every_theme_with_its_group(self, scene, shipped_theme, user_theme):
        listed = help_themes.list_themes(scene)

        assert {entry["name"] for entry in listed} == {"Talemate Dark", "Midnight"}
        assert {entry["group"] for entry in listed} == {SHIPPED_GROUP, USER_GROUP}

    def test_marks_the_shipped_theme_locked_and_the_active_one_active(
        self, scene, shipped_theme
    ):
        listed = {entry["name"]: entry for entry in help_themes.list_themes(scene)}

        assert listed["Talemate Dark"]["active"] is True
        assert "locked" in listed["Talemate Dark"]
        assert listed["Midnight"]["active"] is False
        assert "locked" not in listed["Midnight"]

    def test_says_so_when_there_are_no_themes(self, config, scene):
        scene._world_state_templates = Collection(groups=[])

        assert help_themes.list_themes(scene) == "No theme templates exist yet."


class TestReadTheme:
    def test_returns_every_slot(self, scene, user_theme):
        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert payload["name"] == "Midnight"
        assert payload["colors"]["app"]["primary"] == "#123456"
        slots = sum(len(group) for group in payload["colors"].values())
        assert slots == 51
        assert payload["appearance"]["narrator"] == {"italic": False, "bold": False}
        assert payload["code_editor"] == "one-dark"

    def test_resolves_a_theme_by_name(self, scene, user_theme):
        assert help_themes.read_theme(scene, "midnight")["id"] == theme_id(user_theme)

    def test_unknown_theme_lists_the_known_ones(self, scene):
        result = help_themes.read_theme(scene, "Nocturne")

        assert "No theme 'Nocturne'" in result
        assert "Midnight" in result


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreateTheme:
    async def test_seeds_every_slot_from_the_active_theme(self, scene, shipped_theme):
        result = await help_themes.create_theme(
            scene,
            "Solarized Dark",
            USER_GROUP,
            colors={"surfaces": {"background": "#002B36"}},
        )

        assert result["created"] is True
        assert result["based_on"] == "Talemate Dark"

        theme = created_theme(scene, "Solarized Dark")
        assert theme.colors.surfaces.background == "#002B36"
        # everything the call did not name still comes from the base theme
        assert theme.colors.app.primary == shipped_theme.colors.app.primary
        assert theme.colors.messages == shipped_theme.colors.messages

    async def test_copies_a_named_base_theme(self, scene, user_theme):
        await help_themes.create_theme(
            scene, "Midnight Warm", USER_GROUP, base_theme=theme_id(user_theme)
        )

        assert created_theme(scene, "Midnight Warm").colors.app.primary == "#123456"

    async def test_creates_the_group_it_names(self, scene, template_dir):
        result = await help_themes.create_theme(scene, "Aurora", "Palettes")

        assert result["group_created"] is True
        assert result["group"] == "Palettes"
        assert os.path.exists(os.path.join(template_dir, "palettes.yaml"))
        assert created_theme(scene, "Aurora").group != ""

    async def test_writes_the_theme_to_the_group_file(self, scene, template_dir):
        await help_themes.create_theme(
            scene, "Aurora", USER_GROUP, colors={"app": {"primary": "#00FF00"}}
        )

        reloaded = Collection.load(template_dir)
        names = {
            template.name
            for group in reloaded.groups
            for template in group.templates.values()
        }
        assert "Aurora" in names

    async def test_new_theme_is_not_locked_and_not_favorite(self, scene):
        await help_themes.create_theme(scene, "Aurora", USER_GROUP)

        theme = created_theme(scene, "Aurora")
        assert theme.locked is False
        assert theme.favorite is False

    async def test_refuses_the_shipped_group(self, scene):
        result = await help_themes.create_theme(scene, "Aurora", SHIPPED_GROUP)

        assert "ships with Talemate" in result
        assert len(scene._world_state_templates.groups) == 2

    async def test_refuses_a_duplicate_name(self, scene):
        result = await help_themes.create_theme(scene, "Midnight", USER_GROUP)

        assert "already holds a theme called 'Midnight'" in result

    async def test_refuses_a_name_the_templates_tab_would_reject(self, scene):
        result = await help_themes.create_theme(scene, "Solarized/Dark", USER_GROUP)

        assert "letters, digits, spaces and underscores" in result

    async def test_refuses_a_group_name_that_is_not_a_filename(self, scene):
        result = await help_themes.create_theme(scene, "Aurora", "../escape")

        assert "not a valid template group name" in result

    @pytest.mark.parametrize(
        "colors,expected",
        [
            ({"appp": {"primary": "#123456"}}, "Unknown color group 'appp'"),
            ({"app": {"primaries": "#123456"}}, "Unknown slot 'primaries'"),
            ({"app": {"primary": "green"}}, "Invalid value for 'colors.app.primary'"),
        ],
    )
    async def test_rejects_a_bad_color_payload(self, scene, colors, expected):
        result = await help_themes.create_theme(
            scene, "Aurora", USER_GROUP, colors=colors
        )

        assert expected in result

    async def test_rejects_an_unknown_appearance_flag(self, scene):
        result = await help_themes.create_theme(
            scene, "Aurora", USER_GROUP, appearance={"narrator": {"underline": True}}
        )

        assert "has no style flag 'underline'" in result


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdateTheme:
    async def test_patches_only_the_named_slots(self, scene, user_theme):
        before = user_theme.colors.messages.actor

        result = await help_themes.update_theme(
            scene, theme_id(user_theme), colors={"messages": {"narrator": "#8FBC8F"}}
        )

        assert result["updated"] is True
        assert result["changes"] == {
            "colors.messages.narrator": {
                "previous": "#A180AE",
                "new": "#8FBC8F",
            }
        }
        theme = created_theme(scene, "Midnight")
        assert theme.colors.messages.narrator == "#8FBC8F"
        assert theme.colors.messages.actor == before

    async def test_changes_styling_mode_and_code_editor(self, scene, user_theme):
        result = await help_themes.update_theme(
            scene,
            theme_id(user_theme),
            appearance={"narrator": {"italic": True}},
            dark=False,
            code_editor="solarized-light",
        )

        assert set(result["changes"]) == {
            "appearance.narrator.italic",
            "dark",
            "code_editor",
        }
        theme = created_theme(scene, "Midnight")
        assert theme.appearance.narrator.italic is True
        assert theme.dark is False
        assert theme.code_editor == "solarized-light"

    async def test_a_styling_change_on_the_active_theme_says_it_needs_an_apply(
        self, scene, config, user_theme
    ):
        """Colors resolve live, styling does not - it reaches the app only when
        a theme is applied, so reporting the change alone would be a change the
        user cannot see."""
        config.appearance.theme = theme_id(user_theme)

        result = await help_themes.update_theme(
            scene, theme_id(user_theme), appearance={"narrator": {"italic": True}}
        )

        assert result["active"] is True
        assert "applied" in result["styling_not_live"]

    async def test_a_color_change_on_the_active_theme_carries_no_such_note(
        self, scene, config, user_theme
    ):
        config.appearance.theme = theme_id(user_theme)

        result = await help_themes.update_theme(
            scene, theme_id(user_theme), colors={"app": {"primary": "#FF0000"}}
        )

        assert "styling_not_live" not in result

    async def test_styling_on_an_inactive_theme_carries_no_note(
        self, scene, config, user_theme
    ):
        result = await help_themes.update_theme(
            scene, theme_id(user_theme), appearance={"narrator": {"italic": True}}
        )

        assert result["active"] is False
        assert "styling_not_live" not in result

    async def test_reports_when_nothing_changed(self, scene, user_theme):
        result = await help_themes.update_theme(
            scene, theme_id(user_theme), colors={"app": {"primary": "#123456"}}
        )

        assert "already holds those values" in result

    async def test_refuses_a_locked_theme_and_offers_the_copy(
        self, scene, shipped_theme
    ):
        result = await help_themes.update_theme(
            scene, theme_id(shipped_theme), colors={"app": {"primary": "#FF0000"}}
        )

        assert "ships with Talemate" in result
        assert "create_theme" in result
        assert shipped_theme.colors.app.primary == "#9575CD"

    async def test_rejects_an_unknown_code_editor(self, scene, user_theme):
        result = await help_themes.update_theme(
            scene, theme_id(user_theme), code_editor="dracula"
        )

        assert "Unknown code editor scheme 'dracula'" in result


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


class TestApplyTheme:
    async def test_activates_the_theme(self, scene, config, user_theme):
        result = await help_themes.apply_theme(scene, theme_id(user_theme))

        assert result["applied"] is True
        assert config.appearance.theme == theme_id(user_theme)

    async def test_copies_the_styling_into_the_appearance_settings(
        self, scene, config, user_theme
    ):
        user_theme.appearance.narrator.italic = True

        await help_themes.apply_theme(scene, theme_id(user_theme))

        assert config.appearance.scene.narrator_messages.italic is True

    async def test_unknown_theme_is_refused(self, scene, config):
        result = await help_themes.apply_theme(scene, "nope__nope")

        assert "No theme 'nope__nope'" in result
        assert config.appearance.theme != "nope__nope"


# ---------------------------------------------------------------------------
# unsaved-edit refusals
# ---------------------------------------------------------------------------


class TestUnsavedEditRefusals:
    async def test_create_is_refused_while_the_templates_tab_is_dirty(self, scene):
        result = await help_themes.create_theme(
            scene, "Aurora", USER_GROUP, templates_dirty=True
        )

        assert "Templates tab has an unsaved theme edit" in result
        assert len(scene._world_state_templates.groups) == 2

    async def test_update_is_refused_while_the_templates_tab_is_dirty(
        self, scene, user_theme
    ):
        result = await help_themes.update_theme(
            scene,
            theme_id(user_theme),
            colors={"app": {"primary": "#FF0000"}},
            templates_dirty=True,
        )

        assert "Templates tab has an unsaved theme edit" in result
        assert user_theme.colors.app.primary == "#123456"

    async def test_apply_is_refused_while_the_templates_tab_is_dirty(
        self, scene, config, user_theme
    ):
        result = await help_themes.apply_theme(
            scene, theme_id(user_theme), templates_dirty=True
        )

        assert "Templates tab has an unsaved theme edit" in result
        assert config.appearance.theme != theme_id(user_theme)

    async def test_apply_is_refused_while_the_settings_view_is_dirty(
        self, scene, config, user_theme
    ):
        # applying writes the appearance settings, which that view saves whole
        result = await help_themes.apply_theme(
            scene, theme_id(user_theme), app_settings_dirty=True
        )

        assert "application settings view has unsaved edits" in result
        assert config.appearance.theme != theme_id(user_theme)


# ---------------------------------------------------------------------------
# the chat loop and the pushes it makes
# ---------------------------------------------------------------------------


class TestChatIntegration:
    async def test_a_theme_write_through_the_chat_loop_creates_the_theme(
        self, help_agent, scene
    ):
        chat = help_agent.chat_create()
        call_block = json.dumps(
            {
                "function": "create_theme",
                "arguments": {
                    "name": "Solarized Dark",
                    "group": USER_GROUP,
                    "colors": {"surfaces": {"background": "#002B36"}},
                },
            }
        )

        async with MockClientContext():
            responses = client_responses.get()
            responses.append(f"```json\n{call_block}\n```")
            responses.append("Created Solarized Dark in My Themes.")

            await help_agent.chat_send(chat.id, "Make me a solarized dark theme")

        results = [
            message
            for message in help_agent.chat_get(chat.id).messages
            if message.type == "doc_result"
        ]
        assert len(results) == 1
        assert results[0].name == "create_theme"
        assert results[0].result["created"] is True
        assert created_theme(scene, "Solarized Dark").colors.surfaces.background == (
            "#002B36"
        )

    async def test_the_write_is_refused_when_the_snapshot_reports_a_dirty_tab(
        self, help_agent, scene
    ):
        chat = help_agent.chat_create()
        call_block = json.dumps(
            {
                "function": "create_theme",
                "arguments": {"name": "Solarized Dark", "group": USER_GROUP},
            }
        )

        async with MockClientContext():
            responses = client_responses.get()
            responses.append(f"```json\n{call_block}\n```")
            responses.append("Save your template edit first.")

            await help_agent.chat_send(
                chat.id,
                "Make me a solarized dark theme",
                ux_snapshot={"templates_view": {"dirty": True}},
            )

        results = [
            message
            for message in help_agent.chat_get(chat.id).messages
            if message.type == "doc_result"
        ]
        assert "unsaved theme edit" in results[0].result

    async def test_the_active_theme_write_pushes_templates_and_app_config(
        self, scene, config, user_theme
    ):
        config.appearance.theme = theme_id(user_theme)
        handler = MockWebsocketHandler(scene)
        plugin = HelpWebsocketHandler(handler)

        *_, on_templates_changed = plugin._make_generation_callbacks()
        await on_templates_changed(theme_id(user_theme))

        assert handler.find("templates")["data"]["managed"]["groups"]
        pushed = handler.find("app_config")
        assert pushed["data"]["theme"]["colors"]["app"]["primary"] == "#123456"

    async def test_writing_another_theme_only_pushes_the_template_list(
        self, scene, config, user_theme
    ):
        handler = MockWebsocketHandler(scene)
        plugin = HelpWebsocketHandler(handler)

        *_, on_templates_changed = plugin._make_generation_callbacks()
        await on_templates_changed(theme_id(user_theme))

        assert handler.actions == ["templates"]


def test_the_prompt_sends_deletion_to_the_templates_tab():
    """Deleting a theme is deliberately not a tool - the only thing that can
    tell the agent where deletion happens is the prompt."""
    prompt = (
        pathlib.Path(talemate.__file__).parent
        / "prompts"
        / "templates"
        / "help"
        / "chat.jinja2"
    )
    text = prompt.read_text()

    assert "CANNOT delete one" in text
    assert "Templates tab" in text


# ---------------------------------------------------------------------------
# what the agent is given in place of eyes
# ---------------------------------------------------------------------------


class TestSlotPaints:
    def test_every_slot_is_described(self):
        """A slot the map does not carry would come back without its `paints`,
        and the agent would recolor it from its name alone."""
        expected = {
            f"{group}.{slot}"
            for group, model in help_themes.COLOR_GROUPS.items()
            for slot in model.model_fields
        }

        assert set(help_themes.SLOT_PAINTS) == expected

    def test_a_surprising_use_is_carried(self):
        """The map is worth having only where a slot's name does not give it
        away - the character-detail accent also paints the client list's
        reasoning sliders."""
        assert "reasoning" in help_themes.SLOT_PAINTS["app.highlight2"]


class TestColorMath:
    """The analysis leans on these two, and the shipped-theme contrast test now
    imports the same `contrast_ratio` it measures with - so the oracle has to
    sit somewhere that does not depend on the function under test."""

    def test_contrast_ratio_endpoints(self):
        assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.01)
        assert contrast_ratio("#7F7F7F", "#7F7F7F") == pytest.approx(1.0, abs=0.001)

    def test_contrast_ratio_is_symmetric(self):
        assert contrast_ratio("#123456", "#EEEEEE") == contrast_ratio(
            "#EEEEEE", "#123456"
        )

    def test_relative_luminance_matches_the_wcag_endpoints(self):
        from talemate.util.colors import relative_luminance

        assert relative_luminance("#FFFFFF") == pytest.approx(1.0, abs=0.0001)
        assert relative_luminance("#000000") == pytest.approx(0.0, abs=0.0001)


class TestColorNames:
    @pytest.mark.parametrize(
        "color,expected",
        [
            ("#F44336", "vivid red"),
            ("#002B36", "muted very dark cyan"),
            ("#9E9E9E", "grey"),
            ("#FFFFFF", "white"),
            ("#000000", "black"),
            ("#795548", "muted dark brown"),
            # the boundaries the first cut misnamed
            ("#0000FF", "vivid dark blue"),
            ("#FF5722", "vivid orange"),
            ("#607D8B", "muted blue"),
            ("#A1887F", "muted brown"),
            ("#CDDC39", "very light lime"),
        ],
    )
    def test_names_the_color(self, color, expected):
        assert describe_color(color) == expected

    def test_read_theme_names_every_color(self, scene, user_theme):
        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert payload["slots"]["app.primary"]["name"] == describe_color(
            payload["colors"]["app"]["primary"]
        )
        assert all("name" in slot for slot in payload["slots"].values())


class TestContrast:
    def test_read_theme_reports_the_ground_it_measured(self, scene, user_theme):
        """A slot is drawn on the page and on cards alike, so the number
        reported is the worse of the two - and it says which one it is."""
        user_theme.colors.surfaces.background = "#000000"
        user_theme.colors.surfaces.surface = "#767676"
        user_theme.colors.messages.narrator = "#FFFFFF"

        payload = help_themes.read_theme(scene, theme_id(user_theme))
        contrast = payload["slots"]["messages.narrator"]["contrast"]

        assert contrast["measured_against"] == "surface"
        assert contrast["ratio"] == pytest.approx(
            contrast_ratio("#FFFFFF", "#767676"), abs=0.01
        )

    def test_nothing_is_reported_as_passing(self, scene, user_theme):
        """The theme does not know what a slot is drawn on, so a verdict would
        be a claim about markup this tool cannot see. Only the measurement and
        the reference are reported."""
        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert not [
            slot
            for slot in payload["slots"].values()
            if "passes" in slot.get("contrast", {})
        ]
        assert payload["slots"]["messages.narrator"]["contrast"].keys() == {
            "measured_against",
            "ratio",
            "wcag_reference",
        }

    def test_text_and_interface_slots_carry_different_references(
        self, scene, user_theme
    ):
        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert (
            payload["slots"]["messages.narrator"]["contrast"]["wcag_reference"] == 4.5
        )
        # an accent that also paints 64 spans of literal text answers to the
        # text reference, not the interface one
        assert payload["slots"]["app.primary"]["contrast"]["wcag_reference"] == 4.5
        assert payload["slots"]["app.favorite"]["contrast"]["wcag_reference"] == 3.0

    @pytest.mark.parametrize(
        "slot_key,expected",
        [
            ("app.muted", "dim"),
            ("app.mutedheader", "mutedbg"),
            ("messages.defaultBadge", "white label"),
            ("chats.hchat_msg_help", "tonal"),
            ("chats.dchat_msg_compaction", "muted"),
        ],
    )
    def test_a_slot_drawn_elsewhere_is_unmeasured_with_its_reason(
        self, scene, user_theme, slot_key, expected
    ):
        """Reporting a ratio against a pairing that never renders reads as
        reassurance - these say what they are drawn on instead."""
        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert expected in payload["unmeasured"][slot_key]
        assert "contrast" not in payload["slots"][slot_key]

    def test_unmeasured_slots_never_reach_the_low_contrast_list(
        self, scene, user_theme
    ):
        user_theme.colors.chats.hchat_msg_help = "#111111"
        user_theme.colors.app.muted = "#111111"

        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert not [
            entry
            for entry in payload["low_contrast"]
            if "hchat_msg_help" in entry or "app.muted" in entry
        ]

    def test_the_compaction_slot_never_reports_on_a_shipped_theme(self):
        """It paints no text; held to the text reference it was the only thing
        Talemate Light reported."""
        shipped = Group.load(SHIPPED_THEMES_PATH)

        for uid in ("dark", "light"):
            analysis = help_themes.analyze_theme(shipped.templates[uid])
            assert not [
                entry for entry in analysis["low_contrast"] if "compaction" in entry
            ]

    @pytest.mark.parametrize(
        "uid,count,lowest,highest",
        [("dark", 4, 3.23, 4.47), ("light", 8, 3.73, 4.06)],
    )
    def test_the_shipped_themes_report_what_the_docs_say(
        self, uid, count, lowest, highest
    ):
        """The user guide quotes both counts and Light's range. A ground change
        that moves them has to move the sentence with it."""
        shipped = Group.load(SHIPPED_THEMES_PATH)

        analysis = help_themes.analyze_theme(shipped.templates[uid])
        ratios = [
            analysis["slots"][entry.split(" ", 1)[0]]["contrast"]["ratio"]
            for entry in analysis["low_contrast"]
        ]

        assert len(analysis["low_contrast"]) == count
        assert min(ratios) == lowest
        assert max(ratios) == highest

    def test_a_slot_the_band_never_carries_is_not_measured_against_it(self):
        """The star on a theme row and the diff deletion inside a dialog are
        never in a toolbar; measuring them there reported a problem no user can
        see."""
        shipped = Group.load(SHIPPED_THEMES_PATH)

        analysis = help_themes.analyze_theme(shipped.templates["light"])

        for slot_key in ("app.favorite", "app.inactive", "app.unsaved"):
            assert slot_key not in help_themes.BAND_SLOTS
            assert (
                analysis["slots"][slot_key]["contrast"]["measured_against"] != "mutedbg"
            )
            assert not [
                entry for entry in analysis["low_contrast"] if slot_key in entry
            ]

    def test_an_accent_on_the_band_is_measured_against_the_band(self):
        """The band is a theme fill and `variant="text"` controls sit on it with
        no fill of their own, so the page is the wrong ground for them."""
        shipped = Group.load(SHIPPED_THEMES_PATH)

        analysis = help_themes.analyze_theme(shipped.templates["light"])
        primary = analysis["slots"]["app.primary"]["contrast"]

        assert primary["measured_against"] == "mutedbg"
        assert primary["ratio"] == 3.88
        assert any(
            "app.primary" in entry and "mutedbg" in entry
            for entry in analysis["low_contrast"]
        )

    def test_message_colors_are_not_measured_against_the_band(self):
        """Message text is never drawn in a toolbar."""
        shipped = Group.load(SHIPPED_THEMES_PATH)

        analysis = help_themes.analyze_theme(shipped.templates["light"])

        assert analysis["slots"]["messages.narrator"]["contrast"][
            "measured_against"
        ] in ("background", "surface")

    def test_chip_text_is_measured_against_its_own_fill(self, scene, user_theme):
        # the one ground the theme itself pins: the model declares this slot as
        # the text drawn on surface_variant
        user_theme.colors.surfaces.surface_variant = "#FFFFFF"
        user_theme.colors.surfaces.on_surface_variant = "#000000"

        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert payload["slots"]["surfaces.on_surface_variant"]["contrast"] == {
            "measured_against": "surface_variant",
            "ratio": 21.0,
            "wcag_reference": 4.5,
        }

    def test_surfaces_that_are_only_grounds_carry_no_contrast(self, scene, user_theme):
        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert "contrast" not in payload["slots"]["surfaces.background"]

    def test_flat_surfaces_are_reported(self, scene, user_theme):
        user_theme.colors.surfaces.background = "#121212"
        user_theme.colors.surfaces.surface = "#121212"

        payload = help_themes.read_theme(scene, theme_id(user_theme))

        assert payload["surface_separation"] == 1.0

    def test_a_borderline_ratio_is_never_rounded_up_to_the_reference(self):
        """2.9953 reported as 3.0 under a 3.0 reference contradicts itself."""
        measured = help_themes._measured(
            "app.favorite",
            "#959595",
            {"background": "#FFFFFF", "surface": "#FFFFFF"},
            {"mutedbg": "#FFFFFF"},
        )

        assert measured["ratio"] == 2.99
        assert measured["ratio"] < measured["wcag_reference"]

    async def test_a_write_names_what_it_leaves_under_the_reference(
        self, scene, user_theme
    ):
        result = await help_themes.update_theme(
            scene,
            theme_id(user_theme),
            colors={"messages": {"narrator": "#1A1A1A"}},
        )

        assert any("messages.narrator" in entry for entry in result["low_contrast"])
        assert result["contrast_written"]["messages.narrator"]["ratio"] < 4.5

    async def test_a_write_reports_the_separation_it_may_have_flattened(
        self, scene, user_theme
    ):
        result = await help_themes.update_theme(
            scene,
            theme_id(user_theme),
            colors={"surfaces": {"surface": user_theme.colors.surfaces.background}},
        )

        assert result["surface_separation"] == 1.0

    async def test_a_write_to_an_unmeasured_slot_says_so(self, scene, user_theme):
        result = await help_themes.update_theme(
            scene,
            theme_id(user_theme),
            colors={"chats": {"hchat_msg_help": "#8A8A8A"}},
        )

        assert "unmeasured" in result["contrast_written"]["chats.hchat_msg_help"]

    async def test_a_write_that_reads_well_names_nothing_for_it(
        self, scene, user_theme
    ):
        result = await help_themes.update_theme(
            scene,
            theme_id(user_theme),
            colors={"messages": {"narrator": "#FFFFFF"}},
        )

        assert result["contrast_written"]["messages.narrator"]["ratio"] > 4.5
        assert not [
            entry for entry in result["low_contrast"] if "messages.narrator" in entry
        ]

    async def test_a_created_theme_reports_what_it_measures(self, scene):
        result = await help_themes.create_theme(
            scene,
            "Unreadable",
            USER_GROUP,
            colors={
                "surfaces": {"background": "#000000", "surface": "#000000"},
                "messages": {"narrator": "#0A0A0A"},
            },
        )

        assert any("messages.narrator" in entry for entry in result["low_contrast"])
