"""MultiQC reports registered at ``s3://`` locations, as an ``s3_prefix`` scan leaves them.

The processor parses, hashes, uploads and prerenders from a file on disk, so
each ``s3://`` report is fetched once to a temporary copy, read with the target
the configuration resolves for its URL (here: an allowlisted public bucket in
server context, the worker's own case). The report keeps its URL: the
duplicate check and ``original_file_path`` are keyed by it, so a re-ingest
dedupes per report, as it does for a local path.

No network: the S3 reads go through the shared stub client
(``depictio/tests/cli/s3_stubs.py``), whose key list *is* the bucket, and the
API calls are patched at the processor's seams.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from depictio.cli.cli.utils import api_calls, deltatables
from depictio.cli.cli.utils import multiqc_processor as mp
from depictio.models import s3_utils
from depictio.tests.cli.s3_stubs import StubS3Client, install_s3_client, s3_client_error

BUCKET = "nf-core-awsmegatests"
PREFIX = "ampliseq/results-runs"
REPORT_KEY = "multiqc/multiqc_data/multiqc.parquet"
DC_ID = "507f1f77bcf86cd799439012"
DC_TAG = "multiqc_data"

# The live run's own report, small enough to parse for real.
FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "projects/nf-core/ampliseq/2.18.0/multiqc/multiqc_data/multiqc.parquet"
)


def _key(run: str) -> str:
    return f"{PREFIX}/{run}/{REPORT_KEY}"


def _url(run: str, bucket: str = BUCKET) -> str:
    return f"s3://{bucket}/{_key(run)}"


class _Client(StubS3Client):
    """The stub bucket, with some keys answering ``GetObject`` with AccessDenied."""

    def __init__(self, bodies: dict[str, bytes], denied: frozenset[str] = frozenset()):
        super().__init__(bodies)
        self.denied = denied

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3's own spelling
        if Key in self.denied or Key not in self.bodies:
            self.get_object_calls.append(Key)
            if Key in self.denied:
                raise s3_client_error("AccessDenied", 403, "GetObject")
            raise s3_client_error("NoSuchKey", 404, "GetObject")
        return super().get_object(Bucket, Key)


class _InstanceBucket:
    """The instance's own bucket: records what was uploaded, read at upload time."""

    def __init__(self):
        self.uploads: dict[str, dict] = {}

    def upload_file(self, path, bucket, key, Config=None):  # noqa: N803
        self.uploads[key] = {"path": path, "body": Path(path).read_bytes()}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.uploads[Key] = {"path": Body.name, "body": Body.read()}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    # Server context, as in the Celery worker: only an allowlisted bucket is read.
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", BUCKET)
    for var in (
        "DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS",
        "DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES",
        "DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS",
        "DEPICTIO_INGEST_MULTIQC_PRERENDER",
    ):
        monkeypatch.delenv(var, raising=False)
    # No region lookup goes out: the resolved target is kept as it is.
    monkeypatch.setattr(mp, "ensure_region", lambda target: target)
    # A temp dir of the test's own, so what is left behind can be listed.
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp_root))
    return temp_root


@pytest.fixture()
def ingest(monkeypatch, _env):
    """Run the processor over ``files``; returns what it said and did."""

    def _run(files, bodies, *, denied=frozenset(), existing=None, overwrite=False):
        client = install_s3_client(monkeypatch, _Client(bodies, frozenset(denied)))
        instance = _InstanceBucket()
        said: list[tuple[str, str]] = []
        duplicate_checks: list[str] = []
        created: list[dict] = []
        updated: list[tuple[str, dict]] = []

        def _check_duplicate(_dc_id, original_file_path, _config):
            duplicate_checks.append(original_file_path)
            return (existing or {}).get(original_file_path)

        def _create(report_data, _config):
            created.append(report_data)
            response = MagicMock(status_code=200)
            response.json.return_value = {"report": {"id": f"report-{len(created)}"}}
            return response

        def _update(report_id, report_data, _config):
            updated.append((report_id, report_data))
            return MagicMock(status_code=200)

        monkeypatch.setattr(deltatables, "fetch_file_data", lambda _dc_id, _config: files)
        monkeypatch.setattr(
            s3_utils,
            "turn_S3_config_into_polars_storage_options",
            lambda _s3: SimpleNamespace(endpoint_url="http://s3:9000"),
        )
        monkeypatch.setattr(mp, "_make_s3_client", lambda _options: instance)
        monkeypatch.setattr(mp, "api_check_duplicate_multiqc_report", _check_duplicate)
        monkeypatch.setattr(mp, "api_create_multiqc_report", _create)
        monkeypatch.setattr(mp, "api_update_multiqc_report", _update)
        monkeypatch.setattr(
            api_calls,
            "api_update_dc_specific_properties",
            lambda **_kwargs: MagicMock(status_code=200),
        )
        monkeypatch.setattr(
            mp, "rich_print_checked_statement", lambda message, level: said.append((level, message))
        )
        monkeypatch.setattr(mp, "rich_print_multiqc_processing_summary", lambda **_kwargs: None)

        data_collection = MagicMock()
        data_collection.id = DC_ID
        data_collection.data_collection_tag = DC_TAG
        cli_config = SimpleNamespace(
            api_base_url="http://depictio-backend:8058",
            remote_storage_options=None,
            s3_storage=SimpleNamespace(
                bucket="depictio-bucket",
                endpoint_url="http://s3:9000",
                aws_access_key_id="instance-key",
                aws_secret_access_key="instance-secret",
                verify_tls=True,
            ),
        )
        result = mp.process_multiqc_data_collection(
            data_collection, cli_config, overwrite=overwrite
        )
        return SimpleNamespace(
            result=result,
            client=client,
            instance=instance,
            said=said,
            duplicate_checks=duplicate_checks,
            created=created,
            updated=updated,
        )

    return _run


@pytest.fixture()
def fake_parse(monkeypatch):
    """Parse by reading the copy: its bytes name the samples, so each report's
    metadata can be traced back to the object it was fetched from."""
    parsed: list[str] = []

    def _parse(path: str) -> dict:
        parsed.append(path)
        content = Path(path).read_bytes().decode()
        return {"samples": [content], "modules": ["fastqc"], "plots": {}, "multiqc_version": "1.0"}

    monkeypatch.setattr(mp, "_parse_multiqc_worker", _parse)
    return parsed


def _files(*runs: str, size: int | None = None, bucket: str = BUCKET):
    return [
        SimpleNamespace(file_location=_url(run, bucket), filesize=-1 if size is None else size)
        for run in runs
    ]


def _leftovers(temp_root: Path) -> list[str]:
    return sorted(os.listdir(temp_root))


# ── several reports, one per run prefix ──────────────────────────────────────


def test_reports_under_two_run_prefixes_are_fetched_parsed_and_uploaded(ingest, _env):
    """Sequencing-runs layout: one report per run, both parsed for real."""
    body = FIXTURE.read_bytes()
    out = ingest(_files("run_01", "run_02"), {_key("run_01"): body, _key("run_02"): body})

    assert out.result["result"] == "success", out.said
    assert out.result["metadata"]["processed_files"] == [_url("run_01"), _url("run_02")]
    assert out.client.get_object_calls == [_key("run_01"), _key("run_02")]  # each fetched once

    # Each report is named and deduplicated by its own URL.
    assert out.duplicate_checks == [_url("run_01"), _url("run_02")]
    assert [r["original_file_path"] for r in out.created] == [_url("run_01"), _url("run_02")]
    assert all(r["file_size_bytes"] == len(body) for r in out.created)
    assert all(r["metadata"]["samples"] for r in out.created)  # a real parse

    # Uploaded into the instance bucket from the fetched copy, keyed by content.
    assert len(out.instance.uploads) == 1  # same bytes, same content-hash key
    upload = next(iter(out.instance.uploads.values()))
    assert upload["body"] == body
    # MultiQC only parses its parquet under this very name.
    assert Path(upload["path"]).name == "multiqc.parquet"
    assert Path(upload["path"]).parents[1].name.startswith("depictio_multiqc_")
    assert all(r["s3_location"].startswith("s3://depictio-bucket/") for r in out.created)

    # Nothing fetched outlives the ingest.
    assert _leftovers(_env) == []


def test_the_display_name_is_the_run_segment_of_the_url():
    assert mp._report_display_path(_url("run_01")) == "run_01/multiqc.parquet"
    assert mp._report_display_path("/data/run_02/multiqc/multiqc_data/multiqc.parquet") == (
        "run_02/multiqc.parquet"
    )
    assert mp._report_display_path(f"s3://{BUCKET}/flat/report.parquet") == "report.parquet"


# ── failures stay per report ─────────────────────────────────────────────────


def test_a_failed_and_a_refused_fetch_do_not_stop_the_other_report(ingest, fake_parse, _env):
    files = _files("run_01", "run_02", "run_03")
    # run_03 sits in a bucket this server is not allowed to read.
    files[2] = SimpleNamespace(file_location=_url("run_03", "private-lab"), filesize=-1)
    out = ingest(
        files,
        {_key("run_01"): b"S1", _key("run_02"): b"S2"},
        denied={_key("run_01")},
    )

    assert out.result["result"] == "success"
    assert out.result["metadata"]["processed_files"] == [_url("run_02")]
    assert [r["original_file_path"] for r in out.created] == [_url("run_02")]
    assert out.created[0]["metadata"]["samples"] == ["S2"]

    errors = [message for level, message in out.said if level == "error"]
    assert len(errors) == 2
    denied, refused = errors
    assert _url("run_01") in denied and "denied" in denied
    assert _url("run_03", "private-lab") in refused and "cannot be read by the server" in refused
    # The refused one never reached the store.
    assert _key("run_03") not in out.client.get_object_calls
    assert _leftovers(_env) == []


def test_an_absent_object_is_reported_as_not_found(ingest, fake_parse):
    out = ingest(_files("run_01", "gone"), {_key("run_01"): b"S1"})

    assert out.result["result"] == "success"
    assert ("error", f"MultiQC report not found, skipped: {_url('gone')}") in out.said


def test_no_report_fetched_is_the_collection_error(ingest, fake_parse, _env):
    out = ingest(_files("run_01", "run_02"), {}, denied={_key("run_01"), _key("run_02")})

    assert out.result == {
        "result": "error",
        "message": "No MultiQC parquet files were successfully processed",
    }
    assert fake_parse == []
    assert _leftovers(_env) == []


def test_parallel_parse_maps_each_copy_back_to_its_url(ingest, fake_parse, monkeypatch):
    """With parse workers on, the copies are parsed concurrently; a fetch that
    failed in the middle must not shift which metadata goes with which URL."""
    monkeypatch.setenv("DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS", "3")
    # Threads stand in for processes: what is under test is the bookkeeping.
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", ThreadPoolExecutor)
    out = ingest(
        _files("run_01", "run_02", "run_03"),
        {_key("run_01"): b"S1", _key("run_02"): b"S2", _key("run_03"): b"S3"},
        denied={_key("run_02")},
    )

    assert out.result["result"] == "success"
    assert len(fake_parse) == 2
    by_url = {r["original_file_path"]: r["metadata"]["samples"] for r in out.created}
    assert by_url == {_url("run_01"): ["S1"], _url("run_03"): ["S3"]}


# ── re-ingest ────────────────────────────────────────────────────────────────


def test_reingest_dedupes_per_report_url(ingest, fake_parse):
    existing = {
        _url("run_01"): {
            "id": "existing-1",
            "s3_location": f"s3://depictio-bucket/{DC_ID}/abc/multiqc.parquet",
        }
    }
    out = ingest(
        _files("run_01", "run_02"),
        {_key("run_01"): b"S1", _key("run_02"): b"S2"},
        existing=existing,
    )

    assert out.result["result"] == "success"
    # run_01 is already stored: not uploaded again, not created again.
    assert [r["original_file_path"] for r in out.created] == [_url("run_02")]
    assert out.result["metadata"]["created_reports"] == ["existing-1", "report-1"]
    assert [u["body"] for u in out.instance.uploads.values()] == [b"S2"]


def test_reingest_with_overwrite_updates_the_report_of_that_url(ingest, fake_parse):
    existing = {
        _url("run_01"): {
            "id": "existing-1",
            "s3_location": f"s3://depictio-bucket/{DC_ID}/abc/multiqc.parquet",
        }
    }
    out = ingest(_files("run_01"), {_key("run_01"): b"S1-v2"}, existing=existing, overwrite=True)

    assert out.result["result"] == "success"
    assert out.created == []
    [(report_id, report)] = out.updated
    assert report_id == "existing-1"
    assert report["original_file_path"] == _url("run_01")
    assert out.instance.uploads[f"{DC_ID}/abc/multiqc.parquet"]["body"] == b"S1-v2"


# ── the download budget ──────────────────────────────────────────────────────


def test_reports_share_one_download_budget(ingest, fake_parse, monkeypatch, _env):
    """Listed sizes known: what no longer fits is skipped before any request."""
    monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "10")
    out = ingest(
        _files("run_01", "run_02", size=6),
        {_key("run_01"): b"S1-xxx", _key("run_02"): b"S2-xxx"},
    )

    assert out.result["result"] == "success"
    assert [r["original_file_path"] for r in out.created] == [_url("run_01")]
    assert out.client.get_object_calls == [_key("run_01")]
    [(level, message)] = out.said
    assert level == "error"
    assert _url("run_02") in message
    assert "its 6 bytes exceed the 4 bytes left of the 10-byte download cap" in message
    assert f"'{DC_TAG}'" in message and "DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES" in message
    assert _leftovers(_env) == []


def test_a_report_of_unknown_size_is_stopped_at_the_budget(ingest, fake_parse, monkeypatch, _env):
    """No listed size: the stream itself stops, and no partial copy is kept."""
    monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "10")
    out = ingest(_files("run_01", "run_02"), {_key("run_01"): b"S1", _key("run_02"): b"S2" * 10})

    assert [r["original_file_path"] for r in out.created] == [_url("run_01")]
    [(_level, message)] = out.said
    assert _url("run_02") in message and "it exceeds the 8 bytes left" in message
    assert _leftovers(_env) == []


# ── the copies' lifetime ─────────────────────────────────────────────────────


def test_the_copies_outlive_the_prerender_and_are_removed_after(
    ingest, fake_parse, monkeypatch, _env
):
    monkeypatch.setenv("DEPICTIO_INGEST_MULTIQC_PRERENDER", "1")
    seen: list[tuple[str, str, bool]] = []

    def _prerender(_dc, _config, prerender_inputs, _options):
        seen.extend((path, loc, Path(path).is_file()) for path, loc in prerender_inputs)

    monkeypatch.setattr(mp, "_prerender_multiqc_figures", _prerender)
    out = ingest(_files("run_01", "run_02"), {_key("run_01"): b"S1", _key("run_02"): b"S2"})

    assert out.result["result"] == "success"
    assert len(seen) == 2
    assert all(exists for _path, _loc, exists in seen)  # still there for the prerender
    assert all(loc.startswith("s3://depictio-bucket/") for _path, loc, _exists in seen)
    assert not any(Path(path).exists() for path, _loc, _exists in seen)
    assert _leftovers(_env) == []


def test_the_copies_are_removed_when_the_ingest_fails(ingest, monkeypatch, _env):
    def _crash(_paths, _labels=None):
        raise RuntimeError("parse exploded")

    monkeypatch.setattr(mp, "_parse_multiqc_files", _crash)
    out = ingest(_files("run_01"), {_key("run_01"): b"S1"})

    assert out.result["result"] == "error"
    assert "parse exploded" in out.result["message"]
    assert out.client.get_object_calls == [_key("run_01")]  # it was fetched
    assert _leftovers(_env) == []
