import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import talemate.game.engine.nodes.load_definitions  # noqa: F401

from _node_test_helpers import build_graph, execute_graph, make_capture, make_constant
from talemate.agents.director.action_core import utils
from talemate.agents.director.chat.context import DirectorChatContext
from talemate.agents.director.chat.nodes import (
    DirectorChatAction,
    DirectorChatActionConfirm,
)
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphContext, GraphState
from talemate.game.engine.nodes.registry import (
    get_node,
    import_talemate_node_definitions,
)
from talemate.game.engine.nodes.run import FunctionWrapper
from talemate.game.focal.schema import Call, CallRejected
from talemate.instance import get_agent


MODULES = Path("src/talemate/agents/director/modules")


@pytest.fixture
def action_scene(scene, monkeypatch):
    import_talemate_node_definitions()
    scene.active = True
    visual = get_agent("visual")
    monkeypatch.setattr(type(visual), "can_generate_images", property(lambda _: True))
    monkeypatch.setattr(type(visual), "can_edit_images", property(lambda _: True))
    monkeypatch.setattr(visual, "generate", AsyncMock())
    return scene


@pytest.mark.parametrize(
    ("module", "failure"),
    [
        ("create-image", "No image was started"),
        ("direct-scene", "No scene direction was started"),
        ("prompt-user", "No prompt or notice was shown to the user"),
    ],
)
@pytest.mark.parametrize(
    "response",
    ["I cannot choose a function.", "The requested work has started.", ""],
)
async def test_action_without_function_call_reports_failure_once(
    action_scene, monkeypatch, module, failure, response
):
    scene = action_scene
    action = DirectorChatAction(
        **json.loads((MODULES / f"director-action-{module}.json").read_text())
    )
    send = AsyncMock(return_value=response)
    monkeypatch.setattr(scene.mock_client, "send_prompt", send)

    with (
        ActiveScene(scene),
        DirectorChatContext(chat_id="test", confirm_write_actions=False),
        GraphContext() as state,
    ):
        result = await FunctionWrapper(action, action, state)(
            instructions="Carry out the requested action."
        )

    assert send.await_count == 1
    assert failure in result
    assert "FAILED" in result
    assert "model returned no callable function" in result
    get_agent("visual").generate.assert_not_awaited()


@pytest.mark.parametrize("batch", [None, []])
async def test_empty_action_summary_preserves_empty_default(action_scene, batch):
    result = await run_summary(action_scene, [], batch=batch)
    assert result["summary"] == ""


@pytest.mark.parametrize("calls", [None, []])
@pytest.mark.parametrize(
    "batch",
    [None, [], [Call(name="unknown", skipped_reason="unknown_callback")]],
)
async def test_action_summary_without_known_calls_uses_configured_failure(
    action_scene, calls, batch
):
    result = await run_summary(
        action_scene, calls, batch=batch, no_calls_result="No work was started."
    )
    assert result["summary"] == "No work was started."


async def test_action_summary_rejected_known_call_does_not_use_failure(action_scene):
    result = await run_summary(
        action_scene,
        [],
        batch=[
            Call(name="unknown", skipped_reason="unknown_callback"),
            Call(name="generate", skipped_reason="reject_with_instructions"),
        ],
        no_calls_result="No work was started.",
    )
    assert result["summary"] == ""


@pytest.mark.parametrize(
    ("action_name", "callback", "arguments", "confirm_id"),
    [
        (
            "create_image",
            "generate_visual_asset",
            {
                "character_name": "",
                "vis_type": "SCENE_ILLUSTRATION",
                "instructions": "Draw the harbor.",
            },
            "8a4ddc4c",
        ),
        (
            "direct_scene",
            "advance_time",
            {"amount": 1, "unit": "day", "instructions": "Wait at the harbor."},
            "eebce501",
        ),
    ],
)
async def test_rejected_call_corrections_do_not_claim_model_returned_no_call(
    action_scene, director, monkeypatch, action_name, callback, arguments, confirm_id
):
    scene = action_scene
    scene.nodegraph_state = GraphState()
    await utils.init_action_nodes(scene, scene.nodegraph_state)
    chat = director.chat_create()
    director.chat_update_title(chat.id, "Rejection regression")
    monkeypatch.setattr(
        type(scene.mock_client), "max_token_length", property(lambda _: 16384)
    )
    monkeypatch.setattr(
        director, "_chat_compact_if_needed", AsyncMock(return_value=False)
    )
    confirmation_nodes = []

    async def reject_with_instructions(node, state):
        confirmation_nodes.append(node.id)
        raise CallRejected(
            "User rejected the call",
            reason="reject_with_instructions",
            instructions="Wait for my next request.",
        )

    monkeypatch.setattr(DirectorChatActionConfirm, "run", reject_with_instructions)
    responses = [
        "<ANALYSIS>I will act.</ANALYSIS><MESSAGE>Preparing.</MESSAGE>"
        f"<ACTIONS>```json\n[{json.dumps({'name': action_name, 'instructions': 'Carry out the request.'})}]\n```</ACTIONS>",
        "```json\n"
        + json.dumps(
            {
                "function": action_name,
                "arguments": {"instructions": "Carry out the request."},
            }
        )
        + "\n```",
        "```json\n"
        + json.dumps({"function": callback, "arguments": arguments})
        + "\n```",
        "<ANALYSIS>The user rejected the call.</ANALYSIS>"
        "<MESSAGE>I will wait for your next request.</MESSAGE>",
    ]
    prompts = []

    async def respond(prompt, *args, **kwargs):
        prompts.append(prompt.prompt)
        assert responses, "Unexpected extra LLM request"
        return responses.pop(0)

    monkeypatch.setattr(scene.mock_client, "send_prompt", respond)
    done = AsyncMock()
    original_time = scene.ts
    with (
        ActiveScene(scene),
        DirectorChatContext(chat_id=chat.id, confirm_write_actions=True),
    ):
        result = await director.chat_send(
            chat.id, "Carry out the request.", on_done=done
        )

    assert len(confirmation_nodes) == 1
    assert confirmation_nodes[0].startswith(confirm_id)
    assert len(prompts) == 4
    assert not responses
    assert "User corrections for rejected calls" in prompts[-1]
    assert "Wait for my next request." in prompts[-1]
    assert "model returned no callable function" not in prompts[-1]
    action_results = [m for m in result.messages if m.type == "action_result"]
    assert len(action_results) == 1
    assert action_results[0].result == ""
    assert result.messages[-1].message == "I will wait for your next request."
    assert scene.ts == original_time
    done.assert_awaited_once()
    get_agent("visual").generate.assert_not_awaited()


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (
            Call(name="generate", result="Image started", called=True),
            "SUCCESS: Image started",
        ),
        (
            Call(name="generate", error="Backend unavailable"),
            "FAILED: Backend unavailable",
        ),
    ],
)
@pytest.mark.parametrize("include_batch", [False, True])
async def test_action_summary_preserves_call_results(
    action_scene, call, expected, include_batch
):
    batch = (
        [Call(name="unknown", skipped_reason="unknown_callback"), call]
        if include_batch
        else None
    )
    result = await run_summary(
        action_scene, [call], batch=batch, no_calls_result="No work was started."
    )
    assert expected in result["summary"]
    assert "No work was started" not in result["summary"]


@pytest.mark.parametrize(
    "inner_response",
    [
        "I cannot choose a function.",
        '```json\n{"function":"create_image","arguments":{"instructions":"Draw the harbor."}}\n```',
    ],
    ids=["no-call", "unknown-callback"],
)
async def test_next_chat_turn_receives_no_image_started_result(
    action_scene, director, monkeypatch, inner_response
):
    scene = action_scene
    scene.nodegraph_state = GraphState()
    await utils.init_action_nodes(scene, scene.nodegraph_state)
    chat = director.chat_create()
    director.chat_update_title(chat.id, "Create an image")
    monkeypatch.setattr(
        type(scene.mock_client), "max_token_length", property(lambda _: 16384)
    )
    monkeypatch.setattr(
        director, "_chat_compact_if_needed", AsyncMock(return_value=False)
    )
    responses = [
        "<ANALYSIS>I will ask the artist.</ANALYSIS><MESSAGE>Starting the request.</MESSAGE>"
        '<ACTIONS>```json\n[{"name":"create_image","instructions":"Draw the harbor."}]\n```</ACTIONS>',
        '```json\n{"function":"create_image","arguments":{"instructions":"Draw the harbor."}}\n```',
        inner_response,
        "<ANALYSIS>No image was started.</ANALYSIS><MESSAGE>The image was not started.</MESSAGE>",
    ]
    prompts = []

    async def respond(prompt, *args, **kwargs):
        prompts.append(prompt.prompt)
        assert responses, "Unexpected extra LLM request"
        return responses.pop(0)

    monkeypatch.setattr(scene.mock_client, "send_prompt", respond)
    done = AsyncMock()
    with (
        ActiveScene(scene),
        DirectorChatContext(chat_id=chat.id, confirm_write_actions=False),
    ):
        result = await director.chat_send(chat.id, "Draw the harbor.", on_done=done)

    assert len(prompts) == 4
    assert not responses
    failures = [
        message for message in result.messages if message.type == "action_result"
    ]
    assert len(failures) == 1
    assert failures[0].name == "create_image"
    assert "No image was started" in failures[0].result
    assert "model returned no callable function" in prompts[-1]
    assert "No image was started" in prompts[-1]
    assert result.messages[-1].message == "The image was not started."
    done.assert_awaited_once()
    get_agent("visual").generate.assert_not_awaited()


async def run_summary(scene, calls, batch=None, no_calls_result=""):
    summary = get_node("agents/director/chat/directorActionSummary")()
    summary.set_property("no_calls_result", no_calls_result)
    source = make_constant(calls=calls, batch=batch)
    result = {}
    capture = make_capture(result, "summary")
    graph = build_graph(source, summary, capture)
    graph.connect(source.get_output_socket("calls"), summary.get_input_socket("calls"))
    if batch is not None:
        graph.connect(
            source.get_output_socket("batch"), summary.get_input_socket("batch")
        )
    graph.connect(
        summary.get_output_socket("summary"), capture.get_input_socket("summary")
    )
    await execute_graph(scene, graph)
    return result
