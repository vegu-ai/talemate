"""
Tests for volatile_context_placement() — the function that determines
whether volatile content (RAG, internal notes) goes before or after
the scene history in prompts.

Tests the priority chain:
  1. Per-agent override ("on"/"off") takes precedence
  2. "auto" defers to client.optimize_prompt_caching
  3. No agent context → "before_history"
"""

import pytest
from unittest.mock import Mock

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    optimize_prompt_caching_action,
)
from talemate.agents.context import ActiveAgentContext, active_agent
from talemate.prompts.base import Prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(agent_type: str, override_value: str = "auto", client_opc: bool = False):
    """Build a minimal mock agent with an optimize_prompt_caching config."""
    agent = Mock()
    agent.agent_type = agent_type
    action = optimize_prompt_caching_action()
    action.config["optimize_prompt_caching"].value = override_value
    agent.actions = {
        "prompt_caching": action,
    }
    # Client
    agent.client = Mock()
    agent.client.optimize_prompt_caching = client_opc
    return agent


def _make_agent_no_config(agent_type: str, client_opc: bool = False):
    """Build a mock agent that has NO optimize_prompt_caching config at all."""
    agent = Mock()
    agent.agent_type = agent_type
    agent.actions = {
        "some_action": AgentAction(
            enabled=True,
            label="Some Action",
            config={
                "other_setting": AgentActionConfig(
                    type="bool",
                    label="Other",
                    value=True,
                ),
            },
        ),
    }
    agent.client = Mock()
    agent.client.optimize_prompt_caching = client_opc
    return agent


def _set_active_agent(agent):
    """Set the active agent context and return the token for cleanup."""
    ctx = ActiveAgentContext(agent=agent, fn=lambda: None)
    return active_agent.set(ctx)


def _call_volatile_context_placement():
    """Invoke volatile_context_placement via a Prompt instance."""
    prompt = Prompt.get("conversation.dialogue-movie_script", vars={})
    return prompt.volatile_context_placement()


# ---------------------------------------------------------------------------
# Tests: no agent context
# ---------------------------------------------------------------------------

class TestNoAgentContext:
    def test_returns_before_history_when_no_active_agent(self):
        """With no active agent, default to before_history."""
        # Ensure no agent is set
        token = active_agent.set(None)
        try:
            result = _call_volatile_context_placement()
            assert result == "before_history"
        finally:
            active_agent.reset(token)


# ---------------------------------------------------------------------------
# Tests: agent override = "on"
# ---------------------------------------------------------------------------

class TestAgentOverrideOn:
    def test_returns_after_history_regardless_of_client(self):
        """Agent override 'on' → after_history, even if client is False."""
        agent = _make_agent("conversation", override_value="on", client_opc=False)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "after_history"
        finally:
            active_agent.reset(token)

    def test_returns_after_history_with_client_also_true(self):
        """Agent override 'on' + client True → after_history."""
        agent = _make_agent("narrator", override_value="on", client_opc=True)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "after_history"
        finally:
            active_agent.reset(token)


# ---------------------------------------------------------------------------
# Tests: agent override = "off"
# ---------------------------------------------------------------------------

class TestAgentOverrideOff:
    def test_returns_before_history_regardless_of_client(self):
        """Agent override 'off' → before_history, even if client is True."""
        agent = _make_agent("director", override_value="off", client_opc=True)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "before_history"
        finally:
            active_agent.reset(token)

    def test_returns_before_history_with_client_also_false(self):
        """Agent override 'off' + client False → before_history."""
        agent = _make_agent("editor", override_value="off", client_opc=False)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "before_history"
        finally:
            active_agent.reset(token)


# ---------------------------------------------------------------------------
# Tests: agent override = "auto" (defer to client)
# ---------------------------------------------------------------------------

class TestAgentOverrideAuto:
    def test_auto_with_client_true(self):
        """Agent 'auto' + client optimize_prompt_caching=True → after_history."""
        agent = _make_agent("conversation", override_value="auto", client_opc=True)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "after_history"
        finally:
            active_agent.reset(token)

    def test_auto_with_client_false(self):
        """Agent 'auto' + client optimize_prompt_caching=False → before_history."""
        agent = _make_agent("summarizer", override_value="auto", client_opc=False)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "before_history"
        finally:
            active_agent.reset(token)


# ---------------------------------------------------------------------------
# Tests: agent with no optimize_prompt_caching config (fallback to client)
# ---------------------------------------------------------------------------

class TestAgentWithoutConfig:
    def test_no_config_client_true(self):
        """Agent has no optimize_prompt_caching config + client True → after_history."""
        agent = _make_agent_no_config("conversation", client_opc=True)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "after_history"
        finally:
            active_agent.reset(token)

    def test_no_config_client_false(self):
        """Agent has no optimize_prompt_caching config + client False → before_history."""
        agent = _make_agent_no_config("narrator", client_opc=False)
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "before_history"
        finally:
            active_agent.reset(token)


# ---------------------------------------------------------------------------
# Tests: agent with no client
# ---------------------------------------------------------------------------

class TestAgentWithNoClient:
    def test_auto_no_client(self):
        """Agent override 'auto' with client=None → before_history."""
        agent = _make_agent("creator", override_value="auto", client_opc=False)
        agent.client = None
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "before_history"
        finally:
            active_agent.reset(token)

    def test_on_no_client(self):
        """Agent override 'on' with client=None → after_history (override wins)."""
        agent = _make_agent("creator", override_value="on", client_opc=False)
        agent.client = None
        token = _set_active_agent(agent)
        try:
            assert _call_volatile_context_placement() == "after_history"
        finally:
            active_agent.reset(token)


# ---------------------------------------------------------------------------
# Tests: optimize_prompt_caching_config factory
# ---------------------------------------------------------------------------

class TestOptimizePromptCachingAction:
    def test_factory_returns_agent_action(self):
        action = optimize_prompt_caching_action()
        assert isinstance(action, AgentAction)

    def test_factory_has_config_with_correct_key(self):
        action = optimize_prompt_caching_action()
        assert "optimize_prompt_caching" in action.config
        assert isinstance(action.config["optimize_prompt_caching"], AgentActionConfig)

    def test_factory_default_value_is_auto(self):
        action = optimize_prompt_caching_action()
        assert action.config["optimize_prompt_caching"].value == "auto"

    def test_factory_has_three_choices(self):
        action = optimize_prompt_caching_action()
        config = action.config["optimize_prompt_caching"]
        assert len(config.choices) == 3
        values = [c["value"] for c in config.choices]
        assert values == ["auto", "on", "off"]

    def test_factory_returns_independent_instances(self):
        """Each call should return a new instance, not a shared reference."""
        a = optimize_prompt_caching_action()
        b = optimize_prompt_caching_action()
        a.config["optimize_prompt_caching"].value = "on"
        assert b.config["optimize_prompt_caching"].value == "auto"


# ---------------------------------------------------------------------------
# Tests: all 6 agents have the config
# ---------------------------------------------------------------------------

class TestAllAgentsHaveConfig:
    """Verify that every agent has the prompt_caching action with
    optimize_prompt_caching config."""

    @pytest.mark.parametrize("agent_cls_path", [
        "talemate.agents.conversation.ConversationAgent",
        "talemate.agents.narrator.NarratorAgent",
        "talemate.agents.director.DirectorAgent",
        "talemate.agents.creator.CreatorAgent",
        "talemate.agents.editor.EditorAgent",
        "talemate.agents.summarize.SummarizeAgent",
        "talemate.agents.world_state.WorldStateAgent",
    ])
    def test_agent_has_optimize_prompt_caching(self, agent_cls_path):
        import importlib
        module_path, class_name = agent_cls_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        actions = cls.init_actions()
        assert "prompt_caching" in actions, f"{class_name} missing 'prompt_caching' action"
        action = actions["prompt_caching"]
        assert isinstance(action, AgentAction)
        assert action.config is not None, f"{class_name}.prompt_caching has no config"
        assert "optimize_prompt_caching" in action.config, (
            f"{class_name}.prompt_caching missing 'optimize_prompt_caching' config"
        )
        opc = action.config["optimize_prompt_caching"]
        assert opc.value == "auto"
        assert opc.type == "text"
