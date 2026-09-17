"""Tests for the AnalyzeImages node and the analysis concurrency gate.

The node must await actual analysis completion (not just task launches) and
bound concurrency to what the analysis backend supports — sequential when the
backend routes through a client without `supports_concurrent_inference`.
"""

import asyncio
from types import SimpleNamespace

import pydantic
import pytest

import talemate.instance as instance
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.backends import Backend
from talemate.agents.visual.backends.openai_compatible import (
    Backend as OpenAICompatibleBackend,
)
from talemate.agents.visual.backends.talemate_client import (
    Backend as TalemateClientBackend,
)
from talemate.exceptions import GenerationCancelled
from talemate.agents.visual.nodes import AnalyzeImages
from talemate.agents.visual.schema import BackendStatus, BackendStatusType

from _node_test_helpers import run_node


class FakeAnalysisBackend(Backend):
    name = "fake"
    label = "Fake"
    image_create = False
    image_edit = False
    image_analyzation = True
    description = "Fake analysis backend for tests."

    status: BackendStatus = pydantic.Field(
        default_factory=lambda: BackendStatus(type=BackendStatusType.OK)
    )
    supports_concurrent: bool = True
    fail_ids: set[str] = pydantic.Field(default_factory=set)
    cancel_ids: set[str] = pydantic.Field(default_factory=set)
    delay: float = 0.01
    in_flight: int = 0
    max_in_flight: int = 0
    completed: list[str] = pydantic.Field(default_factory=list)

    @property
    def supports_concurrent_analysis(self) -> bool:
        return self.supports_concurrent

    async def analyze(self, request, response):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        if request.asset_id in self.cancel_ids:
            raise asyncio.CancelledError()
        if request.asset_id in self.fail_ids:
            raise RuntimeError(f"analysis failed for {request.asset_id}")
        self.completed.append(request.asset_id)
        response.analysis = f"analysis of {request.asset_id}"
        return response


class FakeAssets:
    def __init__(self, asset_ids):
        self.assets = {
            asset_id: SimpleNamespace(meta=SimpleNamespace(analysis=None))
            for asset_id in asset_ids
        }
        self.updated_meta = {}

    def get_asset(self, asset_id):
        return self.assets[asset_id]

    def update_asset_meta(self, asset_id, meta):
        self.updated_meta[asset_id] = meta


class FakeScene:
    def __init__(self, asset_ids, cancel_on_action=None):
        self.assets = FakeAssets(asset_ids)
        self.saved = True
        self.agent_overrides = None
        # mirrors Scene.continue_actions consuming the cancel latch: the
        # n-th @set_processing entry raises GenerationCancelled
        self.cancel_on_action = cancel_on_action
        self.action_count = 0
        self.cancel_sequence = 0

    def continue_actions(self):
        self.action_count += 1
        if self.cancel_on_action and self.action_count >= self.cancel_on_action:
            self.cancel_sequence += 1
            raise GenerationCancelled("action cancelled", by_user=True)

    def emit_status(self):
        pass


@pytest.fixture
def visual_agent():
    agent = VisualAgent()
    instance.AGENTS["visual"] = agent
    yield agent
    instance.AGENTS.pop("visual", None)


async def run_analyze_images(scene, asset_ids, **inputs):
    node = AnalyzeImages()
    return await run_node(
        node,
        scene=scene,
        inputs={
            "state": {},
            "asset_ids": asset_ids,
            "missing_only": False,
            "prompt": "Describe.",
            "save": True,
            **inputs,
        },
    )


async def test_concurrent_backend_bounded_at_three(visual_agent):
    backend = FakeAnalysisBackend(supports_concurrent=True)
    visual_agent.backend_image_analyzation = backend
    asset_ids = [f"asset-{i}" for i in range(6)]
    scene = FakeScene(asset_ids)

    outputs = await run_analyze_images(scene, asset_ids)

    assert sorted(outputs["analyzed_ids"]) == asset_ids
    assert outputs["failed_ids"] == []
    assert backend.max_in_flight == 3


async def test_unsupported_backend_runs_sequentially(visual_agent):
    backend = FakeAnalysisBackend(supports_concurrent=False)
    visual_agent.backend_image_analyzation = backend
    asset_ids = [f"asset-{i}" for i in range(4)]
    scene = FakeScene(asset_ids)

    outputs = await run_analyze_images(scene, asset_ids)

    assert sorted(outputs["analyzed_ids"]) == asset_ids
    assert backend.max_in_flight == 1


async def test_node_awaits_analysis_completion(visual_agent):
    # regression pin: agent.analyze used to be fire-and-forget, so the node
    # finished (and reported success) while backend calls were still running
    backend = FakeAnalysisBackend(supports_concurrent=True)
    visual_agent.backend_image_analyzation = backend
    asset_ids = [f"asset-{i}" for i in range(3)]
    scene = FakeScene(asset_ids)

    outputs = await run_analyze_images(scene, asset_ids)

    assert sorted(backend.completed) == asset_ids
    assert backend.in_flight == 0
    assert sorted(outputs["analyzed_ids"]) == asset_ids
    for asset_id in asset_ids:
        assert (
            scene.assets.get_asset(asset_id).meta.analysis == f"analysis of {asset_id}"
        )


async def test_failed_analysis_lands_in_failed_ids(visual_agent):
    backend = FakeAnalysisBackend(supports_concurrent=True, fail_ids={"asset-1"})
    visual_agent.backend_image_analyzation = backend
    asset_ids = ["asset-0", "asset-1", "asset-2"]
    scene = FakeScene(asset_ids)

    outputs = await run_analyze_images(scene, asset_ids)

    assert sorted(outputs["analyzed_ids"]) == ["asset-0", "asset-2"]
    assert outputs["failed_ids"] == ["asset-1"]
    assert scene.assets.get_asset("asset-1").meta.analysis is None


async def test_cancelled_analysis_stops_the_batch(visual_agent):
    # cancel_analysis cancels in-flight backend tasks; the queued assets must
    # not launch fresh analyses, and the bare CancelledError must leave the
    # node as GenerationCancelled - the interrupt the graph engine handles
    backend = FakeAnalysisBackend(supports_concurrent=False, cancel_ids={"asset-0"})
    visual_agent.backend_image_analyzation = backend
    asset_ids = [f"asset-{i}" for i in range(3)]
    scene = FakeScene(asset_ids)

    with pytest.raises(GenerationCancelled):
        await run_analyze_images(scene, asset_ids)

    await asyncio.sleep(0)
    assert backend.completed == []


async def test_consumed_cancel_latch_stops_the_batch(visual_agent):
    # @set_processing's continue_actions() consumes the user-cancel latch and
    # raises GenerationCancelled on entry - a per-asset except must not
    # swallow it, or every queued asset runs post-cancel
    backend = FakeAnalysisBackend(supports_concurrent=False)
    visual_agent.backend_image_analyzation = backend
    asset_ids = [f"asset-{i}" for i in range(3)]
    scene = FakeScene(asset_ids, cancel_on_action=2)

    with pytest.raises(GenerationCancelled):
        await run_analyze_images(scene, asset_ids)

    await asyncio.sleep(0)
    assert backend.completed == ["asset-0"]


async def test_external_task_cancel_propagates_bare(visual_agent):
    # scene unload / module test-stop cancel the node's own task - that
    # cancellation must stay a bare CancelledError so RunModule's
    # cancelling() guard and the scene loop see it
    backend = FakeAnalysisBackend(supports_concurrent=False, delay=0.5)
    visual_agent.backend_image_analyzation = backend
    asset_ids = [f"asset-{i}" for i in range(3)]
    scene = FakeScene(asset_ids)

    task = asyncio.create_task(run_analyze_images(scene, asset_ids))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()


async def test_missing_only_skips_analyzed_assets(visual_agent):
    backend = FakeAnalysisBackend(supports_concurrent=True)
    visual_agent.backend_image_analyzation = backend
    asset_ids = ["asset-0", "asset-1"]
    scene = FakeScene(asset_ids)
    scene.assets.get_asset("asset-0").meta.analysis = "already analyzed"

    outputs = await run_analyze_images(scene, asset_ids, missing_only=True)

    assert outputs["analyzed_ids"] == ["asset-1"]
    assert outputs["skipped_ids"] == ["asset-0"]


class TestTalemateClientBackendGate:
    def test_no_client_selected(self):
        backend = TalemateClientBackend(client_name=None)
        assert backend.supports_concurrent_analysis is False

    def test_client_not_instantiated(self):
        backend = TalemateClientBackend(client_name="missing-client")
        assert backend.supports_concurrent_analysis is False

    @pytest.mark.parametrize("supported", [True, False])
    def test_delegates_to_client(self, supported):
        backend = TalemateClientBackend(client_name="vision-client")
        instance.CLIENTS["vision-client"] = SimpleNamespace(
            supports_concurrent_inference=supported
        )
        try:
            assert backend.supports_concurrent_analysis is supported
        finally:
            instance.CLIENTS.pop("vision-client", None)


def test_backend_base_defaults_to_concurrent():
    from talemate.agents.visual.backends import Backend

    class DirectAPI(Backend):
        name = "direct-api-test"
        label = "Direct API"

    assert DirectAPI().supports_concurrent_analysis is True


def test_openai_compatible_backend_concurrency_is_opt_in():
    assert OpenAICompatibleBackend().supports_concurrent_analysis is False
    assert (
        OpenAICompatibleBackend(concurrent_requests=True).supports_concurrent_analysis
        is True
    )
