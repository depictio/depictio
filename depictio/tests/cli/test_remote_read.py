"""Unit tests for the remote (scan mode "url") read path in deltatables.

Covers the http(s) bounded-download branch against a local in-thread HTTP
server; s3:// branches only assert dispatch behavior (no object store here).
"""

import http.server
import os
import threading

import polars as pl
import pytest

from depictio.cli.cli.utils.deltatables import (
    _download_remote_to_temp,
    _read_remote_file_lazy,
    read_single_file_lazy,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase


@pytest.fixture(autouse=True)
def _remote_env(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
    # The download client honors proxy env vars; a loopback server must not
    # be routed through the sandbox proxy.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def http_fixture_server(tmp_path):
    (tmp_path / "table.csv").write_text("sample,value\nS1,1\nS2,2\n")
    (tmp_path / "table.tsv").write_text("sample\tvalue\nS1\t1\nS2\t2\n")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tmp_path), **kwargs)

        def log_message(self, *args):  # keep test output quiet
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _make_remote_file(url: str) -> File:
    owner = UserBase(id=PyObjectId(), email="test@example.com", is_admin=False)
    return File(
        filename=os.path.basename(url),
        file_location=url,
        creation_time="2026-01-01 00:00:00",
        modification_time="2026-01-01 00:00:00",
        file_hash="a" * 64,
        filesize=-1,
        data_collection_id=PyObjectId(),
        run_id=PyObjectId(),
        run_tag="remote-run",
        permissions=Permission(owners=[owner]),
    )


def test_download_remote_to_temp_roundtrip(http_fixture_server):
    temp_path = _download_remote_to_temp(f"{http_fixture_server}/table.csv")
    try:
        assert temp_path.endswith(".csv")
        assert "sample,value" in open(temp_path).read()
    finally:
        os.unlink(temp_path)


def test_download_remote_cap_enforced(http_fixture_server, monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "5")
    with pytest.raises(ValueError, match="download cap"):
        _download_remote_to_temp(f"{http_fixture_server}/table.csv")


def test_read_remote_csv_lazy(http_fixture_server):
    file_info = _make_remote_file(f"{http_fixture_server}/table.csv")
    lf = read_single_file_lazy(file_info, "csv", {})
    df = lf.collect()
    assert df.shape == (2, 3)  # sample, value + injected depictio_run_id
    assert set(df["depictio_run_id"].to_list()) == {"remote-run"}


def test_read_remote_tsv_separator_inference(http_fixture_server):
    file_info = _make_remote_file(f"{http_fixture_server}/table.tsv")
    df = read_single_file_lazy(file_info, "tsv", {}).collect()
    assert df.columns == ["sample", "value", "depictio_run_id"]


def test_read_remote_temp_file_cleaned(http_fixture_server, tmp_path):
    before = set(os.listdir("/tmp")) if os.path.isdir("/tmp") else set()
    file_info = _make_remote_file(f"{http_fixture_server}/table.csv")
    read_single_file_lazy(file_info, "csv", {}).collect()
    after = set(os.listdir("/tmp")) if os.path.isdir("/tmp") else set()
    leftovers = [f for f in after - before if f.startswith("depictio_remote_")]
    assert leftovers == []


def test_s3_unsupported_format_rejected():
    with pytest.raises(ValueError, match="not supported for s3"):
        _read_remote_file_lazy("s3://bucket/key.xlsx", "xlsx", {}, {})


def test_s3_parquet_dispatches_lazily():
    # No object store in unit tests: the scan must build lazily without
    # touching the network — collection would fail, construction must not.
    lf = _read_remote_file_lazy("s3://bucket/key.parquet", "parquet", {}, {})
    assert isinstance(lf, pl.LazyFrame)


class TestManifestScan:
    """Phase 2: manifest fetch + per-entry File registration + id injection."""

    @pytest.fixture()
    def manifest_file(self, tmp_path, http_fixture_server):
        path = tmp_path / "manifest.csv"
        path.write_text(
            "id,type,url,run\n"
            f"S1,counts,{http_fixture_server}/table.csv,run42\n"
            f"S2,counts,{http_fixture_server}/table.tsv,run42\n"
            f"S1,stats,{http_fixture_server}/table.csv,run42\n"
        )
        return str(path)

    def test_fetch_manifest_local_csv(self, manifest_file):
        from depictio.cli.cli.utils.scan import fetch_manifest

        manifest = fetch_manifest(manifest_file)
        assert manifest.types() == {"counts", "stats"}
        assert len(manifest.entries_for_type("counts")) == 2

    def test_fetch_manifest_over_http(self, tmp_path, http_fixture_server):
        from depictio.cli.cli.utils.scan import fetch_manifest

        (tmp_path / "manifest.json").write_text(
            '[{"id": "S1", "type": "counts", "url": "https://x.org/a.parquet"}]'
        )
        manifest = fetch_manifest(f"{http_fixture_server}/manifest.json")
        assert manifest.entries[0].id == "S1"

    def test_fetch_manifest_s3_rejected(self):
        from depictio.cli.cli.utils.scan import fetch_manifest

        with pytest.raises(ValueError, match="s3://"):
            fetch_manifest("s3://bucket/manifest.csv")

    def test_scan_manifest_registers_files(self, manifest_file, monkeypatch):
        from unittest.mock import MagicMock

        from depictio.cli.cli.utils import scan as scan_mod
        from depictio.models.models.data_collections import (
            DataCollection,
            DataCollectionConfig,
            Scan,
            ScanManifest,
        )
        from depictio.models.models.users import Permission, UserBase
        from depictio.models.models.workflows import (
            Workflow,
            WorkflowConfig,
            WorkflowDataLocation,
            WorkflowEngine,
        )

        dc = DataCollection(
            data_collection_tag="counts",
            config=DataCollectionConfig(
                type="table",
                metatype="aggregate",
                scan=Scan(
                    mode="manifest",
                    scan_parameters=ScanManifest(
                        manifest_url=manifest_file, manifest_type="counts"
                    ),
                ),
                dc_specific_properties={"format": "csv"},
            ),
        )
        workflow = Workflow(
            name="wf",
            workflow_tag="wf",
            engine=WorkflowEngine(name="python"),
            config=WorkflowConfig(),
            data_location=WorkflowDataLocation(structure="flat", locations=["/tmp"]),
            data_collections=[dc],
        )

        no_files = MagicMock(status_code=200)
        no_files.json.return_value = []
        monkeypatch.setattr(scan_mod, "api_get_files_by_dc_id", lambda **_: no_files)
        created = []
        monkeypatch.setattr(
            scan_mod,
            "api_create_files",
            lambda files, CLI_config, update: created.append((list(files), update)),
        )

        owner = UserBase(id=PyObjectId(), email="o@example.com", is_admin=False)
        result = scan_mod.scan_manifest_for_data_collection(
            workflow=workflow,
            data_collection=dc,
            CLI_config=MagicMock(),
            permissions=Permission(owners=[owner]),
            update_files=False,
        )
        assert result == {"result": "success", "added": 2, "updated": 0}
        files, update_flag = created[0]
        assert update_flag is False
        assert {f.manifest_id for f in files} == {"S1", "S2"}
        assert {f.run_tag for f in files} == {"run42"}
        assert all(f.file_location.startswith("http://127.0.0.1") for f in files)

    def test_manifest_type_absent_errors(self, manifest_file, monkeypatch):
        from unittest.mock import MagicMock

        from depictio.cli.cli.utils import scan as scan_mod
        from depictio.models.models.data_collections import (
            DataCollection,
            DataCollectionConfig,
            Scan,
            ScanManifest,
        )
        from depictio.models.models.users import Permission, UserBase
        from depictio.models.models.workflows import (
            Workflow,
            WorkflowConfig,
            WorkflowDataLocation,
            WorkflowEngine,
        )

        dc = DataCollection(
            data_collection_tag="nope",
            config=DataCollectionConfig(
                type="table",
                metatype="aggregate",
                scan=Scan(
                    mode="manifest",
                    scan_parameters=ScanManifest(manifest_url=manifest_file, manifest_type="nope"),
                ),
                dc_specific_properties={"format": "csv"},
            ),
        )
        workflow = Workflow(
            name="wf",
            workflow_tag="wf",
            engine=WorkflowEngine(name="python"),
            config=WorkflowConfig(),
            data_location=WorkflowDataLocation(structure="flat", locations=["/tmp"]),
            data_collections=[dc],
        )
        owner = UserBase(id=PyObjectId(), email="o@example.com", is_admin=False)
        result = scan_mod.scan_manifest_for_data_collection(
            workflow=workflow,
            data_collection=dc,
            CLI_config=MagicMock(),
            permissions=Permission(owners=[owner]),
            update_files=False,
        )
        assert result["result"] == "error"
        assert "counts" in result["message"]  # available types listed


def test_manifest_id_column_injected(http_fixture_server):
    file_info = _make_remote_file(f"{http_fixture_server}/table.csv")
    file_info.manifest_id = "S1"
    df = read_single_file_lazy(file_info, "csv", {}).collect()
    assert df["depictio_manifest_id"].to_list() == ["S1", "S1"]
    assert set(df["depictio_run_id"].to_list()) == {"remote-run"}
