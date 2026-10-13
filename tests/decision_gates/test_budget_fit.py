from unittest.mock import AsyncMock

from talemate.character import Character
from talemate.decisions import ProviderCapabilities
from talemate.decisions.budget import state_tokens
from talemate.decisions.characters import referenced_characters
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage
from talemate.world_state import ContextPin, Reinforcement

LIMIT = 600


def limit(c, total=None, question=LIMIT):
    c.provider.capabilities = ProviderCapabilities(
        max_input_tokens=total, max_question_input_tokens=question
    )


def narration(count):
    return [
        NarratorMessage(f"Report {number}: " + "The fog rolls over the sound. " * 6)
        for number in range(count)
    ]


def assert_within_limit(c, request, limit=LIMIT):
    question_tokens = max(
        state_tokens({key: c.provider.serialize_question(question)})
        for key, question in request.questions.items()
    )
    assert state_tokens(request.state) + question_tokens <= limit


async def test_pin_history_keeps_the_newest_messages(gate_case, monkeypatch):
    c = gate_case
    limit(c)
    c.scene.history = narration(40)
    c.scene.world_state.pins = {
        "fog": ContextPin(entry_id="fog", condition="Is there fog?")
    }
    c.provider.answers = {"fog": {"type": "noul", "p_true": 0.99}}
    llm = AsyncMock()
    monkeypatch.setattr(Prompt, "request", llm)

    await c.agent.check_pin_conditions()

    (request,) = c.provider.calls
    assert_within_limit(c, request)
    # the condition goes out once, in its question
    assert request.state["previous_states"] == {"fog": False}
    assert "Is there fog?" in request.questions["fog"].instructions
    history = request.state["history"]
    assert history and history[-1].startswith("Report 39:")
    assert not any(line.startswith("Report 0:") for line in history)
    llm.assert_not_awaited()


async def test_query_text_keeps_its_end(gate_case, monkeypatch):
    c = gate_case
    limit(c)
    text = "\n".join(str(message) for message in narration(40))
    c.provider.answers = {"query": {"type": "noul", "p_true": 0.99}}
    llm = AsyncMock()
    monkeypatch.setattr(c.agent, "analyze_text_and_answer_question", llm)

    assert await c.agent.answer_query_true_or_false("Is there fog?", text) is True

    (request,) = c.provider.calls
    assert_within_limit(c, request)
    assert text.endswith(request.state) and len(request.state) < len(text)
    llm.assert_not_awaited()


async def test_character_questions_are_split_and_text_fitted(gate_case):
    c = gate_case
    limit(c, total=LIMIT)
    names = [f"Keeper{number}" for number in range(12)]
    for name in names:
        c.scene.character_data[name] = Character(
            name=name, description=f"{name} keeps a lighthouse. " * 8
        )
    c.provider.answers = {"Keeper11": {"type": "noul", "p_true": 0.99}}
    text = "\n".join(str(message) for message in narration(40))

    named = await referenced_characters(
        c.scene,
        text,
        names,
        uid="memory.decision-entity-references",
        enabled=True,
        match=lambda name: False,
        is_current=lambda: True,
    )

    assert named == ["Keeper11"]
    assert len(c.provider.calls) > 1
    assert [key for call in c.provider.calls for key in call.questions] == names
    for request in c.provider.calls:
        assert text.endswith(request.state)
        assert (
            state_tokens(request.state)
            + sum(
                state_tokens({key: c.provider.serialize_question(question)})
                for key, question in request.questions.items()
            )
            <= LIMIT
        )


async def test_tracked_state_history_is_fitted_to_the_budget(gate_case, monkeypatch):
    c = gate_case
    limit(c, question=400)
    reinforcement = Reinforcement(
        question="Where is the key?", answer="In the drawer.", interval=10
    )
    c.scene.world_state.reinforce = [reinforcement]
    c.scene.history = [NarratorMessage("Mara moved the key into the locked chest.")]
    c.scene.history.extend(narration(60))
    monkeypatch.setattr(
        type(c.agent.client), "max_token_length", property(lambda _: 8192)
    )
    monkeypatch.setattr(Prompt, "query_memory", lambda *args, **kwargs: [])
    sent = []

    async def send(prompt, **kwargs):
        sent.append(str(prompt))
        return "<ANSWER>In the locked chest.</ANSWER>"

    monkeypatch.setattr(c.agent.client, "send_prompt", send)
    c.provider.answers = {"changed": {"type": "noul", "p_true": 0.99}}

    assert (
        await c.agent.generate_reinforcement(reinforcement, False, decision_model=True)
        == "In the locked chest."
    )

    (request,) = c.provider.calls
    assert_within_limit(c, request, 400)
    history = request.state["history"]
    assert history and history[-1].startswith("Report 59:")
    assert len(history) < 23
    assert request.state["history_left_out"] == 23 - len(history)
    assert request.state["question"] == "Where is the key?"
    # the fallback renders the update at the client's own size
    (prompt,) = sent
    assert "Mara moved the key into the locked chest." in prompt


async def test_tracked_state_too_large_for_any_history_falls_back(
    gate_case, monkeypatch
):
    c = gate_case
    limit(c, question=100)
    reinforcement = Reinforcement(question="Where is the key?", answer="In the drawer.")
    c.scene.world_state.reinforce = [reinforcement]
    c.scene.history = narration(5)
    monkeypatch.setattr(Prompt, "query_memory", lambda *args, **kwargs: [])
    sent = []

    async def send(prompt, **kwargs):
        sent.append(str(prompt))
        return "<ANSWER>In the chest.</ANSWER>"

    monkeypatch.setattr(c.agent.client, "send_prompt", send)

    assert (
        await c.agent.generate_reinforcement(reinforcement, False, decision_model=True)
        == "In the chest."
    )

    assert not c.provider.calls
    record = next(iter(c.service.log.records.values()))
    assert record.failure.code == "oversize"
    (prompt,) = sent
    assert "Report 4:" in prompt
