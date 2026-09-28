import asyncio
from unittest.mock import Mock

import pytest

from talemate.agents.base import DynamicInstruction
from talemate.agents.context import ActiveAgent
from talemate.character import Character
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage
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

    before, after = [call.state["context"] for call in c.provider.calls]
    assert before != after
    assert changed_text not in before and changed_text in after
    for context in (before, after):
        assert "Key location" in context
        assert "Mara wears" in context
        assert "Mara remembers the key's old hiding place." in context
        assert "Use the latest known location." in context
        assert "Track the key's current location." in context
        assert "The weather is pleasant." in context
    assert [str(message) for message in c.scene.history] == ["The weather is pleasant."]
    assert sent == [after]
    assert (
        memory.call_count == 2
    )  # One retrieval per update, never repeated on fallback.


async def test_gate_uses_updates_full_history_budget(gate_case, monkeypatch):
    c = gate_case
    reinforcement = Reinforcement(question="Where is the key?", answer="In the drawer.")
    c.scene.world_state.reinforce = [reinforcement]
    c.scene.history = [NarratorMessage("Mara moved the key into the locked chest.")]
    c.scene.history.extend(
        NarratorMessage(f"Weather report {number}: " + "The rain falls steadily. " * 25)
        for number in range(25)
    )
    monkeypatch.setattr(
        type(c.agent.client), "max_token_length", property(lambda _: 8192)
    )
    monkeypatch.setattr(Prompt, "query_memory", lambda *args, **kwargs: [])
    assert "locked chest" not in "\n".join(c.scene.context_history(budget=2048))
    sent = []

    async def send(prompt, **kwargs):
        sent.append(str(prompt))
        return "<ANSWER>In the locked chest.</ANSWER>"

    monkeypatch.setattr(c.agent.client, "send_prompt", send)
    assert (
        await c.agent.generate_reinforcement(reinforcement, False, decision_model=True)
        == "In the locked chest."
    )
    context = c.provider.calls[0].state["context"]
    assert "Mara moved the key into the locked chest." in context
    assert "Weather report 24" in context
    assert sent == [context]


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
