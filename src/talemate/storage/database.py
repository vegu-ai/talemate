import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from talemate.path import TALEMATE_ROOT

T = TypeVar("T")


class Migration(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = Field(ge=1)
    statements: tuple[str, ...]


class Namespace(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    migrations: tuple[Migration, ...]

    @model_validator(mode="after")
    def consecutive_versions(self):
        if [m.version for m in self.migrations] != list(
            range(1, len(self.migrations) + 1)
        ):
            raise ValueError("Namespace migrations must be consecutive from version 1")
        return self


class NamespaceVersion(BaseModel):
    namespace: str
    version: int


@contextmanager
def transaction(connection: sqlite3.Connection, *, write: bool = True) -> Iterator:
    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


async def _in_thread(operation: Callable[[], T]) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Do not release a caller's lock while its transaction still runs.
        try:
            await task
        finally:
            raise


class Database:
    """Lazy scoped database; callbacks receive a connection inside a transaction.

    Features pass their Namespace to project(directory, namespace) or
    app(namespace), then await read(callback) or write(callback). Connections
    and callbacks stay in the worker thread; return detached row models.
    """

    def __init__(
        self, path: Path | str, *namespaces: Namespace, busy_timeout_ms: int = 5000
    ):
        self.path = Path(path)
        self.namespaces = namespaces
        self.busy_timeout_ms = busy_timeout_ms

    @classmethod
    def project(cls, directory: Path | str, *namespaces: Namespace):
        return cls(Path(directory) / "data.db", *namespaces)

    @classmethod
    def app(cls, *namespaces: Namespace, root: Path | str = TALEMATE_ROOT):
        return cls(Path(root) / "data.db", *namespaces)

    @contextmanager
    def _connection(self, *, cross_thread: bool = False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=not cross_thread,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                connection.execute("PRAGMA journal_mode = WAL")
            with transaction(connection, write=False):
                pending = self._migration_pending(connection)
            if pending:
                with transaction(connection):
                    self._migrate(connection)
            yield connection
        finally:
            connection.close()

    @asynccontextmanager
    async def keep_open(self):
        """Keep WAL open across a burst of operations without holding a transaction.

        Individual callbacks still get their own connections. The idle anchor
        avoids SQLite checkpointing and deleting WAL at every autosave; the last
        connection checkpoints on exit. No synchronous/durability settings change.
        """
        anchor = self._connection(cross_thread=True)
        try:
            await _in_thread(anchor.__enter__)
            yield self
        finally:
            await _in_thread(lambda: anchor.__exit__(None, None, None))

    def _migration_pending(self, connection: sqlite3.Connection) -> bool:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='storage_versions'"
        ).fetchone():
            return True
        pending = False
        for namespace in self.namespaces:
            row = connection.execute(
                "SELECT namespace, version FROM storage_versions WHERE namespace=?",
                (namespace.name,),
            ).fetchone()
            version = NamespaceVersion(**dict(row)).version if row else 0
            if version > len(namespace.migrations):
                raise ValueError(
                    f"Unsupported {namespace.name} storage version {version}"
                )
            pending |= version < len(namespace.migrations)
        return pending

    def _migrate(self, connection: sqlite3.Connection):
        connection.execute(
            "CREATE TABLE IF NOT EXISTS storage_versions "
            "(namespace TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        for namespace in self.namespaces:
            row = connection.execute(
                "SELECT namespace, version FROM storage_versions WHERE namespace = ?",
                (namespace.name,),
            ).fetchone()
            version = NamespaceVersion(**dict(row)).version if row else 0
            if version > len(namespace.migrations):
                raise ValueError(
                    f"Unsupported {namespace.name} storage version {version}"
                )
            for migration in namespace.migrations[version:]:
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO storage_versions(namespace, version) VALUES (?, ?) "
                    "ON CONFLICT(namespace) DO UPDATE SET version = excluded.version",
                    (namespace.name, migration.version),
                )

    def _run(self, operation: Callable[[sqlite3.Connection], T], write: bool) -> T:
        with self._connection() as connection, transaction(connection, write=write):
            return operation(connection)

    async def read(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        return await _in_thread(lambda: self._run(operation, False))

    async def write(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        return await _in_thread(lambda: self._run(operation, True))

    async def backup(self, destination: Path | str) -> Path:
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError("A database cannot be backed up onto itself")

        def copy():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as source:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                    target.execute("PRAGMA journal_mode = DELETE")
                finally:
                    target.close()
            return destination

        return await _in_thread(copy)
