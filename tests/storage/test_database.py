import asyncio
import sqlite3
import threading

import pytest
from pydantic import ValidationError

from talemate.storage import Database, Migration, Namespace, NamespaceVersion


def feature(name, *statements):
    return Namespace(
        name=name,
        migrations=tuple(
            Migration(version=i, statements=(sql,))
            for i, sql in enumerate(statements, 1)
        ),
    )


@pytest.mark.asyncio
async def test_scopes_are_lazy_and_connections_have_required_settings(tmp_path):
    app = Database.app(root=tmp_path / "app")
    project = Database.project(tmp_path / "project")
    assert not app.path.exists()
    assert not project.path.exists()
    assert (
        await project.read(lambda c: c.execute("PRAGMA journal_mode").fetchone()[0])
        == "wal"
    )
    assert (
        await project.read(lambda c: c.execute("PRAGMA busy_timeout").fetchone()[0])
        == 5000
    )
    assert (
        await project.read(lambda c: c.execute("PRAGMA foreign_keys").fetchone()[0])
        == 1
    )
    assert project.path == tmp_path / "project/data.db"
    assert not app.path.exists()


@pytest.mark.asyncio
async def test_namespaces_upgrade_independently(tmp_path):
    first = feature("first", "CREATE TABLE first_items (id INTEGER PRIMARY KEY)")
    second = feature("second", "CREATE TABLE second_items (name TEXT)")
    db = Database.project(tmp_path, first, second)
    await db.write(lambda c: c.execute("INSERT INTO first_items VALUES (7)"))
    upgraded = feature(
        "first",
        first.migrations[0].statements[0],
        "ALTER TABLE first_items ADD COLUMN name TEXT DEFAULT 'kept'",
    )
    db = Database.project(tmp_path, upgraded)
    assert await db.read(
        lambda c: tuple(c.execute("SELECT * FROM first_items").fetchone())
    ) == (7, "kept")
    versions = await db.read(
        lambda c: [
            NamespaceVersion(**dict(row))
            for row in c.execute("SELECT * FROM storage_versions")
        ]
    )
    assert {v.namespace: v.version for v in versions} == {"first": 2, "second": 1}
    with pytest.raises(ValueError, match="Unsupported first storage version 2"):
        await Database.project(tmp_path, first).read(lambda c: None)


@pytest.mark.asyncio
async def test_failed_migration_rolls_back_tables_and_version(tmp_path):
    broken = feature("broken", "CREATE TABLE broken_items (id INTEGER)", "invalid sql")
    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        await Database.project(tmp_path, broken).write(lambda c: None)
    tables = await Database.project(tmp_path).read(
        lambda c: [
            r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
    )
    assert "broken_items" not in tables
    assert (
        await Database.project(tmp_path).read(
            lambda c: c.execute("SELECT count(*) FROM storage_versions").fetchone()[0]
        )
        == 0
    )


@pytest.mark.parametrize("versions", [[2], [1, 3], [1, 1]])
def test_nonconsecutive_migrations_are_rejected(versions):
    with pytest.raises(ValidationError, match="consecutive"):
        Namespace(
            name="bad",
            migrations=tuple(Migration(version=v, statements=()) for v in versions),
        )


@pytest.mark.asyncio
async def test_write_rollback_and_worker_thread(tmp_path):
    db = Database.project(tmp_path, feature("items", "CREATE TABLE items (id INTEGER)"))
    caller = threading.get_ident()

    def fail(connection):
        assert threading.get_ident() != caller
        connection.execute("INSERT INTO items VALUES (1)")
        raise RuntimeError("aborted")

    with pytest.raises(RuntimeError, match="aborted"):
        await db.write(fail)
    assert (
        await db.read(lambda c: c.execute("SELECT count(*) FROM items").fetchone()[0])
        == 0
    )


@pytest.mark.asyncio
async def test_concurrent_writers_share_one_database(tmp_path):
    namespace = feature("items", "CREATE TABLE items (id INTEGER PRIMARY KEY)")
    first = Database.project(tmp_path, namespace)
    second = Database.project(tmp_path, namespace)
    await first.read(lambda c: None)
    await asyncio.gather(
        *(
            (first if i % 2 else second).write(
                lambda c, i=i: c.execute("INSERT INTO items VALUES (?)", (i,))
            )
            for i in range(20)
        )
    )
    assert (
        await first.read(
            lambda c: c.execute("SELECT count(*) FROM items").fetchone()[0]
        )
        == 20
    )


@pytest.mark.asyncio
async def test_cancellation_waits_for_transaction_to_finish(tmp_path):
    db = Database.project(tmp_path, feature("items", "CREATE TABLE items (id INTEGER)"))
    started, finish = threading.Event(), threading.Event()

    def write(connection):
        connection.execute("INSERT INTO items VALUES (3)")
        started.set()
        assert finish.wait(5)

    task = asyncio.create_task(db.write(write))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await db.read(lambda c: c.execute("SELECT id FROM items").fetchone()[0]) == 3


@pytest.mark.asyncio
async def test_backup_includes_committed_wal_and_is_independent(tmp_path):
    db = Database.project(
        tmp_path / "source", feature("items", "CREATE TABLE items (id INTEGER)")
    )
    await db.write(lambda c: c.execute("INSERT INTO items VALUES (1)"))
    keeper = sqlite3.connect(db.path)
    try:
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        keeper.execute("INSERT INTO items VALUES (2)")
        keeper.commit()
        assert db.path.with_name("data.db-wal").exists()
        destination = await db.backup(tmp_path / "copy/data.db")
    finally:
        keeper.close()
    await db.write(lambda c: c.execute("DELETE FROM items"))
    with sqlite3.connect(destination) as copy:
        assert copy.execute("SELECT id FROM items ORDER BY id").fetchall() == [
            (1,),
            (2,),
        ]
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with pytest.raises(ValueError, match="onto itself"):
        await db.backup(db.path)


async def test_keep_open_preserves_wal_between_operations_and_closes_after_error(
    tmp_path,
):
    database = Database.project(tmp_path)
    wal = tmp_path / "data.db-wal"
    with pytest.raises(RuntimeError, match="leave session"):
        async with database.keep_open():
            await database.write(
                lambda c: c.execute("CREATE TABLE sample (value INTEGER)")
            )
            await database.write(lambda c: c.execute("INSERT INTO sample VALUES (42)"))
            assert wal.exists()
            assert (
                await database.read(
                    lambda c: c.execute("SELECT value FROM sample").fetchone()[0]
                )
                == 42
            )
            assert wal.exists()
            raise RuntimeError("leave session")
    assert not wal.exists()
    assert (
        await database.read(
            lambda c: c.execute("SELECT value FROM sample").fetchone()[0]
        )
        == 42
    )


async def test_current_namespaces_read_while_another_connection_holds_write_lock(
    tmp_path,
):
    namespace = feature("items", "CREATE TABLE items (id INTEGER)")
    db = Database.project(tmp_path, namespace)
    await db.write(lambda c: c.execute("INSERT INTO items VALUES (7)"))
    writer = sqlite3.connect(db.path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO items VALUES (8)")
    try:
        reader = Database(db.path, namespace, busy_timeout_ms=50)
        assert await reader.read(
            lambda c: [row[0] for row in c.execute("SELECT id FROM items")]
        ) == [7]
    finally:
        writer.rollback()
        writer.close()
