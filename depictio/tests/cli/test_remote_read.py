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
