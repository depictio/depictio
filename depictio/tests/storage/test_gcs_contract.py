"""The StorageBackend contract on GCS: what every caller relies on (#1358).

Runs against the emulator (``gcs``) and, when configured, a real bucket
(``gcs_live``). See ``conftest.py``.
"""

from __future__ import annotations

import threading
from pathlib import Path

import polars as pl
import pytest

from depictio.models.storage import StorageBackend, StorageNotFound


def test_it_fulfils_the_protocol(backend):
    assert isinstance(backend, StorageBackend)
    assert backend.url("a/b") == f"gs://{backend.bucket}/a/b"
    assert backend.key_of(f"gs://{backend.bucket}/a/b") == "a/b"
    assert backend.key_of("gs://another-bucket/a") is None
    assert backend.key_of(f"s3://{backend.bucket}/a") is None


def test_put_read_head_range_and_stream(backend, prefix):
    key = f"{prefix}data.bin"
    backend.put_bytes(key, b"0123456789", content_type="application/octet-stream")

    assert backend.read_bytes(key) == b"0123456789"
    assert backend.read_range(key, 2, 5) == b"234"
    assert backend.read_range(key, 5, 5) == b""
    assert b"".join(backend.iter_chunks(key, 4)) == b"0123456789"
    assert b"".join(backend.iter_chunks(key, 4, start=3, end=7)) == b"3456"
    info = backend.head(key)
    assert info is not None and info.key == key and info.size == 10


def test_a_missing_object(backend, prefix):
    assert backend.head(f"{prefix}nope") is None
    with pytest.raises(StorageNotFound):
        backend.read_bytes(f"{prefix}nope")
    with pytest.raises(FileNotFoundError):
        backend.iter_chunks(f"{prefix}nope")


def test_listing_reads_a_prefix_as_s3_does(backend, prefix):
    for name in ("run1/a.txt", "run1/b.txt", "run10/c.txt", "other/d.txt"):
        backend.put_bytes(f"{prefix}{name}", b"x")

    keys = sorted(o.key[len(prefix) :] for o in backend.list_objects(f"{prefix}run1"))
    # Mid-name, as S3's Prefix: run1/ and run10/ both start with "run1".
    assert keys == ["run1/a.txt", "run1/b.txt", "run10/c.txt"]
    keys = sorted(o.key[len(prefix) :] for o in backend.list_objects(f"{prefix}run1/"))
    assert keys == ["run1/a.txt", "run1/b.txt"]
    assert sorted(f[len(prefix) :] for f in backend.list_folders(prefix)) == [
        "other",
        "run1",
        "run10",
    ]


def test_deletes(backend, prefix):
    for i in range(5):
        backend.put_bytes(f"{prefix}d/{i}", b"x")
    assert backend.delete_keys([f"{prefix}d/0", f"{prefix}d/1"]) == []
    assert backend.delete_keys([]) == []
    assert backend.delete_prefix(f"{prefix}d/") == 3
    assert list(backend.list_objects(f"{prefix}d/")) == []
    assert backend.delete_prefix(f"{prefix}d/") == 0


@pytest.mark.parametrize("multipart", [None, False])
def test_upload_file(backend, prefix, tmp_path: Path, multipart):
    path = tmp_path / "report.parquet"
    path.write_bytes(b"P" * 300_000)
    key = f"{prefix}up/report.parquet"
    backend.upload_file(key, path, multipart=multipart)
    assert backend.read_bytes(key) == path.read_bytes()


def test_bucket_and_startup_checks(backend):
    assert backend.bucket_exists()
    assert backend.ensure_bucket() is False
    backend.check(["bucket", "write"])


def test_fsspec_view_of_the_bucket(backend, prefix):
    backend.put_bytes(f"{prefix}fs/a.json", b"{}")
    listed = backend.filesystem().ls(f"{backend.bucket}/{prefix}fs")
    assert any(p.endswith("fs/a.json") for p in listed)


def test_delta_round_trip_through_the_storage_options(backend, prefix):
    """What ingestion does: write a Delta table at backend.url(dc_id), append, read, vacuum."""
    from deltalake import DeltaTable

    table = backend.url(f"{prefix}dc")
    options = backend.storage_options()
    assert not any(k.startswith("AWS_") or k.startswith("aws_") for k in options)

    pl.DataFrame({"x": [1, 2]}).write_delta(table, storage_options=options, mode="overwrite")
    pl.DataFrame({"x": [3]}).write_delta(table, storage_options=options, mode="append")
    assert pl.scan_delta(table, storage_options=options).collect()["x"].sort().to_list() == [
        1,
        2,
        3,
    ]
    pl.DataFrame({"x": [9]}).write_delta(table, storage_options=options, mode="overwrite")
    removed = DeltaTable(table, storage_options=options).vacuum(
        retention_hours=0, enforce_retention_duration=False, dry_run=False
    )
    assert len(removed) == 2
    assert pl.read_delta(table, storage_options=options)["x"].to_list() == [9]


@pytest.mark.gcs_live
def test_concurrent_commits_lose_nothing(backend, prefix):
    """GCS preconditions make Delta commits atomic. The emulator ignores
    preconditions, so this runs against a real bucket only."""
    if backend.config.endpoint_url:
        pytest.skip("the emulator does not enforce GCS preconditions")
    table = backend.url(f"{prefix}concurrent")
    options = backend.storage_options()
    pl.DataFrame({"x": [0]}).write_delta(table, storage_options=options, mode="overwrite")
    errors: list[Exception] = []

    def append(i: int) -> None:
        try:
            pl.DataFrame({"x": [i]}).write_delta(table, storage_options=options, mode="append")
        except Exception as exc:  # noqa: BLE001 - a conflict is fine, a lost write is not
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(i,)) for i in range(1, 9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = pl.read_delta(table, storage_options=options).height
    assert rows == 1 + 8 - len(errors)


@pytest.mark.gcs_live
def test_presigned_urls_are_readable_without_credentials(backend, prefix):
    """Signed with the key file, or IAM signBlob under Workload Identity."""
    import httpx

    if backend.config.endpoint_url:
        pytest.skip("the emulator has no signing service")
    key = f"{prefix}signed.txt"
    backend.put_bytes(key, b"hello")
    url = backend.presign_get(key, 300)
    assert httpx.get(url, timeout=30).content == b"hello"
