"""Scoped SQLite APIs for feature-owned persistence.

Pass a Namespace of consecutive Migration models to Database.project(directory)
for <project>/data.db, or Database.app() for the lazy app database. Each namespace
owns its prefixed tables and evolves independently through storage_versions.
Await read/write callbacks; they receive a connection within the common
transaction helper and run off the event loop. Return detached Pydantic models.

The blobs module provides verified content addresses and namespace/owner/slot
references. Put content and its references in the feature transaction. Release
obsolete references before collect(); other namespaces' references protect
shared content. Database.backup() uses SQLite's backup API, including WAL data.
"""

from .database import Database, Migration, Namespace, NamespaceVersion

__all__ = ["Database", "Migration", "Namespace", "NamespaceVersion"]
