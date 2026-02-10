"""
Integration tests for world state template Group and Collection file operations.

Tests actual YAML file creation, loading, updating, and deletion under tests/data/templates/.
"""

import os
import shutil

import pytest
import yaml

from talemate.world_state.templates.agent import AgentPersona
from talemate.world_state.templates.base import (
    Collection,
    Group,
)
from talemate.world_state.templates.state_reinforcement import StateReinforcement

TEMPLATE_TEST_PATH = os.path.join(os.path.dirname(__file__), "data", "templates")


@pytest.fixture(autouse=True)
def clean_template_dir():
    """Ensure a clean template directory before and after each test."""
    if os.path.exists(TEMPLATE_TEST_PATH):
        shutil.rmtree(TEMPLATE_TEST_PATH)
    os.makedirs(TEMPLATE_TEST_PATH, exist_ok=True)
    yield
    shutil.rmtree(TEMPLATE_TEST_PATH)


def make_template(**overrides) -> dict:
    """Create a state_reinforcement template dict with sensible defaults."""
    defaults = {
        "name": "Test Template",
        "template_type": "state_reinforcement",
        "query": "What is the character's mood?",
        "state_type": "npc",
        "priority": 1,
    }
    defaults.update(overrides)
    return defaults


def make_group(name="Test Group", templates=None, **overrides) -> Group:
    """Create a Group with optional templates."""
    kwargs = {
        "name": name,
        "author": "Test Author",
        "description": "A test group",
    }
    kwargs.update(overrides)
    group = Group(**kwargs)
    if templates:
        for t in templates:
            group.insert_template(t, save=False)
    return group


class TestGroupSaveAndLoad:
    def test_save_creates_yaml_file(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)

        assert group.path is not None
        assert os.path.exists(group.path)
        assert group.path.endswith(".yaml")

    def test_save_sets_path_on_group(self):
        group = make_group()
        assert group.path is None

        group.save(TEMPLATE_TEST_PATH)

        expected = os.path.join(TEMPLATE_TEST_PATH, "test-group.yaml")
        assert group.path == expected

    def test_save_does_not_overwrite_existing_path(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)
        original_path = group.path

        # Saving again should reuse the same path
        group.save(TEMPLATE_TEST_PATH)
        assert group.path == original_path

    def test_saved_yaml_contains_group_data(self):
        group = make_group(name="My Group", author="Alice", description="desc")
        group.save(TEMPLATE_TEST_PATH)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)

        assert data["name"] == "My Group"
        assert data["author"] == "Alice"
        assert data["description"] == "desc"
        assert data["uid"] == group.uid
        assert "path" not in data  # path should be excluded from YAML

    def test_saved_yaml_contains_templates(self):
        tmpl = StateReinforcement(**make_template(name="Mood Check"))
        group = make_group(templates=[tmpl])
        group.save(TEMPLATE_TEST_PATH)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)

        assert tmpl.uid in data["templates"]
        assert data["templates"][tmpl.uid]["name"] == "Mood Check"
        assert data["templates"][tmpl.uid]["query"] == "What is the character's mood?"

    def test_load_roundtrip(self):
        tmpl = StateReinforcement(**make_template(name="Roundtrip"))
        group = make_group(name="Roundtrip Group", templates=[tmpl])
        group.save(TEMPLATE_TEST_PATH)

        loaded = Group.load(group.path)

        assert loaded.uid == group.uid
        assert loaded.name == "Roundtrip Group"
        assert loaded.author == "Test Author"
        assert loaded.path == group.path
        assert tmpl.uid in loaded.templates
        assert loaded.templates[tmpl.uid].name == "Roundtrip"

    def test_save_assigns_group_uid_to_templates(self):
        tmpl = StateReinforcement(**make_template())
        tmpl.group = None  # explicitly unset
        group = make_group(templates=[tmpl])
        group.save(TEMPLATE_TEST_PATH)

        assert tmpl.group == group.uid

        loaded = Group.load(group.path)
        assert loaded.templates[tmpl.uid].group == group.uid


class TestGroupDelete:
    def test_delete_removes_file(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)
        path = group.path
        assert os.path.exists(path)

        group.delete()
        assert not os.path.exists(path)

    def test_delete_with_none_path_does_not_raise(self):
        group = make_group()
        assert group.path is None
        # Should not raise
        group.delete()

    def test_delete_after_file_already_removed_does_not_raise(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)
        os.remove(group.path)

        # File already gone, should not raise
        group.delete()


class TestGroupUpdate:
    def test_update_changes_metadata(self):
        group = make_group(name="Original")
        group.save(TEMPLATE_TEST_PATH)

        updated = make_group(name="Updated", author="Bob", description="new desc")
        group.update(updated)

        assert group.name == "Updated"
        assert group.author == "Bob"
        assert group.description == "new desc"

        # Verify persisted
        loaded = Group.load(group.path)
        assert loaded.name == "Updated"

    def test_update_ignores_templates_by_default(self):
        tmpl = StateReinforcement(**make_template())
        group = make_group(templates=[tmpl])
        group.save(TEMPLATE_TEST_PATH)

        updated = make_group()  # no templates
        group.update(updated)

        assert tmpl.uid in group.templates


class TestGroupTemplateOperations:
    def test_insert_template(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)

        tmpl = StateReinforcement(**make_template(name="Inserted"))
        group.insert_template(tmpl)

        assert tmpl.uid in group.templates

        # Verify persisted
        loaded = Group.load(group.path)
        assert tmpl.uid in loaded.templates

    def test_insert_duplicate_raises(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)

        tmpl = StateReinforcement(**make_template())
        group.insert_template(tmpl)

        with pytest.raises(ValueError, match="already exists"):
            group.insert_template(tmpl)

    def test_update_template(self):
        tmpl = StateReinforcement(**make_template(name="V1"))
        group = make_group(templates=[tmpl])
        group.save(TEMPLATE_TEST_PATH)

        tmpl.name = "V2"
        group.update_template(tmpl)

        loaded = Group.load(group.path)
        assert loaded.templates[tmpl.uid].name == "V2"

    def test_delete_template(self):
        tmpl = StateReinforcement(**make_template())
        group = make_group(templates=[tmpl])
        group.save(TEMPLATE_TEST_PATH)

        group.delete_template(tmpl)

        assert tmpl.uid not in group.templates

        loaded = Group.load(group.path)
        assert tmpl.uid not in loaded.templates

    def test_delete_nonexistent_template_is_noop(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)

        tmpl = StateReinforcement(**make_template())
        # Should not raise
        group.delete_template(tmpl)

    def test_find_template(self):
        tmpl = StateReinforcement(**make_template())
        group = make_group(templates=[tmpl])

        assert group.find(tmpl.uid) is tmpl
        assert group.find("nonexistent") is None


class TestCollectionLoadFromDir:
    def test_load_empty_directory(self):
        collection = Collection.load(TEMPLATE_TEST_PATH)
        assert len(collection.groups) == 0

    def test_load_single_group(self):
        group = make_group(name="Solo")
        group.save(TEMPLATE_TEST_PATH)

        collection = Collection.load(TEMPLATE_TEST_PATH)
        assert len(collection.groups) == 1
        assert collection.groups[0].uid == group.uid

    def test_load_multiple_groups(self):
        g1 = make_group(name="Group A")
        g2 = make_group(name="Group B")
        g1.save(TEMPLATE_TEST_PATH)
        g2.save(TEMPLATE_TEST_PATH)

        collection = Collection.load(TEMPLATE_TEST_PATH)
        assert len(collection.groups) == 2
        loaded_uids = {g.uid for g in collection.groups}
        assert g1.uid in loaded_uids
        assert g2.uid in loaded_uids


class TestCollectionFind:
    def test_find_group_by_uid(self):
        g1 = make_group(name="A")
        g2 = make_group(name="B")
        collection = Collection(groups=[g1, g2])

        assert collection.find(g1.uid) is g1
        assert collection.find(g2.uid) is g2
        assert collection.find("nonexistent") is None

    def test_find_template(self):
        tmpl = StateReinforcement(**make_template())
        group = make_group(templates=[tmpl])
        collection = Collection(groups=[group])

        found = collection.find_template(group.uid, tmpl.uid)
        assert found is tmpl
        assert collection.find_template(group.uid, "nonexistent") is None
        assert collection.find_template("nonexistent", tmpl.uid) is None


class TestCollectionRemove:
    def test_remove_deletes_group_and_file(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)
        path = group.path

        collection = Collection(groups=[group])
        collection.remove(group)

        assert len(collection.groups) == 0
        assert not os.path.exists(path)

    def test_remove_by_deserialized_group(self):
        """Simulates the real bug: removing via a different Group object with same uid."""
        group = make_group(name="Original")
        group.save(TEMPLATE_TEST_PATH)
        path = group.path

        collection = Collection(groups=[group])

        # Simulate deserialized group from frontend (different object, same uid)
        deserialized = Group(
            uid=group.uid,
            name="Original",
            author="Test Author",
            description="A test group",
        )

        collection.remove(deserialized)

        assert len(collection.groups) == 0
        assert not os.path.exists(path)

    def test_remove_nonexistent_raises(self):
        collection = Collection(groups=[])
        group = make_group()

        with pytest.raises(ValueError, match="not found"):
            collection.remove(group)

    def test_remove_without_save(self):
        group = make_group()
        group.save(TEMPLATE_TEST_PATH)
        path = group.path

        collection = Collection(groups=[group])
        collection.remove(group, save=False)

        assert len(collection.groups) == 0
        assert os.path.exists(path)  # file should still exist


class TestCollectionSave:
    def test_save_persists_all_groups(self):
        g1 = make_group(name="Group One")
        g2 = make_group(name="Group Two")
        collection = Collection(groups=[g1, g2])
        collection.save(TEMPLATE_TEST_PATH)

        assert os.path.exists(g1.path)
        assert os.path.exists(g2.path)

        # Verify by loading
        loaded = Collection.load(TEMPLATE_TEST_PATH)
        assert len(loaded.groups) == 2


class TestCollectionFlat:
    def test_flat_merges_all_templates(self):
        t1 = StateReinforcement(**make_template(name="T1"))
        t2 = StateReinforcement(**make_template(name="T2"))
        g1 = make_group(name="G1", templates=[t1])
        g2 = make_group(name="G2", templates=[t2])
        collection = Collection(groups=[g1, g2])

        flat = collection.flat()
        assert len(flat.templates) == 2
        # Keys should be group_uid__template_uid
        assert f"{g1.uid}__{t1.uid}" in flat.templates
        assert f"{g2.uid}__{t2.uid}" in flat.templates

    def test_flat_filters_by_type(self):
        sr = StateReinforcement(**make_template())
        ap = AgentPersona(name="Persona", template_type="agent_persona")
        g1 = make_group(name="G1", templates=[sr])
        g2 = make_group(name="G2", templates=[ap])
        collection = Collection(groups=[g1, g2])

        flat = collection.flat(types=["state_reinforcement"])
        assert len(flat.templates) == 1

        flat_all = collection.flat()
        assert len(flat_all.templates) == 2


class TestCollectionCollectAll:
    def test_collect_all_by_uids(self):
        t1 = StateReinforcement(**make_template(name="T1"))
        t2 = StateReinforcement(**make_template(name="T2"))
        t3 = StateReinforcement(**make_template(name="T3"))
        group = make_group(templates=[t1, t2, t3])
        collection = Collection(groups=[group])

        found = collection.collect_all([t1.uid, t3.uid])
        assert len(found) == 2
        assert t1.uid in found
        assert t3.uid in found
        assert t2.uid not in found

    def test_collect_all_with_no_matches(self):
        group = make_group()
        collection = Collection(groups=[group])

        found = collection.collect_all(["nonexistent"])
        assert len(found) == 0


class TestGroupDiff:
    def test_diff_returns_only_changed_templates(self):
        t1 = StateReinforcement(**make_template(name="Same"))
        t2 = StateReinforcement(**make_template(name="Different"))

        g1 = make_group(name="G1", templates=[t1, t2])
        # Set group field on g1's templates (as save() would do)
        for t in g1.templates.values():
            t.group = g1.uid

        t1_clone = StateReinforcement(**make_template(name="Same", uid=t1.uid))
        g2 = make_group(name="G2", templates=[t1_clone])
        for t in g2.templates.values():
            t.group = g2.uid

        diff = g1.diff(g2)

        # t1 is the same in both groups, t2 only exists in g1
        assert t2.uid in diff.templates
        assert t1.uid not in diff.templates

    def test_diff_empty_when_identical(self):
        t1 = StateReinforcement(**make_template(name="Same"))
        g1 = make_group(name="G1", templates=[t1])
        for t in g1.templates.values():
            t.group = g1.uid

        t1_clone = StateReinforcement(**make_template(name="Same", uid=t1.uid))
        g2 = make_group(name="G2", templates=[t1_clone])
        for t in g2.templates.values():
            t.group = g2.uid

        diff = g1.diff(g2)
        assert len(diff.templates) == 0


class TestGroupFilename:
    def test_filename_from_name(self):
        group = make_group(name="My Cool Templates")
        assert group.filename == "my-cool-templates.yaml"

    def test_filename_simple(self):
        group = make_group(name="default")
        assert group.filename == "default.yaml"
