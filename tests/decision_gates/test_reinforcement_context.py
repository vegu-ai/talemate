import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.agents.base import DynamicInstruction
from talemate.agents.context import ActiveAgent
from talemate.agents.world_state.reinforcements import (
    REINFORCEMENT_HISTORY_CAP,
    reinforcement_history_window,
)
from talemate.character import Character
from talemate.decisions import ProviderCapabilities
from talemate.decisions.budget import state_tokens
from talemate.prompts import Prompt
from talemate.scene_message import (
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
)
from talemate.world_state import ContextPin, Reinforcement
from talemate.world_state.manager import AnnotatedContextPin


@pytest.mark.parametrize("changed_source", ["pin", "description"])
async def test_gate_sees_authoritative_changes_outside_history(
    gate_case, monkeypatch, changed_source
):
    c = gate_case
    character = Character(name="Mara", description="Mara wears a blue coat.")
    c.scene.character_data["Mara"] = character
    reinforcement = Reinforcement(
        question="Where is the key?",
        character="Mara",
        require_active=False,
        answer="In the drawer.",
        instructions="Track the key's current location.",
    )
    c.scene.world_state.reinforce = [reinforcement]
    c.scene.history = [NarratorMessage("The weather is pleasant.")]
    pin = AnnotatedContextPin(
        pin=ContextPin(entry_id="key", active=True),
        is_active=True,
        title="Key location",
        text="The key is in the drawer.",
        time_aware_text="The key is in the drawer.",
    )
    c.scene.active_pins = [pin]
    memory = Mock(return_value=["Mara remembers the key's old hiding place."])
    monkeypatch.setattr(Prompt, "query_memory", memory)
    sent = []

    async def send(prompt, **kwargs):
        sent.append(str(prompt))
        return "<ANSWER>In the chest.</ANSWER>"

    monkeypatch.setattr(c.agent.client, "send_prompt", send)
    with ActiveAgent(c.agent, c.agent.update_reinforcements) as active:
        active.state["dynamic_instructions"] = [
            DynamicInstruction(
                title="Tracking", content="Use the latest known location."
            )
        ]
        c.provider.answers = {"changed": {"type": "noul", "p_true": 0.01}}
        assert (
            await c.agent.generate_reinforcement(
                reinforcement, False, decision_model=True
            )
            is False
        )
        if changed_source == "pin":
            pin.text = pin.time_aware_text = "The key is in the chest."
            changed_text = pin.text
        else:
            character.description = (
                "Mara wears a red coat and keeps the key in her boot."
            )
            changed_text = character.description
        c.provider.answers = {"changed": {"type": "noul", "p_true": 0.99}}
        assert (
            await c.agent.generate_reinforcement(
                reinforcement, False, decision_model=True
            )
            == "In the chest."
        )

    before, after = [call.state for call in c.provider.calls]
    if changed_source == "pin":
        assert before["pins"] == ["Key location: The key is in the drawer."]
        assert after["pins"] == ["Key location: The key is in the chest."]
    else:
        assert before["character_description"] == "Mara wears a blue coat."
        assert after["character_description"] == changed_text
    for state in (before, after):
        assert state["character"] == "Mara"
        assert state["instructions"] == "Track the key's current location."
        assert state["previous_answer"] == "In the drawer."
        assert state["history"] == ["The weather is pleasant."]
        serialized = json.dumps(state)
        assert "Mara remembers the key's old hiding place." not in serialized
        assert "Use the latest known location." not in serialized
    assert [str(message) for message in c.scene.history] == ["The weather is pleasant."]
    (prompt,) = sent
    assert changed_text in prompt
    assert "Mara remembers the key's old hiding place." in prompt
    # the decision state never queries memory; only the update request does
    assert memory.call_count == 1


@pytest.mark.parametrize("interval", [1, 10, 30])
async def test_gate_history_is_the_window_since_the_last_update(
    gate_case, monkeypatch, interval
):
    c = gate_case
    reinforcement = Reinforcement(
        question="Where is the key?", answer="In the drawer.", interval=interval
    )
    c.scene.world_state.reinforce = [reinforcement]
    c.scene.history = [
        NarratorMessage(f"Report {number}: the fog rolls over the sound.")
        for number in range(400)
    ]
    c.scene.history.insert(-1, ReinforcementMessage("Internal note."))
    c.scene.history.insert(-1, DirectorMessage("Director note."))
    monkeypatch.setattr(
        type(c.agent.client), "max_token_length", property(lambda _: 32768)
    )
    llm = AsyncMock()
    monkeypatch.setattr(c.agent.client, "send_prompt", llm)
    c.provider.answers = {"changed": {"type": "noul", "p_true": 0.01}}
    window = reinforcement_history_window(interval)
    expected = [
        f"Report {number}: the fog rolls over the sound."
        for number in range(400 - window, 400)
    ]

    states = []
    for question_limit in (None, 32000, 128000):
        c.provider.capabilities = ProviderCapabilities(
            max_question_input_tokens=question_limit
        )
        c.provider.calls.clear()
        assert (
            await c.agent.generate_reinforcement(
                reinforcement, False, decision_model=True
            )
            is False
        )
        (request,) = c.provider.calls
        states.append(request.state)
        record = list(c.service.log.records.values())[-1]
        assert record.tokens.sized
        assert record.tokens.state == state_tokens(request.state)
        assert (record.tokens.budget is None) == (question_limit is None)

    assert window == 2 * interval + 3
    assert all(state == states[0] for state in states)
    assert states[0]["history"] == expected
    assert states[0]["history_left_out"] == 0
    llm.assert_not_awaited()


async def test_gate_history_is_capped(gate_case, monkeypatch):
    c = gate_case
    reinforcement = Reinforcement(
        question="Where is the key?", answer="In the drawer.", interval=10
    )
    c.scene.world_state.reinforce = [reinforcement]
    c.scene.history = [
        NarratorMessage(f"Report {number}: " + "The fog rolls over the sound. " * 60)
        for number in range(100)
    ]
    c.provider.answers = {"changed": {"type": "noul", "p_true": 0.01}}

    await c.agent.generate_reinforcement(reinforcement, False, decision_model=True)

    (request,) = c.provider.calls
    history = request.state["history"]
    assert state_tokens({"history": history}) <= REINFORCEMENT_HISTORY_CAP
    assert history[-1].startswith("Report 99:")
    assert len(history) < reinforcement_history_window(10)
    assert request.state["history_left_out"] == (
        reinforcement_history_window(10) - len(history)
    )


@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("decision", ["unready", "uncertain", "failed"])
@pytest.mark.parametrize("fail_first", [False, True])
async def test_two_due_states_preserve_scheduling_and_failures(
    gate_case, monkeypatch, concurrent, decision, fail_first
):
    c = gate_case
    first, second = [
        Reinforcement(question=question, answer="Old answer.", interval=5)
        for question in ("First?", "Second?")
    ]
    c.scene.world_state.reinforce = [first, second]
    c.scene.history = [NarratorMessage("Original scene history.")]
    monkeypatch.setattr(
        type(c.agent.client),
        "supports_concurrent_inference",
        property(lambda _: concurrent),
    )
    monkeypatch.setattr(Prompt, "query_memory", lambda *args, **kwargs: [])
    c.provider.ready = decision != "unready"
    if decision == "failed":
        c.provider.error = RuntimeError("Decision unavailable")
    events, prompts = [], {}
    in_flight = max_in_flight = 0

    async def send(prompt, **kwargs):
        nonlocal in_flight, max_in_flight
        question = prompt.vars["question"]
        prompts[question] = str(prompt)
        events.append(("generate", question))
        in_flight += 1
        max_in_flight = max(in_flight, max_in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        if fail_first and question == first.question:
            raise RuntimeError("First state failed")
        return f"<ANSWER>Fresh answer for {question}</ANSWER>"

    apply = c.agent._apply_reinforcement

    async def record_apply(reinforcement, message, answer, reset):
        events.append(("apply", reinforcement.question))
        return await apply(reinforcement, message, answer, reset)

    monkeypatch.setattr(c.agent.client, "send_prompt", send)
    monkeypatch.setattr(c.agent, "_apply_reinforcement", record_apply)
    if fail_first:
        with pytest.raises(RuntimeError, match="First state failed"):
            await c.agent.update_reinforcements()
    else:
        await c.agent.update_reinforcements()

    if concurrent:
        assert events[:2] == [("generate", "First?"), ("generate", "Second?")]
        assert "Fresh answer for First?" not in prompts["Second?"]
        assert second.answer == "Fresh answer for Second?"
        assert events[2:] == (
            [("apply", "Second?")]
            if fail_first
            else [("apply", "First?"), ("apply", "Second?")]
        )
    elif fail_first:
        assert events == [("generate", "First?")]
        assert second.answer == "Old answer."
    else:
        assert events == [
            ("generate", "First?"),
            ("apply", "First?"),
            ("generate", "Second?"),
            ("apply", "Second?"),
        ]
        assert "Fresh answer for First?" in prompts["Second?"]
    assert max_in_flight == (2 if concurrent and decision == "unready" else 1)
    if decision == "unready":
        assert not c.provider.calls
        assert not c.service.log.invocations
    else:
        assert len(c.provider.calls) == len(prompts)
