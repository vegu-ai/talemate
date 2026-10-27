"""Coverage-focused unit tests for talemate.game.engine.nodes.validation.

ValidateNode subclasses raise InputValueError when their validation
predicate fails and pass the input through otherwise. Each subclass is
exercised with positive and negative paths.

Context-ID and asset-ID validators require a real Scene; we use a plain
Scene plus a tmp save_dir for the asset case.
"""

from __future__ import annotations

import os

import pytest

from _node_test_helpers import run_node
from talemate.character import Character
from talemate.game.engine.nodes.core import InputValueError, UNRESOLVED
from talemate.game.engine.nodes.validation import (
    ValidateAssetID,
    ValidateCharacter,
    ValidateContextIDItem,
    ValidateContextIDString,
    ValidateValueContained,
    ValidateValueIsNotSet,
    ValidateValueIsSet,
)

# Importing the context_id package wires up CONTEXT_ID_PATH_HANDLERS for the
# Validate* nodes that walk that registry.
import talemate.game.engine.context_id  # noqa: F401
from talemate.game.engine.context_id import compress_name
from talemate.tale_mate import Scene
from talemate.world_state import ManualContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fs_scene(tmp_path, monkeypatch):
    """Scene with a tmp save_dir so SceneAssets is real."""
    monkeypatch.setattr(
        Scene,
        "scenes_dir",
        classmethod(lambda cls: str(tmp_path)),
        raising=True,
    )
    s = Scene()
    s.project_name = "proj_validation"
    os.makedirs(s.save_dir, exist_ok=True)
    s.emit_status = lambda *a, **kw: None
    return s


# ---------------------------------------------------------------------------
# ValidateValueIsSet
# ---------------------------------------------------------------------------


class TestValidateValueIsSet:
    @pytest.mark.asyncio
    async def test_passes_through_truthy_value(self):
        out = await run_node(ValidateValueIsSet(), inputs={"value": "x"})
        assert out["value"] == "x"

    @pytest.mark.asyncio
    async def test_zero_is_passed_through(self):
        # 0 is falsy in Python but neither None, UNRESOLVED, nor "" — must pass.
        out = await run_node(ValidateValueIsSet(), inputs={"value": 0})
        assert out["value"] == 0

    @pytest.mark.asyncio
    async def test_none_raises(self):
        with pytest.raises(InputValueError):
            await run_node(ValidateValueIsSet(), inputs={"value": None})

    @pytest.mark.asyncio
    async def test_unresolved_raises(self):
        with pytest.raises(InputValueError):
            await run_node(ValidateValueIsSet(), inputs={"value": UNRESOLVED})

    @pytest.mark.asyncio
    async def test_blank_string_raises_when_flag_true(self):
        node = ValidateValueIsSet()
        node.set_property("blank_string_is_unset", True)
        with pytest.raises(InputValueError):
            await run_node(node, inputs={"value": ""})

    @pytest.mark.asyncio
    async def test_blank_string_passes_when_flag_false(self):
        node = ValidateValueIsSet()
        node.set_property("blank_string_is_unset", False)
        out = await run_node(node, inputs={"value": ""})
        assert out["value"] == ""

    @pytest.mark.asyncio
    async def test_custom_error_message_uses_format_string(self):
        # The error message format is interpolated with {value}.
        with pytest.raises(InputValueError, match="The literal: hello-world"):
            # Trigger by setting a value that fails (None) but interpolates a
            # custom string. The {value} is replaced with the failing value.
            node = ValidateValueIsSet()
            node.set_property("error_message", "The literal: hello-world {value}")
            await run_node(node, inputs={"value": None})


# ---------------------------------------------------------------------------
# ValidateValueIsNotSet
# ---------------------------------------------------------------------------


class TestValidateValueIsNotSet:
    @pytest.mark.asyncio
    async def test_none_passes(self):
        out = await run_node(ValidateValueIsNotSet(), inputs={"value": None})
        assert out["value"] is None

    @pytest.mark.asyncio
    async def test_unresolved_passes(self):
        out = await run_node(ValidateValueIsNotSet(), inputs={"value": UNRESOLVED})
        assert out["value"] is UNRESOLVED

    @pytest.mark.asyncio
    async def test_empty_string_passes(self):
        out = await run_node(ValidateValueIsNotSet(), inputs={"value": ""})
        assert out["value"] == ""

    @pytest.mark.asyncio
    async def test_set_value_raises(self):
        with pytest.raises(InputValueError):
            await run_node(ValidateValueIsNotSet(), inputs={"value": "x"})


# ---------------------------------------------------------------------------
# ValidateValueContained
# ---------------------------------------------------------------------------


class TestValidateValueContained:
    @pytest.mark.asyncio
    async def test_in_list_passes(self):
        out = await run_node(
            ValidateValueContained(),
            inputs={"value": "a", "list": ["a", "b"]},
        )
        assert out["value"] == "a"

    @pytest.mark.asyncio
    async def test_not_in_list_raises(self):
        with pytest.raises(InputValueError):
            await run_node(
                ValidateValueContained(),
                inputs={"value": "z", "list": ["a", "b"]},
            )

    @pytest.mark.asyncio
    async def test_in_dict_keys_passes(self):
        out = await run_node(
            ValidateValueContained(),
            inputs={"value": "a", "list": {"a": 1, "b": 2}},
        )
        assert out["value"] == "a"


# ---------------------------------------------------------------------------
# ValidateContextIDString
# ---------------------------------------------------------------------------


class TestValidateContextIDString:
    @pytest.mark.asyncio
    async def test_unhandled_type_raises_input_value_error(self, fs_scene):
        # An int has no .strip method — the validator wraps the AttributeError
        # in InputValueError describing the bad type.
        with pytest.raises(InputValueError, match="Invalid type"):
            await run_node(
                ValidateContextIDString(), scene=fs_scene, inputs={"value": 12345}
            )

    @pytest.mark.asyncio
    async def test_unknown_handler_raises(self, fs_scene):
        # A context-id-like string with an unregistered prefix raises.
        with pytest.raises(InputValueError):
            await run_node(
                ValidateContextIDString(),
                scene=fs_scene,
                inputs={"value": "no_handler_for_this:foo"},
            )


# ---------------------------------------------------------------------------
# ValidateContextIDItem
# ---------------------------------------------------------------------------


class TestValidateContextIDItem:
    @pytest.mark.asyncio
    async def test_invalid_input_type_raises(self, fs_scene):
        with pytest.raises(InputValueError, match="Invalid type"):
            await run_node(ValidateContextIDItem(), scene=fs_scene, inputs={"value": 1})

    @pytest.mark.asyncio
    async def test_unhandled_string_raises(self, fs_scene):
        with pytest.raises(InputValueError):
            await run_node(
                ValidateContextIDItem(),
                scene=fs_scene,
                inputs={"value": "no_handler_for_this:foo"},
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value",
        [
            f"world_entry.manual:{compress_name('Apartment: Living Room')}",
            "world_entry.manual:Apartment: Living Room",
            "`world_entry.manual:Apartment: Living Room`",
        ],
    )
    async def test_world_entry_resolves_by_id_or_title(self, fs_scene, value):
        fs_scene.world_state.manual_context["Apartment: Living Room"] = ManualContext(
            id="Apartment: Living Room",
            text="A cramped living room.",
            meta={"typ": "world_state"},
        )

        out = await run_node(
            ValidateContextIDItem(), scene=fs_scene, inputs={"value": value}
        )

        assert out["name"] == "Apartment: Living Room"
        assert out["context_value"] == "A cramped living room."
        assert str(out["context_id"]) == (
            f"world_entry.manual:{compress_name('Apartment: Living Room')}"
        )

    @pytest.mark.asyncio
    async def test_unknown_world_entry_names_the_context_id(self, fs_scene):
        with pytest.raises(
            InputValueError,
            match="Context ID item not found: world_entry.manual:Basement Workshop",
        ):
            await run_node(
                ValidateContextIDItem(),
                scene=fs_scene,
                inputs={"value": "world_entry.manual:Basement Workshop"},
            )


# ---------------------------------------------------------------------------
# ValidateCharacter
# ---------------------------------------------------------------------------


def _add_actor_min(scene, name: str) -> Character:
    """Add a Character + Actor to a scene without going through the
    `add_actor` async pipeline (which would try to introduce the main
    character etc.). Mutates `scene.actors` and `scene.character_data`."""
    char = Character(name=name)
    actor = scene.Actor(char, None)
    actor.scene = scene
    scene.actors.append(actor)
    scene.character_data[name] = char
    return char


class TestValidateCharacter:
    @pytest.mark.asyncio
    async def test_existing_active_character_passes_through(self, fs_scene):
        char = _add_actor_min(fs_scene, "Alice")
        fs_scene.active_characters.append("Alice")

        node = ValidateCharacter()
        node.set_property("character_status", "all")
        out = await run_node(node, scene=fs_scene, inputs={"value": "Alice"})
        assert out["value"] == "Alice"
        assert out["character"] is char

    @pytest.mark.asyncio
    async def test_missing_character_raises(self, fs_scene):
        with pytest.raises(InputValueError):
            await run_node(
                ValidateCharacter(),
                scene=fs_scene,
                inputs={"value": "Ghost"},
            )

    @pytest.mark.asyncio
    async def test_create_placeholder_returns_new_character(self, fs_scene):
        # When the character is missing AND create_placeholder=True, the
        # validator creates a placeholder Character and emits it on
        # `character`. The character must NOT have been added to the scene.
        node = ValidateCharacter()
        node.set_property("create_placeholder", True)
        node.set_property("character_status", "all")
        out = await run_node(node, scene=fs_scene, inputs={"value": "Bob"})
        assert isinstance(out["character"], Character)
        assert out["character"].name == "Bob"
        # Not added to actor list / character_data
        assert "Bob" not in fs_scene.character_data

    @pytest.mark.asyncio
    async def test_active_required_raises_for_inactive(self, fs_scene):
        # An "inactive" character is one in `character_data` but not present
        # in `actors` — `inactive_characters` is derived from character_data
        # minus the active_characters list. Do not register an actor.
        char = Character(name="Carol")
        fs_scene.character_data["Carol"] = char
        # Note: do NOT add an actor or update active_characters.
        node = ValidateCharacter()
        node.set_property("character_status", "active")
        with pytest.raises(InputValueError, match="not active"):
            await run_node(node, scene=fs_scene, inputs={"value": "Carol"})

    @pytest.mark.asyncio
    async def test_inactive_required_raises_for_active(self, fs_scene):
        _add_actor_min(fs_scene, "Dora")
        fs_scene.active_characters.append("Dora")
        node = ValidateCharacter()
        node.set_property("character_status", "inactive")
        with pytest.raises(InputValueError, match="is active"):
            await run_node(node, scene=fs_scene, inputs={"value": "Dora"})


# ---------------------------------------------------------------------------
# ValidateAssetID
# ---------------------------------------------------------------------------


class TestValidateAssetID:
    @pytest.mark.asyncio
    async def test_existing_id_passes_and_emits_asset(self, fs_scene):
        a = await fs_scene.assets.add_asset(b"x", "png", "image/png")
        out = await run_node(ValidateAssetID(), scene=fs_scene, inputs={"value": a.id})
        assert out["value"] == a.id
        assert out["asset"].id == a.id

    @pytest.mark.asyncio
    async def test_missing_id_raises(self, fs_scene):
        with pytest.raises(InputValueError):
            await run_node(
                ValidateAssetID(), scene=fs_scene, inputs={"value": "absent"}
            )
