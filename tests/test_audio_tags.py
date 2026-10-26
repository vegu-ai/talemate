"""Tests for audio tags feature."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.testing import capture_logs

from talemate.agents.tts.audio_tags import only_tags_inserted
from talemate.agents.tts.schema import Chunk, Voice


class TestAudioTagsSurviveCleanedText:
    """Verify that audio tags in bracket format survive Chunk.cleaned_text."""

    def test_brackets_not_stripped(self):
        chunk = Chunk(
            text=["[laughing] I can't believe it! [excited] This is amazing!"],
            type="dialogue",
        )
        cleaned = chunk.cleaned_text
        assert "[laughing]" in cleaned
        assert "[excited]" in cleaned
        assert "I can't believe it!" in cleaned.replace("[laughing] ", "")

    def test_mixed_tags_and_text(self):
        chunk = Chunk(
            text=["Hello [whispering] don't tell anyone [nervous laugh] okay?"],
            type="dialogue",
        )
        cleaned = chunk.cleaned_text
        assert "[whispering]" in cleaned
        assert "[nervous laugh]" in cleaned


class TestElevenLabsSupportsAudioTags:
    """Tests for ElevenLabsMixin.elevenlabs_supports_audio_tags."""

    def _make_mixin(self, default_model: str):
        """Create a mock mixin with a given default model."""
        from talemate.agents.tts.elevenlabs import ElevenLabsMixin

        mixin = object.__new__(ElevenLabsMixin)
        mixin.actions = {
            "elevenlabs": MagicMock(
                config={
                    "model": MagicMock(value=default_model),
                    "audio_tag_format": MagicMock(value="[{{ tag }}]"),
                }
            )
        }
        return mixin

    def test_v3_model_supported(self):
        mixin = self._make_mixin("eleven_v3")
        assert mixin.elevenlabs_supports_audio_tags() is True

    def test_flash_v2_5_not_supported(self):
        mixin = self._make_mixin("eleven_flash_v2_5")
        assert mixin.elevenlabs_supports_audio_tags() is False

    def test_multilingual_v2_not_supported(self):
        mixin = self._make_mixin("eleven_multilingual_v2")
        assert mixin.elevenlabs_supports_audio_tags() is False

    def test_turbo_v2_5_not_supported(self):
        mixin = self._make_mixin("eleven_turbo_v2_5")
        assert mixin.elevenlabs_supports_audio_tags() is False

    def test_voice_override_to_v3(self):
        """When default model is not v3 but voice overrides to v3."""
        mixin = self._make_mixin("eleven_flash_v2_5")
        assert mixin.elevenlabs_supports_audio_tags(model="eleven_v3") is True

    def test_voice_override_away_from_v3(self):
        """When default model is v3 but voice overrides to something else."""
        mixin = self._make_mixin("eleven_v3")
        assert mixin.elevenlabs_supports_audio_tags(model="eleven_flash_v2_5") is False

    def test_none_model_uses_default(self):
        """When model=None, should use the default model."""
        mixin = self._make_mixin("eleven_v3")
        assert mixin.elevenlabs_supports_audio_tags(model=None) is True


class TestAudioTagFormatDefault:
    """Test the default audio tag format value."""

    def test_elevenlabs_default_format(self):
        from talemate.agents.tts.elevenlabs import ElevenLabsMixin

        mixin = object.__new__(ElevenLabsMixin)
        mixin.actions = {
            "elevenlabs": MagicMock(
                config={
                    "audio_tag_format": MagicMock(value="[{{ tag }}]"),
                }
            )
        }
        assert mixin.elevenlabs_audio_tag_format == "[{{ tag }}]"


class TestChunkSupportsAudioTags:
    """Tests for TTSAgent.chunk_supports_audio_tags."""

    def _make_agent(self):
        from talemate.agents.tts import TTSAgent

        agent = object.__new__(TTSAgent)
        # Mock the elevenlabs_supports_audio_tags method
        agent.actions = {
            "elevenlabs": MagicMock(
                config={
                    "model": MagicMock(value="eleven_v3"),
                    "audio_tag_format": MagicMock(value="[{{ tag }}]"),
                }
            )
        }
        return agent

    def test_eligible_chunk(self):
        agent = self._make_agent()
        chunk = Chunk(
            text=["Hello"],
            type="dialogue",
            api="elevenlabs",
            voice=Voice(
                label="Test",
                provider="elevenlabs",
                provider_id="test",
                provider_model="eleven_v3",
            ),
            model="eleven_v3",
        )
        assert agent.chunk_supports_audio_tags(chunk) is True

    def test_non_eligible_provider(self):
        agent = self._make_agent()
        chunk = Chunk(
            text=["Hello"],
            type="dialogue",
            api="kokoro",
        )
        assert agent.chunk_supports_audio_tags(chunk) is False

    def test_no_api(self):
        agent = self._make_agent()
        chunk = Chunk(
            text=["Hello"],
            type="dialogue",
            api=None,
        )
        assert agent.chunk_supports_audio_tags(chunk) is False

    def test_elevenlabs_non_v3_model(self):
        agent = self._make_agent()
        chunk = Chunk(
            text=["Hello"],
            type="dialogue",
            api="elevenlabs",
            model="eleven_flash_v2_5",
        )
        assert agent.chunk_supports_audio_tags(chunk) is False


@pytest.mark.parametrize(
    "original, tagged, tag_format, expected",
    [
        ("I can't believe it.", "[amused] I can't believe it.", "[{{ tag }}]", True),
        (
            'She ran. "We move now!"',
            'She ran. "[urgent] We move now!"',
            "[{{ tag }}]",
            True,
        ),
        (
            "Hello [authored] there.",
            "Hello [authored] [laugh] there.",
            "[{{ tag }}]",
            True,
        ),
        ("Hello there.", "<sigh> Hello there.", "<{{ tag }}>", True),
        ("Hello there.", "[sigh] Hello there.", "<{{ tag }}>", False),
        (
            "I can't believe it.",
            "Emma: [amused] I can't believe it.",
            "[{{ tag }}]",
            False,
        ),
        (
            "I can't believe it.",
            "(Emma) [amused] I can't believe it.",
            "[{{ tag }}]",
            False,
        ),
        ("I can't believe it.", "[amused] I cannot believe it.", "[{{ tag }}]", False),
        ("I can't believe it.", "[amused] I can't believe it", "[{{ tag }}]", False),
        ("Hello there.", "[Emma: [happy] Hello there.", "[{{ tag }}]", False),
        ("Hello [laugh] there.", "Hello there.", "[{{ tag }}]", False),
        ("Hello [laugh] there.", "Hello [sob] there.", "[{{ tag }}]", False),
        ("Hello there.", "Emma: Goodbye.", "{{ tag }}", False),
        ("Hello [] there.", "Hello [] [happy] there.", "[{{ tag }}]", True),
    ],
)
def test_only_tags_inserted(original, tagged, tag_format, expected):
    assert only_tags_inserted(original, tagged, tag_format) is expected


class TestInjectAudioTagsContract:
    """A tagged chunk is applied only when the model inserted tags and changed nothing else."""

    @pytest.fixture
    def agent(self, monkeypatch):
        from talemate.agents.tts import TTSAgent, voice_library
        from talemate.agents.tts.schema import VoiceLibrary

        monkeypatch.setattr(voice_library, "VOICE_LIBRARY", VoiceLibrary())
        agent = TTSAgent()
        agent.actions["_config"].config["audio_tags"].value = True
        agent.get_audio_tags_cache = AsyncMock(return_value=None)
        agent.set_audio_tags_cache = AsyncMock()
        return agent

    async def inject(self, agent, response: str) -> Chunk:
        chunk = Chunk(
            text=["I can't believe you did that."],
            type="dialogue",
            api="elevenlabs",
            model="eleven_v3",
            character_name="Emma",
        )
        summarizer = SimpleNamespace(
            inject_audio_tags_for_tts=AsyncMock(return_value={0: response})
        )
        await agent._inject_audio_tags([chunk], summarizer)
        return chunk

    @pytest.mark.parametrize(
        "response",
        [
            "Emma: [shocked] I can't believe you did that.",
            "(Emma) [shocked] I can't believe you did that.",
            "[shocked] I cannot believe you did that!",
        ],
        ids=["echoed-label", "echoed-marker", "rewrite"],
    )
    async def test_changed_text_keeps_original(self, agent, response):
        with capture_logs() as logs:
            chunk = await self.inject(agent, response)
        assert chunk.text == ["I can't believe you did that."]
        assert any(
            entry["event"].startswith("Audio tag response changed the chunk text")
            for entry in logs
        )

    async def test_tags_only_is_applied(self, agent):
        chunk = await self.inject(
            agent, "[shocked] I can't believe you [laughing] did that."
        )
        assert chunk.text == ["[shocked] I can't believe you [laughing] did that."]
