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
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from _world_state_helpers import (
    make_actor,
    scene,  # noqa: F401 - pytest fixture
    scene_with_memory,  # noqa: F401 - pytest fixture
)

import talemate.instance as instance_module
import talemate.agents.world_state as world_state_module
import talemate.agents.world_state.snapshot as snapshot_module
from talemate.agents.world_state import (
    SNAPSHOT_TASK,
    TimePassageEmission,
    WorldStateAgent,
    WorldStateAgentEmission,
)
from talemate.agents.world_state.snapshot import (
    SNAPSHOT_ENTITY_SELECTION_MAX,
    SnapshotEntityAddition,
    resolve_character_name,
)
from talemate.agents.world_state.websocket_handler import WorldStateWebsocketHandler
from talemate.exceptions import GenerationCancelled
from talemate.world_state.merge import has_time_passage_boundary
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    TimePassageMessage,
)
from talemate.world_state import (
    CharacterState,
    ContextPin,
    ObjectState,
    PlaceState,
    Reinforcement,
    WorldState,
    WorldStateResponse,
)


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
            duration=3600,
            narrative="time passed",
            human_duration="1 hour later",
        )
        assert em.duration == 3600
        assert em.narrative == "time passed"
        assert em.human_duration == "1 hour later"


# ---------------------------------------------------------------------------
# advance_time
# ---------------------------------------------------------------------------


class TestAdvanceTime:
    @pytest.mark.asyncio
    async def test_emits_time_passage_message(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        msg = await agent.advance_time(1800, narrative="thirty minutes pass")
        # Returns a TimePassageMessage with the duration we passed
        assert msg.ts == 1800
        # Human duration formatted
        assert "later" in msg.message

    @pytest.mark.asyncio
    async def test_pushes_message_into_history(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        before = len(scene.history)
        await agent.advance_time(3600)
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
    async def test_dispatch_forwards_instructions_through_the_chain(  # noqa: F811
        self, scene, monkeypatch
    ):
        """Instructions handed to the dispatch survive the whole chain — tracked
        task -> WorldState.request_update -> apply_snapshot_update -> the
        snapshot prompt call. Only the LLM-calling end is stubbed."""
        from talemate.world_state import WorldStateResponse

        agent = instance_module.get_agent("world_state")
        # Empty response: apply_snapshot_update returns right after the call,
        # so nothing but the threading is under test here.
        request_world_state = AsyncMock(return_value=WorldStateResponse())
        monkeypatch.setattr(agent, "request_world_state", request_world_state)

        assert await agent.dispatch_world_state_update(
            instructions="Focus on the broken door."
        )
        await agent._tracked_task(SNAPSHOT_TASK)

        assert (
            request_world_state.await_args.kwargs["instructions"]
            == "Focus on the broken door."
        )

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
# websocket handler — handle_request_update
# ---------------------------------------------------------------------------


class TestRequestUpdateWebsocketHandler:
    """The manual refresh: reset stays handler-side, instructions travel to
    the agent's dispatch."""

    def _handler(self, scene) -> WorldStateWebsocketHandler:  # noqa: F811
        ws = SimpleNamespace(scene=scene, queue_put=Mock())
        handler = WorldStateWebsocketHandler(websocket_handler=ws)
        handler.signal_operation_done = AsyncMock()
        return handler

    def _record_calls(self, monkeypatch, agent) -> tuple[list[str], AsyncMock]:
        """Record reset/dispatch in call order. reset is patched on the
        WorldState class (pydantic models don't allow per-instance overrides)."""
        from talemate.world_state import WorldState

        calls: list[str] = []
        monkeypatch.setattr(WorldState, "reset", lambda self: calls.append("reset"))
        dispatch = AsyncMock(side_effect=lambda **kwargs: calls.append("dispatch"))
        monkeypatch.setattr(agent, "dispatch_world_state_update", dispatch)
        return calls, dispatch

    @pytest.mark.asyncio
    async def test_default_payload_dispatches_without_reset(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        calls, dispatch = self._record_calls(monkeypatch, agent)

        await self._handler(scene).handle_request_update({})

        assert calls == ["dispatch"]
        assert dispatch.await_args.kwargs["cancel_in_flight"] is True
        assert dispatch.await_args.kwargs["instructions"] == ""

    @pytest.mark.asyncio
    async def test_reset_applied_before_dispatch(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        calls, _ = self._record_calls(monkeypatch, agent)

        await self._handler(scene).handle_request_update({"reset": True})

        assert calls == ["reset", "dispatch"]

    @pytest.mark.asyncio
    async def test_instructions_forwarded_to_dispatch(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        _, dispatch = self._record_calls(monkeypatch, agent)

        await self._handler(scene).handle_request_update(
            {"instructions": "Focus on the broken door."}
        )

        assert dispatch.await_args.kwargs["instructions"] == "Focus on the broken door."

    @pytest.mark.asyncio
    async def test_reset_and_instructions_together(self, scene, monkeypatch):  # noqa: F811
        """What the refresh dialog sends when the user types instructions and
        ticks reset."""
        agent = instance_module.get_agent("world_state")
        calls, dispatch = self._record_calls(monkeypatch, agent)

        await self._handler(scene).handle_request_update(
            {"reset": True, "instructions": "Rebuild from the fire onward."}
        )

        assert calls == ["reset", "dispatch"]
        assert (
            dispatch.await_args.kwargs["instructions"]
            == "Rebuild from the fire onward."
        )


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


# ---------------------------------------------------------------------------
# add_snapshot_entity — the manual add from a text selection
# ---------------------------------------------------------------------------


def _stub_entity_response(monkeypatch, entity: dict) -> AsyncMock:
    """Answer the manual-add prompt with `entity`, bypassing the template."""
    from talemate.prompts import Prompt

    request = AsyncMock(return_value=("", {"entity": entity}))
    monkeypatch.setattr(Prompt, "request", request)
    return request


def _capture_status(monkeypatch) -> list[tuple[str, str]]:
    """The (message, status) pairs the agent emits while the test runs."""
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        snapshot_module,
        "emit",
        lambda typ, message="", status="", **kwargs: messages.append((message, status)),
    )
    return messages


def _seed_message(scene, text: str) -> NarratorMessage:  # noqa: F811
    message = NarratorMessage(message=text)
    scene.history.append(message)
    return message


class TestAddSnapshotEntity:
    @pytest.mark.asyncio
    async def test_adds_a_manual_item_entry(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "dented locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )

        result = await agent.add_snapshot_entity(message.id, "dented locker")

        assert result.resolved is True
        assert result.kind == "item"
        entry = scene.world_state.items["Dented Locker"]
        assert entry.manual is True
        assert entry.snapshot == "Its door is welded shut."

    @pytest.mark.asyncio
    async def test_updates_an_existing_entry_instead_of_duplicating(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        scene.world_state.items["Dented Locker"] = ObjectState(
            snapshot="Sealed.", mentions=["the locker"]
        )
        message = _seed_message(scene, "The dented locker rattles.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Something inside is loose.",
                "mentions": ["The dented locker"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert list(scene.world_state.items) == ["Dented Locker"]
        assert scene.world_state.items["Dented Locker"].snapshot == (
            "Something inside is loose."
        )

    @pytest.mark.asyncio
    async def test_refusal_writes_nothing(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "And then she said nothing at all.")
        _stub_entity_response(monkeypatch, {"resolved": False})

        result = await agent.add_snapshot_entity(message.id, "and then she said")

        assert result.resolved is False
        assert scene.world_state.items == {}
        assert scene.world_state.characters == {}
        assert scene.world_state.places == {}

    @pytest.mark.asyncio
    async def test_unknown_kind_writes_nothing(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "concept",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
            },
        )

        result = await agent.add_snapshot_entity(message.id, "dented locker")

        assert result.resolved is False
        assert scene.world_state.items == {}

    @pytest.mark.asyncio
    async def test_mentions_keep_only_literal_phrases(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker", "the storage unit"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert scene.world_state.items["Dented Locker"].mentions == ["A dented locker"]

    @pytest.mark.asyncio
    async def test_the_selection_stands_in_when_no_model_phrase_survives(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["the storage unit"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert scene.world_state.items["Dented Locker"].mentions == ["dented locker"]

    @pytest.mark.asyncio
    async def test_a_partial_word_match_is_not_a_mention(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["lock"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert scene.world_state.items["Dented Locker"].mentions == ["dented locker"]

    @pytest.mark.asyncio
    async def test_a_character_name_prefix_is_not_a_mention(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = CharacterMessage(message="Elmer: The locker stands open.")
        scene.history.append(message)
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["Elmer", "The locker"],
            },
        )

        await agent.add_snapshot_entity(message.id, "locker")

        assert scene.world_state.items["Locker"].mentions == ["The locker"]

    @pytest.mark.asyncio
    async def test_an_updated_entry_keeps_its_earlier_mentions(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        scene.world_state.items["Dented Locker"] = ObjectState(
            snapshot="Sealed.", mentions=["the steel cabinet"]
        )
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Something inside is loose.",
                "mentions": ["A dented locker"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert scene.world_state.items["Dented Locker"].mentions == [
            "the steel cabinet",
            "A dented locker",
        ]

    @pytest.mark.asyncio
    async def test_a_bare_string_of_mentions_is_ignored(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": "A dented locker",
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert scene.world_state.items["Dented Locker"].mentions == ["dented locker"]

    @pytest.mark.asyncio
    async def test_character_name_resolves_onto_the_cast(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        make_actor(scene, "Elmer")
        message = _seed_message(scene, "Old Elmer leans on the rail.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "character",
                "name": "Old Elmer",
                "emotion": "weary",
                "snapshot": "He favors his left leg.",
                "mentions": ["Old Elmer"],
            },
        )

        await agent.add_snapshot_entity(message.id, "Old Elmer")

        assert "Elmer" in scene.world_state.characters
        assert scene.world_state.characters["Elmer"].emotion == "weary"
        assert scene.world_state.characters["Elmer"].manual is True

    @pytest.mark.asyncio
    async def test_entry_outside_the_moment_is_not_highlighted(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        """A message the current moment has moved past — the default moment is
        the last three narrative messages."""
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        for line in ("She turned away.", "The lamp guttered.", "Rain began."):
            _seed_message(scene, line)
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )

        result = await agent.add_snapshot_entity(message.id, "dented locker")

        assert result.in_moment is False
        assert result.highlighted is False
        assert "Dented Locker" in scene.world_state.items
        assert message.id not in scene.world_state.anchor_message_ids

    @pytest.mark.asyncio
    async def test_entry_in_the_moment_is_highlighted(self, scene, monkeypatch):  # noqa: F811
        """The newest message is in the moment even though the last refresh
        anchored older ones — the anchors are stale the instant a message is
        pushed, so membership comes from the live walk."""
        agent = instance_module.get_agent("world_state")
        stale = _seed_message(scene, "An older beat.")
        scene.world_state.anchor_message_ids = [stale.id]
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )

        result = await agent.add_snapshot_entity(message.id, "dented locker")

        assert result.highlighted is True
        # the client renders a highlight only on an anchored message
        assert message.id in scene.world_state.anchor_message_ids
        assert stale.id in scene.world_state.anchor_message_ids

    @pytest.mark.asyncio
    async def test_the_panel_sees_a_requested_status_and_then_an_update(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )
        statuses = []
        monkeypatch.setattr(
            WorldState,
            "emit",
            lambda self, status="update": statuses.append(status),
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert statuses[0] == "requested"
        assert statuses[-1] == "update"

    @pytest.mark.asyncio
    async def test_the_emitted_payload_carries_the_mentions_and_the_anchor(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        """The emitted world_state frame is the only source of inline
        highlights — the client rebuilds its mention list from it and renders
        a highlight only on a message the frame anchors."""
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        scene.world_state.anchor_message_ids = [message.id]
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )
        frames = []
        monkeypatch.setattr(
            WorldState,
            "emit",
            lambda self, status="update": frames.append((status, self.model_dump())),
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        status, payload = frames[-1]
        assert status == "update"
        assert payload["items"]["Dented Locker"]["mentions"] == ["A dented locker"]
        assert message.id in payload["anchor_message_ids"]

    @pytest.mark.asyncio
    async def test_a_refusal_also_lowers_the_requested_status(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "And then she said nothing at all.")
        _stub_entity_response(monkeypatch, {"resolved": False})
        statuses = []
        monkeypatch.setattr(
            WorldState,
            "emit",
            lambda self, status="update": statuses.append(status),
        )

        await agent.add_snapshot_entity(message.id, "and then she said")

        assert statuses == ["requested", "update"]

    @pytest.mark.asyncio
    async def test_a_failure_after_the_request_still_lowers_the_status(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        """Nothing else lowers it — a stuck spinner would outlive the session
        and its cancel button would have no task to cancel."""
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )
        statuses = []
        monkeypatch.setattr(
            WorldState,
            "emit",
            lambda self, status="update": statuses.append(status),
        )
        monkeypatch.setattr(
            snapshot_module,
            "literal_mentions",
            Mock(side_effect=RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError):
            await agent.add_snapshot_entity(message.id, "dented locker")

        assert statuses == ["requested", "update"]

    @pytest.mark.asyncio
    async def test_the_item_cap_is_left_to_durable_mode(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.actions["update_world_state"].config["durable_snapshot"].value = False
        agent.actions["update_world_state"].config["max_items"].value = 1
        scene.world_state.items["Older Crate"] = ObjectState(snapshot="sealed")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert set(scene.world_state.items) == {"Older Crate", "Dented Locker"}

    @pytest.mark.asyncio
    async def test_a_scene_cut_wipes_before_the_entry_lands(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        """A TimePassage since the last snapshot invalidates it, so the entry
        joins a fresh snapshot rather than the moment before the cut — and the
        anchors it leaves keep the cut visible to the next refresh."""
        agent = instance_module.get_agent("world_state")
        older = _seed_message(scene, "An older beat.")
        scene.world_state.anchor_message_ids = [older.id]
        scene.world_state.items["Older Crate"] = ObjectState(snapshot="sealed")
        scene.history.append(TimePassageMessage(ts=3600, message="an hour later"))
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert set(scene.world_state.items) == {"Dented Locker"}
        assert scene.world_state.anchor_message_ids == [message.id]

    @pytest.mark.asyncio
    async def test_an_item_name_is_matched_against_the_bucket(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        """The model is asked to reuse a tracked name but cannot be relied on
        to: a duplicate pin would survive both eviction and the cap."""
        agent = instance_module.get_agent("world_state")
        scene.world_state.items["Dented Locker"] = ObjectState(
            snapshot="Sealed.", mentions=["the locker"]
        )
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "The dented locker",
                "snapshot": "Something inside is loose.",
                "mentions": ["A dented locker"],
            },
        )

        result = await agent.add_snapshot_entity(message.id, "dented locker")

        assert list(scene.world_state.items) == ["Dented Locker"]
        assert result.name == "Dented Locker"
        assert scene.world_state.items["Dented Locker"].manual is True

    @pytest.mark.asyncio
    async def test_a_place_name_is_matched_against_the_bucket(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        scene.world_state.places["Vester Light"] = PlaceState(snapshot="A lighthouse.")
        message = _seed_message(scene, "The light stood on its rock.")
        # normalize_name only fixes the casing, so the name has to be one it
        # cannot collapse onto the tracked key on its own.
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "place",
                "name": "The Vester light",
                "snapshot": "Its lamp turns every five seconds.",
                "mentions": ["The light"],
            },
        )

        await agent.add_snapshot_entity(message.id, "the light")

        assert list(scene.world_state.places) == ["Vester Light"]

    @pytest.mark.asyncio
    async def test_a_cast_name_is_not_remapped_onto_a_background_entry(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        """The cast confirms the name, so no tracked entry that merely shares a
        word with it may take the snapshot, the emotion and the pin."""
        agent = instance_module.get_agent("world_state")
        make_actor(scene, "Emma")
        scene.world_state.characters["Emma's Mother"] = CharacterState(
            snapshot="Storming down the hall.", emotion="furious"
        )
        message = _seed_message(scene, "Emma waited by the door.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "character",
                "name": "Emma",
                "emotion": "wary",
                "snapshot": "She keeps one hand on the latch.",
                "mentions": ["Emma"],
            },
        )

        result = await agent.add_snapshot_entity(message.id, "Emma")

        assert result.name == "Emma"
        assert scene.world_state.characters["Emma"].emotion == "wary"
        assert scene.world_state.characters["Emma's Mother"].emotion == "furious"
        assert scene.world_state.characters["Emma's Mother"].manual is False

    @pytest.mark.asyncio
    async def test_a_longer_cast_name_is_not_remapped_onto_a_shorter_entry(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        make_actor(scene, "Emma")
        make_actor(scene, "Emma Watson")
        scene.world_state.characters["Emma"] = CharacterState(snapshot="Reading.")
        message = _seed_message(scene, "Emma Watson stormed down the hall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "character",
                "name": "Emma Watson",
                "emotion": "furious",
                "snapshot": "She has not put the letter down.",
                "mentions": ["Emma Watson"],
            },
        )

        result = await agent.add_snapshot_entity(message.id, "Emma Watson")

        assert result.name == "Emma Watson"
        assert scene.world_state.characters["Emma"].snapshot == "Reading."
        assert scene.world_state.characters["Emma Watson"].emotion == "furious"

    @pytest.mark.asyncio
    async def test_a_pending_scene_cut_keeps_its_watermark(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        """Adding from a message before the cut still wipes, and the anchors it
        leaves keep the cut visible to the next refresh — an empty list would
        make has_time_passage_boundary answer False and the pinned entry would
        survive into the post-cut snapshot."""
        agent = instance_module.get_agent("world_state")
        older = _seed_message(scene, "A dented locker sits against the wall.")
        scene.world_state.anchor_message_ids = [older.id]
        scene.history.append(TimePassageMessage(ts=3600, message="an hour later"))
        _seed_message(scene, "Rain began.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )

        result = await agent.add_snapshot_entity(older.id, "dented locker")

        assert result.in_moment is False
        assert scene.world_state.anchor_message_ids
        assert has_time_passage_boundary(
            scene.history, scene.world_state.anchor_message_ids
        )

    @pytest.mark.asyncio
    async def test_an_unrelated_name_starts_its_own_entry(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        scene.world_state.items["Notebook Page"] = ObjectState(snapshot="Creased.")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        _stub_entity_response(
            monkeypatch,
            {
                "resolved": True,
                "kind": "item",
                "name": "Dented Locker",
                "snapshot": "Its door is welded shut.",
                "mentions": ["A dented locker"],
            },
        )

        await agent.add_snapshot_entity(message.id, "dented locker")

        assert set(scene.world_state.items) == {"Notebook Page", "Dented Locker"}

    @pytest.mark.asyncio
    async def test_empty_selection_raises(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        with pytest.raises(ValueError):
            await agent.add_snapshot_entity(message.id, "   ")

    @pytest.mark.asyncio
    async def test_over_long_selection_raises(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        message = _seed_message(scene, "A dented locker sits against the wall.")
        with pytest.raises(ValueError):
            await agent.add_snapshot_entity(
                message.id, "x" * (SNAPSHOT_ENTITY_SELECTION_MAX + 1)
            )

    @pytest.mark.asyncio
    async def test_unknown_message_raises(self, scene):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        with pytest.raises(ValueError):
            await agent.add_snapshot_entity(123456789, "dented locker")


class TestResolveCharacterName:
    """The refresh path's name resolution. The cast is a closed, authoritative
    set, so the loose tail is what keeps one person in one row."""

    @pytest.mark.parametrize(
        "raw,cast,expected",
        [
            ("Sam", ["Samuel"], "Samuel"),
            ("Kate", ["Katelyn"], "Katelyn"),
            ("Bobby", ["Bob"], "Bob"),
            ("Guards", ["Guard"], "Guard"),
            ("Ana", ["Ana Blackwood"], "Ana Blackwood"),
            ("Elmer's", ["Elmer"], "Elmer"),
            # an exact cast name wins before the loose tail runs
            ("Man", ["Man", "Norman"], "Man"),
            ("Emma", ["Emma", "Emma Watson"], "Emma"),
        ],
    )
    def test_folds_onto_the_cast(self, scene, raw, cast, expected):  # noqa: F811
        assert resolve_character_name(scene.world_state, cast, raw) == expected


class TestAddSnapshotEntityAvailability:
    @pytest.mark.asyncio
    async def test_a_disabled_action_starts_no_task(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.actions["update_world_state"].enabled = False
        add = AsyncMock()
        monkeypatch.setattr(agent, "add_snapshot_entity", add)

        assert await agent.dispatch_add_snapshot_entity(1, "the locker") is False
        add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_client_starts_no_task(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        monkeypatch.setattr(agent, "client", None)
        add = AsyncMock()
        monkeypatch.setattr(agent, "add_snapshot_entity", add)

        assert await agent.dispatch_add_snapshot_entity(1, "the locker") is False
        add.assert_not_awaited()


class TestManualEntriesThroughARefresh:
    async def _refresh(self, agent, scene, monkeypatch, raw):  # noqa: F811
        monkeypatch.setattr(
            agent,
            "request_world_state",
            AsyncMock(
                return_value=WorldStateResponse(world_state=raw, anchor_message_ids=[1])
            ),
        )
        await agent.apply_snapshot_update(scene.world_state)

    @pytest.mark.asyncio
    async def test_a_durable_refresh_keeps_an_untouched_manual_entry(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        scene.world_state.items["Beacon"] = ObjectState(
            snapshot="still blinking", manual=True
        )

        await self._refresh(agent, scene, monkeypatch, {"characters": {}, "items": {}})

        assert "Beacon" in scene.world_state.items

    @pytest.mark.asyncio
    async def test_a_legacy_refresh_rebuilds_the_bucket_and_drops_it(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        agent.actions["update_world_state"].config["durable_snapshot"].value = False
        scene.world_state.items["Beacon"] = ObjectState(
            snapshot="still blinking", manual=True
        )

        await self._refresh(agent, scene, monkeypatch, {"characters": {}, "items": {}})

        assert "Beacon" not in scene.world_state.items


class TestDispatchAddSnapshotEntity:
    @pytest.mark.asyncio
    async def test_takes_the_snapshot_slot_from_a_running_refresh(
        self,
        scene,  # noqa: F811
        monkeypatch,
    ):
        agent = instance_module.get_agent("world_state")
        _enable_client_concurrency(monkeypatch, agent)
        release = asyncio.Event()

        async def _blocking_request_update(self, *args, **kwargs):
            await release.wait()

        monkeypatch.setattr(WorldState, "request_update", _blocking_request_update)
        monkeypatch.setattr(agent, "add_snapshot_entity", AsyncMock())

        await agent.update_world_state(force=True)
        refresh = agent._tracked_task(SNAPSHOT_TASK)
        assert refresh is not None and not refresh.done()

        await agent.dispatch_add_snapshot_entity(1, "the locker")
        add = agent._tracked_task(SNAPSHOT_TASK)

        assert add is not refresh
        with pytest.raises(asyncio.CancelledError):
            await refresh
        await add

    @pytest.mark.asyncio
    async def test_a_running_add_is_cancellable(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        _enable_client_concurrency(monkeypatch, agent)
        release = asyncio.Event()

        async def _blocking_add(*args, **kwargs):
            await release.wait()

        monkeypatch.setattr(agent, "add_snapshot_entity", _blocking_add)

        await agent.dispatch_add_snapshot_entity(1, "the locker")
        task = agent._tracked_task(SNAPSHOT_TASK)
        assert task is not None and not task.done()

        assert agent.cancel_world_state_update() is True
        with pytest.raises(asyncio.CancelledError):
            await task


class TestAddAndReportSnapshotEntity:
    @pytest.mark.asyncio
    async def test_reports_a_refusal(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        messages = _capture_status(monkeypatch)
        monkeypatch.setattr(
            agent,
            "add_snapshot_entity",
            AsyncMock(return_value=SnapshotEntityAddition()),
        )

        await agent.add_and_report_snapshot_entity(1, "whatever")

        assert messages[0][1] == "warning"

    @pytest.mark.asyncio
    async def test_reports_a_highlighted_add(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        messages = _capture_status(monkeypatch)
        monkeypatch.setattr(
            agent,
            "add_snapshot_entity",
            AsyncMock(
                return_value=SnapshotEntityAddition(
                    resolved=True,
                    name="Dented Locker",
                    kind="item",
                    in_moment=True,
                    mentions=["the locker"],
                )
            ),
        )

        await agent.add_and_report_snapshot_entity(1, "the locker")

        assert messages[0][1] == "success"
        assert "Dented Locker" in messages[0][0]

    @pytest.mark.asyncio
    async def test_reports_an_entry_outside_the_moment(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        messages = _capture_status(monkeypatch)
        monkeypatch.setattr(
            agent,
            "add_snapshot_entity",
            AsyncMock(
                return_value=SnapshotEntityAddition(
                    resolved=True,
                    name="Dented Locker",
                    kind="item",
                    in_moment=False,
                    mentions=["the locker"],
                )
            ),
        )

        await agent.add_and_report_snapshot_entity(1, "the locker")

        assert messages[0][1] == "info"
        assert "current moment" in messages[0][0]


class TestAddSnapshotEntityErrors:
    @pytest.mark.asyncio
    async def test_a_cancelled_add_reports_nothing(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        messages = _capture_status(monkeypatch)

        await agent.on_add_snapshot_entity_error(GenerationCancelled("scene changed"))

        assert messages == []

    @pytest.mark.asyncio
    async def test_a_real_failure_is_reported(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        messages = _capture_status(monkeypatch)

        await agent.on_add_snapshot_entity_error(RuntimeError("boom"))

        assert messages and messages[0][1] == "error"


class TestAddSnapshotEntityHandler:
    def _handler(self, scene) -> WorldStateWebsocketHandler:  # noqa: F811
        ws = SimpleNamespace(scene=scene, queue_put=Mock())
        handler = WorldStateWebsocketHandler(websocket_handler=ws)
        handler.signal_operation_done = AsyncMock()
        handler.signal_operation_failed = AsyncMock()
        return handler

    @pytest.mark.asyncio
    async def test_dispatches_the_normalized_selection(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        dispatch = AsyncMock(return_value=True)
        monkeypatch.setattr(agent, "dispatch_add_snapshot_entity", dispatch)
        handler = self._handler(scene)

        await handler.handle_add_snapshot_entity(
            {"message_id": 7, "text": "  the dented\n locker "}
        )

        dispatch.assert_awaited_once_with(7, "the dented locker")
        handler.signal_operation_done.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refuses_while_the_action_is_off(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        agent.actions["update_world_state"].enabled = False
        dispatch = AsyncMock()
        monkeypatch.setattr(agent, "dispatch_add_snapshot_entity", dispatch)
        handler = self._handler(scene)

        await handler.handle_add_snapshot_entity(
            {"message_id": 7, "text": "the dented locker"}
        )

        dispatch.assert_not_awaited()
        message = handler.signal_operation_failed.await_args.args[0]
        assert "World State agent" in message

    @pytest.mark.asyncio
    async def test_refuses_without_a_client(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        monkeypatch.setattr(agent, "client", None)
        dispatch = AsyncMock()
        monkeypatch.setattr(agent, "dispatch_add_snapshot_entity", dispatch)
        handler = self._handler(scene)

        await handler.handle_add_snapshot_entity(
            {"message_id": 7, "text": "the dented locker"}
        )

        dispatch.assert_not_awaited()
        message = handler.signal_operation_failed.await_args.args[0]
        assert "no client" in message

    @pytest.mark.asyncio
    async def test_refuses_an_empty_selection(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        dispatch = AsyncMock()
        monkeypatch.setattr(agent, "dispatch_add_snapshot_entity", dispatch)
        handler = self._handler(scene)

        await handler.handle_add_snapshot_entity({"message_id": 7, "text": "   "})

        dispatch.assert_not_awaited()
        handler.signal_operation_failed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refuses_an_over_long_selection(self, scene, monkeypatch):  # noqa: F811
        agent = instance_module.get_agent("world_state")
        dispatch = AsyncMock()
        monkeypatch.setattr(agent, "dispatch_add_snapshot_entity", dispatch)
        handler = self._handler(scene)

        await handler.handle_add_snapshot_entity(
            {"message_id": 7, "text": "x" * (SNAPSHOT_ENTITY_SELECTION_MAX + 1)}
        )

        dispatch.assert_not_awaited()
        handler.signal_operation_failed.assert_awaited_once()
