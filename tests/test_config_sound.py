"""
Unit tests for `SoundConfig` — the persisted sound section of the app config.
"""

import pydantic
import pytest

from talemate.config.schema import Config, SoundConfig


class TestSoundConfigDefaults:
    def test_default_config_has_sound_defaults(self):
        config = Config()
        assert config.sound.volume == 1.0
        assert config.sound.muted is False

    def test_missing_sound_key_gets_defaults(self):
        # configs saved before the sound section existed come in without it
        config = Config(**{"agents": {}, "clients": {}})
        assert config.sound.volume == 1.0
        assert config.sound.muted is False

    def test_values_are_preserved(self):
        config = Config(**{"sound": {"volume": 0.25, "muted": True}})
        assert config.sound.volume == 0.25
        assert config.sound.muted is True


class TestSoundConfigVolumeRange:
    @pytest.mark.parametrize("volume", [-0.1, 1.1])
    def test_volume_outside_range_raises(self, volume):
        with pytest.raises(pydantic.ValidationError):
            SoundConfig(volume=volume)

    @pytest.mark.parametrize("volume", [0.0, 0.5, 1.0])
    def test_volume_within_range_accepted(self, volume):
        assert SoundConfig(volume=volume).volume == volume
