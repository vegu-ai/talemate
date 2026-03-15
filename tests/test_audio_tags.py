"""Tests for audio tags feature."""

from unittest.mock import MagicMock

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
