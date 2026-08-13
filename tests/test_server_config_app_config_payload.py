"""
The `app_config` push the config websocket handlers broadcast.

The resolved theme is not part of the config model - the frontend only ever
gets it attached to this payload, and it repaints (and restores appearances)
from it. A handler that pushes a bare `config.model_dump()` therefore leaves
the frontend with no theme at all, so every emitter goes through
`app_config_message`.
"""

import inspect
import json

import pytest

import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.files
import talemate.server.config as server_config
from talemate.client.system_prompts import RENDER_CACHE as SYSTEM_PROMPTS_CACHE
from talemate.config import Config
from talemate.config.schema import RecentScene
from talemate.server.config import ConfigPlugin
from talemate.world_state.templates.theme import resolve_theme


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

    def app_config_pushes(self) -> list[dict]:
        return [m for m in self.messages if m.get("type") == "app_config"]


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


def _make_scene(scenes_root, name="adventure"):
    project = scenes_root / name
    project.mkdir(parents=True)
    save_file = project / "save.json"
    save_file.write_text(json.dumps({"name": name}))
    return save_file


async def save_default_character(plugin, app_config, scenes_root):
    await plugin.handle_save_default_character(
        {
            "data": {
                "name": "Player",
                "gender": "female",
                "description": "a traveller",
            }
        }
    )


async def remove_scene_from_recents(plugin, app_config, scenes_root):
    save_file = _make_scene(scenes_root)
    app_config.recent_scenes.scenes = [
        RecentScene(
            name="Adventure",
            path=str(save_file),
            filename="save.json",
            date="2026-08-12T00:00:00",
        )
    ]
    await plugin.handle_remove_scene_from_recents({"path": str(save_file)})


async def delete_scene(plugin, app_config, scenes_root):
    save_file = _make_scene(scenes_root)
    await plugin.handle_delete_scene({"path": str(save_file)})


async def delete_scene_project(plugin, app_config, scenes_root):
    save_file = _make_scene(scenes_root)
    await plugin.handle_delete_scene_project({"path": str(save_file.parent)})


# every config handler that pushes an app_config of its own
EMITTERS = [
    save_default_character,
    remove_scene_from_recents,
    delete_scene,
    delete_scene_project,
]


@pytest.mark.parametrize("emitter", EMITTERS, ids=lambda fn: fn.__name__)
@pytest.mark.asyncio
async def test_push_carries_the_resolved_theme(
    emitter, plugin, app_config, scenes_root
):
    await emitter(plugin, app_config, scenes_root)

    pushes = plugin.websocket_handler.app_config_pushes()
    assert pushes
    for pushed in pushes:
        assert pushed["data"]["theme"] == resolve_theme(app_config)
        assert pushed["data"]["theme"]["colors"]["app"]["primary"]


@pytest.mark.parametrize("emitter", EMITTERS, ids=lambda fn: fn.__name__)
@pytest.mark.asyncio
async def test_push_carries_the_system_prompt_defaults(
    emitter, plugin, app_config, scenes_root
):
    """Both extras ride along, in the order the other two emitters use.

    A payload without the prompt defaults blanks them app-wide, since
    `TalemateApp` assigns the payload wholesale with no carry-forward of its
    own. The order matters only so every emitter produces the same shape.
    """
    await emitter(plugin, app_config, scenes_root)

    pushes = plugin.websocket_handler.app_config_pushes()
    assert pushes
    for pushed in pushes:
        assert pushed["data"]["system_prompt_defaults"] is SYSTEM_PROMPTS_CACHE
        assert list(pushed["data"])[-2:] == ["system_prompt_defaults", "theme"]


@pytest.mark.parametrize("emitter", EMITTERS, ids=lambda fn: fn.__name__)
@pytest.mark.asyncio
async def test_push_resolves_the_theme_off_the_live_config(
    emitter, plugin, app_config, scenes_root, monkeypatch
):
    """A push carrying a theme resolved from anything but the config it ships
    would hand the frontend a theme the config does not name."""
    resolved_for = []

    def _resolve(config):
        resolved_for.append(config)
        return {"name": "Midnight"}

    monkeypatch.setattr(server_config, "resolve_theme", _resolve)

    await emitter(plugin, app_config, scenes_root)

    pushes = plugin.websocket_handler.app_config_pushes()
    assert pushes
    for pushed in pushes:
        assert pushed["data"]["theme"] == {"name": "Midnight"}
    assert resolved_for and all(config is app_config for config in resolved_for)


def test_no_handler_assembles_the_push_by_hand():
    """The theme went missing from four handlers because each assembled the
    payload itself - a new one must not start over."""
    source = inspect.getsource(ConfigPlugin)

    assert '"type": "app_config"' not in source
