"""
Tests for the ``delete_scene_project`` config websocket action.

The action removes an entire scene project directory (saves, assets, nodes,
changelog) and cleans up recent-scene entries pointing into it. It must
refuse anything that is not a direct child of the scenes directory.
"""

import json
import os

import pytest

import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.files
from talemate.config import Config
from talemate.config.schema import RecentScene
from talemate.server.config import ConfigPlugin


@pytest.fixture(autouse=True)
def isolated_config_signals():
    """
    set_dirty() broadcasts config.changed to whatever receivers other test
    modules left connected (e.g. mock agents) - isolate the signal here.
    """
    saved = {}
    for name in ("config.changed", "config.changed.follow"):
        signal = async_signals.get(name)
        saved[signal] = signal.receivers
        signal.receivers = []
    yield
    for signal, receivers in saved.items():
        signal.receivers = receivers


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)

    def by_action(self, action):
        return [m for m in self.messages if m.get("action") == action]


@pytest.fixture
def scenes_root(tmp_path, monkeypatch):
    root = tmp_path / "scenes"
    root.mkdir()
    monkeypatch.setattr(talemate.files, "SCENES_DIR", root)
    return root


@pytest.fixture
def app_config(monkeypatch):
    config = Config(recent_scenes={"scenes": []})
    monkeypatch.setattr(config_state, "CONFIG", config)
    return config


@pytest.fixture
def plugin():
    return ConfigPlugin(_MockWebsocketHandler())


def _make_project(scenes_root, name="adventure"):
    project = scenes_root / name
    (project / "assets").mkdir(parents=True)
    (project / "changelog").mkdir()
    (project / "save.json").write_text(json.dumps({"name": name}))
    (project / "assets" / "cover.png").write_bytes(b"png")
    (project / "changelog" / "save.json.base.json").write_text("{}")
    return project


@pytest.mark.asyncio
async def test_delete_scene_project(scenes_root, app_config, plugin):
    project = _make_project(scenes_root)
    other = _make_project(scenes_root, "other")

    app_config.recent_scenes.scenes = [
        RecentScene(
            name="Adventure",
            path=str(project / "save.json"),
            filename="save.json",
            date="2026-07-19T00:00:00",
        ),
        RecentScene(
            name="Other",
            path=str(other / "save.json"),
            filename="save.json",
            date="2026-07-19T00:00:00",
        ),
    ]

    await plugin.handle_delete_scene_project({"path": str(project)})

    assert not project.exists()
    assert other.exists()

    # recents entry for the deleted project removed, the other kept
    assert [scene.name for scene in app_config.recent_scenes.scenes] == ["Other"]

    completed = plugin.websocket_handler.by_action("delete_scene_project_complete")
    assert len(completed) == 1
    assert completed[0]["data"]["name"] == "adventure"

    # app_config broadcast follows
    assert any(
        message.get("type") == "app_config"
        for message in plugin.websocket_handler.messages
    )


@pytest.mark.asyncio
async def test_delete_rejects_paths_outside_scenes_dir(
    tmp_path, scenes_root, app_config, plugin
):
    outside = tmp_path / "not-scenes" / "project"
    outside.mkdir(parents=True)

    with pytest.raises(ValueError, match="Not a scene project"):
        await plugin.handle_delete_scene_project({"path": str(outside)})

    assert outside.exists()


@pytest.mark.asyncio
async def test_delete_rejects_scenes_root_itself(scenes_root, app_config, plugin):
    with pytest.raises(ValueError, match="Not a scene project"):
        await plugin.handle_delete_scene_project({"path": str(scenes_root)})

    assert scenes_root.exists()


@pytest.mark.asyncio
async def test_delete_rejects_reserved_dirs(scenes_root, app_config, plugin):
    for reserved in ("characters", "assets"):
        (scenes_root / reserved).mkdir()
        with pytest.raises(ValueError, match="Not a scene project"):
            await plugin.handle_delete_scene_project(
                {"path": str(scenes_root / reserved)}
            )
        assert (scenes_root / reserved).exists()


@pytest.mark.asyncio
async def test_delete_rejects_traversal(tmp_path, scenes_root, app_config, plugin):
    victim = tmp_path / "victim"
    victim.mkdir()

    traversal = str(scenes_root / "project" / ".." / ".." / "victim")

    with pytest.raises(ValueError, match="Not a scene project"):
        await plugin.handle_delete_scene_project({"path": traversal})

    assert victim.exists()


@pytest.mark.asyncio
async def test_delete_rejects_symlink_escape(tmp_path, scenes_root, app_config, plugin):
    victim = tmp_path / "victim"
    victim.mkdir()

    link = scenes_root / "linked-project"
    os.symlink(str(victim), str(link))

    with pytest.raises(ValueError, match="Not a scene project"):
        await plugin.handle_delete_scene_project({"path": str(link)})

    assert victim.exists()


@pytest.mark.asyncio
async def test_delete_rejects_missing_project(scenes_root, app_config, plugin):
    with pytest.raises(ValueError, match="not found"):
        await plugin.handle_delete_scene_project(
            {"path": str(scenes_root / "does-not-exist")}
        )


@pytest.mark.asyncio
async def test_delete_rejects_active_scene_project(scenes_root, app_config, plugin):
    project = _make_project(scenes_root)

    class _SceneStub:
        full_path = str(project / "save.json")

    plugin.websocket_handler.scene = _SceneStub()

    with pytest.raises(ValueError, match="currently loaded scene"):
        await plugin.handle_delete_scene_project({"path": str(project)})

    assert project.exists()

    # a different loaded scene does not block the delete
    other = _make_project(scenes_root, "other")
    plugin.websocket_handler.scene = type(
        "_OtherScene", (), {"full_path": str(other / "save.json")}
    )()
    await plugin.handle_delete_scene_project({"path": str(project)})
    assert not project.exists()


@pytest.mark.asyncio
async def test_delete_scene_file_contained(tmp_path, scenes_root, app_config, plugin):
    project = _make_project(scenes_root)

    await plugin.handle_delete_scene({"path": str(project / "save.json")})
    assert not (project / "save.json").exists()

    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    with pytest.raises(ValueError, match="Not a scene file"):
        await plugin.handle_delete_scene({"path": str(outside)})
    assert outside.exists()
