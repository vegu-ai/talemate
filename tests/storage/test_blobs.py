import pytest

from talemate.storage import Database
from talemate.storage import blobs


@pytest.mark.asyncio
async def test_deduplicated_blobs_survive_while_any_namespace_references_them(tmp_path):
    db = Database.project(tmp_path, blobs.NAMESPACE)
    blob = blobs.Blob.from_bytes(b'{"value": 1}')

    def insert(connection):
        for namespace in ("first", "second"):
            blobs.put(connection, blob)
            blobs.reference(
                connection,
                blobs.BlobReference(
                    namespace=namespace, owner="one", slot="state", digest=blob.digest
                ),
            )
        return connection.execute("SELECT count(*) FROM storage_blobs").fetchone()[0]

    assert await db.write(insert) == 1
    await db.write(lambda c: blobs.release(c, "first", "one"))
    assert await db.write(blobs.collect) == 0
    assert await db.read(lambda c: blobs.get(c, blob.digest)) == blob
    await db.write(lambda c: blobs.release(c, "second", "one"))
    assert await db.write(blobs.collect) == 1
    with pytest.raises(blobs.BlobCorruptedError, match="Missing snapshot blob"):
        await db.read(lambda c: blobs.get(c, blob.digest))


@pytest.mark.asyncio
async def test_damage_is_detected_and_other_blobs_remain_readable(tmp_path):
    db = Database.project(tmp_path, blobs.NAMESPACE)
    damaged = blobs.Blob.from_bytes(b"original")
    healthy = blobs.Blob.from_bytes(b"different")
    await db.write(lambda c: [blobs.put(c, b) for b in (damaged, healthy)])
    await db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"changed", damaged.digest),
        )
    )
    with pytest.raises(blobs.BlobCorruptedError, match=damaged.digest):
        await db.read(lambda c: blobs.get(c, damaged.digest))
    assert await db.read(lambda c: blobs.get(c, healthy.digest)) == healthy
    with pytest.raises(blobs.BlobCorruptedError):
        await db.write(
            lambda c: blobs.put(c, damaged.model_copy(update={"data": b"wrong"}))
        )


@pytest.mark.asyncio
async def test_reference_update_and_transaction_failure(tmp_path):
    db = Database.project(tmp_path, blobs.NAMESPACE)
    first, second = (blobs.Blob.from_bytes(v) for v in (b"one", b"two"))
    ref = blobs.BlobReference(
        namespace="example", owner="owner", slot="state", digest=first.digest
    )
    await db.write(lambda c: [blobs.put(c, first), blobs.reference(c, ref)])

    def replace(connection, fail=False):
        blobs.put(connection, second)
        blobs.reference(connection, ref.model_copy(update={"digest": second.digest}))
        if fail:
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        await db.write(lambda c: replace(c, fail=True))
    assert await db.read(lambda c: blobs.get(c, first.digest)) == first
    assert await db.write(blobs.collect) == 0
    await db.write(replace)
    assert await db.write(blobs.collect) == 1
    assert await db.read(lambda c: blobs.get(c, second.digest)) == second


async def test_verified_put_heals_damaged_content_and_releases_only_requested_namespace(
    tmp_path,
):
    db = Database.project(tmp_path, blobs.NAMESPACE)
    blob = blobs.Blob.from_bytes(b"unchanged original")

    def setup(c):
        blobs.put(c, blob)
        for namespace in ["one", "two"]:
            blobs.reference(
                c,
                blobs.BlobReference(
                    namespace=namespace, owner="owner", slot="value", digest=blob.digest
                ),
            )
        c.execute("UPDATE storage_blobs SET data=?", (b"damaged",))

    await db.write(setup)
    await db.write(lambda c: blobs.put(c, blob))
    assert await db.read(lambda c: blobs.get(c, blob.digest)) == blob
    assert await db.read(lambda c: blobs.referenced_digests(c, "one")) == {blob.digest}
    await db.write(lambda c: blobs.release_digests(c, "one", {blob.digest}))
    assert await db.read(lambda c: blobs.referenced_digests(c, "one")) == set()
    assert await db.read(lambda c: blobs.referenced_digests(c, "two")) == {blob.digest}
    assert await db.write(blobs.collect) == 0


async def test_missing_digests_checks_rows_without_reading_damaged_content(tmp_path):
    db = Database.project(tmp_path, blobs.NAMESPACE)
    content = [blobs.Blob.from_bytes(str(i).encode()) for i in range(1000)]
    await db.write(lambda c: [blobs.put(c, blob) for blob in content[:-1]])
    await db.write(lambda c: c.execute("UPDATE storage_blobs SET data=?", (b"bad",)))
    assert await db.read(
        lambda c: blobs.missing_digests(c, {blob.digest for blob in content})
    ) == {content[-1].digest}
    assert await db.read(lambda c: blobs.missing_digests(c, set())) == set()
