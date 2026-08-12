"""
Tests that every ``app_config`` push out of ``ConfigPlugin`` carries the
resolved theme.

The frontend repaints from ``data.theme`` and reads its absence as "no theme",
which drops the app - the code editors above all - back to the built-in
defaults. Only the ``config.changed`` broadcast and ``request_app_config`` used
to resolve it, so a save of the default character, a recents removal or a scene
delete quietly reset the running theme.

The handlers are discovered from the module rather than listed, so a new
emitter that skips the shared payload builder fails here instead of shipping.
"""

import ast
import inspect
import json

import pytest

import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.files
import talemate.server.config as server_config
from talemate.config import Config
from talemate.config.schema import RecentScene
from talemate.server.config import ConfigPlugin
from talemate.world_state.templates.base import Collection, Group
from talemate.world_state.templates.theme import (
    Theme,
    invalidate_theme_cache,
    resolve_theme,
)


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


@pytest.fixture(autouse=True)
def theme_cache():
    """`resolve_theme` caches its lookups for the life of the process."""
    invalidate_theme_cache()
    yield
    invalidate_theme_cache()


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)

    @property
    def app_configs(self) -> list[dict]:
        return [m for m in self.messages if m.get("type") == "app_config"]


@pytest.fixture
def scenes_root(tmp_path, monkeypatch):
    root = tmp_path / "scenes"
    root.mkdir()
    monkeypatch.setattr(talemate.files, "SCENES_DIR", root)
    return root


@pytest.fixture
def app_config(monkeypatch, tmp_path):
    config = Config(recent_scenes={"scenes": []})
    monkeypatch.setattr(config_state, "CONFIG", config)
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")
    return config


@pytest.fixture
def active_theme(monkeypatch, app_config) -> Theme:
    """An active theme that differs from the built-in default.

    `resolve_theme` falls back to that default for anything it cannot resolve,
    so a theme identical to it could not tell a resolved payload from a
    fallback - or from a handler that resolved nothing at all.
    """
    template = Theme(
        name="Midnight", colors={"app": {"primary": "#123456"}}, code_editor="nord"
    )
    group = Group(
        author="a",
        name="Themes",
        description="d",
        templates={template.uid: template},
    )
    template.group = group.uid

    def _load(path: str | None = None) -> Collection:
        return Collection(groups=[group])

    monkeypatch.setattr(Collection, "load", _load)
    app_config.appearance.theme = f"{group.uid}__{template.uid}"
    return template


@pytest.fixture
def plugin():
    return ConfigPlugin(_MockWebsocketHandler())


def _make_scene(scenes_root, app_config, name="adventure"):
    project = scenes_root / name
    project.mkdir()
    save_path = project / "save.json"
    save_path.write_text(json.dumps({"name": name}))
    app_config.recent_scenes.scenes = [
        RecentScene(
            name=name,
            path=str(save_path),
            filename="save.json",
            date="2026-08-12T00:00:00",
        )
    ]
    return project


async def _drive_save_default_character(plugin, scenes_root, app_config):
    await plugin.handle_save_default_character(
        {"data": {"name": "Player", "gender": "female", "description": "a player"}}
    )


async def _drive_remove_scene_from_recents(plugin, scenes_root, app_config):
    project = _make_scene(scenes_root, app_config)
    await plugin.handle_remove_scene_from_recents({"path": str(project / "save.json")})


async def _drive_delete_scene(plugin, scenes_root, app_config):
    project = _make_scene(scenes_root, app_config)
    await plugin.handle_delete_scene({"path": str(project / "save.json")})


async def _drive_delete_scene_project(plugin, scenes_root, app_config):
    project = _make_scene(scenes_root, app_config)
    await plugin.handle_delete_scene_project({"path": str(project)})


EMITTERS = {
    "handle_save_default_character": _drive_save_default_character,
    "handle_remove_scene_from_recents": _drive_remove_scene_from_recents,
    "handle_delete_scene": _drive_delete_scene,
    "handle_delete_scene_project": _drive_delete_scene_project,
}


def _emitting_handlers() -> set[str]:
    """`ConfigPlugin` methods that push an app_config payload.

    Both forms count: a call to the shared builder, and a hand written payload
    naming the message type itself.
    """
    tree = ast.parse(inspect.getsource(server_config))
    (plugin_cls,) = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ConfigPlugin"
    ]

    emitters = set()
    for method in plugin_cls.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(method):
            if (isinstance(node, ast.Constant) and node.value == "app_config") or (
                isinstance(node, ast.Name) and node.id == "app_config_message"
            ):
                emitters.add(method.name)
                break

    return emitters


def test_every_app_config_emitter_is_exercised():
    assert _emitting_handlers() == set(EMITTERS)


@pytest.mark.parametrize("handler", sorted(EMITTERS))
async def test_app_config_payload_carries_the_resolved_theme(
    handler, plugin, scenes_root, app_config, active_theme
):
    await EMITTERS[handler](plugin, scenes_root, app_config)

    pushed = plugin.websocket_handler.app_configs
    assert pushed

    for message in pushed:
        assert message["data"]["theme"] == resolve_theme(app_config)
        assert message["data"]["theme"]["colors"]["app"]["primary"] == "#123456"
        assert message["data"]["theme"]["code_editor"] == "nord"


async def test_payload_is_the_config_plus_the_theme(app_config, active_theme):
    message = server_config.app_config_message(app_config)

    assert message["type"] == "app_config"
    assert message["data"]["theme"] == resolve_theme(app_config)
    assert message["data"]["appearance"] == app_config.model_dump()["appearance"]
