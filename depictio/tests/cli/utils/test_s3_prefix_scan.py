"""Tests for the s3_prefix scan mode (remote counterpart of `recursive`).

Listing is exercised against a stubbed boto3 paginator: the S3 wire protocol is
not what can break here, the key filtering and pagination handling are.
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from depictio.cli.cli.utils import scan as scan_module
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import (
    DataCollection,
    DataCollectionConfig,
    Scan,
    ScanS3Prefix,
)
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import (
    Workflow,
    WorkflowConfig,
    WorkflowDataLocation,
    WorkflowEngine,
)


class _StubPaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **_kwargs):
        return self._pages


class _StubClient:
    def __init__(self, keys):
        # Mimic list_objects_v2 splitting results across pages.
        self._pages = [
            {"Contents": [{"Key": k, "Size": 10, "ETag": f'"{k}-etag"'} for k in chunk]}
            for chunk in (keys[:2], keys[2:])
            if chunk
        ]

    def get_paginator(self, _name):
        return _StubPaginator(self._pages)


@pytest.fixture
def stub_s3(monkeypatch):
    def _install(keys):
        monkeypatch.setattr(
            scan_module, "_s3_read_client", lambda _cfg, url=None: _StubClient(keys)
        )

    return _install


KEYS = [
    "run42/sample_A.samples.csv",
    "run42/sample_B.samples.csv",
    "run42/sample_A.measurements.csv",
    "run42/nested/sample_D.samples.csv",
    "run42/notes/",  # console-created "folder" placeholder
]


class TestScanS3PrefixModel:
    def test_accepts_a_prefix_and_glob(self):
        scan = Scan(
            mode="s3_prefix",
            scan_parameters={"prefix": "s3://b/run42/", "pattern": "*.csv"},
        )
        assert scan.scan_parameters.pattern == "*.csv"

    def test_https_prefix_rejected_with_a_pointer_to_the_alternatives(self):
        """HTTPS cannot be listed; the error has to say what to use instead."""
        with pytest.raises(ValueError, match="url.*manifest|manifest"):
            ScanS3Prefix(prefix="https://host/dir/")

    def test_prefix_without_bucket_rejected(self):
        with pytest.raises(ValueError, match="bucket"):
            ScanS3Prefix(prefix="s3://")

    def test_id_regex_must_have_exactly_one_group(self):
        with pytest.raises(ValueError, match="one capture group"):
            ScanS3Prefix(prefix="s3://b/x", id_regex=r"(a)(b)")

    def test_invalid_id_regex_rejected(self):
        with pytest.raises(ValueError, match="Invalid id_regex"):
            ScanS3Prefix(prefix="s3://b/x", id_regex="(")

    def test_empty_pattern_rejected(self):
        with pytest.raises(ValueError, match="pattern cannot be empty"):
            ScanS3Prefix(prefix="s3://b/x", pattern="   ")

    def test_defaults_match_everything_under_the_prefix(self):
        assert ScanS3Prefix(prefix="s3://b/x").pattern == "*"


class TestListS3Prefix:
    def test_glob_filters_by_role_and_recurses(self, stub_s3):
        """`*` spans `/` on purpose, so a role glob reaches nested keys — this
        is what makes the mode the remote twin of a recursive walk."""
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.samples.csv", 10_000, None)
        assert [o["relative"] for o in found] == [
            "sample_A.samples.csv",
            "sample_B.samples.csv",
            "nested/sample_D.samples.csv",
        ]

    def test_directory_placeholder_keys_are_skipped(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*", 10_000, None)
        assert all(not o["key"].endswith("/") for o in found)

    def test_results_span_pages(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*", 10_000, None)
        assert len(found) == 4

    def test_etag_is_unquoted_for_the_identity_hash(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.samples.csv", 10_000, None)
        assert not found[0]["etag"].startswith('"')

    def test_max_files_caps_and_warns(self, stub_s3, monkeypatch):
        """A silent cap would read as 'that is all there is'."""
        stub_s3(KEYS)
        messages = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": messages.append((level, msg)),
        )
        found = scan_module.list_s3_prefix("s3://b/run42/", "*", 2, None)
        assert len(found) == 2
        assert any(level == "warning" and "truncated" in msg for level, msg in messages)

    def test_non_s3_prefix_rejected(self, stub_s3):
        stub_s3(KEYS)
        with pytest.raises(ValueError, match="s3:// prefix"):
            scan_module.list_s3_prefix("https://host/d/", "*", 10, None)

    def test_full_urls_are_reconstructed(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.measurements.csv", 10_000, None)
        assert found[0]["url"] == "s3://b/run42/sample_A.measurements.csv"


class TestS3ReadClientRegion:
    """Per-project storage options spell the region as ``region``."""

    @pytest.fixture
    def captured_boto3(self, monkeypatch):
        import boto3

        calls: list[dict] = []

        def fake_client(service, **kwargs):
            calls.append({"service": service, **kwargs})
            return object()

        monkeypatch.setattr(boto3, "client", fake_client)
        return calls

    def test_region_key_is_honoured(self, captured_boto3):
        from types import SimpleNamespace

        cfg = SimpleNamespace(
            remote_storage_options={
                "aws_access_key_id": "k",
                "aws_secret_access_key": "s",
                "endpoint_url": "https://s3.example",
                "region": "eu-central-1",
            },
            s3_storage=None,
        )
        scan_module._s3_read_client(cfg)
        assert captured_boto3[0]["region_name"] == "eu-central-1"
        assert captured_boto3[0]["endpoint_url"] == "https://s3.example"

    def test_polars_spelling_still_wins(self, captured_boto3):
        from types import SimpleNamespace

        cfg = SimpleNamespace(
            remote_storage_options={"aws_region": "us-west-2", "region": "eu-central-1"},
            s3_storage=None,
        )
        scan_module._s3_read_client(cfg)
        assert captured_boto3[0]["region_name"] == "us-west-2"


class TestS3ReadClientPublicBuckets:
    """A location on the administrator's allowlist is listed unsigned.

    Signing with credentials that have no relationship to someone else's open
    bucket only earns a rejection, and the allowlist is configuration, so the
    choice is made before the client makes any call.
    """

    @pytest.fixture
    def captured_boto3(self, monkeypatch):
        import boto3

        calls: list[dict] = []

        def fake_client(service, **kwargs):
            calls.append({"service": service, **kwargs})
            return object()

        monkeypatch.setattr(boto3, "client", fake_client)
        return calls

    @staticmethod
    def _cfg():
        return SimpleNamespace(
            remote_storage_options={"aws_access_key_id": "k", "aws_secret_access_key": "s"},
            s3_storage=None,
        )

    def test_an_allowlisted_bucket_drops_the_signature(self, captured_boto3, monkeypatch):
        from botocore import UNSIGNED

        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        scan_module._s3_read_client(self._cfg(), url="s3://open-data/run42/x.csv")

        assert captured_boto3[0]["config"].signature_version is UNSIGNED
        assert "aws_access_key_id" not in captured_boto3[0]

    def test_an_unlisted_bucket_keeps_its_credentials(self, captured_boto3, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        scan_module._s3_read_client(self._cfg(), url="s3://private-data/run42/x.csv")

        assert captured_boto3[0]["aws_access_key_id"] == "k"
        assert "config" not in captured_boto3[0]

    def test_nothing_is_unsigned_without_an_allowlist(self, captured_boto3, monkeypatch):
        monkeypatch.delenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", raising=False)

        scan_module._s3_read_client(self._cfg(), url="s3://open-data/run42/x.csv")

        assert captured_boto3[0]["aws_access_key_id"] == "k"


class TestListS3PrefixKeyBudget:
    """A prefix full of non-matching keys must not pin the calling thread."""

    class _CountingClient:
        def __init__(self, keys, page_size):
            self.pages_served = 0
            self._pages = [
                {
                    "Contents": [
                        {"Key": k, "Size": 10, "ETag": f'"{k}-etag"'}
                        for k in keys[i : i + page_size]
                    ]
                }
                for i in range(0, len(keys), page_size)
            ]

        def get_paginator(self, _name):
            client = self

            class _Paginator:
                def paginate(self, **_kwargs):
                    for page in client._pages:
                        client.pages_served += 1
                        yield page

            return _Paginator()

    def test_budget_stops_the_walk_and_warns(self, monkeypatch):
        # max_files=1 -> budget of 10 keys; the only match sits past it.
        keys = [f"run42/noise_{i}.txt" for i in range(40)] + ["run42/late.csv"]
        client = self._CountingClient(keys, page_size=5)
        monkeypatch.setattr(scan_module, "_s3_read_client", lambda _cfg, url=None: client)
        messages = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": messages.append((level, msg)),
        )
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 1, None)
        assert found == []
        # Stopped after the budget's pages, not after all 9.
        assert client.pages_served == 2
        warning = next(msg for level, msg in messages if level == "warning")
        assert "s3://b/run42/" in warning
        assert "budget of 10 keys" in warning
        assert "partial" in warning

    def test_listing_ending_exactly_at_the_budget_is_complete(self, monkeypatch):
        # Ten keys, budget ten: the last page says IsTruncated=False, so this
        # is the whole listing and no warning is due.
        keys = [f"run42/noise_{i}.txt" for i in range(9)] + ["run42/late.csv"]
        client = self._CountingClient(keys, page_size=5)
        for page in client._pages:
            page["IsTruncated"] = False
        monkeypatch.setattr(scan_module, "_s3_read_client", lambda _cfg, url=None: client)
        messages = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": messages.append((level, msg)),
        )
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 1, None)
        assert [o["relative"] for o in found] == ["late.csv"]
        assert messages == []

    def test_budget_scales_with_max_files(self, monkeypatch):
        keys = [f"run42/noise_{i}.txt" for i in range(40)] + ["run42/late.csv"]
        client = self._CountingClient(keys, page_size=5)
        monkeypatch.setattr(scan_module, "_s3_read_client", lambda _cfg, url=None: client)
        messages = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": messages.append((level, msg)),
        )
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 5, None)
        assert [o["relative"] for o in found] == ["late.csv"]
        assert messages == []


# ── scan_s3_prefix_for_data_collection: listing to File records ─────────────

PREFIX = "s3://b/run42/"
SAMPLE_ID_REGEX = r"(sample_[A-Z])\.samples\.csv"


def _s3_prefix_dc(pattern: str = "*.samples.csv", id_regex: str | None = SAMPLE_ID_REGEX):
    return DataCollection(
        data_collection_tag="samples",
        config=DataCollectionConfig(
            type="table",
            metatype="aggregate",
            scan=Scan(
                mode="s3_prefix",
                scan_parameters=ScanS3Prefix(prefix=PREFIX, pattern=pattern, id_regex=id_regex),
            ),
            dc_specific_properties={"format": "csv"},
        ),
    )


def _workflow(dc: DataCollection) -> Workflow:
    return Workflow(
        name="wf",
        workflow_tag="wf",
        engine=WorkflowEngine(name="python"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(structure="flat", locations=[PREFIX]),
        data_collections=[dc],
    )


def _object_hash(key: str) -> str:
    """Identity hash of a stubbed object: url + the ETag the stub derives from its key."""
    return hashlib.sha256(f"s3://b/{key}|{key}-etag".encode()).hexdigest()


def _existing(key: str, file_hash: str) -> dict:
    return {"_id": str(ObjectId()), "file_location": f"s3://b/{key}", "file_hash": file_hash}


@pytest.fixture
def api(monkeypatch):
    """Stub the API round-trips the scan makes; see TestUrlScan in
    tests/cli/test_remote_read.py for the same shape."""
    recorder = SimpleNamespace(existing=[], status=200, created=[], deleted=[])

    def _lookup(**_):
        response = MagicMock(status_code=recorder.status)
        response.json.return_value = recorder.existing
        return response

    monkeypatch.setattr(scan_module, "api_get_files_by_dc_id", _lookup)
    monkeypatch.setattr(
        scan_module,
        "api_create_files",
        lambda files, CLI_config, update: recorder.created.append((list(files), update)),
    )
    monkeypatch.setattr(
        scan_module, "api_delete_file", lambda file_id, CLI_config: recorder.deleted.append(file_id)
    )
    return recorder


@pytest.fixture
def messages(monkeypatch):
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        scan_module,
        "rich_print_checked_statement",
        lambda msg, level="info": captured.append((level, msg)),
    )
    return captured


class TestScanS3PrefixForDataCollection:
    @staticmethod
    def _scan(dc: DataCollection, update_files: bool = False) -> dict:
        owner = UserBase(id=PyObjectId(), email="o@example.com", is_admin=False)
        return scan_module.scan_s3_prefix_for_data_collection(
            workflow=_workflow(dc),
            data_collection=dc,
            CLI_config=MagicMock(),
            permissions=Permission(owners=[owner]),
            update_files=update_files,
        )

    def test_registers_every_matching_object_with_a_join_id(self, stub_s3, api):
        stub_s3(KEYS)
        dc = _s3_prefix_dc()

        assert self._scan(dc) == {"result": "success", "added": 3, "updated": 0}

        ((files, update),) = api.created
        assert update is False
        by_id = {f.manifest_id: f for f in files}
        # id_regex captured the entity id from nested keys too.
        assert set(by_id) == {"sample_A", "sample_B", "sample_D"}
        nested = by_id["sample_D"]
        assert nested.file_location == "s3://b/run42/nested/sample_D.samples.csv"
        assert nested.filename == "sample_D.samples.csv"
        assert nested.file_hash == _object_hash("run42/nested/sample_D.samples.csv")
        assert nested.filesize == 10
        assert nested.run_tag == "remote"
        assert {f.data_collection_id for f in files} == {dc.id}
        assert api.deleted == []

    def test_no_match_is_an_error_not_an_empty_success(self, stub_s3, api):
        stub_s3(KEYS)

        result = self._scan(_s3_prefix_dc(pattern="*.parquet"))

        assert result["result"] == "error"
        assert PREFIX in result["message"]
        assert "*.parquet" in result["message"]
        assert "samples" in result["message"]
        assert api.created == []

    def test_listing_failure_is_reported_as_a_scan_error(self, monkeypatch, api):
        def _no_client(_cfg, url=None):
            raise RuntimeError("no credentials")

        monkeypatch.setattr(scan_module, "_s3_read_client", _no_client)

        result = self._scan(_s3_prefix_dc())

        assert result["result"] == "error"
        assert "S3 prefix listing failed" in result["message"]
        assert "no credentials" in result["message"]
        assert api.created == []

    def test_unchanged_objects_are_skipped_and_stale_records_removed(self, stub_s3, api):
        stub_s3(KEYS)
        stale = _existing("run42/gone.samples.csv", "x" * 64)
        api.existing = [
            _existing("run42/sample_A.samples.csv", _object_hash("run42/sample_A.samples.csv")),
            stale,
        ]

        assert self._scan(_s3_prefix_dc()) == {"result": "success", "added": 2, "updated": 0}

        assert api.deleted == [stale["_id"]]
        ((files, update),) = api.created
        assert update is False
        assert {f.manifest_id for f in files} == {"sample_B", "sample_D"}

    def test_re_uploaded_object_is_an_update_that_keeps_its_id(self, stub_s3, api):
        stub_s3(KEYS)
        known = _existing("run42/sample_A.samples.csv", "0" * 64)  # ETag has since changed
        api.existing = [known]

        assert self._scan(_s3_prefix_dc()) == {"result": "success", "added": 2, "updated": 1}

        ((files, _),) = [(files, update) for files, update in api.created if update]
        assert [str(f.id) for f in files] == [known["_id"]]
        assert files[0].file_hash == _object_hash("run42/sample_A.samples.csv")

    def test_update_files_forces_reregistration_of_unchanged_objects(self, stub_s3, api):
        stub_s3(KEYS)
        api.existing = [
            _existing("run42/sample_A.samples.csv", _object_hash("run42/sample_A.samples.csv"))
        ]

        result = self._scan(_s3_prefix_dc(), update_files=True)

        assert result == {"result": "success", "added": 2, "updated": 1}

    def test_lookup_failure_still_registers_everything(self, stub_s3, api):
        stub_s3(KEYS)
        api.status = 500

        assert self._scan(_s3_prefix_dc()) == {"result": "success", "added": 3, "updated": 0}

    def test_unmatched_id_regex_warns_and_leaves_no_join_id(self, stub_s3, api, messages):
        stub_s3(KEYS)

        result = self._scan(_s3_prefix_dc(id_regex=r"^(run\d+)_"))

        assert result == {"result": "success", "added": 3, "updated": 0}
        ((files, _),) = api.created
        assert [f.manifest_id for f in files] == [None, None, None]
        warning = next(msg for level, msg in messages if level == "warning")
        assert "3 object(s)" in warning
        assert "did not match id_regex" in warning

    def test_without_id_regex_no_join_id_and_no_warning(self, stub_s3, api, messages):
        stub_s3(KEYS)

        self._scan(_s3_prefix_dc(id_regex=None))

        ((files, _),) = api.created
        assert [f.manifest_id for f in files] == [None, None, None]
        assert [level for level, _ in messages] == ["info"]
