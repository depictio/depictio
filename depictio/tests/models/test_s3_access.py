"""Tests for the S3 read target resolution and the one boto3 factory.

The resolver is configuration only, so most of this runs with no network at
all. The calls that do talk to S3 (HeadBucket for the region, ListObjectsV2)
run against botocore's Stubber, which also fails a test on any call it was not
told to expect (``list_buckets`` included).
"""

import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3
import polars as pl
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
from botocore.stub import Stubber

from depictio.models import s3_access
from depictio.models.s3_access import (
    AWS_DEFAULT_REGION,
    ProjectS3Config,
    S3AccessError,
    S3AccessFailed,
    S3AccessRefused,
    S3Target,
    bucket_list_matches,
    ensure_region,
    is_instance_bucket,
    iter_object_pages,
    parse_bucket_list,
    probe_bucket,
    resolve_s3_target,
    split_s3_url,
)

INSTANCE_ENDPOINT = "http://s3:9000"
INSTANCE_KEY = "instance-root-key"
INSTANCE_SECRET = "instance-root-secret-value"


@dataclass
class _Policy:
    public_s3_buckets: str = ""
    credentialed_s3_buckets: str = ""
    timeout_s: float = 12.0


@dataclass
class _Instance:
    bucket: str = "depictio-bucket"
    endpoint_url: str = INSTANCE_ENDPOINT
    aws_access_key_id: str = INSTANCE_KEY
    aws_secret_access_key: str = INSTANCE_SECRET
    verify_tls: bool = True


def _project(**overrides) -> ProjectS3Config:
    fields = {
        "endpoint_url": "https://s3.example.org",
        "bucket": "lab-bucket",
        "region": "eu-central-1",
        "access_key_id": "PROJECTKEY",
        "secret_access_key": "project-secret",
        **overrides,
    }
    return ProjectS3Config(**fields)


def _resolve(url, *, context="server", project=None, instance=None, policy=None):
    return resolve_s3_target(
        url,
        context=context,
        project_storage=project,
        instance_s3=instance if instance is not None else _Instance(),
        policy=policy or _Policy(),
    )


@pytest.fixture(autouse=True)
def _clean_region_cache():
    s3_access._bucket_regions.clear()
    yield
    s3_access._bucket_regions.clear()


@pytest.fixture
def no_session_token(monkeypatch):
    for name in ("AWS_SESSION_TOKEN", "AWS_TOKEN", "SESSION_TOKEN", "TOKEN", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


# ── Locations and lists ─────────────────────────────────────────────────────


class TestLocations:
    def test_bucket_and_key(self):
        assert split_s3_url("s3://bucket/a/b.csv") == ("bucket", "a/b.csv")
        assert split_s3_url("S3://bucket") == ("bucket", "")

    def test_the_key_is_kept_verbatim(self):
        """S3 keys may hold characters a URL parser would cut at."""
        assert split_s3_url("s3://bucket/a#b?c") == ("bucket", "a#b?c")

    @pytest.mark.parametrize(
        "url", ["https://bucket/a", "s3://", "s3:///key", "s3://user:pw@bucket/k", "bucket/k"]
    )
    def test_anything_else_is_refused(self, url):
        with pytest.raises(S3AccessRefused) as exc:
            split_s3_url(url)
        assert exc.value.code == "s3_refused"
        assert exc.value.status_code == 422

    def test_a_refusal_is_still_a_value_error(self):
        """The scan and preview paths catch ValueError; they keep catching this."""
        with pytest.raises(ValueError):
            split_s3_url("s3://")


class TestBucketLists:
    def test_entries_are_comma_separated_and_tolerate_slashes(self):
        assert parse_bucket_list(" first , second/runs/ , /third/ ,,") == [
            ("first", ""),
            ("second", "runs"),
            ("third", ""),
        ]

    def test_a_prefix_only_matches_on_a_path_boundary(self):
        assert bucket_list_matches("bucket/data", "bucket", "data/x.csv")
        assert bucket_list_matches("bucket/data", "bucket", "data")
        assert not bucket_list_matches("bucket/data", "bucket", "database/secrets.csv")

    def test_bucket_names_stay_case_sensitive(self):
        assert bucket_list_matches("MyBucket", "MyBucket", "a")
        assert not bucket_list_matches("MyBucket", "mybucket", "a")


# ── Resolver ────────────────────────────────────────────────────────────────


class TestServerContext:
    def test_nothing_is_readable_without_configuration(self):
        with pytest.raises(S3AccessRefused, match="cannot be read by the server") as exc:
            _resolve("s3://someone-elses/data.csv")
        assert exc.value.code == "s3_refused"

    def test_a_public_bucket_is_read_unsigned_on_aws(self):
        target = _resolve("s3://open-data/x.parquet", policy=_Policy(public_s3_buckets="open-data"))

        assert target.kind == "public"
        assert target.unsigned is True
        assert target.endpoint_url is None
        assert target.access_key_id is None
        assert target.timeout_s == 12.0

    def test_a_prefix_entry_does_not_open_the_whole_bucket(self):
        with pytest.raises(S3AccessRefused):
            _resolve("s3://shared/private/x.csv", policy=_Policy(public_s3_buckets="shared/public"))

    def test_project_storage_is_used_alone(self):
        target = _resolve("s3://lab-bucket/run1/x.csv", project=_project())

        assert target.kind == "project"
        assert target.endpoint_url == "https://s3.example.org"
        assert target.region == "eu-central-1"
        assert (target.access_key_id, target.secret_access_key) == (
            "PROJECTKEY",
            "project-secret",
        )
        assert target.unsigned is False

    def test_project_storage_without_a_key_reads_unsigned_at_its_endpoint(self):
        target = _resolve(
            "s3://lab-bucket/x.csv", project=_project(access_key_id="", secret_access_key="")
        )

        assert target.kind == "project"
        assert target.unsigned is True
        assert target.endpoint_url == "https://s3.example.org"
        assert target.access_key_id is None

    def test_a_key_without_its_secret_never_picks_up_the_instance_keys(self):
        """The credential-mixing bug: an empty secret was completed with the root one."""
        with pytest.raises(S3AccessRefused, match="without its secret"):
            _resolve("s3://lab-bucket/x.csv", project=_project(secret_access_key=""))

    def test_a_secret_without_its_key_is_refused_too(self):
        with pytest.raises(S3AccessRefused):
            _resolve("s3://lab-bucket/x.csv", project=_project(access_key_id=""))

    def test_a_credentialed_bucket_reads_with_the_ambient_chain(self):
        target = _resolve(
            "s3://lab-shared/results/x.csv",
            policy=_Policy(credentialed_s3_buckets="lab-shared/results"),
        )

        assert target.kind == "ambient"
        assert target.access_key_id is None
        assert target.endpoint_url is None
        assert target.unsigned is False

    def test_the_credentialed_list_honours_its_prefix(self):
        with pytest.raises(S3AccessRefused):
            _resolve(
                "s3://lab-shared/other/x.csv",
                policy=_Policy(credentialed_s3_buckets="lab-shared/results"),
            )

    def test_the_project_storage_wins_over_the_credentialed_list(self):
        target = _resolve(
            "s3://lab-shared/x.csv",
            project=_project(),
            policy=_Policy(credentialed_s3_buckets="lab-shared"),
        )
        assert target.kind == "project"

    def test_the_instance_keys_are_never_used(self):
        for url, policy in (
            ("s3://open-data/x", _Policy(public_s3_buckets="open-data")),
            ("s3://lab-shared/x", _Policy(credentialed_s3_buckets="lab-shared")),
        ):
            target = _resolve(url, policy=policy)
            assert target.kind != "instance"
            assert INSTANCE_SECRET not in str(target.polars_options())


class TestInstanceBucket:
    """The instance bucket holds every project's data: refused before anything else."""

    @pytest.mark.parametrize(
        "project, policy",
        [
            (None, _Policy()),
            (None, _Policy(public_s3_buckets="depictio-bucket")),
            (None, _Policy(credentialed_s3_buckets="depictio-bucket")),
            (_project(endpoint_url=INSTANCE_ENDPOINT), _Policy()),
        ],
        ids=["plain", "listed-public", "listed-credentialed", "project-config"],
    )
    def test_refused_in_server_context_whatever_else_matches(self, project, policy):
        with pytest.raises(S3AccessRefused, match="instance's own data"):
            _resolve("s3://depictio-bucket/6512ab/part-0.parquet", project=project, policy=policy)

    def test_the_same_url_is_read_with_the_cli_configuration(self):
        target = _resolve("s3://depictio-bucket/6512ab/part-0.parquet", context="cli")

        assert target.kind == "instance"
        assert target.endpoint_url == INSTANCE_ENDPOINT
        assert target.access_key_id == INSTANCE_KEY

    def test_an_aws_instance_bucket_is_refused_from_any_endpoint(self):
        """On AWS a bucket name is global: the instance's bucket is the same one
        from a regional, a virtual-hosted or the default endpoint, so a project
        config pointing anywhere at it is refused too."""
        instance = _Instance(
            bucket="acme-depictio", endpoint_url="https://s3.eu-west-1.amazonaws.com"
        )
        for project in (
            None,
            _project(endpoint_url="https://s3.amazonaws.com"),
            _project(endpoint_url="https://acme-depictio.s3.eu-west-1.amazonaws.com"),
        ):
            with pytest.raises(S3AccessRefused):
                _resolve("s3://acme-depictio/x.parquet", project=project, instance=instance)

    def test_other_buckets_of_an_aws_instance_are_not_refused_as_the_instance(self):
        instance = _Instance(bucket="acme-depictio", endpoint_url="https://s3.amazonaws.com")
        target = _resolve("s3://acme-depictio-raw/x.csv", project=_project(), instance=instance)
        assert target.kind == "project"

    def test_compared_by_name_only(self):
        assert is_instance_bucket("depictio-bucket", _Instance())
        assert not is_instance_bucket("depictio-bucket-2", _Instance())
        assert not is_instance_bucket("depictio-bucket", None)
        assert not is_instance_bucket("", _Instance(bucket=""))


class TestCliContext:
    def test_public_first(self):
        target = _resolve(
            "s3://open-data/x", context="cli", policy=_Policy(public_s3_buckets="open-data")
        )
        assert target.kind == "public"

    def test_then_the_project(self):
        target = _resolve("s3://lab-bucket/x", context="cli", project=_project())
        assert target.kind == "project"
        assert target.access_key_id == "PROJECTKEY"

    def test_then_the_configuration_s3_credentials(self):
        target = _resolve("s3://anything/x", context="cli")
        assert target.kind == "instance"
        assert target.secret_access_key == INSTANCE_SECRET

    def test_then_the_ambient_chain_when_the_configuration_has_no_keys(self):
        target = _resolve(
            "s3://anything/x", context="cli", instance=_Instance(aws_secret_access_key="")
        )
        assert target.kind == "ambient"

    def test_a_project_key_without_secret_is_refused_here_too(self):
        with pytest.raises(S3AccessRefused):
            _resolve("s3://lab-bucket/x", context="cli", project=_project(secret_access_key=""))


class TestProjectS3Config:
    def test_the_polars_spelling_loads(self):
        config = ProjectS3Config.model_validate(
            {
                "aws_endpoint_url": "https://s3.example.org",
                "aws_access_key_id": "K",
                "aws_secret_access_key": "S",
                "aws_region": "eu-west-3",
            }
        )
        assert (config.endpoint_url, config.access_key_id, config.region) == (
            "https://s3.example.org",
            "K",
            "eu-west-3",
        )

    def test_the_secret_stays_out_of_the_repr(self):
        assert "project-secret" not in repr(_project())

    def test_missing_values_default(self):
        config = ProjectS3Config(
            endpoint_url="https://s3.example.org", region="", access_key_id=None
        )
        assert config.region == AWS_DEFAULT_REGION
        assert config.access_key_id == ""


# ── The boto3 factory ───────────────────────────────────────────────────────


class TestClientFactory:
    def test_a_signed_target_with_an_endpoint(self):
        target = _resolve("s3://lab-bucket/x", project=_project())
        client = target.client()
        config = client.meta.config

        assert config.signature_version == "s3v4"
        # The EMBL gateway rejects the default CRC checksums of boto3 >= 1.36.
        assert config.request_checksum_calculation == "when_required"
        assert config.response_checksum_validation == "when_required"
        assert config.s3 == {"addressing_style": "path"}
        assert config.retries == {"mode": "standard", "total_max_attempts": 3}
        assert (config.connect_timeout, config.read_timeout) == (12.0, 12.0)
        assert client.meta.endpoint_url == "https://s3.example.org"
        assert client.meta.region_name == "eu-central-1"
        credentials = client._request_signer._credentials
        assert (credentials.access_key, credentials.secret_key) == ("PROJECTKEY", "project-secret")

    def test_an_unsigned_target_on_aws_keeps_the_default_addressing(self):
        from botocore import UNSIGNED

        target = _resolve("s3://open-data/x", policy=_Policy(public_s3_buckets="open-data"))
        config = target.client().meta.config

        assert config.signature_version is UNSIGNED
        assert config.request_checksum_calculation == "when_required"
        assert not config.s3

    def test_keys_are_passed_only_for_signed_project_and_instance_targets(self, monkeypatch):
        seen: list[dict] = []
        monkeypatch.setattr(boto3, "client", lambda service, **kwargs: seen.append(kwargs))

        _resolve("s3://lab-shared/x", policy=_Policy(credentialed_s3_buckets="lab-shared")).client()
        _resolve("s3://open/x", policy=_Policy(public_s3_buckets="open")).client()
        _resolve("s3://lab/x", project=_project(access_key_id="", secret_access_key="")).client()
        _resolve("s3://lab/x", context="cli").client()

        assert [(k["aws_access_key_id"], k["aws_secret_access_key"]) for k in seen] == [
            (None, None),
            (None, None),
            (None, None),
            (INSTANCE_KEY, INSTANCE_SECRET),
        ]

    def test_tls_verification_follows_the_instance_setting(self, monkeypatch):
        seen: list[dict] = []
        monkeypatch.setattr(boto3, "client", lambda service, **kwargs: seen.append(kwargs))

        _resolve("s3://lab/x", context="cli", instance=_Instance(verify_tls=False)).client()

        assert seen[0]["verify"] is False

    def test_the_keys_stay_out_of_the_repr(self):
        target = _resolve("s3://lab/x", context="cli")
        assert INSTANCE_SECRET not in repr(target)
        assert INSTANCE_KEY not in repr(target)


class TestPolarsOptions:
    def test_public(self):
        target = _resolve("s3://open/x", policy=_Policy(public_s3_buckets="open")).with_region(
            "eu-west-1"
        )
        assert target.polars_options() == {"aws_skip_signature": "true", "aws_region": "eu-west-1"}

    def test_project_signed(self, no_session_token):
        options = _resolve("s3://lab/x", project=_project()).polars_options()
        assert options == {
            "aws_endpoint_url": "https://s3.example.org",
            "aws_allow_http": "false",
            "aws_region": "eu-central-1",
            "aws_access_key_id": "PROJECTKEY",
            "aws_secret_access_key": "project-secret",
        }

    def test_project_unsigned(self):
        options = _resolve(
            "s3://lab/x",
            project=_project(
                endpoint_url="http://gw.lab:9000", access_key_id="", secret_access_key=""
            ),
        ).polars_options()
        assert options == {
            "aws_endpoint_url": "http://gw.lab:9000",
            "aws_allow_http": "true",
            "aws_region": "eu-central-1",
            "aws_skip_signature": "true",
        }

    def test_ambient_sets_nothing_but_the_region(self):
        target = _resolve("s3://lab/x", policy=_Policy(credentialed_s3_buckets="lab"))
        assert target.polars_options() == {}
        assert target.with_region("us-west-2").polars_options() == {"aws_region": "us-west-2"}

    def test_instance_without_tls_verification(self, no_session_token):
        options = _resolve(
            "s3://lab/x", context="cli", instance=_Instance(verify_tls=False)
        ).polars_options()
        assert options["allow_invalid_certificates"] == "true"
        assert options["aws_access_key_id"] == INSTANCE_KEY

    @pytest.mark.parametrize(
        "var", ["AWS_SESSION_TOKEN", "AWS_TOKEN", "TOKEN", "aws_session_token"]
    )
    def test_a_foreign_session_token_is_given_empty(self, no_session_token, monkeypatch, var):
        monkeypatch.setenv(var, "users-own-session-token")
        for target in (
            _resolve("s3://lab/x", project=_project()),
            _resolve("s3://x/y", context="cli"),
        ):
            assert target.polars_options()["aws_session_token"] == ""

    def test_a_token_for_the_same_key_is_left_alone(self, no_session_token, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "PROJECTKEY")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "its-own-token")
        assert (
            "aws_session_token" not in _resolve("s3://lab/x", project=_project()).polars_options()
        )

    def test_unsigned_targets_carry_no_token_at_all(self, no_session_token, monkeypatch):
        monkeypatch.setenv("AWS_SESSION_TOKEN", "users-own-session-token")
        target = _resolve("s3://open/x", policy=_Policy(public_s3_buckets="open"))
        assert "aws_session_token" not in target.polars_options()


class _RecordingS3(BaseHTTPRequestHandler):
    """Answers every request with a 404, after noting its headers."""

    seen: list[dict[str, str]] = []

    def _answer(self):
        type(self).seen.append({k.lower(): v for k, v in self.headers.items()})
        body = b"<Error><Code>NoSuchKey</Code></Error>"
        self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_HEAD = _answer

    def log_message(self, *args):
        pass


def test_a_polars_read_never_sends_the_users_session_token(no_session_token, monkeypatch):
    """Real polars, against a stand-in for a project's endpoint."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    _RecordingS3.seen = []
    server = HTTPServer(("127.0.0.1", 0), _RecordingS3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("AWS_SESSION_TOKEN", "users-own-session-token")
        target = _resolve(
            "s3://lab/x.parquet",
            context="cli",
            project=_project(endpoint_url=f"http://127.0.0.1:{server.server_address[1]}"),
        )
        with pytest.raises(Exception):
            pl.scan_parquet(
                "s3://lab/x.parquet", storage_options={**target.polars_options(), "max_retries": 0}
            ).collect()
    finally:
        server.shutdown()
        server.server_close()

    assert _RecordingS3.seen, "polars sent no request"
    assert all(h.get("x-amz-security-token", "") == "" for h in _RecordingS3.seen)
    assert all("Credential=PROJECTKEY/" in h.get("authorization", "") for h in _RecordingS3.seen)


# ── Region ──────────────────────────────────────────────────────────────────


class _StubbedS3:
    """One stubbed client handed to every target, noting the region each asked in."""

    def __init__(self, monkeypatch):
        self.client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
        )
        self.stubber = Stubber(self.client)
        self.stubber.activate()
        self.regions: list[str | None] = []

        def _client(target):
            self.regions.append(target.region)
            return self.client

        monkeypatch.setattr(S3Target, "client", _client)

    def head(self, region_header: str | None = None):
        headers = {"x-amz-bucket-region": region_header} if region_header else {}
        self.stubber.add_response(
            "head_bucket", {"ResponseMetadata": {"HTTPStatusCode": 200, "HTTPHeaders": headers}}
        )

    def head_error(self, code: str, status: int, region_header: str | None = None):
        headers = {"x-amz-bucket-region": region_header} if region_header else {}
        self.stubber.add_client_error(
            "head_bucket",
            service_error_code=code,
            http_status_code=status,
            response_meta={"HTTPHeaders": headers},
        )


@pytest.fixture
def stubbed_s3(monkeypatch):
    stub = _StubbedS3(monkeypatch)
    yield stub
    stub.stubber.assert_no_pending_responses()


def _public(bucket="open-data"):
    return _resolve(f"s3://{bucket}/x", policy=_Policy(public_s3_buckets=bucket))


class TestEnsureRegion:
    def test_the_region_comes_from_the_header(self, stubbed_s3):
        stubbed_s3.head("eu-west-1")
        assert ensure_region(_public()).region == "eu-west-1"

    def test_no_header_keeps_the_configured_region(self, stubbed_s3):
        """The EMBL gateway answers HeadBucket 200 without a region header."""
        stubbed_s3.head(None)
        target = _resolve("s3://lab/x", project=_project())

        assert ensure_region(target).region == "eu-central-1"
        # Answered: not asked again.
        assert ensure_region(target).region == "eu-central-1"
        assert stubbed_s3.regions == ["eu-central-1"]

    def test_a_301_is_retried_once_in_the_region_it_names(self, stubbed_s3):
        stubbed_s3.head_error("PermanentRedirect", 301, "ap-south-1")
        stubbed_s3.head("ap-south-1")
        target = _resolve("s3://lab/x", project=_project())

        assert ensure_region(target).region == "ap-south-1"
        assert stubbed_s3.regions == ["eu-central-1", "ap-south-1"]

    def test_a_denied_head_still_names_the_region(self, stubbed_s3):
        """A public bucket that forbids listing answers 403 with the header."""
        stubbed_s3.head_error("403", 403, "us-west-2")
        assert ensure_region(_public("listing-closed")).region == "us-west-2"

    def test_a_failure_is_not_cached(self, stubbed_s3):
        stubbed_s3.head_error("403", 403, None)
        stubbed_s3.head("eu-west-1")
        target = _public("flaky")

        assert ensure_region(target).region == AWS_DEFAULT_REGION
        assert ensure_region(target).region == "eu-west-1"

    def test_cached_per_kind_endpoint_and_bucket(self, stubbed_s3):
        stubbed_s3.head("eu-west-1")
        stubbed_s3.head("eu-north-1")
        ensure_region(_public("one"))
        ensure_region(_public("one"))
        ensure_region(_public("two"))
        assert len(stubbed_s3.regions) == 2

    def test_an_unreachable_store_keeps_the_region(self, monkeypatch):
        def _boom(target):
            raise EndpointConnectionError(endpoint_url="https://s3.example.org")

        monkeypatch.setattr(S3Target, "client", _boom)
        assert ensure_region(_public()).region == AWS_DEFAULT_REGION

    def test_instance_targets_are_left_alone(self, monkeypatch):
        monkeypatch.setattr(S3Target, "client", lambda target: pytest.fail("no probe expected"))
        target = _resolve("s3://lab/x", context="cli")
        assert ensure_region(target) is target

    def test_probe_raises_what_ensure_swallows(self, stubbed_s3):
        stubbed_s3.head_error("NoSuchBucket", 404)
        with pytest.raises(ClientError):
            probe_bucket(_public())


# ── Errors ──────────────────────────────────────────────────────────────────


def _client_error(code: str, status: int, operation: str = "ListObjectsV2") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "x"},
            "ResponseMetadata": {
                "HTTPStatusCode": status,
                "RequestId": "REQ-1234567890",
                "HostId": "host-id-abcdef",
                "HTTPHeaders": {"x-amz-request-id": "REQ-1234567890"},
            },
        },
        operation,
    )


class TestErrorMapping:
    @pytest.mark.parametrize(
        "code, status, expected, http",
        [
            ("AccessDenied", 403, "s3_access_denied", 422),
            ("InvalidAccessKeyId", 403, "s3_access_denied", 422),
            ("SignatureDoesNotMatch", 403, "s3_access_denied", 422),
            ("NoSuchBucket", 404, "s3_no_such_bucket", 422),
            ("404", 404, "s3_no_such_bucket", 422),
            ("PermanentRedirect", 301, "s3_wrong_region", 502),
            ("AuthorizationHeaderMalformed", 400, "s3_wrong_region", 502),
            ("ServiceUnavailable", 503, "s3_unreachable", 502),
            ("InvalidArgument", 400, "s3_error", 502),
        ],
    )
    def test_client_error_codes(self, code, status, expected, http):
        failure = S3AccessFailed.from_client_error(
            _client_error(code, status), _resolve("s3://lab/run1/", project=_project())
        )
        assert (failure.code, failure.status_code) == (expected, http)
        assert isinstance(failure, S3AccessError)
        assert str(failure) == failure.detail

    def test_the_detail_names_the_location_and_never_internals(self):
        target = _resolve("s3://anything/run1/x.csv", context="cli")
        for code, status in (("AccessDenied", 403), ("NoSuchBucket", 404), ("InternalError", 500)):
            detail = S3AccessFailed.from_client_error(_client_error(code, status), target).detail
            assert "anything" in detail
            for secret in (
                INSTANCE_ENDPOINT,
                "s3:9000",
                INSTANCE_KEY,
                INSTANCE_SECRET,
                "REQ-",
                "host-id",
            ):
                assert secret not in detail

    def test_the_kind_shapes_the_message(self):
        denied = _client_error("AccessDenied", 403)
        project = S3AccessFailed.from_client_error(
            denied, _resolve("s3://lab/x", project=_project())
        )
        public = S3AccessFailed.from_client_error(denied, _public())
        assert "project's storage" in project.detail
        assert "public" in public.detail

    def test_transport_and_credential_errors(self):
        target = _resolve("s3://lab/x", project=_project())
        unreachable = S3AccessFailed.from_exception(
            EndpointConnectionError(endpoint_url="https://s3.example.org"), target
        )
        no_credentials = S3AccessFailed.from_exception(NoCredentialsError(), target)
        assert (unreachable.code, unreachable.status_code) == ("s3_unreachable", 502)
        assert (no_credentials.code, no_credentials.status_code) == ("s3_access_denied", 422)


class TestListing:
    def _paginate(self, stubbed_s3):
        target = _resolve("s3://lab/run1/", project=_project())
        return list(iter_object_pages(target, "run1/"))

    def test_pages_come_through(self, stubbed_s3):
        stubbed_s3.stubber.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "run1/a.csv", "Size": 1}], "IsTruncated": False, "KeyCount": 1},
            {"Bucket": "lab", "Prefix": "run1/"},
        )
        pages = self._paginate(stubbed_s3)
        assert [obj["Key"] for obj in pages[0]["Contents"]] == ["run1/a.csv"]

    @pytest.mark.parametrize("code", ["NoSuchKey", "404"])
    def test_a_404_for_an_absent_prefix_is_an_empty_listing(self, stubbed_s3, code):
        """EMBL Group Volume buckets answer a prefix that holds nothing with a 404."""
        stubbed_s3.stubber.add_client_error(
            "list_objects_v2", service_error_code=code, http_status_code=404
        )
        assert self._paginate(stubbed_s3) == []

    def test_a_missing_bucket_is_an_error(self, stubbed_s3):
        stubbed_s3.stubber.add_client_error(
            "list_objects_v2", service_error_code="NoSuchBucket", http_status_code=404
        )
        with pytest.raises(S3AccessFailed) as exc:
            self._paginate(stubbed_s3)
        assert exc.value.code == "s3_no_such_bucket"
        assert "'lab'" in exc.value.detail

    def test_access_denied_is_an_error(self, stubbed_s3):
        stubbed_s3.stubber.add_client_error(
            "list_objects_v2", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(S3AccessFailed) as exc:
            self._paginate(stubbed_s3)
        assert exc.value.code == "s3_access_denied"
        assert "s3://lab/run1/" in exc.value.detail


# ── Compatibility helpers ───────────────────────────────────────────────────


class TestPublicHelpers:
    def test_storage_options_only_for_a_listed_location(self, stubbed_s3):
        stubbed_s3.head("eu-west-1")
        policy = _Policy(public_s3_buckets="open-data")

        assert s3_access.public_s3_storage_options("s3://open-data/x.parquet", policy) == {
            "aws_skip_signature": "true",
            "aws_region": "eu-west-1",
        }
        assert s3_access.public_s3_storage_options("s3://closed/x.parquet", policy) is None

    def test_an_https_url_is_never_a_public_s3_location(self):
        assert not s3_access.is_public_s3_location(
            "https://example.com/a.csv", _Policy(public_s3_buckets="example.com")
        )

    def test_public_region_falls_back_to_the_default(self, monkeypatch):
        def _boom(target):
            raise OSError("no network")

        monkeypatch.setattr(S3Target, "client", _boom)
        assert s3_access.public_s3_region("offline") == AWS_DEFAULT_REGION
