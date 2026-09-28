"""Bioimage data collections at scan and ingest time.

A store is a directory named ``*.zarr`` holding thousands of small files; the
scan must register it as ONE File (never walking into it) and ingest must copy
the whole tree under ``bioimage/{dc_id}/{store}/`` so the chunk endpoint can
serve any key, drop keys a previous upload left behind, and skip a store whose
upload marker still matches. Stores are generated in tmp_path as plain JSON +
bytes, so no zarr dependency, S3 or API is needed: the API calls and boto3 are
mocked (``FakeS3`` keeps objects in a dict).
"""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.deltatables import (
    _delete_s3_keys,
    bioimage_upload_marker_key,
    bioimage_upload_workers,
    client_aggregate_data,
    process_bioimage_data_collection,
    upload_zarr_store,
)
from depictio.cli.cli.utils.scan import (
    _is_current_single_location,
    process_files,
    scan_run_for_multiple_data_collections,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.data_collections_types.bioimage import DCBioimageConfig
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import WorkflowConfig, WorkflowRun

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"
BUCKET = "depictio-bucket"
NOW = "2026-09-26 10:00:00"
OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}

MULTISCALES = {
    "multiscales": [
        {
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"}, {"name": "y"}, {"name": "x"}],
            "datasets": [{"path": "0"}],
        }
    ]
}


def make_store(parent: Path, name: str, attrs: dict | None = None) -> Path:
    """Minimal NGFF 0.4 layout: group metadata, one array, two chunks."""
    store = parent / name
    (store / "0" / "0").mkdir(parents=True)
    (store / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (store / ".zattrs").write_text(json.dumps(MULTISCALES if attrs is None else attrs))
    (store / "0" / ".zarray").write_text(json.dumps({"zarr_format": 2, "shape": [1, 2, 2]}))
    (store / "0" / "0.0.0").write_bytes(b"\x00\x01\x02\x03")
    (store / "0" / "0" / "1").write_bytes(b"\x04\x05")
    return store


def store_size(store: Path) -> int:
    return sum(p.stat().st_size for p in store.rglob("*") if p.is_file())


@pytest.fixture(autouse=True)
def cli_context(monkeypatch):
    """File validation runs its on-disk checks only in CLI context."""
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")


def _permissions() -> Permission:
    return Permission(owners=[UserBase.model_validate(OWNER)])


def _dc(mode: str = "single", pattern: str = r".*\.zarr$", upload: bool = True):
    scan = (
        {"mode": "single", "scan_parameters": {"filename": "unused.zarr"}}
        if mode == "single"
        else {"mode": "recursive", "scan_parameters": {"regex_config": {"pattern": pattern}}}
    )
    return DataCollection.model_validate(
        {
            "_id": DC_ID,
            "data_collection_tag": "images",
            "config": {
                "type": "bioimage",
                "scan": scan,
                "dc_specific_properties": {"upload": upload},
            },
        }
    )


def _run(location: Path) -> WorkflowRun:
    return WorkflowRun(
        workflow_id=PyObjectId(),
        run_tag="run",
        workflow_config_id=PyObjectId(),
        run_location=str(location),
        creation_time=NOW,
        last_modification_time=NOW,
        permissions=_permissions(),
    )


class TestSingleScan:
    def test_store_path_is_one_file(self, tmp_path):
        store = make_store(tmp_path, "sample_A.zarr")

        results = process_files(
            path=str(store),
            run=_run(tmp_path),
            data_collection=_dc(),
            permissions=_permissions(),
            existing_files={},
            skip_regex=True,
        )

        assert len(results) == 1
        file = results[0].file
        assert file.file_location == str(store.resolve())
        assert file.filename == "sample_A.zarr"
        assert file.filesize == store_size(store)
        assert len(file.file_hash) == 64

    def test_folder_of_stores_registers_each_store_not_its_chunks(self, tmp_path):
        folder = tmp_path / "images"
        folder.mkdir()
        make_store(folder, "sample_A.zarr")
        make_store(folder / "nested", "sample_B.zarr")
        (folder / "notes.txt").write_text("not a store")

        results = process_files(
            path=str(folder),
            run=_run(tmp_path),
            data_collection=_dc(),
            permissions=_permissions(),
            existing_files={},
            skip_regex=True,
        )

        assert sorted(r.file.filename for r in results) == ["sample_A.zarr", "sample_B.zarr"]

    def test_hash_follows_zattrs_content(self, tmp_path):
        store = make_store(tmp_path, "sample_A.zarr")

        def scan_hash() -> str:
            (result,) = process_files(
                path=str(store),
                run=_run(tmp_path),
                data_collection=_dc(),
                permissions=_permissions(),
                existing_files={},
                skip_regex=True,
            )
            return result.file.file_hash

        before = scan_hash()
        attrs = {**MULTISCALES, "omero": {"channels": []}}
        (store / ".zattrs").write_text(json.dumps(attrs))

        assert scan_hash() != before

    def test_stores_under_a_single_mode_folder_are_not_stale(self, tmp_path):
        folder = tmp_path / "images"
        folder.mkdir()
        dc = _dc()
        store = str((folder / "sample_A.zarr").resolve())

        assert _is_current_single_location(dc, store, str(folder))
        assert not _is_current_single_location(dc, str(tmp_path / "other.zarr"), str(folder))


class TestRecursiveScan:
    def _scan(self, run_dir: Path, dc: DataCollection) -> list:
        workflow_config = WorkflowConfig()
        with (
            patch("depictio.cli.cli.utils.scan.api_create_files") as create,
            patch("depictio.cli.cli.utils.scan.api_delete_file"),
        ):
            scan_run_for_multiple_data_collections(
                run_location=str(run_dir),
                run_tag="run",
                workflow_config=workflow_config,
                data_collections=[dc],
                all_existing_files={},
                workflow_id=PyObjectId(),
                existing_run=None,
                CLI_config=MagicMock(),
                permissions=_permissions(),
            )
        return [f for call in create.call_args_list for f in call.kwargs["files"]]

    def test_matching_store_directories_are_registered_whole(self, tmp_path):
        run_dir = tmp_path / "run_1"
        run_dir.mkdir()
        a = make_store(run_dir / "a", "sample_A.zarr")
        b = make_store(run_dir / "b", "sample_B.zarr")
        make_store(run_dir, "other.zarr")
        (run_dir / "table.tsv").write_text("x\n1\n")

        files = self._scan(run_dir, _dc(mode="recursive", pattern=r"sample_.*\.zarr$"))

        assert sorted(f.file_location for f in files) == sorted(
            [str(a.resolve()), str(b.resolve())]
        )
        assert {f.filesize for f in files} == {store_size(a)}

    def test_chunk_names_never_match(self, tmp_path):
        """A catch-all regex still registers stores only, never files inside them."""
        run_dir = tmp_path / "run_1"
        run_dir.mkdir()
        store = make_store(run_dir, "sample_A.zarr")

        files = self._scan(run_dir, _dc(mode="recursive", pattern=r".*"))

        assert [f.file_location for f in files] == [str(store.resolve())]


def _registered(monkeypatch, *locations: Path) -> None:
    monkeypatch.setattr(
        deltatables,
        "fetch_file_data",
        lambda dc_id, CLI_config: [SimpleNamespace(file_location=str(p)) for p in locations],
    )


def _ingest_dc(upload: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=DC_ID,
        data_collection_tag="images",
        config=SimpleNamespace(
            type="bioimage", dc_specific_properties=DCBioimageConfig(upload=upload)
        ),
    )


@pytest.fixture
def cli_config() -> MagicMock:
    config = MagicMock()
    config.s3_storage.bucket = BUCKET
    return config


@pytest.fixture
def s3_client(monkeypatch) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr(deltatables, "_s3_client", lambda CLI_config, **kw: client)
    return client


class FakeS3:
    """Dict-backed stand-in for the boto3 calls the OME-Zarr upload makes."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects: dict[str, bytes] = dict(objects or {})
        self.uploaded: list[str] = []
        self.delete_batches: list[list[str]] = []
        self._lock = threading.Lock()

    def upload_file(self, local, bucket, key):
        data = Path(local).read_bytes()
        with self._lock:
            self.objects[key] = data
            self.uploaded.append(key)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def delete_objects(self, Bucket, Delete):
        keys = [o["Key"] for o in Delete["Objects"]]
        self.delete_batches.append(keys)
        for key in keys:
            self.objects.pop(key, None)
        return {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for k in fake.objects if k.startswith(Prefix))
                return [{"Contents": [{"Key": k} for k in keys]}]

        return Paginator()


class TestIngest:
    def test_every_file_of_every_store_is_uploaded_under_its_prefix(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        a = make_store(tmp_path, "sample_A.zarr")
        b = make_store(tmp_path, "sample_B.zarr")
        _registered(monkeypatch, a, b)

        result = process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success"
        keys = {c.args[2] for c in s3_client.upload_file.call_args_list}
        prefix_a = f"bioimage/{DC_ID}/sample_A.zarr/"
        assert {
            prefix_a + ".zattrs",
            prefix_a + ".zgroup",
            prefix_a + "0/.zarray",
            prefix_a + "0/0.0.0",
            prefix_a + "0/0/1",
        } <= keys
        assert len(keys) == 10
        assert {c.args[1] for c in s3_client.upload_file.call_args_list} == {BUCKET}

    def test_missing_multiscales_is_a_clear_error(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        good = make_store(tmp_path, "sample_A.zarr")
        bad = make_store(tmp_path, "plate.zarr", attrs={"plate": {}})
        _registered(monkeypatch, good, bad)

        result = process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert "multiscales" in result["message"]
        assert "plate.zarr" in result["message"]
        s3_client.upload_file.assert_not_called()

    def test_missing_zattrs_is_an_error(self, tmp_path, monkeypatch, cli_config, s3_client):
        store = make_store(tmp_path, "sample_A.zarr")
        (store / ".zattrs").unlink()
        _registered(monkeypatch, store)

        result = process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert ".zattrs" in result["message"]

    def test_reference_only_dc_validates_but_does_not_upload(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        _registered(monkeypatch, make_store(tmp_path, "sample_A.zarr"))

        result = process_bioimage_data_collection(_ingest_dc(upload=False), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success"
        s3_client.upload_file.assert_not_called()

    def test_no_deltatable_is_upserted(self, tmp_path, monkeypatch, cli_config, s3_client):
        _registered(monkeypatch, make_store(tmp_path, "sample_A.zarr"))
        upsert = MagicMock()
        monkeypatch.setattr(deltatables, "api_upsert_deltatable", upsert)

        client_aggregate_data(_ingest_dc(), cli_config, {"overwrite": False})  # type: ignore[arg-type]

        upsert.assert_not_called()
        assert s3_client.upload_file.called

    def test_duplicate_store_names_fail_before_any_upload(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        a = make_store(tmp_path / "run_1", "sample_A.zarr")
        b = make_store(tmp_path / "run_2", "sample_A.zarr")
        c = make_store(tmp_path / "run_2", "sample_B.zarr")
        _registered(monkeypatch, a, b, c)

        result = process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert "sample_A.zarr" in result["message"]
        assert str(a) in result["message"] and str(b) in result["message"]
        assert "sample_B.zarr" not in result["message"]
        s3_client.upload_file.assert_not_called()

    def test_overwrite_forces_a_reupload_of_an_unchanged_store(
        self, tmp_path, monkeypatch, cli_config
    ):
        s3 = FakeS3()
        monkeypatch.setattr(deltatables, "_s3_client", lambda CLI_config, **kw: s3)
        _registered(monkeypatch, make_store(tmp_path, "sample_A.zarr"))

        process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]
        process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]
        assert len(s3.uploaded) == 5

        process_bioimage_data_collection(_ingest_dc(), cli_config, overwrite=True)  # type: ignore[arg-type]
        assert len(s3.uploaded) == 10

    def test_shared_client_pool_matches_the_worker_count(self, tmp_path, monkeypatch, cli_config):
        seen: dict = {}

        def make_client(CLI_config, **kw):
            seen.update(kw)
            return FakeS3()

        monkeypatch.setattr(deltatables, "_s3_client", make_client)
        monkeypatch.setenv("DEPICTIO_BIOIMAGE_UPLOAD_WORKERS", "4")
        _registered(monkeypatch, make_store(tmp_path, "sample_A.zarr"))

        process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert seen == {"max_pool_connections": 4}


PREFIX_A = f"bioimage/{DC_ID}/sample_A.zarr/"
MARKER_A = f"bioimage/{DC_ID}/.uploads/sample_A.zarr.json"


class TestUploadStore:
    def test_marker_lives_outside_every_store_prefix(self):
        assert bioimage_upload_marker_key(DC_ID, "sample_A.zarr") == MARKER_A
        assert not MARKER_A.startswith(PREFIX_A)

    def test_marker_is_written_last_with_the_store_hash(self, tmp_path):
        store = make_store(tmp_path, "sample_A.zarr")
        s3 = FakeS3()

        count = upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=4)

        assert count == 5
        assert len(s3.uploaded) == 5
        marker = json.loads(s3.objects[MARKER_A])
        assert len(marker["hash"]) == 64
        assert marker["objects"] == 5

    def test_unchanged_store_is_skipped(self, tmp_path):
        store = make_store(tmp_path, "sample_A.zarr")
        s3 = FakeS3()
        upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2)

        assert upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2) == 0
        assert len(s3.uploaded) == 5

    def test_changed_store_is_reuploaded(self, tmp_path):
        store = make_store(tmp_path, "sample_A.zarr")
        s3 = FakeS3()
        upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2)
        before = s3.objects[MARKER_A]
        (store / "0" / "0.0.0").write_bytes(b"\x09" * 16)

        assert upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2) == 5
        assert s3.objects[MARKER_A] != before
        assert s3.objects[PREFIX_A + "0/0.0.0"] == b"\x09" * 16

    def test_stale_keys_are_deleted_and_other_stores_kept(self, tmp_path):
        store = make_store(tmp_path, "sample_A.zarr")
        other = f"bioimage/{DC_ID}/sample_AB.zarr/0/0.0.0"
        s3 = FakeS3(
            {
                PREFIX_A + "1/.zarray": b"{}",
                PREFIX_A + "1/0.0.0": b"old",
                PREFIX_A + ".zattrs": b"old",
                other: b"keep",
            }
        )

        upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2)

        assert s3.delete_batches == [[PREFIX_A + "1/.zarray", PREFIX_A + "1/0.0.0"]]
        assert other in s3.objects
        assert MARKER_A in s3.objects
        assert sorted(k for k in s3.objects if k.startswith(PREFIX_A)) == sorted(
            PREFIX_A + rel for rel in (".zattrs", ".zgroup", "0/.zarray", "0/0.0.0", "0/0/1")
        )

    def test_stale_marker_is_removed_before_a_failing_reupload(self, tmp_path):
        store = make_store(tmp_path, "sample_A.zarr")
        s3 = FakeS3({MARKER_A: json.dumps({"hash": "outdated"}).encode()})

        def boom(local, bucket, key):
            raise RuntimeError("network down")

        s3.upload_file = boom  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="network down"):
            upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2)
        assert MARKER_A not in s3.objects

    def test_delete_is_batched_by_a_thousand(self):
        s3 = FakeS3({f"k/{i}": b"" for i in range(2500)})

        _delete_s3_keys(s3, BUCKET, sorted(s3.objects))

        assert [len(b) for b in s3.delete_batches] == [1000, 1000, 500]
        assert s3.objects == {}

    def test_delete_errors_are_raised(self):
        s3 = MagicMock()
        s3.delete_objects.return_value = {
            "Errors": [{"Key": "k/1", "Code": "AccessDenied", "Message": "no"}]
        }

        with pytest.raises(RuntimeError, match="AccessDenied"):
            _delete_s3_keys(s3, BUCKET, ["k/1"])

    @pytest.mark.parametrize(("raw", "expected"), [("", 16), ("8", 8), ("0", 1), ("x", 16)])
    def test_worker_count_from_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("DEPICTIO_BIOIMAGE_UPLOAD_WORKERS", raw)
        assert bioimage_upload_workers() == expected
