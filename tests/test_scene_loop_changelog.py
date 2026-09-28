"""The scene loop end records the changelog like a save: a change that no
delta can record shows an error and does not stop the loop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import talemate.game.engine.nodes.scene as scene_nodes
from talemate.context import ActiveScene
from talemate.emit import async_signals


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded", [True, False])
async def test_loop_end_shows_an_error_and_finishes_the_loop(
    scene, monkeypatch, recorded
):
    shown = []
    monkeypatch.setattr(
        scene_nodes,
        "emit",
        lambda typ, *args, **kwargs: shown.append((typ, kwargs.get("status"))),
    )
    monkeypatch.setattr(type(scene), "auto_save", property(lambda self: False))
    scene._changelog = object()
    monkeypatch.setattr(
        scene, "append_changelog_delta", AsyncMock(return_value=recorded)
    )
    monkeypatch.setattr(
        scene,
        "emit_status",
        lambda *args, **kwargs: shown.append(("emit_status", None)),
    )
    ended = []

    async def end_cycle(event):
        ended.append(event)

    signal = async_signals.get("scene_loop_end_cycle")
    signal.connect(end_cycle)
    try:
        state = SimpleNamespace(outer=SimpleNamespace(data={"scene": scene}))
        with ActiveScene(scene):
            await scene_nodes.SceneLoop().on_loop_end(state)
    finally:
        signal.disconnect(end_cycle)

    assert (("status", "error") in shown) is not recorded
    assert ("emit_status", None) in shown
    assert len(ended) == 1


@pytest.mark.asyncio
async def test_append_changelog_delta_catches_only_the_delta_error(scene):
    from talemate.changelog import ChangelogDeltaError

    scene._changelog = SimpleNamespace(
        append_delta=AsyncMock(side_effect=ChangelogDeltaError("no replay"))
    )
    assert await scene.append_changelog_delta() is False

    scene._changelog = SimpleNamespace(append_delta=AsyncMock(side_effect=OSError))
    with pytest.raises(OSError):
        await scene.append_changelog_delta()

    scene._changelog = SimpleNamespace(append_delta=AsyncMock(return_value=1))
    assert await scene.append_changelog_delta() is True
