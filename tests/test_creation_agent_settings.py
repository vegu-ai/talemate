"""Creation pins survive global changes without writing global or prior-scene state."""

import asyncio
import base64
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image, PngImagePlugin

from conftest import MockScene, bootstrap_scene
from talemate.config import get_config
from talemate.instance import AGENTS
from talemate.load import SceneInitialization, load_scene
from talemate.load.creation_agent_settings import CreationAgentSettings
from talemate.scene_agent_settings import SceneAgentSettings, resolve_link_on_load
from talemate.tale_mate import Scene


DATA = Path(__file__).parent / "data" / "creation_agent_settings"
PRESETS = json.loads((DATA / "presets.json").read_text())
ROWS = [
    (mode, stop, values)
    for mode, stops in PRESETS.items()
    for stop, values in stops.items()
]


def snapshot(values):
    result = {}
    for key, value in values.items():
        agent, action, config = key.split(".")
        target = result.setdefault(agent, {"actions": {}})["actions"].setdefault(
            action, {"config": {}}
        )
        if config == "enabled":
            target["enabled"] = value
        else:
            target.setdefault("config", {})[config] = {"value": value}
    return result


def effective(values):
    result = {}
    for key in values:
        agent, action, config = key.split(".")
        result[key] = (
            AGENTS[agent].resolve_enabled(action)
            if config == "enabled"
            else AGENTS[agent].resolve_config(action, config)
        )
    return result


def globals_snapshot():
    return {
        "stored": copy.deepcopy(get_config().model_dump()["agents"]),
        "runtime": {
            name: {key: action.model_dump() for key, action in agent.actions.items()}
            for name, agent in AGENTS.items()
        },
    }


@pytest.fixture
def creation_env(tmp_path, monkeypatch):
    scene = MockScene()
    bootstrap_scene(scene)
    scene.active = True
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    scene.project_name = "creation-test"
    memory = AGENTS["memory"]
    monkeypatch.setattr(memory, "set_db", AsyncMock())
    monkeypatch.setattr(memory, "close_db", lambda scene: None)
    monkeypatch.setattr(memory, "get_document", AsyncMock(return_value={}))
    monkeypatch.setattr(Scene, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(Scene, "add_to_recent_scenes", AsyncMock())
    return scene


@pytest.mark.parametrize("mode,stop,values", ROWS, ids=[f"{m}-{s}" for m, s, _ in ROWS])
@pytest.mark.parametrize(
    "equal", [False, True], ids=["different-globals", "equal-globals"]
)
async def test_every_preset_pins_and_roundtrips_without_global_mutation(
    creation_env, mode, stop, values, equal
):
    scene = creation_env
    scene.knowledge_eligibility = mode
    for key, value in values.items():
        agent, action, config = key.split(".")
        target = AGENTS[agent].actions[action]
        global_value = (
            value if equal else (not value if isinstance(value, bool) else value + 1)
        )
        if config == "enabled":
            target.enabled = global_value
        else:
            target.config[config].value = global_value
    before = globals_snapshot()
    settings = CreationAgentSettings(snapshot(values), lambda: True)
    settings.install(scene)
    assert effective(values) == values
    assert not list(Path(scene.save_dir).rglob("creation-*.json"))
    await settings.persist(scene)
    assert globals_snapshot() == before
    path = scene.agent_overrides.filepath
    assert json.loads(path.read_text())["agents"] == snapshot(values)
    serialized = scene.serialize
    scene.agent_overrides = None
    await resolve_link_on_load(scene, serialized)
    assert effective(values) == values
    for key, value in values.items():
        agent, action, config = key.split(".")
        if config == "enabled":
            AGENTS[agent].actions[action].enabled = not value
        else:
            AGENTS[agent].actions[action].config[config].value = (
                not value if isinstance(value, bool) else value + 2
            )
    assert effective(values) == values
    for key in values:
        agent, action, config = key.split(".")
        if config == "enabled":
            scene.agent_overrides.clear_enabled(agent, action)
        else:
            scene.agent_overrides.clear_value(agent, action, config)
    assert all(value != values[key] for key, value in effective(values).items())


async def test_reused_project_preserves_prior_file_and_unrelated_overrides(
    creation_env,
):
    scene = creation_env
    prior_path = Path(scene.save_dir) / "agent-settings" / "agent-settings.json"
    prior = SceneAgentSettings(filepath=prior_path)
    prior.set_value("narrator", "unrelated", "keep", 42)
    prior.set_value("conversation", "character_knowledge", "ledger", False)
    await prior.write_to_file()
    prior_bytes = prior_path.read_bytes()
    scene.agent_overrides = prior
    settings = CreationAgentSettings(
        snapshot(PRESETS["legacy"]["balanced"]), lambda: True
    )
    settings.install(scene)
    await settings.persist(scene)
    assert scene.agent_overrides.get_value("narrator", "unrelated", "keep") == 42
    assert prior.get_value("conversation", "character_knowledge", "ledger") is False
    assert prior_path.read_bytes() == prior_bytes
    assert scene.agent_overrides.filepath != prior_path


@pytest.mark.parametrize(
    "invalid",
    [
        {"missing": {"actions": {}}},
        {"conversation": {"actions": {"unknown": {"enabled": True}}}},
        {
            "conversation": {
                "actions": {
                    "character_knowledge": {"config": {"unknown": {"value": True}}}
                }
            }
        },
    ],
)
async def test_invalid_snapshot_is_atomic(creation_env, invalid):
    before = globals_snapshot()
    with pytest.raises(ValueError):
        CreationAgentSettings(
            {**snapshot(PRESETS["legacy"]["balanced"]), **invalid}, lambda: True
        )
    assert creation_env.agent_overrides is None
    assert globals_snapshot() == before


async def test_pending_settings_cannot_be_written_by_another_caller(creation_env):
    settings = CreationAgentSettings(
        snapshot(PRESETS["legacy"]["balanced"]), lambda: True
    )
    settings.install(creation_env)
    with pytest.raises(OSError, match="creation is still in progress"):
        await creation_env.agent_overrides.write_to_file()


async def test_superseded_creation_never_persists(creation_env):
    current = True
    settings = CreationAgentSettings(
        snapshot(PRESETS["legacy"]["balanced"]), lambda: current
    )
    settings.install(creation_env)
    current = False
    with pytest.raises(asyncio.CancelledError):
        await settings.persist(creation_env)
    assert not list(Path(creation_env.save_dir).rglob("creation-*.json"))


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_or_cancelled_persistence_removes_only_owned_file(
    creation_env, monkeypatch, cancelled
):
    directory = Path(creation_env.save_dir) / "agent-settings"
    directory.mkdir(parents=True, exist_ok=True)
    prior = directory / "prior.json"
    prior.write_text('{"agents": {}}')
    before = globals_snapshot()
    current = True
    settings = CreationAgentSettings(
        snapshot(PRESETS["legacy"]["balanced"]), lambda: current
    )
    settings.install(creation_env)

    async def interrupted_write(overlay):
        nonlocal current
        overlay.filepath.write_text("partial")
        if cancelled:
            current = False
        else:
            raise OSError("disk unavailable")

    monkeypatch.setattr(SceneAgentSettings, "write_to_file", interrupted_write)
    with pytest.raises(asyncio.CancelledError if cancelled else OSError):
        await settings.persist(creation_env)
    assert settings.overlay.pending
    assert not settings.overlay.filepath.exists()
    assert prior.read_text() == '{"agents": {}}'
    assert globals_snapshot() == before


@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_new_story_installs_before_activation_and_preserves_unsaved_lifecycle(
    creation_env, mode, monkeypatch
):
    import talemate.load as loader

    values = PRESETS[mode]["balanced"]
    observed = []

    async def player(scene, **kwargs):
        observed.append(effective(values))
        assert scene.knowledge_eligibility == mode
        assert scene.agent_overrides.pending

    monkeypatch.setattr(loader, "handle_no_player_character", player)
    before = globals_snapshot()
    loaded = await load_scene(
        creation_env,
        "$NEW_SCENE$",
        scene_initialization=SceneInitialization(
            character_knowledge=mode == "perception", agent_settings=snapshot(values)
        ),
    )
    assert observed == [values]
    assert loaded.filename is None
    assert loaded.name == ""
    assert loaded.agent_overrides.filepath.exists()
    assert loaded.agent_overrides.pending is False
    assert globals_snapshot() == before


@pytest.mark.parametrize("extension", ["json", "png"])
@pytest.mark.parametrize("mode", ["legacy", "perception"])
@pytest.mark.parametrize(
    "reused", [False, True], ids=["fresh-project", "reused-project"]
)
async def test_real_card_loader_pins_before_player_setup_and_saves_link(
    creation_env, mode, extension, reused, tmp_path, monkeypatch
):
    import talemate.load.character_card as card

    source = tmp_path / f"card.{extension}"
    if extension == "json":
        source.write_bytes((DATA / "card.json").read_bytes())
    else:
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text(
            "chara", base64.b64encode((DATA / "card.json").read_bytes()).decode()
        )
        Image.new("RGB", (16, 16)).save(source, pnginfo=metadata)
    creation_env.project_name = None
    default_path = tmp_path / "hero" / "agent-settings" / "agent-settings.json"
    if reused:
        default = SceneAgentSettings(filepath=default_path)
        default.set_value("conversation", "generation_override", "length", 384)
        default.set_value("conversation", "character_knowledge", "ledger", False)
        await default.write_to_file()
        prior_bytes = default_path.read_bytes()
    assert creation_env.agent_overrides is None
    values = PRESETS[mode]["balanced"]
    observed = []
    original = card._setup_player_character_from_options

    async def player(scene, options):
        observed.append(effective(values))
        assert scene.knowledge_eligibility == mode
        assert scene.agent_overrides.pending
        if reused:
            assert scene.project_name == "hero"
            assert (
                AGENTS["conversation"].resolve_config("generation_override", "length")
                == 384
            )
        return await original(scene, options)

    monkeypatch.setattr(card, "_setup_player_character_from_options", player)
    before = globals_snapshot()
    initialization = SceneInitialization(
        character_knowledge=mode == "perception",
        agent_settings=snapshot(values),
        character_card_import_options=card.CharacterCardImportOptions(
            determine_content_context=False,
            extract_description=False,
            extract_attributes=False,
            extract_dialogue_instructions=False,
            extract_dialogue_examples=False,
            generate_story_intent=False,
            generate_episode_titles=False,
        ),
    )
    loaded = await load_scene(
        creation_env, str(source), scene_initialization=initialization
    )
    assert observed == [values]
    assert effective(values) == values
    assert globals_snapshot() == before
    assert loaded.agent_overrides.filepath.exists()
    saved = json.loads(Path(loaded.full_path).read_text())
    assert saved["agent_settings_file"] == loaded.agent_overrides.filename
    assert saved["knowledge_eligibility"] == mode
    assert loaded.mock_client.prompt_history == []
    if reused:
        assert loaded.agent_overrides.filepath != default_path
        assert default_path.read_bytes() == prior_bytes
        assert (
            loaded.agent_overrides.get_value(
                "conversation", "generation_override", "length"
            )
            == 384
        )

        saved_path = loaded.full_path
        loaded.agent_overrides = None
        reloaded = await load_scene(loaded, saved_path)
        assert reloaded.knowledge_eligibility == mode
        assert effective(values) == values
        assert (
            AGENTS["conversation"].resolve_config("generation_override", "length")
            == 384
        )
        assert reloaded.agent_overrides.filepath != default_path
        assert default_path.read_bytes() == prior_bytes
        assert globals_snapshot() == before


async def test_failed_new_story_does_not_persist_creation_settings(
    creation_env, monkeypatch
):
    import talemate.load as loader

    monkeypatch.setattr(
        loader,
        "handle_no_player_character",
        AsyncMock(side_effect=RuntimeError("creation failed")),
    )
    with pytest.raises(RuntimeError, match="creation failed"):
        await load_scene(
            creation_env,
            "$NEW_SCENE$",
            scene_initialization=SceneInitialization(
                agent_settings=snapshot(PRESETS["legacy"]["balanced"])
            ),
        )
    assert not list(Path(creation_env.save_dir).rglob("creation-*.json"))
