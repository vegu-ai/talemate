"""
Fernet encryption utilities for protecting API keys at rest in config.yaml.

The encryption key is stored in a platform-specific secure location,
separate from the application config file.
"""

import os
import sys
import structlog
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = structlog.get_logger("talemate.util.encryption")

# Prefix that marks encrypted values in YAML
ENC_PREFIX = "ENC:"

# Field names to encrypt/decrypt when walking config dicts
_SENSITIVE_FIELD_NAMES = frozenset({"api_key", "override_api_key"})

# Module-level cached Fernet instance
_fernet: Fernet | None = None


def _key_file_path() -> Path:
    """
    Return the path to the Fernet key file in a platform-specific
    secure directory.

    - Windows: %APPDATA%/talemate/encryption.key
    - Linux: $XDG_CONFIG_HOME/talemate/encryption.key
      (falls back to ~/.config/talemate/encryption.key)
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    return base / "talemate" / "encryption.key"


def _generate_key_file(path: Path) -> bytes:
    """Generate a new Fernet key and write it to the given path."""
    key = Fernet.generate_key()

    path.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform != "win32":
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
    else:
        path.write_bytes(key)

    log.info("generated new encryption key file", path=str(path))
    return key


def _load_or_create_key() -> bytes:
    """Load the Fernet key from disk, or generate a new one if missing."""
    path = _key_file_path()

    if path.exists():
        key = path.read_bytes().strip()
        log.debug("loaded encryption key", path=str(path))
        return key
    else:
        log.info("encryption key file not found, generating new key", path=str(path))
        return _generate_key_file(path)


def get_fernet() -> Fernet:
    """Return the module-level cached Fernet instance, creating it if needed."""
    global _fernet
    if _fernet is None:
        key = _load_or_create_key()
        try:
            _fernet = Fernet(key)
        except (ValueError, Exception) as e:
            log.warning(
                "encryption key file is corrupted, regenerating",
                error=str(e),
            )
            key = _generate_key_file(_key_file_path())
            _fernet = Fernet(key)
    return _fernet


def reset_fernet():
    """
    Clear the cached Fernet instance. Called after generating a fresh key
    due to InvalidToken errors.
    """
    global _fernet
    _fernet = None


def encrypt_value(plaintext: str) -> str:
    """
    Encrypt a plaintext string and return it with the ENC: prefix.

    Returns the original string if it is empty or already encrypted.
    """
    if not plaintext or plaintext.startswith(ENC_PREFIX):
        return plaintext

    f = get_fernet()
    token = f.encrypt(plaintext.encode("utf-8"))
    return ENC_PREFIX + token.decode("utf-8")


def decrypt_value(stored: str) -> str | None:
    """
    Decrypt a stored value. If it has the ENC: prefix, strip and decrypt.
    If not prefixed, return as-is (plaintext/legacy value).

    On InvalidToken (lost/corrupted key), logs a warning, regenerates the
    key file, and returns None to null out the value.
    """
    if not stored:
        return stored

    if not stored.startswith(ENC_PREFIX):
        return stored

    token = stored[len(ENC_PREFIX):]
    f = get_fernet()

    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        log.warning(
            "failed to decrypt api key value (key file may have been lost or replaced); "
            "the affected api key will need to be re-entered",
        )
        _generate_key_file(_key_file_path())
        reset_fernet()
        return None


def _walk_and_transform(node, transform_fn):
    """
    Recursively walk a nested dict/list structure. For any dict key in
    _SENSITIVE_FIELD_NAMES whose value is a str, apply transform_fn
    and replace the value in-place.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SENSITIVE_FIELD_NAMES and isinstance(value, str):
                node[key] = transform_fn(value)
            elif isinstance(value, (dict, list)):
                _walk_and_transform(value, transform_fn)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                _walk_and_transform(item, transform_fn)


def decrypt_sensitive_values(data: dict) -> dict:
    """
    Recursively walk a config dict and decrypt any values for keys named
    'api_key' or 'override_api_key' that are strings.

    Modifies and returns the dict in-place.
    """
    _walk_and_transform(data, decrypt_value)
    return data


def encrypt_sensitive_values(data: dict) -> dict:
    """
    Recursively walk a config dict and encrypt any values for keys named
    'api_key' or 'override_api_key' that are non-empty strings.

    Modifies and returns the dict in-place.
    """
    _walk_and_transform(data, encrypt_value)
    return data
