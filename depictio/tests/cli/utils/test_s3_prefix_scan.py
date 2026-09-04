"""Tests for the s3_prefix scan mode (remote counterpart of `recursive`).

Listing is exercised against the shared boto3 stub (``depictio.tests.cli.s3_stubs``):
the S3 wire protocol is not what can break here, the key filtering and
pagination handling are.
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from depictio.cli.cli.utils import data_root as data_root_module
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
from depictio.tests.cli.s3_stubs import install_s3_listing

# Every object is ten bytes, so ``Size`` is a constant the File assertions can
# name; the shared stub derives it from the body.
_OBJECT_BODY = b"x" * 10


@pytest.fixture
def stub_s3(monkeypatch):
    """Serve ``keys`` as a listing, split across pages the way S3 splits one."""

    def _install(keys, page_size: int = 2, **client_kwargs):
        return install_s3_listing(
            monkeypatch, dict.fromkeys(keys, _OBJECT_BODY), page_size=page_size, **client_kwargs
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

    def test_pattern_syntax_defaults_to_glob(self):
        """Every configuration written before the field keeps its exact meaning."""
        assert ScanS3Prefix(prefix="s3://b/x", pattern="*.csv").pattern_syntax == "glob"

    def test_regex_syntax_is_accepted(self):
        scan = Scan(
            mode="s3_prefix",
            scan_parameters={
                "prefix": "s3://b/run42/",
                "pattern": r".*\.samples\.csv",
                "pattern_syntax": "regex",
            },
        )
        assert scan.scan_parameters.pattern_syntax == "regex"

    def test_an_uncompilable_regex_pattern_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            ScanS3Prefix(prefix="s3://b/x", pattern="sample_(", pattern_syntax="regex")

    def test_a_glob_pattern_is_not_a_valid_regex(self):
        """The two syntaxes are not interchangeable: "*.csv" is a leading
        repeat with nothing to repeat, so it has to fail at config time rather
        than mid-listing."""
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            ScanS3Prefix(prefix="s3://b/x", pattern="*.samples.csv", pattern_syntax="regex")

    def test_an_unknown_pattern_syntax_is_rejected(self):
        with pytest.raises(ValueError):
            ScanS3Prefix(prefix="s3://b/x", pattern="*", pattern_syntax="fnmatch")

    def test_a_glob_pattern_stays_valid_under_the_default_syntax(self):
        assert ScanS3Prefix(prefix="s3://b/x", pattern="*.samples.csv").pattern == "*.samples.csv"


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


class TestListS3PrefixPatternSyntax:
    """``pattern_syntax="regex"`` matches the way the local recursive walk does."""

    def test_regex_matches_on_the_relative_path(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix(
            "s3://b/run42/", r"nested/.*\.csv", 10_000, None, pattern_syntax="regex"
        )
        assert [o["relative"] for o in found] == ["nested/sample_D.samples.csv"]

    def test_regex_matches_on_the_basename_alone(self, stub_s3):
        """A pattern with no "/" is only ever tried against the file name, so it
        reaches nested keys the way the local walk does."""
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix(
            "s3://b/run42/", r"sample_[AB]\.samples\.csv", 10_000, None, pattern_syntax="regex"
        )
        assert [o["relative"] for o in found] == [
            "sample_A.samples.csv",
            "sample_B.samples.csv",
        ]

    def test_regex_stays_unanchored_at_the_end(self, stub_s3):
        """``regex_match`` is ``re.match``: anchored at the start, not the end.
        The local walk relies on that, so the remote one must not tighten it."""
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix(
            "s3://b/run42/", r"sample_A", 10_000, None, pattern_syntax="regex"
        )
        assert [o["relative"] for o in found] == [
            "sample_A.samples.csv",
            "sample_A.measurements.csv",
        ]

    def test_a_regex_pattern_is_not_a_glob(self, stub_s3):
        """Same string, two syntaxes, two answers - which is why translating a
        template's regex into a glob would be lossy."""
        stub_s3(KEYS)
        pattern = r"sample_[AB]\.samples\.csv"
        as_glob = scan_module.list_s3_prefix("s3://b/run42/", pattern, 10_000, None)
        as_regex = scan_module.list_s3_prefix(
            "s3://b/run42/", pattern, 10_000, None, pattern_syntax="regex"
        )
        assert as_glob == []
        assert len(as_regex) == 2

    def test_glob_is_still_the_default(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.samples.csv", 10_000, None)
        assert len(found) == 3


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
        data_root_module.s3_read_client("", cfg)
        assert captured_boto3[0]["region_name"] == "eu-central-1"
        assert captured_boto3[0]["endpoint_url"] == "https://s3.example"

    def test_polars_spelling_still_wins(self, captured_boto3):
        from types import SimpleNamespace

        cfg = SimpleNamespace(
            remote_storage_options={"aws_region": "us-west-2", "region": "eu-central-1"},
            s3_storage=None,
        )
        data_root_module.s3_read_client("", cfg)
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
        monkeypatch.setattr(data_root_module, "public_s3_region", lambda bucket: "eu-west-1")

        data_root_module.s3_read_client("s3://open-data/run42/x.csv", self._cfg())

        assert captured_boto3[0]["config"].signature_version is UNSIGNED
        assert "aws_access_key_id" not in captured_boto3[0]

    def test_the_unsigned_client_uses_the_buckets_own_region(self, captured_boto3, monkeypatch):
        """object-store fails on S3's cross-region redirect rather than
        following it, so the client has to be built in the bucket's own region."""
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")
        monkeypatch.setattr(
            data_root_module, "public_s3_region", lambda bucket: f"region-of-{bucket}"
        )

        data_root_module.s3_read_client("s3://open-data/run42/x.csv", self._cfg())

        assert captured_boto3[0]["region_name"] == "region-of-open-data"

    def test_an_unlisted_bucket_keeps_its_credentials(self, captured_boto3, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        data_root_module.s3_read_client("s3://private-data/run42/x.csv", self._cfg())

        assert captured_boto3[0]["aws_access_key_id"] == "k"
        assert "config" not in captured_boto3[0]

    def test_nothing_is_unsigned_without_an_allowlist(self, captured_boto3, monkeypatch):
        monkeypatch.delenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", raising=False)

        data_root_module.s3_read_client("s3://open-data/run42/x.csv", self._cfg())

        assert captured_boto3[0]["aws_access_key_id"] == "k"


class TestListS3PrefixKeyBudget:
    """A prefix full of non-matching keys must not pin the calling thread."""

    def test_budget_stops_the_walk_and_warns(self, monkeypatch, stub_s3):
        # max_files=1 -> budget of 10 keys; the only match sits past it.
        keys = [f"run42/noise_{i}.txt" for i in range(40)] + ["run42/late.csv"]
        client = stub_s3(keys, page_size=5)
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

    def test_listing_ending_exactly_at_the_budget_is_complete(self, monkeypatch, stub_s3):
        # Ten keys, budget ten: the last page says IsTruncated=False, so this
        # is the whole listing and no warning is due.
        keys = [f"run42/noise_{i}.txt" for i in range(9)] + ["run42/late.csv"]
        stub_s3(keys, page_size=5, is_truncated=False)
        messages = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": messages.append((level, msg)),
        )
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 1, None)
        assert [o["relative"] for o in found] == ["late.csv"]
        assert messages == []

    def test_budget_scales_with_max_files(self, monkeypatch, stub_s3):
        keys = [f"run42/noise_{i}.txt" for i in range(40)] + ["run42/late.csv"]
        stub_s3(keys, page_size=5)
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


def _s3_prefix_dc(
    pattern: str = "*.samples.csv",
    id_regex: str | None = SAMPLE_ID_REGEX,
    pattern_syntax: str = "glob",
    prefix: str = PREFIX,
):
    return DataCollection(
        data_collection_tag="samples",
        config=DataCollectionConfig(
            type="table",
            metatype="aggregate",
            scan=Scan(
                mode="s3_prefix",
                scan_parameters=ScanS3Prefix(
                    prefix=prefix,
                    pattern=pattern,
                    pattern_syntax=pattern_syntax,
                    id_regex=id_regex,
                ),
            ),
            dc_specific_properties={"format": "csv"},
        ),
    )


def _workflow(
    dc: DataCollection,
    structure: str = "flat",
    runs_regex: str | None = None,
    location: str = PREFIX,
) -> Workflow:
    return Workflow(
        name="wf",
        workflow_tag="wf",
        engine=WorkflowEngine(name="python"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(
            structure=structure, locations=[location], runs_regex=runs_regex
        ),
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
    recorder = SimpleNamespace(
        existing=[],
        status=200,
        created=[],
        deleted=[],
        existing_runs=[],
        runs_status=200,
        upserted=[],
    )

    def _lookup(**_):
        response = MagicMock(status_code=recorder.status)
        response.json.return_value = recorder.existing
        return response

    def _runs_lookup(**_):
        response = MagicMock(status_code=recorder.runs_status)
        response.json.return_value = recorder.existing_runs
        return response

    monkeypatch.setattr(scan_module, "api_get_files_by_dc_id", _lookup)
    monkeypatch.setattr(scan_module, "api_get_runs_by_wf_id", _runs_lookup)
    monkeypatch.setattr(
        scan_module,
        "api_create_files",
        lambda files, CLI_config, update: recorder.created.append((list(files), update)),
    )
    monkeypatch.setattr(
        scan_module, "api_delete_file", lambda file_id, CLI_config: recorder.deleted.append(file_id)
    )
    monkeypatch.setattr(
        scan_module,
        "api_upsert_runs_batch",
        lambda runs, CLI_config, update: recorder.upserted.append((list(runs), update)),
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
        def _no_client(_url, _cfg):
            raise RuntimeError("no credentials")

        monkeypatch.setattr(data_root_module, "s3_read_client", _no_client)

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


# ── sequencing-runs: one run per matched run directory ──────────────────────

RUN_PREFIX = "s3://b/data/"
RUN_KEYS = [
    "data/run_1/multiqc/multiqc_data/multiqc.parquet",
    "data/run_2/multiqc/multiqc_data/multiqc.parquet",
    "data/run_3/multiqc/multiqc_data/multiqc.parquet",
    # A sibling directory the runs_regex rejects: the local walk never descends
    # into it, so neither does the remote one.
    "data/scratch/multiqc/multiqc_data/multiqc.parquet",
    "data/run_1/variants/bowtie2/depth.tsv",
    # An object directly under the prefix belongs to no run at all.
    "data/top_level.parquet",
]

# What a template's recursive DC declares: a path relative to a run directory,
# not to the data root. See depictio/projects/nf-core/viralrecon/3.0.0.
RUN_RELATIVE_PATTERN = "multiqc/multiqc_data/multiqc.parquet"


class TestScanS3PrefixSequencingRuns:
    @staticmethod
    def _scan(
        dc: DataCollection,
        runs_regex: str | None = "run_.*",
        update_files: bool = False,
    ) -> dict:
        owner = UserBase(id=PyObjectId(), email="o@example.com", is_admin=False)
        return scan_module.scan_s3_prefix_for_data_collection(
            workflow=_workflow(
                dc,
                structure="sequencing-runs",
                runs_regex=runs_regex,
                location=RUN_PREFIX,
            ),
            data_collection=dc,
            CLI_config=MagicMock(),
            permissions=Permission(owners=[owner]),
            update_files=update_files,
        )

    @staticmethod
    def _dc(pattern: str = RUN_RELATIVE_PATTERN, pattern_syntax: str = "glob"):
        return _s3_prefix_dc(
            pattern=pattern,
            id_regex=None,
            pattern_syntax=pattern_syntax,
            prefix=RUN_PREFIX,
        )

    def test_one_run_per_matching_directory(self, stub_s3, api):
        """Three runs, one rejected sibling, one root-level object."""
        stub_s3(RUN_KEYS)

        assert self._scan(self._dc()) == {"result": "success", "added": 3, "updated": 0}

        ((files, _),) = api.created
        assert sorted(f.run_tag for f in files) == ["run_1", "run_2", "run_3"]
        # The rejected directory contributed nothing, pattern match or not.
        assert all("scratch" not in f.file_location for f in files)

        ((runs, update),) = api.upserted
        assert update is False
        assert sorted(r.run_tag for r in runs) == ["run_1", "run_2", "run_3"]
        assert sorted(r.run_location for r in runs) == [
            "s3://b/data/run_1",
            "s3://b/data/run_2",
            "s3://b/data/run_3",
        ]
        # Every file points at the run document that carries its own tag.
        by_tag = {r.run_tag: r.id for r in runs}
        assert all(f.run_id == by_tag[f.run_tag] for f in files)

    def test_pattern_is_matched_relative_to_the_run_directory(self, stub_s3, api):
        """The template's pattern is written relative to a run, so matching it
        against the root-relative key would find nothing at all."""
        stub_s3(RUN_KEYS)

        assert self._scan(self._dc())["added"] == 3
        ((files, _),) = api.created
        assert all(f.file_location.endswith("/" + RUN_RELATIVE_PATTERN) for f in files)

        # Same pattern with the run segment left in front matches nothing.
        api.created.clear()
        api.upserted.clear()
        result = self._scan(self._dc(pattern="run_1/" + RUN_RELATIVE_PATTERN))
        assert result["result"] == "error"

    def test_regex_syntax_also_matches_run_relative(self, stub_s3, api):
        stub_s3(RUN_KEYS)

        result = self._scan(self._dc(pattern=r"variants/.*\.tsv", pattern_syntax="regex"))

        assert result == {"result": "success", "added": 1, "updated": 0}
        ((files, _),) = api.created
        assert files[0].run_tag == "run_1"
        assert files[0].file_location == "s3://b/data/run_1/variants/bowtie2/depth.tsv"

    def test_a_known_run_keeps_its_server_side_id(self, stub_s3, api):
        """The upsert endpoint matches on ``_id``: minting a fresh one for a
        run_tag the server already knows would leave the files pointing at a run
        document that is never written."""
        stub_s3(RUN_KEYS)
        known_id = str(ObjectId())
        api.existing_runs = [{"_id": known_id, "run_tag": "run_2"}]

        self._scan(self._dc())

        ((runs, _),) = api.upserted
        reused = next(r for r in runs if r.run_tag == "run_2")
        assert str(reused.id) == known_id

    def test_runs_regex_matching_nothing_warns_with_what_was_seen(self, stub_s3, api, messages):
        stub_s3(RUN_KEYS)

        result = self._scan(self._dc(), runs_regex="sequencing_.*")

        # Loud, but not an exception: the scan reports the empty result the way
        # it always has, with a warning that says why it is empty.
        assert result["result"] == "error"
        warning = next(msg for level, msg in messages if level == "warning")
        assert "sequencing_.*" in warning
        for seen in ("run_1", "run_2", "run_3", "scratch"):
            assert seen in warning
        assert api.created == []
        assert api.upserted == []

    def test_detected_runs_are_named_in_the_summary(self, stub_s3, api, messages):
        stub_s3(RUN_KEYS)

        self._scan(self._dc())

        summary = next(msg for level, msg in messages if level == "info")
        assert "run_1, run_2, run_3" in summary

    def test_the_model_forbids_a_run_structure_without_a_regex(self):
        """Why the scan's "sequencing-runs *and* a regex" guard is only a
        backstop: the workflow model already rejects the half-declared case."""
        with pytest.raises(ValueError, match="runs_regex is required"):
            _workflow(self._dc(), structure="sequencing-runs", runs_regex=None)


class TestScanS3PrefixFlatIsUnchanged:
    """The flat prefix keeps exactly the behaviour it had before runs existed."""

    @staticmethod
    def _scan(dc: DataCollection) -> dict:
        owner = UserBase(id=PyObjectId(), email="o@example.com", is_admin=False)
        return scan_module.scan_s3_prefix_for_data_collection(
            workflow=_workflow(dc),
            data_collection=dc,
            CLI_config=MagicMock(),
            permissions=Permission(owners=[owner]),
            update_files=False,
        )

    def test_one_synthetic_run_and_the_constant_run_tag(self, stub_s3, api):
        stub_s3(KEYS)

        assert self._scan(_s3_prefix_dc()) == {"result": "success", "added": 3, "updated": 0}

        ((files, _),) = api.created
        assert {f.run_tag for f in files} == {"remote"}
        assert len({f.run_id for f in files}) == 1
        # Flat prefixes never persisted a run and still do not.
        assert api.upserted == []

    def test_a_regex_pattern_threads_from_the_model_to_the_matcher(self, stub_s3, api):
        stub_s3(KEYS)
        dc = _s3_prefix_dc(
            pattern=r"sample_[AB]\.samples\.csv", id_regex=None, pattern_syntax="regex"
        )

        assert self._scan(dc) == {"result": "success", "added": 2, "updated": 0}

        ((files, _),) = api.created
        assert sorted(f.filename for f in files) == [
            "sample_A.samples.csv",
            "sample_B.samples.csv",
        ]

    def test_the_same_pattern_as_a_glob_matches_nothing(self, stub_s3, api):
        """Proof the syntax is honoured end to end and not quietly ignored."""
        stub_s3(KEYS)
        dc = _s3_prefix_dc(pattern=r"sample_[AB]\.samples\.csv", id_regex=None)

        assert self._scan(dc)["result"] == "error"
