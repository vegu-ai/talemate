# Node reference glossary

The [node reference](/talemate/user-guide/node-editor/reference/nodes/) in the user guide — one page per node category, listing every node's registry path, input/output sockets and properties — is not written by hand. It is rendered from the live node registry by the `glossary` subcommand of the node tools CLI.

## Regenerating the pages

After adding, removing or changing nodes (or their docstrings, sockets or properties), regenerate the reference:

```bash
uv run python -m talemate.game.engine.nodes.tools glossary --write
```

This rewrites the generated portion of every page under `docs/user-guide/node-editor/reference/nodes/`. Anything above the `<!-- glossary:generated -->` marker in a page is a hand-editable intro and is preserved across regenerations — everything below the marker is overwritten.

## Checking for drift

```bash
uv run python -m talemate.game.engine.nodes.tools glossary --check
```

compares the committed pages against a fresh render and exits non-zero when they have drifted from the code (missing pages, stale pages, or generated content that no longer matches). Run it before shipping node changes to catch a forgotten `--write`.

!!! note
    Loading the full node registry takes a while — both commands import every node module before rendering.
