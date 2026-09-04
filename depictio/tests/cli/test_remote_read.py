"""Unit tests for the remote (scan mode "url") read path in deltatables.

Covers the http(s) bounded-download branch against a local in-thread HTTP
server; s3:// branches only assert dispatch behavior (no object store here).

Context matters: the CLI reads loopback directly (the user's own machine),
while the API process and the Celery worker route every read through the SSRF
gateway. The autouse fixture pins ``DEPICTIO_CONTEXT=CLI``; server-context
tests flip it explicitly.
"""

import http.server
import logging
import os
import threading

import httpx
import polars as pl
import pytest

from depictio.api.v1.remote_fetch import RemoteURLRejected
from depictio.cli.cli.utils.deltatables import (
    _download_remote_to_temp,
    _read_remote_file_lazy,
    read_single_file_lazy,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase
from depictio.tests.cli.s3_stubs import install_s3_listing


@pytest.fixture(autouse=True)
def _remote_env(monkeypatch):
    # The shared conftest pins DEPICTIO_CONTEXT=server for the whole session;
    # these tests exercise the CLI's direct read path unless they say otherwise.
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
    for var in (
        "DEPICTIO_REMOTE_URL_ALLOWLIST",
        "DEPICTIO_REMOTE_URL_DENYLIST",
        "DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES",
        "DEPICTIO_REMOTE_MAX_REDIRECTS",
        "DEPICTIO_REMOTE_TIMEOUT_S",
    ):
        monkeypatch.delenv(var, raising=False)
    # The download client honors proxy env vars; a loopback server must not
    # be routed through the sandbox proxy.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def server_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")


@pytest.fixture()
def allowlisted_loopback(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "127.0.0.1")


@pytest.fixture()
def http_fixture_server(tmp_path):
    (tmp_path / "table.csv").write_text("sample,value\nS1,1\nS2,2\n")
    (tmp_path / "table.tsv").write_text("sample\tvalue\nS1\t1\nS2\t2\n")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tmp_path), **kwargs)

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def do_GET(self):  # noqa: N802 (http.server API)
            if self.path == "/redirect-table":
                self._redirect("/table.csv")
            elif self.path == "/redirect-unlisted":
                # Same server, different host name: passes nothing in an
                # allowlist that only names 127.0.0.1.
                self._redirect(f"http://localhost:{self.server.server_address[1]}/table.csv")
            else:
                super().do_GET()

        def log_message(self, *args):  # keep test output quiet
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(autouse=True)
def _isolated_tempdir(monkeypatch, tmp_path):
    """Give every test its own temp directory.

    The leftover-file assertions list ``depictio_remote_*`` entries in the
    temp dir; under xdist another worker's in-flight download would show up
    there and fail the check, so the module never shares the system one.
    """
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def _leftover_temp_files() -> list[str]:
    import tempfile

    return [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("depictio_remote_")]


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
    before = set(_leftover_temp_files())
    with pytest.raises(ValueError, match="download cap"):
        _download_remote_to_temp(f"{http_fixture_server}/table.csv")
    assert set(_leftover_temp_files()) == before


def test_download_cli_context_follows_redirect(http_fixture_server):
    temp_path = _download_remote_to_temp(f"{http_fixture_server}/redirect-table")
    try:
        assert "sample,value" in open(temp_path).read()
    finally:
        os.unlink(temp_path)


def test_download_cli_context_caps_redirects(http_fixture_server, monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_MAX_REDIRECTS", "0")
    before = set(_leftover_temp_files())
    with pytest.raises(httpx.TooManyRedirects):
        _download_remote_to_temp(f"{http_fixture_server}/redirect-table")
    assert set(_leftover_temp_files()) == before


class TestDownloadServerContext:
    """The API/worker path: every data-file URL goes through the gateway."""

    def test_refuses_loopback(self, server_context, http_fixture_server):
        before = set(_leftover_temp_files())
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            _download_remote_to_temp(f"{http_fixture_server}/table.csv")
        assert set(_leftover_temp_files()) == before

    def test_refuses_redirect_to_unlisted_host(
        self, server_context, allowlisted_loopback, http_fixture_server
    ):
        with pytest.raises(RemoteURLRejected, match="not in the administrator allowlist"):
            _download_remote_to_temp(f"{http_fixture_server}/redirect-unlisted")

    def test_refuses_http_when_not_allowed(self, server_context, http_fixture_server, monkeypatch):
        monkeypatch.delenv("DEPICTIO_REMOTE_ALLOW_HTTP", raising=False)
        with pytest.raises(RemoteURLRejected, match="scheme not allowed"):
            _download_remote_to_temp(f"{http_fixture_server}/table.csv")

    def test_allowlisted_roundtrip_keeps_extension(
        self, server_context, allowlisted_loopback, http_fixture_server
    ):
        temp_path = _download_remote_to_temp(f"{http_fixture_server}/table.tsv")
        try:
            assert temp_path.endswith(".tsv")
            assert "sample\tvalue" in open(temp_path).read()
        finally:
            os.unlink(temp_path)

    def test_allowlisted_follows_same_host_redirect(
        self, server_context, allowlisted_loopback, http_fixture_server
    ):
        temp_path = _download_remote_to_temp(f"{http_fixture_server}/redirect-table")
        try:
            assert "sample,value" in open(temp_path).read()
        finally:
            os.unlink(temp_path)

    def test_cap_enforced(
        self, server_context, allowlisted_loopback, http_fixture_server, monkeypatch
    ):
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "5")
        before = set(_leftover_temp_files())
        with pytest.raises(ValueError, match="download cap"):
            _download_remote_to_temp(f"{http_fixture_server}/table.csv")
        assert set(_leftover_temp_files()) == before

    def test_read_single_file_lazy_surfaces_rejection(self, server_context, http_fixture_server):
        file_info = _make_remote_file(f"{http_fixture_server}/table.csv")
        with pytest.raises(Exception, match="non-public address"):
            read_single_file_lazy(file_info, "csv", {})


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
    before = set(_leftover_temp_files())
    file_info = _make_remote_file(f"{http_fixture_server}/table.csv")
    read_single_file_lazy(file_info, "csv", {}).collect()
    assert set(_leftover_temp_files()) == before


def test_s3_unsupported_format_rejected():
    with pytest.raises(ValueError, match="not supported for s3"):
        _read_remote_file_lazy("s3://bucket/key.xlsx", "xlsx", {}, {})


def test_s3_parquet_dispatches_lazily():
    # No object store in unit tests: the scan must build lazily without
    # touching the network — collection would fail, construction must not.
    lf = _read_remote_file_lazy("s3://bucket/key.parquet", "parquet", {}, {})
    assert isinstance(lf, pl.LazyFrame)


class TestPublicBucketReads:
    """Which storage options a remote read ends up using.

    Asserted on the options handed to polars rather than on a real read: there
    is no object store here, and the decision is the whole behaviour.
    """

    @pytest.fixture
    def captured_scan(self, monkeypatch):
        captured: dict = {}

        def fake_scan_parquet(url, storage_options=None, **kwargs):
            captured["url"] = url
            captured["storage_options"] = storage_options
            return pl.LazyFrame()

        monkeypatch.setattr(pl, "scan_parquet", fake_scan_parquet)
        return captured

    def test_an_allowlisted_bucket_is_read_unsigned(self, captured_scan, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        _read_remote_file_lazy(
            "s3://open-data/x.parquet", "parquet", {}, {"aws_access_key_id": "k"}
        )

        assert captured_scan["storage_options"]["aws_skip_signature"] == "true"
        assert "aws_access_key_id" not in captured_scan["storage_options"]

    def test_an_unlisted_bucket_keeps_the_configured_credentials(self, captured_scan, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        _read_remote_file_lazy(
            "s3://private-data/x.parquet", "parquet", {}, {"aws_access_key_id": "k"}
        )

        assert captured_scan["storage_options"] == {"aws_access_key_id": "k"}

    def test_a_prefix_entry_does_not_open_the_whole_bucket(self, captured_scan, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "shared/public")

        _read_remote_file_lazy(
            "s3://shared/private/x.parquet", "parquet", {}, {"aws_access_key_id": "k"}
        )

        assert captured_scan["storage_options"] == {"aws_access_key_id": "k"}


class TestProbeUrlMetadata:
    """HEAD probe feeding the url-mode identity hash."""

    def test_cli_success(self, http_fixture_server):
        from depictio.cli.cli.utils.scan import _probe_url_metadata

        metadata = _probe_url_metadata(f"{http_fixture_server}/table.csv")
        assert metadata["size"] == len("sample,value\nS1,1\nS2,2\n")
        # SimpleHTTPRequestHandler sends no ETag: a successful probe still
        # reports a string, never None.
        assert metadata["etag"] == ""

    def test_s3_returns_unknowns(self):
        from depictio.cli.cli.utils.scan import _probe_url_metadata

        assert _probe_url_metadata("s3://bucket/key.parquet") == {"size": -1, "etag": ""}

    def test_cli_failure_is_visible(self, caplog):
        from depictio.cli.cli.utils.scan import _probe_url_metadata

        with caplog.at_level(logging.WARNING, logger="depictio-cli"):
            metadata = _probe_url_metadata("http://127.0.0.1:1/table.csv")
        assert metadata == {"size": -1, "etag": None}
        assert any("Could not probe" in rec.message for rec in caplog.records)

    def test_server_success_through_gateway(
        self, server_context, allowlisted_loopback, http_fixture_server
    ):
        from depictio.cli.cli.utils.scan import _probe_url_metadata

        metadata = _probe_url_metadata(f"{http_fixture_server}/table.csv")
        assert metadata["size"] == len("sample,value\nS1,1\nS2,2\n")
        assert metadata["etag"] == ""

    def test_server_policy_rejection_propagates(self, server_context, http_fixture_server):
        from depictio.cli.cli.utils.scan import _probe_url_metadata

        with pytest.raises(RemoteURLRejected, match="non-public address"):
            _probe_url_metadata(f"{http_fixture_server}/table.csv")

    def test_server_unreachable_degrades(self, server_context, allowlisted_loopback, caplog):
        from depictio.cli.cli.utils.scan import _probe_url_metadata

        with caplog.at_level(logging.WARNING, logger="depictio-cli"):
            metadata = _probe_url_metadata("http://127.0.0.1:1/table.csv")
        assert metadata == {"size": -1, "etag": None}
        assert any("Could not probe" in rec.message for rec in caplog.records)

    def test_identity_hash_fallback_is_distinct_and_logged(self, caplog):
        from depictio.cli.cli.utils.scan import _url_identity_hash

        url = "https://example.org/data.csv"
        probed = _url_identity_hash(url, {"size": 10, "etag": ""})
        with caplog.at_level(logging.WARNING, logger="depictio-cli"):
            fallback = _url_identity_hash(url, {"size": -1, "etag": None})
        assert probed != fallback
        assert any("falls back to URL + size" in rec.message for rec in caplog.records)
        # Successful probes keep the historical url|etag hash.
        import hashlib

        assert _url_identity_hash(url, {"size": 10, "etag": '"e1"'}) == (
            hashlib.sha256(f'{url}|"e1"'.encode()).hexdigest()
        )


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

    @pytest.fixture()
    def manifest_json(self, tmp_path):
        (tmp_path / "manifest.json").write_text(
            '[{"id": "S1", "type": "counts", "url": "https://x.org/a.parquet"}]'
        )

    def test_fetch_manifest_local_csv(self, manifest_file):
        from depictio.cli.cli.utils.scan import fetch_manifest

        manifest = fetch_manifest(manifest_file)
        assert manifest.types() == {"counts", "stats"}
        assert len(manifest.entries_for_type("counts")) == 2

    def test_fetch_manifest_over_http(self, manifest_json, http_fixture_server):
        from depictio.cli.cli.utils.scan import fetch_manifest

        manifest = fetch_manifest(f"{http_fixture_server}/manifest.json")
        assert manifest.entries[0].id == "S1"

    def test_fetch_manifest_cli_cap_enforced(self, manifest_json, http_fixture_server, monkeypatch):
        from depictio.cli.cli.utils.scan import fetch_manifest

        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "5")
        with pytest.raises(ValueError, match="download cap"):
            fetch_manifest(f"{http_fixture_server}/manifest.json")

    def test_fetch_manifest_server_context_refuses_loopback(
        self, server_context, manifest_json, http_fixture_server
    ):
        from depictio.cli.cli.utils.scan import fetch_manifest

        with pytest.raises(RemoteURLRejected, match="non-public address"):
            fetch_manifest(f"{http_fixture_server}/manifest.json")

    def test_fetch_manifest_server_context_refuses_redirect(
        self, server_context, allowlisted_loopback, http_fixture_server
    ):
        from depictio.cli.cli.utils.scan import fetch_manifest

        with pytest.raises(RemoteURLRejected, match="not in the administrator allowlist"):
            fetch_manifest(f"{http_fixture_server}/redirect-unlisted")

    def test_fetch_manifest_server_context_allowlisted(
        self, server_context, allowlisted_loopback, manifest_json, http_fixture_server
    ):
        from depictio.cli.cli.utils.scan import fetch_manifest

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

    def test_scan_manifest_warns_when_existing_files_lookup_fails(
        self, manifest_file, monkeypatch, caplog
    ):
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
        failed = MagicMock(status_code=500)
        monkeypatch.setattr(scan_mod, "api_get_files_by_dc_id", lambda **_: failed)
        monkeypatch.setattr(scan_mod, "api_create_files", lambda files, CLI_config, update: None)
        owner = UserBase(id=PyObjectId(), email="o@example.com", is_admin=False)
        with caplog.at_level(logging.WARNING, logger="depictio-cli"):
            result = scan_mod.scan_manifest_for_data_collection(
                workflow=workflow,
                data_collection=dc,
                CLI_config=MagicMock(),
                permissions=Permission(owners=[owner]),
                update_files=False,
            )
        assert result["result"] == "success"
        assert any("Failed to retrieve existing files" in rec.message for rec in caplog.records)

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


class TestUrlScan:
    """scan mode "url": one synthesized File per DC, keyed by the remote URL."""

    @staticmethod
    def _dc_and_workflow(url: str):
        from depictio.models.models.data_collections import (
            DataCollection,
            DataCollectionConfig,
            Scan,
            ScanURL,
        )
        from depictio.models.models.workflows import (
            Workflow,
            WorkflowConfig,
            WorkflowDataLocation,
            WorkflowEngine,
        )

        dc = DataCollection(
            data_collection_tag="remote",
            config=DataCollectionConfig(
                type="table",
                metatype="aggregate",
                scan=Scan(mode="url", scan_parameters=ScanURL(url=url)),
                dc_specific_properties={"format": "csv"},
            ),
        )
        workflow = Workflow(
            name="wf",
            workflow_tag="wf",
            engine=WorkflowEngine(name="python"),
            config=WorkflowConfig(),
            data_location=WorkflowDataLocation(structure="flat", locations=[url]),
            data_collections=[dc],
        )
        return dc, workflow

    @pytest.fixture()
    def api(self, monkeypatch):
        """Stub the API round-trips the scan makes.

        ``existing`` and ``status`` shape the existing-files lookup;
        ``created`` records ``(files, update)`` per registration call and
        ``deleted`` the ids of stale records the scan removed.
        """
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from depictio.cli.cli.utils import scan as scan_mod

        recorder = SimpleNamespace(existing=[], status=200, created=[], deleted=[])

        def _lookup(**_):
            response = MagicMock(status_code=recorder.status)
            response.json.return_value = recorder.existing
            return response

        monkeypatch.setattr(scan_mod, "api_get_files_by_dc_id", _lookup)
        monkeypatch.setattr(
            scan_mod,
            "api_create_files",
            lambda files, CLI_config, update: recorder.created.append((list(files), update)),
        )
        monkeypatch.setattr(
            scan_mod,
            "api_delete_file",
            lambda file_id, CLI_config: recorder.deleted.append(file_id),
        )
        return recorder

    def _scan(self, url: str, update_files: bool = False):
        from unittest.mock import MagicMock

        from depictio.cli.cli.utils.scan import scan_url_for_data_collection

        dc, workflow = self._dc_and_workflow(url)
        owner = UserBase(id=PyObjectId(), email="o@example.com", is_admin=False)
        result = scan_url_for_data_collection(
            workflow=workflow,
            data_collection=dc,
            CLI_config=MagicMock(),
            permissions=Permission(owners=[owner]),
            update_files=update_files,
        )
        return result, dc

    @staticmethod
    def _identity_hash(url: str, etag: str = "") -> str:
        import hashlib

        return hashlib.sha256(f"{url}|{etag}".encode()).hexdigest()

    @staticmethod
    def _existing(url: str, file_hash: str) -> dict:
        from bson import ObjectId

        return {"_id": str(ObjectId()), "file_location": url, "file_hash": file_hash}

    def test_registers_the_url_as_one_file(self, api, http_fixture_server):
        url = f"{http_fixture_server}/table.csv"

        result, dc = self._scan(url)

        assert result == {"result": "success"}
        ((files, update),) = api.created
        assert update is False
        (file,) = files
        assert file.file_location == url
        assert file.filename == "table.csv"
        assert file.filesize == len("sample,value\nS1,1\nS2,2\n")  # from the HEAD probe
        # The fixture server sends no ETag: the identity hash is url + "".
        assert file.file_hash == self._identity_hash(url)
        assert file.data_collection_id == dc.id
        assert file.run_tag == "remote-url-scan"
        assert api.deleted == []

    def test_unchanged_url_is_skipped(self, api, http_fixture_server):
        url = f"{http_fixture_server}/table.csv"
        api.existing = [self._existing(url, self._identity_hash(url))]

        result, _ = self._scan(url)

        assert result == {"result": "success"}
        assert api.created == []
        assert api.deleted == []

    def test_update_files_re_registers_an_unchanged_url_under_its_existing_id(
        self, api, http_fixture_server
    ):
        url = f"{http_fixture_server}/table.csv"
        known = self._existing(url, self._identity_hash(url))
        api.existing = [known]

        self._scan(url, update_files=True)

        ((files, update),) = api.created
        assert update is True
        assert str(files[0].id) == known["_id"]

    def test_changed_remote_content_is_registered_as_an_update(self, api, http_fixture_server):
        url = f"{http_fixture_server}/table.csv"
        known = self._existing(url, "0" * 64)  # hash recorded before the content changed
        api.existing = [known]

        self._scan(url)

        ((files, update),) = api.created
        assert update is True
        assert str(files[0].id) == known["_id"]
        assert files[0].file_hash == self._identity_hash(url)

    def test_repointed_dc_drops_the_stale_record(self, api, http_fixture_server):
        old_url = f"{http_fixture_server}/table.tsv"
        new_url = f"{http_fixture_server}/table.csv"
        stale = self._existing(old_url, self._identity_hash(old_url))
        api.existing = [stale]

        self._scan(new_url)

        assert api.deleted == [stale["_id"]]
        ((files, update),) = api.created
        assert update is False
        assert files[0].file_location == new_url

    def test_unreachable_url_is_registered_with_the_size_fallback_hash(self, api, caplog):
        import hashlib

        url = "http://127.0.0.1:1/data.csv"

        with caplog.at_level(logging.WARNING, logger="depictio-cli"):
            result, _ = self._scan(url)

        assert result == {"result": "success"}
        ((files, _),) = api.created
        assert files[0].filesize == -1
        # Failed probe: the weaker url + size hash, and it says so.
        assert files[0].file_hash == hashlib.sha256(f"{url}|size=-1".encode()).hexdigest()
        assert any("Could not probe" in rec.message for rec in caplog.records)
        assert any("falls back to URL + size" in rec.message for rec in caplog.records)

    def test_lookup_failure_warns_and_still_registers(self, api, http_fixture_server, caplog):
        url = f"{http_fixture_server}/table.csv"
        api.status = 500

        with caplog.at_level(logging.WARNING, logger="depictio-cli"):
            result, _ = self._scan(url)

        assert result == {"result": "success"}
        assert any("Failed to retrieve existing files" in rec.message for rec in caplog.records)
        ((files, update),) = api.created
        assert update is False
        assert files[0].file_location == url

    def test_url_without_a_basename_gets_a_placeholder_filename(self, api, http_fixture_server):
        self._scan(f"{http_fixture_server}/")

        ((files, _),) = api.created
        assert files[0].filename == "remote-file"


class TestRecipeSourcesOnS3:
    """``resolve_sources`` against an ``s3://`` data root.

    20 of nf-core/ampliseq's 25 data collections are recipe DCs, so a template
    pointed at an S3 prefix is mostly recipe reads. The listing is stubbed the
    way ``test_data_root.py`` stubs it and the polars calls are captured, so
    nothing here touches the network: what is asserted is which object each
    source resolved to and which storage options the read was handed.
    """

    BUCKET = "nf-core-awsmegatests"
    PREFIX = "ampliseq/results/"
    ROOT = f"s3://{BUCKET}/{PREFIX.rstrip('/')}"

    TREE = [
        "qiime2/barplot/level-3.csv",
        "qiime2/barplot/level-4.csv",
        "qiime2/rel_abundance_tables/rel-table-ASV.tsv",
        "logs/nextflow.log",
        "run_1/qiime2/barplot/level-3.csv",
        "run_2/qiime2/barplot/level-3.csv",
    ]

    @pytest.fixture
    def stub_listing(self, monkeypatch):
        """Serve ``TREE`` as an S3 listing under this class's prefix."""
        install_s3_listing(monkeypatch, dict.fromkeys(self.TREE, b"x" * 10), self.PREFIX)

    @pytest.fixture
    def public_bucket(self, monkeypatch):
        """Allowlist the bucket, which is how a public results prefix is read."""
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", self.BUCKET)

    @pytest.fixture
    def root(self, stub_listing, public_bucket):
        from depictio.cli.cli.utils.data_root import data_root_for

        return data_root_for(self.ROOT, None)

    @pytest.fixture
    def reads(self, monkeypatch):
        """Capture which polars reader ran, and answer it with a one-row frame.

        A remote read must use the *lazy* readers. The eager ones route an
        ``s3://`` path through fsspec/s3fs, which does not understand
        object_store options: ``pl.read_csv(url, storage_options={
        'aws_skip_signature': 'true'})`` dies with ``AioSession.__init__() got
        an unexpected keyword argument``, while ``pl.scan_csv`` on the same
        arguments reads the object. So the eager readers are stubbed to fail
        here: asserting that storage options were handed to *something* is
        weaker than pinning which reader they were handed to.

        The frame carries the location it was asked for, so a test can assert
        which object a source resolved to without reading anything.
        """
        calls: list[dict] = []

        def _scan(reader: str):
            def _fake(location, **kwargs):
                calls.append({"reader": reader, "location": location, **kwargs})
                return pl.DataFrame({"src": [str(location)]}).lazy()

            return _fake

        def _eager_is_a_bug(location, **kwargs):
            raise AssertionError(
                f"remote read of {location} used an eager polars reader; "
                "s3fs cannot take object_store storage options"
            )

        monkeypatch.setattr(pl, "scan_csv", _scan("scan_csv"))
        monkeypatch.setattr(pl, "scan_parquet", _scan("scan_parquet"))
        monkeypatch.setattr(pl, "read_csv", _eager_is_a_bug)
        monkeypatch.setattr(pl, "read_parquet", _eager_is_a_bug)
        return calls

    @staticmethod
    def _module(sources):
        from types import ModuleType
        from unittest.mock import MagicMock

        module = MagicMock(spec=ModuleType)
        module.SOURCES = sources
        module.EXPECTED_SCHEMA = {}
        return module

    def test_a_path_source_resolves_to_the_full_object_url(self, root, reads):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        module = self._module(
            [RecipeSource(ref="barplot", path="qiime2/barplot/level-3.csv", format="csv")]
        )
        sources = resolve_sources(module, root)

        assert sources["barplot"]["src"].to_list() == [f"{self.ROOT}/qiime2/barplot/level-3.csv"]

    def test_a_glob_source_concatenates_every_matching_object(self, root, reads):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        module = self._module(
            [RecipeSource(ref="levels", glob_pattern="qiime2/barplot/level-*.csv", format="csv")]
        )
        sources = resolve_sources(module, root)

        assert sources["levels"]["src"].to_list() == [
            f"{self.ROOT}/qiime2/barplot/level-3.csv",
            f"{self.ROOT}/qiime2/barplot/level-4.csv",
        ]

    def test_a_source_override_repoints_the_object(self, root, reads):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        module = self._module(
            [RecipeSource(ref="barplot", path="qiime2/barplot/level-3.csv", format="csv")]
        )
        sources = resolve_sources(module, root, overrides={"barplot": "qiime2/barplot/level-4.csv"})

        assert sources["barplot"]["src"].to_list() == [f"{self.ROOT}/qiime2/barplot/level-4.csv"]

    def test_an_absent_optional_source_passes_none_through(self, root, reads):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        module = self._module(
            [RecipeSource(ref="maybe", path="qiime2/absent.csv", format="csv", optional=True)]
        )
        sources = resolve_sources(module, root)

        assert sources["maybe"] is None
        assert reads == []

    def test_a_missing_required_source_names_the_s3_url(self, root, reads):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import RecipeError, resolve_sources

        module = self._module([RecipeSource(ref="barplot", path="qiime2/absent.csv", format="csv")])
        with pytest.raises(RecipeError) as excinfo:
            resolve_sources(module, root)

        # The bare relative fragment would be useless in a CLI log: the reader
        # needs to see the bucket and prefix that were actually consulted.
        assert f"{self.ROOT}/qiime2/absent.csv" in str(excinfo.value)

    def test_a_glob_that_matches_nothing_names_the_root(self, root, reads):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import RecipeError, resolve_sources

        module = self._module(
            [RecipeSource(ref="levels", glob_pattern="qiime2/absent/*.csv", format="csv")]
        )
        with pytest.raises(RecipeError, match="no files matched glob"):
            resolve_sources(module, root)

    def test_every_remote_read_is_handed_the_roots_storage_options(self, root, reads):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        module = self._module(
            [
                RecipeSource(ref="barplot", path="qiime2/barplot/level-3.csv", format="csv"),
                RecipeSource(ref="levels", glob_pattern="qiime2/barplot/level-*.csv", format="csv"),
                RecipeSource(
                    ref="rel", path="qiime2/rel_abundance_tables/rel-table-ASV.tsv", format="tsv"
                ),
            ]
        )
        resolve_sources(module, root)

        assert reads, "no read was captured"
        for call in reads:
            assert call["storage_options"] == root.storage_options()
            assert call["storage_options"]["aws_skip_signature"] == "true"
        # The tsv source keeps its separator alongside the storage options.
        tsv_call = next(c for c in reads if c["location"].endswith(".tsv"))
        assert tsv_call["separator"] == "\t"

    def test_remote_csv_and_tsv_go_through_the_lazy_reader(self, root, reads):
        """``aws_skip_signature`` is an object_store option, so scan, not read.

        The eager readers hand an ``s3://`` path to s3fs, which rejects the
        option outright. Only the native scanners take it, so the reader that
        runs is the whole behaviour and is asserted by name.
        """
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        module = self._module(
            [
                RecipeSource(ref="barplot", path="qiime2/barplot/level-3.csv", format="csv"),
                RecipeSource(
                    ref="rel", path="qiime2/rel_abundance_tables/rel-table-ASV.tsv", format="tsv"
                ),
            ]
        )
        resolve_sources(module, root)

        assert [call["reader"] for call in reads] == ["scan_csv", "scan_csv"]

    def test_remote_parquet_goes_through_the_lazy_reader(self, root, reads, monkeypatch):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import _read_source_file

        _read_source_file(
            root.url("qiime2/barplot/level-3.csv"),
            RecipeSource(ref="p", path="qiime2/barplot/level-3.csv", format="parquet"),
            root.storage_options(),
        )

        assert [call["reader"] for call in reads] == ["scan_parquet"]
        assert reads[0]["storage_options"] == root.storage_options()

    def test_read_kwargs_survive_the_move_to_the_scanner(self, root, reads):
        """A recipe's ``read_kwargs`` still reach polars on the remote path.

        ``skip_rows`` is the one the qiime2 recipes lean on hardest (the
        barplot exports carry a preamble line), so a scanner that silently
        dropped it would corrupt every taxonomy DC rather than fail.
        """
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        module = self._module(
            [
                RecipeSource(
                    ref="barplot",
                    path="qiime2/barplot/level-3.csv",
                    format="csv",
                    read_kwargs={"skip_rows": 1},
                )
            ]
        )
        resolve_sources(module, root)

        (call,) = reads
        assert call["reader"] == "scan_csv"
        assert call["skip_rows"] == 1


class TestSequencingRunsOnS3:
    """The ``sequencing-runs`` recipe branch, scoped without re-listing.

    ``process_recipe_data_collection`` builds its per-run roots as
    ``[base_root.scoped(run) for run in base_root.runs(runs_regex)]``; that
    expression is what is exercised here, since the surrounding function also
    writes Delta tables and talks to the API.
    """

    BUCKET = "nf-core-awsmegatests"
    PREFIX = "ampliseq/results/"
    ROOT = f"s3://{BUCKET}/{PREFIX.rstrip('/')}"

    TREE = [
        "logs/nextflow.log",
        "run_1/qiime2/barplot/level-3.csv",
        "run_1/qiime2/barplot/level-4.csv",
        "run_2/qiime2/barplot/level-3.csv",
    ]

    @pytest.fixture
    def base_root(self, monkeypatch):
        from depictio.cli.cli.utils.data_root import data_root_for

        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", self.BUCKET)
        install_s3_listing(monkeypatch, dict.fromkeys(self.TREE, b"x" * 10), self.PREFIX)
        return data_root_for(self.ROOT, None)

    @staticmethod
    def _run_roots(base_root, runs_regex):
        return [base_root.scoped(run) for run in base_root.runs(runs_regex)]

    def test_one_scoped_root_per_matching_run(self, base_root):
        roots = self._run_roots(base_root, "run_")

        # logs/ is a first-level directory too, and must not read as a run.
        assert [root.name for root in roots] == ["run_1", "run_2"]
        assert [root.location for root in roots] == [
            f"{self.ROOT}/run_1",
            f"{self.ROOT}/run_2",
        ]

    def test_a_non_matching_directory_yields_no_run(self, base_root):
        assert self._run_roots(base_root, "sample_") == []

    def test_a_scoped_root_answers_relative_to_its_run(self, base_root):
        run_1, run_2 = self._run_roots(base_root, "run_")

        assert run_1.exists("qiime2/barplot/level-3.csv") is True
        assert run_1.url("qiime2/barplot/level-3.csv") == (
            f"{self.ROOT}/run_1/qiime2/barplot/level-3.csv"
        )
        assert run_1.glob("qiime2/barplot/*.csv") == [
            "qiime2/barplot/level-3.csv",
            "qiime2/barplot/level-4.csv",
        ]
        # run_2 has only level-3: a scoped root must not see its sibling's files.
        assert run_2.glob("qiime2/barplot/*.csv") == ["qiime2/barplot/level-3.csv"]
        assert run_2.exists("qiime2/barplot/level-4.csv") is False

    def test_a_scoped_root_inherits_the_parents_storage_options(self, base_root):
        (run_1, _) = self._run_roots(base_root, "run_")
        assert run_1.storage_options() == base_root.storage_options()
        assert run_1.is_remote is True

    def test_a_recipe_reads_each_run_separately(self, base_root, monkeypatch):
        from depictio.models.models.transforms import RecipeSource
        from depictio.recipes import resolve_sources

        def _fake_scan(location, **kwargs):
            return pl.DataFrame({"src": [str(location)]}).lazy()

        def _eager_is_a_bug(location, **kwargs):
            raise AssertionError(f"remote read of {location} used an eager polars reader")

        monkeypatch.setattr(pl, "scan_csv", _fake_scan)
        monkeypatch.setattr(pl, "read_csv", _eager_is_a_bug)

        from types import ModuleType
        from unittest.mock import MagicMock

        module = MagicMock(spec=ModuleType)
        module.SOURCES = [
            RecipeSource(ref="barplot", path="qiime2/barplot/level-3.csv", format="csv")
        ]
        module.EXPECTED_SCHEMA = {}

        resolved = [
            resolve_sources(module, run_root)["barplot"]["src"].to_list()[0]
            for run_root in self._run_roots(base_root, "run_")
        ]
        assert resolved == [
            f"{self.ROOT}/run_1/qiime2/barplot/level-3.csv",
            f"{self.ROOT}/run_2/qiime2/barplot/level-3.csv",
        ]
