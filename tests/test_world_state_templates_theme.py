"""
Unit tests for `talemate.world_state.templates.theme`, the shipped theme group
and the manager entry point that activates a theme.

Covers:
- registration / polymorphic deserialization through a Group yaml round-trip
- color validation and malformed templates being dropped instead of exploding
- the shipped "Talemate Dark" group declaring every slot
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
from talemate.world_state.manager import (
    THEME_APPEARANCE_MAP,
    WorldStateManager,
    apply_theme_appearance,
)
from talemate.world_state.templates.base import (
    MODELS,
    TEMPLATE_PATH,
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
)
from talemate.world_state.templates.shortcut import SceneToolShortcutTemplate
from talemate.world_state.templates.theme import (
    AppColors,
    ChatColors,
    MessageColors,
    NodeEditorColors,
    SurfaceColors,
    Theme,
    ThemeAppearance,
    ThemeMessageStyle,
    _find_theme,
    invalidate_theme_cache,
    resolve_theme,
)

SHIPPED_THEMES_PATH = os.path.join(TEMPLATE_PATH_TALEMATE, "themes.yaml")

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
        assert template.colors.node_editor.core_node == "#78909C"
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

    def test_locked_node_selected_matches_core_node(self):
        colors = make_template().colors.node_editor
        assert colors.locked_node_selected == colors.core_node

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
        "model", [AppColors, NodeEditorColors, MessageColors, ChatColors, SurfaceColors]
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


class TestShippedThemeGroup:
    @pytest.fixture
    def shipped(self) -> Group:
        return Group.load(SHIPPED_THEMES_PATH)

    def test_loads(self, shipped):
        (template,) = shipped.templates.values()

        assert type(template) is Theme
        assert template.name == "Talemate Dark"

    def test_uids_are_stable(self, shipped):
        (template,) = shipped.templates.values()

        assert shipped.uid == "talemate_dark"
        assert template.uid == "default"
        assert template.group == shipped.uid

    def test_declares_every_slot(self, shipped):
        with open(SHIPPED_THEMES_PATH, "r") as f:
            raw = yaml.safe_load(f)["templates"]["default"]

        for group_name, model in [
            ("app", AppColors),
            ("node_editor", NodeEditorColors),
            ("messages", MessageColors),
            ("chats", ChatColors),
            ("surfaces", SurfaceColors),
        ]:
            assert set(raw["colors"][group_name]) == set(model.model_fields)

        assert set(raw["appearance"]) == set(ThemeAppearance.model_fields)

    def test_declares_the_surfaces_group_and_the_dark_flag(self, shipped):
        with open(SHIPPED_THEMES_PATH, "r") as f:
            raw = yaml.safe_load(f)["templates"]["default"]

        assert raw["colors"]["surfaces"]["background"] == "#121212"
        assert raw["dark"] is True

        (template,) = shipped.templates.values()

        assert template.colors.surfaces.surface == "#212121"
        assert template.dark is True

    def test_matches_the_built_in_default(self, shipped):
        (template,) = shipped.templates.values()

        assert template.resolved() == Theme(name="Default").resolved()

    def test_is_resolvable_by_id(self, shipped):
        cfg = Config()
        cfg.appearance.theme = f"{shipped.uid}__default"

        resolved = resolve_theme(cfg, collection=Collection(groups=[shipped]))

        assert resolved["colors"]["app"]["primary"] == "#9575CD"

    def test_is_resolvable_from_the_template_directory(self, shipped, monkeypatch):
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
        cfg.appearance.theme = f"{shipped.uid}__default"

        resolved = resolve_theme(cfg)

        assert loads == [TEMPLATE_PATH]
        assert resolved == Theme(name="Default").resolved()

        # walks the directory a second time, so it has to come after `loads`
        found = _find_theme(cfg.appearance.theme, None)

        assert found is not None
        assert found.name == "Talemate Dark"


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


class TestResolveTheme:
    def default(self) -> dict:
        return Theme(name="Default").resolved()

    def test_shape(self):
        resolved = resolve_theme(Config())

        assert set(resolved) == {"colors", "appearance", "dark"}
        assert set(resolved["colors"]) == {
            "app",
            "node_editor",
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
