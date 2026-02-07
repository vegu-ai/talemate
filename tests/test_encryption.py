import copy
import os
import sys

import pytest
import yaml
from unittest.mock import patch

from cryptography.fernet import Fernet

from talemate.util.encryption import (
    ENC_PREFIX,
    decrypt_sensitive_values,
    decrypt_value,
    encrypt_sensitive_values,
    encrypt_value,
    get_fernet,
    reset_fernet,
    _key_file_path,
)


@pytest.fixture()
def fresh_fernet(tmp_path):
    """Use a temporary key file for each test."""
    key_file = tmp_path / "encryption.key"
    with patch("talemate.util.encryption._key_file_path", return_value=key_file):
        reset_fernet()
        yield key_file
        reset_fernet()


# ---------------------------------------------------------------------------
# Round-trip encrypt/decrypt
# ---------------------------------------------------------------------------


class TestEncryptDecryptRoundTrip:
    def test_basic(self, fresh_fernet):
        original = "sk-ant-api03-abc123"
        encrypted = encrypt_value(original)
        assert encrypted.startswith(ENC_PREFIX)
        assert decrypt_value(encrypted) == original

    def test_unicode(self, fresh_fernet):
        original = "key-with-unicode-\u00e9\u00e8"
        encrypted = encrypt_value(original)
        assert decrypt_value(encrypted) == original

    def test_long_key(self, fresh_fernet):
        original = "sk-" + "a" * 500
        encrypted = encrypt_value(original)
        assert decrypt_value(encrypted) == original


# ---------------------------------------------------------------------------
# Passthrough / edge cases
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_empty_string_encrypt(self, fresh_fernet):
        assert encrypt_value("") == ""

    def test_empty_string_decrypt(self, fresh_fernet):
        assert decrypt_value("") == ""

    def test_none_decrypt(self, fresh_fernet):
        assert decrypt_value(None) is None

    def test_plaintext_passthrough_on_decrypt(self, fresh_fernet):
        """Legacy plaintext values (no ENC: prefix) return unchanged."""
        assert decrypt_value("sk-plain-key-123") == "sk-plain-key-123"

    def test_already_encrypted_not_double_encrypted(self, fresh_fernet):
        original = "sk-abc"
        encrypted = encrypt_value(original)
        double = encrypt_value(encrypted)
        assert double == encrypted


# ---------------------------------------------------------------------------
# Lost / corrupted key handling
# ---------------------------------------------------------------------------


class TestInvalidTokenHandling:
    def test_lost_key_returns_none(self, fresh_fernet):
        """When the key file is replaced, decrypt returns None and regenerates."""
        encrypted = encrypt_value("sk-secret")

        # Simulate key loss by writing a new key
        fresh_fernet.write_bytes(Fernet.generate_key())
        reset_fernet()

        result = decrypt_value(encrypted)
        assert result is None

    def test_corrupted_key_file_handled(self, fresh_fernet):
        """A corrupted key file triggers regeneration on get_fernet()."""
        fresh_fernet.write_bytes(b"not-a-valid-fernet-key")
        reset_fernet()

        # Should not raise — regenerates the key
        f = get_fernet()
        assert f is not None

        # And encryption works with the new key
        encrypted = encrypt_value("sk-test")
        assert encrypted.startswith(ENC_PREFIX)
        assert decrypt_value(encrypted) == "sk-test"


# ---------------------------------------------------------------------------
# Dict-walking logic
# ---------------------------------------------------------------------------


class TestDictWalking:
    def test_top_level_api_key(self, fresh_fernet):
        data = {"openai": {"api_key": "sk-123"}}
        encrypt_sensitive_values(data)
        assert data["openai"]["api_key"].startswith(ENC_PREFIX)

        decrypt_sensitive_values(data)
        assert data["openai"]["api_key"] == "sk-123"

    def test_client_api_key(self, fresh_fernet):
        data = {
            "clients": {
                "MyClient": {
                    "api_key": "sk-client-key",
                    "name": "MyClient",
                    "type": "openai",
                }
            }
        }
        encrypt_sensitive_values(data)
        assert data["clients"]["MyClient"]["api_key"].startswith(ENC_PREFIX)
        assert data["clients"]["MyClient"]["name"] == "MyClient"

    def test_override_api_key(self, fresh_fernet):
        data = {
            "clients": {
                "Proxy": {
                    "override_api_key": "sk-proxy-key",
                    "override_base_url": "https://proxy.example.com",
                }
            }
        }
        encrypt_sensitive_values(data)
        assert data["clients"]["Proxy"]["override_api_key"].startswith(ENC_PREFIX)
        assert (
            data["clients"]["Proxy"]["override_base_url"] == "https://proxy.example.com"
        )

    def test_agent_action_config_api_key_not_touched(self, fresh_fernet):
        """AgentActionConfig api_key values are dicts, not strings — must be skipped."""
        data = {
            "agents": {
                "tts": {
                    "actions": {
                        "elevenlabs": {
                            "config": {"api_key": {"value": "elevenlabs.api_key"}}
                        }
                    }
                }
            }
        }
        original = copy.deepcopy(data)
        encrypt_sensitive_values(data)
        assert data == original

    def test_none_api_key_not_touched(self, fresh_fernet):
        data = {"openai": {"api_key": None}}
        encrypt_sensitive_values(data)
        assert data["openai"]["api_key"] is None

    def test_empty_string_api_key_passthrough(self, fresh_fernet):
        data = {"clients": {"c1": {"api_key": ""}}}
        encrypt_sensitive_values(data)
        assert data["clients"]["c1"]["api_key"] == ""

    def test_full_round_trip(self, fresh_fernet):
        original = {
            "openai": {"api_key": "sk-openai-123"},
            "anthropic": {"api_key": "sk-ant-456"},
            "clients": {
                "c1": {
                    "api_key": "sk-c1",
                    "override_api_key": "sk-override",
                    "name": "c1",
                },
                "c2": {
                    "api_key": None,
                    "name": "c2",
                },
            },
            "agents": {
                "tts": {
                    "actions": {
                        "elevenlabs": {
                            "config": {"api_key": {"value": "elevenlabs.api_key"}}
                        }
                    }
                }
            },
        }
        data = copy.deepcopy(original)

        encrypt_sensitive_values(data)
        # Verify encryption happened
        assert data["openai"]["api_key"].startswith(ENC_PREFIX)
        assert data["anthropic"]["api_key"].startswith(ENC_PREFIX)
        assert data["clients"]["c1"]["api_key"].startswith(ENC_PREFIX)
        assert data["clients"]["c1"]["override_api_key"].startswith(ENC_PREFIX)
        # None stays None
        assert data["clients"]["c2"]["api_key"] is None
        # Dict-type api_key untouched
        assert (
            data["agents"]["tts"]["actions"]["elevenlabs"]["config"]["api_key"]["value"]
            == "elevenlabs.api_key"
        )

        decrypt_sensitive_values(data)
        assert data["openai"]["api_key"] == "sk-openai-123"
        assert data["anthropic"]["api_key"] == "sk-ant-456"
        assert data["clients"]["c1"]["api_key"] == "sk-c1"
        assert data["clients"]["c1"]["override_api_key"] == "sk-override"
        assert data["clients"]["c2"]["api_key"] is None
        assert (
            data["agents"]["tts"]["actions"]["elevenlabs"]["config"]["api_key"]["value"]
            == "elevenlabs.api_key"
        )


# ---------------------------------------------------------------------------
# YAML round-trip (simulates save / load cycle)
# ---------------------------------------------------------------------------


class TestYamlRoundTrip:
    def test_encrypted_not_in_yaml(self, fresh_fernet):
        data = {"openai": {"api_key": "sk-test-123"}}
        encrypt_sensitive_values(data)
        yaml_str = yaml.dump(data)
        assert "sk-test-123" not in yaml_str
        assert ENC_PREFIX in yaml_str

    def test_load_from_encrypted_yaml(self, fresh_fernet):
        data = {"openai": {"api_key": "sk-test-123"}}
        encrypt_sensitive_values(data)
        yaml_str = yaml.dump(data)

        loaded = yaml.safe_load(yaml_str)
        decrypt_sensitive_values(loaded)
        assert loaded["openai"]["api_key"] == "sk-test-123"

    def test_load_from_plaintext_yaml(self, fresh_fernet):
        """Legacy plaintext config files work without any migration step."""
        yaml_str = "openai:\n  api_key: sk-legacy-key\n"
        loaded = yaml.safe_load(yaml_str)
        decrypt_sensitive_values(loaded)
        assert loaded["openai"]["api_key"] == "sk-legacy-key"


# ---------------------------------------------------------------------------
# Key file path
# ---------------------------------------------------------------------------


class TestKeyFilePath:
    def test_default_path(self):
        """Default path is TALEMATE_ROOT/secrets/encryption.key."""
        with patch.dict(os.environ, {}, clear=True):
            path = _key_file_path()
            assert path.name == "encryption.key"
            assert path.parent.name == "secrets"

    def test_env_var_override(self):
        """TALEMATE_ENCRYPTION_KEY_DIR overrides the default location."""
        with patch.dict(
            os.environ, {"TALEMATE_ENCRYPTION_KEY_DIR": "/custom/secrets"}
        ):
            path = _key_file_path()
            assert str(path) == "/custom/secrets/encryption.key"


# ---------------------------------------------------------------------------
# File permissions (Linux only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions only")
class TestFilePermissions:
    def test_key_file_permissions(self, fresh_fernet):
        get_fernet()  # triggers key generation
        stat = fresh_fernet.stat()
        assert oct(stat.st_mode & 0o777) == "0o600"
