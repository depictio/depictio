"""Tests for the DataRoot abstraction (local directory vs ``s3://`` prefix).

The point of the module is that a caller cannot tell the two apart, so the bulk
of this file is a parity suite: the same virtual tree is built twice, once on
disk and once as a stubbed key listing, and every question is asked of both.

No network: the S3 listing comes from ``depictio.tests.cli.s3_stubs``, which
replaces the client every remote path goes through. How a location is read
(public, project, instance, ambient, or refused) is the real decision.
"""

from types import SimpleNamespace

import pytest

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.cli.cli.utils import data_root as data_root_module
from depictio.cli.cli.utils.data_root import (
    LocalDataRoot,
    S3DataRoot,
    data_root_for,
    list_s3_objects,
)
from depictio.models.s3_access import S3AccessFailed, S3AccessRefused, S3Target

from ..s3_stubs import (
    FailingS3Client,
    StubS3Client,
    install_s3_client,
    install_s3_listing,
    s3_cli_config,
    s3_client_error,
)

# ── the shared virtual tree ──────────────────────────────────────────────────

# A pipeline results directory: template-relevant files at the root, plus a
# sequencing-runs shape (run_1, run_2 and a logs/ that must not read as a run).
TREE = [
    "input/Samplesheet_full.tsv",
    "logs/nextflow.log",
    "pipeline_info/params_2026-01-16.json",
    "qiime2/barplot/level-3.csv",
    "qiime2/barplot/level-4.csv",
    "run_1/pipeline_info/params_2026-01-16.json",
    "run_1/qiime2/barplot/level-3.csv",
    "run_2/pipeline_info/params_2026-02-01.json",
]

S3_BUCKET = "depictio-test"
S3_KEY_PREFIX = "projects/results/"
S3_ROOT = f"s3://{S3_BUCKET}/{S3_KEY_PREFIX.rstrip('/')}"


def _body(rel: str) -> bytes:
    return f"contents of {rel}".encode()


def _s3_storage():
    return S3DepictioCLIConfig(root_user="minio", root_password="minio123")


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context, the suite's default. Importing the CLI app sets
    ``DEPICTIO_CONTEXT=CLI`` for the whole process, and how a location is read
    depends on it."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")


@pytest.fixture
def no_bucket_lists(monkeypatch):
    """No bucket an administrator listed, public or credentialed."""
    monkeypatch.delenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", raising=False)


@pytest.fixture
def no_client(monkeypatch):
    """Fail the test if any S3 client is built: the decision needs none."""
    monkeypatch.setattr(S3Target, "client", lambda _target: pytest.fail("a client was built"))


@pytest.fixture(params=["local", "s3"])
def root(request, tmp_path, monkeypatch):
    """The same tree as a LocalDataRoot and as an S3DataRoot, in turn."""
    if request.param == "local":
        base = tmp_path / "results"
        for rel in TREE:
            path = base / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_body(rel))
        return data_root_for(str(base))

    install_s3_listing(monkeypatch, {f"{S3_KEY_PREFIX}{rel}": _body(rel) for rel in TREE})
    return data_root_for(S3_ROOT, s3_cli_config())


# ── dispatch ─────────────────────────────────────────────────────────────────


class TestDataRootFor:
    def test_a_plain_path_is_local(self, tmp_path):
        root = data_root_for(str(tmp_path))
        assert isinstance(root, LocalDataRoot)
        assert root.is_remote is False
        assert root.location == str(tmp_path)

    def test_an_s3_prefix_is_remote(self, monkeypatch):
        install_s3_listing(monkeypatch, {})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert isinstance(root, S3DataRoot)
        assert root.is_remote is True
        assert root.location == S3_ROOT

    @pytest.mark.parametrize(
        "location",
        ["https://host/results/", "http://host/results/", "gs://bucket/results", "file:///tmp/x"],
    )
    def test_other_schemes_are_refused_by_name(self, location):
        """A scheme we cannot list has to say so, not silently read as a path."""
        with pytest.raises(ValueError, match="cannot be listed"):
            data_root_for(location)


# ── parity ───────────────────────────────────────────────────────────────────


class TestParity:
    """Every answer below must be the same on disk and on S3."""

    def test_name_is_the_last_segment(self, root):
        assert root.name == "results"

    @pytest.mark.parametrize(
        "rel,expected",
        [
            ("", True),
            ("pipeline_info", True),
            ("pipeline_info/params_2026-01-16.json", True),
            ("qiime2/barplot", True),
            ("qiime2/barplot/level-3.csv", True),
            ("run_1", True),
            ("run_3", False),
            ("pipeline_info/params_2026-01-17.json", False),
            ("qiime2/barplot/level-3.csv/deeper", False),
        ],
    )
    def test_exists(self, root, rel, expected):
        assert root.exists(rel) is expected

    @pytest.mark.parametrize(
        "pattern,expected",
        [
            ("pipeline_info/params*.json", ["pipeline_info/params_2026-01-16.json"]),
            (
                "*/pipeline_info/params*.json",
                [
                    "run_1/pipeline_info/params_2026-01-16.json",
                    "run_2/pipeline_info/params_2026-02-01.json",
                ],
            ),
            ("input/*", ["input/Samplesheet_full.tsv"]),
            (
                "**/*.csv",
                [
                    "qiime2/barplot/level-3.csv",
                    "qiime2/barplot/level-4.csv",
                    "run_1/qiime2/barplot/level-3.csv",
                ],
            ),
            # "*" stops at "/", so a top-level glob never reaches into a run.
            ("*.csv", []),
            (
                "qiime2/barplot/level-?.csv",
                ["qiime2/barplot/level-3.csv", "qiime2/barplot/level-4.csv"],
            ),
            (
                "qiime2/barplot/level-[34].csv",
                ["qiime2/barplot/level-3.csv", "qiime2/barplot/level-4.csv"],
            ),
            ("nothing/here*", []),
        ],
    )
    def test_glob(self, root, pattern, expected):
        assert root.glob(pattern) == expected

    def test_glob_returns_directories_too(self, root):
        """``Path.glob`` yields directories, so the S3 side synthesises them."""
        assert root.glob("qiime2/*") == ["qiime2/barplot"]
        assert root.glob("run_*") == ["run_1", "run_2"]

    def test_match_falls_back_to_the_relative_path_for_a_path_regex(self, root):
        """A regex spelling a path cannot match a basename, so the path is tried."""
        assert root.match(r"qiime2/barplot/level-3\.csv") == ["qiime2/barplot/level-3.csv"]

    def test_match_on_a_basename_regex_reaches_every_directory(self, root):
        assert root.match(r"level-\d+\.csv") == [
            "qiime2/barplot/level-3.csv",
            "qiime2/barplot/level-4.csv",
            "run_1/qiime2/barplot/level-3.csv",
        ]

    def test_match_within_a_run_returns_root_relative_paths(self, root):
        """``within`` scopes the path fallback; the answer stays root-relative."""
        assert root.match(r"qiime2/barplot/level-3\.csv", within="run_1") == [
            "run_1/qiime2/barplot/level-3.csv"
        ]

    def test_match_within_a_run_still_matches_basenames(self, root):
        assert root.match(r"params_.*\.json", within="run_2") == [
            "run_2/pipeline_info/params_2026-02-01.json"
        ]

    def test_match_of_an_absent_within_is_empty_not_an_error(self, root):
        assert root.match(r".*", within="run_9") == []

    def test_runs(self, root):
        assert root.runs(r"run_\d+") == ["run_1", "run_2"]

    def test_runs_excludes_non_matching_directories(self, root):
        """logs/ is a directory but not a run, and no file is ever a run."""
        assert "logs" not in root.runs(r"run_\d+")
        assert root.runs(r".*") == [
            "input",
            "logs",
            "pipeline_info",
            "qiime2",
            "run_1",
            "run_2",
        ]

    @pytest.mark.parametrize("rel", TREE)
    def test_relative_of_reverses_url(self, root, rel):
        assert root.relative_of(root.url(rel)) == rel

    def test_relative_of_accepts_a_path_already_relative(self, root):
        assert root.relative_of("run_1/qiime2/barplot/level-3.csv") == (
            "run_1/qiime2/barplot/level-3.csv"
        )

    @pytest.mark.parametrize("rel", ["input/Samplesheet_full.tsv", "qiime2/barplot/level-4.csv"])
    def test_read_bytes_round_trip(self, root, rel):
        assert root.read_bytes(rel) == _body(rel)

    def test_read_bytes_of_an_absent_file_names_the_location(self, root):
        with pytest.raises(FileNotFoundError) as excinfo:
            root.read_bytes("pipeline_info/params_2026-01-17.json")
        assert root.url("pipeline_info/params_2026-01-17.json") in str(excinfo.value)

    def test_read_head_reads_the_start_and_sizes_the_whole(self, root):
        rel = "input/Samplesheet_full.tsv"
        assert root.read_head(rel, 8) == (_body(rel)[:8], len(_body(rel)))

    def test_read_head_past_the_end_is_the_whole_file(self, root):
        rel = "logs/nextflow.log"
        assert root.read_head(rel, 1024) == (_body(rel), len(_body(rel)))

    def test_read_head_of_nothing_still_sizes_the_file(self, root):
        rel = "logs/nextflow.log"
        assert root.read_head(rel, 0) == (b"", len(_body(rel)))

    @pytest.mark.parametrize("rel", ["pipeline_info/params_2026-01-17.json", "pipeline_info"])
    def test_read_head_of_anything_but_a_file_is_absent(self, root, rel):
        with pytest.raises(FileNotFoundError):
            root.read_head(rel, 8)


# ── the two sides where they legitimately differ ─────────────────────────────


class TestLocalSpecifics:
    def test_url_is_an_absolute_filesystem_path(self, tmp_path):
        root = data_root_for(str(tmp_path / "results"))
        assert root.url("input/x.tsv") == str(tmp_path / "results" / "input" / "x.tsv")

    def test_relative_of_rejects_a_path_outside_the_root(self, tmp_path):
        root = data_root_for(str(tmp_path / "results"))
        assert root.relative_of(str(tmp_path / "elsewhere" / "x.tsv")) is None

    def test_relative_of_rejects_an_s3_url(self, tmp_path):
        root = data_root_for(str(tmp_path))
        assert root.relative_of("s3://bucket/x.tsv") is None

    def test_relative_of_rejects_an_escape(self, tmp_path):
        root = data_root_for(str(tmp_path / "results"))
        assert root.relative_of("../elsewhere/x.tsv") is None

    def test_storage_options_are_none(self, tmp_path):
        assert data_root_for(str(tmp_path)).storage_options() is None

    def test_a_missing_root_answers_empty_rather_than_raising(self, tmp_path):
        root = data_root_for(str(tmp_path / "absent"))
        assert root.exists("anything") is False
        assert root.glob("*") == []
        assert root.runs(r".*") == []
        assert root.match(r".*") == []


class TestS3Specifics:
    def test_url_is_an_s3_url(self, monkeypatch):
        install_s3_listing(monkeypatch, {})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.url("input/x.tsv") == f"s3://{S3_BUCKET}/{S3_KEY_PREFIX}input/x.tsv"
        assert root.url("") == S3_ROOT

    def test_relative_of_rejects_another_bucket(self, monkeypatch):
        install_s3_listing(monkeypatch, {})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.relative_of(f"s3://other-bucket/{S3_KEY_PREFIX}x.tsv") is None

    def test_relative_of_rejects_another_prefix_in_the_same_bucket(self, monkeypatch):
        install_s3_listing(monkeypatch, {})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.relative_of(f"s3://{S3_BUCKET}/other/x.tsv") is None

    def test_relative_of_takes_the_root_itself_as_empty(self, monkeypatch):
        install_s3_listing(monkeypatch, {})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.relative_of(S3_ROOT) == ""

    def test_a_prefix_without_a_trailing_slash_does_not_swallow_a_sibling(self, monkeypatch):
        """S3 prefixes are string matches, so ``results`` would also list ``results-old``."""
        install_s3_listing(
            monkeypatch,
            {
                f"{S3_KEY_PREFIX}kept.csv": b"kept",
                "projects/results-old/leaked.csv": b"leaked",
            },
        )
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.glob("**/*.csv") == ["kept.csv"]

    def test_the_name_of_a_bare_bucket_is_the_bucket(self, monkeypatch):
        install_s3_listing(monkeypatch, {})
        root = data_root_for(f"s3://{S3_BUCKET}", s3_cli_config())
        assert root.name == S3_BUCKET

    def test_objects_expose_the_raw_listing(self, monkeypatch):
        install_s3_listing(monkeypatch, {f"{S3_KEY_PREFIX}{rel}": _body(rel) for rel in TREE})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert [obj.relative for obj in root.objects] == TREE
        assert root.objects[0].url == f"s3://{S3_BUCKET}/{S3_KEY_PREFIX}{TREE[0]}"
        assert root.objects[0].etag == f"{S3_KEY_PREFIX}{TREE[0]}-etag"

    def test_the_client_is_built_once_and_reused(self, monkeypatch):
        bodies = {f"{S3_KEY_PREFIX}{rel}": _body(rel) for rel in TREE}
        client = install_s3_listing(monkeypatch, bodies)
        root = data_root_for(S3_ROOT, s3_cli_config())
        root.read_bytes(TREE[0])
        root.read_bytes(TREE[1])
        assert client.get_object_calls == [f"{S3_KEY_PREFIX}{TREE[0]}", f"{S3_KEY_PREFIX}{TREE[1]}"]

    def test_one_listing_answers_every_question(self, monkeypatch):
        """The whole point: fifty questions, one paginated listing."""
        client = install_s3_listing(
            monkeypatch, {f"{S3_KEY_PREFIX}{rel}": _body(rel) for rel in TREE}
        )
        root = data_root_for(S3_ROOT, s3_cli_config())
        pages_after_construction = client.pages_served

        root.exists("run_1")
        root.glob("**/*.csv")
        root.match(r"level-\d+\.csv")
        root.runs(r"run_\d+")

        assert client.pages_served == pages_after_construction == 1


class TestTruncation:
    def test_truncated_when_the_listing_hits_max_keys(self, monkeypatch):
        bodies = {f"{S3_KEY_PREFIX}f{i}.csv": b"x" for i in range(10)}
        install_s3_listing(monkeypatch, bodies, page_size=5)
        root = S3DataRoot(S3_ROOT, s3_cli_config(), max_keys=5)
        assert root.truncated is True
        assert len(root.objects) == 5

    def test_a_listing_ending_on_the_budget_is_complete(self, monkeypatch):
        bodies = {f"{S3_KEY_PREFIX}f{i}.csv": b"x" for i in range(10)}
        install_s3_listing(monkeypatch, bodies, page_size=5, is_truncated=False)
        root = S3DataRoot(S3_ROOT, s3_cli_config(), max_keys=10)
        assert root.truncated is False
        assert len(root.objects) == 10

    def test_a_truncated_listing_does_not_claim_an_object_is_absent(self, monkeypatch):
        """A partial view is not authoritative, so the read goes to S3 anyway."""
        bodies = {f"{S3_KEY_PREFIX}f{i}.csv": f"body {i}".encode() for i in range(10)}
        install_s3_listing(monkeypatch, bodies, page_size=5)
        root = S3DataRoot(S3_ROOT, s3_cli_config(), max_keys=5)
        assert root.read_bytes("f9.csv") == b"body 9"

    def test_read_head_asks_s3_for_a_range_only(self, monkeypatch):
        body = b"0123456789" * 10
        client = install_s3_listing(monkeypatch, {f"{S3_KEY_PREFIX}big.txt": body})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.read_head("big.txt", 16) == (body[:16], len(body))
        assert client.get_object_ranges == ["bytes=0-15"]

    def test_read_head_sizes_an_object_from_its_content_range(self, monkeypatch):
        """A key past a truncated listing has no listed size: S3's answer gives it."""
        bodies = {f"{S3_KEY_PREFIX}f{i}.csv": f"body {i}".encode() * 3 for i in range(10)}
        install_s3_listing(monkeypatch, bodies, page_size=5)
        root = S3DataRoot(S3_ROOT, s3_cli_config(), max_keys=5)
        assert "f9.csv" not in {obj.relative for obj in root.objects}
        assert root.read_head("f9.csv", 4) == (b"body", len(b"body 9" * 3))

    def test_read_head_of_an_empty_object_asks_nothing(self, monkeypatch):
        """A range on an empty object is an error, and there is nothing to read."""
        client = install_s3_listing(monkeypatch, {f"{S3_KEY_PREFIX}empty.txt": b""})
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.read_head("empty.txt", 16) == (b"", 0)
        assert client.get_object_calls == []

    def test_read_head_reads_no_more_than_asked_from_a_store_ignoring_the_range(self, monkeypatch):
        class _WholeObjects(StubS3Client):
            def get_object(self, Bucket, Key, Range=None):  # noqa: N803 - boto3's spelling
                return super().get_object(Bucket, Key)

        body = b"x" * 100
        install_s3_client(monkeypatch, _WholeObjects({f"{S3_KEY_PREFIX}big.txt": body}))
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.read_head("big.txt", 10) == (b"x" * 10, 100)


class TestReadDecision:
    """How a root is read is decided from configuration, before any request.

    A bucket name must never become an existence or region oracle, and the
    server never reads a user-named location with the instance's credentials.
    """

    def test_an_unlisted_bucket_without_project_storage_is_refused(
        self, no_bucket_lists, no_client
    ):
        with pytest.raises(S3AccessRefused) as exc:
            data_root_for("s3://someone-elses-bucket/data", None)
        assert exc.value.code == "s3_refused"
        assert exc.value.status_code == 422

    def test_an_ambient_aws_key_is_not_enough_on_the_server(
        self, monkeypatch, no_bucket_lists, no_client
    ):
        """The server's own credentials read only the buckets an administrator lists."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
        with pytest.raises(S3AccessRefused):
            data_root_for("s3://private-bucket/data", None)

    def test_the_server_never_falls_back_to_the_instance_credentials(
        self, no_bucket_lists, no_client
    ):
        cfg = SimpleNamespace(remote_storage_options=None, s3_storage=_s3_storage())
        with pytest.raises(S3AccessRefused):
            data_root_for(S3_ROOT, cfg)

    def test_the_instance_bucket_is_refused_even_when_listed_public(self, monkeypatch, no_client):
        """That bucket holds every project's data: refused before the public list."""
        bucket = S3DepictioCLIConfig().bucket
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", bucket)
        with pytest.raises(S3AccessRefused, match="instance's own data"):
            data_root_for(f"s3://{bucket}/projects/run42", None)

    def test_an_allowlisted_bucket_is_accepted_without_credentials(
        self, monkeypatch, no_bucket_lists
    ):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")
        install_s3_listing(monkeypatch, {"run42/x.csv": b"x"})
        root = data_root_for("s3://open-data/run42", None)
        assert root.is_remote is True
        assert root.exists("x.csv")

    def test_project_storage_is_enough(self, monkeypatch, no_bucket_lists):
        install_s3_listing(monkeypatch, {})
        assert data_root_for("s3://private-bucket/data", s3_cli_config()).is_remote is True

    def test_the_cli_reads_with_its_own_configuration(self, monkeypatch, no_bucket_lists):
        """CLI context keeps its order: no project storage, the config's S3 keys."""
        monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
        install_s3_listing(monkeypatch, {})
        cfg = SimpleNamespace(remote_storage_options=None, s3_storage=_s3_storage())
        options = data_root_for(S3_ROOT, cfg).storage_options()
        assert options["aws_access_key_id"] == "minio"
        assert options["aws_secret_access_key"] == "minio123"
        assert options["aws_endpoint_url"] == _s3_storage().endpoint_url


class TestStorageOptions:
    """What polars is handed is the target the root was listed with."""

    @pytest.fixture(autouse=True)
    def listing(self, monkeypatch, no_bucket_lists):
        """An empty listing, and each bucket answering from a region named after it."""
        install_s3_listing(monkeypatch, {})
        monkeypatch.setattr(
            data_root_module,
            "ensure_region",
            lambda target: target.with_region(f"region-of-{target.bucket}"),
        )

    def test_an_allowlisted_prefix_is_read_unsigned(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")
        options = data_root_for("s3://open-data/run42", None).storage_options()
        assert options == {"aws_skip_signature": "true", "aws_region": "region-of-open-data"}

    def test_the_project_storage_is_used_as_configured(self):
        options = data_root_for(S3_ROOT, s3_cli_config()).storage_options()
        assert options["aws_endpoint_url"] == "https://s3.example"
        assert options["aws_access_key_id"] == "k"
        assert options["aws_secret_access_key"] == "s"
        assert options["aws_region"] == f"region-of-{S3_BUCKET}"
        assert "aws_skip_signature" not in options

    def test_a_credentialed_bucket_hands_polars_no_credentials(self, monkeypatch):
        """Read with the server's own chain: object-store finds it by itself."""
        monkeypatch.setenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", "private-bucket")
        options = data_root_for("s3://private-bucket/run42", None).storage_options()
        assert options == {"aws_region": "region-of-private-bucket"}

    def test_a_scoped_view_reads_with_its_parents_target(self):
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.scoped("run_1").storage_options() == root.storage_options()


class TestS3Failures:
    """Failures come out coded, sanitized, and with "absent" kept apart."""

    def test_an_absent_prefix_is_an_empty_root(self, monkeypatch):
        """Some gateways answer a prefix that holds nothing with a 404."""
        install_s3_client(monkeypatch, FailingS3Client("NoSuchKey", 404))
        root = data_root_for(S3_ROOT, s3_cli_config())
        assert root.objects == []
        assert root.exists("anything") is False

    def test_a_missing_bucket_is_coded(self, monkeypatch):
        install_s3_client(monkeypatch, FailingS3Client("NoSuchBucket", 404))
        with pytest.raises(S3AccessFailed) as exc:
            data_root_for(S3_ROOT, s3_cli_config())
        assert exc.value.code == "s3_no_such_bucket"
        assert f"'{S3_BUCKET}'" in exc.value.detail

    def test_a_denied_read_is_coded_and_names_no_endpoint(self, monkeypatch):
        class _DeniedReads(StubS3Client):
            def get_object(self, Bucket, Key):  # noqa: N803 - boto3's own spelling
                raise s3_client_error("AccessDenied", 403, "GetObject")

        install_s3_client(monkeypatch, _DeniedReads({f"{S3_KEY_PREFIX}x.csv": b"x"}))
        root = data_root_for(S3_ROOT, s3_cli_config())
        with pytest.raises(S3AccessFailed) as exc:
            root.read_bytes("x.csv")
        assert exc.value.code == "s3_access_denied"
        assert f"{S3_ROOT}/x.csv" in exc.value.detail
        assert "s3.example" not in exc.value.detail

    def test_a_denied_ranged_read_is_coded_alike(self, monkeypatch):
        class _DeniedReads(StubS3Client):
            def get_object(self, Bucket, Key, Range=None):  # noqa: N803 - boto3's spelling
                raise s3_client_error("AccessDenied", 403, "GetObject")

        install_s3_client(monkeypatch, _DeniedReads({f"{S3_KEY_PREFIX}x.csv": b"x"}))
        root = data_root_for(S3_ROOT, s3_cli_config())
        with pytest.raises(S3AccessFailed) as exc:
            root.read_head("x.csv", 8)
        assert exc.value.code == "s3_access_denied"
        assert "s3.example" not in exc.value.detail

    def test_an_object_gone_since_a_truncated_listing_is_absent(self, monkeypatch):
        """A partial listing sends the read to S3; NoSuchKey there is "absent"."""

        class _Gone(StubS3Client):
            def get_object(self, Bucket, Key):  # noqa: N803 - boto3's own spelling
                raise s3_client_error("NoSuchKey", 404, "GetObject")

        bodies = {f"{S3_KEY_PREFIX}f{i}.csv": b"x" for i in range(10)}
        install_s3_client(monkeypatch, _Gone(bodies, page_size=5))
        root = S3DataRoot(S3_ROOT, s3_cli_config(), max_keys=5)
        assert root.truncated is True
        with pytest.raises(FileNotFoundError):
            root.read_bytes("f9.csv")


# ── the listing primitive ────────────────────────────────────────────────────


class TestListS3Objects:
    @pytest.fixture(autouse=True)
    def public_bucket(self, monkeypatch):
        """Bucket ``b`` allowlisted, so a listing without configuration is allowed."""
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "b")

    def test_returns_keys_relative_to_the_prefix(self, monkeypatch):
        install_s3_listing(
            monkeypatch,
            {"run42/a.csv": b"a", "run42/nested/b.csv": b"b"},
        )
        objects, truncated = list_s3_objects("s3://b/run42/", None)
        assert [obj.relative for obj in objects] == ["a.csv", "nested/b.csv"]
        assert [obj.url for obj in objects] == ["s3://b/run42/a.csv", "s3://b/run42/nested/b.csv"]
        assert truncated is False

    def test_console_folder_placeholders_are_skipped(self, monkeypatch):
        install_s3_listing(monkeypatch, {"run42/a.csv": b"a", "run42/notes/": b""})
        objects, _ = list_s3_objects("s3://b/run42/", None)
        assert [obj.key for obj in objects] == ["run42/a.csv"]

    def test_etag_is_unquoted_and_size_carried(self, monkeypatch):
        install_s3_listing(monkeypatch, {"run42/a.csv": b"abc"})
        objects, _ = list_s3_objects("s3://b/run42/", None)
        assert objects[0].etag == "run42/a.csv-etag"
        assert objects[0].size == 3
        assert objects[0].last_modified is None

    def test_a_non_s3_prefix_is_rejected_before_any_client(self, no_client):
        with pytest.raises(ValueError, match="s3:// prefix"):
            list_s3_objects("https://host/d/", None)

    def test_a_prefix_without_a_bucket_is_rejected(self, no_client):
        with pytest.raises(ValueError, match="no bucket"):
            list_s3_objects("s3://", None)

    def test_an_unlisted_bucket_is_refused_before_any_client(self, no_client):
        with pytest.raises(S3AccessRefused):
            list_s3_objects("s3://not-listed/run42/", None)
