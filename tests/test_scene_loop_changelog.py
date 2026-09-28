from unittest.mock import AsyncMock

import pytest

from talemate.context import ActiveScene
from talemate.game.engine.nodes.scene import SceneLoop
from talemate.game.engine.nodes.core import GraphState


@pytest.mark.parametrize("auto_save", [True, False])
async def test_loop_end_saves_once_without_staging_an_extra_revision(
    scene, monkeypatch, auto_save
):
    monkeypatch.setattr(type(scene), "auto_save", property(lambda self: auto_save))
    scene.save = AsyncMock()
    loop = SceneLoop()
    state = GraphState(outer=GraphState(data={"scene": scene}))
    with ActiveScene(scene):
        await loop.on_loop_end(state)
    if auto_save:
        scene.save.assert_awaited_once_with(auto=True)
    else:
        scene.save.assert_not_awaited()
