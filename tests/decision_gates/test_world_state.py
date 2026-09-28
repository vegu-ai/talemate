import json
from unittest.mock import AsyncMock

import pytest

from _node_test_helpers import build_graph, execute_graph, make_capture, make_constant
from talemate.agents.world_state.nodes import EvaluateQuery
from talemate.prompts import Prompt
from talemate.prompts.base import PrependTemplateDirectories
from talemate.scene_message import NarratorMessage
from talemate.world_state import ContextPin


@pytest.mark.parametrize(
    "probability,expected,llm_calls",
    [(0.95, True, 0), (0.05, False, 0), (0.5, True, 1)],
)
async def test_query_graph(gate_case, monkeypatch, probability, expected, llm_calls):
    c = gate_case
    c.provider.answers = {"query": {"type": "noul", "p_true": probability}}
    llm = AsyncMock(return_value="Yes")
    monkeypatch.setattr(c.agent, "analyze_text_and_answer_question", llm)
    query = EvaluateQuery()
    source = make_constant(
        query="Is the door open?", context="The door is open.", state=True
    )
    captured = {}
    output = make_capture(captured, "result")
    graph = build_graph(source, query, output)
    graph.connect(source.outputs[0], query.get_input_socket("query"))
    graph.connect(source.outputs[1], query.get_input_socket("context"))
    graph.connect(source.get_output_socket("state"), query.get_input_socket("state"))
    graph.connect(query.get_output_socket("result"), output.inputs[0])
    await execute_graph(c.scene, graph)
    assert captured["result"] is expected
    assert llm.await_count == llm_calls
    assert len(c.provider.calls) == 1
    record = next(iter(c.service.log.records.values()))
    assert record.actions[0].result["fallback_ran"] is bool(llm_calls)
    assert record.outcomes[0]["details"]["confidence"] == max(
        probability, 1 - probability
    )


@pytest.mark.parametrize(
    "mode", ["off", "disabled", "no_provider", "failed", "unavailable"]
)
async def test_query_old_path(gate_case, monkeypatch, mode):
    c = gate_case
    if mode == "off":
        c.agent.actions["queries"].config["decision_model"].value = False
    elif mode == "disabled":
        c.service.enabled = False
    elif mode == "no_provider":
        c.service.provider = None
    elif mode == "failed":
        c.provider.error = RuntimeError("request failed")
    else:
        c.provider.ready = False
    llm = AsyncMock(return_value="No")
    monkeypatch.setattr(c.agent, "analyze_text_and_answer_question", llm)
    assert await c.agent.answer_query_true_or_false("Open?", "Closed.") is False
    llm.assert_awaited_once_with(
        query="Open? Answer with a yes or no.", text="Closed.", response_length=10
    )
    if mode == "failed":
        record = next(iter(c.service.log.records.values()))
        assert record.status == "failed"
        assert record.actions[0].action == "disabled_path"
        assert record.actions[0].status == "completed"
    else:
        assert not c.provider.calls and not c.service.log.records


@pytest.mark.parametrize("failed", [False, True])
async def test_llm_error_propagates_without_retry(gate_case, monkeypatch, failed):
    c = gate_case
    if failed:
        c.provider.error = RuntimeError("request failed")
    llm = AsyncMock(side_effect=ValueError("original failure"))
    monkeypatch.setattr(c.agent, "analyze_text_and_answer_question", llm)
    with pytest.raises(ValueError, match="original failure"):
        await c.agent.answer_query_true_or_false("Open?", "Closed.")
    llm.assert_awaited_once()
    assert len(c.provider.calls) == 1


async def test_query_policy_override(gate_case, monkeypatch, tmp_path):
    from pathlib import Path

    c = gate_case
    c.provider.answers = {"query": {"type": "noul", "p_true": 0.8}}
    llm = AsyncMock(return_value="No")
    monkeypatch.setattr(c.agent, "analyze_text_and_answer_question", llm)
    source = Path(
        "src/talemate/prompts/templates/world_state/decision-query.jinja2"
    ).read_text()
    (tmp_path / "decision-query.jinja2").write_text(
        source.replace("threshold = 0.9", "threshold = 0.75")
    )
    with PrependTemplateDirectories(str(tmp_path)):
        result = await c.agent.answer_query_true_or_false("Open?", "Open.")
    assert result is True, [
        record.model_dump() for record in c.service.log.records.values()
    ]
    llm.assert_not_awaited()


@pytest.mark.parametrize(
    "mode,expected_ids",
    [
        ("confident", []),
        ("mixed", ["uncertain"]),
        ("failed", ["yes", "no", "uncertain"]),
        ("off", ["yes", "no", "uncertain"]),
        ("disabled", ["yes", "no", "uncertain"]),
    ],
)
async def test_pins_batch_and_decay(gate_case, monkeypatch, mode, expected_ids):
    from talemate.game.schema import ConditionGroup

    c = gate_case
    c.scene.history = [NarratorMessage("The door opens. Nobody is asleep.")]
    c.scene.world_state.pins = {
        "yes": ContextPin(entry_id="yes", condition="Is the door open?", decay=5),
        "no": ContextPin(
            entry_id="no",
            condition="Is anybody asleep?",
            active=True,
            condition_state=True,
        ),
        "uncertain": ContextPin(entry_id="uncertain", condition="Is it raining?"),
        "decaying": ContextPin(
            entry_id="decaying",
            condition="Still here?",
            active=True,
            decay=8,
            decay_due=4,
        ),
        "game": ContextPin(
            entry_id="game",
            gamestate_condition=[ConditionGroup(conditions=[], operator="and")],
            active=True,
            decay=8,
            decay_due=4,
        ),
    }
    c.provider.answers = {
        key: {"type": "noul", "p_true": probability}
        for key, probability in {
            "yes": 0.95,
            "no": 0.05,
            "uncertain": 0.95 if mode == "confident" else 0.5,
        }.items()
    }
    if mode == "failed":
        c.provider.error = RuntimeError("request failed")
    elif mode == "off":
        c.agent.actions["check_pin_conditions"].config["decision_model"].value = False
    elif mode == "disabled":
        c.service.enabled = False

    async def request(uid, client, kind, vars):
        assert uid == "world_state.check-pin-conditions"
        pins = json.loads(vars["previous_states"])
        assert list(pins) == expected_ids
        return "", {key: {"state": key != "no"} for key in pins}

    llm = AsyncMock(side_effect=request)
    monkeypatch.setattr(Prompt, "request", llm)
    await c.agent.check_pin_conditions()
    assert llm.await_count == bool(expected_ids)
    pins = c.scene.world_state.pins
    assert pins["yes"].active and pins["yes"].decay_due == 4
    assert not pins["no"].active
    assert pins["uncertain"].active
    assert pins["decaying"].decay_due == 3
    assert pins["game"].decay_due == 4
    if c.provider.calls:
        assert set(c.provider.calls[0].questions) == {"yes", "no", "uncertain"}
        assert "The door opens" in str(c.provider.calls[0].state["history"])
