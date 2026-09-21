"""
The choice lists a backend pane needs before its selection is saved.

`VisualAgent.emit_status` dispatches the per backend status emits on the
**saved** selection, so a list that needs no backend instance is filled by a
`{backend}_update_choices` hook instead.
"""

from types import SimpleNamespace

import pytest

import talemate.agents.visual.backends.talemate_client as talemate_client_backend
from talemate.agents.visual.agent import VisualAgent


SHIPPED_WORKFLOWS = (
    "default-sd15.json",
    "default-sdxl.json",
    "qwen_image.json",
    "qwen_image_edit.json",
    "z_image_turbo.json",
)


@pytest.fixture
def visual_agent():
    return VisualAgent()


def workflow_choices(agent, action_name):
    return agent.actions[action_name].config["workflow"].choices


def test_workflow_choices_list_the_shipped_workflows_sorted(visual_agent):
    visual_agent.comfyui_update_choices()

    for action_name in ("comfyui_image_create", "comfyui_image_edit"):
        choices = workflow_choices(visual_agent, action_name)
        names = [choice["value"] for choice in choices]
        # a superset: the directory is where a user drops their own workflows
        assert set(SHIPPED_WORKFLOWS) <= set(names)
        assert names == sorted(names)
        assert [choice["label"] for choice in choices] == names


async def test_status_emit_fills_workflow_choices_without_a_saved_backend(
    visual_agent,
):
    assert visual_agent.actions["_config"].config["backend"].value == ""
    assert visual_agent.backend is None

    await visual_agent.emit_status()

    for action_name in ("comfyui_image_create", "comfyui_image_edit"):
        assert workflow_choices(visual_agent, action_name)


def test_talemate_client_choices_fill_without_a_saved_backend(
    visual_agent, monkeypatch
):
    monkeypatch.setattr(
        talemate_client_backend.instance,
        "client_instances",
        lambda: [
            ("seeing", SimpleNamespace(supports_vision=True, model_name="a-model")),
            ("blind", SimpleNamespace(supports_vision=False, model_name="b-model")),
        ],
    )
    action = visual_agent.actions["talemate_client_image_analyzation"]
    assert (
        visual_agent.actions["_config"].config["backend_image_analyzation"].value == ""
    )
    assert action.config["client"].choices == []

    visual_agent.talemate_client_update_choices()

    assert action.config["client"].choices == [
        {"label": "seeing (a-model)", "value": "seeing"}
    ]


async def test_status_emit_fills_every_backend_choice_list(visual_agent, monkeypatch):
    monkeypatch.setattr(
        talemate_client_backend.instance,
        "client_instances",
        lambda: [("seeing", SimpleNamespace(supports_vision=True, model_name="a"))],
    )

    await visual_agent.emit_status()

    assert workflow_choices(visual_agent, "comfyui_image_create")
    assert (
        visual_agent.actions["talemate_client_image_analyzation"]
        .config["client"]
        .choices
    )
