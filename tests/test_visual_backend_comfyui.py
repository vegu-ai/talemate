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
