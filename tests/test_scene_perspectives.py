"""
Tests for the ScenePerspectives schema, the legacy migration path, and the
role-aware behavior of the perspective context ID family.
"""

from unittest.mock import Mock

import pytest

from conftest import MockScene
from talemate.scene.schema import ScenePerspectives
from talemate.game.engine.context_id.story_configuration import (
    PERSPECTIVE_ROLES,
    ScenePerspectiveContextID,
    StoryConfigurationContext,
    StoryConfigurationContextItem,
)
from talemate.game.engine.context_id.base import (
    context_id_item_from_string,
)


# ---------------------------------------------------------------------------
# ScenePerspectives schema
# ---------------------------------------------------------------------------


class TestScenePerspectivesSchema:
    def test_defaults_to_empty_strings(self):
        p = ScenePerspectives()
        assert p.default == ""
        assert p.player == ""
        assert p.other == ""
        assert p.narrator == ""

    def test_for_role_default(self):
        p = ScenePerspectives(default="Third person")
        assert p.for_role("default") == "Third person"
        assert p.for_role(None) == "Third person"

    def test_for_role_specific_overrides_default(self):
        p = ScenePerspectives(
            default="Third person",
            player="First person, present tense",
            narrator="Omniscient narrator voice",
        )
        assert p.for_role("player") == "First person, present tense"
        assert p.for_role("narrator") == "Omniscient narrator voice"

    def test_for_role_falls_back_to_default_when_role_empty(self):
        p = ScenePerspectives(default="Third person")
        assert p.for_role("player") == "Third person"
        assert p.for_role("other") == "Third person"
        assert p.for_role("narrator") == "Third person"

    def test_for_role_empty_default_returns_empty(self):
        p = ScenePerspectives()
        assert p.for_role("player") == ""
        assert p.for_role("default") == ""

    def test_for_role_unknown_role_falls_back_to_default(self):
        p = ScenePerspectives(default="Third person")
        assert p.for_role("bogus") == "Third person"

    def test_for_role_whitespace_only_override_treated_as_empty(self):
        p = ScenePerspectives(default="Third person", player="   \t  \n")
        assert p.for_role("player") == "Third person"

    def test_for_role_strips_surrounding_whitespace(self):
        p = ScenePerspectives(default="  Third person  ", player="\tFirst person\n")
        assert p.for_role("default") == "Third person"
        assert p.for_role("player") == "First person"

    def test_model_dump_serializes_all_four_fields(self):
        p = ScenePerspectives(default="A", player="B", other="C", narrator="D")
        assert p.model_dump() == {
            "default": "A",
            "player": "B",
            "other": "C",
            "narrator": "D",
        }


# ---------------------------------------------------------------------------
# Scene migration: legacy `perspective` string → `perspectives.default`
# ---------------------------------------------------------------------------


class TestSceneMigration:
    def test_scene_has_perspectives_object_by_default(self):
        scene = MockScene()
        assert isinstance(scene.perspectives, ScenePerspectives)
        assert scene.perspectives.default == ""

    def test_legacy_perspective_string_migrates_into_default(self):
        from talemate.load import load_scene_perspectives

        scene_data = {"perspective": "Third person, past tense."}
        result = load_scene_perspectives(scene_data)
        assert isinstance(result, ScenePerspectives)
        assert result.default == "Third person, past tense."
        assert result.player == ""
        assert result.other == ""
        assert result.narrator == ""

    def test_nested_perspectives_preferred_over_legacy(self):
        from talemate.load import load_scene_perspectives

        scene_data = {
            "perspective": "legacy",
            "perspectives": {
                "default": "nested-default",
                "player": "nested-player",
                "other": "",
                "narrator": "",
            },
        }
        result = load_scene_perspectives(scene_data)
        assert result.default == "nested-default"
        assert result.player == "nested-player"

    def test_missing_perspective_yields_empty_default(self):
        from talemate.load import load_scene_perspectives

        result = load_scene_perspectives({})
        assert result.default == ""
        assert result.player == ""
        assert result.other == ""
        assert result.narrator == ""

    def test_none_legacy_perspective_yields_empty_default(self):
        from talemate.load import load_scene_perspectives

        result = load_scene_perspectives({"perspective": None})
        assert result.default == ""


# ---------------------------------------------------------------------------
# Role-aware context ID paths
# ---------------------------------------------------------------------------


@pytest.fixture
def scene_with_perspectives():
    scene = MockScene()
    scene.perspectives = ScenePerspectives(
        default="DEF",
        player="PLY",
        other="OTH",
        narrator="NAR",
    )
    return scene


class TestPerspectiveContextIDPaths:
    def test_default_alias_resolves_to_default_role(self, scene_with_perspectives):
        cid = ScenePerspectiveContextID.make()
        assert cid.path == ["perspective"]
        assert cid.role == "default"
        assert cid.path_to_str == "story_configuration:perspective"

    def test_role_specific_path(self):
        cid = ScenePerspectiveContextID.make(role="player")
        assert cid.path == ["perspective", "player"]
        assert cid.role == "player"
        assert cid.path_to_str == "story_configuration:perspective.player"

    def test_default_role_kwarg_collapses_to_legacy_path(self):
        cid = ScenePerspectiveContextID.make(role="default")
        assert cid.path == ["perspective"]
        assert cid.role == "default"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("default", "DEF"),
            ("player", "PLY"),
            ("other", "OTH"),
            ("narrator", "NAR"),
        ],
    )
    async def test_get_each_role_via_context_id(
        self, scene_with_perspectives, role, expected
    ):
        path = ["perspective"] if role == "default" else ["perspective", role]
        path_str = (
            "story_configuration:perspective"
            if role == "default"
            else f"story_configuration:perspective.{role}"
        )
        handler = StoryConfigurationContext.instance_from_path(
            path, scene_with_perspectives
        )
        item = await handler.context_id_item_from_path(
            "story_configuration", path, path_str, scene_with_perspectives
        )
        assert item is not None
        value = await item.get(scene_with_perspectives)
        assert value == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", PERSPECTIVE_ROLES)
    async def test_set_each_role_via_context_id(self, scene_with_perspectives, role):
        path = ["perspective"] if role == "default" else ["perspective", role]
        path_str = (
            "story_configuration:perspective"
            if role == "default"
            else f"story_configuration:perspective.{role}"
        )
        handler = StoryConfigurationContext.instance_from_path(
            path, scene_with_perspectives
        )
        item = await handler.context_id_item_from_path(
            "story_configuration", path, path_str, scene_with_perspectives
        )
        new_value = f"new-{role}"
        await item.set(scene_with_perspectives, new_value)
        assert getattr(scene_with_perspectives.perspectives, role) == new_value

    @pytest.mark.asyncio
    async def test_unknown_role_returns_none(self, scene_with_perspectives):
        handler = StoryConfigurationContext.instance_from_path(
            ["perspective", "bogus"], scene_with_perspectives
        )
        item = await handler.context_id_item_from_path(
            "story_configuration",
            ["perspective", "bogus"],
            "story_configuration:perspective.bogus",
            scene_with_perspectives,
        )
        assert item is None

    @pytest.mark.asyncio
    async def test_role_specific_fallback_to_default_when_empty(self):
        """An empty role-specific override returns the default, not empty string."""
        scene = MockScene()
        scene.perspectives = ScenePerspectives(default="DEF")
        # No `player` override.
        item = await context_id_item_from_string(
            "story_configuration:perspective.player", scene
        )
        assert item is not None
        value = await item.get(scene)
        assert value == "DEF"


# ---------------------------------------------------------------------------
# StoryConfigurationContextItem human_id / context_id consistency
# ---------------------------------------------------------------------------


class TestScenePerspectiveForRole:
    """
    Scene.perspective_for_role resolves the role-specific value AND substitutes
    {player_name} against the current player character at call time, so a
    rename takes effect immediately without rewriting saved data.
    """

    def _make_scene_with_player(self, player_name: str) -> MockScene:
        from talemate.tale_mate import Player
        from talemate.character import Character

        scene = MockScene()
        character = Character(name=player_name, is_player=True, description="x")
        actor = Player(character=character, agent=None)
        scene.actors.append(actor)
        return scene

    def test_substitutes_player_name(self):
        scene = self._make_scene_with_player("Vincent")
        scene.perspectives = ScenePerspectives(
            default="Second person, present tense. Talking to {player_name}."
        )
        assert (
            scene.perspective_for_role("default")
            == "Second person, present tense. Talking to Vincent."
        )

    def test_substitution_survives_rename(self):
        scene = self._make_scene_with_player("Vincent")
        scene.perspectives = ScenePerspectives(default="Talking to {player_name}.")
        # Rename the player character; perspective_for_role should reflect it.
        scene.get_player_character().name = "Alice"
        assert scene.perspective_for_role("default") == "Talking to Alice."

    def test_substitutes_multiple_occurrences(self):
        scene = self._make_scene_with_player("Vincent")
        scene.perspectives = ScenePerspectives(
            default="{player_name}'s POV — describe everything from {player_name}'s vantage."
        )
        assert (
            scene.perspective_for_role("default")
            == "Vincent's POV — describe everything from Vincent's vantage."
        )

    def test_no_placeholder_returns_value_unchanged(self):
        scene = self._make_scene_with_player("Vincent")
        scene.perspectives = ScenePerspectives(default="Third person limited.")
        assert scene.perspective_for_role("default") == "Third person limited."

    def test_empty_perspective_returns_empty(self):
        scene = self._make_scene_with_player("Vincent")
        assert scene.perspective_for_role("default") == ""

    def test_role_specific_resolved_with_placeholder(self):
        scene = self._make_scene_with_player("Vincent")
        scene.perspectives = ScenePerspectives(
            default="Third person.",
            narrator="Second person, present tense. Talking to {player_name}.",
        )
        assert scene.perspective_for_role("narrator") == (
            "Second person, present tense. Talking to Vincent."
        )
        assert scene.perspective_for_role("default") == "Third person."

    def test_fallback_to_default_resolves_player_name(self):
        scene = self._make_scene_with_player("Vincent")
        scene.perspectives = ScenePerspectives(
            default="Third person, focused on {player_name}'s POV."
        )
        # player role is empty → falls back to default, AND substitutes.
        assert (
            scene.perspective_for_role("player")
            == "Third person, focused on Vincent's POV."
        )

    def test_no_player_character_suppresses_perspective_with_placeholder(self):
        """
        A perspective that references {player_name} but has no anchor to
        substitute is unrenderable as prose ("Talking to the player." reads
        as garbage), so the resolver returns "" — i.e. no perspective line
        is injected at all.
        """
        scene = MockScene()
        scene.perspectives = ScenePerspectives(default="Talking to {player_name}.")
        assert scene.perspective_for_role("default") == ""

    def test_npcs_but_no_player_still_suppresses_placeholder_perspective(self):
        """
        Scene.get_player_character() falls back to the first NPC when no
        Player is registered. The placeholder substitution must use
        get_explicit_player_character() instead so an NPC's name never
        accidentally ends up substituted for `{player_name}`.
        """
        from talemate.tale_mate import Actor
        from talemate.character import Character

        scene = MockScene()
        npc = Character(name="Villainous Vince", is_player=False, description="x")
        scene.actors.append(Actor(character=npc, agent=None))
        scene.perspectives = ScenePerspectives(default="Talking to {player_name}.")
        assert scene.perspective_for_role("default") == ""

    def test_no_player_keeps_perspective_without_placeholder(self):
        """A perspective with no placeholder is returned as-is even with no player."""
        scene = MockScene()
        scene.perspectives = ScenePerspectives(default="Third person limited.")
        assert scene.perspective_for_role("default") == "Third person limited."


class TestStoryConfigurationContextItemRole:
    def test_role_default_produces_legacy_context_id(self):
        item = StoryConfigurationContextItem(
            context_type="perspective",
            name="perspective",
            role="default",
            value="x",
        )
        assert item.context_id.path == ["perspective"]
        assert item.context_id.path_to_str == "story_configuration:perspective"

    def test_role_player_produces_keyed_context_id(self):
        item = StoryConfigurationContextItem(
            context_type="perspective",
            name="perspective",
            role="player",
            value="x",
        )
        assert item.context_id.path == ["perspective", "player"]
        assert item.context_id.path_to_str == "story_configuration:perspective.player"


# ---------------------------------------------------------------------------
# Dialogue template — speaker_role resolution from talking_character
# ---------------------------------------------------------------------------


class TestDialogueSpeakerRoleResolution:
    """
    Direct-render the role-resolution snippet from dialogue.jinja2 to make sure
    player vs. NPC are mapped correctly. The narrator never invokes the
    dialogue template (it uses narrator templates), so only two categories
    matter here.
    """

    SNIPPET = (
        "{%- if talking_character.is_player -%}player{%- else -%}other{%- endif -%}"
    )

    @pytest.mark.parametrize(
        "is_player,expected",
        [
            (True, "player"),
            (False, "other"),
        ],
    )
    def test_role_resolution(self, is_player, expected):
        from jinja2 import Environment

        env = Environment()
        tmpl = env.from_string(self.SNIPPET)
        character = Mock()
        character.is_player = is_player
        rendered = tmpl.render(talking_character=character)
        assert rendered == expected
