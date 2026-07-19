"""Unit tests for talemate.files (scene directory listing)."""

import os
import pytest

import talemate.files
from talemate.files import list_scenes_directory, _list_files_and_directories


# ---------------------------------------------------------------------------
# Fixtures: build a fake scenes/ tree we can assert against deterministically
# ---------------------------------------------------------------------------


@pytest.fixture
def scene_tree(tmp_path):
    """Construct a 'scenes/' directory mirroring the real talemate layout.

    The real layout has scene JSONs at scenes/<scene>/*.json and shared
    character images at scenes/characters/*.png|webp. The helper's fnmatch
    patterns ('characters/*.png' and '*/*.json') only match these top-level
    locations relative to the scenes root.
    """
    scenes_root = tmp_path / "scenes"
    scenes_root.mkdir(parents=True)

    files = {
        # Scene JSONs (one folder per scene)
        "alice_in_wonderland/alice.json": '{"a": 1}',
        "bob_adventure/bob.json": '{"b": 1}',
        # Top-level character images
        "characters/alice.png": b"\x89PNG",
        "characters/queen.webp": b"WEBP",
        # Files that must be filtered out:
        # - non-image extension in characters/
        "characters/notes.txt": "ignored extension",
        # - JSON inside a 'nodes' directory must be skipped
        "alice_in_wonderland/nodes/scene-loop.json": '{"node": true}',
        # - changelog directory must be skipped
        "alice_in_wonderland/changelog/0001.json": '{"x": true}',
        # - assets directory must be skipped
        "assets/portrait.png": b"\x89PNG",
        "assets/library.json": '{"asset": true}',
    }

    paths = {}
    for rel, content in files.items():
        full = scenes_root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(full, mode) as fh:
            fh.write(content)
        paths[rel] = str(full)

    return {"root": str(scenes_root), "tmp": str(tmp_path), "paths": paths}


# ---------------------------------------------------------------------------
# _list_files_and_directories: the underlying helper
# ---------------------------------------------------------------------------


class TestListFilesAndDirectories:
    def test_lists_images_and_jsons_when_images_enabled(self, scene_tree):
        result = _list_files_and_directories(scene_tree["root"], ".", list_images=True)

        # Convert to set for ordering-independent comparison
        result_set = set(result)
        expected = {
            scene_tree["paths"]["characters/alice.png"],
            scene_tree["paths"]["characters/queen.webp"],
            scene_tree["paths"]["alice_in_wonderland/alice.json"],
            scene_tree["paths"]["bob_adventure/bob.json"],
        }
        assert result_set == expected

    def test_omits_images_when_list_images_false(self, scene_tree):
        result = _list_files_and_directories(scene_tree["root"], ".", list_images=False)
        # Only json files (not in nodes/changelog/assets) should appear
        for path in result:
            assert path.endswith(".json")
        result_set = set(result)
        assert result_set == {
            scene_tree["paths"]["alice_in_wonderland/alice.json"],
            scene_tree["paths"]["bob_adventure/bob.json"],
        }

    def test_skips_json_inside_nodes_directory(self, scene_tree):
        result = _list_files_and_directories(scene_tree["root"], ".", list_images=True)
        # nodes/scene-loop.json must NOT appear
        for path in result:
            assert os.sep + "nodes" + os.sep not in path

    def test_skips_changelog_directory(self, scene_tree):
        result = _list_files_and_directories(scene_tree["root"], ".", list_images=True)
        for path in result:
            assert os.sep + "changelog" + os.sep not in path

    def test_skips_assets_directory(self, scene_tree):
        result = _list_files_and_directories(scene_tree["root"], ".", list_images=True)
        for path in result:
            assert os.sep + "assets" + os.sep not in path

    def test_ignores_unsupported_extensions(self, scene_tree):
        result = _list_files_and_directories(scene_tree["root"], ".", list_images=True)
        # The 'characters/notes.txt' file should be filtered out
        for path in result:
            assert not path.endswith(".txt")

    def test_returns_empty_list_for_empty_root(self, tmp_path):
        empty_dir = tmp_path / "empty_scenes"
        empty_dir.mkdir()
        result = _list_files_and_directories(str(empty_dir), ".", list_images=True)
        assert result == []

    def test_returns_empty_for_nonexistent_root(self, tmp_path):
        # os.walk silently returns nothing for missing roots; the helper
        # must follow that behaviour rather than raising.
        result = _list_files_and_directories(
            str(tmp_path / "does_not_exist"), ".", list_images=True
        )
        assert result == []


# ---------------------------------------------------------------------------
# list_scenes_directory: thin wrapper around the helper
# ---------------------------------------------------------------------------


class TestListScenesDirectory:
    def test_walks_scenes_dir(self, scene_tree, monkeypatch):
        # list_scenes_directory anchors on talemate.path.SCENES_DIR
        monkeypatch.setattr(talemate.files, "SCENES_DIR", scene_tree["root"])
        result = list_scenes_directory(list_images=True)

        # The fake scenes tree has 4 matching files (2 JSONs + 2 images)
        assert len(result) == 4
        result_set = set(result)
        assert scene_tree["paths"]["characters/alice.png"] in result_set
        assert scene_tree["paths"]["alice_in_wonderland/alice.json"] in result_set

    def test_passes_list_images_flag_through(self, scene_tree, monkeypatch):
        monkeypatch.setattr(talemate.files, "SCENES_DIR", scene_tree["root"])
        json_only = list_scenes_directory(list_images=False)
        assert all(path.endswith(".json") for path in json_only)

    def test_returns_empty_when_no_scenes_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(talemate.files, "SCENES_DIR", tmp_path / "missing")
        # No scenes/ directory exists -> empty list (os.walk on missing path)
        assert list_scenes_directory(list_images=True) == []
