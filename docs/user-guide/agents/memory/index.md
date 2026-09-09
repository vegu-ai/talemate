# Overview

Manages long term memory via embeddings.

Currently only supports ChromaDB as a backend, but support for additional backends is planned.

Obsolete cached retrievals are released when stored memory changes.

Cached long term memory is refreshed after edits to world entries, character details,
or other stored memories, including deletions. The next prompt uses the updated
memory even when no story message has been added. This applies with and without
Character perspectives enabled. A retrieval already in progress can finish with
its earlier context; that context will not be reused by the next prompt.

When a memory deletion finishes after an interruption, character audiences are still refreshed so the removed entry does not linger in their prompts.
