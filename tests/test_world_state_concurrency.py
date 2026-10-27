"""Pins for the world-state concurrency gates (#306/#307).

Both the reinforcement-update loop and the character-progression loop must:
- keep today's interleaved generate->apply sequence when the client does not
  support concurrent inference,
- fan generations out (bounded at 3) and apply results sequentially in the
  original order when it does,
- apply the successful results and re-raise the first failure when a
  generation errors mid-batch.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from _world_state_helpers import (
    make_actor,
    scene,  # noqa: F401 - pytest fixture
)

import talemate.agents.world_state.reinforcements as reinforcements_module
import talemate.instance as instance_module
from talemate.exceptions import GenerationCancelled
from talemate.world_state import Reinforcement


class FakeClient:
    name = "fake-client"
    max_token_length = 8192
    current_status = "idle"
    enabled = True

    def __init__(self, supports_concurrent_inference: bool):
        self.supports_concurrent_inference = supports_concurrent_inference


class Recorder:
    """Tracks generate/apply events and generation overlap."""

    def __init__(self, fail_on=None, cancel_on=None, delay=0.01):
        self.events = []
        self.fail_on = fail_on
        self.cancel_on = cancel_on
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0

    async def generate(self, key):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        if key == self.cancel_on:
            raise GenerationCancelled(f"cancelled at {key}")
        if key == self.fail_on:
            raise RuntimeError(f"generation failed for {key}")
        self.events.append(("generate", key))
        return f"answer for {key}"

    async def apply(self, key):
        self.events.append(("apply", key))


@pytest.fixture
def agent(scene):  # noqa: F811
    return instance_module.get_agent("world_state")


def add_reinforcements(scene, questions):  # noqa: F811
    reinforcements = []
    for question in questions:
        r = Reinforcement(question=question, answer="old", due=0)
        scene.world_state.reinforce.append(r)
        reinforcements.append(r)
    return reinforcements


def wire_reinforcements(agent, recorder, monkeypatch):
    async def _generate(reinforcement, reset, *, decision_model=False):
        return await recorder.generate(reinforcement.question)

    async def _apply(reinforcement, message, answer, reset):
        assert answer == f"answer for {reinforcement.question}"
        await recorder.apply(reinforcement.question)
        return message

    monkeypatch.setattr(agent, "generate_reinforcement", _generate)
    monkeypatch.setattr(agent, "_apply_reinforcement", _apply)


class TestReinforcementConcurrency:
    async def test_sequential_without_concurrent_support(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        agent.client = FakeClient(supports_concurrent_inference=False)
        add_reinforcements(scene, ["q1", "q2", "q3"])
        recorder = Recorder()
        wire_reinforcements(agent, recorder, monkeypatch)

        await agent.update_reinforcements()

        assert recorder.events == [
            ("generate", "q1"),
            ("apply", "q1"),
            ("generate", "q2"),
            ("apply", "q2"),
            ("generate", "q3"),
            ("apply", "q3"),
        ]
        assert recorder.max_in_flight == 1

    async def test_concurrent_generates_then_applies_in_order(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        agent.client = FakeClient(supports_concurrent_inference=True)
        add_reinforcements(scene, ["q1", "q2", "q3", "q4"])
        recorder = Recorder()
        wire_reinforcements(agent, recorder, monkeypatch)

        await agent.update_reinforcements()

        applies = [key for kind, key in recorder.events if kind == "apply"]
        first_apply = recorder.events.index(("apply", "q1"))
        generates_before = [
            e for e in recorder.events[:first_apply] if e[0] == "generate"
        ]
        assert applies == ["q1", "q2", "q3", "q4"]
        assert len(generates_before) == 4
        assert recorder.max_in_flight == 3

    async def test_concurrent_failure_applies_successes_then_raises(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        agent.client = FakeClient(supports_concurrent_inference=True)
        add_reinforcements(scene, ["q1", "q2", "q3"])
        recorder = Recorder(fail_on="q2")
        wire_reinforcements(agent, recorder, monkeypatch)

        with pytest.raises(RuntimeError, match="generation failed for q2"):
            await agent.update_reinforcements()

        applies = [key for kind, key in recorder.events if kind == "apply"]
        assert applies == ["q1", "q3"]

    async def test_concurrent_interrupt_aborts_batch_without_applying(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        agent.client = FakeClient(supports_concurrent_inference=True)
        add_reinforcements(scene, ["q1", "q2", "q3"])
        recorder = Recorder(cancel_on="q2")
        wire_reinforcements(agent, recorder, monkeypatch)

        with pytest.raises(GenerationCancelled):
            await agent.update_reinforcements()

        applies = [key for kind, key in recorder.events if kind == "apply"]
        assert applies == []

    async def test_single_due_item_stays_on_sequential_path(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        agent.client = FakeClient(supports_concurrent_inference=True)
        add_reinforcements(scene, ["q1"])

        called = []

        async def _fake_update(
            question, character, reset=False, *, decision_model=False
        ):
            called.append(question)

        monkeypatch.setattr(agent, "update_reinforcement", _fake_update)
        await agent.update_reinforcements()
        assert called == ["q1"]

    async def test_update_reinforcement_generates_and_applies(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        # exercises the real _prepare/_generate/_apply split through the
        # public entry point, stubbing only the LLM boundary
        agent.client = FakeClient(supports_concurrent_inference=False)
        make_actor(scene, "Alice")
        r = Reinforcement(
            question="Mood", character="Alice", answer="old", due=0, interval=7
        )
        scene.world_state.reinforce.append(r)

        async def _fake_request(uid, client, kind, vars=None, **kwargs):
            assert vars["question"] == "Mood"
            assert vars["answer"] == "old"
            return ("<ANSWER>cheerful</ANSWER>", {"response": "cheerful"})

        monkeypatch.setattr(
            reinforcements_module.Prompt,
            "request",
            classmethod(
                lambda cls, uid, client, kind, vars=None, **kwargs: _fake_request(
                    uid, client, kind, vars=vars, **kwargs
                )
            ),
        )

        message = await agent.update_reinforcement("Mood", "Alice")

        assert r.answer == "cheerful"
        assert r.due == 7
        assert message.message == "cheerful"
        assert scene.history[-1] is message
        assert scene.get_character("Alice").details["Mood"] == "cheerful"

    async def test_force_runs_concurrent_path(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        agent.client = FakeClient(supports_concurrent_inference=True)
        reinforcements = add_reinforcements(scene, ["q1", "q2", "q3"])
        for r in reinforcements:
            r.due = 5
        recorder = Recorder()
        wire_reinforcements(agent, recorder, monkeypatch)

        await agent.update_reinforcements(force=True)

        applies = [key for kind, key in recorder.events if kind == "apply"]
        assert applies == ["q1", "q2", "q3"]
        assert recorder.max_in_flight == 3

    async def test_reset_routes_to_sequential_path(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        # reset pops history in prepare, before any answer exists - the
        # concurrent path must not run every item's destructive prepare
        # up front
        agent.client = FakeClient(supports_concurrent_inference=True)
        add_reinforcements(scene, ["q1", "q2", "q3"])

        called = []

        async def _fake_update(
            question, character, reset=False, *, decision_model=False
        ):
            called.append((question, reset))

        monkeypatch.setattr(agent, "update_reinforcement", _fake_update)
        await agent.update_reinforcements(reset=True)
        assert called == [("q1", True), ("q2", True), ("q3", True)]

    async def test_not_due_still_decrements(self, scene, agent, monkeypatch):  # noqa: F811
        agent.client = FakeClient(supports_concurrent_inference=True)
        r = Reinforcement(question="later", answer="old", due=3)
        scene.world_state.reinforce.append(r)
        recorder = Recorder()
        wire_reinforcements(agent, recorder, monkeypatch)

        await agent.update_reinforcements()

        assert recorder.events == []
        assert r.due == 2


def make_characters(names):
    return [SimpleNamespace(name=name, is_player=False) for name in names]


def set_progression_clients(agent, world_state_supported, creator_supported):
    agent.client = FakeClient(world_state_supported)
    instance_module.get_agent("creator").client = FakeClient(creator_supported)


def wire_progression(agent, recorder, monkeypatch):
    async def _determine(character):
        return await recorder.generate(character.name)

    async def _process(character, calls, as_suggestions=True):
        assert calls == f"answer for {character.name}"
        assert as_suggestions is agent.character_progression_as_suggestions
        await recorder.apply(character.name)

    monkeypatch.setattr(agent, "determine_character_development", _determine)
    monkeypatch.setattr(agent, "character_progression_process_calls", _process)


class TestCharacterProgressionConcurrency:
    async def test_sequential_without_concurrent_support(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        set_progression_clients(agent, False, True)
        recorder = Recorder()
        wire_progression(agent, recorder, monkeypatch)

        await agent.character_progression_track(make_characters(["Ada", "Bo"]))

        assert recorder.events == [
            ("generate", "Ada"),
            ("apply", "Ada"),
            ("generate", "Bo"),
            ("apply", "Bo"),
        ]
        assert recorder.max_in_flight == 1

    async def test_concurrent_determines_then_processes_in_order(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        set_progression_clients(agent, True, True)
        recorder = Recorder()
        wire_progression(agent, recorder, monkeypatch)

        await agent.character_progression_track(
            make_characters(["Ada", "Bo", "Cy", "Dee"])
        )

        applies = [key for kind, key in recorder.events if kind == "apply"]
        first_apply = recorder.events.index(("apply", "Ada"))
        generates_before = [
            e for e in recorder.events[:first_apply] if e[0] == "generate"
        ]
        assert applies == ["Ada", "Bo", "Cy", "Dee"]
        assert len(generates_before) == 4
        assert recorder.max_in_flight == 3

    async def test_concurrent_failure_processes_successes_then_raises(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        set_progression_clients(agent, True, True)
        recorder = Recorder(fail_on="Bo")
        wire_progression(agent, recorder, monkeypatch)

        with pytest.raises(RuntimeError, match="generation failed for Bo"):
            await agent.character_progression_track(
                make_characters(["Ada", "Bo", "Cy"])
            )

        applies = [key for kind, key in recorder.events if kind == "apply"]
        assert applies == ["Ada", "Cy"]

    async def test_unsupported_creator_client_forces_sequential(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        # the development callbacks generate through the creator agent, so
        # its client gates the fan-out too
        set_progression_clients(agent, True, False)
        recorder = Recorder()
        wire_progression(agent, recorder, monkeypatch)

        await agent.character_progression_track(make_characters(["Ada", "Bo"]))

        assert recorder.events == [
            ("generate", "Ada"),
            ("apply", "Ada"),
            ("generate", "Bo"),
            ("apply", "Bo"),
        ]
        assert recorder.max_in_flight == 1

    async def test_concurrent_interrupt_aborts_batch_without_processing(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        set_progression_clients(agent, True, True)
        recorder = Recorder(cancel_on="Bo")
        wire_progression(agent, recorder, monkeypatch)

        with pytest.raises(GenerationCancelled):
            await agent.character_progression_track(
                make_characters(["Ada", "Bo", "Cy"])
            )

        applies = [key for kind, key in recorder.events if kind == "apply"]
        assert applies == []

    async def test_single_character_stays_on_sequential_path(
        self,
        scene,  # noqa: F811
        agent,
        monkeypatch,
    ):
        set_progression_clients(agent, True, True)
        recorder = Recorder()
        wire_progression(agent, recorder, monkeypatch)

        await agent.character_progression_track(make_characters(["Ada"]))

        assert recorder.events == [("generate", "Ada"), ("apply", "Ada")]
