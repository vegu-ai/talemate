"""
Unit tests for `talemate.world_state.templates.theme`, the shipped theme group
and the manager entry point that activates a theme.

Covers:
- registration / polymorphic deserialization through a Group yaml round-trip
- color validation and malformed templates being dropped instead of exploding
- the shipped "Themes" group and its dark and light templates declaring every
  slot
- `WorldStateManager.apply_template_theme`: config write, styling copied into
  the scene appearance, asset settings and color overrides left alone
- `resolve_theme`: total fallback to the built-in default, and the lookup cache
  that keeps it off the template directory on every config change
- the websocket handlers that apply, save and delete a theme, including the
  app_config push that makes a change live without a reload
"""

import copy
import os

import pydantic
import pytest
import yaml

import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
from conftest import MockScene
from talemate.config.schema import Config, SceneAppearance
from talemate.emit.signals import handlers as emit_handlers
from talemate.server.websocket_server import WebsocketHandler
from talemate.server.world_state_manager import WorldStateManagerPlugin
from talemate.util.colors import contrast_ratio
from talemate.world_state.manager import (
    THEME_APPEARANCE_MAP,
    WorldStateManager,
    apply_theme_appearance,
)
from talemate.world_state.templates.base import (
    MODELS,
    REPAIR_CONTEXT,
    TEMPLATE_PATH,
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
)
from talemate.world_state.templates.shortcut import SceneToolShortcutTemplate
from talemate.world_state.templates.visual import VisualStyle
from talemate.world_state.templates.theme import (
    CODE_EDITOR_THEMES,
    AppColors,
    ChatColors,
    MessageColors,
    SurfaceColors,
    Theme,
    ThemeAppearance,
    ThemeMessageStyle,
    _find_theme,
    default_theme,
    invalidate_theme_cache,
    resolve_theme,
)

SHIPPED_THEMES_PATH = os.path.join(TEMPLATE_PATH_TALEMATE, "themes.yaml")
SHIPPED_DARK_ID = "themes__dark"
SHIPPED_LIGHT_ID = "themes__light"


def raw_shipped_template(uid: str) -> dict:
    """A shipped template as it is written on disk - validation fills in every
    field it forgot to declare, so the file itself is what has to be read."""
    with open(SHIPPED_THEMES_PATH, "r") as f:
        return yaml.safe_load(f)["templates"][uid]


# every value differs from the `SceneAppearance` default, so a test asserting
# them only passes if the theme's styling was actually copied over
STYLED_APPEARANCE = {
    "narrator": {"italic": True, "bold": True},
    "director": {"italic": True, "bold": True, "show": False},
    "quotes": {"italic": True, "bold": True, "override_color": False, "show": False},
    "backdrop_panel_opacity": 0.35,
    "backdrop_text_shadow": False,
}


def make_template(**overrides) -> Theme:
    defaults = dict(name="Midnight")
    defaults.update(overrides)
    return Theme(**defaults)


def load_template(**overrides) -> Theme:
    """A theme validated the way one read off disk is - repairs allowed."""
    defaults = dict(name="Midnight")
    defaults.update(overrides)
    return Theme.model_validate(defaults, context=REPAIR_CONTEXT)


def make_styled_template(**overrides) -> Theme:
    return make_template(appearance=STYLED_APPEARANCE, **overrides)


def make_group(name="g", templates=None) -> Group:
    group = Group(author="a", name=name, description="d")
    if templates:
        for template in templates:
            group.insert_template(template, save=False)
            # `Group.save` is what normally stamps this, and the id a theme is
            # activated by is built from it
            template.group = group.uid
    return group


@pytest.fixture(autouse=True)
def theme_cache():
    """`resolve_theme` caches its lookups for the life of the process."""
    invalidate_theme_cache()
    yield
    invalidate_theme_cache()


@pytest.fixture
def collection_loads(monkeypatch, template_dir) -> list[str]:
    """Points the no-argument `Collection.load()` at the test's template dir.

    That form is what `resolve_theme` uses in production, so a test that wants
    to reach it has to keep it off the shipped template directory. The returned
    list records every load, which is how the cache is observed.
    """
    loads = []
    original = Collection.load

    def _load(path: str = template_dir):
        loads.append(path)
        return original(path)

    monkeypatch.setattr(Collection, "load", _load)
    return loads


@pytest.fixture
def manager() -> WorldStateManager:
    """A manager on a bare scene - activating a theme never touches it."""
    return WorldStateManager(MockScene())


@pytest.fixture
def config(monkeypatch, tmp_path, isolate_signals):
    """A throwaway app config, written to a tmp_path config.yaml.

    Also drops the config.changed receivers so the broadcast the manager
    triggers does not dispatch into agents left behind by other tests.
    """
    isolate_signals("config.changed", "config.changed.follow", "config.saved")

    original = config_state.CONFIG
    cfg = Config()
    cfg.dirty = False
    config_state.CONFIG = cfg
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")

    yield cfg

    config_state.CONFIG = original


@pytest.fixture
def status_messages():
    captured = []

    def _receiver(emission):
        captured.append(emission)

    signal = emit_handlers["status"]
    signal.connect(_receiver, weak=False)
    try:
        yield captured
    finally:
        signal.disconnect(_receiver)


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------


class TestThemeTemplateModel:
    def test_registered(self):
        assert MODELS["theme"] is Theme

    def test_template_type_default(self):
        assert make_template().template_type == "theme"

    def test_defaults_are_the_built_in_theme(self):
        template = make_template()

        assert template.colors.app.primary == "#9575CD"
        assert template.colors.app.module_locked_selected == "#78909C"
        assert template.colors.messages.narrator == "#A180AE"
        assert template.colors.chats.hchat_msg_doc_result == "#64B5F6"
        assert template.appearance.backdrop_panel_opacity == 0.8
        assert template.appearance.backdrop_text_shadow is True

    def test_surface_defaults_are_the_vuetify_dark_base(self):
        """The surface slots default to vuetify's own dark base values, so a
        theme that does not touch them renders exactly as it did before."""
        surfaces = make_template().colors.surfaces

        assert surfaces.background == "#121212"
        assert surfaces.surface == "#212121"
        assert surfaces.surface_bright == "#CCBFD6"
        assert surfaces.surface_light == "#424242"
        assert surfaces.surface_variant == "#C8C8C8"
        assert surfaces.on_surface_variant == "#000000"

    def test_surface_slots_are_named_with_underscores(self):
        """Vuetify's slots are hyphenated (`surface-bright`), which is not a
        valid identifier - the frontend hyphenates these again on the way in."""
        assert set(SurfaceColors.model_fields) == {
            "background",
            "surface",
            "surface_bright",
            "surface_light",
            "surface_variant",
            "on_surface_variant",
        }

    def test_dark_defaults_to_true(self):
        assert make_template().dark is True

    def test_code_editor_defaults_to_one_dark(self):
        assert make_template().code_editor == "one-dark"

    @pytest.mark.parametrize(
        "code_editor", ["", "One Dark", "one_dark", "dracula", None, 7, ["dracula"]]
    )
    def test_unknown_code_editor_falls_back_to_one_dark_when_read_off_disk(
        self, code_editor
    ):
        """An editor theme this version does not know must not cost the theme
        its colors - `Group.sanitize_data` drops a template that fails to
        validate, so the load path has to coerce rather than raise."""
        assert load_template(code_editor=code_editor).code_editor == "one-dark"

    @pytest.mark.parametrize(
        "code_editor", ["", "One Dark", "one_dark", "dracula", None, 7, ["dracula"]]
    )
    def test_unknown_code_editor_is_rejected_without_the_repair_context(
        self, code_editor
    ):
        """The repair belongs to the load path alone - a caller that did not
        ask for it (a save arriving over the websocket) gets an error."""
        with pytest.raises(pydantic.ValidationError, match="Unknown code editor"):
            make_template(code_editor=code_editor)

    @pytest.mark.parametrize("code_editor", ["one-dark\n", "  nord  "])
    def test_code_editor_is_stripped(self, code_editor: str):
        """A yaml block scalar appends a newline - a known id that carries one
        is still that id, not an unknown one."""
        assert make_template(code_editor=code_editor).code_editor == code_editor.strip()

    @pytest.mark.parametrize("code_editor", CODE_EDITOR_THEMES)
    def test_known_code_editor_is_kept(self, code_editor: str):
        template = make_template(code_editor=code_editor)

        assert template.code_editor == code_editor
        assert template.resolved()["code_editor"] == code_editor

    def test_every_shipped_code_editor_id_is_covered(self):
        """The frontend bundles these ids - a coercion that silently swallowed
        one of them would look like the fallback working."""
        assert len(CODE_EDITOR_THEMES) == 8
        assert CODE_EDITOR_THEMES[0] == "one-dark"

    def test_resolved_carries_the_code_editor_theme(self):
        template = make_template(code_editor="nord")

        assert template.resolved()["code_editor"] == "nord"

    def test_built_in_default_payload_carries_the_code_editor_theme(self):
        assert default_theme()["code_editor"] == "one-dark"

    def test_semantic_slots_carry_vuetifys_stock_dark_values(self):
        colors = make_template().colors.app

        assert colors.success == "#4CAF50"
        assert colors.info == "#2196F3"
        assert colors.warning == "#FB8C00"
        assert colors.error == "#CF6679"

    def test_appearance_carries_no_asset_settings(self):
        fields = set(ThemeAppearance.model_fields)
        assert "message_assets" not in fields
        assert "auto_attach_assets" not in fields

    def test_appearance_carries_no_colors(self):
        for name in ThemeAppearance.model_fields:
            sub = getattr(ThemeAppearance(), name)
            if isinstance(sub, pydantic.BaseModel):
                assert "color" not in type(sub).model_fields

    def test_show_only_on_hidable_message_types(self):
        appearance = ThemeAppearance()

        for name in ["narrator", "actor", "time", "information"]:
            assert "show" not in type(getattr(appearance, name)).model_fields

        for name in ["director", "context_investigation"]:
            assert getattr(appearance, name).show is True

    def test_markup_types_carry_override_color_and_show(self):
        appearance = ThemeAppearance()

        for name in ["quotes", "parentheses", "brackets", "emphasis", "entities"]:
            markup = getattr(appearance, name)
            assert markup.override_color is True
            assert markup.show is True

    @pytest.mark.parametrize("opacity", [-0.1, 1.1])
    def test_backdrop_opacity_out_of_range_raises(self, opacity: float):
        with pytest.raises(pydantic.ValidationError):
            ThemeAppearance(backdrop_panel_opacity=opacity)

    def test_yaml_roundtrip_deserializes_to_the_template_class(self, template_dir):
        template = make_template(colors={"app": {"primary": "#123456"}})
        group = make_group(name="Themes", templates=[template])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)
        assert data["templates"][template.uid]["colors"]["app"]["primary"] == "#123456"

        loaded = Group.load(group.path)
        restored = loaded.templates[template.uid]

        assert type(restored) is Theme
        assert restored.name == "Midnight"
        assert restored.colors.app.primary == "#123456"
        assert restored.colors.app.secondary == "#FF5722"
        assert restored.appearance.quotes.show is True

    def test_light_theme_yaml_roundtrip_keeps_dark_false(self, template_dir):
        template = make_template(
            name="Daylight", dark=False, colors={"surfaces": {"background": "#FFFFFF"}}
        )
        group = make_group(name="Themes", templates=[template])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)
        assert data["templates"][template.uid]["dark"] is False

        restored = Group.load(group.path).templates[template.uid]

        assert restored.dark is False
        assert restored.colors.surfaces.background == "#FFFFFF"
        assert restored.colors.surfaces.surface == "#212121"

    def test_yaml_without_a_code_editor_theme_loads_with_the_default(
        self, template_dir
    ):
        """A hand authored theme written before the field existed has to keep
        loading - it just gets the default editor theme."""
        template = make_template()
        group = make_group(name="Themes", templates=[template])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)
        del data["templates"][template.uid]["code_editor"]
        with open(group.path, "w") as f:
            yaml.dump(data, f)

        restored = Group.load(group.path).templates[template.uid]

        assert restored.name == "Midnight"
        assert restored.code_editor == "one-dark"

    def test_yaml_with_a_block_scalar_code_editor_theme_loads(self, template_dir):
        """A yaml block scalar appends a newline - it names a known editor
        theme, so the load must keep it rather than fall back."""
        template = make_template(code_editor="nord")
        group = make_group(name="Themes", templates=[template])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)
        data["templates"][template.uid]["code_editor"] = "nord\n"
        with open(group.path, "w") as f:
            yaml.dump(data, f)

        restored = Group.load(group.path).templates[template.uid]

        assert restored.code_editor == "nord"

    def test_yaml_with_an_unknown_code_editor_theme_keeps_its_colors(
        self, template_dir
    ):
        """A hand edited theme naming an editor theme this version does not
        know used to be dropped from its group entirely - every color gone, and
        permanently, the next save of the group writes the file back out
        without it."""
        template = make_template(colors={"app": {"primary": "#123456"}})
        group = make_group(name="Themes", templates=[template])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)
        data["templates"][template.uid]["code_editor"] = "dracula"
        with open(group.path, "w") as f:
            yaml.dump(data, f)

        loaded = Group.load(group.path)

        assert template.uid in loaded.templates

        restored = loaded.templates[template.uid]

        assert restored.name == "Midnight"
        assert restored.code_editor == "one-dark"
        assert restored.colors.app.primary == "#123456"
        assert restored.colors.model_dump() == template.colors.model_dump()


class TestThemeColorValidation:
    @pytest.mark.parametrize(
        "color", ["", "red", "#12345", "#1234567", "#GGGGGG", "9575CD", "#9575CD;"]
    )
    def test_bad_color_is_rejected(self, color: str):
        with pytest.raises(pydantic.ValidationError, match="#RRGGBB"):
            AppColors(primary=color)

    @pytest.mark.parametrize("color", ["#9575cd", "#9575CD", "#000000"])
    def test_good_color_passes(self, color: str):
        assert AppColors(primary=color).primary == color

    @pytest.mark.parametrize("color", ["#9575CD\n", "  #9575CD  "])
    def test_color_is_stored_stripped(self, color: str):
        """A yaml block scalar appends a newline - the stored value must never
        carry surrounding whitespace, the frontend uses it verbatim."""
        assert AppColors(primary=color).primary == "#9575CD"

    @pytest.mark.parametrize(
        "model", [AppColors, MessageColors, ChatColors, SurfaceColors]
    )
    def test_every_default_is_a_valid_color(self, model):
        for name, value in model().model_dump().items():
            assert model(**{name: value})

    def test_malformed_template_in_yaml_is_dropped_on_load(self, template_dir):
        valid = make_template(name="Valid")
        group = make_group(name="Themes", templates=[valid])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)

        broken = copy.deepcopy(data["templates"][valid.uid])
        broken.update(uid="broken", name="Broken")
        broken["colors"]["app"]["primary"] = "red"
        data["templates"]["broken"] = broken

        with open(group.path, "w") as f:
            yaml.dump(data, f)

        loaded = Group.load(group.path)

        assert "broken" not in loaded.templates
        assert loaded.templates[valid.uid].name == "Valid"


# ---------------------------------------------------------------------------
# shipped group
# ---------------------------------------------------------------------------


class TestShippedThemeContrast:
    """The status colors are the ones a theme author is most likely to get wrong,
    because they read as fixed brand colors rather than theme slots. #276 asks
    that consolidating slots cannot quietly cost readability.

    The floor is the 3:1 that WCAG asks of user interface components - these
    colors paint chips, icons and alert borders rather than body text. The
    tightest of the eight is dark `error` at 4.47:1, which is vuetify's own
    stock value.
    """

    FLOOR = 3.0

    @pytest.fixture
    def shipped(self) -> Group:
        return Group.load(SHIPPED_THEMES_PATH)

    @pytest.mark.parametrize("uid", ["dark", "light"])
    @pytest.mark.parametrize("slot", ["success", "info", "warning", "error"])
    def test_status_colors_clear_the_contrast_floor(self, shipped, uid, slot):
        colors = shipped.templates[uid].colors
        ratio = contrast_ratio(getattr(colors.app, slot), colors.surfaces.surface)

        assert ratio >= self.FLOOR, (
            f"{uid}.{slot} measures {ratio:.2f}:1 against its own surface"
        )


class TestShippedThemesGroup:
    """Both shipped themes live in one group, which is what makes it possible
    for one of them to shadow the other."""

    @pytest.fixture
    def shipped(self) -> Group:
        return Group.load(SHIPPED_THEMES_PATH)

    def test_group_uid_and_name_are_stable(self, shipped):
        assert shipped.uid == "themes"
        assert shipped.name == "Themes"

    def test_ships_both_themes(self, shipped):
        assert set(shipped.templates) == {"dark", "light"}

        for uid, template in shipped.templates.items():
            assert type(template) is Theme
            assert template.uid == uid
            assert template.group == "themes"

    def test_theme_ids_are_stable(self, shipped):
        """These are the ids the config stores - a rename here silently drops
        every user back to the built-in default."""
        assert {f"{shipped.uid}__{uid}" for uid in shipped.templates} == {
            SHIPPED_DARK_ID,
            SHIPPED_LIGHT_ID,
        }

    def test_both_ids_resolve_off_the_template_directory_to_different_themes(
        self, monkeypatch
    ):
        """One group holding both themes is new - a lookup that returned the
        same template for both ids would mean one shadows the other, which a
        group per theme made impossible."""
        loads = []
        original = Collection.load

        def _load(path: str = TEMPLATE_PATH):
            loads.append(path)
            return original(path)

        monkeypatch.setattr(Collection, "load", _load)

        cfg = Config()

        cfg.appearance.theme = SHIPPED_DARK_ID
        dark = resolve_theme(cfg)

        cfg.appearance.theme = SHIPPED_LIGHT_ID
        light = resolve_theme(cfg)

        assert loads and set(loads) == {TEMPLATE_PATH}
        assert dark != light
        assert dark["dark"] is True
        assert light["dark"] is False
        assert dark["colors"]["surfaces"]["background"] == "#121212"
        assert light["colors"]["surfaces"]["background"] == "#F6F1E9"
        assert dark["code_editor"] == "one-dark"
        assert light["code_editor"] == "vscode-light"


class TestShippedDarkTheme:
    @pytest.fixture
    def shipped(self) -> Group:
        return Group.load(SHIPPED_THEMES_PATH)

    @pytest.fixture
    def template(self, shipped) -> Theme:
        return shipped.templates["dark"]

    @pytest.fixture
    def raw(self) -> dict:
        return raw_shipped_template("dark")

    def test_loads(self, template):
        assert type(template) is Theme
        assert template.name == "Talemate Dark"

    def test_uids_are_stable(self, shipped, template):
        assert template.uid == "dark"
        assert template.group == shipped.uid

    def test_declares_every_slot(self, raw):
        for group_name, model in [
            ("app", AppColors),
            ("messages", MessageColors),
            ("chats", ChatColors),
            ("surfaces", SurfaceColors),
        ]:
            assert set(raw["colors"][group_name]) == set(model.model_fields)

        assert set(raw["appearance"]) == set(ThemeAppearance.model_fields)

    def test_declares_every_top_level_field(self, raw):
        """A field added to the model but forgotten here would ship as its
        default, which is only visible where the shipped value differs from
        that default - i.e. usually not at all."""
        assert set(raw) == set(Theme.model_fields)

    def test_declares_the_surfaces_group_and_the_dark_flag(self, raw, template):
        assert raw["colors"]["surfaces"]["background"] == "#121212"
        assert raw["dark"] is True

        assert template.colors.surfaces.surface == "#212121"
        assert template.dark is True

    def test_declares_the_code_editor_theme(self, template):
        assert template.code_editor == "one-dark"
        assert template.resolved()["code_editor"] == "one-dark"

    def test_matches_the_built_in_default(self, template):
        assert template.resolved() == Theme(name="Default").resolved()

    def test_is_resolvable_by_id(self, shipped):
        cfg = Config()
        cfg.appearance.theme = SHIPPED_DARK_ID

        resolved = resolve_theme(cfg, collection=Collection(groups=[shipped]))

        assert resolved["colors"]["app"]["primary"] == "#9575CD"

    def test_is_resolvable_from_the_template_directory(self, monkeypatch):
        """Production never passes a collection, it resolves off the shipped
        template directory. The shipped theme is value identical to the built-in
        fallback, so the payload alone cannot tell a successful resolve from a
        fallback - the lookup the resolve runs on is asserted directly."""
        loads = []
        original = Collection.load

        def _load(path: str = TEMPLATE_PATH):
            loads.append(path)
            return original(path)

        monkeypatch.setattr(Collection, "load", _load)

        cfg = Config()
        cfg.appearance.theme = SHIPPED_DARK_ID

        resolved = resolve_theme(cfg)

        assert loads == [TEMPLATE_PATH]
        assert resolved == Theme(name="Default").resolved()

        # walks the directory a second time, so it has to come after `loads`
        found = _find_theme(cfg.appearance.theme, None)

        assert found is not None
        assert found.name == "Talemate Dark"


class TestShippedLightTheme:
    @pytest.fixture
    def shipped(self) -> Group:
        return Group.load(SHIPPED_THEMES_PATH)

    @pytest.fixture
    def template(self, shipped) -> Theme:
        return shipped.templates["light"]

    @pytest.fixture
    def raw(self) -> dict:
        return raw_shipped_template("light")

    def test_loads(self, template):
        assert type(template) is Theme
        assert template.name == "Talemate Light"

    def test_uids_are_stable(self, shipped, template):
        assert template.uid == "light"
        assert template.group == shipped.uid

    def test_declares_every_slot(self, raw):
        for group_name, model in [
            ("app", AppColors),
            ("messages", MessageColors),
            ("chats", ChatColors),
            ("surfaces", SurfaceColors),
        ]:
            assert set(raw["colors"][group_name]) == set(model.model_fields)

        assert set(raw["appearance"]) == set(ThemeAppearance.model_fields)

    def test_declares_every_top_level_field(self, raw):
        assert set(raw) == set(Theme.model_fields)

    def test_declares_light_surfaces_and_the_dark_flag(self, raw, template):
        assert raw["colors"]["surfaces"]["background"] == "#F6F1E9"
        assert raw["dark"] is False

        assert template.colors.surfaces.background == "#F6F1E9"
        assert template.colors.surfaces.surface == "#FBF8F3"
        assert template.colors.surfaces.surface_bright == "#FEFCF8"
        assert template.colors.surfaces.surface_light == "#EBE4DA"
        assert template.dark is False

    def test_declares_a_light_code_editor_theme(self, template):
        assert template.code_editor == "vscode-light"
        assert template.resolved()["code_editor"] == "vscode-light"

    def test_differs_from_the_built_in_default(self, template):
        """The dark theme is value identical to the built-in fallback, so a
        resolve that quietly fell back would still look right. This one has to
        differ everywhere the surfaces decide light from dark, otherwise the
        same fallback would go unnoticed here too."""
        built_in = Theme(name="Default")

        assert template.resolved() != built_in.resolved()
        assert template.dark != built_in.dark

        for slot in SurfaceColors.model_fields:
            light = getattr(template.colors.surfaces, slot)
            assert light != getattr(built_in.colors.surfaces, slot)

    def test_is_resolvable_by_id(self, shipped):
        cfg = Config()
        cfg.appearance.theme = SHIPPED_LIGHT_ID

        resolved = resolve_theme(cfg, collection=Collection(groups=[shipped]))

        assert resolved["dark"] is False
        assert resolved["colors"]["surfaces"]["background"] == "#F6F1E9"
        assert resolved["colors"]["app"]["primary"] == "#7B56C1"

    def test_is_resolvable_from_the_template_directory(self, monkeypatch):
        """The light theme shares its group with the dark one - resolving it
        off the template directory is what says the dark theme, which is value
        identical to the fallback, does not stand in for it."""
        loads = []
        original = Collection.load

        def _load(path: str = TEMPLATE_PATH):
            loads.append(path)
            return original(path)

        monkeypatch.setattr(Collection, "load", _load)

        cfg = Config()
        cfg.appearance.theme = SHIPPED_LIGHT_ID

        resolved = resolve_theme(cfg)

        assert loads == [TEMPLATE_PATH]
        assert resolved["dark"] is False
        assert resolved["colors"]["surfaces"]["background"] == "#F6F1E9"


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


class TestResolveTheme:
    def default(self) -> dict:
        return Theme(name="Default").resolved()

    def test_shape(self):
        resolved = resolve_theme(Config())

        assert set(resolved) == {"colors", "appearance", "dark", "code_editor"}
        assert set(resolved["colors"]) == {
            "app",
            "messages",
            "chats",
            "surfaces",
        }

    def test_no_theme_configured_resolves_to_the_default(self):
        assert resolve_theme(Config()) == self.default()

    def test_configured_theme_resolves(self):
        template = make_template(colors={"app": {"primary": "#123456"}})
        group = make_group(name="Themes", templates=[template])
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{template.uid}"

        resolved = resolve_theme(cfg, collection=Collection(groups=[group]))

        assert resolved["colors"]["app"]["primary"] == "#123456"
        assert resolved["appearance"]["backdrop_panel_opacity"] == 0.8

    def test_unknown_id_resolves_to_the_default(self):
        cfg = Config()
        cfg.appearance.theme = "nope__nope"

        assert resolve_theme(cfg, collection=Collection(groups=[])) == self.default()

    def test_deleted_group_resolves_to_the_default(self):
        template = make_template()
        group = make_group(name="Themes", templates=[template])
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{template.uid}"

        assert resolve_theme(cfg, collection=Collection(groups=[])) == self.default()

    def test_malformed_id_resolves_to_the_default(self):
        cfg = Config()
        cfg.appearance.theme = "no-separator"

        assert resolve_theme(cfg, collection=Collection(groups=[])) == self.default()

    def test_id_of_another_template_type_resolves_to_the_default(self):
        other = SceneToolShortcutTemplate(
            name="Push On",
            action_id="narrator.progress",
            label="Push on",
            icon="mdi-script-text",
        )
        group = make_group(name="Shortcuts", templates=[other])
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{other.uid}"

        assert (
            resolve_theme(cfg, collection=Collection(groups=[group])) == self.default()
        )

    def test_broken_collection_resolves_to_the_default(self):
        class Broken:
            def find_template_by_id(self, template_id):
                raise RuntimeError("no templates for you")

        cfg = Config()
        cfg.appearance.theme = "some__theme"

        assert resolve_theme(cfg, collection=Broken()) == self.default()

    def test_light_theme_resolves_with_its_surfaces(self):
        template = make_template(
            dark=False,
            colors={"surfaces": {"background": "#FFFFFF", "surface": "#F5F5F5"}},
        )
        group = make_group(name="Themes", templates=[template])
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{template.uid}"

        resolved = resolve_theme(cfg, collection=Collection(groups=[group]))

        assert resolved["dark"] is False
        assert resolved["colors"]["surfaces"]["background"] == "#FFFFFF"
        assert resolved["colors"]["surfaces"]["surface"] == "#F5F5F5"
        assert resolved["colors"]["surfaces"]["surface_light"] == "#424242"

    @pytest.mark.parametrize(
        "theme_id", [None, "nope__nope", "no-separator", "deleted__default"]
    )
    def test_fallback_carries_surfaces_and_dark(self, theme_id: str | None):
        """The frontend writes every slot of this payload into vuetify - a
        fallback missing them would leave a light theme's surfaces behind."""
        cfg = Config()
        cfg.appearance.theme = theme_id

        resolved = resolve_theme(cfg, collection=Collection(groups=[]))

        assert set(resolved["colors"]["surfaces"]) == set(SurfaceColors.model_fields)
        assert resolved["colors"]["surfaces"]["background"] == "#121212"
        assert resolved["dark"] is True
        assert resolved["code_editor"] == "one-dark"

    def test_configured_code_editor_theme_resolves(self):
        template = make_template(code_editor="tokyo-night-storm")
        group = make_group(name="Themes", templates=[template])
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{template.uid}"

        resolved = resolve_theme(cfg, collection=Collection(groups=[group]))

        assert resolved["code_editor"] == "tokyo-night-storm"

    def test_unknown_code_editor_theme_resolves_with_the_theme_colors(self):
        """Only the editor theme falls back - the active theme itself keeps
        rendering, rather than the whole app dropping to the built-in default."""
        template = load_template(
            code_editor="dracula", colors={"app": {"primary": "#123456"}}
        )
        group = make_group(name="Themes", templates=[template])
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{template.uid}"

        resolved = resolve_theme(cfg, collection=Collection(groups=[group]))

        assert resolved["code_editor"] == "one-dark"
        assert resolved["colors"]["app"]["primary"] == "#123456"


class TestResolveThemeCache:
    """`resolve_theme` runs on every config change - a client status write
    during play must not walk and parse the whole template directory."""

    def install(self, template_dir, template) -> Group:
        group = make_group(name="Themes", templates=[template])
        group.save(template_dir)
        return group

    def test_repeat_resolves_load_the_collection_once(
        self, template_dir, collection_loads
    ):
        template = make_template(colors={"app": {"primary": "#123456"}})
        group = self.install(template_dir, template)
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{template.uid}"

        first = resolve_theme(cfg)
        second = resolve_theme(cfg)

        assert first == second
        assert first["colors"]["app"]["primary"] == "#123456"
        assert len(collection_loads) == 1

    def test_an_unresolvable_id_is_only_looked_up_once(
        self, template_dir, collection_loads
    ):
        cfg = Config()
        cfg.appearance.theme = "nope__nope"

        assert resolve_theme(cfg) == Theme(name="Default").resolved()
        assert resolve_theme(cfg) == Theme(name="Default").resolved()
        assert len(collection_loads) == 1

    def test_switching_the_active_theme_resolves_the_new_one(
        self, template_dir, collection_loads
    ):
        first = make_template(name="First", colors={"app": {"primary": "#111111"}})
        second = make_template(name="Second", colors={"app": {"primary": "#222222"}})
        group = make_group(name="Themes", templates=[first, second])
        group.save(template_dir)
        cfg = Config()

        cfg.appearance.theme = f"{group.uid}__{first.uid}"
        assert resolve_theme(cfg)["colors"]["app"]["primary"] == "#111111"

        cfg.appearance.theme = f"{group.uid}__{second.uid}"
        assert resolve_theme(cfg)["colors"]["app"]["primary"] == "#222222"

    def test_an_explicit_collection_neither_reads_nor_fills_the_cache(
        self, template_dir, collection_loads
    ):
        template = make_template(colors={"app": {"primary": "#123456"}})
        group = self.install(template_dir, template)
        cfg = Config()
        cfg.appearance.theme = f"{group.uid}__{template.uid}"

        explicit = Collection(groups=[group.model_copy(deep=True)])
        explicit.groups[0].templates[template.uid].colors.app.primary = "#654321"

        from_explicit = resolve_theme(cfg, collection=explicit)
        from_disk = resolve_theme(cfg)

        assert from_explicit["colors"]["app"]["primary"] == "#654321"
        assert from_disk["colors"]["app"]["primary"] == "#123456"
        assert len(collection_loads) == 1


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


class TestApplyTemplateTheme:
    async def test_sets_the_active_theme(self, manager, config):
        template = make_template()
        group = make_group(name="Themes", templates=[template])
        manager.scene._world_state_templates = Collection(groups=[group])

        result = await manager.apply_template_theme(template)

        assert result.theme_id == f"{group.uid}__{template.uid}"
        assert config.appearance.theme == result.theme_id

    async def test_emits_success_status(self, manager, config, status_messages):
        template = make_template()
        make_group(name="Themes", templates=[template])

        await manager.apply_template_theme(template)

        (emission,) = status_messages
        assert emission.message == "Theme 'Midnight' activated"
        assert emission.status == "success"

    async def test_persists_the_config(self, manager, config):
        template = make_template()
        group = make_group(name="Themes", templates=[template])

        await manager.apply_template_theme(template)

        with open(config_state.CONFIG_FILE, "r") as f:
            saved = yaml.safe_load(f)

        assert saved["appearance"]["theme"] == f"{group.uid}__{template.uid}"
        assert config.dirty is False

    async def test_leaves_asset_settings_alone(self, manager, config):
        scene_appearance = config.appearance.scene
        scene_appearance.auto_attach_assets = False
        scene_appearance.message_assets["avatar"].cadence = "never"
        assets_before = scene_appearance.message_assets.copy()

        template = make_template()
        make_group(name="Themes", templates=[template])

        await manager.apply_template_theme(template)

        assert config.appearance.scene.auto_attach_assets is False
        assert config.appearance.scene.message_assets == assets_before
        assert config.appearance.scene.message_assets["avatar"].cadence == "never"

    async def test_switching_themes_replaces_the_active_theme(self, manager, config):
        first = make_template(name="First")
        second = make_template(name="Second")
        group = make_group(name="Themes", templates=[first, second])

        await manager.apply_template_theme(first)
        await manager.apply_template_theme(second)

        assert config.appearance.theme == f"{group.uid}__{second.uid}"

    async def test_flat_uid_string_resolves_to_the_template(self, manager, config):
        template = make_template()
        group = make_group(name="Themes", templates=[template])
        manager.scene._world_state_templates = Collection(groups=[group])

        result = await manager.apply_template_theme(f"{group.uid}__{template.uid}")

        assert result.theme_id == f"{group.uid}__{template.uid}"
        assert config.appearance.theme == result.theme_id

    async def test_unknown_flat_uid_string_is_a_noop(self, manager, config):
        manager.scene._world_state_templates = Collection(groups=[])

        result = await manager.apply_template_theme("nope__nope")

        assert result is None
        assert config.appearance.theme is None
        assert not config_state.CONFIG_FILE.exists()

    async def test_dispatches_through_apply_template(self, manager, config):
        template = make_template()
        group = make_group(name="Themes", templates=[template])

        result = await manager.apply_template(template)

        assert result.theme_id == f"{group.uid}__{template.uid}"

    async def test_result_is_dumpable(self, manager, config):
        """Every applier returns a pydantic model - the websocket handler
        dumps whatever comes back without looking at it first."""
        template = make_template()
        group = make_group(name="Themes", templates=[template])

        result = await manager.apply_template_theme(template)

        assert isinstance(result, pydantic.BaseModel)
        assert result.model_dump() == {
            "theme_id": f"{group.uid}__{template.uid}",
            "name": "Midnight",
        }

    async def test_ignores_scene_specific_kwargs(self, manager, config):
        template = make_template()
        make_group(name="Themes", templates=[template])

        result = await manager.apply_template_theme(
            template,
            character_name="",
            run_immediately=False,
            generation_options=None,
        )

        assert config.appearance.theme == result.theme_id


class TestApplyThemeAppearance:
    async def test_copies_styling_onto_the_scene_appearance(self, manager, config):
        template = make_styled_template()
        make_group(name="Themes", templates=[template])

        await manager.apply_template_theme(template)

        scene_appearance = config.appearance.scene

        assert scene_appearance.narrator_messages.italic is True
        assert scene_appearance.narrator_messages.bold is True
        assert scene_appearance.quotes.italic is True
        assert scene_appearance.quotes.bold is True
        assert scene_appearance.quotes.override_color is False
        assert scene_appearance.quotes.show is False
        assert scene_appearance.backdrop_panel_opacity == 0.35
        assert scene_appearance.backdrop_text_shadow is False

    async def test_copies_show_of_hidable_message_types(self, manager, config):
        template = make_styled_template()
        make_group(name="Themes", templates=[template])

        await manager.apply_template_theme(template)

        assert config.appearance.scene.director_messages.show is False

    async def test_leaves_asset_settings_alone(self, manager, config):
        scene_appearance = config.appearance.scene
        scene_appearance.auto_attach_assets = False
        scene_appearance.message_assets["avatar"].cadence = "never"
        assets_before = scene_appearance.message_assets.copy()

        template = make_styled_template()
        make_group(name="Themes", templates=[template])

        await manager.apply_template_theme(template)

        assert config.appearance.scene.narrator_messages.italic is True
        assert config.appearance.scene.auto_attach_assets is False
        assert config.appearance.scene.message_assets == assets_before
        assert config.appearance.scene.message_assets["avatar"].cadence == "never"

    async def test_leaves_color_overrides_alone(self, manager, config):
        config.appearance.scene.narrator_messages.color = "#123456"

        template = make_styled_template()
        make_group(name="Themes", templates=[template])

        await manager.apply_template_theme(template)

        assert config.appearance.scene.narrator_messages.color == "#123456"
        assert config.appearance.scene.narrator_messages.italic is True

    async def test_switching_themes_replaces_the_styling(self, manager, config):
        styled = make_styled_template(name="Styled")
        plain = make_template(name="Plain")
        make_group(name="Themes", templates=[styled, plain])

        await manager.apply_template_theme(styled)

        assert config.appearance.scene.narrator_messages.italic is True

        await manager.apply_template_theme(plain)

        assert config.appearance.scene.narrator_messages.italic is False
        assert config.appearance.scene.quotes.show is True
        assert config.appearance.scene.backdrop_panel_opacity == 0.8

    async def test_theme_with_a_default_appearance_applies(self, manager, config):
        """No part of a theme's appearance is optional - one that leaves it at
        the defaults resets the scene appearance to them."""
        config.appearance.scene.narrator_messages.italic = True
        config.appearance.scene.backdrop_panel_opacity = 0.35

        template = make_template(name="Bare")
        group = make_group(name="Themes", templates=[template])

        result = await manager.apply_template_theme(template)

        assert result.theme_id == f"{group.uid}__{template.uid}"
        assert config.appearance.scene == SceneAppearance()

    def test_appearance_defaults_are_copied_alongside_the_declared_styling(self):
        """A theme declares every appearance field - the ones it leaves at
        their default are copied too, that is what makes a switch replace the
        previous theme's styling instead of layering onto it."""
        scene_appearance = SceneAppearance()
        scene_appearance.narrator_messages.color = "#123456"
        scene_appearance.quotes.show = False

        appearance = ThemeAppearance(
            narrator=ThemeMessageStyle(italic=True, bold=True),
            backdrop_text_shadow=False,
        )

        apply_theme_appearance(appearance, scene_appearance)

        assert scene_appearance.narrator_messages.italic is True
        assert scene_appearance.narrator_messages.bold is True
        assert scene_appearance.narrator_messages.color == "#123456"
        assert scene_appearance.backdrop_text_shadow is False
        assert scene_appearance.quotes.show is True
        assert scene_appearance.backdrop_panel_opacity == 0.8

    def test_every_appearance_field_is_mapped_to_a_scene_appearance_field(self):
        """The copy reads these attributes directly - a key that only exists on
        one side is a crash, not a silently skipped field. A field missing from
        the map is worse: its styling silently stops being copied, which is why
        the map has to be the whole model rather than a subset of it."""
        assert set(THEME_APPEARANCE_MAP) == set(ThemeAppearance.model_fields)

        for config_key in THEME_APPEARANCE_MAP.values():
            assert config_key in SceneAppearance.model_fields


# ---------------------------------------------------------------------------
# websocket handlers
# ---------------------------------------------------------------------------


class MockWebsocketHandler:
    """Stand-in for `WebsocketHandler`.

    `on_config_changed` is the app_config push the frontend repaints from - it
    is taken from the real handler rather than reimplemented, and connected to
    `config.changed` the same way, so a test can assert on what the running app
    would actually receive. It only needs `queue_put`.
    """

    on_config_changed = WebsocketHandler.on_config_changed

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


@pytest.fixture
def plugin(config, collection_loads) -> WorldStateManagerPlugin:
    handler = MockWebsocketHandler(MockScene())
    async_signals.get("config.changed").connect(handler.on_config_changed)
    return WorldStateManagerPlugin(handler)


def install_group(plugin, template_dir, templates) -> Group:
    """Puts a saved group in front of the plugin - the handlers write the group
    file back out, so it needs a path inside the test's template dir."""
    group = make_group(name="Themes", templates=templates)
    group.save(template_dir)
    plugin.scene._world_state_templates = Collection(groups=[group])
    return group


def saved_theme():
    with open(config_state.CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)["appearance"].get("theme")


class TestApplyTemplateHandler:
    async def test_applying_a_theme_completes(
        self, plugin, config, template_dir, status_messages
    ):
        template = make_template()
        group = install_group(plugin, template_dir, [template])

        task = await plugin.handle_apply_template({"template": template.model_dump()})
        await task

        applied = plugin.websocket_handler.find("template_applied")
        assert applied["result"] == {
            "theme_id": f"{group.uid}__{template.uid}",
            "name": "Midnight",
        }
        assert config.appearance.theme == f"{group.uid}__{template.uid}"
        assert [e.message for e in status_messages if e.status == "error"] == []

    async def test_applying_a_theme_refreshes_and_signals_done(
        self, plugin, config, template_dir
    ):
        template = make_template()
        install_group(plugin, template_dir, [template])

        task = await plugin.handle_apply_template({"template": template.model_dump()})
        await task

        assert "templates" in plugin.websocket_handler.actions
        assert "operation_done" in plugin.websocket_handler.actions

    async def test_applying_a_theme_through_apply_templates_completes(
        self, plugin, config, template_dir, status_messages
    ):
        template = make_template()
        group = install_group(plugin, template_dir, [template])

        task = await plugin.handle_apply_templates(
            {"templates": [template.model_dump()]}
        )
        await task

        applied = plugin.websocket_handler.find("template_applied")
        assert applied["result"]["theme_id"] == f"{group.uid}__{template.uid}"
        assert "templates_applied" in plugin.websocket_handler.actions
        assert [e.message for e in status_messages if e.status == "error"] == []


class TestApplyingAThemeLeavesTheSceneAlone:
    """
    A theme writes the application config and nothing else, so the completion
    of an apply must not reach the scene. The switcher in the app bar makes it
    a single unconfirmed click, so an auto-save on every theme pick would write
    the scene file behind the user's back.
    """

    @pytest.fixture
    def scene_writes(self, plugin, monkeypatch) -> list:
        """
        Records `Scene.save` calls. The call is what is asserted on, not what
        save does: an unsaved scene has no filename and save returns early, so
        watching the file would pass with the fix reverted.
        """
        calls = []

        async def record(*args, **kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(plugin.scene, "save", record)
        monkeypatch.setattr(plugin.scene, "emit_status", lambda *a, **kw: None)
        return calls

    async def test_a_theme_apply_does_not_auto_save_the_scene(
        self, plugin, config, template_dir, scene_writes
    ):
        config.game.general.auto_save = True
        plugin.scene.saved = True
        template = make_template()
        install_group(plugin, template_dir, [template])

        task = await plugin.handle_apply_template({"template": template.model_dump()})
        await task

        assert scene_writes == []
        assert plugin.scene.saved is True

    async def test_a_theme_apply_does_not_mark_the_scene_unsaved(
        self, plugin, config, template_dir, scene_writes
    ):
        config.game.general.auto_save = False
        plugin.scene.saved = True
        template = make_template()
        install_group(plugin, template_dir, [template])

        task = await plugin.handle_apply_template({"template": template.model_dump()})
        await task

        assert plugin.scene.saved is True

    async def test_a_template_that_is_not_a_theme_still_reaches_the_scene(
        self, plugin, config, template_dir, scene_writes
    ):
        """The exception is theme-shaped - every other type still completes the
        way it always has."""
        config.game.general.auto_save = False
        plugin.scene.saved = True
        template = VisualStyle(name="Painterly")

        task = await plugin.handle_apply_template({"template": template.model_dump()})
        await task

        assert plugin.scene.saved is False


class TestSaveTemplateHandler:
    async def test_saving_the_active_theme_repushes_app_config(
        self, plugin, config, template_dir
    ):
        """The push has to carry the edited colors - that is what repaints the
        running app, a push of the config alone leaves it on the old theme."""
        template = make_template(colors={"app": {"primary": "#123456"}})
        group = install_group(plugin, template_dir, [template])
        config.appearance.theme = f"{group.uid}__{template.uid}"

        edited = template.model_copy(deep=True)
        edited.colors.app.primary = "#654321"

        await plugin.handle_save_template({"template": edited.model_dump()})

        pushed = plugin.websocket_handler.find("app_config")
        assert pushed["data"]["theme"]["colors"]["app"]["primary"] == "#654321"

    async def test_saving_a_theme_invalidates_the_resolve_cache(
        self, plugin, config, template_dir, collection_loads
    ):
        template = make_template(colors={"app": {"primary": "#123456"}})
        group = install_group(plugin, template_dir, [template])
        config.appearance.theme = f"{group.uid}__{template.uid}"

        assert resolve_theme(config)["colors"]["app"]["primary"] == "#123456"

        edited = template.model_copy(deep=True)
        edited.colors.app.primary = "#654321"
        await plugin.handle_save_template({"template": edited.model_dump()})

        assert resolve_theme(config)["colors"]["app"]["primary"] == "#654321"

    async def test_saving_an_unknown_code_editor_theme_is_rejected(
        self, plugin, config, template_dir
    ):
        """A theme read off disk repairs an editor theme id this version does
        not know, but a save naming one is a bad payload - accepting it would
        silently persist the fallback over what the client asked for."""
        template = make_template(code_editor="nord")
        group = install_group(plugin, template_dir, [template])
        config.appearance.theme = f"{group.uid}__{template.uid}"

        edited = template.model_dump()
        edited["code_editor"] = "github-ligth"

        with pytest.raises(pydantic.ValidationError, match="Unknown code editor"):
            await plugin.handle_save_template({"template": edited})

        assert Group.load(group.path).templates[template.uid].code_editor == "nord"

    async def test_saving_another_theme_does_not_repush_app_config(
        self, plugin, config, template_dir
    ):
        active = make_template(name="Active")
        other = make_template(name="Other")
        group = install_group(plugin, template_dir, [active, other])
        config.appearance.theme = f"{group.uid}__{active.uid}"

        await plugin.handle_save_template({"template": other.model_dump()})

        assert "app_config" not in plugin.websocket_handler.actions


class TestDeleteTemplateHandler:
    async def test_deleting_the_active_theme_clears_it(
        self, plugin, config, template_dir
    ):
        template = make_template()
        group = install_group(plugin, template_dir, [template])
        config.appearance.theme = f"{group.uid}__{template.uid}"

        await plugin.handle_delete_template({"template": template.model_dump()})

        assert config.appearance.theme is None
        assert saved_theme() is None
        assert "app_config" in plugin.websocket_handler.actions

    async def test_deleting_another_theme_leaves_the_active_one(
        self, plugin, config, template_dir
    ):
        active = make_template(name="Active")
        other = make_template(name="Other")
        group = install_group(plugin, template_dir, [active, other])
        config.appearance.theme = f"{group.uid}__{active.uid}"

        await plugin.handle_delete_template({"template": other.model_dump()})

        assert config.appearance.theme == f"{group.uid}__{active.uid}"
        assert "app_config" not in plugin.websocket_handler.actions

    async def test_deleting_a_non_theme_template_leaves_the_active_theme(
        self, plugin, config, template_dir
    ):
        theme = make_template()
        shortcut = SceneToolShortcutTemplate(
            name="Push On",
            action_id="narrator.progress",
            label="Push on",
            icon="mdi-script-text",
        )
        group = install_group(plugin, template_dir, [theme, shortcut])
        config.appearance.theme = f"{group.uid}__{theme.uid}"

        await plugin.handle_delete_template({"template": shortcut.model_dump()})

        assert config.appearance.theme == f"{group.uid}__{theme.uid}"
        assert "app_config" not in plugin.websocket_handler.actions


class TestDeleteTemplateGroupHandler:
    async def test_deleting_the_group_of_the_active_theme_clears_it(
        self, plugin, config, template_dir
    ):
        template = make_template()
        group = install_group(plugin, template_dir, [template])
        config.appearance.theme = f"{group.uid}__{template.uid}"

        await plugin.handle_delete_template_group({"group": group.model_dump()})

        assert config.appearance.theme is None
        assert saved_theme() is None
        assert "app_config" in plugin.websocket_handler.actions

    async def test_deleting_another_group_leaves_the_active_theme(
        self, plugin, config, template_dir
    ):
        template = make_template()
        group = install_group(plugin, template_dir, [template])
        other = make_group(name="Other")
        other.save(template_dir)
        plugin.scene._world_state_templates.groups.append(other)
        config.appearance.theme = f"{group.uid}__{template.uid}"

        await plugin.handle_delete_template_group({"group": other.model_dump()})

        assert config.appearance.theme == f"{group.uid}__{template.uid}"
        assert "app_config" not in plugin.websocket_handler.actions
