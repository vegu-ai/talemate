"""Unit tests for `talemate.scene_agent_settings` and the
`Agent.resolve_config` / `Agent.resolve_enabled` helpers.

Tests use real Agent subclasses and a lightweight scene-like object so the
read-time resolution path is exercised end to end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from talemate.agents.base import Agent, AgentAction, AgentActionConfig
from talemate.scene_agent_settings import (
    AGENT_SETTINGS_DIRNAME,
    DEFAULT_SETTINGS_FILENAME,
    SceneAgentSettings,
    UNSET,
    agent_settings_dir,
    apply_scene_settings_link,
    is_safe_settings_filename,
    is_settings_filename,
    list_settings_files,
    resolve_link_on_load,
)
from talemate.tale_mate import Scene


class _ResolverAgent(Agent):
    """Real Agent subclass with a couple of scene_overridable fields."""

    agent_type = "resolver-test"
    verbose_name = "Resolver Test"
    requires_llm_client = False

    def __init__(self, scene=None):
        self.actions = {
            "container": AgentAction(
                enabled=True,
                label="Container",
                container=True,
                can_be_disabled=True,
                enabled_scene_overridable=True,
                config={
                    "fmt": AgentActionConfig(
                        type="text",
                        label="fmt",
                        value="global-fmt",
                        scene_overridable=True,
                    ),
                    "fixed": AgentActionConfig(
                        type="text",
                        label="fixed",
                        value="global-fixed",
                    ),
                    "tags": AgentActionConfig(
                        type="flags",
                        label="tags",
                        value=["a", "b"],
                        scene_overridable=True,
                    ),
                },
            ),
        }
        self.scene = scene
        self.processing = 0


@pytest.fixture
def scene_with_save_dir(tmp_path: Path, monkeypatch) -> Scene:
    """Real ``Scene`` whose ``save_dir`` is rooted in ``tmp_path``.

    Patches the class-level ``scenes_dir`` so ``scene.save_dir`` resolves
    inside the per-test ``tmp_path`` instead of the real ``scenes/`` folder.
    """
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    scene = Scene()
    scene._project_name = "test-project"
    scene.filename = "scene.json"
    return scene


def _scene_with_overrides(overrides: SceneAgentSettings | None) -> Scene:
    """Real ``Scene`` instance with ``agent_overrides`` preset.

    The resolver only reads ``scene.agent_overrides``, but per repo
    convention tests use real collaborator types rather than stand-ins.
    """
    scene = Scene()
    scene.agent_overrides = overrides
    return scene


# ---------------------------------------------------------------------------
# SceneAgentSettings: I/O and round-trip
# ---------------------------------------------------------------------------


class TestSceneAgentSettingsIO:
    @pytest.mark.asyncio
    async def test_write_and_reload_preserves_overrides(self, tmp_path: Path):
        fp = tmp_path / "agent-settings.json"
        s = SceneAgentSettings(filepath=fp)
        s.set_value("conv", "act", "field", "narrative")
        s.set_enabled("conv", "act", False)
        await s.write_to_file()

        s2 = SceneAgentSettings(filepath=fp)
        await s2.init_from_file()
        assert s2.get_value("conv", "act", "field") == "narrative"
        assert s2.get_enabled("conv", "act") is False

    @pytest.mark.asyncio
    async def test_write_omits_kind_discriminator(self, tmp_path: Path):
        # Filename-prefix identification means we no longer write a `_kind`
        # marker into the file. Asserts we haven't accidentally re-added it.
        fp = tmp_path / "agent-settings.json"
        s = SceneAgentSettings(filepath=fp)
        s.set_value("a", "b", "c", 1)
        await s.write_to_file()
        data = json.loads(fp.read_text())
        assert "_kind" not in data
        assert "agents" in data

    def test_get_value_returns_unset_when_missing(self, tmp_path: Path):
        s = SceneAgentSettings(filepath=tmp_path / "x.json")
        assert s.get_value("a", "b", "c") is UNSET
        s.set_value("a", "b", "c", "v")
        assert s.get_value("a", "b", "missing") is UNSET
        assert s.get_value("a", "missing", "c") is UNSET
        assert s.get_value("missing", "b", "c") is UNSET

    def test_get_enabled_returns_unset_when_not_set(self, tmp_path: Path):
        s = SceneAgentSettings(filepath=tmp_path / "x.json")
        assert s.get_enabled("a", "b") is UNSET
        # Setting a config value alone should NOT make enabled appear set
        s.set_value("a", "b", "c", "v")
        assert s.get_enabled("a", "b") is UNSET
        s.set_enabled("a", "b", True)
        assert s.get_enabled("a", "b") is True
        s.set_enabled("a", "b", False)
        assert s.get_enabled("a", "b") is False

    def test_clear_value_removes_override(self, tmp_path: Path):
        s = SceneAgentSettings(filepath=tmp_path / "x.json")
        s.set_value("a", "b", "c", "v")
        assert s.get_value("a", "b", "c") == "v"
        s.clear_value("a", "b", "c")
        assert s.get_value("a", "b", "c") is UNSET

    def test_clear_enabled_removes_override(self, tmp_path: Path):
        s = SceneAgentSettings(filepath=tmp_path / "x.json")
        s.set_enabled("a", "b", False)
        assert s.get_enabled("a", "b") is False
        s.clear_enabled("a", "b")
        assert s.get_enabled("a", "b") is UNSET

    @pytest.mark.asyncio
    async def test_write_prunes_empty_containers(self, tmp_path: Path):
        fp = tmp_path / "x.json"
        s = SceneAgentSettings(filepath=fp)
        s.set_value("conv", "act", "f", "v")
        s.clear_value("conv", "act", "f")
        # Now `act` has no enabled override and no config; `conv` has only
        # an empty action. Write should prune both.
        await s.write_to_file()
        data = json.loads(fp.read_text())
        assert data["agents"] == {}

    def test_replace_agent_overrides_sets_full_overlay(self, tmp_path: Path):
        s = SceneAgentSettings(filepath=tmp_path / "x.json")
        s.set_value("conv", "act", "old", "value")
        s.replace_agent_overrides(
            "conv",
            {"actions": {"new_act": {"enabled": False, "config": {"f": {"value": 1}}}}},
        )
        assert s.get_value("conv", "old", "value") is UNSET
        assert s.get_value("conv", "new_act", "f") == 1
        assert s.get_enabled("conv", "new_act") is False

    def test_replace_agent_overrides_empty_drops_agent(self, tmp_path: Path):
        s = SceneAgentSettings(filepath=tmp_path / "x.json")
        s.set_value("conv", "act", "f", "v")
        s.replace_agent_overrides("conv", {})
        assert s.get_value("conv", "act", "f") is UNSET
        assert "conv" not in s.agents


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_is_settings_filename_accepts_any_json(self):
        # The dedicated `agent-settings/` subdir carries the role now, so any
        # non-empty .json filename qualifies.
        assert is_settings_filename("agent-settings.json")
        assert is_settings_filename("strict.json")
        assert is_settings_filename("my-overrides.json")

    def test_is_settings_filename_rejects_non_json(self):
        assert not is_settings_filename("scene.txt")
        assert not is_settings_filename(".json")  # empty stem
        assert not is_settings_filename("")

    def test_is_safe_settings_filename_accepts_any_safe_json(self):
        assert is_safe_settings_filename("agent-settings.json")
        assert is_safe_settings_filename("strict.json")
        assert is_safe_settings_filename("any-name.json")
        # Path traversal — rejected even though the suffix matches.
        assert not is_safe_settings_filename("../agent-settings.json")
        assert not is_safe_settings_filename("foo/agent-settings.json")
        assert not is_safe_settings_filename("scene.txt")

    def test_list_settings_files_reads_from_subdir(self, tmp_path: Path):
        settings_dir = tmp_path / AGENT_SETTINGS_DIRNAME
        settings_dir.mkdir()
        (settings_dir / "agent-settings.json").write_text("{}")
        (settings_dir / "strict.json").write_text("{}")
        (settings_dir / "notes.txt").write_text("ignore me")
        # Files at the root of save_dir must NOT be picked up — the dedicated
        # subdir is what identifies the role.
        (tmp_path / "agent-settings.json").write_text("{}")
        result = list_settings_files(tmp_path)
        assert result == ["agent-settings.json", "strict.json"]

    def test_list_settings_files_missing_subdir_returns_empty(self, tmp_path: Path):
        # Bare save_dir with no agent-settings/ subdir → empty list.
        assert list_settings_files(tmp_path) == []

    def test_agent_settings_dir_returns_subdir(self, tmp_path: Path):
        assert agent_settings_dir(tmp_path) == tmp_path / AGENT_SETTINGS_DIRNAME


# ---------------------------------------------------------------------------
# Agent resolver helpers
# ---------------------------------------------------------------------------


class TestAgentResolveConfig:
    def test_returns_global_value_when_no_scene(self):
        agent = _ResolverAgent(scene=None)
        assert agent.resolve_config("container", "fmt") == "global-fmt"

    def test_returns_global_value_when_scene_has_no_overrides(self):
        agent = _ResolverAgent(scene=_scene_with_overrides(None))
        assert agent.resolve_config("container", "fmt") == "global-fmt"

    def test_returns_global_value_when_field_not_overridden(self, tmp_path: Path):
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))
        assert agent.resolve_config("container", "fmt") == "global-fmt"

    def test_returns_override_when_field_overridden(self, tmp_path: Path):
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        overrides.set_value("resolver-test", "container", "fmt", "narrative")
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))
        assert agent.resolve_config("container", "fmt") == "narrative"

    def test_override_for_one_field_does_not_affect_siblings(self, tmp_path: Path):
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        overrides.set_value("resolver-test", "container", "fmt", "narrative")
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))
        # `fixed` has no override → should fall through to global
        assert agent.resolve_config("container", "fixed") == "global-fixed"

    def test_override_for_other_agent_is_ignored(self, tmp_path: Path):
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        overrides.set_value("other-agent", "container", "fmt", "narrative")
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))
        assert agent.resolve_config("container", "fmt") == "global-fmt"


class TestAgentResolveEnabled:
    def test_returns_global_enabled_when_no_override(self):
        agent = _ResolverAgent(scene=None)
        assert agent.resolve_enabled("container") is True

    def test_returns_override_when_set(self, tmp_path: Path):
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        overrides.set_enabled("resolver-test", "container", False)
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))
        assert agent.resolve_enabled("container") is False

    def test_clear_enabled_falls_back_to_global(self, tmp_path: Path):
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        overrides.set_enabled("resolver-test", "container", False)
        overrides.clear_enabled("resolver-test", "container")
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))
        assert agent.resolve_enabled("container") is True


# ---------------------------------------------------------------------------
# Complex-value overrides (flags / weights / lists / dicts)
# ---------------------------------------------------------------------------


class TestAgentResolveComplexValues:
    """Overrides for list/dict-valued fields must flow through the resolver
    untouched and must not alias the global value."""

    @pytest.mark.asyncio
    async def test_list_override_roundtrips_through_file(self, tmp_path: Path):
        fp = tmp_path / "x.json"
        s = SceneAgentSettings(filepath=fp)
        s.set_value("resolver-test", "container", "tags", ["only-this"])
        await s.write_to_file()

        s2 = SceneAgentSettings(filepath=fp)
        await s2.init_from_file()
        agent = _ResolverAgent(scene=_scene_with_overrides(s2))
        assert agent.resolve_config("container", "tags") == ["only-this"]

    def test_list_override_does_not_alias_global(self, tmp_path: Path):
        # The overlay's stored list must be a distinct object from the
        # global's stored list — overriding `tags` must not bleed into
        # the global config, and vice versa. (The resolver returns values
        # by reference; agents are expected to read but not mutate them.)
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        overrides.set_value("resolver-test", "container", "tags", ["only-this"])
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))

        overlay_list = agent.resolve_config("container", "tags")
        global_list = agent.actions["container"].config["tags"].value
        assert overlay_list is not global_list
        assert overlay_list == ["only-this"]
        assert global_list == ["a", "b"]


# ---------------------------------------------------------------------------
# config_options payload semantics (enabled: false must not be pruned)
# ---------------------------------------------------------------------------


class TestSceneOverridesPayload:
    def test_enabled_false_survives_model_dump(self, tmp_path: Path):
        overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
        overrides.set_enabled("resolver-test", "container", False)
        agent = _ResolverAgent(scene=_scene_with_overrides(overrides))

        payload = Agent._scene_overrides_payload(agent)
        # `exclude_none=True` must NOT prune `enabled: false` — only an unset
        # (None) override should disappear from the payload.
        assert payload["actions"]["container"]["enabled"] is False

    def test_empty_override_returns_empty_payload(self):
        agent = _ResolverAgent(scene=_scene_with_overrides(None))
        assert Agent._scene_overrides_payload(agent) == {}


# ---------------------------------------------------------------------------
# Scene wiring helpers (resolve_link_on_load + apply_scene_settings_link)
# ---------------------------------------------------------------------------


def _write_overlay(scene: Scene, filename: str, *, contents: str | None = None) -> Path:
    """Materialize an overlay file in the scene's agent-settings/ folder."""
    settings_dir = agent_settings_dir(scene.save_dir)
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / filename
    if contents is None:
        path.write_text(json.dumps({"agents": {}}))
    else:
        path.write_text(contents)
    return path


class TestResolveLinkOnLoad:
    @pytest.mark.asyncio
    async def test_opted_out_skips_link(self, scene_with_save_dir: Scene):
        _write_overlay(scene_with_save_dir, DEFAULT_SETTINGS_FILENAME)
        await resolve_link_on_load(
            scene_with_save_dir, {"agent_settings_opted_out": True}
        )
        assert scene_with_save_dir._agent_settings_opted_out is True
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None

    @pytest.mark.asyncio
    async def test_explicit_file_loads(self, scene_with_save_dir: Scene):
        _write_overlay(
            scene_with_save_dir,
            "strict.json",
            contents=json.dumps(
                {
                    "agents": {
                        "resolver-test": {"actions": {"container": {"enabled": False}}}
                    }
                }
            ),
        )
        await resolve_link_on_load(
            scene_with_save_dir, {"agent_settings_file": "strict.json"}
        )
        assert scene_with_save_dir.agent_settings_file == "strict.json"
        assert (
            scene_with_save_dir.agent_overrides.get_enabled(
                "resolver-test", "container"
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_missing_explicit_file_clears_reference(
        self, scene_with_save_dir: Scene
    ):
        await resolve_link_on_load(
            scene_with_save_dir, {"agent_settings_file": "vanished.json"}
        )
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None

    @pytest.mark.asyncio
    async def test_malformed_explicit_file_clears_reference(
        self, scene_with_save_dir: Scene
    ):
        _write_overlay(scene_with_save_dir, "broken.json", contents="{not json")
        # _safe_init_overlay should catch the load error, log it, and clear
        # the link so the scene falls back to global config rather than
        # presenting a half-initialized overlay.
        await resolve_link_on_load(
            scene_with_save_dir, {"agent_settings_file": "broken.json"}
        )
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None

    @pytest.mark.asyncio
    async def test_schema_mismatch_explicit_file_clears_reference(
        self, scene_with_save_dir: Scene
    ):
        # Well-formed JSON but the schema is wrong (agents must be a dict
        # of AgentOverride; passing a string triggers pydantic.ValidationError).
        _write_overlay(
            scene_with_save_dir,
            "schema-bad.json",
            contents=json.dumps({"agents": {"resolver-test": "not-an-override"}}),
        )
        await resolve_link_on_load(
            scene_with_save_dir, {"agent_settings_file": "schema-bad.json"}
        )
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None

    @pytest.mark.asyncio
    async def test_auto_link_picks_up_default(self, scene_with_save_dir: Scene):
        _write_overlay(scene_with_save_dir, DEFAULT_SETTINGS_FILENAME)
        await resolve_link_on_load(scene_with_save_dir, {})
        assert scene_with_save_dir.agent_settings_file == DEFAULT_SETTINGS_FILENAME
        assert scene_with_save_dir.agent_overrides is not None

    @pytest.mark.asyncio
    async def test_auto_link_no_default_leaves_scene_blank(
        self, scene_with_save_dir: Scene
    ):
        await resolve_link_on_load(scene_with_save_dir, {})
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None


class TestApplySceneSettingsLink:
    @pytest.mark.asyncio
    async def test_filename_none_opts_out(self, scene_with_save_dir: Scene):
        await apply_scene_settings_link(scene_with_save_dir, filename=None)
        assert scene_with_save_dir._agent_settings_opted_out is True
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None

    @pytest.mark.asyncio
    async def test_unsafe_filename_raises(self, scene_with_save_dir: Scene):
        with pytest.raises(ValueError):
            await apply_scene_settings_link(
                scene_with_save_dir, filename="../escape.json"
            )

    @pytest.mark.asyncio
    async def test_missing_filename_raises(self, scene_with_save_dir: Scene):
        with pytest.raises(ValueError):
            await apply_scene_settings_link(
                scene_with_save_dir, filename="does-not-exist.json"
            )

    @pytest.mark.asyncio
    async def test_malformed_file_raises_and_clears(self, scene_with_save_dir: Scene):
        _write_overlay(scene_with_save_dir, "bad.json", contents="{not json")
        with pytest.raises(ValueError):
            await apply_scene_settings_link(scene_with_save_dir, filename="bad.json")
        # Failed init must leave the scene with no overlay so the resolver
        # falls back to global config.
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None

    @pytest.mark.asyncio
    async def test_valid_filename_links_and_clears_opt_out(
        self, scene_with_save_dir: Scene
    ):
        _write_overlay(scene_with_save_dir, "strict.json")
        scene_with_save_dir._agent_settings_opted_out = True
        await apply_scene_settings_link(scene_with_save_dir, filename="strict.json")
        assert scene_with_save_dir._agent_settings_opted_out is False
        assert scene_with_save_dir.agent_settings_file == "strict.json"
        assert scene_with_save_dir.agent_overrides is not None

    @pytest.mark.asyncio
    async def test_opted_out_clear_relinks_default_when_present(
        self, scene_with_save_dir: Scene
    ):
        _write_overlay(scene_with_save_dir, DEFAULT_SETTINGS_FILENAME)
        scene_with_save_dir._agent_settings_opted_out = True
        await apply_scene_settings_link(scene_with_save_dir, opted_out_clear=True)
        assert scene_with_save_dir._agent_settings_opted_out is False
        assert scene_with_save_dir.agent_settings_file == DEFAULT_SETTINGS_FILENAME

    @pytest.mark.asyncio
    async def test_opted_out_clear_no_default_leaves_scene_blank(
        self, scene_with_save_dir: Scene
    ):
        await apply_scene_settings_link(scene_with_save_dir, opted_out_clear=True)
        assert scene_with_save_dir._agent_settings_opted_out is False
        assert scene_with_save_dir.agent_settings_file is None
        assert scene_with_save_dir.agent_overrides is None
