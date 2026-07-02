"""
Unit tests for the uniform UX field framework (`talemate.ux.schema`) and its
integration into agent action configs (`talemate.agents.base.AgentActionConfig`)
and client extra fields (`talemate.client.base.ExtraField`).
"""

from __future__ import annotations

import pydantic
import pytest

import talemate.ux.schema as ux_schema
from talemate.agents.base import (
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentActionNote,
)
from talemate.client.base import ExtraField, FieldGroup


# ---------------------------------------------------------------------------
# Field base
# ---------------------------------------------------------------------------


def test_field_choices_scalar_normalization():
    field = ux_schema.Field(type="text", label="Mode", choices=["budget", "adaptive"])
    assert field.choices == [
        {"label": "budget", "value": "budget"},
        {"label": "adaptive", "value": "adaptive"},
    ]


def test_field_choices_dict_passthrough():
    choices = [{"label": "A", "value": "a"}, {"label": "B", "value": "b", "help": "x"}]
    field = ux_schema.Field(type="text", label="Mode", choices=choices)
    assert field.choices == choices


def test_field_choices_mixed_normalization():
    field = ux_schema.Field(
        type="flags",
        label="Flags",
        choices=["plain", {"label": "Rich", "value": "rich"}],
    )
    assert field.choices == [
        {"label": "plain", "value": "plain"},
        {"label": "Rich", "value": "rich"},
    ]


def test_field_choices_none_stays_none():
    field = ux_schema.Field(type="text", label="Name")
    assert field.choices is None


def test_field_note_string_coercion():
    field = ux_schema.Field(type="text", label="Name", note="a helpful note")
    assert isinstance(field.note, ux_schema.Note)
    assert field.note.text == "a helpful note"


def test_field_note_string_assignment_serializes_as_note():
    # post-construction assignment bypasses validation; the serializer must
    # still emit the Note object shape
    field = ux_schema.Field(type="text", label="Name")
    field.note = "assigned later"
    dumped = field.model_dump()
    assert dumped["note"] == {
        "text": "assigned later",
        "title": None,
        "color": None,
        "icon": None,
        "actions": [],
    }


def test_field_rejects_unknown_type():
    with pytest.raises(pydantic.ValidationError):
        ux_schema.Field(type="select", label="Legacy")


def test_field_table_type_with_columns():
    field = ux_schema.Field(
        type="table",
        label="Rows",
        columns=[
            ux_schema.Column(name="key", type="text", label="Key"),
            ux_schema.Column(name="weight", type="number", label="Weight", min=0),
        ],
    )
    dumped = field.model_dump()
    assert [c["name"] for c in dumped["columns"]] == ["key", "weight"]


def test_field_condition_serialization():
    field = ux_schema.Field(
        type="text",
        label="Name",
        condition=ux_schema.Condition(attribute="other_field", value=["a", "b"]),
    )
    dumped = field.model_dump()
    assert dumped["condition"] == {"attribute": "other_field", "value": ["a", "b"]}


def test_field_group_serialization():
    field = ux_schema.Field(
        type="text",
        label="Name",
        group=ux_schema.FieldGroup(name="grp", label="Group", description="desc"),
    )
    dumped = field.model_dump()
    assert dumped["group"]["name"] == "grp"
    assert dumped["group"]["icon"] == "mdi-cog"


# ---------------------------------------------------------------------------
# AgentActionConfig on the shared base
# ---------------------------------------------------------------------------


def test_agent_action_config_is_uniform_field():
    assert issubclass(AgentActionConfig, ux_schema.Field)


def test_agent_action_conditional_is_shared_condition():
    assert AgentActionConditional is ux_schema.Condition
    assert AgentActionNote is ux_schema.Note


def test_agent_action_config_defaults_preserved():
    config = AgentActionConfig(type="number", label="Length", value=5, min=1, max=10)
    assert config.scope == "global"
    assert config.scene_overridable is True
    assert config.quick_toggle is False
    assert config.save_on_change is False
    assert config.choices is None
    assert config.value_migration is None


def test_agent_action_config_note_coercion_and_note_on_value():
    config = AgentActionConfig(
        type="bool",
        label="Enabled",
        value=True,
        note="plain string note",
        note_on_value={True: AgentActionNote(text="on"), False: "off"},
    )
    assert config.note.text == "plain string note"
    dumped = config.model_dump()
    assert dumped["note"]["text"] == "plain string note"
    assert dumped["note_on_value"][True]["text"] == "on"
    assert dumped["note_on_value"][False]["text"] == "off"


def test_agent_action_config_value_migration_excluded_from_dump():
    config = AgentActionConfig(type="text", label="Name", value_migration=lambda v: v)
    assert "value_migration" not in config.model_dump()


def test_agent_action_serializes_config_via_shared_schema():
    action = AgentAction(
        label="Test action",
        config={
            "mode": AgentActionConfig(
                type="text",
                label="Mode",
                value="a",
                choices=[{"label": "A", "value": "a"}],
                condition=AgentActionConditional(
                    attribute="_config.config.x", value=True
                ),
            )
        },
    )
    dumped = action.model_dump()
    config = dumped["config"]["mode"]
    assert config["type"] == "text"
    assert config["choices"] == [{"label": "A", "value": "a"}]
    assert config["condition"] == {"attribute": "_config.config.x", "value": True}
    # uniform-schema keys are present for the frontend renderer
    for key in ("required", "group", "note_on_value", "save_on_change"):
        assert key in config


# ---------------------------------------------------------------------------
# ExtraField on the shared base
# ---------------------------------------------------------------------------


def test_extra_field_is_uniform_field():
    assert issubclass(ExtraField, ux_schema.Field)
    assert FieldGroup is ux_schema.FieldGroup


def test_extra_field_minimal_construction():
    field = ExtraField(name="my_field", type="bool", label="My Field")
    assert field.required is False
    assert field.group is None
    assert field.description == ""


def test_extra_field_scalar_choices_normalized():
    field = ExtraField(
        name="mode",
        type="text",
        label="Mode",
        choices=["budget", "adaptive"],
    )
    assert field.choices == [
        {"label": "budget", "value": "budget"},
        {"label": "adaptive", "value": "adaptive"},
    ]


def test_extra_field_gains_uniform_capabilities():
    # capabilities that used to be agent-only are now available to client
    # extra fields through the shared schema
    field = ExtraField(
        name="quality",
        type="number",
        label="Quality",
        min=1,
        max=10,
        step=1,
        condition=ux_schema.Condition(attribute="enabled", value=True),
        note_on_value={10: "maximum quality is expensive"},
    )
    dumped = field.model_dump()
    assert dumped["min"] == 1
    assert dumped["condition"]["attribute"] == "enabled"
    assert dumped["note_on_value"][10]["text"] == "maximum quality is expensive"


# ---------------------------------------------------------------------------
# Client Meta serialization (websocket payload shape)
# ---------------------------------------------------------------------------


def test_client_meta_extra_fields_serialize_uniformly():
    import talemate.client  # noqa: F401 - ensure client registration
    from talemate.client.registry import CLIENT_CLASSES

    for client_type, cls in CLIENT_CLASSES.items():
        meta = cls.Meta().model_dump()
        for name, field in (meta.get("extra_fields") or {}).items():
            # legacy "select" type must not appear anywhere
            assert field["type"] != "select", (client_type, name)
            # choices, when present, are normalized {label, value} dicts
            for choice in field["choices"] or []:
                assert isinstance(choice, dict), (client_type, name)
                assert "label" in choice and "value" in choice, (client_type, name)
            # uniform keys the shared renderer relies on
            for key in ("name", "type", "label", "description", "required"):
                assert key in field, (client_type, name)


def test_anthropic_thinking_mode_select_migrated_to_choices():
    import talemate.client  # noqa: F401
    from talemate.client.registry import CLIENT_CLASSES

    meta = CLIENT_CLASSES["anthropic"].Meta().model_dump()
    thinking_mode = meta["extra_fields"]["thinking_mode"]
    assert thinking_mode["type"] == "text"
    assert {"label": "budget", "value": "budget"} in thinking_mode["choices"]
    assert {"label": "adaptive", "value": "adaptive"} in thinking_mode["choices"]
