"""
Unit tests for `talemate.agents.world_state.WorldStateAgent`.

These tests use real Scene/Agent objects via `bootstrap_scene` and only stub
the LLM client boundary by:
  - Pre-queuing canned `send_prompt` responses on MockClient OR
  - Replacing `Prompt.request` for the targeted call when we don't want the
    template pipeline (where templates depend on heavy scene state).

The function under test is always invoked via its real public entry point.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from _world_state_helpers import (
    make_actor,
    scene,  # noqa: F401 - pytest fixture
    scene_with_memory,  # noqa: F401 - pytest fixture
)

import talemate.instance as instance_module
import talemate.agents.world_state as world_state_module
from talemate.agents.world_state import (
    SNAPSHOT_TASK,
    TimePassageEmission,
    WorldStateAgent,
    WorldStateAgentEmission,
)
from talemate.world_state import ContextPin, Reinforcement


# ---------------------------------------------------------------------------
# Init / actions / properties
# ---------------------------------------------------------------------------


class TestInitActions:
    def test_init_actions_returns_expected_keys(self):
        actions = WorldStateAgent.init_actions()
        # Core actions
        assert "prompt_caching" in actions
        assert "update_world_state" in actions
        assert "update_reinforcements" in actions
        assert "check_pin_conditions" in actions

    def test_update_world_state_action_has_initial_and_turns(self):
        actions = WorldStateAgent.init_actions()
        cfg = actions["update_world_state"].config
        assert cfg["initial"].value is True
        assert cfg["turns"].value == 10

    def test_check_pin_conditions_action_default_turns(self):
        actions = WorldStateAgent.init_actions()
        cfg = actions["check_pin_conditions"].config
        assert cfg["turns"].value == 2


class TestAgentMetadata:
    def test_agent_type(self):
        assert WorldStateAgent.agent_type == "world_state"

    def test_verbose_name(self):
        assert WorldStateAgent.verbose_name == "World State"


class TestAgentInstance:
    def test_initial_update_property_reads_action_config(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        # Default value is True
        assert agent.initial_update is True
        # Mutate config to verify the property reflects updates
        agent.actions["update_world_state"].config["initial"].value = False
        assert agent.initial_update is False

    def test_check_pin_conditions_turns_property(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        assert agent.check_pin_conditions_turns == 2
        agent.actions["check_pin_conditions"].config["turns"].value = 7
        assert agent.check_pin_conditions_turns == 7

    def test_enabled_default_true(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        assert agent.enabled is True

    def test_has_toggle(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        assert agent.has_toggle is True

    def test_experimental(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        assert agent.experimental is True

    def test_is_enabled_disable(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.is_enabled = False
        assert agent.enabled is False
        agent.is_enabled = True


# ---------------------------------------------------------------------------
# WorldStateAgentEmission / TimePassageEmission dataclasses
# ---------------------------------------------------------------------------


class TestEmissionDataclasses:
    def test_world_state_emission_basic(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        em = WorldStateAgentEmission(agent=agent)
        assert em.agent is agent

    def test_time_passage_emission_fields(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        em = TimePassageEmission(
            agent=agent,
            duration="PT1H",
            narrative="time passed",
            human_duration="1 hour later",
        )
        assert em.duration == "PT1H"
        assert em.narrative == "time passed"
        assert em.human_duration == "1 hour later"


# ---------------------------------------------------------------------------
# advance_time
# ---------------------------------------------------------------------------


class TestAdvanceTime:
    @pytest.mark.asyncio
    async def test_emits_time_passage_message(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        msg = await agent.advance_time("PT30M", narrative="thirty minutes pass")
        # Returns a TimePassageMessage with the duration we passed
        assert msg.ts == "PT30M"
        # Human duration formatted
        assert "later" in msg.message

    @pytest.mark.asyncio
    async def test_pushes_message_into_history(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        before = len(scene.history)
        await agent.advance_time("PT1H")
        assert len(scene.history) == before + 1

    @pytest.mark.asyncio
    async def test_invalid_duration_raises(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        with pytest.raises(Exception):
            await agent.advance_time("not-an-iso8601-duration")


# ---------------------------------------------------------------------------
# auto_update_reinforcments / update_world_state gating
# ---------------------------------------------------------------------------


class TestAutoUpdateReinforcements:
    @pytest.mark.asyncio
    async def test_disabled_agent_returns_immediately(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.is_enabled = False
        # Should not raise — early return before any LLM call
        await agent.auto_update_reinforcments()

    @pytest.mark.asyncio
    async def test_disabled_action_returns_immediately(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.actions["update_reinforcements"].enabled = False
        # Should not raise even with empty reinforce list
        await agent.auto_update_reinforcments()


class TestAutoCheckPinConditions:
    @pytest.mark.asyncio
    async def test_disabled_agent_skips(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.is_enabled = False
        # No-op
        await agent.auto_check_pin_conditions()

    @pytest.mark.asyncio
    async def test_disabled_action_skips(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.actions["check_pin_conditions"].enabled = False
        await agent.auto_check_pin_conditions()

    @pytest.mark.asyncio
    async def test_increments_counter_when_not_due(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        # turns=2, next_pin_check=0 -> first call increments to 1 and returns
        agent.next_pin_check = 0
        agent.actions["check_pin_conditions"].config["turns"].value = 2
        await agent.auto_check_pin_conditions()
        assert agent.next_pin_check == 1


def _enable_client_concurrency(monkeypatch, agent):
    """Make the agent's client report concurrent-inference support so the
    snapshot takes the background (non-blocking) dispatch path."""
    monkeypatch.setattr(
        type(agent.client),
        "supports_concurrent_inference",
        property(lambda self: True),
    )


class TestUpdateWorldState:
    @pytest.mark.asyncio
    async def test_disabled_agent_skips(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.is_enabled = False
        await agent.update_world_state()

    @pytest.mark.asyncio
    async def test_disabled_action_skips(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.actions["update_world_state"].enabled = False
        await agent.update_world_state()

    @pytest.mark.asyncio
    async def test_force_triggers_update_request(self, scene, monkeypatch):  # noqa: F811
        """When force=True, the gating logic is bypassed and
        scene.world_state.request_update is dispatched as a background task."""
        from talemate.world_state import WorldState

        agent = instance_module.get_agent("world_state")
        _enable_client_concurrency(monkeypatch, agent)
        called = {"flag": False}

        async def _fake_request_update(self, *args, **kwargs):
            called["flag"] = True

        # Patch on the WorldState class (pydantic models don't allow per-instance method override)
        monkeypatch.setattr(WorldState, "request_update", _fake_request_update)
        await agent.update_world_state(force=True)
        # The snapshot now runs in the background; await the task to observe it.
        task = agent._tracked_task(SNAPSHOT_TASK)
        assert task is not None
        await task
        assert called["flag"] is True

    @pytest.mark.asyncio
    async def test_single_flight_skips_while_in_flight(self, scene, monkeypatch):  # noqa: F811
        """A forced update is skipped while a prior snapshot is still running,
        and resumes once the in-flight task finishes."""
        from talemate.world_state import WorldState

        agent = instance_module.get_agent("world_state")
        _enable_client_concurrency(monkeypatch, agent)
        called = {"n": 0}

        async def _fake_request_update(self, *args, **kwargs):
            called["n"] += 1

        monkeypatch.setattr(WorldState, "request_update", _fake_request_update)

        # Simulate an in-flight snapshot that hasn't completed yet.
        release = asyncio.Event()

        async def _blocker():
            await release.wait()

        in_flight = asyncio.create_task(_blocker())
        agent._tracked_tasks = {SNAPSHOT_TASK: in_flight}

        # Forced run must skip rather than start an overlapping generation.
        await agent.update_world_state(force=True)
        assert called["n"] == 0
        assert agent._tracked_task(SNAPSHOT_TASK) is in_flight

        # Once the in-flight task completes, a forced run dispatches again.
        release.set()
        await in_flight
        await agent.update_world_state(force=True)
        assert agent._tracked_task(SNAPSHOT_TASK) is not in_flight
        await agent._tracked_task(SNAPSHOT_TASK)
        assert called["n"] == 1

    @pytest.mark.asyncio
    async def test_cancel_world_state_update(self, scene, monkeypatch):  # noqa: F811
        """cancel_world_state_update cancels the in-flight background snapshot
        and is a no-op when nothing is running."""
        from talemate.world_state import WorldState

        agent = instance_module.get_agent("world_state")
        _enable_client_concurrency(monkeypatch, agent)
        release = asyncio.Event()

        async def _fake_request_update(self, *args, **kwargs):
            await release.wait()

        monkeypatch.setattr(WorldState, "request_update", _fake_request_update)

        # Nothing in flight yet -> no-op.
        assert agent.cancel_world_state_update() is False

        # Start a background snapshot that blocks, then cancel it.
        await agent.update_world_state(force=True)
        task = agent._tracked_task(SNAPSHOT_TASK)
        assert task is not None and not task.done()

        assert agent.cancel_world_state_update() is True
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

        # Already finished -> no-op again.
        assert agent.cancel_world_state_update() is False

    @pytest.mark.asyncio
    async def test_concurrency_gate_controls_background_flag(  # noqa: F811
        self, scene, monkeypatch
    ):
        """The snapshot runs under the background-processing flag only when the
        linked client supports concurrent inference; otherwise it runs in the
        foreground. Either way the dispatch is non-blocking."""
        from talemate.world_state import WorldState
        from talemate.agents.base import background_processing

        agent = instance_module.get_agent("world_state")
        observed = {}

        async def _fake_request_update(self, *args, **kwargs):
            # asyncio.create_task copies the context, so this reflects whether
            # the snapshot was dispatched in background mode.
            observed["background"] = background_processing.get()

        monkeypatch.setattr(WorldState, "request_update", _fake_request_update)

        # No concurrency -> foreground (flag not set).
        assert agent.snapshot_runs_in_background is False
        await agent.update_world_state(force=True)
        await agent._tracked_task(SNAPSHOT_TASK)
        assert observed["background"] is False

        # Concurrency enabled -> background (flag set).
        _enable_client_concurrency(monkeypatch, agent)
        assert agent.snapshot_runs_in_background is True
        await agent.update_world_state(force=True)
        await agent._tracked_task(SNAPSHOT_TASK)
        assert observed["background"] is True

    @pytest.mark.asyncio
    async def test_increments_when_not_due(self, scene, monkeypatch):  # noqa: F811
        from talemate.world_state import WorldState

        agent = instance_module.get_agent("world_state")
        # next_update=0 with turns=5 -> increments and returns without LLM call
        agent.next_update = 0
        agent.actions["update_world_state"].config["turns"].value = 5

        called = {"flag": False}

        async def _fake_request_update(self, *args, **kwargs):
            called["flag"] = True

        monkeypatch.setattr(WorldState, "request_update", _fake_request_update)
        await agent.update_world_state()
        assert agent.next_update == 1
        assert called["flag"] is False


# ---------------------------------------------------------------------------
# request_world_state — empty short-circuit
# ---------------------------------------------------------------------------


class TestRequestWorldState:
    @pytest.mark.asyncio
    async def test_empty_scene_returns_none(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        # Empty: no characters, no intro, no history
        scene.intro = ""
        scene.history = []
        # active_characters is empty by default
        response = await agent.request_world_state()
        assert response.world_state is None
        assert response.anchor_message_ids == []


# ---------------------------------------------------------------------------
# _parse_character_sheet
# ---------------------------------------------------------------------------


class TestParseCharacterSheet:
    def _agent(self, scene):
        return instance_module.get_agent("world_state")

    def test_basic_parsing(self, scene):  # noqa: F811
        agent = self._agent(scene)
        result = agent._parse_character_sheet("Name: Alice\nAge: 30\nMood: curious\n")
        assert result == {"Name": "Alice", "Age": "30", "Mood": "curious"}

    def test_empty_lines_skipped(self, scene):  # noqa: F811
        agent = self._agent(scene)
        result = agent._parse_character_sheet("Name: Alice\n\nAge: 30\n")
        assert result == {"Name": "Alice", "Age": "30"}

    def test_breaks_on_non_colon_line(self, scene):  # noqa: F811
        agent = self._agent(scene)
        result = agent._parse_character_sheet(
            "Name: Alice\nthis line has no colon and stops parsing\nAge: 30\n"
        )
        # Stops after Alice
        assert result == {"Name": "Alice"}

    def test_max_attributes_caps_count(self, scene):  # noqa: F811
        agent = self._agent(scene)
        text = "A: 1\nB: 2\nC: 3\nD: 4\n"
        result = agent._parse_character_sheet(text, max_attributes=2)
        assert len(result) == 2
        # First two keys preserved
        assert "A" in result and "B" in result

    def test_zero_max_attributes_treated_as_no_limit(self, scene):  # noqa: F811
        agent = self._agent(scene)
        result = agent._parse_character_sheet("A: 1\nB: 2\n", max_attributes=0)
        # 0 should not impose a limit
        assert result == {"A": "1", "B": "2"}

    def test_handles_value_with_colons(self, scene):  # noqa: F811
        agent = self._agent(scene)
        # split with maxsplit=1 keeps the rest of the value intact
        result = agent._parse_character_sheet("URL: http://example.com\n")
        assert result == {"URL": "http://example.com"}


# ---------------------------------------------------------------------------
# answer_query_true_or_false
# ---------------------------------------------------------------------------


class TestAnswerQueryTrueOrFalse:
    @pytest.mark.asyncio
    async def test_yes_response_returns_true(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")

        async def _fake(text, query, response_length=512):
            return "yes, definitely"

        monkeypatch.setattr(agent, "analyze_text_and_answer_question", _fake)
        result = await agent.answer_query_true_or_false("Is X?", "context")
        assert result is True

    @pytest.mark.asyncio
    async def test_no_response_returns_false(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")

        async def _fake(text, query, response_length=512):
            return "no, not at all"

        monkeypatch.setattr(agent, "analyze_text_and_answer_question", _fake)
        result = await agent.answer_query_true_or_false("Is X?", "context")
        assert result is False


# ---------------------------------------------------------------------------
# is_character_present / is_character_leaving
# ---------------------------------------------------------------------------


class TestIsCharacterPresent:
    @pytest.mark.asyncio
    async def test_yes_returns_true(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        # Stub the underlying analyze method
        monkeypatch.setattr(
            agent,
            "analyze_text_and_answer_question",
            AsyncMock(return_value="yes, present"),
        )
        # Set scene state so the function is exercised
        scene.intro = "Alice walks in"
        result = await agent.is_character_present("Alice")
        assert result is True

    @pytest.mark.asyncio
    async def test_no_returns_false(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        monkeypatch.setattr(
            agent,
            "analyze_text_and_answer_question",
            AsyncMock(return_value="no"),
        )
        scene.intro = "Empty room"
        assert await agent.is_character_present("Alice") is False


class TestIsCharacterLeaving:
    @pytest.mark.asyncio
    async def test_yes_returns_true(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        monkeypatch.setattr(
            agent,
            "analyze_text_and_answer_question",
            AsyncMock(return_value="yes"),
        )
        scene.intro = "Goodbye"
        assert await agent.is_character_leaving("Bob") is True

    @pytest.mark.asyncio
    async def test_no_returns_false(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        monkeypatch.setattr(
            agent,
            "analyze_text_and_answer_question",
            AsyncMock(return_value="absolutely not"),
        )
        scene.intro = "Stays"
        assert await agent.is_character_leaving("Bob") is False


# ---------------------------------------------------------------------------
# manager() dispatch
# ---------------------------------------------------------------------------


class TestManagerDispatch:
    @pytest.mark.asyncio
    async def test_calls_existing_world_state_manager_method(
        self,
        scene,
        monkeypatch,  # noqa: F811
    ):
        from talemate.world_state.manager import WorldStateManager

        agent = instance_module.get_agent("world_state")

        # Inject a custom method on the manager class
        async def my_method(self, *args, **kwargs):
            return ("ok", args, kwargs)

        monkeypatch.setattr(WorldStateManager, "my_method", my_method, raising=False)
        result = await agent.manager("my_method", "arg1", kw="kw1")
        assert result[0] == "ok"
        assert result[1] == ("arg1",)
        assert result[2] == {"kw": "kw1"}

    @pytest.mark.asyncio
    async def test_unknown_action_raises(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        with pytest.raises(ValueError):
            await agent.manager("does_not_exist")

    @pytest.mark.asyncio
    async def test_function_exception_propagates(self, scene, monkeypatch):  # noqa: F811
        from talemate.world_state.manager import WorldStateManager

        agent = instance_module.get_agent("world_state")

        async def boom(self, *args, **kwargs):
            raise RuntimeError("bang")

        monkeypatch.setattr(WorldStateManager, "explode", boom, raising=False)
        with pytest.raises(RuntimeError, match="bang"):
            await agent.manager("explode")


# ---------------------------------------------------------------------------
# check_pin_conditions — pin-decay logic for pins-with-no-conditions branch
# ---------------------------------------------------------------------------


class TestCheckPinConditionsDecay:
    @pytest.mark.asyncio
    async def test_no_conditions_to_check_ticks_decay(
        self,
        scene,
        monkeypatch,  # noqa: F811
    ):
        """When no pins have conditions, the early-return tick decay path
        runs. Active pins with decay should have decay_due decremented."""
        agent = instance_module.get_agent("world_state")
        ws = scene.world_state

        # Pin with NO condition (LLM check skipped) — only decay tick path runs
        ws.pins["p1"] = ContextPin(
            entry_id="p1",
            condition=None,
            active=True,
            decay=5,
            decay_due=None,  # will be initialized to decay
        )

        # Stub load_active_pins so it doesn't try to look up entries in memory
        monkeypatch.setattr(scene, "load_active_pins", AsyncMock())

        # turns=2 -> decay_due decrements by 2 per cycle
        agent.actions["check_pin_conditions"].config["turns"].value = 2
        await agent.check_pin_conditions()

        # decay_due should have been initialized to 5 then decremented by 2 -> 3
        assert ws.pins["p1"].decay_due == 3
        assert ws.pins["p1"].active is True

    @pytest.mark.asyncio
    async def test_decay_expiry_deactivates_pin(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        ws = scene.world_state
        ws.pins["p1"] = ContextPin(
            entry_id="p1",
            condition=None,
            active=True,
            decay=5,
            decay_due=2,  # below current turns -> goes negative -> deactivate
        )

        monkeypatch.setattr(scene, "load_active_pins", AsyncMock())

        agent.actions["check_pin_conditions"].config["turns"].value = 5
        await agent.check_pin_conditions()
        assert ws.pins["p1"].active is False
        assert ws.pins["p1"].decay_due is None

    @pytest.mark.asyncio
    async def test_gamestate_controlled_pin_skipped_from_decay(
        self,
        scene,
        monkeypatch,  # noqa: F811
    ):
        from talemate.game.schema import ConditionGroup

        agent = instance_module.get_agent("world_state")
        ws = scene.world_state
        # gamestate-controlled pin: decay never applies. The check is `if
        # pin.gamestate_condition:` so we need a non-empty list.
        ws.pins["gs"] = ContextPin(
            entry_id="gs",
            condition=None,
            gamestate_condition=[ConditionGroup(conditions=[], operator="and")],
            active=True,
            decay=5,
            decay_due=2,
        )

        monkeypatch.setattr(scene, "load_active_pins", AsyncMock())
        await agent.check_pin_conditions()
        # decay_due unchanged (no condition + gamestate-controlled = skipped)
        assert ws.pins["gs"].decay_due == 2
        assert ws.pins["gs"].active is True


class TestCheckPinConditionsLLMBranch:
    @pytest.mark.asyncio
    async def test_llm_yes_activates_pin(self, scene, monkeypatch):  # noqa: F811
        """When the LLM responds with state=True for a pin's condition,
        the pin should be activated (and decay_due set if decay configured)."""
        agent = instance_module.get_agent("world_state")
        ws = scene.world_state
        # Inactive pin with a condition
        ws.pins["p1"] = ContextPin(
            entry_id="p1",
            condition="Is the player alive?",
            active=False,
        )

        # Stub load_active_pins so we don't hit memory
        monkeypatch.setattr(scene, "load_active_pins", AsyncMock())

        # Stub Prompt.request to return canned answers
        async def _fake_request(uid, client, kind, vars=None, **kwargs):
            answers = {"p1": {"state": True}}
            return ("response-text", answers)

        monkeypatch.setattr(
            world_state_module.Prompt,
            "request",
            classmethod(
                lambda cls, uid, client, kind, vars=None, **kwargs: _fake_request(
                    uid, client, kind, vars=vars, **kwargs
                )
            ),
        )

        await agent.check_pin_conditions()
        assert ws.pins["p1"].active is True
        assert ws.pins["p1"].condition_state is True

    @pytest.mark.asyncio
    async def test_llm_no_deactivates_active_pin(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        ws = scene.world_state
        ws.pins["p1"] = ContextPin(
            entry_id="p1",
            condition="Q?",
            active=True,
            condition_state=True,
        )

        monkeypatch.setattr(scene, "load_active_pins", AsyncMock())

        async def _fake_request(uid, client, kind, vars=None, **kwargs):
            return ("text", {"p1": {"state": "no"}})

        monkeypatch.setattr(
            world_state_module.Prompt,
            "request",
            classmethod(
                lambda cls, uid, client, kind, vars=None, **kwargs: _fake_request(
                    uid, client, kind, vars=vars, **kwargs
                )
            ),
        )

        await agent.check_pin_conditions()
        assert ws.pins["p1"].active is False
        assert ws.pins["p1"].condition_state is False

    @pytest.mark.asyncio
    async def test_llm_unknown_pin_id_is_ignored(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        ws = scene.world_state
        ws.pins["real"] = ContextPin(
            entry_id="real",
            condition="Q?",
            active=False,
        )

        monkeypatch.setattr(scene, "load_active_pins", AsyncMock())

        async def _fake_request(uid, client, kind, vars=None, **kwargs):
            return ("text", {"unknown_id": {"state": True}, "real": {"state": False}})

        monkeypatch.setattr(
            world_state_module.Prompt,
            "request",
            classmethod(
                lambda cls, uid, client, kind, vars=None, **kwargs: _fake_request(
                    uid, client, kind, vars=vars, **kwargs
                )
            ),
        )

        await agent.check_pin_conditions()
        # Real pin still inactive
        assert ws.pins["real"].active is False
        # Unknown pin not added
        assert "unknown_id" not in ws.pins


# ---------------------------------------------------------------------------
# update_reinforcements — gating behavior with require_active
# ---------------------------------------------------------------------------


class TestUpdateReinforcementsRequireActive:
    @pytest.mark.asyncio
    async def test_skips_reinforcement_for_inactive_character(
        self,
        scene,
        monkeypatch,  # noqa: F811
    ):
        from talemate.character import Character

        agent = instance_module.get_agent("world_state")
        ws = scene.world_state

        # Create a character but DO NOT add to active list / actors. This puts
        # the character in inactive_characters (looked up via character_data).
        inactive_char = Character(name="Inactive")
        scene.character_data["Inactive"] = inactive_char

        r = Reinforcement(
            question="What is Inactive's mood?",
            character="Inactive",
            answer="curious",
            require_active=True,
            due=0,
        )
        ws.reinforce.append(r)

        called = {"flag": False}

        async def _fake_update(*args, **kwargs):
            called["flag"] = True

        monkeypatch.setattr(agent, "update_reinforcement", _fake_update)
        await agent.update_reinforcements()
        # Inactive -> update_reinforcement should NOT be called
        assert called["flag"] is False

    @pytest.mark.asyncio
    async def test_calls_update_when_active(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        # Make Alice active in the scene
        make_actor(scene, "Alice")

        ws = scene.world_state
        r = Reinforcement(
            question="What is Alice's mood?",
            character="Alice",
            answer="curious",
            require_active=True,
            due=0,
        )
        ws.reinforce.append(r)

        called = {"args": None}

        async def _fake_update(question, character, reset=False):
            called["args"] = (question, character, reset)

        monkeypatch.setattr(agent, "update_reinforcement", _fake_update)
        await agent.update_reinforcements()
        assert called["args"] == ("What is Alice's mood?", "Alice", False)

    @pytest.mark.asyncio
    async def test_decrements_due_when_not_due(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        ws = scene.world_state
        r = Reinforcement(question="q", answer="a", due=3)
        ws.reinforce.append(r)

        called = {"flag": False}

        async def _fake_update(*args, **kwargs):
            called["flag"] = True

        monkeypatch.setattr(agent, "update_reinforcement", _fake_update)
        await agent.update_reinforcements()
        assert called["flag"] is False
        assert r.due == 2

    @pytest.mark.asyncio
    async def test_force_overrides_due(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        ws = scene.world_state
        r = Reinforcement(question="q", answer="a", due=10)
        ws.reinforce.append(r)

        called = {"flag": False}

        async def _fake_update(*args, **kwargs):
            called["flag"] = True

        monkeypatch.setattr(agent, "update_reinforcement", _fake_update)
        await agent.update_reinforcements(force=True)
        assert called["flag"] is True


# ---------------------------------------------------------------------------
# update_reinforcement — missing reinforcement returns None
# ---------------------------------------------------------------------------


class TestUpdateReinforcementMissing:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_question(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        result = await agent.update_reinforcement("unknown question", None)
        assert result is None
