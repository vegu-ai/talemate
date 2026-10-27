import hashlib
import sqlite3

from pydantic import BaseModel, ConfigDict, Field

from .database import Migration, Namespace

NAMESPACE = Namespace(
    name="blobs",
    migrations=(
        Migration(
            version=1,
            statements=(
                "CREATE TABLE storage_blobs (digest TEXT PRIMARY KEY, data BLOB NOT NULL)",
                "CREATE TABLE storage_blob_refs (namespace TEXT NOT NULL, "
                "owner TEXT NOT NULL, slot TEXT NOT NULL, digest TEXT NOT NULL "
                "REFERENCES storage_blobs(digest), PRIMARY KEY(namespace, owner, slot))",
                "CREATE INDEX storage_blob_refs_digest ON storage_blob_refs(digest)",
            ),
        ),
    ),
)


class BlobCorruptedError(ValueError):
    pass


class BlobDigest(BaseModel):
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Blob(BlobDigest):
    model_config = ConfigDict(frozen=True)

    data: bytes

    @classmethod
    def from_bytes(cls, data: bytes):
        return cls(digest=hashlib.sha256(data).hexdigest(), data=data)

    def verify(self):
        if hashlib.sha256(self.data).hexdigest() != self.digest:
            raise BlobCorruptedError(f"Damaged snapshot blob: {self.digest}")


class BlobReference(BaseModel):
    namespace: str
    owner: str
    slot: str
    digest: str


def put(connection: sqlite3.Connection, blob: Blob):
    blob.verify()
    connection.execute(
        "INSERT INTO storage_blobs(digest, data) VALUES (?, ?) "
        "ON CONFLICT(digest) DO UPDATE SET data=excluded.data "
        "WHERE storage_blobs.data != excluded.data",
        (blob.digest, blob.data),
    )


def get(connection: sqlite3.Connection, digest: str) -> Blob:
    row = connection.execute(
        "SELECT digest, data FROM storage_blobs WHERE digest = ?", (digest,)
    ).fetchone()
    if row is None:
        raise BlobCorruptedError(f"Missing snapshot blob: {digest}")
    blob = Blob(**dict(row))
    blob.verify()
    return blob


def missing_digests(connection: sqlite3.Connection, digests: set[str]) -> set[str]:
    missing = set(digests)
    requested = list(digests)
    for start in range(0, len(requested), 900):
        batch = requested[start : start + 900]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            f"SELECT digest FROM storage_blobs WHERE digest IN ({placeholders})", batch
        )
        missing.difference_update(BlobDigest(**dict(row)).digest for row in rows)
    return missing


def reference(connection: sqlite3.Connection, ref: BlobReference):
    connection.execute(
        "INSERT INTO storage_blob_refs(namespace, owner, slot, digest) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(namespace, owner, slot) "
        "DO UPDATE SET digest = excluded.digest",
        (ref.namespace, ref.owner, ref.slot, ref.digest),
    )


def release(connection: sqlite3.Connection, namespace: str, owner: str):
    connection.execute(
        "DELETE FROM storage_blob_refs WHERE namespace = ? AND owner = ?",
        (namespace, owner),
    )


def referenced_digests(connection: sqlite3.Connection, namespace: str) -> set[str]:
    return {
        BlobReference(**dict(row)).digest
        for row in connection.execute(
            "SELECT * FROM storage_blob_refs WHERE namespace=?", (namespace,)
        )
    }


def release_digests(connection: sqlite3.Connection, namespace: str, digests: set[str]):
    connection.executemany(
        "DELETE FROM storage_blob_refs WHERE namespace=? AND digest=?",
        [(namespace, digest) for digest in digests],
    )


def collect(connection: sqlite3.Connection) -> int:
    return connection.execute(
        "DELETE FROM storage_blobs WHERE NOT EXISTS "
        "(SELECT 1 FROM storage_blob_refs WHERE digest = storage_blobs.digest)"
    ).rowcount
