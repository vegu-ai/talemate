import json
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from talemate.agents.visual.backends.comfyui import Workflow


def prompt_node(title, class_type, inputs):
    return {
        "inputs": inputs,
        "class_type": class_type,
        "_meta": {"title": title},
    }


def workflow_with_prompt_nodes(positive_inputs, negative_inputs=None):
    nodes = {
        "positive": prompt_node(
            "Talemate Positive Prompt", "PositiveNode", positive_inputs
        )
    }
    if negative_inputs is not None:
        nodes["negative"] = prompt_node(
            "Talemate Negative Prompt", "NegativeNode", negative_inputs
        )
    return Workflow(nodes=nodes, mtime=0, path="unused.json")


def test_set_prompt_uses_attached_workflow_value_receiver():
    workflow = Workflow(
        nodes={
            "54": prompt_node(
                "Positive Prompt",
                "CLIPTextEncode",
                {"text": ["75", 0], "clip": ["59", 0]},
            ),
            "75": prompt_node(
                "Talemate Positive Prompt",
                "PrimitiveStringMultiline",
                {"value": "Photo of a cat"},
            ),
        },
        mtime=0,
        path="talemate_krea_broken.json",
    )

    workflow.set_prompt("Photo of a fox")

    assert workflow.nodes["75"]["inputs"]["value"] == "Photo of a fox"
    assert workflow.nodes["54"]["inputs"]["text"] == ["75", 0]


def test_set_prompt_uses_unique_direct_string_receiver_for_both_prompt_kinds():
    workflow = workflow_with_prompt_nodes(
        {"content": "old positive", "clip": ["1", 0]},
        {"description": "old negative", "clip": ["1", 0]},
    )

    workflow.set_prompt("new positive", "new negative")

    assert workflow.nodes["positive"]["inputs"]["content"] == "new positive"
    assert workflow.nodes["negative"]["inputs"]["description"] == "new negative"


@pytest.mark.parametrize(
    ("inputs", "receiver", "unrelated_input"),
    [
        ({"text": ["75", 0], "parser": "comfy++", "clip": ["1", 0]}, "text", "parser"),
        (
            {"prompt": ["75", 0], "negative_prompt": "keep", "clip": ["1", 0]},
            "prompt",
            "negative_prompt",
        ),
    ],
)
def test_set_prompt_prefers_linked_named_receiver_over_unrelated_string(
    inputs, receiver, unrelated_input
):
    original_unrelated_value = inputs[unrelated_input]
    workflow = workflow_with_prompt_nodes(inputs)

    workflow.set_prompt("new positive")

    assert workflow.nodes["positive"]["inputs"][receiver] == "new positive"
    assert (
        workflow.nodes["positive"]["inputs"][unrelated_input]
        == original_unrelated_value
    )


def test_set_prompt_uses_unique_declared_string_instead_of_combo_value():
    workflow = workflow_with_prompt_nodes(
        {"user_prompt": ["75", 0], "system_prompt": "superior", "clip": ["1", 0]}
    )
    workflow.nodes["positive"]["class_type"] = "CLIPTextEncodeLumina2"
    object_info = {
        "CLIPTextEncodeLumina2": {
            "input": {
                "required": {
                    "system_prompt": ["COMBO", {"options": ["superior", "alignment"]}],
                    "user_prompt": ["STRING", {"multiline": True}],
                    "clip": ["CLIP", {}],
                }
            }
        }
    }

    workflow.set_prompt("new positive", object_info=object_info)

    assert workflow.nodes["positive"]["inputs"]["user_prompt"] == "new positive"
    assert workflow.nodes["positive"]["inputs"]["system_prompt"] == "superior"


@pytest.mark.parametrize(
    ("inputs", "expected_receiver"),
    [
        ({"text": "", "prompt": "", "value": ""}, "text"),
        ({"prompt": "", "value": ""}, "prompt"),
        ({"value": "", "other": ""}, "value"),
    ],
)
def test_set_prompt_fallback_receiver_priority(inputs, expected_receiver):
    workflow = workflow_with_prompt_nodes(inputs)

    workflow.set_prompt("new prompt")

    assert workflow.nodes["positive"]["inputs"][expected_receiver] == "new prompt"


def test_set_prompt_warns_when_prompt_node_has_no_receiver():
    workflow = workflow_with_prompt_nodes(
        {"prefix": "prefix", "suffix": "suffix", "clip": ["1", 0]},
        {"conditioning": ["2", 0]},
    )

    with capture_logs() as logs:
        workflow.set_prompt("new positive", "new negative")

    warnings = [
        entry for entry in logs if entry["event"] == "comfyui.prompt_receiver_missing"
    ]
    assert warnings == [
        {
            "prompt_kind": "positive",
            "node_title": "Talemate Positive Prompt",
            "node_type": "PositiveNode",
            "input_properties": ["clip", "prefix", "suffix"],
            "event": "comfyui.prompt_receiver_missing",
            "log_level": "warning",
        },
        {
            "prompt_kind": "negative",
            "node_title": "Talemate Negative Prompt",
            "node_type": "NegativeNode",
            "input_properties": ["conditioning"],
            "event": "comfyui.prompt_receiver_missing",
            "log_level": "warning",
        },
    ]


def test_shipped_prompt_nodes_keep_their_named_receivers():
    workflows_dir = Path("templates/comfyui-workflows")
    prompt_nodes = []

    for workflow_path in sorted(workflows_dir.glob("*.json")):
        nodes = json.loads(workflow_path.read_text(encoding="utf-8"))
        for node_id, node in nodes.items():
            title = node.get("_meta", {}).get("title")
            if title in ("Talemate Positive Prompt", "Talemate Negative Prompt"):
                prompt_nodes.append((workflow_path, node_id, title, node))

    assert len(prompt_nodes) == 9

    for workflow_path, node_id, title, node in prompt_nodes:
        receiver = "text" if "text" in node["inputs"] else "prompt"
        prompt = f"{workflow_path.name}:{node_id}:{title}"
        workflow = Workflow(
            nodes={node_id: node},
            mtime=workflow_path.stat().st_mtime,
            path=str(workflow_path),
        )

        if title == "Talemate Positive Prompt":
            workflow.set_prompt(prompt)
        else:
            workflow.nodes[node_id]["_meta"]["title"] = "Talemate Negative Prompt"
            positive = prompt_node(
                "Talemate Positive Prompt", "CLIPTextEncode", {"text": ""}
            )
            workflow.nodes["positive"] = positive
            workflow.set_prompt("positive", prompt)

        assert workflow.nodes[node_id]["inputs"][receiver] == prompt
