import copy
import os
import sys
import types

import pytest
import yaml
from unittest.mock import patch

from cryptography.fernet import Fernet

from talemate.util.encryption import (
    ENC_PREFIX,
    _key_file_path,
    _keyring_available,
    decrypt_sensitive_values,
    decrypt_value,
    encrypt_sensitive_values,
    encrypt_value,
    get_fernet,
    reset_fernet,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_fernet(tmp_path):
    """Use a temporary key file for each test, with keyring disabled."""
    key_file = tmp_path / "encryption.key"
    with (
        patch("talemate.util.encryption._key_file_path", return_value=key_file),
        patch("talemate.util.encryption._keyring_available", return_value=False),
    ):
        reset_fernet()
        yield key_file
        reset_fernet()


@pytest.fixture()
def mock_keyring_module():
    """A module-like mock keyring backed by a dict."""
    store = {}
    mod = types.ModuleType("keyring")

    def get_password(service, username):
        return store.get((service, username))

    def set_password(service, username, password):
        store[(service, username)] = password

    def delete_password(service, username):
        if (service, username) not in store:
            raise Exception("not found")
        del store[(service, username)]

    mod.get_password = get_password
    mod.set_password = set_password
    mod.delete_password = delete_password
    mod.store = store  # for test assertions

    return mod


@pytest.fixture()
def fresh_fernet_with_keyring(tmp_path, mock_keyring_module):
    """Use a temporary key file AND mock keyring for each test."""
    key_file = tmp_path / "encryption.key"
    with (
        patch("talemate.util.encryption._key_file_path", return_value=key_file),
        patch("talemate.util.encryption._keyring_available", return_value=True),
        patch("talemate.util.encryption.keyring", mock_keyring_module),
    ):
        reset_fernet()
        yield key_file, mock_keyring_module
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
        with patch.dict(os.environ, {"TALEMATE_ENCRYPTION_KEY_DIR": "/custom/secrets"}):
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


# ---------------------------------------------------------------------------
# Keyring storage
# ---------------------------------------------------------------------------


class TestKeyringStorage:
    def test_new_key_stored_in_keyring(self, fresh_fernet_with_keyring):
        """When no key exists, a new key is generated and stored in keyring."""
        key_file, mock_kr = fresh_fernet_with_keyring
        get_fernet()

        assert ("talemate", "encryption_key") in mock_kr.store
        assert not key_file.exists()

    def test_encrypt_decrypt_with_keyring(self, fresh_fernet_with_keyring):
        """Full round-trip works when key is in keyring only."""
        key_file, mock_kr = fresh_fernet_with_keyring
        encrypted = encrypt_value("sk-secret-123")
        assert encrypted.startswith(ENC_PREFIX)
        assert decrypt_value(encrypted) == "sk-secret-123"
        assert not key_file.exists()

    def test_keyring_read_on_subsequent_load(self, fresh_fernet_with_keyring):
        """After storing in keyring, resetting and re-loading reads from keyring."""
        key_file, mock_kr = fresh_fernet_with_keyring
        encrypted = encrypt_value("sk-abc")
        reset_fernet()

        assert decrypt_value(encrypted) == "sk-abc"
        assert not key_file.exists()


# ---------------------------------------------------------------------------
# File-to-keyring migration
# ---------------------------------------------------------------------------


class TestFileMigrationToKeyring:
    def test_existing_file_migrated_to_keyring(self, fresh_fernet_with_keyring):
        """When a key file exists and keyring is available, key migrates."""
        key_file, mock_kr = fresh_fernet_with_keyring

        # Pre-create a key file (simulating pre-keyring installation)
        key = Fernet.generate_key()
        key_file.write_bytes(key)

        get_fernet()

        assert ("talemate", "encryption_key") in mock_kr.store
        assert mock_kr.store[("talemate", "encryption_key")] == key.decode("utf-8")
        assert not key_file.exists()

    def test_migration_preserves_encrypted_data(self, fresh_fernet_with_keyring):
        """Data encrypted with the file-based key can still be decrypted after migration."""
        key_file, mock_kr = fresh_fernet_with_keyring

        # Create a key file and encrypt some data using it
        key = Fernet.generate_key()
        key_file.write_bytes(key)

        # First load: triggers migration
        encrypted = encrypt_value("sk-migrate-me")
        reset_fernet()

        # Second load: key now comes from keyring
        assert not key_file.exists()
        assert decrypt_value(encrypted) == "sk-migrate-me"


# ---------------------------------------------------------------------------
# Keyring fallback to file
# ---------------------------------------------------------------------------


class TestKeyringFallback:
    def test_keyring_store_fails_falls_back_to_file(self, tmp_path):
        """When keyring.set_password raises, key is written to file."""
        key_file = tmp_path / "encryption.key"
        failing_mod = types.ModuleType("keyring")
        failing_mod.get_password = lambda s, u: None
        failing_mod.set_password = lambda s, u, p: (_ for _ in ()).throw(
            Exception("no keyring")
        )
        failing_mod.delete_password = lambda s, u: None

        with (
            patch("talemate.util.encryption._key_file_path", return_value=key_file),
            patch("talemate.util.encryption._keyring_available", return_value=True),
            patch("talemate.util.encryption.keyring", failing_mod),
        ):
            reset_fernet()
            f = get_fernet()
            assert f is not None
            assert key_file.exists()

    def test_keyring_unavailable_uses_file(self, fresh_fernet):
        """When keyring is unavailable, behaves exactly like the old code."""
        get_fernet()
        assert fresh_fernet.exists()


# ---------------------------------------------------------------------------
# Keyring edge cases
# ---------------------------------------------------------------------------


class TestKeyringEdgeCases:
    def test_keyring_disappears_after_store(self, tmp_path, mock_keyring_module):
        """
        If keyring was used to store the key but is later unavailable,
        the user gets a new key (data loss on encrypted values, but no crash).
        """
        key_file = tmp_path / "encryption.key"

        # First run: keyring works, key stored there
        with (
            patch("talemate.util.encryption._key_file_path", return_value=key_file),
            patch("talemate.util.encryption._keyring_available", return_value=True),
            patch("talemate.util.encryption.keyring", mock_keyring_module),
        ):
            reset_fernet()
            encrypted = encrypt_value("sk-important")
            reset_fernet()

        # Second run: keyring unavailable, no file exists
        with (
            patch("talemate.util.encryption._key_file_path", return_value=key_file),
            patch("talemate.util.encryption._keyring_available", return_value=False),
        ):
            reset_fernet()
            result = decrypt_value(encrypted)
            assert result is None

    def test_corrupted_keyring_value(self, tmp_path, mock_keyring_module):
        """If keyring returns a corrupted key, regeneration occurs gracefully."""
        key_file = tmp_path / "encryption.key"
        mock_keyring_module.store[("talemate", "encryption_key")] = (
            "not-a-valid-fernet-key"
        )

        with (
            patch("talemate.util.encryption._key_file_path", return_value=key_file),
            patch("talemate.util.encryption._keyring_available", return_value=True),
            patch("talemate.util.encryption.keyring", mock_keyring_module),
        ):
            reset_fernet()
            f = get_fernet()
            assert f is not None

            # A new valid key should now be in the keyring
            new_key = mock_keyring_module.store[("talemate", "encryption_key")]
            assert new_key != "not-a-valid-fernet-key"


# ---------------------------------------------------------------------------
# TALEMATE_DISABLE_KEYRING env var
# ---------------------------------------------------------------------------


class TestDisableKeyringEnvVar:
    def test_env_var_disables_keyring(self):
        """TALEMATE_DISABLE_KEYRING=1 forces file-based storage."""
        with patch.dict(os.environ, {"TALEMATE_DISABLE_KEYRING": "1"}):
            assert _keyring_available() is False
