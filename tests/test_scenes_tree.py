"""
Tests for the structured scenes-tree listing used by the scene browser
landing page (``list_scenes_tree`` in ``talemate.files``).
"""

import json
import os

import pytest

import talemate.files
from talemate.files import list_scenes_tree


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as file:
        json.dump(data, file)


def _touch(path, mtime):
    os.utime(path, (mtime, mtime))


@pytest.fixture
def scenes_root(tmp_path, monkeypatch):
    root = tmp_path / "scenes"
    root.mkdir()
    monkeypatch.setattr(talemate.files, "SCENES_DIR", root)
    return root


COVER_ID = "cover-asset-id"


def _make_project(root, name, saves: dict, cover_in_library: bool = True):
    """
    Create a scene project directory with the given saves.

    ``saves`` maps filename -> (mtime, scene_data)
    """
    project = root / name
    project.mkdir(exist_ok=True)

    if cover_in_library:
        _write_json(
            str(project / "assets" / "library.json"),
            {
                "assets": {
                    COVER_ID: {
                        "id": COVER_ID,
                        "file_type": "webp",
                        "media_type": "image/webp",
                    }
                }
            },
        )

    for filename, (mtime, scene_data) in saves.items():
        path = project / filename
        _write_json(str(path), scene_data)
        _touch(str(path), mtime)

    return project


def test_empty_scenes_dir(scenes_root):
    tree = list_scenes_tree()
    assert tree == {"projects": [], "characters": []}


def test_missing_scenes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(talemate.files, "SCENES_DIR", tmp_path / "does-not-exist")
    tree = list_scenes_tree()
    assert tree == {"projects": [], "characters": []}


def test_project_listing_with_metadata(scenes_root):
    _make_project(
        scenes_root,
        "adventure",
        {
            "old-save.json": (
                1000,
                {"name": "Adventure", "assets": {"cover_image": COVER_ID}},
            ),
            "new-save.json": (
                2000,
                {"name": "Adventure II", "assets": {"cover_image": COVER_ID}},
            ),
        },
    )

    tree = list_scenes_tree()

    assert len(tree["projects"]) == 1
    project = tree["projects"][0]
    assert project["name"] == "adventure"
    assert project["path"] == str(scenes_root / "adventure")

    # files sorted newest first
    filenames = [entry["filename"] for entry in project["files"]]
    assert filenames == ["new-save.json", "old-save.json"]

    newest = project["files"][0]
    assert newest["scene_name"] == "Adventure II"
    assert newest["relpath"] == "new-save.json"
    assert newest["size"] > 0
    assert newest["modified"] == project["modified"]

    # cover resolved through the asset library, path anchored at the
    # project's assets dir
    assert project["cover_image"] == {
        "id": COVER_ID,
        "file_type": "webp",
        "media_type": "image/webp",
        "path": str(scenes_root / "adventure" / "assets" / f"{COVER_ID}.webp"),
    }

    # library.json does not count as an asset
    assert project["num_assets"] == 0
    assert project["num_nodes"] == 0


def test_project_asset_and_node_counts(scenes_root):
    project = _make_project(
        scenes_root, "counted", {"save.json": (1000, {"name": "Counted"})}
    )

    (project / "assets" / "one.png").write_bytes(b"png")
    (project / "assets" / "two.webp").write_bytes(b"webp")
    _write_json(str(project / "nodes" / "scene-loop.json"), {})
    _write_json(str(project / "nodes" / "sub" / "module.json"), {})

    tree = list_scenes_tree()

    counted = next(p for p in tree["projects"] if p["name"] == "counted")
    assert counted["num_assets"] == 2
    assert counted["num_nodes"] == 2


def test_projects_sorted_newest_first(scenes_root):
    _make_project(scenes_root, "older", {"save.json": (1000, {"name": "Older"})})
    _make_project(scenes_root, "newer", {"save.json": (2000, {"name": "Newer"})})

    tree = list_scenes_tree()

    assert [project["name"] for project in tree["projects"]] == ["newer", "older"]


def test_excluded_subdirs_and_empty_projects(scenes_root):
    project = _make_project(
        scenes_root, "adventure", {"save.json": (1000, {"name": "Adventure"})}
    )

    # json files in nodes/changelog/assets/info must not be listed
    _write_json(str(project / "nodes" / "graph.json"), {})
    _write_json(str(project / "changelog" / "save.json.base.json"), {})
    _write_json(str(project / "assets" / "library.json"), {"assets": {}})
    _write_json(str(project / "info" / "modules.json"), {})

    # a project directory without any save files is not listed
    (scenes_root / "empty-project").mkdir()

    # a reserved top-level assets dir is not a project
    _write_json(str(scenes_root / "assets" / "some.json"), {})

    tree = list_scenes_tree()

    assert [project["name"] for project in tree["projects"]] == ["adventure"]
    assert [entry["filename"] for entry in tree["projects"][0]["files"]] == [
        "save.json"
    ]


def test_unparseable_and_non_dict_saves_are_still_listed(scenes_root):
    project = scenes_root / "broken"
    project.mkdir()

    invalid = project / "invalid.json"
    invalid.write_text("{not valid json")
    _touch(str(invalid), 1000)

    non_dict = project / "list.json"
    _write_json(str(non_dict), [1, 2, 3])
    _touch(str(non_dict), 2000)

    tree = list_scenes_tree()

    files = tree["projects"][0]["files"]
    assert [entry["filename"] for entry in files] == ["list.json", "invalid.json"]
    for entry in files:
        assert entry["scene_name"] is None
        assert entry["cover_image"] is None


def test_cover_probe_fallback_without_library(scenes_root):
    project = _make_project(
        scenes_root,
        "no-library",
        {
            "save.json": (
                1000,
                {"name": "No Library", "assets": {"cover_image": COVER_ID}},
            )
        },
        cover_in_library=False,
    )

    # cover asset exists on disk but not in a library.json
    asset_path = project / "assets" / f"{COVER_ID}.png"
    os.makedirs(str(project / "assets"), exist_ok=True)
    asset_path.write_bytes(b"png-bytes")

    tree = list_scenes_tree()

    assert tree["projects"][0]["cover_image"] == {
        "id": COVER_ID,
        "file_type": "png",
        "media_type": "image/png",
        "path": str(asset_path),
    }


def test_cover_path_anchored_at_project_for_nested_saves(scenes_root):
    # a project whose only save lives in a subdirectory still resolves the
    # cover against the project-level assets dir
    project = scenes_root / "nested"
    _write_json(
        str(project / "sub" / "save.json"),
        {"name": "Nested", "assets": {"cover_image": COVER_ID}},
    )
    _write_json(
        str(project / "assets" / "library.json"),
        {
            "assets": {
                COVER_ID: {
                    "id": COVER_ID,
                    "file_type": "png",
                    "media_type": "image/png",
                }
            }
        },
    )

    tree = list_scenes_tree()

    cover = tree["projects"][0]["cover_image"]
    assert cover["path"] == str(project / "assets" / f"{COVER_ID}.png")


def test_cover_unresolvable(scenes_root):
    _make_project(
        scenes_root,
        "no-cover",
        {
            "save.json": (
                1000,
                {"name": "No Cover", "assets": {"cover_image": "missing-id"}},
            )
        },
        cover_in_library=False,
    )

    tree = list_scenes_tree()
    assert tree["projects"][0]["cover_image"] is None


def test_character_cards_listing(scenes_root):
    characters = scenes_root / "characters"
    characters.mkdir()

    png = characters / "alice.png"
    png.write_bytes(b"png")
    _touch(str(png), 1000)

    webp = characters / "bob.webp"
    webp.write_bytes(b"webp")
    _touch(str(webp), 3000)

    card_json = characters / "carol.json"
    _write_json(str(card_json), {"spec": "chara_card_v2"})
    _touch(str(card_json), 2000)

    v0_card = characters / "dave.json"
    _write_json(str(v0_card), {"first_mes": "Hello"})
    _touch(str(v0_card), 1500)

    # scene uploads and other non-card json files land here too - not cards
    scene_json = characters / "uploaded-scene.json"
    _write_json(str(scene_json), {"name": "A Scene", "environment": "scene"})

    broken_json = characters / "broken.json"
    broken_json.write_text("{not json")

    ignored = characters / "readme.txt"
    ignored.write_text("not a card")

    # upload side artifacts in subdirectories are never cards
    _write_json(str(characters / "assets" / "library.json"), {"assets": {}})
    nested_png = characters / "assets" / "cover.png"
    nested_png.write_bytes(b"png")

    tree = list_scenes_tree()

    # characters dir is not listed as a project
    assert tree["projects"] == []

    cards = tree["characters"]
    assert [card["filename"] for card in cards] == [
        "bob.webp",
        "carol.json",
        "dave.json",
        "alice.png",
    ]
    assert cards[0]["media_type"] == "image/webp"
    assert cards[1]["media_type"] == "application/json"
    assert cards[3]["media_type"] == "image/png"


def test_scene_meta_cache_invalidates_on_mtime(scenes_root):
    project = scenes_root / "cached"
    project.mkdir()
    save = project / "save.json"

    _write_json(str(save), {"name": "First"})
    _touch(str(save), 1000)
    tree = list_scenes_tree()
    assert tree["projects"][0]["files"][0]["scene_name"] == "First"

    # same mtime -> cached name survives a content change
    _write_json(str(save), {"name": "Second"})
    _touch(str(save), 1000)
    tree = list_scenes_tree()
    assert tree["projects"][0]["files"][0]["scene_name"] == "First"

    # new mtime -> cache invalidated
    _touch(str(save), 2000)
    tree = list_scenes_tree()
    assert tree["projects"][0]["files"][0]["scene_name"] == "Second"
