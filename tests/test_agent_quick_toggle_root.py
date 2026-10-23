import pytest

from talemate.agents.base import AgentActionConfig
from talemate.agents.visual.agent import VisualAgent


def test_quick_toggle_root_defaults_off():
    config = AgentActionConfig(type="bool", label="Flag", value=False)
    assert config.quick_toggle_root is False
    assert config.icon is None


def test_quick_toggle_root_and_quick_toggle_are_exclusive():
    with pytest.raises(ValueError, match="exclusive"):
        AgentActionConfig(
            type="bool",
            label="Flag",
            value=False,
            quick_toggle=True,
            quick_toggle_root=True,
        )


def test_quick_toggle_root_is_serialized():
    config = AgentActionConfig(
        type="bool", label="Flag", value=False, quick_toggle_root=True, icon="mdi-x"
    )
    dumped = config.model_dump()
    assert dumped["quick_toggle_root"] is True
    assert dumped["icon"] == "mdi-x"


def test_visual_automatic_generation_is_a_root_quick_toggle():
    config_action = VisualAgent.init_actions()["_config"]
    field = config_action.config["automatic_generation"]

    assert field.quick_toggle_root is True
    assert field.quick_toggle is False
    assert field.icon
    assert config_action.quick_toggle is False
