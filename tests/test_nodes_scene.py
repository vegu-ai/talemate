"""
Unit tests for src/talemate/game/engine/nodes/scene.py.

These tests instantiate node classes directly and invoke their `run` method
inside a `GraphContext` (so socket value setters can write to state) with the
`active_scene` contextvar bound to a real `Scene`. Where a node interacts with
agents (memory, conversation, director), real agent instances are wired up via
`bootstrap_scene` from conftest. LLM-bound and event-loop-bound nodes are
deliberately skipped.
"""

import pytest
import structlog

from talemate.character import Character
from talemate.context import ActiveScene, InteractionState
from talemate.game.engine.nodes.core import (
    GraphContext,
    GraphState,
    NodeVerbosity,
    InputValueError,
    UNRESOLVED,
)
from talemate.game.engine.nodes.scene import (
    ActivateCharacter,
    DeactivateCharacter,
    GetCharacter,
    GetCharacterAttribute,
    GetCharacterDescription,
    GetCharacterDetail,
    GetContentClassification,
    GetDescription,
    GetIntroduction,
    GetPlayerCharacter,
    GetSceneLoopState,
    GetSceneState,
    GetTitle,
    IsActiveCharacter,
    IsPlayerCharacter,
    ListCharacters,
    MakeCharacter,
    RemoveAllCharacters,
    RemoveCharacter,
    RestoreScene,
    SceneLoop,
    SetCharacterAttribute,
    SetCharacterDescription,
    SetCharacterDetail,
    SetContentClassification,
    SetDescription,
    SetIntroduction,
    SetTitle,
    TriggerGameLoopActorIter,
    UnpackCharacter,
    UnpackInteractionState,
    UpdateCharacterData,
    WaitForInput,
)
from talemate.game.engine.nodes.scene_messages import (
    CharacterMessage as CharacterMessageNode,
    DirectorMessage as DirectorMessageNode,
    NarratorMessage as NarratorMessageNode,
    ToggleMessageContextVisibility,
    UnpackMessageMeta,
)
import talemate.events as events
import talemate.scene_message as scene_message

from conftest import MockScene, bootstrap_scene

log = structlog.get_logger("tests.test_nodes_scene")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def scene():
    """Real Scene with bootstrapped agents (mock memory + mock client)."""
    s = MockScene()
    bootstrap_scene(s)
    return s


async def _add_character(
    scene,
    name: str,
    *,
    description: str = "",
    is_player: bool = False,
    base_attributes: dict | None = None,
    details: dict | None = None,
    color: str = "#fff",
):
    """Create and add a character (and matching actor) to the scene."""
    character = Character(
        name=name,
        description=description,
        is_player=is_player,
        base_attributes=base_attributes or {},
        details=details or {},
        color=color,
    )
    actor = scene.Player(character, None) if is_player else scene.Actor(character, None)
    await scene.add_actor(actor, commit_to_memory=False)
    if name not in scene.active_characters:
        scene.active_characters.append(name)
    return character


_RESERVED_PROPERTY_NAMES = {"title", "id"}


async def _run_node(
    node,
    scene,
    *,
    inputs: dict | None = None,
    verbosity: NodeVerbosity = NodeVerbosity.NORMAL,
    state_setup=None,
):
    """Run a node inside a GraphContext bound to the given scene.

    `inputs` is a dict of {input_name: value} pre-loaded onto the node as
    properties (via `set_property`). This is the simplest way to provide
    input values without wiring up a full producer node — the node's
    `get_input_value` falls back to the matching property when the input
    socket isn't connected. `state_setup(state)` may further customize the
    state (e.g. populate state.shared / state.data) before run. Returns a
    dict of {output_name: value} and {f"{name}__deactivated": bool} captured
    BEFORE the GraphContext is exited — socket `.value` reads are scoped to
    the active context."""
    if inputs:
        for k, v in inputs.items():
            if k in _RESERVED_PROPERTY_NAMES:
                # `name` is reserved on Node — fall back to direct dict assignment.
                node.properties[k] = v
            else:
                node.set_property(k, v)
    with ActiveScene(scene):
        with GraphContext() as state:
            state.verbosity = verbosity
            if state_setup:
                state_setup(state)
            await node.run(state)
            outputs = {sock.name: sock.value for sock in node.outputs}
            outputs.update(
                {f"{sock.name}__deactivated": sock.deactivated for sock in node.outputs}
            )
            return outputs


# ---------------------------------------------------------------------------
# GetSceneState
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_scene_state_returns_scene_settings_and_characters(scene):
    """GetSceneState exposes characters generator + the boolean flags
    + the scene reference."""
    await _add_character(scene, "Alice")
    scene.active = True
    # auto_save / auto_progress are read-only properties driven by config;
    # config.example.yaml defaults both to True.

    out = await _run_node(GetSceneState(), scene)

    assert [c.name for c in out["characters"]] == ["Alice"]
    assert out["active"] is True
    assert out["auto_save"] is True
    # MockScene.auto_progress always returns True
    assert out["auto_progress"] is True
    assert out["scene"] is scene


# ---------------------------------------------------------------------------
# MakeCharacter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_character_assigns_random_color_when_unset_and_adds_to_scene(scene):
    """Without a color input, MakeCharacter generates a random hex color and
    actually adds the resulting actor to the scene."""
    node = MakeCharacter()
    node.set_property("name", "Bob")
    node.set_property("color", UNRESOLVED)  # force random_color path
    node.set_property("base_attributes", {})
    node.set_property("is_player", False)
    node.set_property("add_to_scene", True)
    node.set_property("is_active", True)

    # use VERBOSE to also exercise the verbose log line at L222
    out = await _run_node(node, scene, verbosity=NodeVerbosity.VERBOSE)

    character = out["character"]
    actor = out["actor"]
    assert isinstance(character, Character)
    assert character.name == "Bob"
    # color should have been auto-generated to a non-empty hex string
    assert isinstance(character.color, str)
    assert character.color.startswith("#")
    assert character is actor.character
    # was added & activated
    assert "Bob" in scene.character_data
    assert "Bob" in [c.name for c in scene.characters]
    assert "Bob" in scene.active_characters


@pytest.mark.asyncio
async def test_make_character_player_uses_player_actor_class(scene):
    """is_player=True should produce a Player (not a plain Actor)."""
    node = MakeCharacter()
    node.set_property("name", "Hero")
    node.set_property("color", "#abcdef")
    node.set_property("base_attributes", {})
    node.set_property("is_player", True)
    node.set_property("add_to_scene", True)
    node.set_property("is_active", True)

    out = await _run_node(node, scene)

    actor = out["actor"]
    assert isinstance(actor, scene.Player)
    assert actor.character.is_player is True


@pytest.mark.asyncio
async def test_make_character_does_not_add_when_add_to_scene_false(scene):
    """add_to_scene=False must keep the character out of the scene."""
    node = MakeCharacter()
    node.set_property("name", "Lurker")
    node.set_property("color", "#123456")
    node.set_property("base_attributes", {})
    node.set_property("is_player", False)
    node.set_property("add_to_scene", False)
    node.set_property("is_active", True)

    out = await _run_node(node, scene)

    assert out["character"].name == "Lurker"
    assert "Lurker" not in scene.character_data
    assert "Lurker" not in scene.active_characters


# ---------------------------------------------------------------------------
# GetCharacter / GetPlayerCharacter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_character_returns_named_character(scene):
    await _add_character(scene, "Alice")
    await _add_character(scene, "Bob")

    node = GetCharacter()
    node.set_property("character_name", "Bob")
    out = await _run_node(node, scene)
    assert out["character"].name == "Bob"


@pytest.mark.asyncio
async def test_get_player_character_returns_first_player_actor(scene):
    await _add_character(scene, "NPC1")
    await _add_character(scene, "Hero", is_player=True)

    out = await _run_node(GetPlayerCharacter(), scene)
    assert out["character"].name == "Hero"


# ---------------------------------------------------------------------------
# ListCharacters
# ---------------------------------------------------------------------------


async def _two_chars_one_inactive(scene):
    await _add_character(scene, "Alice")
    await _add_character(scene, "Bob")
    bob = scene.character_data["Bob"]
    await scene.remove_actor(bob.actor)
    scene.active_characters.remove("Bob")


@pytest.mark.asyncio
async def test_list_characters_active_returns_only_active(scene):
    await _two_chars_one_inactive(scene)

    node = ListCharacters()
    node.set_property("character_status", "active")
    out = await _run_node(node, scene)
    names = sorted(c.name for c in out["characters"])
    assert names == ["Alice"]


@pytest.mark.asyncio
async def test_list_characters_inactive_returns_only_inactive(scene):
    await _two_chars_one_inactive(scene)

    node = ListCharacters()
    node.set_property("character_status", "inactive")
    out = await _run_node(node, scene)
    names = sorted(c.name for c in out["characters"])
    assert names == ["Bob"]


@pytest.mark.asyncio
async def test_list_characters_all_returns_active_and_inactive(scene):
    await _two_chars_one_inactive(scene)

    node = ListCharacters()
    node.set_property("character_status", "all")
    out = await _run_node(node, scene)
    names = sorted(c.name for c in out["characters"])
    assert names == ["Alice", "Bob"]


# ---------------------------------------------------------------------------
# IsActiveCharacter / IsPlayerCharacter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_active_character_yes_and_no(scene):
    alice = await _add_character(scene, "Alice")
    inactive_char = Character(name="Ghost")
    scene.character_data["Ghost"] = inactive_char  # not in actors

    out_yes = await _run_node(IsActiveCharacter(), scene, inputs={"character": alice})
    assert out_yes["active"] is True

    out_no = await _run_node(
        IsActiveCharacter(), scene, inputs={"character": inactive_char}
    )
    assert out_no["active"] is False


@pytest.mark.asyncio
async def test_is_player_character_routes_yes_path(scene):
    """IsPlayerCharacter must deactivate the no-output and emit yes=True for
    a player character (and exercise the verbose log)."""
    hero = await _add_character(scene, "Hero", is_player=True)

    out = await _run_node(
        IsPlayerCharacter(),
        scene,
        inputs={"character": hero},
        verbosity=NodeVerbosity.VERBOSE,
    )
    assert out["yes"] is True
    assert out["no"] is UNRESOLVED
    assert out["yes__deactivated"] is False
    assert out["no__deactivated"] is True


@pytest.mark.asyncio
async def test_is_player_character_routes_no_path(scene):
    npc = await _add_character(scene, "NPC")

    out = await _run_node(IsPlayerCharacter(), scene, inputs={"character": npc})
    assert out["yes"] is UNRESOLVED
    assert out["no"] is True
    assert out["yes__deactivated"] is True
    assert out["no__deactivated"] is False


# ---------------------------------------------------------------------------
# UnpackCharacter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpack_character_emits_individual_fields(scene):
    char = await _add_character(
        scene,
        "Alice",
        description="A brave hero.",
        base_attributes={"age": "30"},
        details={"hometown": "Riverdale"},
        color="#abcdef",
    )

    out = await _run_node(UnpackCharacter(), scene, inputs={"character": char})

    assert out["name"] == "Alice"
    assert out["is_player"] is False
    assert out["description"] == "A brave hero."
    assert out["base_attributes"] == {"age": "30"}
    assert out["details"] == {"hometown": "Riverdale"}
    assert out["color"] == "#abcdef"
    assert out["actor"] is char.actor


# ---------------------------------------------------------------------------
# UpdateCharacterData
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_character_data_applies_each_provided_field(scene):
    char = await _add_character(scene, "Alice", description="Original")

    out = await _run_node(
        UpdateCharacterData(),
        scene,
        inputs={
            "character": char,
            "base_attributes": {"age": "31"},
            "details": {"city": "Somewhere"},
            "description": "Updated",
            "name": "Alicia",
            "color": "#ff00ff",
        },
    )

    assert char.name == "Alicia"
    assert char.description == "Updated"
    assert char.base_attributes == {"age": "31"}
    assert char.details == {"city": "Somewhere"}
    assert char.color == "#ff00ff"
    assert out["character"] is char


@pytest.mark.asyncio
async def test_update_character_data_skips_unset_fields(scene):
    char = await _add_character(
        scene,
        "Alice",
        description="Original",
        base_attributes={"age": "30"},
        color="#abc",
    )

    # Don't supply any optional inputs, leave properties UNRESOLVED.
    await _run_node(UpdateCharacterData(), scene, inputs={"character": char})

    assert char.name == "Alice"
    assert char.description == "Original"
    assert char.base_attributes == {"age": "30"}
    assert char.color == "#abc"


# ---------------------------------------------------------------------------
# Get/SetCharacterAttribute / Detail / Description
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_character_attribute_returns_value_and_context_id(scene):
    char = await _add_character(
        scene, "Alice", base_attributes={"age": "30", "role": "knight"}
    )

    node = GetCharacterAttribute()
    node.set_property("name", "age")
    out = await _run_node(node, scene, inputs={"character": char})

    assert out["character"] is char
    assert out["name"] == "age"
    assert out["value"] == "30"
    assert out["context_id"] is not None  # CharacterAttributeContextID instance


@pytest.mark.asyncio
async def test_get_character_attribute_missing_returns_none(scene):
    char = await _add_character(scene, "Alice", base_attributes={"age": "30"})

    node = GetCharacterAttribute()
    node.set_property("name", "no_such_attr")
    out = await _run_node(node, scene, inputs={"character": char})

    assert out["value"] is None
    assert out["context_id"] is None


@pytest.mark.asyncio
async def test_set_character_attribute_writes_to_character(scene):
    char = await _add_character(scene, "Alice", base_attributes={})

    node = SetCharacterAttribute()
    node.set_property("name", "color_eye")
    out = await _run_node(node, scene, inputs={"character": char, "value": "blue"})

    assert char.base_attributes["color_eye"] == "blue"
    assert out["name"] == "color_eye"
    assert out["value"] == "blue"
    assert out["character"] is char


@pytest.mark.asyncio
async def test_get_character_detail_returns_value_and_context_id(scene):
    char = await _add_character(scene, "Alice", details={"hometown": "Riverdale"})

    node = GetCharacterDetail()
    node.set_property("name", "hometown")
    out = await _run_node(node, scene, inputs={"character": char})

    assert out["detail"] == "Riverdale"
    assert out["context_id"] is not None


@pytest.mark.asyncio
async def test_get_character_detail_missing_returns_none(scene):
    char = await _add_character(scene, "Alice", details={})

    node = GetCharacterDetail()
    node.set_property("name", "no_such_detail")
    out = await _run_node(node, scene, inputs={"character": char})

    assert out["detail"] is None
    assert out["context_id"] is None


@pytest.mark.asyncio
async def test_set_character_detail_writes_to_character(scene):
    char = await _add_character(scene, "Alice")

    node = SetCharacterDetail()
    node.set_property("name", "hometown")
    out = await _run_node(node, scene, inputs={"character": char, "value": "Riverdale"})

    assert char.details["hometown"] == "Riverdale"
    assert out["value"] == "Riverdale"


@pytest.mark.asyncio
async def test_get_character_description_returns_description(scene):
    char = await _add_character(scene, "Alice", description="Brave knight.")
    out = await _run_node(GetCharacterDescription(), scene, inputs={"character": char})

    assert out["description"] == "Brave knight."
    assert out["character"] is char


@pytest.mark.asyncio
async def test_set_character_description_overwrites_when_provided(scene):
    char = await _add_character(scene, "Alice", description="Old")

    out = await _run_node(
        SetCharacterDescription(),
        scene,
        inputs={
            "character": char,
            "description": "New description",
            "state": "STATE",
        },
    )

    assert char.description == "New description"
    assert out["description"] == "New description"
    assert out["character"] is char
    assert out["state"] == "STATE"


@pytest.mark.asyncio
async def test_set_character_description_falls_back_to_empty_string(scene):
    """When neither input nor property is set, description normalizes to ''."""
    char = await _add_character(scene, "Alice", description="Old")
    # leave property at default ''
    await _run_node(SetCharacterDescription(), scene, inputs={"character": char})
    assert char.description == ""


# ---------------------------------------------------------------------------
# UnpackInteractionState
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpack_interaction_state_emits_fields(scene):
    interaction = InteractionState(
        act_as="Alice",
        from_choice="choice-1",
        input="hello",
        reset_requested=True,
    )

    out = await _run_node(
        UnpackInteractionState(), scene, inputs={"interaction_state": interaction}
    )

    assert out["act_as"] == "Alice"
    assert out["from_choice"] == "choice-1"
    assert out["input"] == "hello"
    assert out["reset_requested"] is True


@pytest.mark.asyncio
async def test_unpack_interaction_state_rejects_non_interaction_state(scene):
    with pytest.raises(InputValueError):
        await _run_node(
            UnpackInteractionState(),
            scene,
            inputs={"interaction_state": {"act_as": "Alice"}},
        )


# ---------------------------------------------------------------------------
# CharacterMessage / NarratorMessage / DirectorMessage / UnpackMessageMeta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_character_message_node_prefixes_and_attaches_avatar_and_choice(scene):
    char = await _add_character(scene, "Alice")
    char.current_avatar = "alice-avatar"

    node = CharacterMessageNode()
    node.set_property("source", "ai")
    out = await _run_node(
        node,
        scene,
        inputs={
            "character": char,
            "message": "Hello there!",
            "from_choice": "greeting-option",
            "source": "ai",
        },
    )

    msg = out["message"]
    assert isinstance(msg, scene_message.CharacterMessage)
    # name prefix added
    assert msg.message == "Alice: Hello there!"
    assert msg.source == "ai"
    assert msg.from_choice == "greeting-option"
    assert msg.asset_id == "alice-avatar"
    assert msg.asset_type == "avatar"


@pytest.mark.asyncio
async def test_character_message_node_keeps_existing_prefix(scene):
    char = await _add_character(scene, "Alice")
    out = await _run_node(
        CharacterMessageNode(),
        scene,
        inputs={
            "character": char,
            "message": "Alice: Already prefixed",
            "source": "player",
        },
    )
    assert out["message"].message == "Alice: Already prefixed"


@pytest.mark.asyncio
async def test_narrator_message_node_attaches_meta_when_provided(scene):
    meta = {"agent": "narrator", "function": "narrate", "arguments": {}}
    out = await _run_node(
        NarratorMessageNode(),
        scene,
        inputs={"message": "The wind howls.", "source": "ai", "meta": meta},
    )

    msg = out["message"]
    assert isinstance(msg, scene_message.NarratorMessage)
    assert msg.message == "The wind howls."
    assert msg.meta == meta


@pytest.mark.asyncio
async def test_director_message_node_sets_character_meta_when_character_provided(scene):
    char = await _add_character(scene, "Alice")
    out = await _run_node(
        DirectorMessageNode(),
        scene,
        inputs={
            "message": "Stay calm",
            "source": "ai",
            "action": "actor_instruction",
            "character": char,
            "meta": {"foo": "bar"},
        },
    )

    msg = out["message"]
    assert isinstance(msg, scene_message.DirectorMessage)
    assert msg.action == "actor_instruction"
    assert msg.source == "ai"
    assert msg.meta["character"] == "Alice"
    assert msg.meta["foo"] == "bar"
    assert out["character"] is char
    assert out["source"] == "ai"


@pytest.mark.asyncio
async def test_director_message_node_without_character_does_not_set_meta(scene):
    out = await _run_node(
        DirectorMessageNode(),
        scene,
        inputs={
            "message": "Generic direction",
            "source": "ai",
            "action": "actor_instruction",
        },
    )
    msg = out["message"]
    assert msg.meta is None or "character" not in (msg.meta or {})


@pytest.mark.asyncio
async def test_unpack_message_meta_extracts_components(scene):
    meta = {
        "agent": "narrator",
        "function": "narrate_query",
        "arguments": {"query": "what next?"},
    }
    out = await _run_node(UnpackMessageMeta(), scene, inputs={"meta": meta})

    assert out["agent_name"] == "narrator"
    assert out["function_name"] == "narrate_query"
    assert out["arguments"] == {"query": "what next?"}
    # arguments must be a copy, not the same dict reference
    assert out["arguments"] is not meta["arguments"]


@pytest.mark.asyncio
async def test_unpack_message_meta_uses_empty_dict_when_arguments_missing(scene):
    meta = {"agent": "director", "function": "act"}
    out = await _run_node(UnpackMessageMeta(), scene, inputs={"meta": meta})
    assert out["arguments"] == {}


# ---------------------------------------------------------------------------
# ToggleMessageContextVisibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_message_context_visibility_hides_message(scene):
    msg = scene_message.NarratorMessage("Some narration", source="ai")
    assert not msg.hidden

    node = ToggleMessageContextVisibility()
    node.set_property("hidden", True)
    out = await _run_node(node, scene, inputs={"message": msg})

    assert bool(msg.hidden)
    assert out["message"] is msg


@pytest.mark.asyncio
async def test_toggle_message_context_visibility_unhides_message(scene):
    msg = scene_message.NarratorMessage("Some narration", source="ai")
    msg.hide()
    assert bool(msg.hidden)

    node = ToggleMessageContextVisibility()
    node.set_property("hidden", False)
    out = await _run_node(node, scene, inputs={"message": msg})

    assert not msg.hidden
    assert out["message"] is msg


# ---------------------------------------------------------------------------
# ActivateCharacter / DeactivateCharacter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_character_adds_to_active_set(scene):
    """A character that exists only in character_data gets activated and joins
    scene.actors."""
    inactive = Character(name="Ghost")
    scene.character_data["Ghost"] = inactive

    await _run_node(ActivateCharacter(), scene, inputs={"character": inactive})

    assert "Ghost" in scene.active_characters
    assert "Ghost" in [c.name for c in scene.characters]


@pytest.mark.asyncio
async def test_deactivate_character_removes_from_active_set(scene):
    char = await _add_character(scene, "Alice")
    assert "Alice" in scene.active_characters

    await _run_node(DeactivateCharacter(), scene, inputs={"character": char})

    assert "Alice" not in scene.active_characters


# ---------------------------------------------------------------------------
# RemoveAllCharacters / RemoveCharacter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_all_characters_clears_actors(scene):
    await _add_character(scene, "Alice")
    await _add_character(scene, "Bob")
    assert len(scene.actors) == 2

    out = await _run_node(RemoveAllCharacters(), scene)

    assert scene.actors == []
    assert scene.character_data == {}
    # state output is the GraphState itself
    assert isinstance(out["state"], GraphState)


@pytest.mark.asyncio
async def test_remove_character_removes_named_character_only(scene):
    alice = await _add_character(scene, "Alice")
    await _add_character(scene, "Bob")

    await _run_node(
        RemoveCharacter(),
        scene,
        inputs={"character": alice, "state": "STATE"},
    )

    remaining = [a.character.name for a in scene.actors]
    assert remaining == ["Bob"]
    assert "Alice" not in scene.character_data


# ---------------------------------------------------------------------------
# GetSceneLoopState
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_scene_loop_state_returns_data_and_shared_no_outer(scene):
    def setup(state):
        state.data["k"] = "v"
        state.shared["s"] = 42

    out = await _run_node(GetSceneLoopState(), scene, state_setup=setup)
    # `state` (data dict) should have our injected key
    assert out["state"].get("k") == "v"
    # No outer state set in this context
    assert out["parent"] == {}
    assert out["shared"].get("s") == 42


@pytest.mark.asyncio
async def test_get_scene_loop_state_uses_outer_when_set(scene):
    """When state.outer is set, parent reflects state.outer.data."""
    node = GetSceneLoopState()
    outer = GraphState()
    outer.data["from_outer"] = True

    with ActiveScene(scene):
        # Manually create an inner state with explicit outer; emulate what
        # GraphContext does, but without losing the outer linkage.
        with GraphContext(outer_state=outer) as state:
            await node.run(state)
            outputs = {sock.name: sock.value for sock in node.outputs}

    assert outputs["parent"] == {"from_outer": True}


# ---------------------------------------------------------------------------
# RestoreScene
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_scene_returns_state_when_no_restore_source(scene):
    """With restore_from unset, scene.restore() short-circuits without raising,
    and the node still propagates state through."""
    assert scene.restore_from is None

    # The node passes back the *state* GraphState object (not the input).
    with ActiveScene(scene):
        with GraphContext() as state:
            state.set_node_socket_value(RestoreScene(), "state", "STATE-OBJ")
            node = RestoreScene()
            await node.run(state)
            assert node.get_output_socket("state").value is state


# ---------------------------------------------------------------------------
# GetTitle / SetTitle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_title_falls_back_to_scene_name_when_title_blank(scene):
    scene.title = ""
    scene.name = "FallbackName"
    out = await _run_node(GetTitle(), scene)
    assert out["title"] == "FallbackName"


@pytest.mark.asyncio
async def test_get_title_returns_explicit_title(scene):
    scene.title = "Explicit Title"
    out = await _run_node(GetTitle(), scene)
    assert out["title"] == "Explicit Title"


@pytest.mark.asyncio
async def test_set_title_updates_scene_and_emits_old_and_new(scene):
    scene.title = "Old Title"
    scene.name = ""

    out = await _run_node(
        SetTitle(),
        scene,
        inputs={"new_title": "Brand New", "state": "STATE"},
    )

    assert scene.title == "Brand New"
    assert out["new_title"] == "Brand New"
    assert out["old_title"] == "Old Title"
    # state output is the GraphState object itself
    assert isinstance(out["state"], GraphState)


@pytest.mark.asyncio
async def test_set_title_raises_when_title_blank(scene):
    with pytest.raises(InputValueError):
        await _run_node(SetTitle(), scene, inputs={"new_title": ""})


# ---------------------------------------------------------------------------
# GetDescription / SetDescription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_description_returns_scene_description(scene):
    scene.description = "A long description."
    out = await _run_node(GetDescription(), scene)
    assert out["description"] == "A long description."


@pytest.mark.asyncio
async def test_set_description_updates_scene(scene):
    scene.description = "old"
    out = await _run_node(
        SetDescription(),
        scene,
        inputs={"description": "new", "state": "STATE"},
    )
    assert scene.description == "new"
    assert out["description"] == "new"


# ---------------------------------------------------------------------------
# GetContentClassification / SetContentClassification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_content_classification_returns_scene_context(scene):
    scene.context = "fantasy adventure"
    out = await _run_node(GetContentClassification(), scene)
    assert out["content_classification"] == "fantasy adventure"


@pytest.mark.asyncio
async def test_set_content_classification_writes_within_max_length(scene):
    node = SetContentClassification()
    node.set_property("max_length", 75)
    out = await _run_node(
        node, scene, inputs={"content_classification": "horror", "state": "STATE"}
    )
    assert scene.context == "horror"
    assert out["content_classification"] == "horror"


@pytest.mark.asyncio
async def test_set_content_classification_rejects_too_long_value(scene):
    node = SetContentClassification()
    node.set_property("max_length", 5)
    with pytest.raises(InputValueError):
        await _run_node(node, scene, inputs={"content_classification": "way too long"})


# ---------------------------------------------------------------------------
# GetIntroduction / SetIntroduction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_introduction_returns_scene_intro(scene):
    scene.intro = "Once upon a time."
    out = await _run_node(GetIntroduction(), scene)
    assert out["introduction"] == "Once upon a time."


@pytest.mark.asyncio
async def test_set_introduction_writes_intro_without_emitting_history(scene):
    """emit_history=False keeps the test lean (no main_character required)."""
    scene.intro = "Old"
    node = SetIntroduction()
    node.set_property("introduction", "Brand new intro")
    node.set_property("emit_history", False)
    out = await _run_node(node, scene, inputs={"state": "STATE"})

    assert scene.get_intro() == "Brand new intro"
    assert out["state"] == "STATE"


@pytest.mark.asyncio
async def test_set_introduction_requires_introduction_input(scene):
    with pytest.raises(InputValueError):
        # leave introduction property UNRESOLVED
        await _run_node(SetIntroduction(), scene)


# ---------------------------------------------------------------------------
# TriggerGameLoopActorIter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_game_loop_actor_iter_signal_name_is_fixed():
    """The subclass overrides signal_name to a fixed identifier."""
    node = TriggerGameLoopActorIter()
    assert node.signal_name == "game_loop_actor_iter"


@pytest.mark.asyncio
async def test_trigger_game_loop_actor_iter_make_event_object_uses_actor_input(scene):
    """`make_event_object` packages the actor input + shared.game_loop into
    a GameLoopActorIterEvent."""
    char = await _add_character(scene, "Alice")
    game_loop_event = events.GameLoopEvent(
        scene=scene, event_type="game_loop", had_passive_narration=False
    )

    node = TriggerGameLoopActorIter()
    # `actor` input falls back to the same-named property when the socket
    # isn't connected.
    node.set_property("actor", char.actor)
    with ActiveScene(scene):
        with GraphContext() as state:
            state.shared["game_loop"] = game_loop_event
            evt = node.make_event_object(state)

    assert isinstance(evt, events.GameLoopActorIterEvent)
    assert evt.scene is scene
    assert evt.actor is char.actor
    assert evt.game_loop is game_loop_event


@pytest.mark.asyncio
async def test_trigger_game_loop_actor_iter_after_routes_player_signal(scene):
    """When the actor's character.is_player, after() routes to the player
    iter signal; otherwise to the AI iter signal. Verify by attaching ad-hoc
    receivers."""
    import talemate.emit.async_signals as async_signals

    player = await _add_character(scene, "Hero", is_player=True)
    npc = await _add_character(scene, "NPC")

    node = TriggerGameLoopActorIter()
    game_loop_event = events.GameLoopEvent(
        scene=scene, event_type="game_loop", had_passive_narration=False
    )
    state = GraphState()
    state.shared["game_loop"] = game_loop_event

    received_player: list = []
    received_ai: list = []

    async def on_player(evt):
        received_player.append(evt)

    async def on_ai(evt):
        received_ai.append(evt)

    async_signals.get("game_loop_player_character_iter").connect(on_player)
    async_signals.get("game_loop_ai_character_iter").connect(on_ai)
    try:
        evt_player = events.GameLoopActorIterEvent(
            scene=scene,
            event_type="game_loop_actor_iter",
            actor=player.actor,
            game_loop=game_loop_event,
        )
        with ActiveScene(scene):
            await node.after(state, evt_player)
        assert len(received_player) == 1
        assert len(received_ai) == 0

        evt_ai = events.GameLoopActorIterEvent(
            scene=scene,
            event_type="game_loop_actor_iter",
            actor=npc.actor,
            game_loop=game_loop_event,
        )
        with ActiveScene(scene):
            await node.after(state, evt_ai)
        assert len(received_player) == 1
        assert len(received_ai) == 1
    finally:
        async_signals.get("game_loop_player_character_iter").disconnect(on_player)
        async_signals.get("game_loop_ai_character_iter").disconnect(on_ai)


# ---------------------------------------------------------------------------
# WaitForInput.execute_node_command (parsing only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_input_execute_node_command_unknown_returns_false(scene):
    """When the command is not in state.data['_commands'], returns False
    without scheduling anything."""
    node = WaitForInput()
    with ActiveScene(scene):
        with GraphContext() as state:
            state.data["_commands"] = {}  # empty registry
            result = await node.execute_node_command(state, "!nope:arg1;arg2")
            assert result is False


@pytest.mark.asyncio
async def test_wait_for_input_execute_node_command_handles_no_args(scene):
    """A command without ':' should still parse — command_name is the bare
    word and the args list contains a single empty string."""
    node = WaitForInput()
    with ActiveScene(scene):
        with GraphContext() as state:
            state.data["_commands"] = {}
            # Even with no colon, this should not raise a ValueError; the
            # function falls into its except-ValueError branch.
            result = await node.execute_node_command(state, "!bareCmd")
            assert result is False


@pytest.mark.asyncio
async def test_wait_for_input_execute_node_command_strips_leading_bang_and_spaces(
    scene,
):
    """Command-name parsing must strip a leading `!` and surrounding spaces
    before consulting the registry; the lookup miss returns False."""
    node = WaitForInput()
    with ActiveScene(scene):
        with GraphContext() as state:
            state.data["_commands"] = {"actual_cmd": "talemate/scene/SomeNode"}
            # Surrounding spaces and a missing colon both exercise parsing.
            result = await node.execute_node_command(state, "  !  spaced_cmd  ")
            assert result is False  # not in registry


# ---------------------------------------------------------------------------
# SceneLoop scene_loop_event property
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scene_loop_event_property_uses_active_scene(scene):
    loop = SceneLoop()
    with ActiveScene(scene):
        evt = loop.scene_loop_event
    assert evt.scene is scene
    assert evt.event_type == "scene_loop"
