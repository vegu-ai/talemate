"""
Tests for ``talemate.agents.conversation`` (the ConversationAgent class).

Targets:
- Action registration (``init_actions``) and the property accessors
  (``conversation_format``, ``conversation_format_label``,
  ``content_use_*``, ``generation_settings_*``,
  ``inject_character_names_into_stop``).
- ``agent_details`` populated dictionary.
- ``set_generation_overrides`` writing context attributes when enabled.
- ``clean_result`` post-processing of LLM output.
- ``allow_repetition_break`` and ``inject_prompt_paramters``.
- ``converse`` happy path through ``Prompt.request`` mock for both
  movie_script and narrative formats, including character-name
  prefix handling.
- ``converse`` raises GenerationCancelled when the LLM returns empty.

The full ``build_prompt_default`` pathway is left to template-baseline
tests; here we patch ``build_prompt`` so converse can be tested end-to-end.
"""

import pytest

import talemate.client.context as client_context_module
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

    def test_default_format_is_movie_script(self, conversation_scene):
        _, conversation, _ = conversation_scene
        assert conversation.conversation_format == "movie_script"

    def test_format_returns_movie_script_when_override_disabled(
        self, conversation_scene
    ):
        _, conversation, _ = conversation_scene
        # Override config value first, then disable. Should fall back to
        # the movie_script default.
        conversation.actions["generation_override"].config["format"].value = "chat"
        conversation.actions["generation_override"].enabled = False
        assert conversation.conversation_format == "movie_script"

    def test_format_returns_value_when_override_enabled(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].enabled = True
        conversation.actions["generation_override"].config["format"].value = "chat"
        assert conversation.conversation_format == "chat"

    def test_format_label_resolves_known_value(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].config["format"].value = "chat"
        # The choices contain a label "Chat (legacy)" for value "chat".
        assert conversation.conversation_format_label == "Chat (legacy)"

    def test_format_label_falls_back_to_value_when_unknown(self, conversation_scene):
        _, conversation, _ = conversation_scene
        # Inject an unknown value and confirm the label is the raw value.
        conversation.actions["generation_override"].config["format"].value = "weird"
        assert conversation.conversation_format_label == "weird"

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
    def test_includes_client_and_format(self, conversation_scene):
        _, conversation, _ = conversation_scene
        details = conversation.agent_details
        assert "client" in details
        assert "format" in details
        assert details["client"]["value"] == conversation.client.name
        # Format default is movie_script -> label is "Screenplay".
        assert details["format"]["value"] == "Screenplay"

    def test_no_client_yields_none_value(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.client = None
        details = conversation.agent_details
        assert details["client"]["value"] is None


# ---------------------------------------------------------------------------
# set_generation_overrides
# ---------------------------------------------------------------------------


class TestSetGenerationOverrides:
    def test_does_nothing_when_disabled(self, conversation_scene):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].enabled = False
        # Should not raise even without a client_context active.
        conversation.set_generation_overrides()

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
# allow_repetition_break / inject_prompt_paramters
# ---------------------------------------------------------------------------


class TestAllowRepetitionBreakAndInject:
    def test_allow_repetition_break_only_for_converse(self, conversation_scene):
        _, conversation, _ = conversation_scene
        assert conversation.allow_repetition_break("conversation", "converse") is True
        assert (
            conversation.allow_repetition_break("conversation", "build_prompt") is False
        )

    def test_inject_prompt_parameters_noop_with_inject_enabled_and_empty(
        self, conversation_scene
    ):
        _, conversation, _ = conversation_scene
        params = {}
        conversation.inject_prompt_paramters(params, "conversation", "converse")
        # When inject_character_names_into_stop is True (default) and no
        # stopping strings are present, the function leaves params untouched.
        assert "extra_stopping_strings" not in params

    def test_inject_prompt_parameters_resets_when_inject_disabled(
        self, conversation_scene
    ):
        _, conversation, _ = conversation_scene
        conversation.actions["generation_override"].config[
            "inject_character_names_into_stop"
        ].value = False
        params = {"extra_stopping_strings": ["EXISTING"]}
        conversation.inject_prompt_paramters(params, "conversation", "converse")
        # When inject_character_names_into_stop is False, any stopping
        # strings already populated (e.g. character names added by the
        # client) are wiped.
        assert params["extra_stopping_strings"] == []

    def test_inject_prompt_parameters_preserves_existing_with_inject_enabled(
        self, conversation_scene
    ):
        _, conversation, _ = conversation_scene
        # When inject_character_names_into_stop is True AND extra_stopping_strings
        # is already populated, it is left untouched.
        conversation.actions["generation_override"].config[
            "inject_character_names_into_stop"
        ].value = True
        params = {"extra_stopping_strings": ["EXISTING"]}
        conversation.inject_prompt_paramters(params, "conversation", "converse")
        assert params["extra_stopping_strings"] == ["EXISTING"]


# ---------------------------------------------------------------------------
# converse — patched build_prompt + LLM client
# ---------------------------------------------------------------------------


class TestConverse:
    async def test_converse_movie_script_format(self, conversation_scene, alice):
        scene, conversation, alice_actor = conversation_scene
        conversation.actions["generation_override"].enabled = True
        conversation.actions["generation_override"].config[
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
        conversation.actions["generation_override"].enabled = True
        conversation.actions["generation_override"].config["format"].value = "narrative"

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
        conversation.actions["generation_override"].enabled = True
        conversation.actions["generation_override"].config[
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
