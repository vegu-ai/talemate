# API Key Encryption

!!! info "New in 0.36.0"
    API keys stored in `config.yaml` are now encrypted at rest using Fernet symmetric encryption.

Starting with version 0.36.0, Talemate automatically encrypts all API keys before writing them to `config.yaml`. This protects your credentials from being exposed if the configuration file is accidentally shared, committed to version control, or accessed by unauthorized parties.

## How It Works

When Talemate saves your configuration:

1. All fields named `api_key` or `override_api_key` are identified throughout the configuration
2. Each plaintext key is encrypted using [Fernet symmetric encryption](https://cryptography.io/en/latest/fernet/)
3. The encrypted value is stored with an `ENC:` prefix in `config.yaml`

When Talemate loads the configuration, encrypted values are automatically decrypted back to plaintext in memory. The encryption and decryption are fully transparent -- you continue to enter and use API keys normally through the UI.

### Automatic Migration

Existing plaintext API keys in your `config.yaml` are encrypted automatically the next time Talemate saves the configuration. No manual action is required.

!!! warning "API keys are no longer human-readable"
    If you have been using `config.yaml` as a reference to look up your API keys, that will no longer work after this update. Stored keys will appear as long encrypted strings prefixed with `ENC:`.

## Encryption Key Storage

The encryption key itself must be stored securely. Talemate uses a two-tier approach:

### OS Keyring (Preferred)

When available, the encryption key is stored in your operating system's secure credential storage:

| Platform | Keyring Backend |
|----------|----------------|
| Windows | Windows Credential Locker |
| Linux (Desktop) | GNOME Keyring or KDE Wallet |
| macOS | macOS Keychain |

The OS keyring is the preferred storage method because it is protected by your operating system's security mechanisms, including your user login credentials.

### File-Based Fallback

When no OS keyring is available (common in Docker containers, headless Linux servers, or WSL environments without a desktop), the encryption key is stored in a file:

```
TALEMATE_ROOT/secrets/encryption.key
```

On Linux and macOS, this file is created with restricted permissions (`0600` -- readable only by the file owner).

!!! warning "Protect the key file"
    If using file-based storage, ensure the `secrets/` directory is not accessible to unauthorized users or included in backups that could be compromised. If someone obtains both your `config.yaml` and the encryption key file, they can decrypt your API keys.

### Environment Variables

Two environment variables control encryption key behavior:

| Variable | Effect |
|----------|--------|
| `TALEMATE_DISABLE_KEYRING=1` | Forces file-based key storage even if an OS keyring is available |
| `TALEMATE_ENCRYPTION_KEY_DIR=/path/to/dir` | Overrides the directory where the key file is stored (useful for Docker deployments) |

### Automatic Key Migration

If Talemate finds an encryption key in a file but an OS keyring is now available (for example, after installing a desktop environment), it automatically migrates the key to the keyring and removes the file.

## Lost or Corrupted Keys

If the encryption key is lost or corrupted (for example, if the keyring is reset or the key file is deleted), Talemate will:

1. Log a warning that decryption failed
2. Generate a new encryption key
3. Set affected API key values to empty (null)

You will need to re-enter your API keys through the Talemate UI after a key loss event. This is a security measure -- without the original encryption key, the stored encrypted values cannot be recovered.

## Docker Deployments

For Docker deployments, the encryption key file is stored at the default location inside the container. To persist the key across container recreations, mount a volume to the `secrets/` directory:

```yaml
volumes:
  - ./secrets:/app/secrets
```

Alternatively, use the `TALEMATE_ENCRYPTION_KEY_DIR` environment variable to point to a mounted volume:

```yaml
environment:
  - TALEMATE_ENCRYPTION_KEY_DIR=/data/secrets
volumes:
  - ./data/secrets:/data/secrets
```

## Technical Details

- **Algorithm**: Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256)
- **Key format**: URL-safe base64-encoded 32-byte key
- **Encrypted fields**: `api_key` and `override_api_key` throughout the config structure
- **Prefix**: Encrypted values are stored with `ENC:` prefix for identification
- **Plaintext passthrough**: Values without the `ENC:` prefix are treated as legacy plaintext and encrypted on next save
