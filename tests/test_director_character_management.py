"""Unit tests for talemate.agents.director.character_management.CharacterManagementMixin.

Covers:
- Config property helpers (cm_assign_voice, cm_generate_visuals,
  cm_max_attributes, cm_should_assign_voice).
- assign_voice_to_character early-return paths (TTS disabled, no APIs,
  no voices). The full Focal-driven request is NOT exercised.
- _detect_characters_from_texts_chunk: filters empty texts + dedup callback.
- detect_characters_from_texts: end-to-end with stubbed Focal request,
  exercises chunking, dedup, lowercase exclusion, substring-name removal.
- persist_characters_from_worldstate: skip logic (excluded names + names
  already in scene). The actual persist_character call is replaced with a
  fake on the agent instance to keep the test focused on iteration.
- persist_character: the example dialogue step (opt-in flag, guidance and
  count forwarding, skipped by default) with the creator's LLM-backed
  methods patched, plus the PersistCharacterPayload/signature parity guard
  and the early-error path when the name already exists. The remaining
  LLM-backed steps (name/attributes/description generation) are bypassed
  via flags rather than exercised.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from conftest import MockScene, bootstrap_scene

import talemate.agents.tts.voice_library as voice_library_mod
import talemate.instance as instance
from talemate.agents.director.character_management import (
    PERSIST_CHARACTER_EXAMPLE_DIALOGUE_COUNT,
    CharacterManagementMixin,
)
from talemate.agents.director.websocket_handler import PersistCharacterPayload
from talemate.agents.tts.schema import Voice  # noqa: F401
from talemate.character import Character
from talemate.world_state import CharacterState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    return s


@pytest.fixture
def director(scene):
    return instance.get_agent("director")


@pytest.fixture
def tts_agent():
    return instance.get_agent("tts")


# ---------------------------------------------------------------------------
# Config property helpers
# ---------------------------------------------------------------------------


class TestCharacterManagementConfig:
    def test_assign_voice_default_true(self, director):
        assert director.cm_assign_voice is True

    def test_generate_visuals_default_true(self, director):
        assert director.cm_generate_visuals is True

    def test_max_attributes_default_zero(self, director):
        assert director.cm_max_attributes == 0

    def test_max_attributes_handles_falsy(self, director):
        director.actions["character_management"].config["max_attributes"].value = None
        # `or 0` should kick in
        assert director.cm_max_attributes == 0

    def test_max_attributes_returns_int(self, director):
        director.actions["character_management"].config["max_attributes"].value = 7
        assert director.cm_max_attributes == 7
        assert isinstance(director.cm_max_attributes, int)


# ---------------------------------------------------------------------------
# cm_should_assign_voice
# ---------------------------------------------------------------------------


class TestCmShouldAssignVoice:
    def test_returns_false_when_assign_voice_disabled(self, director):
        director.actions["character_management"].config["assign_voice"].value = False
        try:
            assert director.cm_should_assign_voice is False
        finally:
            director.actions["character_management"].config["assign_voice"].value = True

    def test_returns_false_when_tts_agent_disabled(self, director, tts_agent):
        # By default the TTS agent in tests is not enabled (no API keys etc.)
        # but to be defensive, force-disable it via monkey-patch.
        with patch.object(type(tts_agent), "enabled", property(lambda self: False)):
            assert director.cm_should_assign_voice is False

    def test_returns_false_when_no_ready_apis(self, director, tts_agent):
        with patch.object(type(tts_agent), "enabled", property(lambda self: True)):
            with patch.object(
                type(tts_agent),
                "ready_apis",
                property(lambda self: []),
            ):
                assert director.cm_should_assign_voice is False

    def test_returns_true_when_all_conditions_met(self, director, tts_agent):
        with patch.object(type(tts_agent), "enabled", property(lambda self: True)):
            with patch.object(
                type(tts_agent),
                "ready_apis",
                property(lambda self: ["someapi"]),
            ):
                assert director.cm_should_assign_voice is True


# ---------------------------------------------------------------------------
# assign_voice_to_character — early-return paths
# ---------------------------------------------------------------------------


class TestAssignVoiceToCharacterEarlyReturn:
    @pytest.mark.asyncio
    async def test_skipped_when_should_assign_false(self, scene, director):
        # Default: TTS not enabled → cm_should_assign_voice is False.
        char = Character(name="Alice")
        result = await director.assign_voice_to_character(char)
        assert result is None  # early return (no calls list)

    @pytest.mark.asyncio
    async def test_skipped_when_no_voices_available(self, scene, director, tts_agent):
        # Force should_assign_voice to True and have ready APIs, but no voices
        # in the global library or the scene library.
        with patch.object(type(tts_agent), "enabled", property(lambda self: True)):
            with patch.object(
                type(tts_agent),
                "ready_apis",
                property(lambda self: ["someapi"]),
            ):
                # Replace the voice library with an empty one
                voice_library_mod.VOICE_LIBRARY = voice_library_mod.VoiceLibrary(
                    voices={}
                )
                # Scene's voice_library may be empty by default — ensure so
                scene.voice_library = voice_library_mod.VoiceLibrary(voices={})

                char = Character(name="Bob")
                result = await director.assign_voice_to_character(char)
                # Returns None when no voices are available
                assert result is None


class TestAssignVoiceToCharacterWithVoices:
    """Cover the body of assign_voice_to_character once voices exist.

    The Focal request itself is stubbed out — we only exercise candidate
    construction and the focal_handler return path.
    """

    @pytest.mark.asyncio
    async def test_returns_focal_calls_when_voices_present(
        self, scene, director, tts_agent, monkeypatch
    ):
        # Stand up a global voice library with one Voice
        v = Voice(label="V", provider="someapi", provider_id="v1")
        voice_library_mod.VOICE_LIBRARY = voice_library_mod.VoiceLibrary(
            voices={v.id: v}
        )
        scene.voice_library = voice_library_mod.VoiceLibrary(voices={})

        # Stub Focal.request to record the call and skip the LLM round-trip.
        import talemate.game.focal as focal_mod

        async def _stub_request(self, template, *args, **kwargs):
            return None

        monkeypatch.setattr(focal_mod.Focal, "request", _stub_request)

        with patch.object(type(tts_agent), "enabled", property(lambda self: True)):
            with patch.object(
                type(tts_agent),
                "ready_apis",
                property(lambda self: ["someapi"]),
            ):
                char = Character(name="Carol")
                # Add the character to the scene so .all_characters iteration
                # can run cleanly.
                actor = scene.Actor(char, None)
                await scene.add_actor(actor, commit_to_memory=False)
                result = await director.assign_voice_to_character(char)
                # focal_handler.state.calls is initialized as an empty list and
                # the stubbed request never appends — but the call itself
                # must complete without raising.
                assert result == []


# ---------------------------------------------------------------------------
# _detect_characters_from_texts_chunk — Focal.request stubbed
#
# ``Focal`` is a real production class (talemate.game.focal.Focal). Tests
# replace its ``request`` instance method using ``monkeypatch.setattr`` with
# ``raising=True`` so a rename of ``Focal.request`` immediately fails the
# patch instead of silently keeping a stand-in alive.
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_focal_request(monkeypatch):
    """Patch ``Focal.request`` to drive the registered callbacks deterministically.

    The function-under-test invokes ``Focal(...).request(template)`` to ask
    the LLM to emit ``add_detected_character`` calls. Substituting the
    method with a function that walks ``focal_inst.callbacks`` directly
    bypasses the LLM round-trip while preserving the real callback object
    types and dispatch path. The ``raising=True`` default on monkeypatch
    ensures the patch fails if ``Focal.request`` is renamed.
    """
    from talemate.game.focal import Focal

    class _CallRecorder:
        def __init__(self, names_to_emit: list[str]):
            self.names_to_emit = names_to_emit
            self.calls: list[dict] = []

    def install(names: list[str]):
        recorder = _CallRecorder(names)

        async def _patched_request(
            self, template_name=None, prompt=None, retry_state=None
        ):
            # `self` is a real Focal instance — read its real callbacks dict
            # and invoke add_detected_character with each canned name.
            cb = self.callbacks.get("add_detected_character")
            if cb is not None:
                for name in recorder.names_to_emit:
                    await cb.fn(name)
            recorder.calls.append({"template": template_name})
            return None

        monkeypatch.setattr(Focal, "request", _patched_request, raising=True)
        return recorder

    return install


class TestDetectCharactersFromTextsChunk:
    @pytest.mark.asyncio
    async def test_empty_texts_returns_empty(self, scene, director):
        result = await director._detect_characters_from_texts_chunk(["", "  ", None])
        assert result == []

    @pytest.mark.asyncio
    async def test_dedupes_within_chunk(self, scene, director, stub_focal_request):
        stub_focal_request(["Alice", "Bob", "Alice"])
        result = await director._detect_characters_from_texts_chunk(["text"])
        assert sorted(result) == ["Alice", "Bob"]

    @pytest.mark.asyncio
    async def test_propagates_already_detected_to_request(
        self, scene, director, stub_focal_request
    ):
        stub_focal_request(["Carol"])
        result = await director._detect_characters_from_texts_chunk(
            ["text"], already_detected_names=["Alice"]
        )
        assert "Carol" in result
        # already_detected names are NOT in the chunk's local list (they're
        # passed through as kwargs to the focal request only)
        assert "Alice" not in result


# ---------------------------------------------------------------------------
# detect_characters_from_texts (end-to-end orchestration)
# ---------------------------------------------------------------------------


class TestDetectCharactersFromTexts:
    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, scene, director):
        assert await director.detect_characters_from_texts([]) == []
        assert await director.detect_characters_from_texts(["", "  "]) == []

    @pytest.mark.asyncio
    async def test_no_client_returns_empty(self, scene, director):
        original_client = director.client
        director.client = None
        try:
            assert await director.detect_characters_from_texts(["text"]) == []
        finally:
            director.client = original_client

    @pytest.mark.asyncio
    async def test_filters_excluded_names(self, scene, director, stub_focal_request):
        stub_focal_request(["Alice", "user", "{{char}}", "Bob"])
        result = await director.detect_characters_from_texts(["text"])
        assert "user" not in [n.lower() for n in result]
        assert "{{char}}" not in result
        assert "Alice" in result
        assert "Bob" in result

    @pytest.mark.asyncio
    async def test_substring_names_removed(self, scene, director, stub_focal_request):
        # "Julia" appears as a whole word inside "Julia Smith" → gets removed
        stub_focal_request(["Julia Smith", "Julia"])
        result = await director.detect_characters_from_texts(["text"])
        assert "Julia Smith" in result
        assert "Julia" not in result

    @pytest.mark.asyncio
    async def test_dedupes_across_chunks(self, scene, director, stub_focal_request):
        # Each chunk emission returns the same name
        stub_focal_request(["Alice"])
        # Call with two chunks (chunk_items_by_tokens may produce 1 or more
        # depending on size, but result must be deduped)
        result = await director.detect_characters_from_texts(["text 1", "text 2"])
        assert result.count("Alice") == 1


# ---------------------------------------------------------------------------
# persist_characters_from_worldstate — iteration logic only
# ---------------------------------------------------------------------------


class TestPersistCharactersFromWorldstate:
    @pytest.mark.asyncio
    async def test_skips_excluded_names(self, scene, director):
        # Populate worldstate with several characters
        scene.world_state.characters = {
            "Alice": CharacterState(name="Alice"),
            "Bob": CharacterState(name="Bob"),
            "Eve": CharacterState(name="Eve"),
        }
        persisted_calls: list[str] = []

        async def fake_persist(name, **kwargs):
            persisted_calls.append(name)
            char = Character(name=name)
            return char

        with patch.object(director, "persist_character", side_effect=fake_persist):
            result = await director.persist_characters_from_worldstate(
                exclude=["bob"]  # lowercase comparison in source
            )
        names = [c.name for c in result]
        assert "Alice" in names
        assert "Eve" in names
        assert "Bob" not in names
        # Excluded name is never even passed to persist_character
        assert "Bob" not in persisted_calls

    @pytest.mark.asyncio
    async def test_skips_names_already_in_scene(self, scene, director):
        # Add "Existing" to scene first
        existing_char = Character(name="Existing")
        actor = scene.Actor(existing_char, None)
        await scene.add_actor(actor, commit_to_memory=False)

        scene.world_state.characters = {
            "Existing": CharacterState(name="Existing"),
            "NewOne": CharacterState(name="NewOne"),
        }

        async def fake_persist(name, **kwargs):
            return Character(name=name)

        with patch.object(director, "persist_character", side_effect=fake_persist):
            result = await director.persist_characters_from_worldstate()
        names = [c.name for c in result]
        assert "NewOne" in names
        assert "Existing" not in names

    @pytest.mark.asyncio
    async def test_no_world_state_characters_returns_empty(self, scene, director):
        scene.world_state.characters = {}
        result = await director.persist_characters_from_worldstate()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_list_of_persisted_characters(self, scene, director):
        scene.world_state.characters = {"X": CharacterState(name="X")}

        async def fake_persist(name, **kwargs):
            return Character(name=name)

        with patch.object(director, "persist_character", side_effect=fake_persist):
            result = await director.persist_characters_from_worldstate()
        assert len(result) == 1
        assert result[0].name == "X"


# ---------------------------------------------------------------------------
# persist_character — example dialogue generation
# ---------------------------------------------------------------------------


class TestPersistCharacterExampleDialogue:
    """Cover the example dialogue step of persist_character.

    Creator collaborators are patched with AsyncMocks; the flags passed to
    persist_character (determine_name=False, generate_attributes=False,
    description set, narrate_entry=False) skip every other LLM-backed step.
    """

    @pytest.fixture
    def patched_creator(self, scene):
        creator = instance.get_agent("creator")
        with (
            patch.object(
                creator,
                "determine_character_dialogue_instructions",
                AsyncMock(return_value="speaks softly"),
            ),
            patch.object(
                creator,
                "determine_character_dialogue_examples",
                AsyncMock(return_value=['Nyx: "Well, that went great." rolls eyes']),
            ) as mock_examples,
        ):
            yield mock_examples

    @pytest.mark.asyncio
    async def test_generates_examples_with_guidance(
        self, scene, director, patched_creator
    ):
        character = await director.persist_character(
            name="Nyx",
            content="A mysterious stranger",
            determine_name=False,
            generate_attributes=False,
            description="Already described.",
            narrate_entry=False,
            generate_example_dialogue=True,
            example_dialogue_instructions="Dry humor, short sentences.",
        )

        assert character is not None
        patched_creator.assert_awaited_once()
        kwargs = patched_creator.await_args.kwargs
        assert kwargs["text"] == "A mysterious stranger"
        assert kwargs["instructions"] == "Dry humor, short sentences."
        assert kwargs["max_examples"] == PERSIST_CHARACTER_EXAMPLE_DIALOGUE_COUNT
        assert character.example_dialogue == [
            'Nyx: "Well, that went great." rolls eyes'
        ]

    @pytest.mark.asyncio
    async def test_skipped_by_default(self, scene, director, patched_creator):
        character = await director.persist_character(
            name="Vex",
            content="A quiet merchant",
            determine_name=False,
            generate_attributes=False,
            description="Already described.",
            narrate_entry=False,
        )

        assert character is not None
        patched_creator.assert_not_awaited()
        assert not character.example_dialogue

    def test_payload_fields_match_persist_character_signature(self):
        """Every field the websocket payload exposes must be a persist_character
        kwarg — guards backend/frontend parity when either side changes."""
        params = set(
            inspect.signature(CharacterManagementMixin.persist_character).parameters
        ) - {"self"}
        assert set(PersistCharacterPayload.model_fields).issubset(params)


# ---------------------------------------------------------------------------
# persist_character — early-error path when name already exists
# ---------------------------------------------------------------------------


class TestPersistCharacterEarlyErrorPath:
    @pytest.mark.asyncio
    async def test_raises_value_error_when_name_already_in_scene(self, scene, director):
        # Add a character so its name exists in scene.all_character_names.
        existing = Character(name="Existing")
        actor = scene.Actor(existing, None)
        await scene.add_actor(actor, commit_to_memory=False)

        # Patch determine_character_name on the creator agent so it returns
        # the same name without LLM use.
        creator = instance.get_agent("creator")

        async def fake_determine(name, instructions=None):
            return "Existing"

        with patch.object(
            creator, "determine_character_name", side_effect=fake_determine
        ):
            with pytest.raises(ValueError, match="already exists"):
                await director.persist_character(name="Existing", determine_name=True)
