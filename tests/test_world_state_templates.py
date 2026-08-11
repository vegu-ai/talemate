"""
Integration tests for world state template Group and Collection file operations.

Tests actual YAML file creation, loading, updating, and deletion in a per-test
temporary template directory.
"""

import os

import pydantic
import pytest
import yaml

from conftest import MockScene
from talemate.server.world_state_manager import SaveWorldStateTemplateGroupPayload
from talemate.world_state.manager import WorldStateManager
from talemate.world_state.templates.agent import AgentPersona
from talemate.world_state.templates.base import (
    TEMPLATE_PATH,
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
)
from talemate.world_state.templates.state_reinforcement import StateReinforcement


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
    def test_save_creates_yaml_file(self, template_dir):
        group = make_group()
        group.save(template_dir)

        assert group.path is not None
        assert os.path.exists(group.path)
        assert group.path.endswith(".yaml")

    def test_save_sets_path_on_group(self, template_dir):
        group = make_group()
        assert group.path is None

        group.save(template_dir)

        expected = os.path.join(template_dir, "test-group.yaml")
        assert group.path == expected

    def test_save_does_not_overwrite_existing_path(self, template_dir):
        group = make_group()
        group.save(template_dir)
        original_path = group.path

        # Saving again should reuse the same path
        group.save(template_dir)
        assert group.path == original_path

    def test_saved_yaml_contains_group_data(self, template_dir):
        group = make_group(name="My Group", author="Alice", description="desc")
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)

        assert data["name"] == "My Group"
        assert data["author"] == "Alice"
        assert data["description"] == "desc"
        assert data["uid"] == group.uid
        assert "path" not in data  # path should be excluded from YAML

    def test_saved_yaml_contains_templates(self, template_dir):
        tmpl = StateReinforcement(**make_template(name="Mood Check"))
        group = make_group(templates=[tmpl])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)

        assert tmpl.uid in data["templates"]
        assert data["templates"][tmpl.uid]["name"] == "Mood Check"
        assert data["templates"][tmpl.uid]["query"] == "What is the character's mood?"

    def test_load_roundtrip(self, template_dir):
        tmpl = StateReinforcement(**make_template(name="Roundtrip"))
        group = make_group(name="Roundtrip Group", templates=[tmpl])
        group.save(template_dir)

        loaded = Group.load(group.path)

        assert loaded.uid == group.uid
        assert loaded.name == "Roundtrip Group"
        assert loaded.author == "Test Author"
        assert loaded.path == group.path
        assert tmpl.uid in loaded.templates
        assert loaded.templates[tmpl.uid].name == "Roundtrip"

    def test_save_assigns_group_uid_to_templates(self, template_dir):
        tmpl = StateReinforcement(**make_template())
        tmpl.group = None  # explicitly unset
        group = make_group(templates=[tmpl])
        group.save(template_dir)

        assert tmpl.group == group.uid

        loaded = Group.load(group.path)
        assert loaded.templates[tmpl.uid].group == group.uid


class TestGroupDelete:
    def test_delete_removes_file(self, template_dir):
        group = make_group()
        group.save(template_dir)
        path = group.path
        assert os.path.exists(path)

        group.delete()
        assert not os.path.exists(path)

    def test_delete_with_none_path_does_not_raise(self):
        group = make_group()
        assert group.path is None
        # Should not raise
        group.delete()

    def test_delete_after_file_already_removed_does_not_raise(self, template_dir):
        group = make_group()
        group.save(template_dir)
        os.remove(group.path)

        # File already gone, should not raise
        group.delete()


class TestGroupUpdate:
    def test_update_changes_metadata(self, template_dir):
        group = make_group(name="Original")
        group.save(template_dir)

        updated = make_group(name="Updated", author="Bob", description="new desc")
        group.update(updated)

        assert group.name == "Updated"
        assert group.author == "Bob"
        assert group.description == "new desc"

        # Verify persisted
        loaded = Group.load(group.path)
        assert loaded.name == "Updated"

    def test_update_ignores_templates_by_default(self, template_dir):
        tmpl = StateReinforcement(**make_template())
        group = make_group(templates=[tmpl])
        group.save(template_dir)

        updated = make_group()  # no templates
        group.update(updated)

        assert tmpl.uid in group.templates


class TestGroupTemplateOperations:
    def test_insert_template(self, template_dir):
        group = make_group()
        group.save(template_dir)

        tmpl = StateReinforcement(**make_template(name="Inserted"))
        group.insert_template(tmpl)

        assert tmpl.uid in group.templates

        # Verify persisted
        loaded = Group.load(group.path)
        assert tmpl.uid in loaded.templates

    def test_insert_duplicate_raises(self, template_dir):
        group = make_group()
        group.save(template_dir)

        tmpl = StateReinforcement(**make_template())
        group.insert_template(tmpl)

        with pytest.raises(ValueError, match="already exists"):
            group.insert_template(tmpl)

    def test_update_template(self, template_dir):
        tmpl = StateReinforcement(**make_template(name="V1"))
        group = make_group(templates=[tmpl])
        group.save(template_dir)

        tmpl.name = "V2"
        group.update_template(tmpl)

        loaded = Group.load(group.path)
        assert loaded.templates[tmpl.uid].name == "V2"

    def test_delete_template(self, template_dir):
        tmpl = StateReinforcement(**make_template())
        group = make_group(templates=[tmpl])
        group.save(template_dir)

        group.delete_template(tmpl)

        assert tmpl.uid not in group.templates

        loaded = Group.load(group.path)
        assert tmpl.uid not in loaded.templates

    def test_delete_nonexistent_template_is_noop(self, template_dir):
        group = make_group()
        group.save(template_dir)

        tmpl = StateReinforcement(**make_template())
        # Should not raise
        group.delete_template(tmpl)

    def test_find_template(self):
        tmpl = StateReinforcement(**make_template())
        group = make_group(templates=[tmpl])

        assert group.find(tmpl.uid) is tmpl
        assert group.find("nonexistent") is None


class TestCollectionLoadFromDir:
    def test_load_empty_directory(self, template_dir):
        collection = Collection.load(template_dir)
        assert len(collection.groups) == 0

    def test_load_single_group(self, template_dir):
        group = make_group(name="Solo")
        group.save(template_dir)

        collection = Collection.load(template_dir)
        assert len(collection.groups) == 1
        assert collection.groups[0].uid == group.uid

    def test_load_multiple_groups(self, template_dir):
        g1 = make_group(name="Group A")
        g2 = make_group(name="Group B")
        g1.save(template_dir)
        g2.save(template_dir)

        collection = Collection.load(template_dir)
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
    def test_remove_deletes_group_and_file(self, template_dir):
        group = make_group()
        group.save(template_dir)
        path = group.path

        collection = Collection(groups=[group])
        collection.remove(group)

        assert len(collection.groups) == 0
        assert not os.path.exists(path)

    def test_remove_by_deserialized_group(self, template_dir):
        """Simulates the real bug: removing via a different Group object with same uid."""
        group = make_group(name="Original")
        group.save(template_dir)
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

    def test_remove_ignores_the_incoming_group_path(self, template_dir, tmp_path):
        """Deletion goes through the collection's own group, so a path on the
        incoming (websocket deserialized) group never reaches the filesystem."""
        group = make_group()
        group.save(template_dir)
        path = group.path

        outside = tmp_path / "config.yaml"
        outside.write_text("keep me")

        collection = Collection(groups=[group])
        collection.remove(
            Group(
                uid=group.uid,
                name=group.name,
                author=group.author,
                description=group.description,
                path=str(outside),
            )
        )

        assert not os.path.exists(path)
        assert outside.read_text() == "keep me"

    def test_remove_nonexistent_raises(self):
        collection = Collection(groups=[])
        group = make_group()

        with pytest.raises(ValueError, match="not found"):
            collection.remove(group)

    def test_remove_without_save(self, template_dir):
        group = make_group()
        group.save(template_dir)
        path = group.path

        collection = Collection(groups=[group])
        collection.remove(group, save=False)

        assert len(collection.groups) == 0
        assert os.path.exists(path)  # file should still exist


class TestCollectionSave:
    def test_save_persists_all_groups(self, template_dir):
        g1 = make_group(name="Group One")
        g2 = make_group(name="Group Two")
        collection = Collection(groups=[g1, g2])
        collection.save(template_dir)

        assert os.path.exists(g1.path)
        assert os.path.exists(g2.path)

        # Verify by loading
        loaded = Collection.load(template_dir)
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


class TestGroupSavePathContainment:
    def test_traversal_name_is_refused(self, template_dir):
        group = make_group(name="../../config")

        with pytest.raises(ValueError, match="path separators"):
            group.save(template_dir)

        assert group.path is None
        escaped = os.path.join(template_dir, "..", "..", "config.yaml")
        assert not os.path.exists(escaped)

    @pytest.mark.parametrize("name", ["sub/dir", "sub\\dir", "/etc/passwd"])
    def test_separator_name_is_refused(self, template_dir, name):
        group = make_group(name=name)

        with pytest.raises(ValueError, match="path separators"):
            group.save(template_dir)

        assert group.path is None
        assert os.listdir(template_dir) == []

    def test_dots_without_separator_still_save(self, template_dir):
        group = make_group(name="..")
        group.save(template_dir)

        assert group.path == os.path.join(template_dir, "...yaml")
        assert os.path.exists(group.path)

    def test_normal_name_still_saves(self, template_dir):
        tmpl = StateReinforcement(**make_template())
        group = make_group(name="My Cool Templates", templates=[tmpl])
        group.save(template_dir)

        assert group.path == os.path.join(template_dir, "my-cool-templates.yaml")
        assert os.path.exists(group.path)
        assert Group.load(group.path).uid == group.uid

    def test_existing_path_from_disk_is_kept(self, template_dir):
        """A group loaded off a disk walk saves back to where it came from,
        even when that is a subdirectory of the path passed to save()."""
        nested = os.path.join(template_dir, "nested")
        os.makedirs(nested)
        group = make_group(name="Nested Group")
        group.save(nested)

        loaded = Collection.load(template_dir).groups[0]
        tmpl = StateReinforcement(**make_template(name="Added"))
        loaded.insert_template(tmpl)

        assert loaded.path == os.path.join(nested, "nested-group.yaml")
        assert tmpl.uid in Group.load(loaded.path).templates


class TestSaveTemplateGroupPayloadPath:
    """The entry-point belt: an inbound `path` is refused before it reaches
    the manager (which ignores it anyway, see
    `TestSaveTemplateGroupOwnership`)."""

    def make_payload(self, **overrides) -> dict:
        group = {
            "name": "Inbound Group",
            "author": "Test Author",
            "description": "A test group",
        }
        group.update(overrides)
        return {"group": group}

    def test_absent_path_passes(self):
        payload = SaveWorldStateTemplateGroupPayload(**self.make_payload())
        assert payload.group.path is None

    def test_contained_path_passes(self):
        path = os.path.join(TEMPLATE_PATH_TALEMATE, "inbound-group.yaml")
        payload = SaveWorldStateTemplateGroupPayload(**self.make_payload(path=path))

        assert payload.group.path == path

    @pytest.mark.parametrize(
        "path",
        [
            os.path.join(TEMPLATE_PATH, "..", "..", "config.yaml"),
            "/workspace/config.yaml",
            "/etc/passwd",
        ],
    )
    def test_path_outside_the_template_directory_is_refused(self, path: str):
        with pytest.raises(
            pydantic.ValidationError, match="outside of the template directory"
        ):
            SaveWorldStateTemplateGroupPayload(**self.make_payload(path=path))

    def test_tmp_path_outside_the_template_directory_is_refused(self, tmp_path):
        outside = str(tmp_path / "config.yaml")

        with pytest.raises(
            pydantic.ValidationError, match="outside of the template directory"
        ):
            SaveWorldStateTemplateGroupPayload(**self.make_payload(path=outside))


class TestSaveTemplateGroupOwnership:
    """`WorldStateManager.save_template_group` decides which file a group
    writes to: a known group keeps its own, an unknown one derives a fresh
    one. Whatever `path` the client sent is never consulted."""

    @pytest.fixture
    def manager(self, monkeypatch, template_dir) -> WorldStateManager:
        # `Group.save` binds TEMPLATE_PATH as a default argument, so only the
        # lookups the manager does at call time can be redirected
        monkeypatch.setattr(
            "talemate.world_state.templates.TEMPLATE_PATH", template_dir
        )
        manager = WorldStateManager(MockScene())
        manager.scene._world_state_templates = Collection.load(template_dir)
        return manager

    async def test_inbound_path_of_an_unknown_group_is_ignored(
        self, manager, template_dir
    ):
        other = make_group(name="Other")
        other.save(template_dir)

        inbound = make_group(name="Inbound", path=other.path)
        await manager.save_template_group(inbound)

        assert inbound.path == os.path.join(template_dir, "inbound.yaml")
        assert Group.load(other.path).uid == other.uid

    async def test_unknown_group_is_added_to_the_collection(
        self, manager, template_dir
    ):
        group = make_group(name="Fresh")

        await manager.save_template_group(group)

        assert manager.template_collection.find(group.uid) is group
        assert os.path.exists(os.path.join(template_dir, "fresh.yaml"))

    async def test_known_group_saves_back_to_its_own_file(self, manager, template_dir):
        nested = os.path.join(template_dir, "talemate")
        os.makedirs(nested)
        known = make_group(name="Known")
        known.save(nested)
        manager.scene._world_state_templates = Collection.load(template_dir)

        other = make_group(name="Other")
        other.save(template_dir)

        inbound = make_group(
            name="Known", uid=known.uid, description="edited", path=other.path
        )
        await manager.save_template_group(inbound)

        saved = Group.load(os.path.join(nested, "known.yaml"))
        assert saved.description == "edited"
        assert Group.load(other.path).uid == other.uid
        assert not os.path.exists(os.path.join(template_dir, "known.yaml"))

    async def test_colliding_derived_name_is_refused(self, manager, template_dir):
        existing = make_group(name="Human")
        existing.save(template_dir)

        fresh = make_group(name="Human")

        with pytest.raises(ValueError, match="human.yaml already exists"):
            await manager.save_template_group(fresh)

        assert Group.load(existing.path).uid == existing.uid
        assert manager.template_collection.find(fresh.uid) is None

    async def test_separator_name_is_refused(self, manager, template_dir):
        group = make_group(name="../escape")

        with pytest.raises(ValueError, match="path separators"):
            await manager.save_template_group(group)

        assert manager.template_collection.find(group.uid) is None


class TestGroupFilename:
    def test_filename_from_name(self):
        group = make_group(name="My Cool Templates")
        assert group.filename == "my-cool-templates.yaml"

    def test_filename_simple(self):
        group = make_group(name="default")
        assert group.filename == "default.yaml"
