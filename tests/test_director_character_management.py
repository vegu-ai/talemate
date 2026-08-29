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
  already in scene).
- persist_character: real-path end-to-end coverage per generation mode
  (manual, split, fast, fast+fill-miss) at the client response level
  (MockClient + client_responses queue) - real templates render, real
  parsing runs, routing asserted via prompt kinds. Agent-level mocks remain
  only for the template fold gates and the name-guard edges (combinatorial
  cases), always spec'd via autospec so signature drift fails loudly.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from conftest import MockClientContext, MockScene, bootstrap_scene, client_responses
from _character_test_helpers import (
    DEFAULT_CONSOLIDATE,
    KIND_DESCRIPTION,
    KIND_DIALOGUE_INSTRUCTIONS,
    KIND_FOCAL,
    KIND_NAME,
    KIND_SHEET,
    KIND_UNIFIED,
    description_response,
    example_dialogue_response,
    name_response,
    prompt_kinds,
    sheet_response,
    unified_response,
)

import talemate.agents.tts.voice_library as voice_library_mod
import talemate.instance as instance
from talemate.agents.creator.character import (
    CHARACTER_GENERATION_ASPECTS,
    CharacterGenerationResult,
)
from talemate.agents.director.character_management import (
    PERSIST_CHARACTER_EXAMPLE_DIALOGUE_COUNT,
    SPLIT_ASPECT_LOADING_MESSAGES,
    PersistCharacterRequest,
)
from talemate.agents.director.websocket_handler import (
    DirectorWebsocketHandler,
    PersistCharacterPayload,
)
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
    async def test_skipped_when_no_voices_available(
        self, scene, director, tts_agent, monkeypatch
    ):
        # Force should_assign_voice to True and have ready APIs, but no voices
        # in the global library or the scene library.
        with patch.object(type(tts_agent), "enabled", property(lambda self: True)):
            with patch.object(
                type(tts_agent),
                "ready_apis",
                property(lambda self: ["someapi"]),
            ):
                # Replace the voice library with an empty one
                monkeypatch.setattr(
                    voice_library_mod,
                    "VOICE_LIBRARY",
                    voice_library_mod.VoiceLibrary(voices={}),
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
        monkeypatch.setattr(
            voice_library_mod,
            "VOICE_LIBRARY",
            voice_library_mod.VoiceLibrary(voices={v.id: v}),
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
    @pytest.fixture
    def fake_persist(self, director):
        """persist_character replaced with a recorder (autospec'd) that
        returns a real Character; yields the recorded names."""
        persisted_calls: list[str] = []

        async def _persist(request):
            persisted_calls.append(request.name)
            return Character(name=request.name)

        with patch.object(
            director, "persist_character", autospec=True, side_effect=_persist
        ):
            yield persisted_calls

    @pytest.mark.asyncio
    async def test_skips_excluded_names(self, scene, director, fake_persist):
        # Populate worldstate with several characters
        scene.world_state.characters = {
            "Alice": CharacterState(name="Alice"),
            "Bob": CharacterState(name="Bob"),
            "Eve": CharacterState(name="Eve"),
        }
        result = await director.persist_characters_from_worldstate(
            exclude=["bob"]  # lowercase comparison in source
        )
        names = [c.name for c in result]
        assert "Alice" in names
        assert "Eve" in names
        assert "Bob" not in names
        # Excluded name is never even passed to persist_character
        assert "Bob" not in fake_persist

    @pytest.mark.asyncio
    async def test_skips_names_already_in_scene(self, scene, director, fake_persist):
        # Add "Existing" to scene first
        existing_char = Character(name="Existing")
        actor = scene.Actor(existing_char, None)
        await scene.add_actor(actor, commit_to_memory=False)

        scene.world_state.characters = {
            "Existing": CharacterState(name="Existing"),
            "NewOne": CharacterState(name="NewOne"),
        }
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
    async def test_returns_list_of_persisted_characters(
        self, scene, director, fake_persist
    ):
        scene.world_state.characters = {"X": CharacterState(name="X")}
        result = await director.persist_characters_from_worldstate()
        assert len(result) == 1
        assert result[0].name == "X"


# ---------------------------------------------------------------------------
# persist_character — example dialogue generation (real path, client level)
# ---------------------------------------------------------------------------


class TestPersistCharacterExampleDialogue:
    """Cover the example dialogue step of persist_character.

    The flags (determine_name=False, generate_attributes=False, description
    set, narrate_entry=False) skip every other LLM-backed step except
    dialogue instructions, so the queue is: instructions, then the focal
    example dialogue request.
    """

    @pytest.mark.asyncio
    async def test_generates_examples_with_guidance(self, scene, director):
        async with MockClientContext():
            client_responses.get().append("speaks softly")
            client_responses.get().append(
                example_dialogue_response('"Well, that went great." rolls eyes')
            )
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="Nyx",
                    content="A mysterious stranger",
                    determine_name=False,
                    generate_attributes=False,
                    description="Already described.",
                    narrate_entry=False,
                    generate_example_dialogue=True,
                    example_dialogue_instructions="Dry humor, short sentences.",
                )
            )

        assert character is not None
        assert prompt_kinds(scene.mock_client) == [
            KIND_DIALOGUE_INSTRUCTIONS,
            KIND_FOCAL,
        ]
        # content, guidance and the example count all reach the rendered
        # example dialogue prompt
        prompt = str(scene.mock_client.prompt_history[-1]["prompt"])
        assert "A mysterious stranger" in prompt
        assert "Dry humor, short sentences." in prompt
        assert (
            f"up to {PERSIST_CHARACTER_EXAMPLE_DIALOGUE_COUNT} dialogue examples"
            in prompt
        )
        assert character.example_dialogue == [
            'Nyx: "Well, that went great." rolls eyes'
        ]

    @pytest.mark.asyncio
    async def test_skipped_by_default(self, scene, director):
        async with MockClientContext():
            client_responses.get().append("speaks softly")
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="Vex",
                    content="A quiet merchant",
                    determine_name=False,
                    generate_attributes=False,
                    description="Already described.",
                    narrate_entry=False,
                )
            )

        assert character is not None
        # only the dialogue instructions request ran - no focal example
        # dialogue prompt
        assert prompt_kinds(scene.mock_client) == [KIND_DIALOGUE_INSTRUCTIONS]
        assert not character.example_dialogue

    @pytest.mark.asyncio
    async def test_supplied_examples_are_smart_quote_normalized(self, scene, director):
        # pre-supplied examples (node graph literals, ws payload) skip the
        # generation step entirely, so this is the only place they are cleaned
        async with MockClientContext():
            client_responses.get().append("speaks softly")
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="Isolde",
                    content="A travelling scribe",
                    determine_name=False,
                    generate_attributes=False,
                    description="Already described.",
                    narrate_entry=False,
                    example_dialogue=["Isolde: “Ink and patience.” She nods."],
                )
            )

        assert character is not None
        # no example dialogue prompt ran - the supplied list was used as-is
        assert prompt_kinds(scene.mock_client) == [KIND_DIALOGUE_INSTRUCTIONS]
        assert character.example_dialogue == ['Isolde: "Ink and patience." She nods.']

    def test_payload_fields_match_persist_character_signature(self):
        """Every field the websocket payload exposes must be a
        PersistCharacterRequest field — guards backend/frontend parity when
        either side changes."""
        params = set(PersistCharacterRequest.model_fields)
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

        # the real name determination comes back with the same name
        async with MockClientContext():
            client_responses.get().append(name_response("Existing"))
            with pytest.raises(ValueError, match="already exists"):
                await director.persist_character(
                    PersistCharacterRequest(name="Existing", determine_name=True)
                )

        assert prompt_kinds(scene.mock_client) == [KIND_NAME]


# ---------------------------------------------------------------------------
# persist_character — generation modes (manual / split / fast)
# ---------------------------------------------------------------------------


class TestPersistCharacterGenerationModes:
    """Cover the generate flag, the Fast (consolidated) path and
    pre-generated field params of persist_character.

    One real-path end-to-end test per mode (manual, split, fast,
    fast+fill-miss) at the client response level; agent-level mocks remain
    only for the name-guard edges and the template fold gates."""

    @pytest.fixture
    def creator(self):
        return instance.get_agent("creator")

    @pytest.fixture
    def fast_mode(self, creator):
        creator.actions["character_creation"].config["fast"].value = True
        yield
        creator.actions["character_creation"].config["fast"].value = False

    @pytest.mark.asyncio
    async def test_manual_mode_makes_no_llm_calls(self, scene, director):
        # template values are LLM-generated, so manual mode must not touch
        # the template machinery either
        template_collection = scene.world_state_manager.template_collection
        with (
            patch.object(
                type(template_collection),
                "collect_all",
                autospec=True,
                return_value={},
            ) as mock_collect,
            patch.object(
                type(scene.world_state_manager),
                "apply_templates",
                autospec=True,
            ) as mock_apply,
        ):
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="Manual Bob",
                    description="A manually created character.",
                    attributes="Age: 40\nOccupation: blacksmith",
                    templates=["some-template"],
                    generate=False,
                    determine_name=False,
                    active=False,
                )
            )

        assert scene.mock_client.prompt_history == []
        mock_collect.assert_not_called()
        mock_apply.assert_not_called()
        assert character is not None
        assert character.name == "Manual Bob"
        assert character.description == "A manually created character."
        assert character.base_attributes == {
            "Age": "40",
            "Occupation": "blacksmith",
        }
        assert not character.dialogue_instructions
        assert not character.example_dialogue
        assert scene.get_character("Manual Bob") is not None

    @pytest.mark.asyncio
    async def test_manual_mode_requires_name(self, scene, director):
        with pytest.raises(ValueError, match="name is required"):
            await director.persist_character(
                PersistCharacterRequest(name="", generate=False, determine_name=False)
            )

    @pytest.mark.asyncio
    async def test_split_mode_uses_individual_prompts(self, scene, director):
        async with MockClientContext():
            client_responses.get().append(name_response("Elena"))
            client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
            client_responses.get().append(description_response("Elena", "is a healer."))
            client_responses.get().append("Soft.")
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="the tall woman",
                    content="A healer arrives.",
                    narrate_entry=False,
                    active=False,
                )
            )

        # split-mode generation order: name, sheet, description, instructions
        assert prompt_kinds(scene.mock_client) == [
            KIND_NAME,
            KIND_SHEET,
            KIND_DESCRIPTION,
            KIND_DIALOGUE_INSTRUCTIONS,
        ]
        # the freshly generated sheet is visible to the description prompt
        description_prompt = str(scene.mock_client.prompt_history[2]["prompt"])
        assert "Age: 30" in description_prompt
        assert character.name == "Elena"
        assert character.description == "Elena is a healer."
        assert character.base_attributes == {"Name": "Elena", "Age": "30"}
        assert character.dialogue_instructions == "Soft."

    @pytest.mark.asyncio
    async def test_split_mode_presupplied_attributes_reach_downstream_prompts(
        self, scene, director
    ):
        # caller-provided attributes are parsed onto the character before
        # aspect generation - no sheet request, and the description prompt
        # renders the provided sheet
        async with MockClientContext():
            client_responses.get().append(description_response("Elena", "is a healer."))
            client_responses.get().append("Soft.")
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="Elena",
                    content="A healer arrives.",
                    attributes="Age: 40\nOccupation: blacksmith",
                    determine_name=False,
                    narrate_entry=False,
                    active=False,
                )
            )

        assert prompt_kinds(scene.mock_client) == [
            KIND_DESCRIPTION,
            KIND_DIALOGUE_INSTRUCTIONS,
        ]
        description_prompt = str(scene.mock_client.prompt_history[0]["prompt"])
        assert "Age: 40" in description_prompt
        assert "Occupation: blacksmith" in description_prompt
        assert character.base_attributes == {"Age": "40", "Occupation": "blacksmith"}
        assert character.description == "Elena is a healer."

    @pytest.mark.asyncio
    async def test_fast_mode_uses_consolidated_one_shot(
        self, scene, director, fast_mode
    ):
        async with MockClientContext():
            client_responses.get().append(
                unified_response(
                    name="Elena",
                    description="Elena is a healer.",
                    attributes="Age: 30",
                    dialogue_instructions="Soft.",
                )
            )
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="the tall woman",
                    content="A healer arrives.",
                    narrate_entry=False,
                    active=False,
                )
            )

        # everything came from the single consolidated prompt - nothing goes
        # through the individual split prompts in fast mode
        assert prompt_kinds(scene.mock_client) == [KIND_UNIFIED]
        prompt = str(scene.mock_client.prompt_history[0]["prompt"])
        for section in (
            "<NAME>",
            "<DESCRIPTION>",
            "<ATTRIBUTES>",
            "<DIALOGUE_INSTRUCTIONS>",
        ):
            assert section in prompt
        assert "<EXAMPLE_DIALOGUE>" not in prompt
        assert character.name == "Elena"
        assert character.description == "Elena is a healer."
        assert character.base_attributes == {"Age": "30"}
        assert character.dialogue_instructions == "Soft."

    @pytest.mark.asyncio
    async def test_fast_mode_fill_misses_uses_individual_request(
        self, scene, director, fast_mode
    ):
        # the consolidated response misses dialogue instructions - the
        # default fill-misses policy fills it with the individual request
        async with MockClientContext():
            client_responses.get().append(
                unified_response(
                    name="Elena",
                    description="Elena is a healer.",
                    attributes="Age: 30",
                )
            )
            client_responses.get().append("Soft.")
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="the tall woman",
                    content="A healer arrives.",
                    narrate_entry=False,
                    active=False,
                )
            )

        assert prompt_kinds(scene.mock_client) == [
            KIND_UNIFIED,
            KIND_DIALOGUE_INSTRUCTIONS,
        ]
        assert character.name == "Elena"
        assert character.dialogue_instructions == "Soft."

    @pytest.mark.asyncio
    async def test_fast_mode_respects_requested_aspects(
        self, scene, director, fast_mode
    ):
        # determine_name off + description provided + example dialogue on:
        # the one-shot asks only for the remaining aspects; the canned
        # response misses example dialogue, which fill_misses then generates
        # with its individual focal request
        async with MockClientContext():
            client_responses.get().append(
                unified_response(
                    attributes="Age: 30",
                    dialogue_instructions="Soft.",
                )
            )
            client_responses.get().append(example_dialogue_response('"Hi."'))
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="Elena",
                    content="A healer arrives.",
                    description="Provided description.",
                    determine_name=False,
                    generate_example_dialogue=True,
                    narrate_entry=False,
                    active=False,
                )
            )

        assert prompt_kinds(scene.mock_client) == [KIND_UNIFIED, KIND_FOCAL]
        prompt = str(scene.mock_client.prompt_history[0]["prompt"])
        for section in ("<ATTRIBUTES>", "<DIALOGUE_INSTRUCTIONS>"):
            assert section in prompt
        assert "<NAME>" not in prompt
        assert "<DESCRIPTION>" not in prompt
        assert "<EXAMPLE_DIALOGUE>" in prompt
        assert character.name == "Elena"
        assert character.description == "Provided description."
        assert character.base_attributes == {"Age": "30"}
        assert character.dialogue_instructions == "Soft."
        assert character.example_dialogue == ['Elena: "Hi."']

    @pytest.mark.asyncio
    async def test_pre_generated_fields_skip_generation(self, scene, director):
        character = await director.persist_character(
            PersistCharacterRequest(
                name="Elena",
                determine_name=False,
                generate_attributes=False,
                description="Provided.",
                dialogue_instructions="Provided DI.",
                example_dialogue=['Elena: "Hi."'],
                generate_example_dialogue=True,
                narrate_entry=False,
                active=False,
            )
        )

        # every generation step was pre-supplied - no LLM request at all
        assert scene.mock_client.prompt_history == []
        assert character.description == "Provided."
        assert character.dialogue_instructions == "Provided DI."
        assert character.example_dialogue == ['Elena: "Hi."']

    @pytest.mark.asyncio
    async def test_fast_mode_missed_name_falls_back_to_individual(
        self, scene, director, creator, fast_mode
    ):
        # one-shot missed the name and fill_misses can't help - a nameless
        # character must never be persisted, so the individual request runs
        with (
            patch.object(
                creator,
                "generate_character_aspects",
                autospec=True,
                return_value=CharacterGenerationResult(
                    description="A healer.",
                    attributes={"Age": "30"},
                    dialogue_instructions="Soft.",
                ),
            ),
            patch.object(
                creator,
                "determine_character_name",
                autospec=True,
                return_value="Elena",
            ) as mock_name,
        ):
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="",
                    content="A healer arrives.",
                    determine_name=True,
                    narrate_entry=False,
                    active=False,
                )
            )

        mock_name.assert_awaited_once()
        assert character.name == "Elena"

    @pytest.mark.asyncio
    async def test_fast_mode_unresolvable_name_raises(
        self, scene, director, creator, fast_mode
    ):
        with (
            patch.object(
                creator,
                "generate_character_aspects",
                autospec=True,
                return_value=CharacterGenerationResult(),
            ),
            patch.object(
                creator, "determine_character_name", autospec=True, return_value=""
            ),
        ):
            with pytest.raises(ValueError, match="name is required"):
                await director.persist_character(
                    PersistCharacterRequest(
                        name="",
                        content="A healer arrives.",
                        determine_name=True,
                        narrate_entry=False,
                        active=False,
                    )
                )

    @pytest.fixture
    def attribute_templates(self):
        attr = SimpleNamespace(
            template_type="character_attribute",
            formatted=lambda prop, scene, character_name=None: (
                f"Appearance of {character_name}"
                if prop == "attribute"
                else f"looks fitting for {character_name}"
            ),
        )
        detail = SimpleNamespace(
            template_type="character_detail",
            formatted=lambda prop, scene, character_name=None: "x",
        )
        return {"t1": attr, "t2": detail}

    @pytest.fixture
    def fold_mocks(self, scene, creator, attribute_templates):
        """Contextmanager factory patching the template machinery and the
        orchestrator (all autospec'd) around a persist_character call.
        Takes the orchestrator's canned result; yields the apply/unified
        mocks. NOTE: type-level autospec records the manager instance as
        the first positional arg of apply_templates."""

        @contextlib.contextmanager
        def install(generated: CharacterGenerationResult):
            template_collection = scene.world_state_manager.template_collection
            with (
                patch.object(
                    type(template_collection),
                    "collect_all",
                    autospec=True,
                    return_value=attribute_templates,
                ),
                patch.object(
                    type(scene.world_state_manager),
                    "apply_templates",
                    autospec=True,
                ) as mock_apply,
                patch.object(
                    creator,
                    "generate_character_aspects",
                    autospec=True,
                    return_value=generated,
                ) as mock_unified,
            ):
                yield SimpleNamespace(apply=mock_apply, unified=mock_unified)

        return install

    _BRAM_RESULT = CharacterGenerationResult(
        name="Bram", description="A veteran.", dialogue_instructions="Gruff."
    )

    @pytest.mark.asyncio
    async def test_fast_mode_consolidates_attribute_templates(
        self, scene, director, fast_mode, fold_mocks, attribute_templates
    ):
        # attribute templates fold into the one-shot as instructions instead
        # of one prompt per template
        with fold_mocks(
            CharacterGenerationResult(
                name="Bram",
                description="A veteran.",
                attributes={"Appearance": "scarred and weathered"},
                dialogue_instructions="Gruff.",
            )
        ) as m:
            character = await director.persist_character(
                PersistCharacterRequest(
                    name="Bram",
                    determine_name=False,
                    templates=["t1", "t2"],
                    narrate_entry=False,
                    active=False,
                )
            )

        assert "attributes" in m.unified.await_args.args[0].aspects
        # template placeholders are formatted with the final name
        assert m.unified.await_args.args[0].attribute_instructions == [
            {
                "attribute": "Appearance of Bram",
                "instructions": "looks fitting for Bram",
            }
        ]
        # only the non-attribute template is applied separately
        assert list(m.apply.await_args.args[1]) == [attribute_templates["t2"]]
        assert character.base_attributes == {"Appearance": "scarred and weathered"}

    @pytest.mark.asyncio
    async def test_fast_mode_attribute_templates_flag_off(
        self, scene, director, creator, fast_mode, fold_mocks
    ):
        # 'Attribute templates' deselected from Consolidate - attribute
        # templates suppress the aspect and are applied separately, as before
        creator.actions["character_creation"].config["consolidate"].value = [
            flag for flag in DEFAULT_CONSOLIDATE if flag != "attribute_templates"
        ]
        try:
            with fold_mocks(self._BRAM_RESULT) as m:
                await director.persist_character(
                    PersistCharacterRequest(
                        name="Bram",
                        determine_name=False,
                        templates=["t1", "t2"],
                        narrate_entry=False,
                        active=False,
                    )
                )
        finally:
            creator.actions["character_creation"].config["consolidate"].value = list(
                DEFAULT_CONSOLIDATE
            )

        assert "attributes" not in m.unified.await_args.args[0].aspects
        assert m.unified.await_args.args[0].attribute_instructions is None
        # both templates applied separately
        assert len(list(m.apply.await_args.args[1])) == 2

    @pytest.mark.asyncio
    async def test_fast_mode_templates_not_folded_when_aspect_not_one_shot(
        self, scene, director, fast_mode, fold_mocks
    ):
        # generate_attributes=False: the attributes aspect is not one-shot,
        # so the templates must apply per-template, not vanish
        with fold_mocks(self._BRAM_RESULT) as m:
            await director.persist_character(
                PersistCharacterRequest(
                    name="Bram",
                    determine_name=False,
                    generate_attributes=False,
                    templates=["t1", "t2"],
                    narrate_entry=False,
                    active=False,
                )
            )

        assert m.unified.await_args.args[0].attribute_instructions is None
        # both templates still applied separately
        assert len(list(m.apply.await_args.args[1])) == 2

    @pytest.mark.asyncio
    async def test_fast_mode_templates_folded_with_placeholder_name(
        self, scene, director, fast_mode, fold_mocks, attribute_templates
    ):
        # determine_name=True with a blank name (the scene tools introduce
        # flow): the fold happens, with template placeholders formatted as
        # "the character" until the name is determined
        with fold_mocks(
            CharacterGenerationResult(
                name="Bram",
                description="A veteran.",
                attributes={"Appearance of the character": "scarred"},
                dialogue_instructions="Gruff.",
            )
        ) as m:
            await director.persist_character(
                PersistCharacterRequest(
                    name="",
                    determine_name=True,
                    templates=["t1", "t2"],
                    narrate_entry=False,
                    active=False,
                )
            )

        assert m.unified.await_args.args[0].attribute_instructions == [
            {
                "attribute": "Appearance of the character",
                "instructions": "looks fitting for the character",
            }
        ]
        # only the non-attribute template is applied separately
        assert list(m.apply.await_args.args[1]) == [attribute_templates["t2"]]

    @pytest.mark.asyncio
    async def test_fast_mode_templates_folded_provisional_name_not_baked_in(
        self, scene, director, fast_mode, fold_mocks
    ):
        # determine_name=True with a provisional name (the scene tools flow
        # substitutes "new character" when the user leaves the name blank):
        # the placeholders must still format as "the character" - the same
        # one-shot is being asked to invent the name
        with fold_mocks(
            CharacterGenerationResult(
                name="Bram",
                description="A veteran.",
                attributes={"Appearance of the character": "scarred"},
                dialogue_instructions="Gruff.",
            )
        ) as m:
            await director.persist_character(
                PersistCharacterRequest(
                    name="new character",
                    determine_name=True,
                    templates=["t1", "t2"],
                    narrate_entry=False,
                    active=False,
                )
            )

        assert m.unified.await_args.args[0].attribute_instructions == [
            {
                "attribute": "Appearance of the character",
                "instructions": "looks fitting for the character",
            }
        ]

    @pytest.mark.asyncio
    async def test_fast_mode_augment_attributes_folded(
        self, scene, director, fast_mode, fold_mocks
    ):
        # a caller-supplied augment instruction folds into the one-shot
        # alongside the template instructions (it must not vanish)
        with fold_mocks(
            CharacterGenerationResult(
                name="Bram",
                description="A veteran.",
                attributes={"Appearance": "scarred"},
                dialogue_instructions="Gruff.",
            )
        ) as m:
            await director.persist_character(
                PersistCharacterRequest(
                    name="Bram",
                    determine_name=False,
                    templates=["t1", "t2"],
                    augment_attributes="Add some additional, interesting attributes.",
                    narrate_entry=False,
                    active=False,
                )
            )

        assert m.unified.await_args.args[0].augment_attributes == (
            "Add some additional, interesting attributes."
        )

    @pytest.mark.asyncio
    async def test_fast_mode_templates_not_folded_when_attributes_deselected(
        self, scene, director, creator, fast_mode, fold_mocks
    ):
        # Attributes deselected from Consolidate (with 'Attribute templates'
        # still selected): the fold must not strip the templates - they
        # apply per-template
        creator.actions["character_creation"].config["consolidate"].value = [
            "name",
            "description",
            "dialogue_instructions",
            "attribute_templates",
        ]
        try:
            with fold_mocks(self._BRAM_RESULT) as m:
                await director.persist_character(
                    PersistCharacterRequest(
                        name="Bram",
                        determine_name=False,
                        templates=["t1", "t2"],
                        narrate_entry=False,
                        active=False,
                    )
                )
        finally:
            creator.actions["character_creation"].config["consolidate"].value = list(
                DEFAULT_CONSOLIDATE
            )

        assert m.unified.await_args.args[0].attribute_instructions is None
        assert len(list(m.apply.await_args.args[1])) == 2

    @pytest.mark.asyncio
    async def test_empty_name_rejected_regardless_of_flags(self, scene, director):
        # the node-chain hole: generate=True + determine_name=False + no name
        with pytest.raises(ValueError, match="name is required"):
            await director.persist_character(
                PersistCharacterRequest(
                    name="", determine_name=False, narrate_entry=False, active=False
                )
            )

    @pytest.mark.asyncio
    async def test_split_mode_empty_determined_name_raises(self, scene, director):
        # a junk name response ("<NAME>.</NAME>" strips to nothing) reads as
        # an empty determined name - the name guard must reject it before
        # any character is created
        async with MockClientContext():
            client_responses.get().append(name_response("."))
            with pytest.raises(ValueError, match="name is required"):
                await director.persist_character(
                    PersistCharacterRequest(
                        name="the tall woman",
                        determine_name=True,
                        narrate_entry=False,
                        active=False,
                    )
                )

        assert prompt_kinds(scene.mock_client) == [KIND_NAME]

    @pytest.mark.asyncio
    async def test_split_mode_generated_sheet_capped_by_max_attributes(
        self, scene, director
    ):
        # the trailing enforcement block was removed - for generated sheets
        # the cap relies on max_attributes threading through extraction. The
        # primed Name line is scaffold, so a limit of 2 buys 2 attributes
        # beside it
        director.actions["character_management"].config["max_attributes"].value = 2
        try:
            async with MockClientContext():
                client_responses.get().append(name_response("Elena"))
                client_responses.get().append(
                    sheet_response(
                        "Elena", {"Age": "30", "Occupation": "healer", "Height": "tall"}
                    )
                )
                client_responses.get().append(
                    description_response("Elena", "is a healer.")
                )
                client_responses.get().append("Soft.")
                character = await director.persist_character(
                    PersistCharacterRequest(
                        name="the tall woman",
                        content="A healer arrives.",
                        narrate_entry=False,
                        active=False,
                    )
                )
        finally:
            director.actions["character_management"].config["max_attributes"].value = 0

        assert character.base_attributes == {
            "Name": "Elena",
            "Age": "30",
            "Occupation": "healer",
        }

    @pytest.mark.asyncio
    async def test_split_mode_template_overflow_truncated_before_prompts(
        self, scene, director, attribute_templates
    ):
        # template-applied attributes are not capped by the producers - the
        # hoisted enforcement must truncate them before the downstream
        # prompts render the sheet
        director.actions["character_management"].config["max_attributes"].value = 2
        template_collection = scene.world_state_manager.template_collection

        async def fake_apply(
            _manager, templates, character_name=None, information=None
        ):
            scene.get_character(character_name).base_attributes.update(
                {"Name": "Bram", "Age": "40", "Occupation": "smith", "Height": "tall"}
            )

        try:
            with (
                patch.object(
                    type(template_collection),
                    "collect_all",
                    autospec=True,
                    return_value=attribute_templates,
                ),
                patch.object(
                    type(scene.world_state_manager),
                    "apply_templates",
                    autospec=True,
                    side_effect=fake_apply,
                ),
            ):
                async with MockClientContext():
                    client_responses.get().append(
                        description_response("Bram", "is a veteran.")
                    )
                    client_responses.get().append("Gruff.")
                    character = await director.persist_character(
                        PersistCharacterRequest(
                            name="Bram",
                            determine_name=False,
                            templates=["t1", "t2"],
                            narrate_entry=False,
                            active=False,
                        )
                    )
        finally:
            director.actions["character_management"].config["max_attributes"].value = 0

        # capped to the first two budgeted attributes (insertion order, the
        # character's own name is free) before the description prompt - the
        # prompt must not render the discarded attributes
        assert character.base_attributes == {
            "Name": "Bram",
            "Age": "40",
            "Occupation": "smith",
        }
        description_prompt = str(scene.mock_client.prompt_history[0]["prompt"])
        assert "Age: 40" in description_prompt
        assert "Height" not in description_prompt


def test_split_aspect_loading_messages_cover_every_aspect():
    # the unguarded callback lookup depends on the mapping being total
    assert set(SPLIT_ASPECT_LOADING_MESSAGES) == set(CHARACTER_GENERATION_ASPECTS)


class TestPersistCharacterWebsocketHandler:
    """The manual-mode activation parity rule in handle_persist_character."""

    async def _persisted_request(
        self, scene, director, payload: dict
    ) -> PersistCharacterRequest:
        """Run handle_persist_character with persist_character replaced by an
        autospec'd recorder; returns the request it was awaited with."""
        ws = SimpleNamespace(scene=scene, queue_put=Mock())
        handler = DirectorWebsocketHandler(websocket_handler=ws)
        handler.signal_operation_done = AsyncMock()

        with patch.object(
            director,
            "persist_character",
            autospec=True,
            return_value=Character(name="X"),
        ) as mock_persist:
            await handler.handle_persist_character(payload)
            await asyncio.sleep(0)

        return mock_persist.await_args.args[0]

    @pytest.mark.asyncio
    async def test_manual_npc_activated_when_no_active_npcs(self, scene, director):
        request = await self._persisted_request(
            scene,
            director,
            {
                "name": "Manual NPC",
                "generate": False,
                "is_player": False,
                "active": False,
                "narrate_entry": False,
            },
        )
        assert request.active is True

    @pytest.mark.asyncio
    async def test_manual_player_activated(self, scene, director):
        request = await self._persisted_request(
            scene,
            director,
            {
                "name": "Manual Player",
                "generate": False,
                "is_player": True,
                "active": False,
                "narrate_entry": False,
            },
        )
        assert request.active is True

    @pytest.mark.asyncio
    async def test_ai_payload_active_untouched(self, scene, director):
        request = await self._persisted_request(
            scene,
            director,
            {
                "name": "AI NPC",
                "generate": True,
                "is_player": False,
                "active": False,
                "narrate_entry": False,
            },
        )
        assert request.active is False
