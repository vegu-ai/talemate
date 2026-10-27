"""
Tests for ``talemate.agents.conversation`` (the ConversationAgent class).

Targets:
- Action registration (``init_actions``) and the property accessors
  (``content_use_*``, ``generation_settings_*``,
  ``inject_character_names_into_stop``).
- ``agent_details`` populated dictionary.
- ``set_generation_overrides`` writing context attributes when enabled.
- ``clean_result`` post-processing of LLM output.
- ``allow_repetition_break`` and the character-name stopping strings the
  agent/client handshake produces.
- ``converse`` happy path through ``Prompt.request`` mock for both
  movie_script and narrative formats, including character-name
  prefix handling.
- ``converse`` raises GenerationCancelled when the LLM returns empty.

The full ``build_prompt_default`` pathway is left to template-baseline
tests; here we patch ``build_prompt`` so converse can be tested end-to-end.
"""

import pytest

import talemate.client.context as client_context_module
import talemate.instance as instance
from talemate.agents.conversation import (
    ConversationAgent,
)
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.prompts.base import Prompt
from talemate.scene_message import CharacterMessage
from talemate.tale_mate import Actor, Player

from conftest import MockScene, bootstrap_scene


def _canned_prompt(raw: str, extracted: dict) -> Prompt:
    """Build a real ``Prompt`` whose ``send`` returns canned LLM output.

    The function-under-test (``ConversationAgent.converse``) calls
    ``await prompt.send(client, kind="conversation")``. We construct a real
    ``Prompt`` and shadow ``send`` on the instance — the surrounding contract
    (the ``Prompt`` class itself, its constructor fields, and the ``send``
    method's signature) stays anchored to the real production type. Renaming
    ``Prompt`` or removing ``.send`` on the real class fails the test instead
    of being papered over.
    """
    prompt = Prompt(
        uid="conversation.test",
        agent_type="conversation",
        name="test",
        vars={},
    )

    async def _send(client, kind, **kwargs):
        return raw, extracted

    # Bypass pydantic's strict field-only assignment to shadow send on this
    # instance; pydantic forbids `prompt.send = ...` because `send` is not a
    # declared field.
    object.__setattr__(prompt, "send", _send)
    return prompt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alice():
    return Character(name="Alice", description="Test character.", is_player=False)


@pytest.fixture
def bob_player():
    return Character(name="Bob", description="Player.", is_player=True)


@pytest.fixture
def conversation_scene(alice, bob_player):
    """Bootstrapped MockScene with conversation agent + actors."""
    scene = MockScene()
    agents = bootstrap_scene(scene)
    conversation = agents["conversation"]

    # Wire actor/character relationships so that scene.character_names
    # and actor.character.actor.scene work.
    alice_actor = Actor(character=alice, agent=conversation)
    alice_actor.scene = scene
    scene.actors.append(alice_actor)
    scene.active_characters.append(alice.name)
    scene.character_data[alice.name] = alice

    bob_actor = Player(character=bob_player, agent=None)
    bob_actor.scene = scene
    scene.actors.append(bob_actor)
    scene.active_characters.append(bob_player.name)
    scene.character_data[bob_player.name] = bob_player

    with ActiveScene(scene):
        yield scene, conversation, alice_actor


# ---------------------------------------------------------------------------
# Action registration and properties
# ---------------------------------------------------------------------------


class TestActionRegistration:
    def test_actions_present(self, conversation_scene):
        _, conversation, _ = conversation_scene
        for key in ["generation_override", "content"]:
            assert key in conversation.actions

    def test_init_actions_returns_full_set(self):
        actions = ConversationAgent.init_actions()
        assert "generation_override" in actions
        assert "content" in actions
        assert "prompt_caching" in actions

    def test_generation_has_no_format(self, conversation_scene):
        _, conversation, _ = conversation_scene
        assert "format" not in conversation.actions["generation_override"].config

    def test_generation_note_opens_scene_history(self, conversation_scene):
        _, conversation, _ = conversation_scene
        note = conversation.actions["generation_override"].note
        assert "Scene History" in note.text
        [action] = note.actions
        assert action.action_name == "openAgentSettings"
        assert action.arguments == ["summarizer", "manage_scene_history"]

    def test_generation_setting_properties(self, conversation_scene):
        _, conversation, _ = conversation_scene
        gen_override = conversation.actions["generation_override"]

        gen_override.config["instructions"].value = "be cool"
        gen_override.config["actor_instructions"].value = "act"
        gen_override.config["actor_instructions_offset"].value = 5
        gen_override.config["length"].value = 256
        gen_override.config["inject_character_names_into_stop"].value = False

        assert conversation.generation_settings_task_instructions == "be cool"
        assert conversation.generation_settings_actor_instructions == "act"
        assert conversation.generation_settings_actor_instructions_offset == 5
        assert conversation.generation_settings_response_length == 256
        assert conversation.inject_character_names_into_stop is False
        assert conversation.generation_settings_override_enabled is True

    def test_content_properties(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["content"].config["use_scene_intent"].value = False
        conversation.actions["content"].config["use_writing_style"].value = False
        assert conversation.content_use_scene_intent is False
        assert conversation.content_use_writing_style is False
        conversation.actions["content"].config["use_scene_intent"].value = True
        conversation.actions["content"].config["use_writing_style"].value = True
        assert conversation.content_use_scene_intent is True
        assert conversation.content_use_writing_style is True


# ---------------------------------------------------------------------------
# agent_details
# ---------------------------------------------------------------------------


class TestAgentDetails:
    def test_includes_client_only(self, conversation_scene):
        _, conversation, _ = conversation_scene
        details = conversation.agent_details
        assert details["client"]["value"] == conversation.client.name
        assert "format" not in details


# ---------------------------------------------------------------------------
# set_generation_overrides
# ---------------------------------------------------------------------------


class TestSetGenerationOverrides:
    def test_ignores_a_disabled_flag_on_the_override(self, conversation_scene):
        # `generation_override` is can_be_disabled=False, so `resolve_enabled`
        # reports it on regardless of a stored flag and the early return in
        # `set_generation_overrides` is unreachable — every attribute is still
        # written.
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].enabled = False
        conversation.actions["generation_override"].config["length"].value = 333

        with client_context_module.ClientContext():
            conversation.set_generation_overrides()
            data = client_context_module.context_data.get()
            assert data["conversation"]["length"] == 333
            assert data["conversation"]["inject_character_names"] is True

    def test_writes_length_to_conversation_context(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].enabled = True
        conversation.actions["generation_override"].config["length"].value = 333

        with client_context_module.ClientContext():
            conversation.set_generation_overrides()
            # ``set_conversation_context_attribute`` writes through the
            # nested "conversation" dict.
            data = client_context_module.context_data.get()
            assert data["conversation"]["length"] == 333

    def test_jiggle_sets_nuke_repetition(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].enabled = True
        conversation.actions["generation_override"].config["jiggle"].value = 0.5

        with client_context_module.ClientContext():
            # Default nuke_repetition is 0.0 -> override applied.
            conversation.set_generation_overrides()
            assert (
                client_context_module.client_context_attribute("nuke_repetition") == 0.5
            )

    def test_jiggle_skipped_when_existing_nuke_repetition(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].enabled = True
        conversation.actions["generation_override"].config["jiggle"].value = 0.5

        with client_context_module.ClientContext(nuke_repetition=0.7):
            conversation.set_generation_overrides()
            # Existing nuke_repetition is preserved.
            assert (
                client_context_module.client_context_attribute("nuke_repetition") == 0.7
            )


# ---------------------------------------------------------------------------
# clean_result
# ---------------------------------------------------------------------------


class TestCleanResult:
    def test_empty_input_returns_empty(self, conversation_scene, alice):
        _, conversation, _ = conversation_scene
        assert conversation.clean_result("", alice) == ""
        assert conversation.clean_result(None, alice) == ""

    def test_strips_after_hash(self, conversation_scene, alice):
        _, conversation, _ = conversation_scene
        result = conversation.clean_result("hello # internal", alice)
        assert "internal" not in result
        assert "hello" in result

    def test_strips_after_internal_marker(self, conversation_scene, alice):
        _, conversation, _ = conversation_scene
        result = conversation.clean_result(
            "real dialogue (Internal: thinking thoughts)", alice
        )
        assert "Internal" not in result
        assert "real dialogue" in result

    def test_collapses_space_colon(self, conversation_scene, alice):
        _, conversation, _ = conversation_scene
        result = conversation.clean_result("Alice : hi there", alice)
        assert "Alice:" in result
        assert "Alice :" not in result


# ---------------------------------------------------------------------------
# allow_repetition_break / character names in stop tokens
# ---------------------------------------------------------------------------


class TestAllowRepetitionBreak:
    def test_allow_repetition_break_only_for_converse(self, conversation_scene):
        _, conversation, _ = conversation_scene
        assert conversation.allow_repetition_break("conversation", "converse") is True
        assert (
            conversation.allow_repetition_break("conversation", "build_prompt") is False
        )


def _stopping_strings_for_conversation(conversation, preset_strings: list[str]):
    """Run the agent/client handshake that assembles the stopping strings.

    The agent publishes the toggle to the conversation context and the client
    decides whether to add the character names on top of whatever the
    inference preset already contributed.
    """
    params = {"extra_stopping_strings": list(preset_strings)}
    with client_context_module.ClientContext():
        client_context_module.set_client_context_attribute(
            "conversation",
            {"talking_character": "Alice", "other_characters": ["Bob"]},
        )
        conversation.set_generation_overrides()
        conversation.client.tune_prompt_parameters_conversation(params)
    return params["extra_stopping_strings"]


class TestInjectCharacterNamesIntoStop:
    def test_names_added_alongside_preset_strings_when_enabled(
        self, conversation_scene
    ):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].config[
            "inject_character_names_into_stop"
        ].value = True

        strings = _stopping_strings_for_conversation(conversation, ["PRESET"])
        assert "PRESET" in strings
        assert "Bob:" in strings
        assert "BOB\n" in strings

    def test_only_names_dropped_when_disabled(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].config[
            "inject_character_names_into_stop"
        ].value = False

        # The preset's own stopping strings must survive the toggle.
        strings = _stopping_strings_for_conversation(conversation, ["PRESET"])
        assert strings == ["PRESET"]


# ---------------------------------------------------------------------------
# converse — patched build_prompt + LLM client
# ---------------------------------------------------------------------------


class TestConverse:
    async def test_converse_movie_script_format(self, conversation_scene, alice):
        scene, conversation, alice_actor = conversation_scene
        instance.get_agent("summarizer").actions["manage_scene_history"].config[
            "format"
        ].value = "movie_script"

        # Stub the agent's own build_prompt to skip the templating pipeline.
        # Returns a real Prompt instance whose `send` is overridden to deliver
        # canned LLM output — the contract still flows through the real Prompt
        # class.
        async def fake_build_prompt(character, char_message="", instruction=None):
            return _canned_prompt("raw response", {"response": "Alice:Hello there!"})

        conversation.build_prompt = fake_build_prompt

        result = await conversation.converse(alice_actor)
        assert isinstance(result, list)
        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, CharacterMessage)
        # Movie-script format strips a leading "ALICE\n" pattern; result
        # should still be prefixed with "Alice: " by the converse path.
        assert msg.message.startswith("Alice: ")
        assert "Hello there" in msg.message

    async def test_converse_narrative_format(self, conversation_scene, alice):
        scene, conversation, alice_actor = conversation_scene
        instance.get_agent("summarizer").actions["manage_scene_history"].config[
            "format"
        ].value = "narrative"

        async def fake_build_prompt(character, char_message="", instruction=None):
            return _canned_prompt(
                "She walked over and smiled.",
                {"response": "She walked over and smiled."},
            )

        conversation.build_prompt = fake_build_prompt
        result = await conversation.converse(alice_actor)
        assert len(result) == 1
        msg = result[0]
        # Narrative format: prepend character name when not already present.
        assert msg.message.startswith("Alice: ")
        assert "She walked over and smiled" in msg.message

    async def test_converse_strips_uppercase_name_prefix(
        self, conversation_scene, alice
    ):
        scene, conversation, alice_actor = conversation_scene
        instance.get_agent("summarizer").actions["manage_scene_history"].config[
            "format"
        ].value = "movie_script"

        async def fake_build_prompt(character, char_message="", instruction=None):
            return _canned_prompt(
                "ALICE\nBack soon.", {"response": "ALICE\nBack soon."}
            )

        conversation.build_prompt = fake_build_prompt
        result = await conversation.converse(alice_actor)
        msg = result[0]
        # The "ALICE\n" prefix is stripped, then "Alice: " is prepended.
        assert msg.message.startswith("Alice: ")
        assert "ALICE\n" not in msg.message
        assert "Back soon" in msg.message

    async def test_converse_empty_response_raises(self, conversation_scene, alice):
        scene, conversation, alice_actor = conversation_scene
        conversation.actions["generation_override"].enabled = True

        async def fake_build_prompt(character, char_message="", instruction=None):
            return _canned_prompt("", {"response": ""})

        conversation.build_prompt = fake_build_prompt
        # The empty-response handler raises GenerationCancelled.
        with pytest.raises(GenerationCancelled):
            await conversation.converse(alice_actor)

    async def test_converse_passes_avatar_through_emission(
        self, conversation_scene, alice
    ):
        scene, conversation, alice_actor = conversation_scene
        alice.current_avatar = "default-avatar.png"

        async def fake_build_prompt(character, char_message="", instruction=None):
            return _canned_prompt("Hi!", {"response": "Hi!"})

        conversation.build_prompt = fake_build_prompt
        messages = await conversation.converse(alice_actor)
        msg = messages[0]
        # Falls back to the character's current avatar.
        assert msg.asset_id == "default-avatar.png"
        assert msg.asset_type == "avatar"
