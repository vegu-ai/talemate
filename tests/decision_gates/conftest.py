from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from talemate.context import ActiveScene
from talemate.decisions import DecisionService, ProviderResponse
from talemate.instance import get_agent

from _decision_test_helpers import FakeDecisionProvider


class GateProvider(FakeDecisionProvider):
    def __init__(self):
        super().__init__()
        self.answers = {}
        self.error = None

    def respond(self, request):
        if self.error:
            raise self.error
        return ProviderResponse(
            answers={
                key: self.answers.get(key, {"type": "noul", "p_true": 0.5})
                for key in request.questions
            },
            response_body={},
        )


@pytest.fixture
def gate_case(scene, monkeypatch):
    from talemate.decisions import gate

    scene.active = True
    provider = GateProvider()
    service = DecisionService(provider, enabled=True, timeout_seconds=1)
    monkeypatch.setattr(gate, "decision_service", service)
    monkeypatch.setattr(scene, "load_active_pins", AsyncMock())
    with ActiveScene(scene):
        yield SimpleNamespace(
            scene=scene,
            provider=provider,
            service=service,
            agent=get_agent("world_state"),
            memory=get_agent("memory"),
        )
