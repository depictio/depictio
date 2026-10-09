"""Tests for the s3_prefix scan mode (remote counterpart of `recursive`).

Listing is exercised against the shared boto3 stub (``depictio.tests.cli.s3_stubs``):
the S3 wire protocol is not what can break here, the key filtering and
pagination handling are. Which credentials a listing uses is decided by
``data_root._s3_read_target`` from configuration alone, so those tests assert
on the resolved target.
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from depictio.api.v1 import remote_fetch
from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
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
from depictio.models.s3_access import S3AccessFailed, S3AccessRefused, S3Target

from ..s3_stubs import FailingS3Client, install_s3_client, install_s3_listing, s3_cli_config

# Every object is ten bytes, so ``Size`` is a constant the File assertions can
# name; the shared stub derives it from the body.
_OBJECT_BODY = b"x" * 10


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context, the suite's default. Importing the CLI app sets
    ``DEPICTIO_CONTEXT=CLI`` for the whole process, and how a location is read
    depends on it."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")


@pytest.fixture
def public_b(monkeypatch):
    """Bucket ``b`` allowlisted, so a listing without project storage is allowed."""
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "b")


@pytest.fixture
def stub_s3(monkeypatch, public_b):
    """Serve ``keys`` as a listing, split across pages the way S3 splits one."""

    def _install(keys, page_size: int = 2, **client_kwargs):
        return install_s3_listing(
            monkeypatch, dict.fromkeys(keys, _OBJECT_BODY), page_size=page_size, **client_kwargs
        )

    return _install


@pytest.fixture
def failing_s3(monkeypatch, public_b):
    """A listing whose first page answers with an S3 error ``code`` / ``status``."""

    def _install(code: str, status: int):
        return install_s3_client(monkeypatch, FailingS3Client(code, status))

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

    @staticmethod
    def _warnings(monkeypatch) -> list[str]:
        captured: list[str] = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": captured.append(msg) if level == "warning" else None,
        )
        return captured

    def test_listing_stops_once_max_files_match(self, stub_s3, monkeypatch):
        """No page is asked for past the one that fills the cap, rather than
        paging on to the key budget for matches that would be dropped."""
        client = stub_s3([f"run42/sample_{i}.csv" for i in range(10)], page_size=2)
        warnings = self._warnings(monkeypatch)

        found = scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 2, None)

        assert [o["relative"] for o in found] == ["sample_0.csv", "sample_1.csv"]
        assert client.pages_served == 1
        assert len(warnings) == 1
        assert "max_files cap (2)" in warnings[0]
        assert "results may be truncated" in warnings[0]

    def test_a_further_match_on_that_page_says_the_results_are_truncated(
        self, stub_s3, monkeypatch
    ):
        client = stub_s3([f"run42/sample_{i}.csv" for i in range(10)], page_size=3)
        warnings = self._warnings(monkeypatch)

        found = scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 2, None)

        assert len(found) == 2
        assert client.pages_served == 1
        assert "results are truncated" in warnings[0]

    def test_a_listing_that_ends_with_the_cap_is_complete(self, stub_s3, monkeypatch):
        stub_s3(["run42/sample_0.csv", "run42/sample_1.csv"], page_size=2, is_truncated=False)
        warnings = self._warnings(monkeypatch)

        found = scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 2, None)

        assert len(found) == 2
        assert warnings == []

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


class TestListS3PrefixFailures:
    def test_an_absent_prefix_lists_as_empty(self, failing_s3):
        """Some gateways answer a prefix that holds nothing with a 404."""
        failing_s3("NoSuchKey", 404)
        assert scan_module.list_s3_prefix("s3://b/run42/", "*", 10, None) == []

    @pytest.mark.parametrize(
        ("code", "status", "expected", "names"),
        [
            ("NoSuchBucket", 404, "s3_no_such_bucket", "The bucket 'lab'"),
            ("AccessDenied", 403, "s3_access_denied", "s3://lab/run42/"),
        ],
    )
    def test_other_failures_carry_their_code(self, failing_s3, code, status, expected, names):
        failing_s3(code, status)
        with pytest.raises(S3AccessFailed) as exc:
            scan_module.list_s3_prefix("s3://lab/run42/", "*", 10, s3_cli_config())
        assert exc.value.code == expected
        assert names in exc.value.detail
        # Read with the project's storage: its endpoint is never echoed.
        assert "s3.example" not in exc.value.detail

    def test_a_refused_prefix_is_refused_before_any_client(self, monkeypatch):
        monkeypatch.setattr(S3Target, "client", lambda _target: pytest.fail("a client was built"))
        with pytest.raises(S3AccessRefused):
            scan_module.list_s3_prefix("s3://someone-elses/run42/", "*", 10, None)


class TestS3ReadTarget:
    """Which credentials a prefix listing uses, decided before any request."""

    @pytest.fixture(autouse=True)
    def _server_context(self, monkeypatch):
        """Server context unless a test says CLI: importing the CLI app sets
        ``DEPICTIO_CONTEXT=CLI`` for the whole process, so a test that ran it
        earlier in the same worker would otherwise decide these."""
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")

    @pytest.fixture
    def regions(self, monkeypatch):
        """Record what is asked for its region, and answer with a fixed one."""
        asked: list[S3Target] = []

        def fake_ensure_region(target):
            asked.append(target)
            return target.with_region(f"region-of-{target.bucket}")

        monkeypatch.setattr(data_root_module, "ensure_region", fake_ensure_region)
        return asked

    @staticmethod
    def _cfg(project=None):
        return SimpleNamespace(
            remote_storage_options=project,
            s3_storage=S3DepictioCLIConfig(
                bucket="depictio-bucket", root_user="instance-key", root_password="instance-pw-1"
            ),
        )

    @staticmethod
    def _project(**overrides):
        return {
            "aws_access_key_id": "k",
            "aws_secret_access_key": "s",
            "endpoint_url": "https://s3.example",
            "region": "eu-central-1",
            **overrides,
        }

    def test_the_project_storage_is_used_as_configured(self, regions):
        target = data_root_module._s3_read_target("s3://lab/run42/", self._cfg(self._project()))

        assert target.kind == "project"
        assert regions[0].region == "eu-central-1"
        assert target.endpoint_url == "https://s3.example"
        assert target.access_key_id == "k"

    def test_the_polars_spellings_still_load(self, regions):
        project = {
            "aws_endpoint_url": "https://s3.example",
            "aws_region": "us-west-2",
            "aws_access_key_id": "k",
            "aws_secret_access_key": "s",
        }
        data_root_module._s3_read_target("s3://lab/run42/", self._cfg(project))

        assert regions[0].region == "us-west-2"
        assert regions[0].access_key_id == "k"

    def test_region_wins_over_the_polars_spelling(self, regions):
        """``region`` is what the project's storage settings store; given both,
        it is the one read."""
        project = self._project(aws_region="us-west-2", region="eu-central-1")
        data_root_module._s3_read_target("s3://lab/run42/", self._cfg(project))

        assert regions[0].region == "eu-central-1"

    def test_the_listing_runs_in_the_buckets_own_region(self, regions):
        """object-store and boto3 fail on S3's cross-region redirect rather than
        following it, so the target is moved to the bucket's own region."""
        target = data_root_module._s3_read_target("s3://lab/run42/", self._cfg(self._project()))

        assert target.region == "region-of-lab"

    def test_an_allowlisted_bucket_is_listed_unsigned(self, regions, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        target = data_root_module._s3_read_target(
            "s3://open-data/run42/", self._cfg(self._project())
        )

        assert target.kind == "public"
        assert target.unsigned is True
        assert not target.access_key_id

    def test_the_unsigned_client_sends_no_credentials(self, monkeypatch):
        """``s3_read_client`` is the resolved target's client."""
        import boto3
        from botocore import UNSIGNED

        calls: list[dict] = []
        monkeypatch.setattr(boto3, "client", lambda service, **kwargs: calls.append(kwargs))
        monkeypatch.setattr(remote_fetch, "ensure_region", lambda target: target)
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        data_root_module.s3_read_client("s3://open-data/run42/x.csv", self._cfg(self._project()))

        assert calls[0]["config"].signature_version is UNSIGNED
        assert calls[0].get("aws_access_key_id") is None

    def test_an_unlisted_bucket_uses_the_project_storage(self, regions, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")

        target = data_root_module._s3_read_target("s3://private/run42/", self._cfg(self._project()))

        assert target.kind == "project"
        assert target.access_key_id == "k"

    def test_the_server_refuses_a_bucket_without_storage_settings(self, regions):
        """No project storage, not public: refused, never listed with the root keys."""
        with pytest.raises(S3AccessRefused):
            data_root_module._s3_read_target("s3://someone-elses/run42/", self._cfg())
        assert regions == []

    def test_the_server_refuses_the_instance_bucket(self, regions):
        with pytest.raises(S3AccessRefused, match="instance's own data"):
            data_root_module._s3_read_target(
                "s3://depictio-bucket/6512/", self._cfg(self._project())
            )
        assert regions == []

    def test_keyless_project_storage_never_borrows_the_instance_keys(self, regions, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
        project = {"endpoint_url": "https://s3.example"}

        target = data_root_module._s3_read_target("s3://lab/run42/", self._cfg(project))

        assert target.kind == "project"
        assert target.unsigned is True
        assert not target.access_key_id

    def test_the_cli_lists_with_its_own_credentials(self, regions, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")

        target = data_root_module._s3_read_target("s3://depictio-bucket/run42/", self._cfg())

        assert target.kind == "instance"
        assert target.access_key_id == "instance-key"


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

    def test_the_budget_warning_counts_every_key_listed(self, monkeypatch, stub_s3):
        """Folder markers are listed, and paid for, like any key: the count the
        warning gives is the one the budget was reached with."""
        keys = (
            [f"run42/dir_{i}/" for i in range(5)]
            + [f"run42/noise_{i}.txt" for i in range(10)]
            + ["run42/late.csv"]
        )
        client = stub_s3(keys, page_size=5)
        messages = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": messages.append((level, msg)),
        )

        assert scan_module.list_s3_prefix("s3://b/run42/", "*.csv", 1, None) == []

        assert client.pages_served == 2
        warning = next(msg for level, msg in messages if level == "warning")
        assert "listed 10 keys" in warning
        assert "budget of 10 keys" in warning

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
        def _no_target(_url, _cfg):
            raise RuntimeError("no credentials")

        monkeypatch.setattr(data_root_module, "_s3_read_target", _no_target)

        result = self._scan(_s3_prefix_dc())

        assert result["result"] == "error"
        assert "S3 prefix listing failed" in result["message"]
        assert "no credentials" in result["message"]
        assert api.created == []

    def test_a_refused_read_propagates_with_its_code(self, monkeypatch, api):
        """Sanitized and coded already: the API answers with it as is."""

        def _refuse(url, _cfg):
            raise S3AccessRefused(f"{url} cannot be read by the server.")

        monkeypatch.setattr(data_root_module, "_s3_read_target", _refuse)

        with pytest.raises(S3AccessRefused) as exc:
            self._scan(_s3_prefix_dc())
        assert exc.value.code == "s3_refused"
        assert api.created == []

    def test_a_failed_listing_propagates_with_its_code(self, failing_s3, api):
        failing_s3("AccessDenied", 403)

        with pytest.raises(S3AccessFailed) as exc:
            self._scan(_s3_prefix_dc())
        assert exc.value.code == "s3_access_denied"
        assert api.created == []

    def test_an_absent_prefix_is_a_no_match_error(self, failing_s3, api):
        failing_s3("NoSuchKey", 404)

        result = self._scan(_s3_prefix_dc())

        assert result["result"] == "error"
        assert "No object under" in result["message"]

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
