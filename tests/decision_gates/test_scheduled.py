from unittest.mock import AsyncMock

import pytest

from _node_test_helpers import run_node
from talemate.agents.world_state.nodes import DetermineAvatar
from talemate.character import Character
from talemate.prompts import Prompt
from talemate.prompts.response import AnchorExtractor, ResponseSpec
from talemate.scene_assets import Asset, AssetMeta
from talemate.scene_message import NarratorMessage
from talemate.world_state import Reinforcement


@pytest.mark.parametrize(
    "mode",
    [
        "skip",
        "change",
        "uncertain",
        "failed",
        "off",
        "disabled",
        "empty",
        "force",
        "reset",
    ],
)
async def test_due_state_gate(gate_case, monkeypatch, mode):
    c = gate_case
    reinforcement = Reinforcement(
        question="Where is the key?", answer="In the drawer.", interval=5, updated_ts=2
    )
    c.scene.world_state.reinforce = [reinforcement]
    c.scene.history = [NarratorMessage("The key lies in the drawer.")]
    c.provider.answers = {
        "changed": {
            "type": "noul",
            "p_true": {"skip": 0.01, "change": 0.99}.get(mode, 0.5),
        }
    }
    if mode == "failed":
        c.provider.error = RuntimeError("request failed")
    elif mode == "off":
        c.agent.actions["update_reinforcements"].config["decision_model"].value = False
    elif mode == "disabled":
        c.service.enabled = False
    elif mode == "empty":
        reinforcement.answer = None
    send = AsyncMock(return_value=("In the chest.", {"response": "In the chest."}))
    monkeypatch.setattr(Prompt, "send", send)
    monkeypatch.setattr(Prompt, "query_memory", lambda *args, **kwargs: [])
    await c.agent.update_reinforcements(force=mode == "force", reset=mode == "reset")
    if mode == "skip":
        send.assert_not_awaited()
        assert reinforcement.answer == "In the drawer."
        assert reinforcement.due == 5 and reinforcement.updated_ts == 2
        assert len(c.scene.history) == 1
    else:
        send.assert_awaited_once()
        assert reinforcement.answer == "In the chest."
    if mode in {"off", "disabled", "empty", "force", "reset"}:
        assert not c.provider.calls
    else:
        assert len(c.provider.calls) == 1
        record = next(iter(c.service.log.records.values()))
        if mode == "failed":
            assert record.failure is not None
            assert record.actions[0].action == "disabled_path"
        else:
            assert record.actions[0].result["fallback_ran"] is (mode != "skip")


async def test_due_schedule_excludes_inactive_and_not_due(gate_case, monkeypatch):
    c = gate_case
    waiting = Reinforcement(question="Later?", answer="Yes", due=2)
    inactive = Reinforcement(
        question="Where?", answer="Away", character="Nobody", require_active=True
    )
    c.scene.world_state.reinforce = [waiting, inactive]
    update = AsyncMock()
    monkeypatch.setattr(c.agent, "update_reinforcement", update)
    await c.agent.update_reinforcements()
    assert waiting.due == 1
    assert inactive.due == 0
    assert not c.provider.calls
    update.assert_not_awaited()


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("keep", "calm"),
        ("switch", "angry"),
        ("uncertain", "fallback"),
        ("none", "fallback"),
        ("failed", "fallback"),
        ("off", "fallback"),
        ("disabled", "fallback"),
    ],
)
async def test_avatar_node_uses_original_generation_once(
    gate_case, monkeypatch, mode, expected
):
    c = gate_case
    character = Character(name="Mara", current_avatar="calm")
    assets = [
        Asset(
            id=name,
            file_type="png",
            media_type="image",
            meta=AssetMeta(name=name, tags=[name]),
        )
        for name in ("calm", "angry")
    ]
    selected = "none" if mode == "none" else "angry"
    confident = mode in {"keep", "switch", "none"}
    probabilities = {
        key: 0.98 if key == selected else 0.01 for key in ("calm", "angry", "none")
    }
    c.provider.answers = {
        "fits_current": {"type": "noul", "p_true": 0.99 if mode == "keep" else 0.1},
        "avatar": {
            "type": "choice",
            "selected": selected,
            "probabilities": probabilities,
            "confidence": 0.99 if confident else 0.5,
        },
    }
    if mode == "failed":
        c.provider.error = RuntimeError("request failed")
    elif mode == "off":
        c.agent.actions["avatars"].config["decision_model"].value = False
    elif mode == "disabled":
        c.service.enabled = False
    send = AsyncMock(return_value="<ASSET_ID>fallback</ASSET_ID>")
    monkeypatch.setattr(Prompt, "send", send)
    prompt = Prompt.from_text("Select an avatar.", vars={})
    result = await run_node(
        DetermineAvatar(),
        scene=c.scene,
        inputs={
            "state": True,
            "agent": c.agent,
            "prompt": prompt,
            "character": character,
            "content": "Mara shouts in anger.",
            "assets": assets,
            "response_spec": ResponseSpec(
                extractors={
                    "asset_id": AnchorExtractor(left="<ASSET_ID>", right="</ASSET_ID>")
                }
            ),
        },
    )
    assert result["extracted"]["asset_id"] == expected
    assert send.await_count == (expected == "fallback")
    assert len(c.provider.calls) == (mode not in {"off", "disabled"})


@pytest.mark.parametrize("decision_enabled", [True, False])
async def test_shipped_avatar_module_switches_existing_portrait(
    gate_case, monkeypatch, decision_enabled, tmp_path
):
    from PIL import Image
    from _node_test_helpers import (
        build_graph,
        execute_graph,
        make_capture,
        make_constant,
    )
    from talemate.game.engine.nodes.layout import load_graph_from_file
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
    from talemate.scene_assets import VIS_TYPE
    from talemate.tale_mate import Actor

    c = gate_case
    ensure_registry_loaded()
    character = Character(name="Mara", current_avatar="calm")
    c.scene.character_data["Mara"] = character
    c.scene.actors.append(Actor(character=character, agent=None))
    c.scene.active_characters = ["Mara"]
    c.scene.project_name = "avatar-module-test"
    monkeypatch.setattr(c.scene, "scenes_dir", lambda: str(tmp_path))
    asset_dir = tmp_path / c.scene.project_name / "assets"
    asset_dir.mkdir(parents=True)
    for name in ("calm", "angry"):
        Image.new("RGB", (2, 2), "blue").save(asset_dir / f"{name}.png")
    c.scene.assets._assets_cache = {
        name: Asset(
            id=name,
            file_type="png",
            media_type="image",
            meta=AssetMeta(
                name=name,
                character_name="Mara",
                tags=[name],
                vis_type=VIS_TYPE.CHARACTER_PORTRAIT,
            ),
        )
        for name in ("calm", "angry")
    }
    c.agent.actions["avatars"].config["decision_model"].value = decision_enabled
    c.provider.answers = {
        "fits_current": {"type": "noul", "p_true": 0.01},
        "avatar": {
            "type": "choice",
            "selected": "angry",
            "probabilities": {"calm": 0.01, "angry": 0.98, "none": 0.01},
            "confidence": 0.99,
        },
    }
    send = AsyncMock(return_value="<ASSET_ID>angry</ASSET_ID>")
    monkeypatch.setattr(Prompt, "send", send)
    module, _ = load_graph_from_file(
        "src/talemate/agents/world_state/modules/determine-character-avatar.json"
    )
    source = make_constant(
        state=True,
        character=character,
        content="Mara shouts in anger.",
        force_determine=True,
    )
    captured = {}
    output = make_capture(captured, "asset_id")
    graph = build_graph(source, module, output)
    for name in ("state", "character", "content", "force_determine"):
        graph.connect(source.get_output_socket(name), module.get_input_socket(name))
    graph.connect(
        module.get_output_socket("asset_id"), output.get_input_socket("asset_id")
    )
    await execute_graph(c.scene, graph)
    assert captured["asset_id"] == "angry"
    assert character.current_avatar == "angry"
    assert send.await_count == (not decision_enabled)
    assert len(c.provider.calls) == decision_enabled
