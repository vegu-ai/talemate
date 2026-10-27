import asyncio

import pytest

import talemate.agents.visual.generation as generation_module
import talemate.emit.async_signals as async_signals
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.nodes import GenerationRunning
from talemate.agents.visual.schema import GenerationRequest
from talemate.context import active_scene
from talemate.game.engine.nodes.core import InputValueError

from _node_test_helpers import run_node
from conftest import MockScene

PURPOSE = "world_state.scene_background"


class GatedBackend:
    name = "gated"

    def __init__(self):
        self.release = asyncio.Event()
        self.error: BaseException | None = None

    async def generate(self, request, response):
        await self.release.wait()
        if self.error:
            raise self.error
        return response

    async def cancel_request(self):
        pass


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(generation_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: True))
    monkeypatch.setattr(VisualAgent, "backend", None, raising=False)
    agent = VisualAgent()
    agent.backend = GatedBackend()

    async def no_finalize(request):
        pass

    async def no_status(*args, **kwargs):
        pass

    monkeypatch.setattr(agent, "finalize_prompt_request", no_finalize)
    monkeypatch.setattr(agent, "emit_status", no_status)
    return agent


@pytest.fixture
def active(scene):
    token = active_scene.set(scene)
    yield scene
    active_scene.reset(token)


@pytest.fixture
def failures():
    received = []

    async def on_failed(emission):
        received.append(emission)

    async_signals.get("agent.visual.generation.failed").connect(on_failed)
    yield received
    async_signals.get("agent.visual.generation.failed").disconnect(on_failed)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_generation_counts_as_running_until_its_result_is_handled(
    agent, active
):
    handled = asyncio.Event()

    async def callback(response):
        assert agent.generations_running(PURPOSE) == 1
        handled.set()

    await agent.generate(GenerationRequest(purpose=PURPOSE, callback=callback))

    assert agent.generations_running(PURPOSE) == 1
    assert agent.generations_running("other.purpose") == 0

    agent.backend.release.set()
    await asyncio.wait_for(handled.wait(), 1)
    await settle()

    assert agent.generations_running(PURPOSE) == 0


async def test_a_running_generation_belongs_to_its_scene(agent, active):
    await agent.generate(GenerationRequest(purpose=PURPOSE))

    assert agent.generations_running(PURPOSE, scene=MockScene()) == 0
    assert agent.generations_running(PURPOSE, scene=active) == 1

    agent.backend.release.set()
    await settle()


async def test_a_failed_generation_stops_running_and_is_signalled(
    agent, active, failures
):
    agent.backend.error = ValueError("backend refused")
    request = GenerationRequest(purpose=PURPOSE)
    await agent.generate(request)

    agent.backend.release.set()
    await settle()

    assert agent.generations_running(PURPOSE) == 0
    assert [(f.request.id, f.error, f.cancelled) for f in failures] == [
        (request.id, "backend refused", False)
    ]


async def test_a_cancelled_generation_stops_running_and_is_signalled(
    agent, active, failures
):
    request = GenerationRequest(purpose=PURPOSE)
    await agent.generate(request)

    await agent.cancel_generation()
    await settle()

    assert agent.generations_running(PURPOSE) == 0
    assert [(f.request.id, f.cancelled) for f in failures] == [(request.id, True)]


async def test_a_generation_failing_before_its_image_task_is_signalled(
    agent, active, failures, monkeypatch
):
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: False))
    request = GenerationRequest(purpose=PURPOSE)

    with pytest.raises(Exception):
        await agent.generate(request)

    assert agent.generations_running(PURPOSE) == 0
    assert [f.request.id for f in failures] == [request.id]


async def test_generation_running_node_reports_the_purpose(agent, active, monkeypatch):
    await agent.generate(GenerationRequest(purpose=PURPOSE))
    monkeypatch.setattr(GenerationRunning, "agent", property(lambda s: agent))

    outputs = await run_node(GenerationRunning(), inputs={"purpose": PURPOSE})
    assert (outputs["running"], outputs["count"]) == (True, 1)

    outputs = await run_node(GenerationRunning(), inputs={"purpose": "other.purpose"})
    assert (outputs["running"], outputs["count"]) == (False, 0)

    with pytest.raises(InputValueError):
        await run_node(GenerationRunning(), inputs={"purpose": ""})

    agent.backend.release.set()
    await settle()
