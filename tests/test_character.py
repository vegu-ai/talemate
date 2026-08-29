"""Unit tests for talemate.character: Character pydantic model, helpers, signals."""

import pytest

import talemate.emit.async_signals as async_signals
import talemate.instance as instance

from talemate.character import (
    Character,
    CharacterStatus,
    VoiceChangedEvent,
    activate_character,
    deactivate_character,
    list_characters,
    set_voice,
)
from talemate.agents.tts.schema import Voice
from talemate.scene_message import CharacterMessage
from talemate.tale_mate import Scene

from conftest import bootstrap_engine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_character():
    """Factory that builds a fully-formed Character with sensible defaults.

    Each test gets to override only the bits it cares about. The defaults
    populate enough attributes / details / dialogue examples to exercise
    serialization, dialogue selection, and rename helpers.
    """

    def _factory(**overrides):
        defaults = dict(
            name="Alice",
            description="A curious girl from England.",
            base_attributes={
                "gender": "female",
                "age": "12",
                "scenario_context": "Wonderland",
            },
            details={"hair": "blonde", "eyes": "blue"},
            example_dialogue=[
                "Alice: Oh dear, oh dear!",
                "Alice: Curiouser and curiouser!",
                "Alice: I wonder what's down there.",
            ],
            color="#abcdef",
        )
        defaults.update(overrides)
        return Character(**defaults)

    return _factory


@pytest.fixture
def isolated_voice_signal():
    """Replace the character.voice_changed receivers list and restore on
    teardown so tests don't leak handlers into one another."""
    sig = async_signals.get("character.voice_changed")
    saved = list(sig.receivers)
    sig.receivers.clear()
    yield sig
    sig.receivers.clear()
    sig.receivers.extend(saved)


@pytest.fixture
def bootstrap_engine_isolated():
    """Bootstrap the agent registry but restore it afterwards."""
    saved_agents = dict(instance.AGENTS)
    instance.AGENTS.clear()
    bootstrap_engine()
    yield
    instance.AGENTS.clear()
    instance.AGENTS.update(saved_agents)


# ---------------------------------------------------------------------------
# Construction & basic attribute access
# ---------------------------------------------------------------------------


class TestCharacterBasics:
    def test_minimal_construction_uses_defaults(self):
        c = Character(name="Bob")
        assert c.name == "Bob"
        assert c.description == ""
        assert c.color == "#fff"
        assert c.is_player is False
        assert c.base_attributes == {}
        assert c.details == {}
        assert c.example_dialogue == []
        assert c.voice is None

    def test_str_repr_use_character_name(self):
        c = Character(name="Bob")
        assert str(c) == "Character: Bob"
        assert repr(c) == "Character: Bob"

    def test_hash_is_based_on_name(self):
        a = Character(name="Bob")
        b = Character(name="Bob")
        c = Character(name="Eve")
        assert hash(a) == hash(b)
        assert hash(a) != hash(c)

    def test_acting_instructions_alias_for_dialogue_instructions(self):
        c = Character(name="Bob")
        c.acting_instructions = "Speak softly"
        assert c.dialogue_instructions == "Speak softly"
        assert c.acting_instructions == "Speak softly"

    def test_acting_instructions_validation_alias_on_init(self):
        # The pydantic AliasChoices accepts either alias.
        c = Character(name="Bob", acting_instructions="be brave")
        assert c.dialogue_instructions == "be brave"

    def test_gender_property_reads_from_base_attributes(self, make_character):
        c = make_character()
        assert c.gender == "female"

    def test_gender_defaults_to_empty_string(self):
        c = Character(name="Bob")
        assert c.gender == ""


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


class TestSetColor:
    def test_set_color_assigns_explicit_value(self):
        c = Character(name="Bob")
        c.set_color("#123456")
        assert c.color == "#123456"

    def test_set_color_with_none_picks_random_color(self):
        c = Character(name="Bob")
        original = c.color
        c.set_color(None)
        # The randomly chosen color must be a non-empty string
        assert c.color != original or len(c.color) > 0
        assert isinstance(c.color, str)
        assert c.color.startswith("#")


# ---------------------------------------------------------------------------
# sheet / sheet_filtered / filtered_sheet
# ---------------------------------------------------------------------------


class TestSheet:
    def test_sheet_lists_all_base_attributes(self, make_character):
        c = make_character()
        out = c.sheet
        assert "gender: female" in out
        assert "age: 12" in out
        assert "scenario_context: Wonderland" in out

    def test_sheet_falls_back_to_name_and_description_when_no_attrs(self):
        c = Character(name="Bob", description="A man")
        out = c.sheet
        assert "name: Bob" in out
        assert "description: A man" in out

    def test_sheet_filtered_excludes_named_keys_case_insensitive(self, make_character):
        c = make_character()
        out = c.sheet_filtered("AGE", "Gender")
        assert "age" not in out.lower()
        assert "gender" not in out.lower()
        assert "scenario_context" in out

    def test_filtered_sheet_includes_only_listed_attributes(self, make_character):
        c = make_character()
        out = c.filtered_sheet(["age"])
        assert out == "age: 12"


# ---------------------------------------------------------------------------
# Dialogue example helpers
# ---------------------------------------------------------------------------


class TestDialogueExamples:
    def test_random_dialogue_example_returns_one_of_examples(self, make_character):
        c = make_character()
        chosen = c.random_dialogue_example
        assert chosen in c.example_dialogue

    def test_random_dialogue_example_empty_returns_empty_string(self):
        c = Character(name="Bob")
        assert c.random_dialogue_example == ""

    def test_random_dialogue_examples_returns_unique_subset(self, make_character):
        c = make_character()
        examples = c._random_dialogue_examples(num=2)
        assert len(examples) == 2
        # No duplicates
        assert len(set(examples)) == 2
        assert all(e in c.example_dialogue for e in examples)

    def test_random_dialogue_examples_caps_at_available(self, make_character):
        c = make_character()
        # asking for 10 when only 3 exist must return at most 3
        examples = c._random_dialogue_examples(num=10)
        assert len(examples) == 3

    def test_random_dialogue_examples_strips_name_when_requested(self, make_character):
        c = make_character()
        examples = c._random_dialogue_examples(num=3, strip_name=True)
        for e in examples:
            assert not e.startswith("Alice:")

    def test_random_dialogue_examples_empty_returns_empty_list(self):
        c = Character(name="Bob")
        assert c._random_dialogue_examples(num=3) == []

    @pytest.mark.asyncio
    async def test_add_example_dialogue_appends_trimmed(self):
        c = Character(name="Bob")
        await c.add_example_dialogue("  Bob: Hello  ")
        assert c.example_dialogue == ["Bob: Hello"]

    @pytest.mark.asyncio
    async def test_add_example_dialogue_skips_empty(self):
        c = Character(name="Bob")
        await c.add_example_dialogue("   ")
        await c.add_example_dialogue(None)  # type: ignore[arg-type]
        assert c.example_dialogue == []

    @pytest.mark.asyncio
    async def test_add_example_dialogue_replaces_smart_quotes(self):
        c = Character(name="Bob")
        await c.add_example_dialogue("Bob: “Hello!” He waves. ‘Really.’")
        assert c.example_dialogue == ["Bob: \"Hello!\" He waves. 'Really.'"]

    @pytest.mark.asyncio
    async def test_set_example_dialogue_item_replaces_smart_quotes(
        self, make_character
    ):
        c = make_character()
        await c.set_example_dialogue_item(0, "Alice: “New line”")
        assert c.example_dialogue[0] == 'Alice: "New line"'

    @pytest.mark.asyncio
    async def test_set_example_dialogue_item_replaces_at_index(self, make_character):
        c = make_character()
        await c.set_example_dialogue_item(0, "Alice: New line")
        assert c.example_dialogue[0] == "Alice: New line"

    @pytest.mark.asyncio
    async def test_set_example_dialogue_item_out_of_range_is_noop(self, make_character):
        c = make_character()
        original = list(c.example_dialogue)
        await c.set_example_dialogue_item(99, "Alice: nope")
        await c.set_example_dialogue_item(-1, "Alice: nope")
        assert c.example_dialogue == original

    @pytest.mark.asyncio
    async def test_set_example_dialogue_item_with_empty_deletes(self, make_character):
        c = make_character()
        original_len = len(c.example_dialogue)
        await c.set_example_dialogue_item(0, "   ")
        assert len(c.example_dialogue) == original_len - 1

    @pytest.mark.asyncio
    async def test_remove_example_dialogue_deletes_at_index(self, make_character):
        c = make_character()
        first = c.example_dialogue[0]
        await c.remove_example_dialogue(0)
        assert first not in c.example_dialogue

    @pytest.mark.asyncio
    async def test_remove_example_dialogue_out_of_range_is_noop(self, make_character):
        c = make_character()
        original = list(c.example_dialogue)
        await c.remove_example_dialogue(99)
        await c.remove_example_dialogue(-1)
        assert c.example_dialogue == original

    @pytest.mark.asyncio
    async def test_set_acting_instructions_normalizes_empty_to_none(self):
        c = Character(name="Bob")
        await c.set_acting_instructions("")
        assert c.dialogue_instructions is None
        await c.set_acting_instructions(None)
        assert c.dialogue_instructions is None

    @pytest.mark.asyncio
    async def test_set_acting_instructions_stores_value(self):
        c = Character(name="Bob")
        await c.set_acting_instructions("Be solemn.")
        assert c.dialogue_instructions == "Be solemn."


# ---------------------------------------------------------------------------
# random_dialogue_examples (using a real Scene history)
# ---------------------------------------------------------------------------


class TestRandomDialogueExamplesFromScene:
    def test_short_history_uses_prepared_examples(self, make_character):
        c = make_character()
        scene = Scene()
        # No history -> below threshold; falls back to prepared examples.
        result = c.random_dialogue_examples(scene, num=2)
        assert len(result) == 2
        for r in result:
            assert "Alice" in r or "wonder" in r.lower() or "curious" in r.lower()

    def test_history_threshold_pulls_from_history(self, make_character):
        c = make_character()
        scene = Scene()
        # Inflate history past threshold (15) with character messages
        for i in range(20):
            scene.history.append(CharacterMessage(message=f"Alice: line {i}"))
        result = c.random_dialogue_examples(scene, num=3)
        assert len(result) == 3
        # All should derive from the history lines (prefix stripped).
        for r in result:
            assert r.startswith("line ")

    def test_history_examples_filtered_by_character_name(self, make_character):
        c = make_character()
        scene = Scene()
        # 20 messages, but only some belong to Alice
        for i in range(20):
            scene.history.append(CharacterMessage(message=f"Bob: irrelevant {i}"))
        # No Alice messages in history -> falls through to prepared examples
        result = c.random_dialogue_examples(scene, num=2)
        assert len(result) == 2
        for r in result:
            # These are pulled from prepared example_dialogue which all start with "Alice:"
            # but max_length truncation may trim the trailing portion.
            assert "Alice" in r or "wonder" in r.lower() or "curious" in r.lower()

    def test_max_length_truncates_history_examples(self, make_character):
        # max_length truncation only applies to the history-based path
        # (after the threshold). The prepared-example fallback returns
        # examples verbatim. Build enough history to push past threshold
        # so we exercise the truncation branch.
        c = make_character()
        scene = Scene()
        long_line = "Alice: " + "y" * 500
        for _ in range(20):
            scene.history.append(CharacterMessage(message=long_line))
        result = c.random_dialogue_examples(scene, num=1, max_length=20)
        assert len(result) == 1
        # strip_partial_sentences may drop incomplete sentences (returning ""),
        # but the slice itself must be at most max_length.
        assert len(result[0]) <= 20


# ---------------------------------------------------------------------------
# rename / introduce_main_character
# ---------------------------------------------------------------------------


class TestRename:
    def test_rename_updates_name(self):
        c = Character(name="Bob", description="Bob is brave.")
        c.rename("Robert")
        assert c.name == "Robert"
        assert c.description == "Robert is brave."
        assert c.memory_dirty

    def test_rename_replaces_in_base_attributes(self):
        c = Character(name="Bob", base_attributes={"bio": "Bob lives here"})
        c.rename("Robert")
        assert c.base_attributes["bio"] == "Robert lives here"

    def test_rename_replaces_in_details(self):
        c = Character(name="Bob", details={"intro": "Bob from town"})
        c.rename("Robert")
        assert c.details["intro"] == "Robert from town"

    def test_rename_from_you_does_not_replace_in_text(self):
        # When original name is "You", the helper short-circuits to avoid
        # mangling references to the player throughout the description.
        c = Character(name="You", description="You sing songs.")
        c.rename("Alice")
        assert c.name == "Alice"
        # Description must be untouched
        assert c.description == "You sing songs."


class TestIntroduceMainCharacter:
    def test_replaces_user_token_in_description(self):
        c = Character(
            name="Bob",
            description="{{user}} entered the room.",
            greeting_text="Hello, {{user}}!",
        )
        main = Character(name="Alice")
        c.introduce_main_character(main)
        assert c.description == "Alice entered the room."
        assert c.greeting_text == "Hello, Alice!"

    def test_replacement_is_case_insensitive(self):
        c = Character(name="Bob", description="{{USER}} and {{User}} chatted.")
        main = Character(name="Alice")
        c.introduce_main_character(main)
        assert c.description == "Alice and Alice chatted."

    def test_replaces_in_example_dialogue(self):
        c = Character(
            name="Bob",
            example_dialogue=["Bob: Welcome, {{user}}!", "Bob: Goodbye {{user}}"],
        )
        main = Character(name="Alice")
        c.introduce_main_character(main)
        assert c.example_dialogue == [
            "Bob: Welcome, Alice!",
            "Bob: Goodbye Alice",
        ]


# ---------------------------------------------------------------------------
# update / get/set helpers
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_assigns_attributes_and_marks_dirty(self):
        c = Character(name="Bob")
        c.update(description="updated", color="#000")
        assert c.description == "updated"
        assert c.color == "#000"
        assert c.memory_dirty

    def test_update_sets_voice_from_dict(self):
        c = Character(name="Bob")
        c.update(
            voice={"label": "Bob Voice", "provider": "kokoro", "provider_id": "v1"}
        )
        assert isinstance(c.voice, Voice)
        assert c.voice.label == "Bob Voice"

    def test_update_clears_voice_when_value_falsy(self):
        c = Character(
            name="Bob",
            voice=Voice(label="x", provider="kokoro", provider_id="v"),
        )
        c.update(voice=None)
        assert c.voice is None

    def test_set_detail_defer_does_not_touch_memory(self):
        c = Character(name="Bob")
        c.set_detail_defer("hair", "brown")
        assert c.details == {"hair": "brown"}
        assert c.memory_dirty

    def test_get_detail_returns_value(self, make_character):
        c = make_character()
        assert c.get_detail("hair") == "blonde"
        assert c.get_detail("nonexistent") is None

    def test_set_base_attribute_defer(self):
        c = Character(name="Bob")
        c.set_base_attribute_defer("age", "30")
        assert c.base_attributes == {"age": "30"}
        assert c.memory_dirty

    def test_get_base_attribute(self, make_character):
        c = make_character()
        assert c.get_base_attribute("age") == "12"
        assert c.get_base_attribute("nope") is None


# ---------------------------------------------------------------------------
# Shared context helpers
# ---------------------------------------------------------------------------


class TestSharedContext:
    @pytest.mark.asyncio
    async def test_set_shared_true_seeds_attributes_and_details(self, make_character):
        c = make_character()
        await c.set_shared(True)
        assert c.shared is True
        assert set(c.shared_attributes) == set(c.base_attributes.keys())
        assert set(c.shared_details) == set(c.details.keys())

    @pytest.mark.asyncio
    async def test_set_shared_false_clears_attributes(self, make_character):
        c = make_character()
        await c.set_shared(True)
        await c.set_shared(False)
        assert c.shared is False
        assert c.shared_attributes == []
        # set_shared_details is reseeded at the end regardless; verify it
        # contains the current details keys (a known oddity of the impl).
        assert set(c.shared_details) == set(c.details.keys())

    @pytest.mark.asyncio
    async def test_set_shared_attribute_adds_and_removes(self, make_character):
        c = make_character()
        await c.set_shared_attribute("age", True)
        assert "age" in c.shared_attributes
        await c.set_shared_attribute("age", False)
        assert "age" not in c.shared_attributes
        # Removing again is a no-op
        await c.set_shared_attribute("age", False)

    @pytest.mark.asyncio
    async def test_set_shared_detail_adds_and_removes(self, make_character):
        c = make_character()
        await c.set_shared_detail("hair", True)
        assert "hair" in c.shared_details
        await c.set_shared_detail("hair", False)
        assert "hair" not in c.shared_details

    @pytest.mark.asyncio
    async def test_apply_shared_context_copies_marked_attrs(self, make_character):
        a = make_character()  # source
        b = Character(name="Alice")  # destination

        await a.set_shared(True)
        # Restrict shared scope to only "age" to verify selective copying
        a.shared_attributes = ["age"]
        a.shared_details = ["hair"]
        # Move shared lists onto destination so apply_shared_context picks them up
        b.shared_attributes = ["age"]
        b.shared_details = ["hair"]

        await b.apply_shared_context(a)

        # Selectively shared keys propagate
        assert b.base_attributes == {"age": "12"}
        assert b.details == {"hair": "blonde"}
        # Top-level scalar fields are mirrored
        assert b.description == a.description
        assert b.memory_dirty

    @pytest.mark.asyncio
    async def test_apply_shared_context_propagates_folder_even_when_none(
        self, make_character
    ):
        a = make_character(folder=None)
        b = Character(name="Alice", folder="some/folder")
        await b.apply_shared_context(a)
        # `folder` is explicitly assigned even when source value is None,
        # because exclude_none=True would otherwise drop it.
        assert b.folder is None


# ---------------------------------------------------------------------------
# voice signal: set_voice + VoiceChangedEvent
# ---------------------------------------------------------------------------


class TestSetVoice:
    @pytest.mark.asyncio
    async def test_set_voice_updates_attribute(self, isolated_voice_signal):
        c = Character(name="Bob")
        new_voice = Voice(label="x", provider="kokoro", provider_id="v")

        emission = await set_voice(c, new_voice)

        assert c.voice is new_voice
        assert isinstance(emission, VoiceChangedEvent)
        assert emission.character is c
        assert emission.voice is new_voice
        assert emission.auto is False

    @pytest.mark.asyncio
    async def test_set_voice_clears_when_none(self, isolated_voice_signal):
        c = Character(
            name="Bob",
            voice=Voice(label="x", provider="kokoro", provider_id="v"),
        )

        emission = await set_voice(c, None)

        assert c.voice is None
        assert emission.voice is None

    @pytest.mark.asyncio
    async def test_set_voice_fires_async_signal(self, isolated_voice_signal):
        received = []

        async def handler(event: VoiceChangedEvent):
            received.append(event)

        isolated_voice_signal.connect(handler)

        c = Character(name="Bob")
        v = Voice(label="x", provider="kokoro", provider_id="v")
        await set_voice(c, v, auto=True)

        assert len(received) == 1
        assert received[0].character is c
        assert received[0].voice is v
        assert received[0].auto is True


# ---------------------------------------------------------------------------
# activate / deactivate / list_characters
# ---------------------------------------------------------------------------


class TestActivateDeactivate:
    @pytest.mark.asyncio
    async def test_activate_npc_adds_actor_and_marks_active(
        self, bootstrap_engine_isolated
    ):
        scene = Scene()
        char = Character(name="Bob", description="An NPC")
        scene.character_data["Bob"] = char

        result = await activate_character(scene, char)

        assert result is None or result is True
        assert "Bob" in scene.active_characters
        assert any(a.character is char for a in scene.actors)
        # NPC actor uses the conversation agent
        for actor in scene.actors:
            if actor.character is char:
                assert actor.agent is instance.AGENTS["conversation"]

    @pytest.mark.asyncio
    async def test_activate_player_uses_player_class(self, bootstrap_engine_isolated):
        scene = Scene()
        player = Character(name="Player", is_player=True)
        scene.character_data["Player"] = player

        await activate_character(scene, player)

        assert "Player" in scene.active_characters
        # The player actor has no agent
        for actor in scene.actors:
            if actor.character is player:
                assert actor.agent is None

    @pytest.mark.asyncio
    async def test_activate_already_active_returns_false(
        self, bootstrap_engine_isolated
    ):
        scene = Scene()
        char = Character(name="Bob")
        scene.character_data["Bob"] = char
        scene.active_characters.append("Bob")

        result = await activate_character(scene, char)

        assert result is False

    @pytest.mark.asyncio
    async def test_activate_with_string_name_resolves_via_scene(
        self, bootstrap_engine_isolated
    ):
        scene = Scene()
        char = Character(name="Bob")
        scene.character_data["Bob"] = char

        await activate_character(scene, "Bob")

        assert "Bob" in scene.active_characters

    @pytest.mark.asyncio
    async def test_deactivate_returns_false_when_not_active(
        self, bootstrap_engine_isolated
    ):
        scene = Scene()
        char = Character(name="Bob")
        scene.character_data["Bob"] = char

        result = await deactivate_character(scene, char)

        assert result is False

    @pytest.mark.asyncio
    async def test_deactivate_removes_actor_and_active_entry(
        self, bootstrap_engine_isolated
    ):
        scene = Scene()
        char = Character(name="Bob")
        scene.character_data["Bob"] = char
        await activate_character(scene, char)
        assert "Bob" in scene.active_characters

        await deactivate_character(scene, char)

        assert "Bob" not in scene.active_characters


class TestListCharacters:
    @pytest.mark.asyncio
    async def test_list_characters_returns_status_objects(
        self, bootstrap_engine_isolated, make_character
    ):
        scene = Scene()
        bob = make_character(name="Bob")
        alice = Character(name="Alice", is_player=True)
        scene.character_data["Bob"] = bob
        scene.character_data["Alice"] = alice
        await activate_character(scene, bob)

        result = await list_characters(scene)

        assert len(result) == 2
        by_name = {s.name: s for s in result}
        assert isinstance(by_name["Bob"], CharacterStatus)
        assert by_name["Bob"].active is True
        assert by_name["Bob"].is_player is False
        assert by_name["Alice"].active is False
        assert by_name["Alice"].is_player is True

    @pytest.mark.asyncio
    async def test_list_characters_truncates_long_descriptions(
        self, bootstrap_engine_isolated
    ):
        scene = Scene()
        long_desc = "x" * 500
        scene.character_data["Bob"] = Character(name="Bob", description=long_desc)

        result = await list_characters(scene, max_description_length=10)

        assert result[0].description.endswith("...")
        # original 10 chars + 3 dots
        assert len(result[0].description) == 13
