"""
Fernet encryption utilities for protecting API keys at rest in config.yaml.

The encryption key is stored in the OS keyring when available (Windows
Credential Locker, GNOME Keyring, KDE Wallet, etc.).  When no keyring
backend is detected (e.g. Docker / headless Linux), the key is stored in
a ``secrets/`` directory next to config.yaml
(i.e. ``TALEMATE_ROOT/secrets/encryption.key``).

The file location can be overridden via the ``TALEMATE_ENCRYPTION_KEY_DIR``
environment variable for Docker deployments.

Set ``TALEMATE_DISABLE_KEYRING=1`` to force file-based storage.
"""

import os
import sys
import structlog
from pathlib import Path

import keyring
from keyring.backends.fail import Keyring as FailKeyring
from cryptography.fernet import Fernet, InvalidToken

from talemate.path import TALEMATE_ROOT

log = structlog.get_logger("talemate.util.encryption")

# Prefix that marks encrypted values in YAML
ENC_PREFIX = "ENC:"

# Field names to encrypt/decrypt when walking config dicts
_SENSITIVE_FIELD_NAMES = frozenset({"api_key", "override_api_key"})

# Keyring identifiers for OS credential storage
_KEYRING_SERVICE = "talemate"
_KEYRING_USERNAME = "encryption_key"

# Module-level cached Fernet instance
_fernet: Fernet | None = None


# ---------------------------------------------------------------------------
# Key file helpers
# ---------------------------------------------------------------------------


def _key_file_path() -> Path:
    """
    Return the path to the Fernet key file.

    Default: ``TALEMATE_ROOT/secrets/encryption.key``
    Override: set ``TALEMATE_ENCRYPTION_KEY_DIR`` env var to a directory path.
    """
    env_dir = os.environ.get("TALEMATE_ENCRYPTION_KEY_DIR")
    if env_dir:
        return Path(env_dir) / "encryption.key"

    return TALEMATE_ROOT / "secrets" / "encryption.key"


def _write_key_file(key: bytes, path: Path) -> None:
    """Write a Fernet key to *path* with secure permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform != "win32":
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
    else:
        path.write_bytes(key)

    log.info("wrote encryption key to file", path=str(path))


def _generate_key_file(path: Path) -> bytes:
    """Generate a new Fernet key and write it to the given path."""
    key = Fernet.generate_key()
    _write_key_file(key, path)
    return key


# ---------------------------------------------------------------------------
# OS keyring helpers (lazy-import for robustness)
# ---------------------------------------------------------------------------


def _keyring_available() -> bool:
    """
    Return True if the ``keyring`` library is installed and a usable
    backend is present (i.e. not the fail backend).

    Respects the ``TALEMATE_DISABLE_KEYRING`` environment variable.
    """
    if os.environ.get("TALEMATE_DISABLE_KEYRING"):
        return False

    try:
        backend = keyring.get_keyring()
        if isinstance(backend, FailKeyring):
            return False
        return True
    except Exception:
        return False


def _load_key_from_keyring() -> bytes | None:
    """
    Attempt to read the Fernet key from the OS keyring.

    Returns the key as bytes, or ``None`` if unavailable / not stored.
    """
    try:
        value = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if value is not None:
            log.debug("loaded encryption key from OS keyring")
            return value.encode("utf-8")
        return None
    except Exception as exc:
        log.debug("could not read from OS keyring", error=str(exc))
        return None


def _store_key_in_keyring(key: bytes) -> bool:
    """
    Attempt to store the Fernet key in the OS keyring.

    Returns ``True`` on success, ``False`` on failure.
    """
    try:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key.decode("utf-8"))
        log.info("stored encryption key in OS keyring")
        return True
    except Exception as exc:
        log.debug("could not store key in OS keyring", error=str(exc))
        return False


def _delete_key_from_keyring() -> bool:
    """
    Attempt to delete the Fernet key from the OS keyring.

    Returns ``True`` on success, ``False`` on failure.
    """
    try:
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        log.info("deleted encryption key from OS keyring")
        return True
    except Exception:
        return False


def _migrate_file_to_keyring(key: bytes, file_path: Path) -> None:
    """
    Migrate an existing file-based key to the OS keyring, then remove
    the file.  If storing in the keyring fails the file is left in place.
    """
    if _store_key_in_keyring(key):
        try:
            file_path.unlink()
            log.info(
                "migrated encryption key from file to OS keyring, file removed",
                path=str(file_path),
            )
        except OSError as exc:
            log.warning(
                "stored key in keyring but could not remove old file",
                path=str(file_path),
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Key loading / generation / regeneration
# ---------------------------------------------------------------------------


def _load_or_create_key() -> bytes:
    """
    Load the Fernet key, checking OS keyring first, then file fallback.

    Strategy:
      1. Try OS keyring  → if found, return it.
      2. Try key file    → if found, attempt migration to keyring, return key.
      3. Neither exists  → generate new key, store in keyring (or file).
    """
    use_keyring = _keyring_available()

    # 1. Try keyring
    if use_keyring:
        key = _load_key_from_keyring()
        if key is not None:
            return key

    # 2. Try file
    file_path = _key_file_path()
    if file_path.exists():
        key = file_path.read_bytes().strip()
        log.debug("loaded encryption key from file", path=str(file_path))
        if use_keyring:
            _migrate_file_to_keyring(key, file_path)
        return key

    # 3. Generate new key
    log.info("no encryption key found, generating new key")
    key = Fernet.generate_key()

    if use_keyring and _store_key_in_keyring(key):
        return key

    # Fallback: write to file
    _write_key_file(key, file_path)
    return key


def _regenerate_key() -> bytes:
    """
    Generate a new Fernet key and store it, replacing any existing key
    in both keyring and file.
    """
    key = Fernet.generate_key()
    file_path = _key_file_path()

    if _keyring_available():
        _delete_key_from_keyring()
        if _store_key_in_keyring(key):
            # Remove stale file if present
            if file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    pass
            return key

    # Fallback: write to file
    _write_key_file(key, file_path)
    return key


# ---------------------------------------------------------------------------
# Fernet instance management
# ---------------------------------------------------------------------------


def get_fernet() -> Fernet:
    """Return the module-level cached Fernet instance, creating it if needed."""
    global _fernet
    if _fernet is None:
        key = _load_or_create_key()
        try:
            _fernet = Fernet(key)
        except (ValueError, Exception) as e:
            log.warning(
                "encryption key is corrupted, regenerating",
                error=str(e),
            )
            key = _regenerate_key()
            _fernet = Fernet(key)
    return _fernet


def reset_fernet():
    """
    Clear the cached Fernet instance. Called after generating a fresh key
    due to InvalidToken errors.
    """
    global _fernet
    _fernet = None


# ---------------------------------------------------------------------------
# Value-level encrypt / decrypt
# ---------------------------------------------------------------------------


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
    key, and returns None to null out the value.
    """
    if not stored:
        return stored

    if not stored.startswith(ENC_PREFIX):
        return stored

    token = stored[len(ENC_PREFIX) :]
    f = get_fernet()

    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        log.warning(
            "failed to decrypt api key value (key may have been lost or replaced); "
            "the affected api key will need to be re-entered",
        )
        _regenerate_key()
        reset_fernet()
        return None


# ---------------------------------------------------------------------------
# Dict-walking helpers for config encrypt/decrypt
# ---------------------------------------------------------------------------


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
