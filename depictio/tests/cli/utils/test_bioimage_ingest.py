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
import struct
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
    upload_ome_tiff,
    upload_zarr_store,
    validate_ome_tiff,
    zarr_store_hash,
)
from depictio.cli.cli.utils.scan import (
    _is_current_single_location,
    process_files,
    scan_project_files,
    scan_run_for_multiple_data_collections,
    zarr_store_stats,
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


OME_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
    '<Image ID="Image:0"><Pixels ID="Pixels:0" SizeX="2" SizeY="2" SizeC="1" SizeZ="1"'
    ' SizeT="1" Type="uint8" DimensionOrder="XYZCT"/></Image></OME>'
)


def make_ome_tiff(
    path: Path,
    description: str | None = OME_XML,
    *,
    bigtiff: bool = False,
    order: str = "<",
) -> Path:
    """Header + first IFD only (ImageWidth, then ImageDescription): enough to validate.

    Written by hand so the tests need no TIFF library.
    """
    mark = b"II" if order == "<" else b"MM"
    desc = description.encode() + b"\x00" if description is not None else b""
    if bigtiff:
        header = mark + struct.pack(order + "HHHQ", 43, 8, 0, 16)
        count_fmt, entry_fmt, next_fmt = "Q", "HHQ8s", "Q"
    else:
        header = mark + struct.pack(order + "HI", 42, 8)
        count_fmt, entry_fmt, next_fmt = "H", "HHI4s", "I"
    value_size = 8 if bigtiff else 4
    entries = [(256, 3, 1, struct.pack(order + "H", 2).ljust(value_size, b"\x00"))]
    n = len(entries) + (1 if description is not None else 0)
    ifd_size = sum(struct.calcsize(order + f) for f in (count_fmt, next_fmt))
    ifd_size += n * struct.calcsize(order + entry_fmt)
    desc_offset = len(header) + ifd_size
    if description is not None:
        offset_fmt = "I" if value_size == 4 else "Q"
        entries.append((270, 2, len(desc), struct.pack(order + offset_fmt, desc_offset)))
    ifd = struct.pack(order + count_fmt, n)
    for entry in entries:
        ifd += struct.pack(order + entry_fmt, *entry)
    ifd += struct.pack(order + next_fmt, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + ifd + desc + b"\x00" * 4)
    return path


def make_spatialdata(parent: Path, name: str, images: tuple[str, ...] = ("img",)) -> Path:
    """A SpatialData root (zarr v2) with NGFF 0.4 images and a table element."""
    root = parent / name
    root.mkdir(parents=True)
    (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (root / ".zattrs").write_text(json.dumps({"spatialdata_attrs": {"version": "0.2"}}))
    (root / "images").mkdir()
    (root / "images" / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    for image in images:
        make_store(root / "images", image)
    table = root / "tables" / "table"
    table.mkdir(parents=True)
    (table / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (table / "X").write_bytes(b"\x00" * 8)
    return root


SHARDED_CODECS = [
    {
        "name": "sharding_indexed",
        "configuration": {
            "chunk_shape": [1, 2, 2],
            "codecs": [{"name": "bytes", "configuration": {"endian": "little"}}],
            "index_codecs": [{"name": "bytes", "configuration": {"endian": "little"}}],
            "index_location": "end",
        },
    }
]


def make_store_v3(
    parent: Path, name: str, ome: dict | None = None, levels: tuple[str, ...] = ("0", "1")
) -> Path:
    """Minimal NGFF 0.5 layout: a zarr v3 group and one sharded array per level.

    Shards are fake bytes: the CLI never decodes chunks.
    """
    store = parent / name
    store.mkdir(parents=True)
    if ome is None:
        ome = {
            "version": "0.5",
            "multiscales": [
                {
                    "axes": [{"name": "c", "type": "channel"}, {"name": "y"}, {"name": "x"}],
                    "datasets": [{"path": level} for level in levels],
                }
            ],
        }
    group = {"zarr_format": 3, "node_type": "group", "attributes": {"ome": ome}}
    (store / "zarr.json").write_text(json.dumps(group))
    for level in levels:
        (store / level / "c" / "0" / "0").mkdir(parents=True)
        array = {
            "zarr_format": 3,
            "node_type": "array",
            "shape": [1, 4, 4],
            "data_type": "uint8",
            "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [1, 4, 4]}},
            "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
            "fill_value": 0,
            "codecs": SHARDED_CODECS,
        }
        (store / level / "zarr.json").write_text(json.dumps(array))
        (store / level / "c" / "0" / "0" / "0").write_bytes(b"\x07" * 48)
    return store


def make_spatialdata_v3(parent: Path, name: str, image: str = "img") -> Path:
    """A SpatialData root in zarr v3 (spatialdata >= 0.5 defaults) with an NGFF 0.5 image."""
    root = parent / name
    root.mkdir(parents=True)
    (root / "zarr.json").write_text(
        json.dumps(
            {
                "zarr_format": 3,
                "node_type": "group",
                "attributes": {"spatialdata_attrs": {"version": "0.2"}},
            }
        )
    )
    (root / "images").mkdir()
    (root / "images" / "zarr.json").write_text(
        json.dumps({"zarr_format": 3, "node_type": "group", "attributes": {}})
    )
    make_store_v3(root / "images", image)
    table = root / "tables" / "table"
    table.mkdir(parents=True)
    (table / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group"}))
    return root


def store_size(store: Path) -> int:
    return sum(p.stat().st_size for p in store.rglob("*") if p.is_file())


@pytest.fixture(autouse=True)
def cli_context(monkeypatch):
    """File validation runs its on-disk checks only in CLI context."""
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")


def _permissions() -> Permission:
    return Permission(owners=[UserBase.model_validate(OWNER)])


def _dc(mode: str = "single", pattern: str = r".*\.zarr$", upload: bool = True, **props):
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
                "dc_specific_properties": {"upload": upload, **props},
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


class TestFormatScan:
    def _single(self, path: Path, dc: DataCollection) -> list:
        return process_files(
            path=str(path),
            run=_run(path.parent),
            data_collection=dc,
            permissions=_permissions(),
            existing_files={},
            skip_regex=True,
        )

    def test_ome_tiff_file_is_one_file(self, tmp_path):
        tiff = make_ome_tiff(tmp_path / "sample_A.ome.tif")

        (result,) = self._single(tiff, _dc(format="ome-tiff"))

        assert result.file.filename == "sample_A.ome.tif"
        assert result.file.filesize == tiff.stat().st_size

    def test_ome_tiff_folder_keeps_ome_tiffs_only(self, tmp_path):
        folder = tmp_path / "images"
        make_ome_tiff(folder / "sample_A.ome.tif")
        make_ome_tiff(folder / "nested" / "sample_B.ome.tiff")
        make_ome_tiff(folder / "plain.tif")
        make_ome_tiff(make_store(folder, "sample_C.zarr") / "inside.ome.tif")

        results = self._single(folder, _dc(format="ome-tiff"))

        assert sorted(r.file.filename for r in results) == ["sample_A.ome.tif", "sample_B.ome.tiff"]

    def test_symlinked_ome_tiff_keeps_its_scanned_name(self, tmp_path):
        """git-annex / DataLad: the link carries the name, the target is a content blob."""
        blob = make_ome_tiff(tmp_path / "annex" / "MD5E-s123--abc.ome.tif")
        link = tmp_path / "data" / "sample_A.ome.tif"
        link.parent.mkdir()
        link.symlink_to(blob)

        (result,) = self._single(link, _dc(format="ome-tiff"))

        assert result.file.filename == "sample_A.ome.tif"
        assert result.file.file_location == str(link)

    def test_symlinked_zarr_store_keeps_its_scanned_name(self, tmp_path):
        target = make_store(tmp_path / "work", "abc123.zarr")
        link = tmp_path / "sample_A.zarr"
        link.symlink_to(target)

        (result,) = self._single(link, _dc())

        assert result.file.filename == "sample_A.zarr"

    def test_non_ome_tiff_single_path_registers_nothing(self, tmp_path):
        assert self._single(make_ome_tiff(tmp_path / "plain.tif"), _dc(format="ome-tiff")) == []

    def test_spatialdata_store_is_one_file_at_its_root(self, tmp_path):
        root = make_spatialdata(tmp_path, "slide.zarr")

        (result,) = self._single(root, _dc(format="spatialdata", image_path="images/img"))

        assert result.file.file_location == str(root.resolve())
        assert result.file.filesize == store_size(root)

    def test_recursive_ome_tiff_matches_tiff_files_only(self, tmp_path):
        run_dir = tmp_path / "run_1"
        tiff = make_ome_tiff(run_dir / "a" / "sample_A.ome.tiff")
        make_ome_tiff(run_dir / "plain.tif")
        make_store(run_dir, "sample_B.zarr")

        files = TestRecursiveScan()._scan(
            run_dir, _dc(mode="recursive", pattern=r".*", format="ome-tiff")
        )

        assert [f.file_location for f in files] == [str(tiff.resolve())]

    def test_recursive_spatialdata_registers_the_store_root(self, tmp_path):
        run_dir = tmp_path / "run_1"
        root = make_spatialdata(run_dir, "slide.zarr")

        files = TestRecursiveScan()._scan(
            run_dir,
            _dc(mode="recursive", pattern=r".*", format="spatialdata", image_path="images/img"),
        )

        assert [f.file_location for f in files] == [str(root.resolve())]

    def test_remote_only_dc_is_not_scanned(self):
        # A stand-in: the DataCollection validator still requires `scan` on native DCs.
        remote_dc = SimpleNamespace(
            id=DC_ID,
            data_collection_tag="remote",
            config=SimpleNamespace(
                type="bioimage",
                scan=None,
                dc_specific_properties=DCBioimageConfig(
                    remote_stores=["https://images.example.org/a/sample_A.zarr"]
                ),
            ),
        )
        project = SimpleNamespace(
            name="p",
            workflows=[SimpleNamespace(workflow_tag="wf", data_collections=[remote_dc])],
        )
        with (
            patch("depictio.cli.cli.utils.scan.scan_files_for_workflow") as agg,
            patch("depictio.cli.cli.utils.scan.scan_files_for_data_collection") as single,
            patch("depictio.cli.cli.utils.scan.rich_print_checked_statement") as printed,
        ):
            result = scan_project_files(project, MagicMock())

        assert result["result"] == "success"
        agg.assert_not_called()
        single.assert_not_called()
        assert any("1 remote store(s), read in place" in c.args[0] for c in printed.call_args_list)


def _registered(monkeypatch, *locations: Path) -> None:
    monkeypatch.setattr(
        deltatables,
        "fetch_file_data",
        lambda dc_id, CLI_config: [SimpleNamespace(file_location=str(p)) for p in locations],
    )


def _ingest_dc(upload: bool = True, scan: object = True, **props) -> SimpleNamespace:
    return SimpleNamespace(
        id=DC_ID,
        data_collection_tag="images",
        config=SimpleNamespace(
            type="bioimage",
            scan=scan,
            dc_specific_properties=DCBioimageConfig(upload=upload, **props),
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
        monkeypatch.setenv("DEPICTIO_INGEST_BIOIMAGE_UPLOAD_WORKERS", "4")
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
        monkeypatch.setenv("DEPICTIO_INGEST_BIOIMAGE_UPLOAD_WORKERS", raw)
        assert bioimage_upload_workers() == expected


SD_PREFIX = f"bioimage/{DC_ID}/slide.zarr/"
SD_MARKER = f"bioimage/{DC_ID}/.uploads/slide.zarr.json"
TIFF_KEY = f"bioimage/{DC_ID}/sample_A.ome.tif"
TIFF_MARKER = f"bioimage/{DC_ID}/.uploads/sample_A.ome.tif.json"
IMAGE_KEYS = (".zattrs", ".zgroup", "0/.zarray", "0/0.0.0", "0/0/1")


@pytest.fixture
def fake_s3(monkeypatch) -> FakeS3:
    s3 = FakeS3()
    monkeypatch.setattr(deltatables, "_s3_client", lambda CLI_config, **kw: s3)
    return s3


V3_KEYS = (
    "zarr.json",
    "0/zarr.json",
    "0/c/0/0/0",
    "1/zarr.json",
    "1/c/0/0/0",
)


class TestZarrV3:
    def test_sharded_ngff_05_store_is_uploaded_whole(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        _registered(monkeypatch, make_store_v3(tmp_path, "sample_A.zarr"))

        result = process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success"
        assert sorted(k for k in fake_s3.objects if k != MARKER_A) == sorted(
            PREFIX_A + rel for rel in V3_KEYS
        )
        assert fake_s3.objects[PREFIX_A + "0/c/0/0/0"] == b"\x07" * 48

    def test_v2_and_v3_stores_mix_when_no_version_is_pinned(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        _registered(
            monkeypatch, make_store(tmp_path, "v2.zarr"), make_store_v3(tmp_path, "v3.zarr")
        )

        result = process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success"

    @pytest.mark.parametrize(
        ("maker", "pinned", "found"),
        [(make_store_v3, "0.4", "NGFF 0.5"), (make_store, "0.5", "NGFF 0.4")],
    )
    def test_pinned_ngff_version_rejects_the_other(
        self, tmp_path, monkeypatch, cli_config, fake_s3, maker, pinned, found
    ):
        _registered(monkeypatch, maker(tmp_path, "sample_A.zarr"))

        result = process_bioimage_data_collection(
            _ingest_dc(ngff_version=pinned),  # type: ignore[arg-type]
            cli_config,
        )

        assert result["result"] == "error"
        assert found in result["message"]
        assert f"requires ngff_version {pinned}" in result["message"]
        assert fake_s3.uploaded == []

    @pytest.mark.parametrize(("maker", "pinned"), [(make_store_v3, "0.5"), (make_store, "0.4")])
    def test_pinned_ngff_version_accepts_its_own(self, tmp_path, maker, pinned):
        store = maker(tmp_path, "sample_A.zarr")
        assert deltatables.validate_ome_zarr_store(str(store), pinned) == pinned

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            (
                lambda s: (s / "zarr.json").write_text(
                    json.dumps({"zarr_format": 3, "node_type": "group", "attributes": MULTISCALES})
                ),
                "no 'attributes.ome' entry",
            ),
            (
                lambda s: (s / "zarr.json").write_text(
                    json.dumps(
                        {
                            "zarr_format": 3,
                            "node_type": "group",
                            "attributes": {"ome": {"version": "0.5", "plate": {}}},
                        }
                    )
                ),
                "no 'multiscales' entry",
            ),
            (
                lambda s: (s / "zarr.json").write_text(
                    json.dumps({"zarr_format": 3, "node_type": "array"})
                ),
                "not a zarr v3 group",
            ),
            (lambda s: (s / "1" / "zarr.json").unlink(), "no array at dataset path '1'"),
            (
                lambda s: (s / "1" / "zarr.json").write_text(
                    json.dumps({"zarr_format": 3, "node_type": "group"})
                ),
                "is not a zarr v3 array",
            ),
            (lambda s: (s / "zarr.json").write_text("{not json"), "is not valid JSON"),
            (lambda s: (s / "zarr.json").unlink(), "no root .zattrs (NGFF 0.4) or zarr.json"),
        ],
    )
    def test_invalid_v3_stores_are_clear_errors(
        self, tmp_path, monkeypatch, cli_config, fake_s3, mutate, expected
    ):
        store = make_store_v3(tmp_path, "sample_A.zarr")
        mutate(store)
        _registered(monkeypatch, store)

        result = process_bioimage_data_collection(_ingest_dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert expected in result["message"]
        assert fake_s3.uploaded == []

    def test_dataset_path_cannot_escape_the_store(self, tmp_path):
        store = make_store_v3(
            tmp_path,
            "sample_A.zarr",
            ome={"multiscales": [{"datasets": [{"path": "../other"}]}]},
            levels=(),
        )
        with pytest.raises(ValueError, match="invalid dataset path"):
            deltatables.validate_ome_zarr_store(str(store))

    def test_hash_follows_zarr_json_content(self, tmp_path):
        store = make_store_v3(tmp_path, "sample_A.zarr")
        before = zarr_store_hash(str(store))
        meta = json.loads((store / "zarr.json").read_text())
        meta["attributes"]["ome"]["multiscales"][0]["name"] = "renamed"
        text = json.dumps(meta)
        (store / "zarr.json").write_text(text)

        assert zarr_store_stats(str(store))[2] == text.encode()
        assert zarr_store_hash(str(store)) != before

    def test_rewritten_shard_reuploads(self, tmp_path):
        store = make_store_v3(tmp_path, "sample_A.zarr")
        s3 = FakeS3()
        assert upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2) == len(V3_KEYS)
        (store / "0" / "c" / "0" / "0" / "0").write_bytes(b"\x08" * 96)

        assert upload_zarr_store(s3, BUCKET, DC_ID, str(store), workers=2) == len(V3_KEYS)
        assert s3.objects[PREFIX_A + "0/c/0/0/0"] == b"\x08" * 96


class TestSpatialData:
    def _dc(self, image_path: str = "images/img", **kw) -> SimpleNamespace:
        return _ingest_dc(format="spatialdata", image_path=image_path, **kw)

    def test_only_the_image_subtree_is_uploaded(self, tmp_path, monkeypatch, cli_config, fake_s3):
        _registered(monkeypatch, make_spatialdata(tmp_path, "slide.zarr"))

        result = process_bioimage_data_collection(self._dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success"
        assert "SpatialData" in result["message"]
        assert sorted(k for k in fake_s3.objects if k != SD_MARKER) == sorted(
            SD_PREFIX + rel for rel in IMAGE_KEYS
        )
        assert json.loads(fake_s3.objects[SD_MARKER])["objects"] == 5

    def test_changing_image_path_reuploads(self, tmp_path, cli_config):
        root = make_spatialdata(tmp_path, "slide.zarr", images=("img", "other"))
        s3 = FakeS3()
        upload_zarr_store(s3, BUCKET, DC_ID, str(root), workers=2, image_path="images/img")

        assert (
            upload_zarr_store(s3, BUCKET, DC_ID, str(root), workers=2, image_path="images/img") == 0
        )
        assert (
            upload_zarr_store(s3, BUCKET, DC_ID, str(root), workers=2, image_path="images/other")
            == 5
        )
        assert zarr_store_hash(str(root), "images/img") != zarr_store_hash(
            str(root), "images/other"
        )

    def test_a_change_outside_the_image_does_not_reupload(self, tmp_path):
        root = make_spatialdata(tmp_path, "slide.zarr")
        s3 = FakeS3()
        upload_zarr_store(s3, BUCKET, DC_ID, str(root), workers=2, image_path="images/img")
        (root / "tables" / "table" / "X").write_bytes(b"\x01" * 64)

        assert (
            upload_zarr_store(s3, BUCKET, DC_ID, str(root), workers=2, image_path="images/img") == 0
        )

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            (lambda root: None, "no image element at image_path 'images/missing'"),
            (
                lambda root: (root / ".zattrs").unlink() or (root / ".zgroup").unlink(),
                "not a SpatialData store",
            ),
        ],
    )
    def test_invalid_stores_are_clear_errors(
        self, tmp_path, monkeypatch, cli_config, fake_s3, mutate, expected
    ):
        root = make_spatialdata(tmp_path, "slide.zarr")
        mutate(root)
        _registered(monkeypatch, root)
        image_path = "images/missing" if "missing" in expected else "images/img"

        result = process_bioimage_data_collection(self._dc(image_path), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert expected in result["message"]
        assert fake_s3.uploaded == []

    def test_image_without_multiscales_is_an_error(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        root = make_spatialdata(tmp_path, "slide.zarr")
        (root / "images" / "img" / ".zattrs").write_text(json.dumps({"plate": {}}))
        _registered(monkeypatch, root)

        result = process_bioimage_data_collection(self._dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert "multiscales" in result["message"]


class TestSpatialDataV3:
    def _dc(self, **kw) -> SimpleNamespace:
        return _ingest_dc(format="spatialdata", image_path="images/img", **kw)

    def test_v3_root_uploads_only_the_image_subtree(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        _registered(monkeypatch, make_spatialdata_v3(tmp_path, "slide.zarr"))

        result = process_bioimage_data_collection(self._dc(), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success"
        assert sorted(k for k in fake_s3.objects if k != SD_MARKER) == sorted(
            SD_PREFIX + rel for rel in V3_KEYS
        )

    def test_pinned_version_is_checked_on_the_image(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        _registered(monkeypatch, make_spatialdata_v3(tmp_path, "slide.zarr"))

        result = process_bioimage_data_collection(self._dc(ngff_version="0.4"), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert "requires ngff_version 0.4" in result["message"]
        assert fake_s3.uploaded == []

    def test_v2_root_with_v3_image_is_accepted(self, tmp_path):
        root = make_spatialdata(tmp_path, "slide.zarr", images=())
        make_store_v3(root / "images", "img")

        assert deltatables.validate_spatialdata_store(str(root), "images/img") == "0.5"


class TestOmeTiffValidation:
    @pytest.mark.parametrize("bigtiff", [False, True])
    @pytest.mark.parametrize("order", ["<", ">"])
    def test_valid_headers(self, tmp_path, bigtiff, order):
        validate_ome_tiff(str(make_ome_tiff(tmp_path / "a.ome.tif", bigtiff=bigtiff, order=order)))

    def test_short_inline_description_without_ome_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="no OME-XML"):
            validate_ome_tiff(str(make_ome_tiff(tmp_path / "a.ome.tif", description="ab")))

    def test_plain_tiff_description_is_rejected(self, tmp_path):
        path = make_ome_tiff(tmp_path / "a.ome.tif", description="ImageJ=1.54f\nimages=1")
        with pytest.raises(ValueError, match="no OME-XML"):
            validate_ome_tiff(str(path))

    def test_missing_description_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="no ImageDescription"):
            validate_ome_tiff(str(make_ome_tiff(tmp_path / "a.ome.tif", description=None)))

    def test_not_a_tiff(self, tmp_path):
        path = tmp_path / "a.ome.tif"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        with pytest.raises(ValueError, match="not a TIFF"):
            validate_ome_tiff(str(path))

    def test_truncated_ifd(self, tmp_path):
        path = make_ome_tiff(tmp_path / "a.ome.tif")
        path.write_bytes(path.read_bytes()[:12])
        with pytest.raises(ValueError, match="truncated"):
            validate_ome_tiff(str(path))


class TestOmeTiffIngest:
    def test_uploaded_as_one_object_with_a_marker(self, tmp_path, monkeypatch, cli_config, fake_s3):
        tiff = make_ome_tiff(tmp_path / "sample_A.ome.tif")
        _registered(monkeypatch, tiff)

        result = process_bioimage_data_collection(_ingest_dc(format="ome-tiff"), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success"
        assert "1 OME-TIFF store(s)" in result["message"]
        assert fake_s3.uploaded == [TIFF_KEY]
        assert fake_s3.objects[TIFF_KEY] == tiff.read_bytes()
        marker = json.loads(fake_s3.objects[TIFF_MARKER])
        assert marker["objects"] == [TIFF_KEY]
        assert len(marker["hash"]) == 64

    def test_unchanged_is_skipped_changed_and_overwrite_reupload(self, tmp_path):
        tiff = make_ome_tiff(tmp_path / "sample_A.ome.tif")
        s3 = FakeS3()

        assert upload_ome_tiff(s3, BUCKET, DC_ID, str(tiff)) == 1
        assert upload_ome_tiff(s3, BUCKET, DC_ID, str(tiff)) == 0
        assert upload_ome_tiff(s3, BUCKET, DC_ID, str(tiff), force=True) == 1
        tiff.write_bytes(tiff.read_bytes() + b"\x00" * 32)
        assert upload_ome_tiff(s3, BUCKET, DC_ID, str(tiff)) == 1
        assert s3.uploaded == [TIFF_KEY] * 3

    def test_invalid_tiff_fails_before_upload(self, tmp_path, monkeypatch, cli_config, fake_s3):
        _registered(
            monkeypatch,
            make_ome_tiff(tmp_path / "sample_A.ome.tif"),
            make_ome_tiff(tmp_path / "sample_B.ome.tif", description="not ome"),
        )

        result = process_bioimage_data_collection(_ingest_dc(format="ome-tiff"), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert "Invalid OME-TIFF store" in result["message"]
        assert "sample_B.ome.tif" in result["message"]
        assert fake_s3.uploaded == []

    def test_duplicate_names_are_an_error(self, tmp_path, monkeypatch, cli_config, fake_s3):
        a = make_ome_tiff(tmp_path / "run_1" / "sample_A.ome.tif")
        b = make_ome_tiff(tmp_path / "run_2" / "sample_A.ome.tif")
        _registered(monkeypatch, a, b)

        result = process_bioimage_data_collection(_ingest_dc(format="ome-tiff"), cli_config)  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert "OME-TIFF store names must be unique" in result["message"]
        assert fake_s3.uploaded == []

    def test_reference_only_validates_without_upload(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        _registered(monkeypatch, make_ome_tiff(tmp_path / "sample_A.ome.tif"))

        result = process_bioimage_data_collection(
            _ingest_dc(format="ome-tiff", upload=False), cli_config
        )  # type: ignore[arg-type]

        assert result["result"] == "success"
        assert fake_s3.uploaded == []


class TestRemoteStores:
    REMOTE = "https://images.example.org/data/sample_A.zarr"

    def test_remote_only_dc_is_neither_fetched_nor_uploaded(self, monkeypatch, cli_config):
        fetch = MagicMock()
        client = MagicMock()
        monkeypatch.setattr(deltatables, "fetch_file_data", fetch)
        monkeypatch.setattr(deltatables, "_s3_client", client)

        result = process_bioimage_data_collection(
            _ingest_dc(scan=None, remote_stores=[self.REMOTE]), cli_config
        )  # type: ignore[arg-type]

        assert result == {"result": "success", "message": "1 remote store(s), read in place"}
        fetch.assert_not_called()
        client.assert_not_called()

    def test_local_and_remote_stores(self, tmp_path, monkeypatch, cli_config, fake_s3):
        _registered(monkeypatch, make_store(tmp_path, "sample_B.zarr"))

        result = process_bioimage_data_collection(
            _ingest_dc(remote_stores=[self.REMOTE]), cli_config
        )  # type: ignore[arg-type]

        assert result["result"] == "success"
        assert "1 OME-Zarr store(s)" in result["message"]
        assert "1 remote store(s), read in place" in result["message"]

    def test_scan_that_found_nothing_still_serves_remote_stores(self, monkeypatch, cli_config):
        def no_files(dc_id, CLI_config):
            raise Exception("No files found")

        monkeypatch.setattr(deltatables, "fetch_file_data", no_files)

        result = process_bioimage_data_collection(
            _ingest_dc(remote_stores=[self.REMOTE]), cli_config
        )  # type: ignore[arg-type]

        assert result["result"] == "success"

    def test_local_store_named_like_a_remote_one_is_an_error(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        _registered(monkeypatch, make_store(tmp_path, "sample_A.zarr"))

        result = process_bioimage_data_collection(
            _ingest_dc(remote_stores=[self.REMOTE]), cli_config
        )  # type: ignore[arg-type]

        assert result["result"] == "error"
        assert self.REMOTE in result["message"]
        assert fake_s3.uploaded == []
