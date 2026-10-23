import json
from pathlib import Path

import httpx
import pytest
from structlog.testing import capture_logs

from talemate.agents.visual.backends.comfyui import Backend, Workflow


SHIPPED_PROMPT_NODES = {
    "default-sd15.json": {
        "4": ("Talemate Positive Prompt", "text"),
        "5": ("Talemate Negative Prompt", "text"),
    },
    "default-sdxl.json": {
        "4": ("Talemate Positive Prompt", "text"),
        "5": ("Talemate Negative Prompt", "text"),
    },
    "qwen_image.json": {
        "6": ("Talemate Positive Prompt", "text"),
        "7": ("Talemate Negative Prompt", "text"),
    },
    "qwen_image_edit.json": {
        "110": ("Talemate Negative Prompt", "prompt"),
        "111": ("Talemate Positive Prompt", "prompt"),
    },
    "z_image_turbo.json": {
        "51": ("Talemate Positive Prompt", "text"),
    },
}
PROMPT_TITLES = {"Talemate Positive Prompt", "Talemate Negative Prompt"}


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


@pytest.mark.asyncio
async def test_object_info_failure_uses_direct_string_fallback():
    class UnavailableObjectInfoBackend(Backend):
        @property
        async def object_info(self):
            raise httpx.ReadTimeout("")

    workflow = workflow_with_prompt_nodes({"content": "old positive", "clip": ["1", 0]})
    backend = UnavailableObjectInfoBackend(
        api_url="http://comfyui.invalid", workflow=workflow
    )

    with capture_logs() as logs:
        await backend._set_workflow_prompt(workflow, "new positive", None)

    assert workflow.nodes["positive"]["inputs"]["content"] == "new positive"
    assert {
        "error": "ReadTimeout",
        "api_url": "http://comfyui.invalid",
        "event": "comfyui.object_info_unavailable",
        "log_level": "warning",
    } in logs


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


def assert_shipped_prompt_receivers(
    workflows_dir: Path,
    workflow_name: str,
    expected_nodes: dict[str, tuple[str, str]],
):
    workflow_path = workflows_dir / workflow_name
    assert workflow_path.is_file(), f"Shipped workflow is missing: {workflow_name}"

    nodes = json.loads(workflow_path.read_text(encoding="utf-8"))
    actual_nodes = {
        node_id: node.get("_meta", {}).get("title")
        for node_id, node in nodes.items()
        if node.get("_meta", {}).get("title") in PROMPT_TITLES
    }
    expected_titles = {node_id: title for node_id, (title, _) in expected_nodes.items()}
    assert actual_nodes == expected_titles, (
        f"{workflow_name}: named prompt node inventory changed; "
        f"expected {expected_titles}, got {actual_nodes}"
    )

    for node_id, (title, receiver) in expected_nodes.items():
        node = nodes[node_id]
        assert receiver in node["inputs"], (
            f"{workflow_name}:{node_id}:{title} is missing its expected "
            f"'{receiver}' receiver"
        )
        prompt = f"{workflow_name}:{node_id}:{title}"
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


@pytest.mark.parametrize(
    ("workflow_name", "expected_nodes"),
    SHIPPED_PROMPT_NODES.items(),
    ids=SHIPPED_PROMPT_NODES,
)
def test_shipped_prompt_nodes_keep_their_named_receivers(workflow_name, expected_nodes):
    assert_shipped_prompt_receivers(
        Path("templates/comfyui-workflows"), workflow_name, expected_nodes
    )


@pytest.fixture
def copied_shipped_workflows(tmp_path):
    source = Path("templates/comfyui-workflows")
    for workflow_name in SHIPPED_PROMPT_NODES:
        (tmp_path / workflow_name).write_bytes((source / workflow_name).read_bytes())
    return tmp_path


def test_missing_shipped_workflow_fails_with_its_name(copied_shipped_workflows):
    workflow_name = "default-sd15.json"
    (copied_shipped_workflows / workflow_name).unlink()

    with pytest.raises(
        AssertionError, match=f"Shipped workflow is missing: {workflow_name}"
    ):
        assert_shipped_prompt_receivers(
            copied_shipped_workflows,
            workflow_name,
            SHIPPED_PROMPT_NODES[workflow_name],
        )


def test_missing_expected_prompt_node_fails_with_template_inventory(
    copied_shipped_workflows,
):
    workflow_name = "default-sd15.json"
    workflow_path = copied_shipped_workflows / workflow_name
    nodes = json.loads(workflow_path.read_text(encoding="utf-8"))
    del nodes["4"]
    workflow_path.write_text(json.dumps(nodes), encoding="utf-8")

    with pytest.raises(AssertionError, match="named prompt node inventory changed"):
        assert_shipped_prompt_receivers(
            copied_shipped_workflows,
            workflow_name,
            SHIPPED_PROMPT_NODES[workflow_name],
        )


def test_broken_expected_prompt_receiver_fails_with_node_name(
    copied_shipped_workflows,
):
    workflow_name = "default-sd15.json"
    workflow_path = copied_shipped_workflows / workflow_name
    nodes = json.loads(workflow_path.read_text(encoding="utf-8"))
    nodes["4"]["inputs"]["content"] = nodes["4"]["inputs"].pop("text")
    workflow_path.write_text(json.dumps(nodes), encoding="utf-8")

    with pytest.raises(AssertionError, match="default-sd15.json:4:.*'text' receiver"):
        assert_shipped_prompt_receivers(
            copied_shipped_workflows,
            workflow_name,
            SHIPPED_PROMPT_NODES[workflow_name],
        )


def test_unlisted_malformed_user_workflow_is_not_parsed(copied_shipped_workflows):
    (copied_shipped_workflows / "user-workflow.json").write_text(
        "not valid JSON", encoding="utf-8"
    )

    for workflow_name, expected_nodes in SHIPPED_PROMPT_NODES.items():
        assert_shipped_prompt_receivers(
            copied_shipped_workflows, workflow_name, expected_nodes
        )
