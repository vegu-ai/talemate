from unittest.mock import AsyncMock

import pytest

from _node_test_helpers import run_node
from talemate.agents.world_state import WorldStateAgent
from talemate.agents.world_state.nodes import DetermineVisual
from talemate.game.engine.nodes.assets import (
    MakeAssetAttachmentContext,
    SetSceneBackdrop,
)
from talemate.game.engine.nodes.core import InputValueError
from talemate.prompts import Prompt
from talemate.prompts.response import (
    AnchorExtractor,
    AnchorListExtractor,
    ResponseSpec,
)
from talemate.scene_assets import Asset, AssetMeta, SceneAssets
from talemate.scene_message import SceneBackdropMessage


def background(name: str) -> Asset:
    return Asset(
        id=name,
        file_type="png",
        media_type="image",
        meta=AssetMeta(name=name, tags=[name]),
    )


def response_spec() -> ResponseSpec:
    return ResponseSpec(
        extractors={
            **{
                name: AnchorExtractor(
                    left=f"<{name.upper()}>", right=f"</{name.upper()}>"
                )
                for name in ("asset_id", "instructions")
            },
            "references": AnchorListExtractor(
                left="<REFERENCES>", right="</REFERENCES>", separator=r"[\s,;]+"
            ),
        }
    )


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("keep", "harbour-day"),
        ("switch", "harbour-night"),
        ("uncertain", ""),
        ("none", ""),
        ("off", ""),
    ],
)
async def test_background_selection_uses_the_usual_request_once(
    gate_case, monkeypatch, mode, expected
):
    c = gate_case
    monkeypatch.setattr(SceneAssets, "validate_asset_id", lambda self, asset_id: True)
    await c.scene.assets.set_scene_backdrop(asset_id="harbour-day", record=False)
    selected = "none" if mode == "none" else "harbour-night"
    confident = mode in {"keep", "switch", "none"}
    c.provider.answers = {
        "fits_current": {"type": "noul", "p_true": 0.99 if mode == "keep" else 0.1},
        "background": {
            "type": "choice",
            "selected": selected,
            "probabilities": {
                key: 0.98 if key == selected else 0.01
                for key in ("harbour-day", "harbour-night", "none")
            },
            "confidence": 0.99 if confident else 0.5,
        },
    }
    if mode == "off":
        c.agent.actions["backgrounds"].config["decision_model"].value = False
    send = AsyncMock(
        return_value=(
            "<ASSET_ID></ASSET_ID><INSTRUCTIONS>A harbour at dawn</INSTRUCTIONS>"
            "<REFERENCES>harbour-day, `unknown`</REFERENCES>"
        )
    )
    monkeypatch.setattr(Prompt, "send", send)

    result = await run_node(
        DetermineVisual(),
        scene=c.scene,
        inputs={
            "kind": "background",
            "state": True,
            "agent": c.agent,
            "prompt": Prompt.from_text("Select a background.", vars={}),
            "content": "Dawn breaks over the harbour.",
            "assets": [background("harbour-day"), background("harbour-night")],
            "response_spec": response_spec(),
        },
    )

    extracted = result["extracted"]
    assert extracted["asset_id"] == expected
    assert send.await_count == (expected == "")
    assert len(c.provider.calls) == (mode != "off")
    if expected == "":
        assert extracted["instructions"] == "A harbour at dawn"
        assert extracted["references"] == ["harbour-day"]
    else:
        assert "instructions" not in extracted


async def test_a_portrait_selection_needs_a_character(gate_case):
    with pytest.raises(InputValueError):
        await run_node(
            DetermineVisual(),
            scene=gate_case.scene,
            inputs={
                "kind": "portrait",
                "state": True,
                "agent": gate_case.agent,
                "prompt": Prompt.from_text("Select a portrait.", vars={}),
                "content": "Mara shouts.",
                "assets": [],
            },
        )


async def test_set_scene_backdrop_records_a_change(scene, monkeypatch):
    monkeypatch.setattr(SceneAssets, "validate_asset_id", lambda self, asset_id: True)

    first = await run_node(
        SetSceneBackdrop(), scene=scene, inputs={"state": True, "asset_id": "night"}
    )
    again = await run_node(
        SetSceneBackdrop(), scene=scene, inputs={"state": True, "asset_id": "night"}
    )

    assert (first["state"], first["changed"], again["changed"]) == (True, True, False)
    assert scene.assets.backdrop == "night"
    assert [
        m.backdrop for m in scene.history if isinstance(m, SceneBackdropMessage)
    ] == ["night"]


async def test_set_scene_backdrop_refuses_an_unknown_asset(scene):
    with pytest.raises(InputValueError):
        await run_node(
            SetSceneBackdrop(),
            scene=scene,
            inputs={"state": True, "asset_id": "missing"},
        )


async def test_an_attachment_context_can_ask_for_the_backdrop():
    result = await run_node(
        MakeAssetAttachmentContext(), inputs={"scene_backdrop": True}
    )

    assert result["context"].scene_backdrop is True
    assert result["context"].save_asset is True
    assert result["scene_backdrop"] is True


def test_scene_backgrounds_ship_off():
    config = WorldStateAgent.init_actions()["backgrounds"].config

    assert config["selection_frequency"].value == 0
    assert config["generate_new"].value is False
    assert config["decision_model"].value is True


async def test_no_backgrounds_skips_the_decision_model(gate_case, monkeypatch):
    c = gate_case
    send = AsyncMock(return_value="<ASSET_ID></ASSET_ID>")
    monkeypatch.setattr(Prompt, "send", send)

    result = await run_node(
        DetermineVisual(),
        scene=c.scene,
        inputs={
            "kind": "background",
            "state": True,
            "agent": c.agent,
            "prompt": Prompt.from_text("Select a background.", vars={}),
            "content": "Dawn breaks over the harbour.",
            "assets": [],
            "response_spec": response_spec(),
        },
    )

    assert result["extracted"]["asset_id"] == ""
    assert send.await_count == 1
    assert c.provider.calls == []
