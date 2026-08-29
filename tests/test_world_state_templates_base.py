"""
Unit tests for `talemate.world_state.templates.base` covering the parts
not exercised by `tests/test_world_state_templates.py`:

- `Template.formatted` (player_name / character_name interpolation, falsy values)
- `Group.sanitize_data` malformed-input branches
- `Collection.flat_by_template_uid_only`
- `Collection.typed`
- `TypedCollection.find_by_name`
- `Collection.create_from_legacy_config`
"""

import os

import pytest
import yaml

from _world_state_helpers import scene  # noqa: F401 - pytest fixture
from _world_state_helpers import make_actor
from talemate.world_state.templates.base import (
    Collection,
    FlatCollection,
    Group,
    Priority,
    name_to_id,
)
from talemate.world_state.templates.state_reinforcement import StateReinforcement


def make_state_template(**overrides) -> StateReinforcement:
    defaults = dict(
        name="Test",
        template_type="state_reinforcement",
        query="What is {character_name}'s mood?",
        state_type="npc",
        priority=1,
    )
    defaults.update(overrides)
    return StateReinforcement(**defaults)


def make_group(name="g", templates=None, **kw) -> Group:
    g = Group(author="a", name=name, description="d", **kw)
    if templates:
        for t in templates:
            g.insert_template(t, save=False)
    return g


# ---------------------------------------------------------------------------
# name_to_id
# ---------------------------------------------------------------------------


class TestNameToId:
    def test_replaces_spaces_with_underscore_and_lowercases(self):
        assert name_to_id("Foo Bar Baz") == "foo_bar_baz"

    def test_already_lowercase(self):
        assert name_to_id("simple") == "simple"


# ---------------------------------------------------------------------------
# Template.formatted
# ---------------------------------------------------------------------------


class TestTemplateFormatted:
    def test_returns_falsy_value_unchanged(self, scene):
        t = make_state_template()
        t.instructions = None
        # None -> returned as-is (not formatted)
        assert t.formatted("instructions", scene, "Alice") is None

    def test_returns_empty_string_unchanged(self, scene):
        t = make_state_template()
        t.instructions = ""
        assert t.formatted("instructions", scene, "Alice") == ""

    def test_interpolates_character_name(self, scene):
        t = make_state_template(query="What is {character_name}'s mood?")
        result = t.formatted("query", scene, "Alice")
        assert result == "What is Alice's mood?"

    def test_interpolates_player_name(self, scene):
        # Add a player character so player_name is populated
        make_actor(scene, "Hero", is_player=True)
        t = make_state_template(query="Player is {player_name}.")
        result = t.formatted("query", scene, character_name=None)
        assert result == "Player is Hero."

    def test_player_name_none_when_no_player(self, scene):
        # No player added — player_name should be None
        t = make_state_template(query="Player is {player_name}.")
        # str.format with None -> "None"
        result = t.formatted("query", scene, character_name=None)
        assert result == "Player is None."

    def test_extra_vars_kwargs(self, scene):
        t = make_state_template(query="{custom}")
        result = t.formatted("query", scene, "Alice", custom="extra-value")
        assert result == "extra-value"

    def test_literal_braces_fall_back_to_raw_text(self, scene):
        # user-authored text with braces that aren't placeholders (JSON
        # examples, unknown fields) must render raw, not raise
        t = make_state_template(query='Emit JSON like {"mood": "dark"}.')
        assert (
            t.formatted("query", scene, "Alice") == 'Emit JSON like {"mood": "dark"}.'
        )

    def test_unknown_placeholder_falls_back_to_raw_text(self, scene):
        t = make_state_template(query="Use a {tone} voice for {character_name}.")
        # one bad field poisons the whole format call - the raw text comes
        # back, known placeholders included
        assert (
            t.formatted("query", scene, "Alice")
            == "Use a {tone} voice for {character_name}."
        )

    def test_compound_attribute_field_falls_back_to_raw_text(self, scene):
        # str.format only raises KeyError when the FIRST field component
        # misses - {character_name.first} resolves character_name and then
        # raises AttributeError on the str
        t = make_state_template(query="Refer to {character_name.first} only.")
        assert (
            t.formatted("query", scene, "Alice")
            == "Refer to {character_name.first} only."
        )

    def test_compound_index_field_on_none_falls_back_to_raw_text(self, scene):
        # player_name is None in a scene without a player character - the
        # same template renders fine in one scene and raised TypeError in
        # another, by scene state rather than syntax
        t = make_state_template(query="Use {player_name[0]} as the initial.")
        assert (
            t.formatted("query", scene, "Alice")
            == "Use {player_name[0]} as the initial."
        )


# ---------------------------------------------------------------------------
# Priority enum + Template.priority field
# ---------------------------------------------------------------------------


class TestPriority:
    def test_priority_enum_values(self):
        assert int(Priority.low) == 1
        assert int(Priority.medium) == 2
        assert int(Priority.high) == 3

    def test_template_default_priority_is_int_one(self):
        t = make_state_template()
        assert t.priority == 1


# ---------------------------------------------------------------------------
# validate_template (used by AnnotatedTemplate)
# ---------------------------------------------------------------------------


class TestValidateTemplate:
    def test_unknown_template_type_raises_via_dict(self):
        # Round-trip via Group -> AnnotatedTemplate dict path
        with pytest.raises(ValueError, match="not registered"):
            Group(
                author="a",
                name="g",
                description="d",
                templates={
                    "tid": {
                        "name": "x",
                        "template_type": "no-such-type",
                        "uid": "tid",
                    }
                },
            )

    def test_known_template_type_works(self):
        g = Group(
            author="a",
            name="g",
            description="d",
            templates={
                "tid": {
                    "name": "x",
                    "template_type": "state_reinforcement",
                    "query": "q",
                    "uid": "tid",
                    "state_type": "npc",
                    "priority": 1,
                }
            },
        )
        assert "tid" in g.templates
        assert g.templates["tid"].template_type == "state_reinforcement"


# ---------------------------------------------------------------------------
# Group.sanitize_data - malformed YAML data branches
# ---------------------------------------------------------------------------


class TestSanitizeData:
    def _write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f)
        return path

    def test_loads_with_missing_uid_assigns_one(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path, {"author": "a", "name": "n", "description": "d", "templates": {}}
        )
        g = Group.load(path)
        assert g.uid  # assigned a new uuid

    def test_loads_with_missing_name_assigns_uid_prefix(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": "a",
                "name": None,
                "description": "d",
                "templates": {},
                "uid": "abcdefghijkl",
            },
        )
        g = Group.load(path)
        assert g.name == "abcdefgh"

    def test_loads_with_null_description_and_author(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": None,
                "name": "n",
                "description": None,
                "templates": {},
            },
        )
        g = Group.load(path)
        assert g.description == ""
        assert g.author == ""

    def test_loads_drops_null_template(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": "a",
                "name": "n",
                "description": "d",
                "templates": {"tid": None},
                "uid": "g-uid",
            },
        )
        g = Group.load(path)
        assert g.templates == {}

    def test_loads_assigns_template_uid_from_key(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": "a",
                "name": "n",
                "description": "d",
                "templates": {
                    "key1": {
                        "name": "named",
                        "template_type": "state_reinforcement",
                        "query": "q",
                        "state_type": "npc",
                    }
                },
                "uid": "g-uid",
            },
        )
        g = Group.load(path)
        assert "key1" in g.templates
        assert g.templates["key1"].uid == "key1"
        # template.group should match the group's uid
        assert g.templates["key1"].group == "g-uid"

    def test_loads_assigns_template_name_from_key(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": "a",
                "name": "n",
                "description": "d",
                "templates": {
                    "abcdefghijkl": {
                        "template_type": "state_reinforcement",
                        "query": "q",
                        "state_type": "npc",
                    }
                },
                "uid": "g-uid",
            },
        )
        g = Group.load(path)
        # name was missing -> set to first 8 chars of template_id
        assert g.templates["abcdefghijkl"].name == "abcdefgh"

    def test_loads_drops_template_with_missing_template_type(self, template_dir):
        # A template with no `template_type` field should be dropped (the
        # missing-type branch deletes and `continue`s, so it doesn't fall
        # into the invalid-type branch and double-delete).
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": "a",
                "name": "n",
                "description": "d",
                "templates": {
                    "tid1": {
                        "name": "no-type",
                        "uid": "tid1",
                        # template_type intentionally absent
                    }
                },
                "uid": "g-uid",
            },
        )
        g = Group.load(path)
        assert "tid1" not in g.templates

    def test_loads_drops_template_with_invalid_template_type(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": "a",
                "name": "n",
                "description": "d",
                "templates": {
                    "tid1": {
                        "name": "bad",
                        "template_type": "no_such_type",
                        "uid": "tid1",
                    }
                },
                "uid": "g-uid",
            },
        )
        g = Group.load(path)
        assert "tid1" not in g.templates

    def test_loads_with_non_int_priority_falls_back_to_one(self, template_dir):
        path = os.path.join(template_dir, "g.yaml")
        self._write(
            path,
            {
                "author": "a",
                "name": "n",
                "description": "d",
                "templates": {
                    "tid": {
                        "name": "x",
                        "template_type": "state_reinforcement",
                        "query": "q",
                        "state_type": "npc",
                        "priority": "not-a-number",
                        "uid": "tid",
                    }
                },
                "uid": "g-uid",
            },
        )
        g = Group.load(path)
        assert g.templates["tid"].priority == 1


# ---------------------------------------------------------------------------
# Collection.flat_by_template_uid_only
# ---------------------------------------------------------------------------


class TestFlatByTemplateUidOnly:
    def test_keys_are_template_uids_only(self):
        t1 = make_state_template(name="T1")
        t2 = make_state_template(name="T2")
        g1 = make_group(name="g1", templates=[t1])
        g2 = make_group(name="g2", templates=[t2])
        col = Collection(groups=[g1, g2])

        flat = col.flat_by_template_uid_only()
        assert isinstance(flat, FlatCollection)
        assert set(flat.templates.keys()) == {t1.uid, t2.uid}


# ---------------------------------------------------------------------------
# Collection.typed
# ---------------------------------------------------------------------------


class TestTypedCollection:
    def test_groups_templates_by_type(self):
        from talemate.world_state.templates.agent import AgentPersona

        sr = make_state_template()
        ap = AgentPersona(name="P", template_type="agent_persona")
        g = make_group(name="g", templates=[sr, ap])
        col = Collection(groups=[g])

        typed = col.typed()
        assert "state_reinforcement" in typed.templates
        assert "agent_persona" in typed.templates
        assert len(typed.templates["state_reinforcement"]) == 1
        assert len(typed.templates["agent_persona"]) == 1

    def test_typed_filter_by_types(self):
        from talemate.world_state.templates.agent import AgentPersona

        sr = make_state_template()
        ap = AgentPersona(name="P", template_type="agent_persona")
        g = make_group(name="g", templates=[sr, ap])
        col = Collection(groups=[g])

        typed = col.typed(types=["agent_persona"])
        assert "agent_persona" in typed.templates
        assert "state_reinforcement" not in typed.templates


class TestTypedCollectionFindByName:
    def test_finds_existing(self):
        sr = make_state_template(name="MoodCheck")
        g = make_group(name="g", templates=[sr])
        col = Collection(groups=[g])
        typed = col.typed()
        found = typed.find_by_name("MoodCheck")
        assert found is sr

    def test_returns_none_when_not_found(self):
        col = Collection(groups=[])
        typed = col.typed()
        assert typed.find_by_name("nope") is None


# ---------------------------------------------------------------------------
# Collection.create_from_legacy_config
# ---------------------------------------------------------------------------


class TestCreateFromLegacyConfig:
    def test_legacy_config_creates_groups(self, monkeypatch, tmp_path):
        """Passes a synthetic Config-like object whose
        game.world_state.templates has a dict the migrator can convert."""

        # Redirect TEMPLATE_PATH_TALEMATE so we don't pollute real templates
        monkeypatch.setattr(
            "talemate.world_state.templates.base.TEMPLATE_PATH_TALEMATE",
            str(tmp_path),
        )

        # Build a minimal legacy "config" structure: an object exposing
        # config.game.world_state.templates that .model_dump()s to a
        # {template_type: {uid: template_dict}} mapping.
        class Templates:
            def model_dump(self):
                return {
                    "state_reinforcement": {
                        "mood": {
                            "name": "Mood",
                            "query": "q",
                            "state_type": "npc",
                            "template_type": "state_reinforcement",
                            "priority": 1,
                        }
                    }
                }

        class WorldState:
            def __init__(self):
                self.templates = Templates()

        class Game:
            def __init__(self):
                self.world_state = WorldState()

        class Config:
            def __init__(self):
                self.game = Game()

        col = Collection.create_from_legacy_config(
            Config(), save=False, check_if_exists=False
        )
        # Our group should be present
        assert any(g.name == "legacy-state-reinforcements" for g in col.groups), [
            g.name for g in col.groups
        ]

    def test_legacy_config_skips_existing(self, monkeypatch, tmp_path):
        # Pre-create a yaml file with the expected legacy name.
        existing_path = os.path.join(str(tmp_path), "legacy-state-reinforcements.yaml")
        with open(existing_path, "w") as f:
            yaml.dump(
                {
                    "author": "x",
                    "name": "legacy-state-reinforcements",
                    "description": "",
                    "templates": {},
                    "uid": "existing",
                },
                f,
            )

        monkeypatch.setattr(
            "talemate.world_state.templates.base.TEMPLATE_PATH_TALEMATE",
            str(tmp_path),
        )

        class Templates:
            def model_dump(self):
                return {
                    "state_reinforcement": {
                        "mood": {
                            "name": "Mood",
                            "query": "q",
                            "state_type": "npc",
                            "template_type": "state_reinforcement",
                            "priority": 1,
                        }
                    }
                }

        class WorldState:
            def __init__(self):
                self.templates = Templates()

        class Game:
            def __init__(self):
                self.world_state = WorldState()

        class Config:
            def __init__(self):
                self.game = Game()

        col = Collection.create_from_legacy_config(
            Config(), save=False, check_if_exists=True
        )
        # No new groups added (skipped)
        assert all(g.name != "legacy-state-reinforcements" for g in col.groups)


# ---------------------------------------------------------------------------
# Group.update with ignore_templates=False
# ---------------------------------------------------------------------------


class TestGroupUpdateTemplates:
    def test_update_with_ignore_templates_false_replaces(self, tmp_path):
        t1 = make_state_template(name="T1")
        original = make_group(templates=[t1])
        original.save(str(tmp_path))

        t2 = make_state_template(name="T2")
        replacement = make_group(templates=[t2])

        original.update(replacement, ignore_templates=False)
        # Original now contains t2 (template list replaced)
        assert t2.uid in original.templates
        assert t1.uid not in original.templates


# ---------------------------------------------------------------------------
# Group.diff exception path - regression: group field is restored
# ---------------------------------------------------------------------------


class TestGroupDiffRestoresGroupField:
    def test_diff_restores_template_group_field(self):
        t = make_state_template(name="X")
        g1 = make_group(name="g1", templates=[t])
        for tt in g1.templates.values():
            tt.group = g1.uid

        g2 = make_group(name="g2")
        g2.uid = "different-uid"

        # Run diff (raises nothing). Verify group field is unchanged after.
        original_group = t.group
        g1.diff(g2)
        assert t.group == original_group
