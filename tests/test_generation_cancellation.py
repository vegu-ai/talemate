import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from talemate.agents.base import set_processing
from talemate.context import ActiveScene, handle_generation_cancelled
from talemate.exceptions import GenerationCancelled
from talemate.game.engine.nodes.core import LoopBreak
from talemate.game.engine.nodes.scene import SceneLoop
from talemate.game.scope import GameInstructionScope
from talemate.instance import get_agent
from talemate.status import set_loading


@pytest.fixture
def cancellation_emissions(monkeypatch):
    emissions = []

    def record(typ, *args, **kwargs):
        emissions.append((typ, kwargs))

    monkeypatch.setattr("talemate.emit.emit", record)
    monkeypatch.setattr("talemate.status.emit", record)
    return emissions


@pytest.mark.asyncio
@pytest.mark.parametrize("sink", ["scene_loop", "scope", "game", "creative", "loading"])
@pytest.mark.parametrize(
    "cause", ["system", "user_flag", "consumed_flag", "user_dialog"]
)
async def test_cancellation_sinks_report_system_abort_once_and_keep_user_silent(
    scene, monkeypatch, cancellation_emissions, sink, cause
):
    exc = GenerationCancelled(
        "Perception for passage 17 is pending",
        by_user=cause == "user_dialog",
        message_id=17,
        view_status="pending",
        character="Alice",
    )
    if cause in ("user_flag", "consumed_flag"):
        scene.interrupt()
    if cause == "consumed_flag":
        with pytest.raises(GenerationCancelled) as raised:
            scene.continue_actions()
        exc = raised.value
        assert not scene.cancel_requested

    with ActiveScene(scene), capture_logs() as logs:
        if sink == "scene_loop":
            state = SimpleNamespace(
                outer=SimpleNamespace(data={"scene": scene}), shared={}
            )
            with pytest.raises(LoopBreak):
                await SceneLoop().on_loop_error(state, exc)
            assert state.shared == {"skip_to_player": True, "signal_game_loop": False}
        elif sink == "scope":

            def module(scope):
                raise exc

            scope = GameInstructionScope.__new__(GameInstructionScope)
            scope.module_function = module
            scope.on_generation_cancelled = None
            assert scope() is None
        elif sink == "loading":

            @set_loading("Generating")
            async def generate():
                raise exc

            with pytest.raises(GenerationCancelled):
                await generate()
        else:

            async def execute(state):
                state.data["continue_scene"] = False
                raise exc

            scene.active = True
            monkeypatch.setattr(scene, "emit_history", AsyncMock())
            graph = SimpleNamespace(execute=execute)
            scene.node_graph = scene.creative_node_graph = graph
            if sink == "game":
                await scene._run_game_loop(init=False)
            else:
                await scene._run_creative_loop(init=False)

        handle_generation_cancelled(exc)

    warnings = [entry for entry in logs if entry["log_level"] == "warning"]
    statuses = [
        data for typ, data in cancellation_emissions if data.get("status") == "warning"
    ]
    assert not scene.cancel_requested
    if cause == "system":
        assert len(warnings) == len(statuses) == 1
        assert warnings[0] == {
            "event": "Generation aborted",
            "log_level": "warning",
            "reason": str(exc),
            "message_id": 17,
            "view_status": "pending",
            "character": "Alice",
        }
        assert statuses[0]["message"] == str(exc)
        assert statuses[0]["data"] == {
            "message_id": 17,
            "view_status": "pending",
            "character": "Alice",
        }
    else:
        assert warnings == statuses == []


@pytest.mark.asyncio
async def test_action_preserves_consumed_user_cancel(
    scene, monkeypatch, cancellation_emissions
):
    agent = get_agent("summarizer")
    monkeypatch.setattr(agent, "emit_status", AsyncMock())
    entered, release = asyncio.Event(), asyncio.Event()

    @set_processing
    async def action(self):
        entered.set()
        await release.wait()
        raise GenerationCancelled("Non-LLM operation stopped")

    with ActiveScene(scene), capture_logs() as logs:
        task = asyncio.create_task(action(agent))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            scene.interrupt()
            scene.cancel_requested = False
            release.set()
            with pytest.raises(GenerationCancelled) as raised:
                await asyncio.wait_for(task, 2)
            assert raised.value.by_user
            handle_generation_cancelled(raised.value)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    assert not [entry for entry in logs if entry["log_level"] == "warning"]
    assert not [
        data for _, data in cancellation_emissions if data.get("status") == "warning"
    ]
