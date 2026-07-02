"""
Unit tests for `talemate.agents.base` — Agent, AgentAction, AgentActionConfig,
AgentEmission, set_processing decorator, and dynamic-children helpers.

Tests use real Agent subclasses (not MagicMock), exercising the public
contract of the base class.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import pytest

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentDetail,
    AgentEmission,
    AgentTemplateEmission,
    DYNAMIC_CHILDREN_FIELD,
    DynamicInstruction,
    args_and_kwargs_to_dict,
    background_processing,
    optimize_prompt_caching_action,
    set_processing,
    store_context_state,
)
from talemate.agents.context import active_agent


# ---------------------------------------------------------------------------
# Test agent subclass
# ---------------------------------------------------------------------------


class _MinimalAgent(Agent):
    """Minimal real Agent subclass for testing base behavior."""

    agent_type = "minimal-test"
    verbose_name = "Minimal Test"
    requires_llm_client = False

    def __init__(self, actions: Optional[dict] = None):
        self.actions = actions or {}
        self.scene = None
        self.processing = 0


class _ToggleableAgent(Agent):
    agent_type = "toggle-test"
    verbose_name = "Toggle Test"
    requires_llm_client = False

    def __init__(self):
        self.actions = {
            "main": AgentAction(
                enabled=True,
                label="Main",
                config={
                    "field": AgentActionConfig(
                        type="text", label="field", value="orig"
                    ),
                    "scene_field": AgentActionConfig(
                        type="number",
                        label="scene field",
                        value=42,
                        scope="scene",
                        default_value=10,
                    ),
                    "scene_no_default": AgentActionConfig(
                        type="text",
                        label="scene field no default",
                        value="hello",
                        scope="scene",
                    ),
                },
            )
        }
        self.is_enabled = True
        self.processing = 0

    @property
    def has_toggle(self):
        return True

    @property
    def enabled(self):
        return self.is_enabled


# ---------------------------------------------------------------------------
# AgentActionConfig validation
# ---------------------------------------------------------------------------


class TestAgentActionConfigNoteValidation:
    def test_string_note_is_converted_to_object(self):
        cfg = AgentActionConfig(type="text", label="x", note="hello")
        assert cfg.note is not None
        assert cfg.note.text == "hello"

    def test_existing_agent_action_note_passes_through(self):
        from talemate.agents.base import AgentActionNote

        note = AgentActionNote(text="explicit")
        cfg = AgentActionConfig(type="text", label="x", note=note)
        assert cfg.note is not None
        assert cfg.note.text == "explicit"

    def test_none_note_remains_none(self):
        cfg = AgentActionConfig(type="text", label="x")
        assert cfg.note is None


class TestAgentActionConditionalModel:
    def test_simple_construction(self):
        cond = AgentActionConditional(attribute="foo", value=42)
        assert cond.attribute == "foo"
        assert cond.value == 42

    def test_list_value(self):
        cond = AgentActionConditional(attribute="x", value=[1, 2, 3])
        assert cond.value == [1, 2, 3]

    def test_default_value_is_none(self):
        cond = AgentActionConditional(attribute="x")
        assert cond.value is None


# ---------------------------------------------------------------------------
# args_and_kwargs_to_dict
# ---------------------------------------------------------------------------


class TestArgsAndKwargsToDict:
    def test_collects_positional_into_named(self):
        def fn(self, a, b, c=10):
            pass

        result = args_and_kwargs_to_dict(fn, ["self_obj", 1, 2], {})
        assert result == {"a": 1, "b": 2, "c": 10}

    def test_filter_drops_unwanted_keys(self):
        def fn(self, a, b, c):
            pass

        result = args_and_kwargs_to_dict(
            fn, ["self_obj", 1, 2, 3], {}, filter=["a", "c"]
        )
        assert result == {"a": 1, "c": 3}

    def test_kwargs_merge(self):
        def fn(self, a, b=2, c=3):
            pass

        result = args_and_kwargs_to_dict(fn, ["self_obj"], {"a": 100, "b": 200})
        assert result == {"a": 100, "b": 200, "c": 3}


# ---------------------------------------------------------------------------
# optimize_prompt_caching_action factory
# ---------------------------------------------------------------------------


class TestOptimizePromptCachingAction:
    def test_returns_fresh_action_each_call(self):
        a = optimize_prompt_caching_action()
        b = optimize_prompt_caching_action()
        assert a is not b

    def test_action_has_optimize_prompt_caching_field(self):
        a = optimize_prompt_caching_action()
        assert "optimize_prompt_caching" in a.config
        assert a.config["optimize_prompt_caching"].value == "auto"

    def test_choices_include_auto_on_off(self):
        a = optimize_prompt_caching_action()
        choice_values = [
            c["value"] for c in a.config["optimize_prompt_caching"].choices
        ]
        assert set(choice_values) == {"auto", "on", "off"}


# ---------------------------------------------------------------------------
# DynamicInstruction
# ---------------------------------------------------------------------------


class TestDynamicInstruction:
    def test_str_renders_section_block(self):
        di = DynamicInstruction(title="System", content="Hello world")
        s = str(di)
        assert "<|SECTION:System|>" in s
        assert "Hello world" in s
        assert "<|CLOSE_SECTION|>" in s

    def test_empty_content_renders_empty(self):
        di = DynamicInstruction(title="Title", content="")
        assert str(di) == ""


# ---------------------------------------------------------------------------
# AgentDetail
# ---------------------------------------------------------------------------


class TestAgentDetail:
    def test_default_color_is_grey(self):
        d = AgentDetail()
        assert d.color == "grey"
        assert d.hidden is False
        assert d.value is None

    def test_full_construction(self):
        d = AgentDetail(
            value="x", description="desc", icon="ic", color="primary", hidden=True
        )
        assert d.value == "x"
        assert d.color == "primary"


# ---------------------------------------------------------------------------
# Agent.config_options
# ---------------------------------------------------------------------------


class TestConfigOptions:
    def test_no_agent_returns_defaults(self):
        opts = _MinimalAgent.config_options()
        assert "client" in opts
        assert opts["enabled"] is True
        assert opts["actions"] == {}

    def test_with_agent_includes_actions(self):
        a = _ToggleableAgent()
        opts = type(a).config_options(agent=a)
        assert "main" in opts["actions"]
        # actions are model-dumped
        assert opts["actions"]["main"]["enabled"] is True


# ---------------------------------------------------------------------------
# Agent.ready / status / enabled
# ---------------------------------------------------------------------------


class _ClientStub:
    def __init__(self, enabled=True, current_status="idle", name="c1"):
        self.enabled = enabled
        self.current_status = current_status
        self.name = name


class TestReady:
    def test_no_client_attribute_means_not_ready(self):
        a = _MinimalAgent()
        a.requires_llm_client = True
        # No `client` attribute set
        assert a.ready is False

    def test_client_disabled_means_not_ready(self):
        a = _MinimalAgent()
        a.requires_llm_client = True
        a.client = _ClientStub(enabled=False)
        assert a.ready is False

    def test_client_in_error_means_not_ready(self):
        a = _MinimalAgent()
        a.requires_llm_client = True
        a.client = _ClientStub(current_status="error")
        assert a.ready is False

    def test_client_idle_means_ready(self):
        a = _MinimalAgent()
        a.requires_llm_client = True
        a.client = _ClientStub()
        assert a.ready is True

    def test_no_llm_required_always_ready(self):
        a = _MinimalAgent()
        a.requires_llm_client = False
        assert a.ready is True


class TestStatus:
    def test_disabled_when_not_enabled(self):
        a = _ToggleableAgent()
        a.is_enabled = False
        a.client = _ClientStub()
        assert a.status == "disabled"

    def test_uninitialized_when_not_ready(self):
        a = _MinimalAgent()
        a.requires_llm_client = True
        # No client -> uninitialized
        assert a.status == "uninitialized"

    def test_busy_when_processing(self):
        a = _MinimalAgent()
        a.processing = 1
        assert a.status == "busy"

    def test_busy_bg_when_processing_bg(self):
        a = _MinimalAgent()
        a.processing = 0
        a.processing_bg = 2
        assert a.status == "busy_bg"

    def test_idle_default(self):
        a = _MinimalAgent()
        a.processing = 0
        assert a.status == "idle"


class TestAgentDetails:
    def test_returns_client_name_when_present(self):
        a = _MinimalAgent()
        a.client = _ClientStub(name="my-llm")
        assert a.agent_details == "my-llm"

    def test_returns_none_when_no_client(self):
        a = _MinimalAgent()
        a.client = None
        assert a.agent_details is None


class TestSanitizedActionConfig:
    def test_returns_empty_when_no_actions(self):
        a = _MinimalAgent(actions=None)
        a.actions = None
        assert a.sanitized_action_config == {}

    def test_dumps_each_action(self):
        a = _ToggleableAgent()
        d = a.sanitized_action_config
        assert "main" in d
        # Dumped form is a plain dict
        assert isinstance(d["main"], dict)
        assert d["main"]["enabled"] is True


# ---------------------------------------------------------------------------
# Agent.meta
# ---------------------------------------------------------------------------


class TestMeta:
    def test_meta_includes_essential_and_current_action(self):
        a = _MinimalAgent()
        a._current_action = "doing_thing"
        m = a.meta
        assert m["essential"] is True
        assert m["current_action"] == "doing_thing"


# ---------------------------------------------------------------------------
# Agent.apply_config
# ---------------------------------------------------------------------------


class TestApplyConfig:
    @pytest.mark.asyncio
    async def test_applies_action_enabled_flag_and_value(self):
        a = _ToggleableAgent()
        await a.apply_config(
            actions={
                "main": {
                    "enabled": False,
                    "config": {"field": {"value": "new-value"}},
                }
            }
        )
        assert a.actions["main"].enabled is False
        assert a.actions["main"].config["field"].value == "new-value"

    @pytest.mark.asyncio
    async def test_value_migration_applied(self):
        a = _ToggleableAgent()
        a.actions["main"].config["field"].value_migration = lambda v: f"migrated:{v}"
        await a.apply_config(
            actions={
                "main": {
                    "enabled": True,
                    "config": {"field": {"value": "input"}},
                }
            }
        )
        assert a.actions["main"].config["field"].value == "migrated:input"

    @pytest.mark.asyncio
    async def test_toggle_enabled_via_kwargs(self):
        a = _ToggleableAgent()
        await a.apply_config(enabled=False)
        assert a.is_enabled is False

    @pytest.mark.asyncio
    async def test_no_actions_kwarg_keeps_state(self):
        a = _ToggleableAgent()
        original = a.actions["main"].config["field"].value
        await a.apply_config()
        assert a.actions["main"].config["field"].value == original


# ---------------------------------------------------------------------------
# Agent.on_game_loop_start (resets scene-scoped configs)
# ---------------------------------------------------------------------------


class TestOnGameLoopStart:
    @pytest.mark.asyncio
    async def test_resets_scene_scoped_to_default_value(self):
        a = _ToggleableAgent()
        # change the value before reset
        a.actions["main"].config["scene_field"].value = 999
        await a.on_game_loop_start(event=None)
        assert a.actions["main"].config["scene_field"].value == 10  # default_value

    @pytest.mark.asyncio
    async def test_resets_scene_scoped_no_default_to_type_zero(self):
        a = _ToggleableAgent()
        a.actions["main"].config["scene_no_default"].value = "altered"
        await a.on_game_loop_start(event=None)
        # default_value None -> type(value)() -> "" for str
        assert a.actions["main"].config["scene_no_default"].value == ""

    @pytest.mark.asyncio
    async def test_does_not_reset_global_scoped(self):
        a = _ToggleableAgent()
        a.actions["main"].config["field"].value = "kept"
        await a.on_game_loop_start(event=None)
        assert a.actions["main"].config["field"].value == "kept"

    @pytest.mark.asyncio
    async def test_no_actions_is_noop(self):
        a = _MinimalAgent(actions={})
        # Override actions to empty (falsy) so the early return triggers
        a.actions = None
        await a.on_game_loop_start(event=None)


# ---------------------------------------------------------------------------
# Dynamic registry helpers
# ---------------------------------------------------------------------------


def _make_dynamic_agent_class():
    """Build a real Agent subclass with one dynamic registry."""

    class _DynAgent(Agent):
        agent_type = "dynamic-test-base"
        requires_llm_client = False

        def __init__(self):
            self.actions = {
                "registry": AgentAction(
                    enabled=True,
                    label="Registry",
                    config={
                        DYNAMIC_CHILDREN_FIELD: AgentActionConfig(
                            type="blob",
                            label="children",
                            value="[]",
                        )
                    },
                ),
                "static": AgentAction(
                    enabled=True,
                    label="static",
                    config={
                        "v": AgentActionConfig(type="text", label="v", value=""),
                    },
                ),
            }
            self.added: list[tuple[str, str]] = []
            self.removed: list[str] = []
            self.renamed: list[tuple[str, str]] = []

        def dynamic_action_factory(self, registry_key, slug, label):
            return AgentAction(
                enabled=True,
                label=label,
                config={
                    "child_v": AgentActionConfig(type="text", label="v", value=""),
                },
            )

        def on_dynamic_child_added(self, registry_key, slug, label):
            self.added.append((slug, label))

        def on_dynamic_child_removed(self, registry_key, slug):
            self.removed.append(slug)

        def on_dynamic_child_renamed(self, registry_key, slug, label):
            self.renamed.append((slug, label))

    return _DynAgent


class TestIsDynamicRegistry:
    def test_registry_action_is_detected(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.is_dynamic_registry("registry") is True

    def test_static_action_is_not_a_registry(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.is_dynamic_registry("static") is False

    def test_unknown_key_is_not_a_registry(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.is_dynamic_registry("nonexistent") is False


class TestDynamicChildrenEntries:
    def test_invalid_json_returns_empty(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.actions["registry"].config[DYNAMIC_CHILDREN_FIELD].value = "{not json"
        assert a.dynamic_children_entries("registry") == []

    def test_filters_entries_without_slug(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.actions["registry"].config[DYNAMIC_CHILDREN_FIELD].value = json.dumps(
            [
                {"slug": "good", "label": "Good"},
                {"label": "Bad - missing slug"},
                "not-a-dict",
            ]
        )
        entries = a.dynamic_children_entries("registry")
        assert entries == [{"slug": "good", "label": "Good"}]

    def test_dynamic_child_slugs(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.actions["registry"].config[DYNAMIC_CHILDREN_FIELD].value = json.dumps(
            [{"slug": "a", "label": "A"}, {"slug": "b", "label": "B"}]
        )
        assert a.dynamic_child_slugs("registry") == ["a", "b"]

    def test_non_registry_returns_empty(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.dynamic_children_entries("static") == []


class TestRegisterAndUnregisterDynamicChild:
    def test_register_creates_child_action_and_fires_hook(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.register_dynamic_child("registry", "child1", "Child 1")
        assert "child1" in a.actions
        # parent_key must be set for frontend grouping
        assert a.actions["child1"].parent_key == "registry"
        assert a.added == [("child1", "Child 1")]

    def test_register_blank_slug_raises(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        with pytest.raises(ValueError):
            a.register_dynamic_child("registry", "", "Label")

    def test_register_duplicate_slug_raises(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.register_dynamic_child("registry", "x", "X")
        with pytest.raises(ValueError):
            a.register_dynamic_child("registry", "x", "X")

    def test_register_to_non_registry_raises(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        with pytest.raises(ValueError):
            a.register_dynamic_child("static", "x", "x")

    def test_register_reserved_slug_raises(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        # Override reserved_slugs_for_registry to forbid "reserved"
        a.reserved_slugs_for_registry = lambda key: {"reserved"}
        with pytest.raises(ValueError):
            a.register_dynamic_child("registry", "reserved", "x")

    def test_unregister_removes_child_and_fires_hook(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.register_dynamic_child("registry", "child1", "Child 1")
        a.unregister_dynamic_child("registry", "child1")
        assert "child1" not in a.actions
        assert a.removed == ["child1"]

    def test_unregister_unknown_slug_is_noop(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        # Should not raise
        a.unregister_dynamic_child("registry", "no-such-slug")
        assert a.removed == []

    def test_unregister_non_registry_raises(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        with pytest.raises(ValueError):
            a.unregister_dynamic_child("static", "x")


class TestRenameDynamicChildLabel:
    def test_renames_label_and_fires_hook(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.register_dynamic_child("registry", "child1", "Old")
        a.rename_dynamic_child_label("registry", "child1", "New")
        # action label was updated
        assert a.actions["child1"].label == "New"
        # blob entry label updated
        entries = a.dynamic_children_entries("registry")
        assert entries[0]["label"] == "New"
        assert a.renamed == [("child1", "New")]

    def test_rename_unknown_slug_does_not_invoke_hook(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.rename_dynamic_child_label("registry", "missing", "Label")
        assert a.renamed == []

    def test_rename_blank_label_falls_back_to_slug(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.register_dynamic_child("registry", "child1", "OrigLabel")
        a.rename_dynamic_child_label("registry", "child1", "")
        assert a.actions["child1"].label == "child1"

    def test_rename_non_registry_raises(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        with pytest.raises(ValueError):
            a.rename_dynamic_child_label("static", "x", "y")


class TestInstallDynamicChildren:
    def test_purges_stale_entries(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        # Manually inject an action with parent_key but no matching slug
        from talemate.agents.base import AgentAction as _AA
        from talemate.agents.base import AgentActionConfig as _AC

        a.actions["stale"] = _AA(
            label="Stale",
            parent_key="registry",
            config={"v": _AC(type="text", label="v", value="")},
        )
        # The blob is empty so install should drop "stale"
        a.install_dynamic_children("registry")
        assert "stale" not in a.actions

    def test_idempotent_does_not_overwrite_existing(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.register_dynamic_child("registry", "child1", "C1")
        # Mutate child config — install_dynamic_children should not overwrite
        a.actions["child1"].config["child_v"].value = "kept"
        a.install_dynamic_children("registry")
        assert a.actions["child1"].config["child_v"].value == "kept"

    def test_non_registry_is_noop(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a.install_dynamic_children("static")  # must not raise


class TestDynamicAttrAndMethod:
    def test_dynamic_attr_returns_default_when_helper_absent(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.dynamic_attr("registry", "x", "label", default="dflt") == "dflt"

    def test_dynamic_attr_resolves_helper(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        a._registry_label = lambda slug: f"label-of-{slug}"
        assert a.dynamic_attr("registry", "x", "label") == "label-of-x"

    def test_dynamic_method_returns_default_when_missing(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.dynamic_method("registry", "x", "do", default=None) is None

    def test_dynamic_method_returns_partial(self):
        cls = _make_dynamic_agent_class()
        a = cls()

        def helper(slug, n):
            return f"{slug}:{n}"

        a._registry_do = helper
        partial = a.dynamic_method("registry", "x", "do")
        assert partial(5) == "x:5"


class TestDynamicActionFactoryDefault:
    def test_base_class_raises_not_implemented(self):
        a = _MinimalAgent()
        with pytest.raises(NotImplementedError):
            a.dynamic_action_factory("registry", "slug", "label")


# ---------------------------------------------------------------------------
# Agent.dynamic_registry_keys + reserved_slugs_for_registry
# ---------------------------------------------------------------------------


class TestDynamicRegistryKeys:
    def test_returns_list_of_registry_keys(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.dynamic_registry_keys() == ["registry"]

    def test_no_actions_returns_empty(self):
        a = _MinimalAgent(actions={})
        a.actions = None
        assert a.dynamic_registry_keys() == []

    def test_default_reserved_slugs_is_empty(self):
        cls = _make_dynamic_agent_class()
        a = cls()
        assert a.reserved_slugs_for_registry("registry") == set()


# ---------------------------------------------------------------------------
# Agent.set_processing decorator
# ---------------------------------------------------------------------------


class TestSetProcessingDecorator:
    @pytest.mark.asyncio
    async def test_runs_function_and_returns_value(self):
        a = _MinimalAgent()
        a.processing = 0

        @set_processing
        async def my_action(self_):
            return "result"

        # Bind manually
        result = await my_action(a)
        assert result == "result"
        assert a._current_action is None  # reset on exit

    @pytest.mark.asyncio
    async def test_active_agent_set_during_execution(self):
        a = _MinimalAgent()
        a.processing = 0
        seen = {}

        @set_processing
        async def my_action(self_):
            seen["agent"] = active_agent.get().agent
            seen["fn_name"] = active_agent.get().action

        await my_action(a)
        assert seen["agent"] is a
        assert seen["fn_name"] == "my_action"

    @pytest.mark.asyncio
    async def test_background_flag_suppresses_foreground_processing(self):
        """Under the background flag, a @set_processing action must not bump the
        foreground `processing` counter (so status stays out of "busy"), while
        still running normally."""
        a = _MinimalAgent()
        a.processing = 0
        seen = {}

        @set_processing
        async def my_action(self_):
            seen["processing"] = self_.processing
            return "ok"

        # Normal: foreground processing is incremented during execution.
        assert await my_action(a) == "ok"
        assert seen["processing"] == 1
        assert a.processing == 0  # reset on exit

        # Background: foreground processing is left untouched.
        seen.clear()
        token = background_processing.set(True)
        try:
            assert await my_action(a) == "ok"
        finally:
            background_processing.reset(token)
        assert seen["processing"] == 0
        assert a.processing == 0

    @pytest.mark.asyncio
    async def test_store_context_state_writes_args(self):
        a = _MinimalAgent()
        a.processing = 0

        @set_processing
        @store_context_state("x", "y")
        async def my_action(self_, x, y, z=10):
            return active_agent.get().state

        state = await my_action(a, 1, 2, z=99)
        # Expects keys prefixed by agent_type__
        prefix = f"{a.agent_type}__"
        assert state[f"{prefix}x"] == 1
        assert state[f"{prefix}y"] == 2
        # `z` not in store_context_state filter list -> not added
        assert f"{prefix}z" not in state

    @pytest.mark.asyncio
    async def test_store_context_state_extra_kwargs_added(self):
        a = _MinimalAgent()
        a.processing = 0

        @set_processing
        @store_context_state("x", extra_marker="here")
        async def my_action(self_, x):
            return active_agent.get().state

        state = await my_action(a, 5)
        prefix = f"{a.agent_type}__"
        assert state[f"{prefix}x"] == 5
        assert state[f"{prefix}extra_marker"] == "here"


# ---------------------------------------------------------------------------
# Agent context state helpers
# ---------------------------------------------------------------------------


class TestContextStateHelpers:
    @pytest.mark.asyncio
    async def test_set_and_get_context_state_within_active_agent(self):
        a = _MinimalAgent()
        a.processing = 0

        @set_processing
        async def action(self_):
            self_.set_context_states(foo="bar")
            return self_.get_context_state("foo")

        result = await action(a)
        assert result == "bar"

    @pytest.mark.asyncio
    async def test_get_context_state_default_when_outside_active(self):
        a = _MinimalAgent()
        # No active_agent context, use default
        assert a.get_context_state("missing", default="def") == "def"

    @pytest.mark.asyncio
    async def test_dump_context_state_outside_active_returns_empty(self):
        a = _MinimalAgent()
        assert a.dump_context_state() == {}


class TestSceneStateHelpers:
    def test_set_and_get_scene_state(self):
        a = _MinimalAgent()

        class _SceneStub:
            agent_state = {}

        a.scene = _SceneStub()
        a.set_scene_states(foo="bar", count=2)
        assert a.get_scene_state("foo") == "bar"
        assert a.get_scene_state("count") == 2
        assert a.get_scene_state("missing", default="dflt") == "dflt"

    def test_dump_scene_state_returns_dict(self):
        a = _MinimalAgent()

        class _SceneStub:
            agent_state = {}

        a.scene = _SceneStub()
        a.set_scene_states(x=1)
        d = a.dump_scene_state()
        assert d == {"x": 1}


# ---------------------------------------------------------------------------
# Agent.clean_result
# ---------------------------------------------------------------------------


class TestCleanResult:
    def test_strips_text_after_pound(self):
        a = _MinimalAgent()
        # "before # comment" -> takes "before " and then strips partial sentences
        # "before " has no terminator -> the partial-sentence regex strips it
        result = a.clean_result("complete sentence. # comment")
        # The regex removes any non-terminated trailing chunk
        assert "comment" not in result
        assert "complete sentence." in result

    def test_strips_text_after_colon(self):
        a = _MinimalAgent()
        result = a.clean_result("Speaker: Hello there.")
        assert result == "Hello there."

    def test_removes_partial_sentence_at_end(self):
        a = _MinimalAgent()
        result = a.clean_result("First sentence. Second incomplete\n")
        # Trailing partial without terminator is stripped
        assert "First sentence." in result
        assert "incomplete" not in result


# ---------------------------------------------------------------------------
# Agent.connect (game_loop_start signal)
# ---------------------------------------------------------------------------


class TestConnect:
    def test_connect_assigns_scene(self):
        a = _MinimalAgent()

        class _SceneStub:
            pass

        scene = _SceneStub()
        a.connect(scene)
        assert a.scene is scene


# ---------------------------------------------------------------------------
# AgentEmission / AgentTemplateEmission
# ---------------------------------------------------------------------------


class TestEmissionDataclasses:
    def test_agent_emission_holds_agent(self):
        a = _MinimalAgent()
        em = AgentEmission(agent=a)
        assert em.agent is a

    def test_template_emission_defaults(self):
        a = _MinimalAgent()
        em = AgentTemplateEmission(agent=a)
        assert em.template_vars == {}
        assert em.response is None
        assert em.dynamic_instructions == []

    def test_template_emission_with_dynamic_instructions(self):
        a = _MinimalAgent()
        di = DynamicInstruction(title="t", content="c")
        em = AgentTemplateEmission(agent=a, dynamic_instructions=[di])
        assert em.dynamic_instructions == [di]


# ---------------------------------------------------------------------------
# delegate (set_processing-wrapped)
# ---------------------------------------------------------------------------


class TestDelegate:
    @pytest.mark.asyncio
    async def test_delegate_calls_passed_function(self):
        a = _MinimalAgent()
        a.processing = 0

        async def task(x, y):
            return x + y

        result = await a.delegate(task, 3, 4)
        assert result == 7


# ---------------------------------------------------------------------------
# run_tracked_task (single-flight background/foreground task helper)
# ---------------------------------------------------------------------------


class TestRunTrackedTask:
    @pytest.mark.asyncio
    async def test_background_sets_flag(self):
        a = _MinimalAgent()
        a.processing = 0
        observed = {}

        async def work():
            observed["bg"] = background_processing.get()

        task = await a.run_tracked_task("k", lambda: work(), background=True)
        assert task is not None
        await task
        assert observed["bg"] is True

    @pytest.mark.asyncio
    async def test_foreground_does_not_set_flag(self):
        a = _MinimalAgent()
        a.processing = 0
        observed = {}

        async def work():
            observed["bg"] = background_processing.get()

        task = await a.run_tracked_task("k", lambda: work(), background=False)
        await task
        assert observed["bg"] is False

    @pytest.mark.asyncio
    async def test_single_flight_skips_and_does_not_invoke_factory(self):
        a = _MinimalAgent()
        a.processing = 0
        release = asyncio.Event()
        calls = {"n": 0}

        async def work():
            calls["n"] += 1
            await release.wait()

        task = await a.run_tracked_task("k", lambda: work())
        assert task is not None
        await asyncio.sleep(0)  # let the first task start
        assert calls["n"] == 1
        # Second call while in flight is skipped; factory is never invoked.
        assert await a.run_tracked_task("k", lambda: work()) is None
        assert calls["n"] == 1

        release.set()
        await task

    @pytest.mark.asyncio
    async def test_cancel_in_flight_replaces_task(self):
        a = _MinimalAgent()
        a.processing = 0
        release = asyncio.Event()

        async def work():
            await release.wait()

        first = await a.run_tracked_task("k", lambda: work())
        second = await a.run_tracked_task("k", lambda: work(), cancel_in_flight=True)
        assert second is not None and second is not first
        with pytest.raises(asyncio.CancelledError):
            await first

        release.set()
        await second

    @pytest.mark.asyncio
    async def test_cancel_tracked_task(self):
        a = _MinimalAgent()
        a.processing = 0
        release = asyncio.Event()

        async def work():
            await release.wait()

        task = await a.run_tracked_task("k", lambda: work())
        assert a.tracked_task_running("k") is True

        assert a.cancel_tracked_task("k") is True
        with pytest.raises(asyncio.CancelledError):
            await task

        # Nothing in flight now.
        assert a.cancel_tracked_task("k") is False

    @pytest.mark.asyncio
    async def test_distinct_keys_are_independent(self):
        a = _MinimalAgent()
        a.processing = 0
        release = asyncio.Event()

        async def work():
            await release.wait()

        task_a = await a.run_tracked_task("a", lambda: work())
        task_b = await a.run_tracked_task("b", lambda: work())
        assert a.tracked_task_running("a") is True
        assert a.tracked_task_running("b") is True

        release.set()
        await task_a
        await task_b

    @pytest.mark.asyncio
    async def test_completed_task_is_untracked(self):
        """A finished task is removed from the table so keys don't accumulate."""
        a = _MinimalAgent()
        a.processing = 0

        async def work():
            return

        task = await a.run_tracked_task("k", lambda: work())
        await task
        # The done-callback that drops the entry runs on a later loop turn.
        for _ in range(5):
            if a._tracked_task("k") is None:
                break
            await asyncio.sleep(0)
        assert a._tracked_task("k") is None
        assert a.tracked_task_running("k") is False

    @pytest.mark.asyncio
    async def test_foreground_error_handler_called(self):
        a = _MinimalAgent()
        a.processing = 0
        seen = {}

        async def work():
            raise ValueError("boom")

        async def handler(exc):
            seen["error"] = exc

        await a.run_tracked_task(
            "k", lambda: work(), background=False, error_handler=handler
        )
        # The task fails, its done-callback schedules the handler — give both a
        # few loop turns to run.
        for _ in range(10):
            if "error" in seen:
                break
            await asyncio.sleep(0)
        assert isinstance(seen.get("error"), ValueError)
