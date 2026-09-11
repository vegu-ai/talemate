# Testing

Talemate's default test command runs every test that applies to the checkout:

```bash
uv run pytest tests/
```

No opt-in flag is needed for the full suite. A missing prerequisite fails with
setup guidance instead of silently skipping its coverage.

## Setup

From the repository root, create a lock-file-faithful development environment:

```bash
uv sync --extra dev --locked
uv run python -c "import nltk; nltk.download('punkt_tab')"
```

The Compose configuration tests also require the `docker compose` CLI. Install
[Docker Compose](https://docs.docker.com/compose/install/) through Docker
Desktop or the Compose plugin and verify it with:

```bash
docker compose version
```

These tests call `docker compose config`; they do not start containers and do
not require a running Docker daemon.

## Explicit exclusions

Deliberately omit the Compose checks with a pytest marker expression:

```bash
uv run pytest tests/ -m "not requires_compose"
```

This is never a default. Pytest reports the six deselected Compose cases so the
omitted coverage remains visible.

## Configuration isolation

The root test fixture validates `config.example.yaml` as the runtime
configuration and redirects configuration writes to a temporary directory.
Tests must not read from, write to, or delete the active `config.yaml`, local
scenes, or user templates to influence their result.
