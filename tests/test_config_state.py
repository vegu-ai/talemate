"""
Unit tests for `talemate.config.state` — config persistence helpers.

Covers:
- `_load_config` (reads yaml, decrypts, builds Config).
- `get_config` (lazy initialization).
- `update_config` (partial via dict).
- `save_config` (round-trip + cleanup of inference defaults / unchanged
  presets / unified_api_key configs / dangling preset_groups).
- `cleanup_removed_clients`, `cleanup_removed_agents`,
  `cleanup_removed_recent_scenes`, `cleanup_instructor_embeddings`.
- `commit_config` (no-op when not dirty, otherwise saves and clears flag).

We isolate filesystem and signal side-effects so the test never writes to
the real config.yaml. Because `tests/conftest.py` swaps `CONFIG` to the
example config, we restore CONFIG between tests where we mutate it.
"""

from pathlib import Path

import pytest
import yaml

import talemate.config.state as config_state
from talemate.config.schema import (
    Agent,
    AgentAction,
    AgentActionConfig,
    Client,
    Config,
    EmbeddingFunctionPreset,
    InferencePresetGroup,
    InferencePresets,
    RecentScene,
    SceneAppearance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Replace `CONFIG` with a fresh, fully-populated Config and redirect
    CONFIG_FILE to a tmp_path. Restores CONFIG on teardown so the
    session-level autouse fixture from conftest still has its expected
    state for the next test."""
    import talemate.instance as instance_module
    import talemate.emit.async_signals as async_signals

    original_config = config_state.CONFIG
    cfg = Config()
    cfg.dirty = False
    config_state.CONFIG = cfg

    fake_path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_state, "CONFIG_FILE", fake_path)

    # Some tests (when run in the same session) pollute instance.AGENTS via
    # bootstrap_scene; the registered MockMemoryAgent then receives every
    # config.changed signal which may crash on missing attributes. Snapshot
    # and isolate.
    original_agents = dict(instance_module.AGENTS)
    instance_module.AGENTS.clear()

    # Snapshot the config.changed signal receivers and restore on exit so
    # we don't fire stale handlers from leaked memory agents.
    changed_signal = async_signals.get("config.changed")
    changed_follow_signal = async_signals.get("config.changed.follow")
    original_receivers = list(changed_signal.receivers)
    original_follow_receivers = list(changed_follow_signal.receivers)
    changed_signal.receivers.clear()
    changed_follow_signal.receivers.clear()

    yield cfg

    config_state.CONFIG = original_config
    instance_module.AGENTS.clear()
    instance_module.AGENTS.update(original_agents)
    changed_signal.receivers[:] = original_receivers
    changed_follow_signal.receivers[:] = original_follow_receivers


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_loads_minimal_yaml(self, monkeypatch, tmp_path):
        path = tmp_path / "tiny.yaml"
        path.write_text("agents: {}\nclients: {}\n")
        monkeypatch.setattr(config_state, "CONFIG_FILE", path)

        cfg = config_state._load_config()
        assert isinstance(cfg, Config)
        assert cfg.agents == {}
        assert cfg.clients == {}

    def test_handles_empty_yaml_file(self, monkeypatch, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        monkeypatch.setattr(config_state, "CONFIG_FILE", path)

        cfg = config_state._load_config()
        # Empty yaml -> {} -> Config defaults populated
        assert isinstance(cfg, Config)
        assert cfg.dirty is False

    def test_decrypts_api_keys_during_load(self, monkeypatch, tmp_path):
        # Write an unencrypted (plaintext-passthrough) value; decrypt_value
        # returns input unchanged when ENC_PREFIX is absent.
        path = tmp_path / "with_keys.yaml"
        path.write_text("openai:\n  api_key: 'plaintext-key'\n")
        monkeypatch.setattr(config_state, "CONFIG_FILE", path)

        cfg = config_state._load_config()
        assert cfg.openai.api_key == "plaintext-key"


class TestGetConfig:
    def test_returns_existing_config_without_reloading(self, monkeypatch):
        sentinel = Config()
        monkeypatch.setattr(config_state, "CONFIG", sentinel)
        # Should NOT trigger _load_config because CONFIG is non-None.
        # If it did, it would crash on the missing CONFIG_FILE.
        assert config_state.get_config() is sentinel

    def test_lazy_loads_when_none(self, monkeypatch, tmp_path):
        # Force CONFIG=None and provide a valid config file
        path = tmp_path / "load.yaml"
        path.write_text("agents: {}\n")
        monkeypatch.setattr(config_state, "CONFIG", None)
        monkeypatch.setattr(config_state, "CONFIG_FILE", path)

        cfg = config_state.get_config()
        assert isinstance(cfg, Config)
        # Subsequent call returns same instance (cached)
        assert config_state.get_config() is cfg


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_partial_dict_only_overrides_specified_keys(self, isolated_config):
        # Pre-set agents with one entry to verify it's overwritten exactly
        isolated_config.agents = {"keep": Agent(name="keep")}
        isolated_config.clients = {"original": Client(type="openai", name="original")}

        # Update only `agents` via dict — clients should be preserved
        await config_state.update_config(
            {"agents": {"new_only": Agent(name="new_only")}}
        )

        assert "new_only" in config_state.CONFIG.agents
        assert "keep" not in config_state.CONFIG.agents
        assert "original" in config_state.CONFIG.clients

    @pytest.mark.asyncio
    async def test_marks_config_dirty(self, isolated_config):
        isolated_config.dirty = False
        await config_state.update_config({"agents": {}})
        assert config_state.CONFIG.dirty is True


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


def _read_back(path: Path) -> dict:
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


class TestSaveConfig:
    def test_writes_yaml_to_config_file_path(self, isolated_config, tmp_path):
        config_state.save_config()
        target = tmp_path / "config.yaml"
        assert target.exists()
        # File should be valid yaml round-tripping back to dict
        data = _read_back(target)
        assert isinstance(data, dict)

    def test_drops_inference_defaults_and_embeddings_defaults(
        self, isolated_config, tmp_path
    ):
        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        # Defaults are stripped before write
        assert "inference_defaults" not in data["presets"]
        assert "embeddings_defaults" not in data["presets"]

    def test_only_persists_changed_inference_presets(self, isolated_config, tmp_path):
        # Mutate one preset to changed=True so it should survive
        isolated_config.presets.inference.analytical.changed = True
        # Leave conversation as default (changed=False) -> must be dropped

        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        # Only changed presets remain (or `inference` removed entirely if empty)
        if "inference" in data["presets"]:
            preserved = set(data["presets"]["inference"].keys())
            assert "analytical" in preserved
            assert "conversation" not in preserved

    def test_drops_inference_section_when_no_presets_changed(
        self, isolated_config, tmp_path
    ):
        # Default state: nothing is "changed" → after the per-preset prune the
        # `inference` dict is empty → save_config should delete it.
        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        assert "inference" not in data["presets"]

    def test_clears_dangling_preset_group_reference(self, isolated_config, tmp_path):
        # client points at "ghost-group" not present in inference_groups
        client = Client(type="openai", name="c1", preset_group="ghost-group")
        isolated_config.clients = {"c1": client}
        # Ensure no matching preset group exists
        isolated_config.presets.inference_groups = {}

        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        assert data["clients"]["c1"]["preset_group"] == ""

    def test_keeps_valid_preset_group_reference(self, isolated_config, tmp_path):
        # Group exists, with a changed preset to keep it alive on save
        presets = InferencePresets()
        presets.analytical.changed = True
        isolated_config.presets.inference_groups = {
            "real-group": InferencePresetGroup(name="real-group", presets=presets),
        }
        isolated_config.clients = {
            "c1": Client(type="openai", name="c1", preset_group="real-group")
        }

        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        assert data["clients"]["c1"]["preset_group"] == "real-group"

    def test_inference_groups_drop_unchanged_presets(self, isolated_config, tmp_path):
        presets = InferencePresets()
        presets.analytical.changed = True  # keep this one
        # creative is default (changed=False) -> drop
        isolated_config.presets.inference_groups = {
            "g1": InferencePresetGroup(name="g1", presets=presets),
        }

        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        group = data["presets"]["inference_groups"]["g1"]
        assert "analytical" in group["presets"]
        assert "creative" not in group["presets"]

    def test_strip_unified_api_key_configs_removes_unified_keys(
        self, isolated_config, tmp_path, monkeypatch
    ):
        """
        _strip_unified_api_key_configs removes saved config entries whose
        runtime AgentActionConfig.type == "unified_api_key" before persist.
        """
        from talemate.agents.base import Agent as RuntimeAgent
        from talemate.agents.base import AgentAction as RuntimeAction
        from talemate.agents.base import AgentActionConfig as RuntimeConfig
        import talemate.instance as instance_module

        # Build a real `Agent` subclass with the runtime action structure the
        # function-under-test reads. Using the production `Agent` class
        # (instead of a `_FakeAgent` stub) keeps the test honest if the
        # `actions`/`AgentAction`/`AgentActionConfig` API changes.
        class _TestAgent(RuntimeAgent):
            agent_type = "fakeagent"

            def __init__(self):
                self.actions = {
                    "main": RuntimeAction(
                        label="Main",
                        config={
                            "secret_ref": RuntimeConfig(
                                type="unified_api_key", label="secret"
                            ),
                            "setting": RuntimeConfig(type="text", label="other"),
                        },
                    )
                }

        original_agents = instance_module.AGENTS
        monkeypatch.setattr(instance_module, "AGENTS", {"fakeagent": _TestAgent()})

        # Saved config (what would otherwise hit disk) for the same shape:
        isolated_config.agents = {
            "fakeagent": Agent(
                name="fakeagent",
                actions={
                    "main": AgentAction(
                        config={
                            "secret_ref": AgentActionConfig(value="will-be-stripped"),
                            "setting": AgentActionConfig(value="kept"),
                        }
                    )
                },
            )
        }

        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        action_cfg = data["agents"]["fakeagent"]["actions"]["main"]["config"]
        assert "secret_ref" not in action_cfg
        assert action_cfg["setting"]["value"] == "kept"

        # restore (paranoia - monkeypatch will too)
        instance_module.AGENTS = original_agents

    def test_drops_empty_system_prompts(self, isolated_config, tmp_path):
        # Default Config has system_prompts as default SystemPrompts() — model_dump
        # may produce an empty dict; ensure save handles that path without crashing.
        config_state.save_config()
        data = _read_back(tmp_path / "config.yaml")
        # Empty system_prompts shouldn't be persisted (assertion lenient — only
        # checks: if present, it was non-empty)
        if "system_prompts" in data:
            assert data["system_prompts"]


# ---------------------------------------------------------------------------
# cleanup helpers
# ---------------------------------------------------------------------------


class TestCleanupRemovedClients:
    def test_removes_client_with_unknown_type(self, isolated_config):
        isolated_config.clients = {
            "ghost": Client(type="totally_made_up_type", name="ghost")
        }
        config_state.cleanup_removed_clients(isolated_config)
        assert "ghost" not in isolated_config.clients

    def test_keeps_client_with_known_type(self, isolated_config):
        # "openai" client class is registered on import
        isolated_config.clients = {"keep": Client(type="openai", name="keep")}
        config_state.cleanup_removed_clients(isolated_config)
        assert "keep" in isolated_config.clients

    def test_none_config_is_noop(self):
        # Should not raise on None
        config_state.cleanup_removed_clients(None)


class TestCleanupRemovedAgents:
    def test_removes_agent_with_unregistered_name(self, isolated_config):
        isolated_config.agents = {"phantom": Agent(name="phantom")}
        config_state.cleanup_removed_agents(isolated_config)
        assert "phantom" not in isolated_config.agents

    def test_keeps_agent_with_registered_name(self, isolated_config):
        # world_state is a registered agent type
        isolated_config.agents = {"world_state": Agent(name="world_state")}
        config_state.cleanup_removed_agents(isolated_config)
        assert "world_state" in isolated_config.agents

    def test_none_config_is_noop(self):
        config_state.cleanup_removed_agents(None)


class TestCleanupRemovedRecentScenes:
    def test_drops_scenes_with_missing_paths(self, isolated_config, tmp_path):
        existing = tmp_path / "exists.json"
        existing.write_text("{}")

        isolated_config.recent_scenes.scenes = [
            RecentScene(
                name="exists",
                path=str(existing),
                filename="exists.json",
                date="2026-01-01T00:00:00",
            ),
            RecentScene(
                name="ghost",
                path=str(tmp_path / "ghost.json"),
                filename="ghost.json",
                date="2026-01-01T00:00:00",
            ),
        ]

        config_state.cleanup_removed_recent_scenes(isolated_config)
        names = [s.name for s in isolated_config.recent_scenes.scenes]
        assert names == ["exists"]

    def test_keeps_when_all_paths_exist(self, isolated_config, tmp_path):
        existing = tmp_path / "exists.json"
        existing.write_text("{}")
        isolated_config.recent_scenes.scenes = [
            RecentScene(
                name="exists",
                path=str(existing),
                filename="exists.json",
                date="2026-01-01T00:00:00",
            )
        ]
        config_state.cleanup_removed_recent_scenes(isolated_config)
        assert len(isolated_config.recent_scenes.scenes) == 1


class TestCleanupInstructorEmbeddings:
    def _set_memory_embeddings(self, cfg, preset_key):
        cfg.agents["memory"] = Agent(
            name="memory",
            actions={
                "_config": AgentAction(
                    config={"embeddings": AgentActionConfig(value=preset_key)}
                )
            },
        )

    def test_drops_instructor_preset_and_resets_memory_embeddings(
        self, isolated_config
    ):
        isolated_config.presets.embeddings["custom-instructor"] = (
            EmbeddingFunctionPreset(
                embeddings="instructor", model="hkunlp/instructor-xl"
            )
        )
        isolated_config.presets.embeddings["fine"] = EmbeddingFunctionPreset()
        self._set_memory_embeddings(isolated_config, "custom-instructor")
        isolated_config.dirty = False

        config_state.cleanup_instructor_embeddings(isolated_config)

        assert "custom-instructor" not in isolated_config.presets.embeddings
        assert "fine" in isolated_config.presets.embeddings
        memory_embed = (
            isolated_config.agents["memory"].actions["_config"].config["embeddings"]
        )
        assert memory_embed.value == "default"
        assert isolated_config.dirty is True

    def test_no_change_when_no_instructor_preset(self, isolated_config):
        # Default embeddings are not instructor → nothing to do
        self._set_memory_embeddings(isolated_config, "default")
        isolated_config.dirty = False
        config_state.cleanup_instructor_embeddings(isolated_config)
        assert isolated_config.dirty is False

    def test_none_config_is_noop(self):
        config_state.cleanup_instructor_embeddings(None)


# ---------------------------------------------------------------------------
# commit_config
# ---------------------------------------------------------------------------


class TestCommitConfig:
    @pytest.mark.asyncio
    async def test_noop_when_not_dirty(self, isolated_config, tmp_path, monkeypatch):
        # set up a sentinel: if save_config is called we'll see a file appear
        target = tmp_path / "config.yaml"
        assert not target.exists()
        isolated_config.dirty = False

        await config_state.commit_config()
        # save_config should NOT have written anything
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_saves_and_clears_dirty_flag(self, isolated_config, tmp_path):
        isolated_config.dirty = True
        await config_state.commit_config()
        assert (tmp_path / "config.yaml").exists()
        assert isolated_config.dirty is False


# ---------------------------------------------------------------------------
# SceneAppearance.message_assets defaults
# ---------------------------------------------------------------------------


class TestSceneAppearanceMessageAssets:
    DEFAULT_KEYS = {"avatar", "card", "scene_illustration", "scene_background"}

    def test_defaults_include_all_entries(self):
        appearance = SceneAppearance()
        assert set(appearance.message_assets.keys()) == self.DEFAULT_KEYS
        # scene backgrounds default to full-width display
        assert appearance.message_assets["scene_background"].size == "big"
        assert appearance.message_assets["scene_illustration"].size == "medium"

    def test_missing_entries_are_filled(self):
        # configs saved before scene_background existed omit it — the
        # validator must fill the gap without touching stored values
        appearance = SceneAppearance(
            message_assets={
                "avatar": {"cadence": "never", "size": "small"},
                "card": {},
                "scene_illustration": {"size": "big"},
            }
        )
        assert set(appearance.message_assets.keys()) == self.DEFAULT_KEYS
        assert appearance.message_assets["avatar"].cadence == "never"
        assert appearance.message_assets["avatar"].size == "small"
        assert appearance.message_assets["scene_illustration"].size == "big"
        assert appearance.message_assets["scene_background"].size == "big"


class TestEnvVariableNameValidation:
    def test_invalid_names_dropped(self):
        # a hand-edited config can hold names the UI would reject; '=' in a
        # name would fail subprocess spawns far from the cause
        config = Config(
            env={
                "GOOD_NAME": "v1",
                "_ALSO_GOOD": "v2",
                "BAD=NAME": "v3",
                "9STARTS_WITH_DIGIT": "v4",
                "has space": "v5",
            }
        )
        assert config.env == {"GOOD_NAME": "v1", "_ALSO_GOOD": "v2"}
