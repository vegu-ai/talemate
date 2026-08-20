# Environment variables

Talemate reads a small set of environment variables at startup. They cover networking, debugging, encryption, and the Docker frontend's WebSocket discovery. CLI flags (where applicable) override the matching env var.

## Backend & frontend networking

Read by [src/talemate/server/run.py](https://github.com/vegu-ai/talemate/blob/main/src/talemate/server/run.py) and the start scripts.

| Variable | Default | CLI flag | Purpose |
|----------|---------|----------|---------|
| `TALEMATE_BACKEND_HOST` | `localhost` | `--host` | Interface the backend websocket server binds to. |
| `TALEMATE_BACKEND_PORT` | `5050` | `--port` | Port the backend websocket server binds to. |
| `TALEMATE_FRONTEND_HOST` | `localhost` | `--frontend-host` | Interface the frontend web server binds to. |
| `TALEMATE_FRONTEND_PORT` | `8082` | `--frontend-port` | Port the frontend web server binds to. |

In Docker the host variables default to `0.0.0.0` inside the container so the ports are reachable from your browser.

See [Changing host and port](change-host-and-port.md) for full usage, including the upgrade notes for the `0.36.x → 0.37.0` port and Docker variable rename.

## Frontend WebSocket URL (browser)

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_TALEMATE_BACKEND_WEBSOCKET_URL` | _auto-detect_ `ws://<host>:5050/ws` | WebSocket URL the browser uses to reach the backend. Required whenever the backend port differs from `5050` or the browser cannot reach the backend on its own hostname. |

This variable is read by Vite at build time and re-read at container start in the Docker image. See [Changing host and port – Docker Runtime Configuration](change-host-and-port.md#docker-runtime-configuration).

## Logging & debugging

| Variable | Default | Purpose |
|----------|---------|---------|
| `TALEMATE_DEBUG` | _unset_ | Set to `1` to enable `DEBUG`-level logging and write errors to a separate error log file. See [Debug logging](debug-logging.md). |
| `TALEMATE_LOG_PROMPTS` | _unset_ | Set to any non-empty value to write full prompt + response data to `logs/prompt_log.jsonl`. See [Prompt logging](prompt-logging.md). |
| `TALEMATE_PI_BRIDGE_TRACE` | _unset_ | Set to `1` to log the [Pi Bridge client's](../../user-guide/clients/types/pi-bridge.md) pi event stream as it is consumed (per-event sizes and types plus a heartbeat warning while the stream is silent). Diagnostic aid for generations that stream but never finish. |

`start-backend.sh` and `start-backend.bat` set `TALEMATE_DEBUG=1` automatically; the production `start.sh` / `start.bat` do not.

## API-key encryption

Read by [src/talemate/util/encryption.py](https://github.com/vegu-ai/talemate/blob/main/src/talemate/util/encryption.py).

| Variable | Default | Purpose |
|----------|---------|---------|
| `TALEMATE_DISABLE_KEYRING` | _unset_ | Set to `1` to force file-based key storage even if an OS keyring is available. |
| `TALEMATE_ENCRYPTION_KEY_DIR` | `<TALEMATE_ROOT>/secrets/` | Directory where the encryption key file is stored. Useful for Docker volumes. |

See [API key encryption](../../user-guide/api-key-encryption.md) for the full key-management flow, including automatic migration between keyring and file storage.

## Docker Compose passthroughs

The values below are not consumed by Talemate's Python code directly — they're consumed by the default and CPU-only Compose configurations so that the same variable controls both the published host port and the value passed into the container as `TALEMATE_BACKEND_PORT` / `TALEMATE_FRONTEND_PORT`:

- `TALEMATE_BACKEND_PORT`
- `TALEMATE_FRONTEND_PORT`
- `VITE_TALEMATE_BACKEND_WEBSOCKET_URL`

Set them in your shell or in a `.env` file alongside `docker-compose.yml`.
