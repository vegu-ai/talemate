"""
decision.invocation.finished, decision.gate.resolved and
agent.world_state.reinforcement.skipped.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

import talemate.emit.async_signals as async_signals
from talemate.agents.world_state.reinforcements import ReinforcementSkippedEmission
from talemate.decisions.gate import DecisionGateResolved
from talemate.decisions.policy import DecisionInvocationFinished
from talemate.world_state import Reinforcement


@pytest.fixture
def listen():
    connected = []

    def connect(name):
        received = []

        async def handler(emission):
            received.append(emission)

        async_signals.get(name).connect(handler)
        connected.append((name, handler))
        return received

    yield connect
    for name, handler in connected:
        async_signals.get(name).disconnect(handler)


async def ask(case, monkeypatch, answer="Yes"):
    llm = AsyncMock(return_value=answer)
    monkeypatch.setattr(case.agent, "analyze_text_and_answer_question", llm)
    result = await case.agent.answer_query_true_or_false(
        query="Is the door open?", text="The door is open."
    )
    return result, llm


@pytest.mark.parametrize(
    "probability, expected, decided, fallback_ids",
    [
        (0.95, True, {"query": True}, []),
        (0.5, True, {}, ["query"]),
    ],
)
async def test_gate_and_invocation_events(
    gate_case, monkeypatch, listen, probability, expected, decided, fallback_ids
):
    c = gate_case
    c.provider.answers = {"query": {"type": "noul", "p_true": probability}}
    gates = listen("decision.gate.resolved")
    invocations = listen("decision.invocation.finished")
    result, _ = await ask(c, monkeypatch)
    assert result is expected

    [gate] = gates
    assert isinstance(gate, DecisionGateResolved)
    assert gate.uid == "world_state.decision-query"
    assert gate.gate_enabled is True
    assert gate.candidates == ["query"]
    assert gate.decided == decided
    assert gate.fallback_ids == fallback_ids
    assert gate.result == {"query": expected}

    [invocation] = invocations
    assert isinstance(invocation, DecisionInvocationFinished)
    assert invocation.template_uid == "world_state.decision-query"
    assert invocation.status == "completed"
    [request] = invocation.requests
    assert request.status == "completed"
    assert request.failure_code is None
    assert request.answers == {"query": {"type": "noul", "p_true": probability}}
    assert invocation.actions and invocation.actions[0]["action"]


async def test_gate_off_sends_resolved_without_an_invocation(
    gate_case, monkeypatch, listen
):
    c = gate_case
    c.agent.actions["queries"].config["decision_model"].value = False
    gates = listen("decision.gate.resolved")
    invocations = listen("decision.invocation.finished")
    result, llm = await ask(c, monkeypatch, answer="No")
    assert result is False
    llm.assert_awaited_once()
    [gate] = gates
    assert gate.gate_enabled is False
    assert gate.decided == {}
    assert gate.fallback_ids == ["query"]
    assert invocations == []


async def test_failed_request_is_reported(gate_case, monkeypatch, listen):
    c = gate_case
    c.provider.error = RuntimeError("request failed")
    invocations = listen("decision.invocation.finished")
    await ask(c, monkeypatch)
    [invocation] = invocations
    assert invocation.status == "fallback"
    [request] = invocation.requests
    assert request.status == "failed"
    assert request.failure_code == "transport"


async def test_unchanged_reinforcement_sends_skipped(gate_case, listen):
    c = gate_case
    skipped = listen("agent.world_state.reinforcement.skipped")
    reinforcement = Reinforcement(
        question="Mood", answer="calm", character="Bob", interval=7
    )
    c.scene.world_state.reinforce.append(reinforcement)
    result = await c.agent._apply_reinforcement(reinforcement, None, False, False)
    assert result is None
    [emission] = skipped
    assert isinstance(emission, ReinforcementSkippedEmission)
    assert emission.agent is c.agent
    assert (emission.question, emission.character, emission.answer) == (
        "Mood",
        "Bob",
        "calm",
    )
    assert emission.interval == 7
    assert reinforcement.due == 7


async def test_events_from_a_gate_inside_a_template_wait_for_the_render(
    gate_case, monkeypatch, listen, tmp_path
):
    from talemate.character import Character
    from talemate.prompts.base import (
        PrependTemplateDirectories,
        Prompt,
        _render_signals,
    )
    from talemate.tale_mate import Actor

    c = gate_case
    for name in ("Mara", "Player"):
        c.scene.character_data[name] = Character(name=name, description=name)
    c.scene.actors.append(Actor(character=c.scene.character_data["Player"], agent=None))
    c.scene.active_characters = ["Player"]
    c.provider.answers = {"Mara": {"type": "noul", "p_true": 0.99}}
    monkeypatch.setattr(c.memory, "get_documents_by_meta", AsyncMock(return_value={}))

    async def rag_build(**kwargs):
        await c.agent.entity_lookup(["Mara laughs."])
        return ""

    monkeypatch.setattr(c.memory, "rag_build", rag_build, raising=False)
    order = []
    handlers = []
    for name in ("decision.gate.resolved", "decision.invocation.finished"):

        async def handler(emission, name=name):
            order.append((name, _render_signals.get() is None))

        async_signals.get(name).connect(handler)
        handlers.append((name, handler))
    (tmp_path / "ncov-render-check.jinja2").write_text(
        '{{ agent_action("memory", "rag_build") }}done'
    )
    try:
        with PrependTemplateDirectories(str(tmp_path)):
            rendered = Prompt.get("world_state.ncov-render-check").render()
            order.append(("rendered", True))
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        for name, handler in handlers:
            async_signals.get(name).disconnect(handler)
    assert rendered.endswith("done")
    assert order[0] == ("rendered", True)
    assert sorted(order[1:]) == [
        ("decision.gate.resolved", True),
        ("decision.invocation.finished", True),
    ]
