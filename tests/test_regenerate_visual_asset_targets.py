"""Revisualize attaches the new image to the clicked passage, except for a
scene background, which becomes a Backdrop entry at the end of the story."""

import pytest

from talemate.agents.visual.schema import VIS_TYPE
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphState
from talemate.game.engine.nodes.registry import get_node
from talemate.game.engine.nodes.run import FunctionWrapper
from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
from talemate.scene_assets import Asset, AssetMeta


async def run_revisualize(scene, monkeypatch, data: dict):
    ensure_registry_loaded()
    handler = get_node("agents/visual/wshRegenerateVisualAsset")()
    regenerate = next(
        node
        for node in handler.nodes.values()
        if node.registry == "agents/visual/regenerateVisualAsset"
    )
    contexts = []

    async def capture(node, state):
        contexts.append(node.get_input_value("asset_ctx"))

    monkeypatch.setattr(type(regenerate), "run", capture)
    with ActiveScene(scene):
        await FunctionWrapper(handler, handler, GraphState())(
            websocket_router=None, data=data
        )
    assert len(contexts) == 1
    return contexts[0]


@pytest.mark.parametrize(
    "vis_type, expected",
    [
        (VIS_TYPE.SCENE_ILLUSTRATION, [7]),
        (VIS_TYPE.CHARACTER_PORTRAIT, [7]),
        (VIS_TYPE.CHARACTER_CARD, [7]),
        (VIS_TYPE.SCENE_BACKGROUND, []),
    ],
)
async def test_revisualize_targets_the_clicked_passage(
    scene, monkeypatch, vis_type, expected
):
    scene.assets.save_asset(
        Asset(
            id="clicked",
            file_type="png",
            media_type="image/png",
            meta=AssetMeta(vis_type=vis_type),
        )
    )

    ctx = await run_revisualize(
        scene,
        monkeypatch,
        {
            "asset_id": "clicked",
            "asset_allow_override": True,
            "asset_allow_auto_attach": True,
            "asset_delete_old": True,
            "message_ids": [7],
        },
    )

    assert ctx.message_ids == expected
    assert ctx.allow_override and ctx.allow_auto_attach and ctx.delete_old


async def test_revisualize_without_a_passage_attaches_to_the_latest(scene, monkeypatch):
    scene.assets.save_asset(
        Asset(
            id="clicked",
            file_type="png",
            media_type="image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.SCENE_ILLUSTRATION),
        )
    )

    ctx = await run_revisualize(
        scene, monkeypatch, {"asset_id": "clicked", "asset_allow_auto_attach": True}
    )

    assert ctx.message_ids == []
