"""Tests for the TTS agent.

Baseline coverage of the TTS agent's *current* behaviour ahead of a refactor
that will introduce dynamic OpenAI-compatible backends.

External integrations (real audio bytes, websocket emit, LLM/summarizer calls)
are mocked. Domain objects (TTSAgent, Voice, VoiceLibrary, Chunk, real Scenes
where needed) are instantiated directly rather than mocked.
"""

from __future__ import annotations

import asyncio
import json
import os
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pydantic
import pytest
import pytest_asyncio

import talemate.agents.tts.pocket_tts as pocket_tts_module
import talemate.agents.tts.voice_library as voice_library
import talemate.instance as instance
from talemate.agents.tts import TTSAgent
from talemate.agents.tts.openai_compatible import (
    _parse_voices_payload,
    _resolve_voices_url,
)
from talemate.config.state import get_config
from talemate.agents.tts.schema import (
    Chunk,
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_VOICE,
    Voice,
    VoiceLibrary,
)
from talemate.agents.tts.voice_library import (
    _apply_default_voice_migration,
    load_scene_voice_library,
    save_scene_voice_library,
    scoped_voice_library,
    voices_for_apis,
)
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
)
from talemate.ux.schema import Action


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_voice(
    label: str = "Test Voice",
    provider: str = "kokoro",
    provider_id: str = "vid",
    **kwargs,
) -> Voice:
    return Voice(label=label, provider=provider, provider_id=provider_id, **kwargs)


@pytest.fixture
def fresh_voice_library():
    """Replace the global voice library with a fresh empty instance."""
    original = voice_library.VOICE_LIBRARY
    voice_library.VOICE_LIBRARY = VoiceLibrary(voices={})
    try:
        yield voice_library.VOICE_LIBRARY
    finally:
        voice_library.VOICE_LIBRARY = original


@pytest.fixture
def tts_agent(fresh_voice_library):
    """Provide a fresh TTSAgent with an empty global voice library."""
    return TTSAgent()


class FakeCharacter:
    """Minimal stand-in for talemate.character.Character used in voice routing."""

    def __init__(self, name: str, voice: Voice | None = None):
        self.name = name
        self.voice = voice


class FakeScene:
    """Lightweight scene stand-in exposing only the attributes the agent reads."""

    def __init__(
        self,
        characters: list[FakeCharacter] | None = None,
        environment: str = "scene",
        info_dir: str | None = None,
    ):
        self.characters = characters or []
        self.environment = environment
        self.info_dir = info_dir
        self.voice_library = VoiceLibrary()
        self.agent_state: dict = {}

    def get_character(self, name: str) -> FakeCharacter | None:
        for c in self.characters:
            if c.name == name:
                return c
        return None


# ---------------------------------------------------------------------------
# Voice schema
# ---------------------------------------------------------------------------


class TestVoiceSchema:
    def test_id_is_provider_colon_provider_id(self):
        voice = Voice(label="Adam", provider="kokoro", provider_id="am_adam")
        assert voice.id == "kokoro:am_adam"

    def test_id_changes_when_provider_changes(self):
        voice = Voice(label="Adam", provider="kokoro", provider_id="am_adam")
        assert voice.id == "kokoro:am_adam"
        voice.provider = "openai"
        assert voice.id == "openai:am_adam"

    def test_too_many_tags_rejected(self):
        too_many = [f"tag{i}" for i in range(MAX_TAGS_PER_VOICE + 1)]
        with pytest.raises(pydantic.ValidationError):
            Voice(
                label="X",
                provider="p",
                provider_id="pid",
                tags=too_many,
            )

    def test_exactly_max_tags_accepted(self):
        # boundary - exactly MAX_TAGS_PER_VOICE is fine
        ok = [f"tag{i}" for i in range(MAX_TAGS_PER_VOICE)]
        voice = Voice(label="X", provider="p", provider_id="pid", tags=ok)
        assert len(voice.tags) == MAX_TAGS_PER_VOICE

    def test_tag_too_long_rejected(self):
        too_long = "a" * (MAX_TAG_LENGTH + 1)
        with pytest.raises(pydantic.ValidationError):
            Voice(
                label="X",
                provider="p",
                provider_id="pid",
                tags=[too_long],
            )

    def test_tag_at_max_length_accepted(self):
        ok_tag = "b" * MAX_TAG_LENGTH
        voice = Voice(label="X", provider="p", provider_id="pid", tags=[ok_tag])
        assert voice.tags == [ok_tag]


# ---------------------------------------------------------------------------
# Chunk schema
# ---------------------------------------------------------------------------


class TestChunk:
    def test_cleaned_text_strips_special_characters(self):
        chunk = Chunk(text=['*hello* "world" `code`'], type="exposition")
        cleaned = chunk.cleaned_text
        assert "*" not in cleaned
        assert '"' not in cleaned
        assert "`" not in cleaned
        assert "hello world code." == cleaned

    def test_cleaned_text_replaces_em_dash_ellipsis_semicolon(self):
        chunk = Chunk(
            text=["She paused — then continued… and laughed; loudly"],
            type="exposition",
        )
        cleaned = chunk.cleaned_text
        # em dash becomes " - "
        assert " - " in cleaned
        # ellipsis char becomes "..."
        assert "..." in cleaned
        assert "…" not in cleaned
        # semicolon becomes comma
        assert ";" not in cleaned
        assert "and laughed, loudly" in cleaned

    def test_cleaned_text_collapses_whitespace(self):
        chunk = Chunk(text=["Hello   world\t\twith\nmany   spaces"], type="exposition")
        cleaned = chunk.cleaned_text
        # only single spaces between words
        assert "  " not in cleaned
        assert "\t" not in cleaned
        assert "\n" not in cleaned
        assert "Hello world with many spaces." == cleaned

    def test_cleaned_text_lowercases_uppercase_runs_of_two_or_more(self):
        chunk = Chunk(text=["I am OK with HELLO but A is fine"], type="exposition")
        cleaned = chunk.cleaned_text
        # Both runs of 2+ uppercase chars are lowered, single "I" and "A" kept
        assert "I am ok with hello but A is fine." == cleaned

    def test_cleaned_text_adds_terminal_period(self):
        chunk = Chunk(text=["no terminator"], type="exposition")
        assert chunk.cleaned_text.endswith(".")

    def test_cleaned_text_preserves_existing_terminator(self):
        chunk_q = Chunk(text=["really?"], type="exposition")
        assert chunk_q.cleaned_text == "really?"

        chunk_e = Chunk(text=["wow!"], type="exposition")
        assert chunk_e.cleaned_text == "wow!"

    def test_cleaned_text_strips_trailing_commas(self):
        chunk = Chunk(text=["hello,"], type="exposition")
        # trailing comma is stripped, then a period is appended
        assert chunk.cleaned_text == "hello."

    def test_sub_chunks_single_text_returns_self(self):
        chunk = Chunk(text=["only one"], type="dialogue")
        sub = chunk.sub_chunks
        assert len(sub) == 1
        assert sub[0] is chunk

    def test_sub_chunks_multiple_text_returns_distinct_chunks(self):
        voice = _make_voice()
        chunk = Chunk(
            text=["first", "second", "third"],
            type="dialogue",
            api="kokoro",
            voice=voice,
            model="some-model",
            character_name="John",
            message_id=42,
        )
        sub = chunk.sub_chunks
        assert len(sub) == 3
        assert [s.text for s in sub] == [["first"], ["second"], ["third"]]

        for s in sub:
            assert s.type == "dialogue"
            assert s.api == "kokoro"
            assert s.model == "some-model"
            assert s.character_name == "John"
            assert s.message_id == 42
            # voice is copied by value, not the same instance
            assert s.voice == voice
            assert s.voice is not voice


# ---------------------------------------------------------------------------
# VoiceLibrary migration / helpers
# ---------------------------------------------------------------------------


class TestVoiceLibraryMigration:
    def test_provider_with_zero_voices_gets_defaults(self, monkeypatch):
        defaults = {
            "openai:alloy": Voice(
                label="Alloy", provider="openai", provider_id="alloy"
            ),
            "openai:echo": Voice(label="Echo", provider="openai", provider_id="echo"),
        }
        monkeypatch.setattr(voice_library, "DEFAULT_VOICES", defaults)

        library = VoiceLibrary(voices={})
        changed = _apply_default_voice_migration(library)

        assert changed is True
        assert "openai:alloy" in library.voices
        assert "openai:echo" in library.voices

    def test_provider_with_existing_voices_unchanged(self, monkeypatch):
        defaults = {
            "openai:alloy": Voice(
                label="Alloy", provider="openai", provider_id="alloy"
            ),
            "openai:echo": Voice(label="Echo", provider="openai", provider_id="echo"),
        }
        monkeypatch.setattr(voice_library, "DEFAULT_VOICES", defaults)

        existing = Voice(label="Custom", provider="openai", provider_id="custom")
        library = VoiceLibrary(voices={existing.id: existing})

        changed = _apply_default_voice_migration(library)

        assert changed is False
        # Only the user's own voice survives - defaults were skipped wholesale
        assert list(library.voices.keys()) == [existing.id]

    def test_independent_providers_handled_independently(self, monkeypatch):
        defaults = {
            "openai:alloy": Voice(
                label="Alloy", provider="openai", provider_id="alloy"
            ),
            "kokoro:am_adam": Voice(
                label="Adam", provider="kokoro", provider_id="am_adam"
            ),
        }
        monkeypatch.setattr(voice_library, "DEFAULT_VOICES", defaults)

        # User has an openai voice but no kokoro voices
        existing = Voice(label="Custom", provider="openai", provider_id="custom")
        library = VoiceLibrary(voices={existing.id: existing})

        changed = _apply_default_voice_migration(library)

        assert changed is True
        # openai untouched (user already has at least one)
        assert "openai:alloy" not in library.voices
        # kokoro defaults injected (provider had zero voices)
        assert "kokoro:am_adam" in library.voices


class TestVoicesForApis:
    def test_filters_by_provider_list(self):
        v1 = Voice(label="A", provider="kokoro", provider_id="a")
        v2 = Voice(label="B", provider="openai", provider_id="b")
        v3 = Voice(label="C", provider="elevenlabs", provider_id="c")
        v4 = Voice(label="D", provider="kokoro", provider_id="d")

        library = VoiceLibrary(voices={v.id: v for v in [v1, v2, v3, v4]})

        result = voices_for_apis(["kokoro", "openai"], library)
        result_ids = {v.id for v in result}
        assert result_ids == {v1.id, v2.id, v4.id}

    def test_empty_apis_returns_empty(self):
        v1 = Voice(label="A", provider="kokoro", provider_id="a")
        library = VoiceLibrary(voices={v1.id: v1})
        assert voices_for_apis([], library) == []

    def test_unknown_apis_returns_empty(self):
        v1 = Voice(label="A", provider="kokoro", provider_id="a")
        library = VoiceLibrary(voices={v1.id: v1})
        assert voices_for_apis(["totally_unknown"], library) == []


# ---------------------------------------------------------------------------
# scoped_voice_library + scene voice library load/save
# ---------------------------------------------------------------------------


class TestScopedVoiceLibrary:
    def test_global_scope_uses_global_instance(self, fresh_voice_library):
        scoped = scoped_voice_library("global")
        assert scoped.voice_library is fresh_voice_library

    @pytest.mark.asyncio
    async def test_global_scope_save_calls_global_save(
        self, fresh_voice_library, monkeypatch
    ):
        called: list[VoiceLibrary] = []

        async def fake_save(library: VoiceLibrary):
            called.append(library)

        monkeypatch.setattr(voice_library, "save_voice_library", fake_save)
        # scoped_voice_library captures save_voice_library by reference at
        # call time, so we re-import after patch.
        scoped = voice_library.scoped_voice_library("global")
        await scoped.save()

        assert called == [fresh_voice_library]

    def test_scene_scope_requires_scene(self):
        with pytest.raises(ValueError):
            scoped_voice_library("scene", scene=None)

    def test_scene_scope_uses_scene_voice_library(self, tmp_path):
        scene = FakeScene(info_dir=str(tmp_path))
        scoped = scoped_voice_library("scene", scene=scene)
        assert scoped.voice_library is scene.voice_library

    @pytest.mark.asyncio
    async def test_scene_scope_save_writes_to_info_dir(self, tmp_path):
        scene = FakeScene(info_dir=str(tmp_path))
        v = Voice(label="A", provider="kokoro", provider_id="a")
        scene.voice_library.voices[v.id] = v

        scoped = scoped_voice_library("scene", scene=scene)
        await scoped.save()

        path = tmp_path / "voice-library.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert "kokoro:a" in data["voices"]


class TestSceneVoiceLibrary:
    @pytest.mark.asyncio
    async def test_load_returns_empty_when_file_missing(self, tmp_path):
        scene = FakeScene(info_dir=str(tmp_path))
        library = await load_scene_voice_library(scene)
        assert library.voices == {}

    @pytest.mark.asyncio
    async def test_round_trip_save_then_load(self, tmp_path):
        scene = FakeScene(info_dir=str(tmp_path))
        original = VoiceLibrary(
            voices={
                "kokoro:a": Voice(label="A", provider="kokoro", provider_id="a"),
                "openai:b": Voice(label="B", provider="openai", provider_id="b"),
            }
        )

        await save_scene_voice_library(scene, original)
        loaded = await load_scene_voice_library(scene)

        assert set(loaded.voices.keys()) == {"kokoro:a", "openai:b"}
        assert loaded.voices["kokoro:a"].label == "A"
        assert loaded.voices["openai:b"].provider == "openai"

    @pytest.mark.asyncio
    async def test_load_corrupted_json_returns_empty(self, tmp_path):
        scene = FakeScene(info_dir=str(tmp_path))
        os.makedirs(scene.info_dir, exist_ok=True)
        path = Path(scene.info_dir) / "voice-library.json"
        path.write_text("{ this is not valid json :::")

        library = await load_scene_voice_library(scene)
        assert library.voices == {}

    @pytest.mark.asyncio
    async def test_save_creates_missing_info_dir(self, tmp_path):
        # info_dir does not exist yet
        scene = FakeScene(info_dir=str(tmp_path / "info"))
        v = Voice(label="A", provider="kokoro", provider_id="a")
        await save_scene_voice_library(scene, VoiceLibrary(voices={v.id: v}))
        assert (Path(scene.info_dir) / "voice-library.json").exists()


# ---------------------------------------------------------------------------
# TTSAgent api_* helpers
# ---------------------------------------------------------------------------


class TestTTSAgentApiHelpers:
    def test_api_enabled_reflects_apis_list(self, tts_agent):
        tts_agent.actions["_config"].config["apis"].value = ["kokoro", "openai"]
        assert tts_agent.api_enabled("kokoro") is True
        assert tts_agent.api_enabled("openai") is True
        assert tts_agent.api_enabled("elevenlabs") is False

    def test_api_configured_uses_provider_property(self, tts_agent):
        # kokoro_configured (static path) is True regardless of state
        assert tts_agent.api_configured("kokoro") is True

        # Dynamic backend: configured iff its api_url is set on the child action.
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        tts_agent.actions["test-be"].config["api_url"].value = ""
        assert tts_agent.api_configured("test-be") is False
        tts_agent.actions["test-be"].config[
            "api_url"
        ].value = "http://localhost:8000/v1"
        assert tts_agent.api_configured("test-be") is True

    def test_api_configured_default_true_when_property_missing(self, tts_agent):
        # api with no _configured property defaults to True (getattr default=True)
        assert tts_agent.api_configured("does_not_exist") is True

    def test_api_ready_requires_enabled_and_configured(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        # Registering injected the backend slug into apis.choices as a
        # dynamic-marked dict — flip the apis-enabled list to enable it.
        choices = tts_agent.actions["_config"].config["apis"].choices
        assert any(
            c.get("value") == "test-be" and c.get("_dynamic_backend") is True
            for c in choices
        )
        tts_agent.actions["_config"].config["apis"].value = ["test-be"]

        # configured + enabled -> ready
        tts_agent.actions["test-be"].config[
            "api_url"
        ].value = "http://localhost:8000/v1"
        assert tts_agent.api_ready("test-be") is True

        # not configured -> not ready
        tts_agent.actions["test-be"].config["api_url"].value = ""
        assert tts_agent.api_ready("test-be") is False

        # configured but not enabled -> not ready
        tts_agent.actions["test-be"].config[
            "api_url"
        ].value = "http://localhost:8000/v1"
        tts_agent.actions["_config"].config["apis"].value = []
        assert tts_agent.api_ready("test-be") is False

    def test_ready_apis_only_includes_ready(self, tts_agent):
        # enable kokoro (always configured) and a dynamic backend (only if
        # api_url set)
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        tts_agent.actions["_config"].config["apis"].value = [
            "kokoro",
            "test-be",
        ]
        tts_agent.actions["test-be"].config["api_url"].value = ""
        assert tts_agent.ready_apis == ["kokoro"]

        tts_agent.actions["test-be"].config[
            "api_url"
        ].value = "http://localhost:8000/v1"
        assert sorted(tts_agent.ready_apis) == ["kokoro", "test-be"]


class TestTTSAgentApiUsed:
    def test_returns_true_when_narrator_uses_api(self, tts_agent, fresh_voice_library):
        v = Voice(label="Adam", provider="kokoro", provider_id="am_adam")
        fresh_voice_library.voices[v.id] = v
        tts_agent.actions["_config"].config["narrator_voice_id"].value = v.id
        tts_agent.scene = FakeScene(characters=[])

        assert tts_agent.api_used("kokoro") is True
        assert tts_agent.api_used("openai") is False

    def test_returns_true_when_character_voice_uses_api(
        self, tts_agent, fresh_voice_library
    ):
        narrator = Voice(label="N", provider="kokoro", provider_id="nv")
        char_voice = Voice(label="C", provider="openai", provider_id="cv")
        fresh_voice_library.voices[narrator.id] = narrator
        fresh_voice_library.voices[char_voice.id] = char_voice

        tts_agent.actions["_config"].config["narrator_voice_id"].value = narrator.id

        char = FakeCharacter("Alice", voice=char_voice)
        tts_agent.scene = FakeScene(characters=[char])

        assert tts_agent.api_used("openai") is True
        assert tts_agent.api_used("kokoro") is True  # narrator
        assert tts_agent.api_used("elevenlabs") is False

    def test_returns_false_when_no_match(self, tts_agent, fresh_voice_library):
        # narrator not configured to a real voice in library
        tts_agent.actions["_config"].config["narrator_voice_id"].value = "nope:nope"
        tts_agent.scene = FakeScene(characters=[])

        assert tts_agent.api_used("kokoro") is False

    def test_returns_false_when_no_scene(self, tts_agent, fresh_voice_library):
        tts_agent.actions["_config"].config["narrator_voice_id"].value = "nope:nope"
        # ensure no scene attribute
        if hasattr(tts_agent, "scene"):
            delattr(tts_agent, "scene")
        assert tts_agent.api_used("kokoro") is False


# ---------------------------------------------------------------------------
# use_ai_assisted_speaker_separation
# ---------------------------------------------------------------------------


class TestUseAIAssistedSpeakerSeparation:
    def _set(self, agent, mode):
        agent.actions["_config"].config["speaker_separation"].value = mode

    def test_ai_assisted_with_npc_message_returns_true(self, tts_agent):
        self._set(tts_agent, "ai_assisted")
        msg = NarratorMessage(message="hello", source="ai")
        assert tts_agent.use_ai_assisted_speaker_separation("hello", msg) is True

    def test_mixed_with_narrator_message_returns_true(self, tts_agent):
        self._set(tts_agent, "mixed")
        msg = NarratorMessage(message="hello", source="ai")
        assert tts_agent.use_ai_assisted_speaker_separation("hello", msg) is True

    def test_mixed_with_character_message_returns_false(self, tts_agent):
        self._set(tts_agent, "mixed")
        msg = CharacterMessage(message="Alice: hi", source="ai")
        assert tts_agent.use_ai_assisted_speaker_separation("Alice: hi", msg) is False

    def test_simple_with_quotes_still_false(self, tts_agent):
        self._set(tts_agent, "simple")
        msg = CharacterMessage(message='Alice: "hi"', source="ai")
        assert tts_agent.use_ai_assisted_speaker_separation('Alice: "hi"', msg) is False

    def test_player_source_always_false(self, tts_agent):
        self._set(tts_agent, "ai_assisted")
        msg = CharacterMessage(message='Alice: "hi"', source="player")
        assert tts_agent.use_ai_assisted_speaker_separation('Alice: "hi"', msg) is False

    def test_no_message_no_quotes_false(self, tts_agent):
        self._set(tts_agent, "ai_assisted")
        assert tts_agent.use_ai_assisted_speaker_separation("plain text", None) is False

    def test_no_message_with_quotes_returns_true_when_ai_assisted(self, tts_agent):
        self._set(tts_agent, "ai_assisted")
        assert (
            tts_agent.use_ai_assisted_speaker_separation('he said "hi"', None) is True
        )

    def test_no_message_with_quotes_returns_true_when_mixed(self, tts_agent):
        self._set(tts_agent, "mixed")
        assert (
            tts_agent.use_ai_assisted_speaker_separation('he said "hi"', None) is True
        )

    def test_no_message_with_quotes_returns_false_when_simple(self, tts_agent):
        self._set(tts_agent, "simple")
        assert (
            tts_agent.use_ai_assisted_speaker_separation('he said "hi"', None) is False
        )

    def test_exception_path_returns_false(self, tts_agent):
        self._set(tts_agent, "ai_assisted")
        # Pass a message-like sentinel that will raise on attribute access via .source
        bad = object()  # accessing .source raises AttributeError
        # Bypass the no-message branch by ensuring text contains quotes AND
        # message is truthy; this means we hit the message.source line and raise.
        assert (
            tts_agent.use_ai_assisted_speaker_separation('he "said" hi', bad) is False
        )


# ---------------------------------------------------------------------------
# narrator_voice_id_choices
# ---------------------------------------------------------------------------


class TestNarratorVoiceIdChoices:
    def test_only_includes_voices_for_ready_apis(self, tts_agent, fresh_voice_library):
        # Only kokoro ready by default
        v_kokoro = Voice(label="Adam", provider="kokoro", provider_id="am_adam")
        v_openai = Voice(label="Alloy", provider="openai", provider_id="alloy")
        fresh_voice_library.voices[v_kokoro.id] = v_kokoro
        fresh_voice_library.voices[v_openai.id] = v_openai

        tts_agent.actions["_config"].config["apis"].value = ["kokoro"]
        choices = TTSAgent.narrator_voice_id_choices(tts_agent)

        assert {c["value"] for c in choices} == {v_kokoro.id}

    def test_choices_sorted_by_label(self, tts_agent, fresh_voice_library):
        for label, pid in [("Charlie", "c"), ("Alice", "a"), ("Bob", "b")]:
            v = Voice(label=label, provider="kokoro", provider_id=pid)
            fresh_voice_library.voices[v.id] = v

        tts_agent.actions["_config"].config["apis"].value = ["kokoro"]
        choices = TTSAgent.narrator_voice_id_choices(tts_agent)

        assert [c["label"] for c in choices] == [
            "Alice (kokoro)",
            "Bob (kokoro)",
            "Charlie (kokoro)",
        ]

    def test_choice_label_format_is_label_paren_provider(
        self, tts_agent, fresh_voice_library
    ):
        v = Voice(label="Adam", provider="kokoro", provider_id="am_adam")
        fresh_voice_library.voices[v.id] = v
        tts_agent.actions["_config"].config["apis"].value = ["kokoro"]
        choices = TTSAgent.narrator_voice_id_choices(tts_agent)
        assert choices == [{"label": "Adam (kokoro)", "value": "kokoro:am_adam"}]


# ---------------------------------------------------------------------------
# OpenAICompatibleMixin
# ---------------------------------------------------------------------------


class TestOpenAICompatibleMixin:
    """Per-backend OpenAI-compatible helpers.

    Per-backend config now lives on a synthesized child action keyed by the
    backend slug. The mixin's helpers take the slug as their first argument
    and are reachable through ``api_attr`` / ``api_method`` / direct
    ``_openai_compatible_<name>`` access.
    """

    SLUG = "test-be"
    LABEL = "Test Backend"

    def _register(self, agent):
        agent.register_dynamic_child("openai_compatible", self.SLUG, self.LABEL)

    def test_configured_when_api_url_set(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config[
            "api_url"
        ].value = "http://localhost:8000/v1"
        assert tts_agent._openai_compatible_configured(self.SLUG) is True
        # api_attr should resolve to the same value via the registry bridge
        assert tts_agent.api_attr(self.SLUG, "configured") is True

    def test_not_configured_when_api_url_blank(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config["api_url"].value = ""
        assert tts_agent._openai_compatible_configured(self.SLUG) is False
        assert tts_agent.api_attr(self.SLUG, "configured") is False

    def test_not_configured_reason_when_url_missing(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config["api_url"].value = ""
        assert (
            tts_agent._openai_compatible_not_configured_reason(self.SLUG)
            == "API base URL not set"
        )

    def test_not_configured_reason_none_when_url_set(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config[
            "api_url"
        ].value = "http://localhost:8000/v1"
        assert tts_agent._openai_compatible_not_configured_reason(self.SLUG) is None

    def test_not_configured_action_targets_settings(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config["api_url"].value = ""
        action = tts_agent._openai_compatible_not_configured_action(self.SLUG)
        assert isinstance(action, Action)
        assert action.action_name == "openAgentSettings"
        # Action points at the backend's tab, not the management tab
        assert action.arguments == ["tts", self.SLUG]

    def test_not_configured_action_none_when_configured(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config[
            "api_url"
        ].value = "http://localhost:8000/v1"
        assert tts_agent._openai_compatible_not_configured_action(self.SLUG) is None

    def test_agent_details_error_when_not_configured(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config["api_url"].value = ""
        details = tts_agent._openai_compatible_agent_details(self.SLUG)
        url_key = f"{self.SLUG}_url"
        model_key = f"{self.SLUG}_model"
        assert url_key in details
        assert details[url_key]["color"] == "error"
        assert "API URL not set" in details[url_key]["value"]
        # No model detail when not configured
        assert model_key not in details

    def test_agent_details_show_url_and_model_when_configured(self, tts_agent):
        self._register(tts_agent)
        tts_agent.actions[self.SLUG].config[
            "api_url"
        ].value = "http://localhost:9000/v1"
        tts_agent.actions[self.SLUG].config["model"].value = "tts-2"
        details = tts_agent._openai_compatible_agent_details(self.SLUG)
        url_key = f"{self.SLUG}_url"
        model_key = f"{self.SLUG}_model"

        assert details[url_key]["value"] == "http://localhost:9000/v1"
        # not error-flavored when configured
        assert details[url_key].get("color") != "error"
        assert details[model_key]["value"] == "tts-2"

    def test_management_tab_has_only_dynamic_children_field(self, tts_agent):
        """The static management tab no longer carries per-backend config —
        it only carries the dynamic-children registry blob."""
        management = tts_agent.actions["openai_compatible"]
        assert list(management.config.keys()) == ["dynamic_children"]
        assert "api_url" not in management.config
        assert "api_key" not in management.config
        assert "model" not in management.config


# ---------------------------------------------------------------------------
# api_status
# ---------------------------------------------------------------------------


class TestApiStatus:
    def test_returns_one_status_per_registered_api_sorted(self, tts_agent):
        statuses = tts_agent.api_status
        names = [s.api for s in statuses]
        assert names == sorted(names)
        # all currently registered apis appear
        assert set(names) == set(tts_agent.all_apis)

    def test_enabled_ready_configured_flags_reflect_state(self, tts_agent):
        # Register a dynamic OpenAI-compatible backend; it should appear in
        # api_status alongside the static APIs.
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        tts_agent.actions["_config"].config["apis"].value = ["kokoro"]
        # Ensure the dynamic backend is not configured
        tts_agent.actions["test-be"].config["api_url"].value = ""

        statuses = {s.api: s for s in tts_agent.api_status}
        kokoro = statuses["kokoro"]
        compat = statuses["test-be"]

        assert kokoro.enabled is True
        assert kokoro.configured is True
        assert kokoro.ready is True

        # Backend is registered but not in apis-enabled list and has no api_url
        assert compat.enabled is False
        assert compat.configured is False
        assert compat.ready is False

    def test_surfaces_not_configured_reason_as_error_note(self, tts_agent):
        # A registered dynamic backend with no api_url should surface the
        # "API base URL not set" reason as an error note in api_status.
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        tts_agent.actions["_config"].config["apis"].value = ["test-be"]
        tts_agent.actions["test-be"].config["api_url"].value = ""

        statuses = {s.api: s for s in tts_agent.api_status}
        compat = statuses["test-be"]
        error_notes = [m for m in compat.messages if m.color == "error"]
        assert len(error_notes) == 1
        assert "API base URL not set" in error_notes[0].text

    def test_surfaces_info_as_muted_note(self, tts_agent):
        # kokoro defines a kokoro_info string
        statuses = {s.api: s for s in tts_agent.api_status}
        kokoro = statuses["kokoro"]
        muted = [m for m in kokoro.messages if m.color == "muted"]
        assert len(muted) >= 1
        # should not be empty
        assert all(n.text.strip() for n in muted)


# ---------------------------------------------------------------------------
# tts markup cache
# ---------------------------------------------------------------------------


class TestTTSMarkupCache:
    @pytest.mark.asyncio
    async def test_round_trip_set_then_get(self, tts_agent):
        tts_agent.scene = FakeScene()
        await tts_agent.set_tts_markup_cache("hello world", "[Narrator] hello world")
        result = await tts_agent.get_tts_markup_cache("hello world")
        assert result == "[Narrator] hello world"

    @pytest.mark.asyncio
    async def test_different_text_misses_cache(self, tts_agent):
        tts_agent.scene = FakeScene()
        await tts_agent.set_tts_markup_cache("hello world", "[Narrator] hello world")
        result = await tts_agent.get_tts_markup_cache("something else")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_cache_returns_none(self, tts_agent):
        tts_agent.scene = FakeScene()
        assert await tts_agent.get_tts_markup_cache("anything") is None


# ---------------------------------------------------------------------------
# generate() routing & chunking
# ---------------------------------------------------------------------------


class _SummarizerStub:
    """Stub summarizer agent registered under instance.AGENTS['summarizer']."""

    agent_type = "summarizer"

    async def markup_context_for_tts(self, text: str) -> str:
        # Default: a single narrator chunk
        return f"[Narrator] {text}"

    async def inject_audio_tags_for_tts(self, chunk_entries, tag_format):
        return {}


@pytest_asyncio.fixture
async def generate_agent(tts_agent, fresh_voice_library, monkeypatch):
    """Agent prepared for generate() tests: enabled, kokoro-ready,
    narrator voice in the library, summarizer registered, generation
    side-effects suppressed."""
    # Register a stub summarizer
    original_agents = dict(instance.AGENTS)
    instance.AGENTS["summarizer"] = _SummarizerStub()

    # Enable agent + kokoro
    tts_agent.is_enabled = True
    tts_agent.actions["_config"].config["apis"].value = ["kokoro"]

    # Add a narrator voice to the library
    narrator = Voice(label="Adam", provider="kokoro", provider_id="am_adam")
    fresh_voice_library.voices[narrator.id] = narrator
    tts_agent.actions["_config"].config["narrator_voice_id"].value = narrator.id

    # Default scene
    tts_agent.scene = FakeScene(characters=[])

    # Suppress emit / set_processing emission noise
    monkeypatch.setattr("talemate.agents.tts.emit", MagicMock(), raising=False)

    # Replace _generate_chunk with a recording AsyncMock so we capture what
    # would be sent for synthesis without actually generating audio.
    tts_agent._generate_chunk = AsyncMock()

    # Stub set_background_processing so it doesn't go through the real signal
    async def _noop_set_bg(task, error_handler=None):
        return None

    tts_agent.set_background_processing = _noop_set_bg

    yield tts_agent

    # restore
    instance.AGENTS = original_agents


async def _drain_queue(agent: TTSAgent, timeout: float = 1.0):
    """Wait for the background queue task to drain naturally."""
    if agent._queue_task is not None:
        try:
            await asyncio.wait_for(agent._queue_task, timeout=timeout)
        except asyncio.CancelledError:
            pass


class TestTTSAgentGenerate:
    @pytest.mark.asyncio
    async def test_empty_text_returns_without_enqueue(self, generate_agent):
        await generate_agent.generate("")
        assert len(generate_agent._generation_queue) == 0
        assert generate_agent._queue_id is None
        generate_agent._generate_chunk.assert_not_called()

    @pytest.mark.asyncio
    async def test_text_that_becomes_empty_after_strip_returns(self, generate_agent):
        # appearance.brackets.show defaults to True; force it off so brackets get stripped
        generate_agent.config.appearance.scene.brackets.show = False
        try:
            # Whole text is bracketed -> after strip, empty
            await generate_agent.generate("[hidden content]")
            assert len(generate_agent._generation_queue) == 0
            assert generate_agent._queue_id is None
            generate_agent._generate_chunk.assert_not_called()
        finally:
            generate_agent.config.appearance.scene.brackets.show = True

    @pytest.mark.asyncio
    async def test_no_separation_uses_character_voice_when_ready(
        self, generate_agent, fresh_voice_library
    ):
        char_voice = Voice(label="Char", provider="kokoro", provider_id="cv")
        fresh_voice_library.voices[char_voice.id] = char_voice

        generate_agent.actions["_config"].config["speaker_separation"].value = "none"
        char = FakeCharacter("Alice", voice=char_voice)
        generate_agent.scene = FakeScene(characters=[char])

        await generate_agent.generate("Hello!", character=char)
        await _drain_queue(generate_agent)

        generate_agent._generate_chunk.assert_called_once()
        chunk_arg = generate_agent._generate_chunk.call_args.args[0]
        assert chunk_arg.api == "kokoro"
        assert chunk_arg.voice.provider_id == "cv"
        assert chunk_arg.character_name == "Alice"
        # generate/prepare_fn must be the bound method on the agent
        assert chunk_arg.generate_fn == generate_agent.kokoro_generate

    @pytest.mark.asyncio
    async def test_falls_back_to_narrator_when_character_api_not_ready(
        self, generate_agent, fresh_voice_library, caplog
    ):
        # character voice belongs to openai which is NOT enabled
        char_voice = Voice(label="Char", provider="openai", provider_id="alloy")
        fresh_voice_library.voices[char_voice.id] = char_voice
        char = FakeCharacter("Alice", voice=char_voice)
        generate_agent.scene = FakeScene(characters=[char])
        generate_agent.actions["_config"].config["speaker_separation"].value = "none"

        await generate_agent.generate("hi", character=char)
        await _drain_queue(generate_agent)

        generate_agent._generate_chunk.assert_called_once()
        chunk_arg = generate_agent._generate_chunk.call_args.args[0]
        # Falls back to narrator (kokoro:am_adam)
        assert chunk_arg.voice.provider == "kokoro"
        assert chunk_arg.voice.provider_id == "am_adam"

    @pytest.mark.asyncio
    async def test_simple_separation_splits_dialogue_and_exposition(
        self, generate_agent
    ):
        generate_agent.actions["_config"].config["speaker_separation"].value = "simple"

        text = 'She walked away. "Goodbye!" he called after her.'
        await generate_agent.generate(text)
        await _drain_queue(generate_agent)

        assert generate_agent._generate_chunk.call_count >= 2
        types = [
            call.args[0].type for call in generate_agent._generate_chunk.call_args_list
        ]
        assert "dialogue" in types
        assert "exposition" in types

    @pytest.mark.asyncio
    async def test_oversized_chunk_split_by_size(self, generate_agent):
        generate_agent.actions["_config"].config["speaker_separation"].value = "none"
        # Force a small max_generation_length via chunk_size <= max
        generate_agent.actions["kokoro"].config["chunk_size"].value = 64

        # Build a long text that will need to be split. kokoro's
        # max_generation_length is 256, but min(api_chunk_size, max) = 64
        # when api_chunk_size > 0.
        # Use distinct sentences so parse_chunks can split sensibly.
        sentences = ["This is sentence number {i}.".format(i=i) for i in range(20)]
        text = " ".join(sentences)
        assert len(text) > 64

        await generate_agent.generate(text)
        await _drain_queue(generate_agent)

        # One enqueued (context, chunk) pair per chunk; the chunk's `text`
        # list will hold multiple sub-strings each <= 64 chars.
        assert generate_agent._generate_chunk.call_count == 1
        chunk_arg = generate_agent._generate_chunk.call_args.args[0]
        assert len(chunk_arg.text) > 1
        for piece in chunk_arg.text:
            assert len(piece) <= 64

    @pytest.mark.asyncio
    async def test_inject_audio_tags_is_called_once(self, generate_agent):
        called = []

        async def spy(chunks, summarizer):
            called.append(list(chunks))

        generate_agent._inject_audio_tags = spy
        generate_agent.actions["_config"].config["speaker_separation"].value = "none"
        await generate_agent.generate("Hello world")
        await _drain_queue(generate_agent)
        assert len(called) == 1

    @pytest.mark.asyncio
    async def test_chunk_generate_and_prepare_fn_resolved_via_getattr(
        self, generate_agent
    ):
        generate_agent.actions["_config"].config["speaker_separation"].value = "none"
        await generate_agent.generate("hi")
        await _drain_queue(generate_agent)

        chunk_arg = generate_agent._generate_chunk.call_args.args[0]
        assert chunk_arg.generate_fn == generate_agent.kokoro_generate
        # kokoro has no kokoro_prepare_chunk -> None
        assert chunk_arg.prepare_fn == getattr(
            generate_agent, "kokoro_prepare_chunk", None
        )


# ---------------------------------------------------------------------------
# Queue lifecycle
# ---------------------------------------------------------------------------


class TestQueueLifecycle:
    @pytest.mark.asyncio
    async def test_stop_and_clear_resets_state(self, generate_agent):
        generate_agent.actions["_config"].config["speaker_separation"].value = "none"

        # Enqueue multiple items by making _generate_chunk slow
        block = asyncio.Event()

        async def _slow_chunk(chunk, ctx):
            await block.wait()

        generate_agent._generate_chunk = _slow_chunk

        await generate_agent.generate("hi 1")
        # A queue should now be active
        assert generate_agent._queue_id is not None
        assert generate_agent._queue_task is not None

        await generate_agent.stop_and_clear_queue()

        assert generate_agent._queue_id is None
        assert generate_agent._queue_task is None
        assert len(generate_agent._generation_queue) == 0
        assert generate_agent.playback_done_event.is_set()
        # Unblock to let any pending coroutines exit
        block.set()

    @pytest.mark.asyncio
    async def test_back_to_back_generate_appends_to_same_queue(self, generate_agent):
        generate_agent.actions["_config"].config["speaker_separation"].value = "none"

        # Block processing so the queue stays alive between calls
        block = asyncio.Event()
        seen_ids: list[str] = []

        async def _slow_chunk(chunk, ctx):
            seen_ids.append(generate_agent._queue_id)
            await block.wait()

        generate_agent._generate_chunk = _slow_chunk

        await generate_agent.generate("first")
        first_id = generate_agent._queue_id
        await generate_agent.generate("second")
        second_id = generate_agent._queue_id

        assert first_id is not None
        assert first_id == second_id
        # both items now sit in the same queue (at least one being processed)
        assert (
            len(generate_agent._generation_queue) >= 1
            or generate_agent._queue_task is not None
        )

        # cleanup
        await generate_agent.stop_and_clear_queue()
        block.set()

    @pytest.mark.asyncio
    async def test_queue_drains_naturally_resets_state(self, generate_agent):
        generate_agent.actions["_config"].config["speaker_separation"].value = "none"
        # default _generate_chunk is an AsyncMock that returns immediately
        await generate_agent.generate("just one")
        await _drain_queue(generate_agent)

        # after natural drain, queue state is reset
        assert generate_agent._queue_id is None
        assert len(generate_agent._generation_queue) == 0


# ---------------------------------------------------------------------------
# Websocket handler payload validation
# ---------------------------------------------------------------------------


class TestWebsocketHandlerPayloads:
    def test_voice_ref_payload_validates(self):
        from talemate.agents.tts.websocket_handler import VoiceRefPayload

        ok = VoiceRefPayload(voice_id="kokoro:a", scope="global")
        assert ok.voice_id == "kokoro:a"
        assert ok.scope == "global"

    def test_voice_ref_payload_rejects_invalid_scope(self):
        from talemate.agents.tts.websocket_handler import VoiceRefPayload

        with pytest.raises(pydantic.ValidationError):
            VoiceRefPayload(voice_id="kokoro:a", scope="not-real")

    def test_upload_voice_file_payload_requires_data_url(self):
        from talemate.agents.tts.websocket_handler import UploadVoiceFilePayload

        with pytest.raises(pydantic.ValidationError):
            UploadVoiceFilePayload(
                provider="kokoro", label="x", content="not a data url"
            )

    def test_upload_voice_file_payload_accepts_valid_data_url(self):
        from talemate.agents.tts.websocket_handler import UploadVoiceFilePayload

        payload = UploadVoiceFilePayload(
            provider="kokoro",
            label="x",
            content="data:audio/wav;base64,AAAB",
        )
        assert payload.content.startswith("data:audio/wav;base64,")

    def test_voice_exists_helper(self):
        from talemate.agents.tts.websocket_handler import TTSWebsocketHandler

        handler = object.__new__(TTSWebsocketHandler)

        v = Voice(label="A", provider="kokoro", provider_id="a")
        library = VoiceLibrary(voices={v.id: v})

        assert handler._voice_exists(library, "kokoro:a") is True
        assert handler._voice_exists(library, "kokoro:nope") is False
        assert handler._voice_exists(VoiceLibrary(), "kokoro:a") is False


# ---------------------------------------------------------------------------
# Dynamic OpenAI-compatible backends — TTS specialization
# ---------------------------------------------------------------------------


class TestTTSAgentDynamicBackends:
    """Verify the TTSAgent specialization of the dynamic-children registry.

    Registering a backend should:
      - synthesize a per-backend child action with parent_key set
      - inject a dynamic-marked entry into apis.choices
      - bridge per-backend property lookups (configured/api_url/etc.) through
        ``api_attr`` and ``api_method`` to the underscored mixin helpers
    """

    def test_register_appends_slug_to_dynamic_child_slugs(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        assert "test-be" in tts_agent.dynamic_child_slugs("openai_compatible")

    def test_synthesized_child_has_parent_key(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        assert "test-be" in tts_agent.actions
        assert tts_agent.actions["test-be"].parent_key == "openai_compatible"

    def test_synthesized_child_carries_full_per_backend_config(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        config = tts_agent.actions["test-be"].config
        # Per-backend config that used to live on the management tab now
        # lives here.
        for key in ("api_url", "api_key", "model", "voices_endpoint", "chunk_size"):
            assert key in config

    def test_apis_choices_gains_dynamic_marker_entry(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        choices = tts_agent.actions["_config"].config["apis"].choices
        match = next((c for c in choices if c.get("value") == "test-be"), None)
        assert match is not None
        assert match.get("label") == "Test Backend"
        assert match.get("_dynamic_backend") is True

    def test_api_attr_configured_reflects_api_url(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        tts_agent.actions["test-be"].config["api_url"].value = ""
        assert tts_agent.api_attr("test-be", "configured") is False

        tts_agent.actions["test-be"].config["api_url"].value = "http://example/v1"
        assert tts_agent.api_attr("test-be", "configured") is True

    def test_api_method_returns_callable_for_generate(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        method = tts_agent.api_method("test-be", "generate")
        assert callable(method)

    def test_rejects_slug_collision_with_static_api(self, tts_agent):
        # "kokoro" is a static API; registering a backend with that slug
        # would shadow the static helpers, so it must be rejected.
        import pytest as _pytest

        with _pytest.raises(ValueError, match="reserved"):
            tts_agent.register_dynamic_child("openai_compatible", "kokoro", "My Kokoro")

    def test_rejects_slug_collision_with_registry_key(self, tts_agent):
        import pytest as _pytest

        with _pytest.raises(ValueError, match="reserved"):
            tts_agent.register_dynamic_child(
                "openai_compatible", "openai_compatible", "Self"
            )


class TestTTSAgentDynamicBackendLifecycle:
    """The TTSAgent's lifecycle hooks must clean up scene state when a
    dynamic backend is unregistered:
      - drop slug from apis.value if present
      - purge voices whose provider matches the slug
      - remove the synthesized action
    """

    def test_unregister_removes_synthesized_action(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        assert "test-be" in tts_agent.actions
        tts_agent.unregister_dynamic_child("openai_compatible", "test-be")
        assert "test-be" not in tts_agent.actions

    def test_unregister_strips_slug_from_apis_value(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        tts_agent.actions["_config"].config["apis"].value = [
            "kokoro",
            "test-be",
        ]
        tts_agent.unregister_dynamic_child("openai_compatible", "test-be")
        # kokoro is preserved; test-be is removed.
        assert tts_agent.actions["_config"].config["apis"].value == ["kokoro"]

    @pytest.mark.asyncio
    async def test_unregister_purges_voices_with_matching_provider(
        self, tts_agent, fresh_voice_library, monkeypatch
    ):
        # Suppress the async save side-effect to keep the test sync-safe.
        save_calls: list[VoiceLibrary] = []

        async def _fake_save(library):
            save_calls.append(library)

        monkeypatch.setattr(voice_library, "save_voice_library", _fake_save)

        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")

        # Seed library: a voice from the dynamic backend, a voice from kokoro
        # (must survive), and a voice from another backend slug.
        v_be = Voice(label="V1", provider="test-be", provider_id="v1")
        v_kokoro = Voice(label="K", provider="kokoro", provider_id="k1")
        v_other = Voice(label="O", provider="other-be", provider_id="o1")
        for v in (v_be, v_kokoro, v_other):
            fresh_voice_library.voices[v.id] = v

        # The agent's removal hook spawns an asyncio task to save the library,
        # so the test must run inside an event loop.
        tts_agent.unregister_dynamic_child("openai_compatible", "test-be")

        # Yield control once so the spawned save task can run.
        await asyncio.sleep(0)

        # test-be voice purged; others preserved.
        assert v_be.id not in fresh_voice_library.voices
        assert v_kokoro.id in fresh_voice_library.voices
        assert v_other.id in fresh_voice_library.voices

    def test_unregister_apis_value_only_drops_slug_if_present(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        # apis.value does NOT contain test-be — unregister still works.
        tts_agent.actions["_config"].config["apis"].value = ["kokoro"]
        tts_agent.unregister_dynamic_child("openai_compatible", "test-be")
        assert tts_agent.actions["_config"].config["apis"].value == ["kokoro"]

    def test_refresh_drops_orphan_dynamic_slug_from_apis_value(self, tts_agent):
        # apis.value holds an entry for a dynamic backend that is no longer
        # in the registry blob (e.g., the user deleted the backend but a
        # stale bulk-config save resurrected the slug in apis.value). The
        # next _refresh_apis_choices must drop the orphan so the UI stops
        # showing an unremovable chip.
        tts_agent.actions["_config"].config["apis"].value = ["kokoro", "deleted-be"]
        tts_agent._refresh_apis_choices()
        assert tts_agent.actions["_config"].config["apis"].value == ["kokoro"]

    def test_refresh_preserves_static_apis_in_value(self, tts_agent):
        # Static api slugs (kokoro, chatterbox, etc.) are always valid
        # choices — sanitization must not drop them.
        tts_agent.actions["_config"].config["apis"].value = [
            "kokoro",
            "chatterbox",
            "openai",
        ]
        tts_agent._refresh_apis_choices()
        assert tts_agent.actions["_config"].config["apis"].value == [
            "kokoro",
            "chatterbox",
            "openai",
        ]

    def test_refresh_preserves_currently_registered_dynamic_slug(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "live-be", "Live Backend")
        tts_agent.actions["_config"].config["apis"].value = ["kokoro", "live-be"]
        tts_agent._refresh_apis_choices()
        # Registered slug stays enabled.
        assert "live-be" in tts_agent.actions["_config"].config["apis"].value
        assert "kokoro" in tts_agent.actions["_config"].config["apis"].value

    @pytest.mark.asyncio
    async def test_apply_config_cleans_orphans_from_persisted_state(self, tts_agent):
        # Simulates loading a saved agent config that lists a dynamic-backend
        # slug in apis.value but has no matching entry in the registry blob
        # (the backend was deleted in a previous session). After apply_config
        # the orphan should be gone.
        await tts_agent.apply_config(
            actions={
                "_config": {
                    "config": {
                        "apis": {"value": ["kokoro", "ghost-be"]},
                    },
                },
                "openai_compatible": {
                    "config": {
                        "dynamic_children": {"value": "[]"},
                    },
                },
            },
        )
        assert tts_agent.actions["_config"].config["apis"].value == ["kokoro"]


class TestTTSAgentApiAttrFallback:
    """``api_attr`` must dispatch to the underscored mixin helper for
    dynamic-backend slugs and to ``getattr(self, "<api>_<name>")`` for static
    apis. Both paths must take effect on the same call site."""

    def test_static_api_falls_through_to_getattr(self, tts_agent):
        # kokoro is a static API — kokoro_configured is a property on the
        # agent. api_attr must resolve to the same value.
        assert tts_agent.api_attr("kokoro", "configured") is True
        assert tts_agent.kokoro_configured is True

    def test_dynamic_api_resolves_through_registry(self, tts_agent):
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")
        # Set the per-backend api_url, then ask api_attr — it must dispatch
        # to _openai_compatible_configured("test-be") rather than to a
        # nonexistent "test-be_configured" attribute.
        tts_agent.actions["test-be"].config[
            "api_url"
        ].value = "http://localhost:9000/v1"
        assert tts_agent.api_attr("test-be", "configured") is True
        # And the underlying mixin helper agrees.
        assert tts_agent._openai_compatible_configured("test-be") is True

    def test_static_default_used_when_attr_missing(self, tts_agent):
        # No `kokoro_voices_endpoint` exists — api_attr returns the default.
        sentinel = object()
        assert (
            tts_agent.api_attr("kokoro", "voices_endpoint", default=sentinel)
            is sentinel
        )

    def test_unknown_static_api_returns_default(self, tts_agent):
        sentinel = object()
        # "ghost" is not a registered slug and not a static api — falls
        # through to getattr with the default.
        assert tts_agent.api_attr("ghost", "configured", default=sentinel) is sentinel


class TestAutoSetupClients:
    """``TTSAgent.setup_check`` polls every configured client for a
    ``tts_openai_compatible_setup`` capability method and lets each register
    its own backend. Verifies the dispatch contract; client-side probe logic
    lives in the koboldcpp tests below.
    """

    @pytest.mark.asyncio
    async def test_skips_when_automatic_setup_off(self, tts_agent, monkeypatch):
        tts_agent.actions["_config"].config["automatic_setup"].value = False
        called = {"count": 0}

        class StubClient:
            name = "stub"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                called["count"] += 1
                return True

        monkeypatch.setattr(instance, "CLIENTS", {"stub": StubClient()})
        result = await tts_agent.setup_check()
        assert result is False
        assert called["count"] == 0

    @pytest.mark.asyncio
    async def test_skips_disabled_clients(self, tts_agent, monkeypatch):
        called = {"count": 0}

        class StubClient:
            name = "stub"
            enabled = False

            async def tts_openai_compatible_setup(self_, agent):
                called["count"] += 1
                return True

        monkeypatch.setattr(instance, "CLIENTS", {"stub": StubClient()})
        await tts_agent.setup_check()
        assert called["count"] == 0

    @pytest.mark.asyncio
    async def test_calls_capability_method_on_every_capable_client(
        self, tts_agent, monkeypatch
    ):
        # Two clients, both capable; both should be invoked.
        invoked = []

        class CapableClient:
            def __init__(self, name):
                self.name = name
                self.enabled = True

            async def tts_openai_compatible_setup(self, agent):
                invoked.append(self.name)
                return False  # nothing changed

        class IncapableClient:
            name = "no-tts"
            enabled = True
            # No tts_openai_compatible_setup method

        monkeypatch.setattr(
            instance,
            "CLIENTS",
            {
                "kobold-1": CapableClient("kobold-1"),
                "no-tts": IncapableClient(),
                "kobold-2": CapableClient("kobold-2"),
            },
        )
        await tts_agent.setup_check()
        assert sorted(invoked) == ["kobold-1", "kobold-2"]

    @pytest.mark.asyncio
    async def test_persists_and_emits_when_any_client_changed_state(
        self, tts_agent, monkeypatch
    ):
        # When at least one client returns True, save_config + emit_status fire.
        save_called = {"count": 0}
        emit_called = {"count": 0}

        async def _save():
            save_called["count"] += 1

        async def _emit():
            emit_called["count"] += 1

        monkeypatch.setattr(tts_agent, "save_config", _save)
        monkeypatch.setattr(tts_agent, "emit_status", _emit)

        class ChangingClient:
            name = "kobold"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                return True

        class IdempotentClient:
            name = "kobold-2"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                return False

        monkeypatch.setattr(
            instance,
            "CLIENTS",
            {"kobold": ChangingClient(), "kobold-2": IdempotentClient()},
        )
        result = await tts_agent.setup_check()
        assert result is True
        assert save_called["count"] == 1
        assert emit_called["count"] == 1

    @pytest.mark.asyncio
    async def test_no_persist_when_nothing_changed(self, tts_agent, monkeypatch):
        save_called = {"count": 0}

        async def _save():
            save_called["count"] += 1

        monkeypatch.setattr(tts_agent, "save_config", _save)
        monkeypatch.setattr(tts_agent, "emit_status", AsyncMock(return_value=None))

        class IdempotentClient:
            name = "kobold"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                return False

        monkeypatch.setattr(instance, "CLIENTS", {"kobold": IdempotentClient()})
        await tts_agent.setup_check()
        assert save_called["count"] == 0

    @pytest.mark.asyncio
    async def test_one_client_raising_does_not_break_loop(self, tts_agent, monkeypatch):
        invoked = []

        class BoomClient:
            name = "boom"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                invoked.append("boom")
                raise RuntimeError("nope")

        class OkClient:
            name = "ok"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                invoked.append("ok")
                return False

        monkeypatch.setattr(
            instance,
            "CLIENTS",
            {"boom": BoomClient(), "ok": OkClient()},
        )
        # Doesn't raise; the OK client still got its turn.
        await tts_agent.setup_check()
        assert "ok" in invoked

    @pytest.mark.asyncio
    async def test_auto_enables_agent_when_new_backend_added(
        self, tts_agent, monkeypatch
    ):
        # Voice agent starts disabled; a client adds itself to apis.value
        # during setup_check → agent should flip on.
        tts_agent.is_enabled = False
        tts_agent.actions["_config"].config["apis"].value = []
        monkeypatch.setattr(tts_agent, "save_config", AsyncMock(return_value=None))
        monkeypatch.setattr(tts_agent, "emit_status", AsyncMock(return_value=None))

        class AddingClient:
            name = "kobold"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                value = list(agent.actions["_config"].config["apis"].value or [])
                value.append("kobold")
                agent.actions["_config"].config["apis"].value = value
                return True

        monkeypatch.setattr(instance, "CLIENTS", {"kobold": AddingClient()})

        await tts_agent.setup_check()

        assert tts_agent.is_enabled is True

    @pytest.mark.asyncio
    async def test_does_not_re_enable_agent_when_only_removals_happen(
        self, tts_agent, monkeypatch
    ):
        # Agent disabled; client drops a slug from apis.value but adds nothing.
        # The agent should stay disabled — auto-enable only fires on additions.
        tts_agent.is_enabled = False
        tts_agent.actions["_config"].config["apis"].value = ["going-away"]
        monkeypatch.setattr(tts_agent, "save_config", AsyncMock(return_value=None))
        monkeypatch.setattr(tts_agent, "emit_status", AsyncMock(return_value=None))

        class RemovingClient:
            name = "kobold"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                value = list(agent.actions["_config"].config["apis"].value or [])
                if "going-away" in value:
                    value.remove("going-away")
                agent.actions["_config"].config["apis"].value = value
                return True

        monkeypatch.setattr(instance, "CLIENTS", {"kobold": RemovingClient()})

        await tts_agent.setup_check()

        assert tts_agent.is_enabled is False
        # The removal itself must have happened — otherwise this test would
        # be silently asserting the wrong thing (agent stays disabled because
        # nothing changed, rather than because only-removals don't auto-enable).
        assert tts_agent.actions["_config"].config["apis"].value == []

    @pytest.mark.asyncio
    async def test_leaves_agent_alone_when_already_enabled(
        self, tts_agent, monkeypatch
    ):
        # Pre-enabled agent: an added api shouldn't *toggle* anything off.
        tts_agent.is_enabled = True
        tts_agent.actions["_config"].config["apis"].value = []
        monkeypatch.setattr(tts_agent, "save_config", AsyncMock(return_value=None))
        monkeypatch.setattr(tts_agent, "emit_status", AsyncMock(return_value=None))

        class AddingClient:
            name = "kobold"
            enabled = True

            async def tts_openai_compatible_setup(self_, agent):
                value = list(agent.actions["_config"].config["apis"].value or [])
                value.append("kobold")
                agent.actions["_config"].config["apis"].value = value
                return True

        monkeypatch.setattr(instance, "CLIENTS", {"kobold": AddingClient()})

        await tts_agent.setup_check()

        assert tts_agent.is_enabled is True


class TestKoboldCppTTSSetup:
    """Direct exercise of ``KoboldCppClient._tts_openai_compatible_setup_impl``.

    The bound method is invoked against a SimpleNamespace stand-in for the
    client (only needs ``connected``, ``url``, ``name``). httpx is mocked
    via monkeypatch so no network hits.
    """

    @pytest_asyncio.fixture
    async def fake_client(self):
        from talemate.client.koboldcpp import KoboldCppClient

        ns = types.SimpleNamespace(
            connected=True,
            url="http://localhost:5001",
            name="My Kobold",
        )
        # The impl method calls self._probe_kcpp_tts_loaded — bind the real
        # method onto the namespace so it can run unchanged.
        ns._probe_kcpp_tts_loaded = types.MethodType(
            KoboldCppClient._probe_kcpp_tts_loaded, ns
        )
        return ns

    @staticmethod
    def _patch_httpx(monkeypatch, status: int, payload):
        """Monkeypatch ``httpx.AsyncClient`` so any GET returns ``payload``.

        The stub answers every URL with the same response, which is fine
        for the capabilities probe in isolation. Tests that exercise the
        ``tts: true`` branch (which then triggers ``refresh_backend_voices``
        — itself an httpx caller) MUST also stub ``refresh_backend_voices``
        on the agent (e.g., via ``AsyncMock``) so the voice fetch doesn't
        accidentally consume the same payload.
        """
        from talemate.client import koboldcpp as kobold_module

        class _Resp:
            status_code = status

            def json(self_):
                if isinstance(payload, Exception):
                    raise payload
                return payload

        class _AsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, **kwargs):
                return _Resp()

        monkeypatch.setattr(kobold_module.httpx, "AsyncClient", _AsyncClient)

    @pytest.mark.asyncio
    async def test_skips_when_disconnected(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        from talemate.client.koboldcpp import KoboldCppClient

        fake_client.connected = False

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_no_register_when_kobold_reports_tts_false(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # Capabilities probe returns tts=False (definitive: no TTS loaded).
        # No backend exists for this URL → no register, no state change.
        self._patch_httpx(monkeypatch, 200, {"result": "KoboldCpp", "tts": False})

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is False
        assert tts_agent.dynamic_child_slugs("openai_compatible") == []

    @pytest.mark.asyncio
    async def test_no_change_on_404(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # /api/extra/version returns 404 (older kobold build without the
        # endpoint) → probe inconclusive → state untouched.
        self._patch_httpx(monkeypatch, 404, {})

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_no_change_when_capabilities_payload_missing_tts_field(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # Defensive: a response without the ``tts`` field is treated as
        # uncertain — never toggle state on it.
        self._patch_httpx(monkeypatch, 200, {"result": "KoboldCpp"})

        from talemate.client.koboldcpp import KoboldCppClient

        # Pre-existing enabled backend; should remain enabled.
        tts_agent.register_dynamic_child("openai_compatible", "kobold", "kobold")
        tts_agent.actions["kobold"].config["api_url"].value = "http://localhost:5001/v1"
        tts_agent.actions["_config"].config["apis"].value = ["kobold"]

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is False
        assert tts_agent.actions["_config"].config["apis"].value == ["kobold"]

    @pytest.mark.asyncio
    async def test_registers_backend_when_voices_present(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        self._patch_httpx(
            monkeypatch,
            200,
            {"result": "KoboldCpp", "tts": True},
        )

        from talemate.client.koboldcpp import KoboldCppClient

        # Stub out the voice refresh (it uses real httpx — different mock surface).
        monkeypatch.setattr(
            tts_agent,
            "refresh_backend_voices",
            AsyncMock(return_value=2),
        )

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is True

        # Slug derived from client name; backend created and pointed at the
        # /v1 base URL.
        slugs = tts_agent.dynamic_child_slugs("openai_compatible")
        assert "my-kobold" in slugs
        backend = tts_agent.actions["my-kobold"]
        assert backend.config["api_url"].value == "http://localhost:5001/v1"

        # Auto-enabled in apis flags so the narrator-voice dropdown sees it.
        assert "my-kobold" in (tts_agent.actions["_config"].config["apis"].value or [])

        # Voice refresh fired once.
        tts_agent.refresh_backend_voices.assert_awaited_once_with("my-kobold")

    @pytest.mark.asyncio
    async def test_idempotent_when_backend_already_tracking_and_enabled(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # Backend already points at this kobold and is in apis.value — no
        # change.
        tts_agent.register_dynamic_child("openai_compatible", "manual", "Manual")
        tts_agent.actions["manual"].config["api_url"].value = "http://localhost:5001/v1"
        tts_agent.actions["_config"].config["apis"].value = ["manual"]

        self._patch_httpx(
            monkeypatch,
            200,
            {"result": "KoboldCpp", "tts": True},
        )

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is False
        assert tts_agent.dynamic_child_slugs("openai_compatible") == ["manual"]
        assert tts_agent.actions["_config"].config["apis"].value == ["manual"]

    @pytest.mark.asyncio
    async def test_re_enables_existing_backend_when_voices_appear(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # Backend exists for this URL but is currently disabled (kobold was
        # restarted with TTS unloaded earlier). Now voices are back: should
        # auto-re-enable without creating a duplicate.
        tts_agent.register_dynamic_child("openai_compatible", "kobold", "kobold")
        tts_agent.actions["kobold"].config["api_url"].value = "http://localhost:5001/v1"
        # apis.value is empty → backend is currently disabled.
        tts_agent.actions["_config"].config["apis"].value = []

        self._patch_httpx(
            monkeypatch,
            200,
            {"result": "KoboldCpp", "tts": True},
        )

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is True
        assert tts_agent.actions["_config"].config["apis"].value == ["kobold"]
        # Single backend; no duplicate registered.
        assert tts_agent.dynamic_child_slugs("openai_compatible") == ["kobold"]

    @pytest.mark.asyncio
    async def test_auto_disables_backend_when_kobold_has_no_voices(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # Backend exists for this URL and is currently enabled. Kobold up
        # but reports empty voices list (TTS model unloaded after restart).
        # Should drop slug from apis.value but keep the backend's config.
        tts_agent.register_dynamic_child("openai_compatible", "kobold", "kobold")
        tts_agent.actions["kobold"].config["api_url"].value = "http://localhost:5001/v1"
        tts_agent.actions["kobold"].config["api_key"].value = "stay-please"
        tts_agent.actions["_config"].config["apis"].value = ["kobold"]

        self._patch_httpx(monkeypatch, 200, {"result": "KoboldCpp", "tts": False})

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is True
        assert tts_agent.actions["_config"].config["apis"].value == []
        # Backend kept (config preserved).
        assert "kobold" in tts_agent.dynamic_child_slugs("openai_compatible")
        assert tts_agent.actions["kobold"].config["api_key"].value == "stay-please"

    @pytest.mark.asyncio
    async def test_no_change_when_already_disabled_and_no_voices(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        tts_agent.register_dynamic_child("openai_compatible", "kobold", "kobold")
        tts_agent.actions["kobold"].config["api_url"].value = "http://localhost:5001/v1"
        tts_agent.actions["_config"].config["apis"].value = []

        self._patch_httpx(monkeypatch, 200, {"result": "KoboldCpp", "tts": False})

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_network_blip_does_not_toggle_state(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # Backend currently enabled. The probe raises (uncertain). State
        # must not change — otherwise transient network errors would flap
        # the user's setup.
        tts_agent.register_dynamic_child("openai_compatible", "kobold", "kobold")
        tts_agent.actions["kobold"].config["api_url"].value = "http://localhost:5001/v1"
        tts_agent.actions["_config"].config["apis"].value = ["kobold"]

        from talemate.client import koboldcpp as kobold_module

        class _BoomClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, **kwargs):
                raise RuntimeError("flaky network")

        monkeypatch.setattr(kobold_module.httpx, "AsyncClient", _BoomClient)

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is False
        # apis.value untouched.
        assert tts_agent.actions["_config"].config["apis"].value == ["kobold"]

    @pytest.mark.asyncio
    async def test_slug_collision_appends_numeric_suffix(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        # Collision against an unrelated slug forces a numeric suffix.
        tts_agent.register_dynamic_child(
            "openai_compatible", "my-kobold", "Different Kobold"
        )
        # That existing one points elsewhere, so idempotency check passes.
        tts_agent.actions["my-kobold"].config["api_url"].value = "http://other:5001/v1"

        self._patch_httpx(
            monkeypatch,
            200,
            {"result": "KoboldCpp", "tts": True},
        )
        monkeypatch.setattr(
            tts_agent,
            "refresh_backend_voices",
            AsyncMock(return_value=1),
        )

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        assert result is True
        # New backend slug is the suffixed one.
        slugs = tts_agent.dynamic_child_slugs("openai_compatible")
        assert "my-kobold" in slugs
        assert "my-kobold-2" in slugs

    @pytest.mark.asyncio
    async def test_voice_refresh_failure_does_not_undo_setup(
        self, tts_agent, fresh_voice_library, fake_client, monkeypatch
    ):
        self._patch_httpx(
            monkeypatch,
            200,
            {"result": "KoboldCpp", "tts": True},
        )

        async def _boom(*args, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(tts_agent, "refresh_backend_voices", _boom)

        from talemate.client.koboldcpp import KoboldCppClient

        result = await KoboldCppClient._tts_openai_compatible_setup_impl(
            fake_client, tts_agent
        )
        # Setup still succeeded — the voice fetch is best-effort.
        assert result is True
        assert "my-kobold" in tts_agent.dynamic_child_slugs("openai_compatible")


class TestRefreshBackendVoices:
    """``refresh_backend_voices`` should:
    - fetch via api_method("fetch_voices")
    - union new voices into the global library
    - preserve user-customized voices (tags / non-default labels)
    - drop auto-fetched voices the server no longer reports
    """

    @pytest.mark.asyncio
    async def test_returns_zero_for_unknown_slug(self, tts_agent, fresh_voice_library):
        # No registered backend with that slug.
        count = await tts_agent.refresh_backend_voices("nope")
        assert count == 0

    @pytest.mark.asyncio
    async def test_unions_fetched_voices_into_library(
        self, tts_agent, fresh_voice_library, monkeypatch
    ):
        save_calls: list[VoiceLibrary] = []

        async def _fake_save(library):
            save_calls.append(library)

        monkeypatch.setattr(voice_library, "save_voice_library", _fake_save)

        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")

        fetched = [
            Voice(label="alpha", provider="test-be", provider_id="alpha"),
            Voice(label="beta", provider="test-be", provider_id="beta"),
        ]

        async def _fake_fetch(*args, **kwargs):
            return fetched

        # Override api_method to return our fake fetcher (pre-bound, no slug
        # needed for the test fake).
        original_api_method = tts_agent.api_method

        def _api_method(api: str, name: str, default=None):
            if api == "test-be" and name == "fetch_voices":
                return _fake_fetch
            return original_api_method(api, name, default)

        monkeypatch.setattr(tts_agent, "api_method", _api_method)

        count = await tts_agent.refresh_backend_voices("test-be")
        assert count == 2
        assert "test-be:alpha" in fresh_voice_library.voices
        assert "test-be:beta" in fresh_voice_library.voices
        # save was invoked
        assert len(save_calls) == 1
        assert save_calls[0] is fresh_voice_library

    @pytest.mark.asyncio
    async def test_preserves_user_customized_voices(
        self, tts_agent, fresh_voice_library, monkeypatch
    ):
        async def _fake_save(library):
            pass

        monkeypatch.setattr(voice_library, "save_voice_library", _fake_save)

        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")

        # User has manually customized "alpha" with a non-default label and
        # tags. The backend still reports "alpha" — the customization must
        # survive (setdefault keeps the existing entry).
        custom = Voice(
            label="My Favorite",
            provider="test-be",
            provider_id="alpha",
            tags=["male", "warm"],
        )
        fresh_voice_library.voices[custom.id] = custom

        # And user has a voice "ghost" the server no longer reports — but
        # because it has tags, it's considered manually customized and must
        # survive the purge.
        kept_orphan = Voice(
            label="ghost",
            provider="test-be",
            provider_id="ghost",
            tags=["custom-tag"],
        )
        fresh_voice_library.voices[kept_orphan.id] = kept_orphan

        async def _fake_fetch(*args, **kwargs):
            # Server reports a fresh "alpha" with default label; the user's
            # customized entry should remain unchanged.
            return [Voice(label="alpha", provider="test-be", provider_id="alpha")]

        monkeypatch.setattr(
            tts_agent,
            "api_method",
            lambda api, name, default=None: _fake_fetch
            if (api == "test-be" and name == "fetch_voices")
            else getattr(tts_agent, f"{api}_{name}", default),
        )

        await tts_agent.refresh_backend_voices("test-be")

        # Customized "alpha" still has its user-supplied label + tags.
        kept = fresh_voice_library.voices["test-be:alpha"]
        assert kept.label == "My Favorite"
        assert kept.tags == ["male", "warm"]
        # Tagged orphan survived.
        assert "test-be:ghost" in fresh_voice_library.voices

    @pytest.mark.asyncio
    async def test_drops_auto_fetched_voices_no_longer_reported(
        self, tts_agent, fresh_voice_library, monkeypatch
    ):
        async def _fake_save(library):
            pass

        monkeypatch.setattr(voice_library, "save_voice_library", _fake_save)

        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")

        # An auto-fetched voice (no tags, label == provider_id) the server
        # no longer reports — must be dropped.
        stale = Voice(label="ghost", provider="test-be", provider_id="ghost")
        fresh_voice_library.voices[stale.id] = stale
        # And an unrelated kokoro voice — must be preserved regardless of
        # what the server reports.
        keep = Voice(label="K", provider="kokoro", provider_id="k1")
        fresh_voice_library.voices[keep.id] = keep

        async def _fake_fetch(*args, **kwargs):
            return [Voice(label="alpha", provider="test-be", provider_id="alpha")]

        monkeypatch.setattr(
            tts_agent,
            "api_method",
            lambda api, name, default=None: _fake_fetch
            if (api == "test-be" and name == "fetch_voices")
            else getattr(tts_agent, f"{api}_{name}", default),
        )

        await tts_agent.refresh_backend_voices("test-be")

        assert "test-be:ghost" not in fresh_voice_library.voices
        assert "test-be:alpha" in fresh_voice_library.voices
        assert "kokoro:k1" in fresh_voice_library.voices

    @pytest.mark.asyncio
    async def test_propagates_fetcher_exception(
        self, tts_agent, fresh_voice_library, monkeypatch
    ):
        # Hard failures (HTTP errors, JSON shape mismatches, etc.) must
        # propagate so the websocket plugin can surface the real error to
        # the UI rather than rendering "no listing endpoint" copy.
        tts_agent.register_dynamic_child("openai_compatible", "test-be", "Test Backend")

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated network failure")

        monkeypatch.setattr(
            tts_agent,
            "api_method",
            lambda api, name, default=None: _boom
            if (api == "test-be" and name == "fetch_voices")
            else getattr(tts_agent, f"{api}_{name}", default),
        )

        fresh_voice_library.voices.clear()
        with pytest.raises(RuntimeError, match="simulated network failure"):
            await tts_agent.refresh_backend_voices("test-be")
        # Library state untouched on the way out.
        assert fresh_voice_library.voices == {}


class TestParseVoicesPayload:
    """Direct exercise of the tolerant payload parser."""

    def test_list_of_strings(self):
        voices = _parse_voices_payload(["alpha", "beta"], "test-be")
        assert [(v.provider_id, v.label, v.provider) for v in voices] == [
            ("alpha", "alpha", "test-be"),
            ("beta", "beta", "test-be"),
        ]

    def test_list_of_id_dicts(self):
        voices = _parse_voices_payload([{"id": "alpha"}, {"id": "beta"}], "test-be")
        assert [v.provider_id for v in voices] == ["alpha", "beta"]
        # No display name → label falls back to id.
        assert all(v.label == v.provider_id for v in voices)

    def test_list_of_voice_id_with_display_name(self):
        voices = _parse_voices_payload(
            [{"voice_id": "alpha", "display_name": "Alpha Display"}],
            "test-be",
        )
        assert voices[0].provider_id == "alpha"
        assert voices[0].label == "Alpha Display"

    def test_voices_container(self):
        payload = {"voices": [{"id": "alpha"}, {"id": "beta"}]}
        voices = _parse_voices_payload(payload, "test-be")
        assert [v.provider_id for v in voices] == ["alpha", "beta"]

    def test_data_container(self):
        payload = {"data": [{"id": "alpha"}]}
        voices = _parse_voices_payload(payload, "test-be")
        assert [v.provider_id for v in voices] == ["alpha"]

    def test_results_container_also_supported(self):
        payload = {"results": [{"id": "alpha"}]}
        voices = _parse_voices_payload(payload, "test-be")
        assert [v.provider_id for v in voices] == ["alpha"]

    def test_none_payload_returns_empty(self):
        assert _parse_voices_payload(None, "test-be") == []

    def test_dict_without_recognized_keys_returns_empty(self):
        assert _parse_voices_payload({"unknown": [1, 2, 3]}, "test-be") == []

    def test_entries_missing_id_skipped(self):
        # An entry that has neither id, voice_id, name, nor voice should
        # be dropped silently.
        voices = _parse_voices_payload(
            [{"description": "no id field"}, {"id": "alpha"}],
            "test-be",
        )
        assert [v.provider_id for v in voices] == ["alpha"]

    def test_provider_set_to_backend_slug(self):
        voices = _parse_voices_payload(["alpha"], "my-server")
        assert voices[0].provider == "my-server"

    def test_non_dict_non_string_entries_skipped(self):
        # Numbers, lists, etc. don't match either branch — they're skipped.
        voices = _parse_voices_payload([42, ["nope"], "alpha"], "test-be")
        assert [v.provider_id for v in voices] == ["alpha"]


class TestResolveVoicesUrl:
    """``_resolve_voices_url`` joins probe paths to the user's API base URL.

    Three idioms must hold so the user's base URL (which by OpenAI-compat
    convention already includes ``/v1``) doesn't get the version doubled.
    """

    def test_relative_path_appends_under_versioned_base(self):
        url = _resolve_voices_url("https://api.openai.com/v1", "audio/speech/voices")
        assert url == "https://api.openai.com/v1/audio/speech/voices"

    def test_relative_path_works_with_trailing_slash_base(self):
        url = _resolve_voices_url("https://api.openai.com/v1/", "voices")
        assert url == "https://api.openai.com/v1/voices"

    def test_absolute_path_anchors_to_host_root(self):
        # Leading "/" on the candidate means: replace the base URL's path,
        # use the host root. This lets users opt into endpoints that don't
        # live underneath /v1.
        url = _resolve_voices_url("https://api.openai.com/v1", "/custom/voices")
        assert url == "https://api.openai.com/custom/voices"

    def test_full_url_passes_through(self):
        full = "https://elsewhere.example.com/v2/voices"
        assert _resolve_voices_url("https://api.openai.com/v1", full) == full

    def test_does_not_duplicate_v1_for_default_paths(self):
        # Regression: previously stripping leading "/" then urljoining produced
        # ".../v1/v1/audio/speech/voices" because the candidate was
        # "/v1/audio/...". The new defaults are relative to the base URL.
        for default in ("audio/voices", "audio/speech/voices", "voices"):
            url = _resolve_voices_url("https://api.openai.com/v1", default)
            assert url.count("/v1") == 1, url

    def test_koboldcpp_path_resolves_against_v1_base(self):
        # KoboldCPP exposes /v1/audio/voices on its OpenAI-compat endpoint.
        url = _resolve_voices_url("http://localhost:5001/v1", "audio/voices")
        assert url == "http://localhost:5001/v1/audio/voices"


# ---------------------------------------------------------------------------
# Pocket TTS
# ---------------------------------------------------------------------------


def _pocket_tts_stub_instance(agent, has_voice_cloning: bool = True):
    """Stand-in for PocketTTSInstance matching the agent's current settings."""
    return types.SimpleNamespace(
        model_language=agent.pocket_tts_language,
        temp=agent.pocket_tts_temp,
        lsd_decode_steps=agent.pocket_tts_lsd_decode_steps,
        noise_clamp=agent.pocket_tts_noise_clamp,
        eos_threshold=agent.pocket_tts_eos_threshold,
        quantize=agent.pocket_tts_quantize,
        model=types.SimpleNamespace(has_voice_cloning=has_voice_cloning, device="cpu"),
        voice_states={},
    )


class TestPocketTTSReloadDecision:
    """Reload decision for the cached Pocket TTS model (issue #133).

    pocket_tts silently falls back to the public non-voice-cloning weights when
    the gated download fails; once a HF token is configured, the cached
    fallback model must be discarded so the gated download is retried.
    """

    def test_no_instance_reloads(self, tts_agent):
        assert tts_agent._pocket_tts_should_reload(None)

    def test_unchanged_params_do_not_reload(self, tts_agent):
        inst = _pocket_tts_stub_instance(tts_agent)
        assert not tts_agent._pocket_tts_should_reload(inst)

    def test_param_change_reloads(self, tts_agent):
        inst = _pocket_tts_stub_instance(tts_agent)
        tts_agent.actions["pocket_tts"].config["temp"].value = 1.2
        assert tts_agent._pocket_tts_should_reload(inst)

    def test_fallback_model_without_token_does_not_reload(self, tts_agent, monkeypatch):
        monkeypatch.setattr(pocket_tts_module, "get_token", lambda: None)
        inst = _pocket_tts_stub_instance(tts_agent, has_voice_cloning=False)
        assert not tts_agent._pocket_tts_should_reload(inst)

    def test_fallback_model_with_token_reloads(self, tts_agent, monkeypatch):
        inst = _pocket_tts_stub_instance(tts_agent, has_voice_cloning=False)
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_test_token")
        assert tts_agent._pocket_tts_should_reload(inst)

    def test_fallback_model_with_env_token_reloads(self, tts_agent, monkeypatch):
        inst = _pocket_tts_stub_instance(tts_agent, has_voice_cloning=False)
        monkeypatch.setenv("HF_TOKEN", "hf_env_token")
        assert tts_agent._pocket_tts_should_reload(inst)

    def test_fallback_model_with_token_file_reloads(self, tts_agent, monkeypatch):
        # hf auth login writes a token file; get_token() resolves it the same
        # way the download itself will
        monkeypatch.setattr(pocket_tts_module, "get_token", lambda: "hf_file_token")
        inst = _pocket_tts_stub_instance(tts_agent, has_voice_cloning=False)
        assert tts_agent._pocket_tts_should_reload(inst)

    def test_intact_model_with_token_does_not_reload(self, tts_agent, monkeypatch):
        inst = _pocket_tts_stub_instance(tts_agent)
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_test_token")
        assert not tts_agent._pocket_tts_should_reload(inst)


class TestPocketTTSApplyHfToken:
    def test_cleared_config_token_removes_exported_env_var(
        self, tts_agent, monkeypatch
    ):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_cfg_token")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token"

        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert "HF_TOKEN" not in os.environ

    def test_user_set_env_var_is_left_alone(self, tts_agent, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_user_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_user_token"

    def test_displaced_user_env_var_is_restored_on_clear(self, tts_agent, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_user_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_cfg_token")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token"

        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_user_token"

    def test_displaced_value_survives_config_token_change(self, tts_agent, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_user_token")
        for cfg_token in ("hf_cfg_token_a", "hf_cfg_token_b"):
            monkeypatch.setattr(get_config().huggingface, "api_key", cfg_token)
            tts_agent._pocket_tts_apply_hf_token()
            assert os.environ["HF_TOKEN"] == cfg_token

        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_user_token"

    def test_displaced_value_survives_repeated_apply_of_same_token(
        self, tts_agent, monkeypatch
    ):
        # apply runs on every generation, so the steady state between a set
        # and a clear is N applies of the same unchanged token - none of them
        # may clobber the displaced value with Talemate's own export
        monkeypatch.setenv("HF_TOKEN", "hf_user_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_cfg_token")
        for _ in range(3):
            tts_agent._pocket_tts_apply_hf_token()
            assert os.environ["HF_TOKEN"] == "hf_cfg_token"

        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_user_token"

    def test_user_env_value_identical_to_config_token_round_trips(
        self, tts_agent, monkeypatch
    ):
        monkeypatch.setenv("HF_TOKEN", "hf_same_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_same_token")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_same_token"

        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_same_token"

    def test_external_change_while_token_set_becomes_restore_target(
        self, tts_agent, monkeypatch
    ):
        monkeypatch.setenv("HF_TOKEN", "hf_user_1")
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_cfg_token")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token"

        # env changed out-of-band while the config token stays set: the next
        # apply adopts the newer external value as the restore target
        monkeypatch.setenv("HF_TOKEN", "hf_user_2")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token"

        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_user_2"

    def test_external_deletion_while_token_set_makes_clear_unset(
        self, tts_agent, monkeypatch
    ):
        monkeypatch.setenv("HF_TOKEN", "hf_user_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_cfg_token")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token"

        # user deletes the var while the config token stays set: the restore
        # target becomes "unset", not the pre-export value
        monkeypatch.delenv("HF_TOKEN")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token"

        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert "HF_TOKEN" not in os.environ

    def test_out_of_band_change_resets_bookkeeping(self, tts_agent, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_user_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_cfg_token")
        tts_agent._pocket_tts_apply_hf_token()

        # env changed out-of-band: clearing must not overwrite it
        monkeypatch.setenv("HF_TOKEN", "hf_external_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_external_token"

        # and the dropped bookkeeping must not mistake a later user value
        # equal to the old export for Talemate's own
        monkeypatch.setenv("HF_TOKEN", "hf_cfg_token")
        monkeypatch.setattr(get_config().huggingface, "api_key", "hf_cfg_token_2")
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token_2"
        monkeypatch.setattr(get_config().huggingface, "api_key", None)
        tts_agent._pocket_tts_apply_hf_token()
        assert os.environ["HF_TOKEN"] == "hf_cfg_token"


class TestPocketTTSAgentDetails:
    def test_no_warning_when_voice_cloning_available(self, tts_agent):
        tts_agent.pocket_tts_instance = _pocket_tts_stub_instance(tts_agent)
        assert "pocket_tts_voice_cloning" not in tts_agent.pocket_tts_agent_details

    def test_warning_when_voice_cloning_unavailable(self, tts_agent):
        tts_agent.pocket_tts_instance = _pocket_tts_stub_instance(
            tts_agent, has_voice_cloning=False
        )
        warning = tts_agent.pocket_tts_agent_details["pocket_tts_voice_cloning"]
        assert warning["color"] == "warning"
        assert warning["value"] == "Voice cloning unavailable"

    def test_warning_surfaces_when_api_enabled_but_unused(self, tts_agent):
        # No narrator/character voice uses pocket_tts, but the api is enabled:
        # details flagged surface_when_unused must still reach the agent card,
        # while informational chips (model, voice cache) stay hidden.
        tts_agent.is_enabled = True
        tts_agent.actions["_config"].config["apis"].value = ["pocket_tts"]
        tts_agent.pocket_tts_instance = _pocket_tts_stub_instance(
            tts_agent, has_voice_cloning=False
        )
        details = tts_agent.agent_details
        assert "pocket_tts_voice_cloning" in details
        assert "pocket_tts_model" not in details
        assert "pocket_tts_voice_cache" not in details

    def test_error_details_of_unused_apis_stay_hidden(self, tts_agent):
        # openai is enabled but unconfigured (no api key) and no voice uses it:
        # its error detail must not reach the agent card - the api status in
        # the voice UI already surfaces it.
        tts_agent.is_enabled = True
        tts_agent.actions["_config"].config["apis"].value = ["openai"]
        assert tts_agent.openai_agent_details["openai_api_key"]["color"] == "error"
        assert "openai_api_key" not in tts_agent.agent_details
