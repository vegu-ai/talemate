import asyncio
from unittest.mock import AsyncMock

import pytest

from talemate.decisions.gate import decision_gate
from talemate.exceptions import GenerationCancelled
from talemate.prompts.base import PrependTemplateDirectories


async def query_gate(case, fallback):
    return await decision_gate(
        "world_state.decision-query",
        enabled=True,
        candidates={"query": [True, False]},
        variables=lambda: {"query": "Is the door open?", "text": "The door is open."},
        fallback=fallback,
    )


async def test_timeout_takes_fallback_once(gate_case, monkeypatch):
    c = gate_case
    c.service.timeout_seconds = 0.01
    request = AsyncMock(side_effect=lambda request: None)

    async def slow(request):
        await asyncio.Event().wait()

    request.side_effect = slow
    monkeypatch.setattr(c.provider, "request", request)
    fallback = AsyncMock(return_value={"query": False})
    assert await asyncio.wait_for(query_gate(c, fallback), 1) == {"query": False}
    request.assert_awaited_once()
    fallback.assert_awaited_once_with(["query"])
    record = next(iter(c.service.log.records.values()))
    assert record.failure.code == "timeout"


async def test_cancelled_decision_does_not_fallback(gate_case, monkeypatch):
    c = gate_case

    async def cancel(request):
        c.scene.cancel_requested = True
        await asyncio.Event().wait()

    monkeypatch.setattr(c.provider, "request", cancel)
    fallback = AsyncMock(return_value={"query": False})
    with pytest.raises(GenerationCancelled):
        await asyncio.wait_for(query_gate(c, fallback), 1)
    fallback.assert_not_awaited()


@pytest.mark.parametrize(
    "source",
    [
        "{{ missing() }}",
        "{{ decision_result({}) }}",
        '{{ decision_result({"query": "false"}) }}',
        '{{ decision_result({"query": 0}) }}',
        '{{ decision_result({"query": none}) }}',
        '{{ decision_result({"other": false}) }}',
        '{{ decision_result({"query": false, "extra": true}) }}',
        '{{ decision_result(agent_action("gate", "resolve", answers={"unknown": true})) }}',
        '{{ decision_result(agent_action("gate", "resolve")) }}',
        '{{ decision_result(agent_action("gate", "resolve", unknown=true)) }}',
    ],
)
async def test_invalid_policy_uses_original_path(gate_case, tmp_path, source):
    (tmp_path / "decision-query.jinja2").write_text(source)
    fallback = AsyncMock(return_value={"query": False})
    with PrependTemplateDirectories(str(tmp_path)):
        assert await query_gate(gate_case, fallback) == {"query": False}
    fallback.assert_awaited_once_with(["query"])


@pytest.mark.parametrize("answer", [None, True, False])
async def test_template_error_after_resolution_preserves_result(
    gate_case, tmp_path, answer
):
    source = (
        '{{ agent_action("gate", "resolve", answers={"query": '
        + {None: "none", True: "true", False: "false"}[answer]
        + "}) }}{{ missing() }}"
    )
    (tmp_path / "decision-query.jinja2").write_text(source)
    fallback = AsyncMock(return_value={"query": False})
    with PrependTemplateDirectories(str(tmp_path)):
        assert await query_gate(gate_case, fallback) == {
            "query": answer if answer is not None else False
        }
    assert fallback.await_count == (answer is None)


@pytest.mark.parametrize("direct", ["{}", '{"query": "false"}', "none"])
@pytest.mark.parametrize("answer", [None, True, False])
async def test_malformed_direct_result_after_action_preserves_resolution(
    gate_case, tmp_path, direct, answer
):
    route = {None: "none", True: "true", False: "false"}[answer]
    source = (
        '{{ agent_action("gate", "resolve", answers={"query": '
        + route
        + "}) }}{{ decision_result("
        + direct
        + ") }}"
    )
    (tmp_path / "decision-query.jinja2").write_text(source)
    fallback = AsyncMock(return_value={"query": False})
    with PrependTemplateDirectories(str(tmp_path)):
        assert await query_gate(gate_case, fallback) == {
            "query": answer if answer is not None else False
        }
    assert fallback.await_count == (answer is None)


@pytest.mark.parametrize(
    "source",
    [
        "{{ decision_result({}) }}",
        '{{ decision_result(agent_action("gate", "resolve", answers={"state": none})) }}',
        '{{ agent_action("gate", "resolve", answers={"state": none}) }}{{ decision_result({}) }}',
    ],
)
async def test_opaque_fallback_results_survive_policy_recovery(
    gate_case, tmp_path, source
):
    from talemate.scene_message import ReinforcementMessage

    message = ReinforcementMessage("An opaque fallback result.")
    fallback = AsyncMock(return_value={"state": message})
    (tmp_path / "decision-reinforcement.jinja2").write_text(source)
    with PrependTemplateDirectories(str(tmp_path)):
        result = await decision_gate(
            "world_state.decision-reinforcement",
            enabled=True,
            candidates={"state": [False]},
            variables=lambda: {},
            fallback=fallback,
        )
    assert result["state"] is message
    fallback.assert_awaited_once_with(["state"])


@pytest.mark.parametrize(
    "edit", ['result.update({"Mara": "false"})', 'result.pop("Mara")']
)
@pytest.mark.parametrize(
    "finalization", ["before_edit", "after_edit", "error_after_edit"]
)
@pytest.mark.parametrize("use_fallback", [False, True])
async def test_resolved_mapping_survives_template_edits(
    gate_case, tmp_path, edit, finalization, use_fallback
):
    from talemate.scene_message import ReinforcementMessage

    message = ReinforcementMessage("An opaque fallback result.")
    fallback = AsyncMock(return_value={"Mara": message})
    route = "none" if use_fallback else "false"
    source = (
        '{% set result = agent_action("gate", "resolve", answers={"Mara": '
        + route
        + "}) %}"
    )
    if finalization == "before_edit":
        source += "{{ decision_result(result) }}"
    source += "{% set unused = " + edit + " %}"
    if finalization == "after_edit":
        source += "{{ decision_result(result) }}"
    elif finalization == "error_after_edit":
        source += "{{ missing() }}"
    (tmp_path / "decision-query.jinja2").write_text(source)

    with PrependTemplateDirectories(str(tmp_path)):
        result = await decision_gate(
            "world_state.decision-query",
            enabled=True,
            candidates={"Mara": [True, False]},
            variables=lambda: {},
            fallback=fallback,
        )

    assert result.keys() == {"Mara"}
    assert result["Mara"] is (message if use_fallback else False)
    if use_fallback:
        fallback.assert_awaited_once_with(["Mara"])
    else:
        fallback.assert_not_awaited()
    invocation = next(iter(gate_case.service.log.invocations.values()))
    assert len(invocation.actions) == 1
    assert invocation.status == (
        "preserved" if finalization == "error_after_edit" else "completed"
    )


@pytest.mark.parametrize(
    "source",
    [
        "{{ decision_result({}) }}",
        '{{ decision_result(agent_action("gate", "resolve", answers={"query": none})) }}',
    ],
)
async def test_original_failure_is_raised_without_replay(gate_case, tmp_path, source):
    (tmp_path / "decision-query.jinja2").write_text(source)
    fallback = AsyncMock(side_effect=RuntimeError("Original request failed"))
    with PrependTemplateDirectories(str(tmp_path)):
        with pytest.raises(RuntimeError, match="Original request failed"):
            await query_gate(gate_case, fallback)
    fallback.assert_awaited_once_with(["query"])
