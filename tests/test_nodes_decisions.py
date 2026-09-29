"""
Decision model nodes: AskDecisionModel, DecideYesNo and DecisionModelStatus.
"""

import asyncio

import pytest

from _decision_test_helpers import FakeDecisionProvider
from _node_test_helpers import run_node
from talemate.decisions import DecisionService, ProviderResponse
from talemate.decisions.slot import DecisionModelSlotStatus
from talemate.game.engine.nodes import decisions as decision_nodes
from talemate.game.engine.nodes.core import Graph, GraphContext, InputValueError
from talemate.game.engine.nodes.decisions import (
    AskDecisionModel,
    DecideYesNo,
    DecisionModelStatus,
)


class AnswerProvider(FakeDecisionProvider):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer

    def respond(self, request):
        return ProviderResponse(
            answers={key: self.answer for key in request.questions},
            response_body={},
        )


def use_service(monkeypatch, answer=None, *, enabled=True):
    provider = AnswerProvider(answer)
    service = DecisionService(provider, enabled=enabled, timeout_seconds=1)
    monkeypatch.setattr(decision_nodes, "decision_service", service)
    return service, provider


class TestAskDecisionModel:
    @pytest.mark.asyncio
    async def test_yes_no_answer(self, monkeypatch):
        service, provider = use_service(monkeypatch, {"type": "noul", "p_true": 0.8})
        out = await run_node(
            AskDecisionModel(),
            inputs={
                "subject": "Mara looks away when she answers.",
                "instructions": "Is Mara lying?",
                "true_criteria": "She hides the truth.",
                "label": "Lie check",
            },
        )
        assert out["available"] is True
        assert out["failure_code"] is None
        assert out["p_true"] == 0.8
        assert out["answer"] == {"type": "noul", "p_true": 0.8}
        request = provider.calls[0]
        assert request.state == "Mara looks away when she answers."
        question = request.questions["question"]
        assert question.instructions == "Is Mara lying?"
        assert question.true_criteria == "She hides the truth."
        assert question.false_criteria is None
        record = service.log.records[out["request_id"]]
        assert record.label == "Lie check"
        assert record.template_uid == "node_editor.decision"

    @pytest.mark.asyncio
    async def test_choice_answer(self, monkeypatch):
        use_service(
            monkeypatch,
            {
                "type": "choice",
                "selected": "flee",
                "probabilities": {"flee": 0.7, "fight": 0.3},
                "confidence": 0.7,
            },
        )
        out = await run_node(
            AskDecisionModel(),
            inputs={
                "question_type": "choice",
                "subject": {"threat": "wolves"},
                "instructions": "What does Bob do?",
                "options": {"flee": "Bob runs", "fight": "Bob fights"},
            },
        )
        assert out["selected"] == "flee"
        assert out["probabilities"] == {"flee": 0.7, "fight": 0.3}
        assert out["confidence"] == 0.7
        assert out["p_true"] is None

    @pytest.mark.asyncio
    async def test_score_answer(self, monkeypatch):
        use_service(
            monkeypatch,
            {
                "type": "score",
                "value": 1.5,
                "probabilities": [0.1, 0.3, 0.6],
                "legend": ["calm", "tense", "hostile"],
                "confidence": 0.6,
            },
        )
        out = await run_node(
            AskDecisionModel(),
            inputs={
                "question_type": "score",
                "instructions": "How hostile is the crowd?",
                "rubric": ["calm", "tense", "hostile"],
            },
        )
        assert out["value"] == 1.5
        assert out["probabilities"] == [0.1, 0.3, 0.6]

    @pytest.mark.asyncio
    async def test_decision_model_off_gives_no_answer_without_raising(
        self, monkeypatch
    ):
        _, provider = use_service(monkeypatch, enabled=False)
        out = await run_node(
            AskDecisionModel(), inputs={"instructions": "Is it raining?"}
        )
        assert out["available"] is False
        assert out["failure_code"] == "disabled"
        assert out["p_true"] is None
        assert out["request_id"]
        assert provider.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "inputs, socket",
        [
            ({"instructions": "  "}, "instructions"),
            (
                {
                    "question_type": "choice",
                    "instructions": "Which?",
                    "options": {"a": "A"},
                },
                "options",
            ),
            (
                {"question_type": "score", "instructions": "How?", "rubric": ["low"]},
                "rubric",
            ),
        ],
    )
    async def test_incomplete_question_is_refused_before_a_request(
        self, monkeypatch, inputs, socket
    ):
        _, provider = use_service(monkeypatch, {"type": "noul", "p_true": 0.5})
        with pytest.raises(InputValueError) as exc:
            await run_node(AskDecisionModel(), inputs=inputs)
        assert exc.value.input_name == socket
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self, monkeypatch):
        _, provider = use_service(monkeypatch)

        async def cancelled(request):
            raise asyncio.CancelledError()

        provider.handler = cancelled
        with pytest.raises(asyncio.CancelledError):
            await run_node(AskDecisionModel(), inputs={"instructions": "Now?"})


class TestDecideYesNo:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "p_true, threshold, route",
        [
            (0.95, 0.9, "yes"),
            (0.05, 0.9, "no"),
            (0.7, 0.9, "uncertain"),
            (0.7, 0.6, "yes"),
        ],
    )
    async def test_routes_on_threshold(self, monkeypatch, p_true, threshold, route):
        use_service(monkeypatch, {"type": "noul", "p_true": p_true})
        out = await run_node(
            DecideYesNo(),
            inputs={"instructions": "Is the door open?", "threshold": threshold},
        )
        for name in ("yes", "no", "uncertain"):
            assert out[f"{name}__deactivated"] is (name != route)
        assert out[route] is True
        assert out["p_true"] == p_true
        assert out["failure_code"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("enabled", [True, False])
    @pytest.mark.parametrize("node_class", [AskDecisionModel, DecideYesNo])
    async def test_state_passes_through_unchanged(
        self, monkeypatch, node_class, enabled
    ):
        _, provider = use_service(
            monkeypatch, {"type": "noul", "p_true": 0.95}, enabled=enabled
        )
        state = {"door": "open", "keys": ["brass"]}
        out = await run_node(
            node_class(), inputs={"state": state, "instructions": "Is it open?"}
        )
        assert out["state"] is state
        assert state == {"door": "open", "keys": ["brass"]}
        # state only activates the node; it is not the subject of the question
        assert [call.state for call in provider.calls] == ([""] if enabled else [])

    @pytest.mark.parametrize("node_class", [AskDecisionModel, DecideYesNo])
    def test_no_request_without_a_state(self, node_class):
        # a required state lets the graph decide when the question is sent
        node = node_class()
        graph = Graph()
        graph.add_node(node)
        with GraphContext() as state:
            assert node.check_is_available(state) is False
            node.set_property("state", "The door is open.")
            for socket in node.outputs:
                socket.deactivated = False
            assert node.check_is_available(state) is True

    @pytest.mark.asyncio
    async def test_no_answer_routes_to_uncertain(self, monkeypatch):
        use_service(monkeypatch, enabled=False)
        out = await run_node(DecideYesNo(), inputs={"instructions": "Open?"})
        assert out["uncertain"] is True
        assert out["yes__deactivated"] and out["no__deactivated"]
        assert out["failure_code"] == "disabled"
        assert out["p_true"] is None

    @pytest.mark.asyncio
    async def test_threshold_below_half_is_refused(self, monkeypatch):
        use_service(monkeypatch, {"type": "noul", "p_true": 0.5})
        with pytest.raises(InputValueError):
            await run_node(
                DecideYesNo(), inputs={"instructions": "Open?", "threshold": 0.4}
            )


class TestDecisionModelStatus:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status, provider_ready, ready",
        [
            ({"enabled": True, "state": "ready"}, True, True),
            ({"enabled": True, "state": "ready"}, False, False),
            ({"enabled": True, "state": "incomplete"}, True, False),
            ({"enabled": False, "state": "disabled"}, True, False),
        ],
    )
    async def test_status(self, monkeypatch, status, provider_ready, ready):
        service, provider = use_service(monkeypatch)
        provider.ready = provider_ready
        monkeypatch.setattr(
            decision_nodes,
            "decision_model_status",
            lambda: DecisionModelSlotStatus(
                **status,
                provider="openrouter",
                model="any-model-name",
                timeout_seconds=1.5,
                missing=[],
                last_failure=None,
            ),
        )
        out = await run_node(DecisionModelStatus())
        assert out["ready"] is ready
        assert out["enabled"] is status["enabled"]
        assert out["status"] == status["state"]
        assert out["provider"] == "openrouter"
        assert out["model"] == "any-model-name"
