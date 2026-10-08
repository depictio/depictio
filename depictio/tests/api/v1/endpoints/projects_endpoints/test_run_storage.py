"""Tests for storage settings typed in with a run folder in a private bucket.

The POST twins of ``/projects/s3_dirs``, ``/folder_inspect`` and ``/find_runs``,
``POST /projects/storage_test`` and ``POST /projects/from_run`` take a
``storage`` body (``RunStorageIn``): the location is then read with those
settings alone (a ``project`` target, whatever the bucket lists say), they are
validated exactly as a saved config is, the instance's own bucket stays
refused, and only the creation stores them, on the project it creates, before
its ingestion is dispatched. The secret is never logged and never answered
back: every test here fails if a log record of any level carries it.

No network: S3 is the shared stub (``depictio/tests/cli/s3_stubs.py``) or a
botocore ``Stubber``; Mongo is mongomock.
"""

import json
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import boto3
import mongomock
import pytest
from botocore.stub import Stubber
from bson import ObjectId
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.requests import Request

from depictio.api.v1 import remote_fetch
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import (
    from_run,
    manifest_ingest,
    routes,
    run_folders,
    storage_config,
)
from depictio.api.v1.endpoints.projects_endpoints.run_folders import (
    FindRunsRequest,
    FolderInspectRequest,
    S3DirListing,
    S3DirsRequest,
)
from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
    RunStorageIn,
    RunStorageTestRequest,
)
from depictio.cli.cli.utils import data_root as data_root_module
from depictio.cli.cli.utils import multiqc_processor
from depictio.models.models.users import UserBase
from depictio.models.s3_access import S3AccessFailed, S3AccessRefused, S3Target
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_KEY_PREFIX,
    S3_ROOT,
    FailingS3Client,
    StubS3Client,
    s3_client_error,
)

SECRET = "pR1vate-S3cret-Value-9f8e7d6c"
KEY_ID = "AKIAPRIVATEKEY0001"
ENDPOINT = "https://s3.example.org"
PRIVATE = "lab-private"
INSTANCE = "instance-data"
TEMPLATE_ID = "nf-core/ampliseq/2.16.0"


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _request(host: str = "localhost:8058") -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [(b"host", host.encode())]}
    )


def _storage(**overrides) -> RunStorageIn:
    fields = {"endpoint_url": ENDPOINT, "access_key_id": KEY_ID, "secret_access_key": SECRET}
    return RunStorageIn(**{**fields, **overrides})


@pytest.fixture(autouse=True)
def server_context(monkeypatch, tmp_path):
    """Server context, no bucket listed, the test endpoint allowlisted, local folders
    off, a keys directory of the test's own."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    for name in (
        "DEPICTIO_LOCAL_DATA_ROOTS",
        "DEPICTIO_AUTH_SINGLE_USER_MODE",
        "DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS",
        "DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "s3.example.org")
    monkeypatch.setattr(settings.s3, "bucket", INSTANCE)
    monkeypatch.setattr(settings.auth, "keys_dir", tmp_path / "keys")


@pytest.fixture(autouse=True)
def secret_never_logged(caplog):
    """Every record of every level, from every Depictio logger, is free of the secret."""
    for name in (None, "depictio-models", "depictio-cli", "depictio.api.v1.configs.logging_init"):
        caplog.set_level(logging.DEBUG, logger=name)
    yield caplog
    formatter = logging.Formatter("%(name)s %(message)s")
    for when in ("setup", "call"):
        for record in caplog.get_records(when):
            assert SECRET not in formatter.format(record), record.getMessage()


@pytest.fixture()
def no_client(monkeypatch):
    """Fail the test if any S3 client is built: a refusal needs none."""
    monkeypatch.setattr(S3Target, "client", lambda _target: pytest.fail("an S3 client was built"))


def _serve(monkeypatch, client):
    """Make ``client`` the client of every S3 target, recording each target, with no
    region lookup. Returns the list of targets."""
    seen: list[S3Target] = []

    def _client(target):
        seen.append(target)
        return client

    monkeypatch.setattr(S3Target, "client", _client)
    for module in (run_folders, data_root_module, multiqc_processor):
        monkeypatch.setattr(module, "ensure_region", lambda target: target)
    return seen


def _assert_read_with_the_storage(seen: list[S3Target]):
    assert seen, "nothing was read"
    for target in seen:
        assert target.kind == "project"
        assert (target.endpoint_url, target.access_key_id, target.secret_access_key) == (
            ENDPOINT,
            KEY_ID,
            SECRET,
        )


def _echoed(*answers) -> bool:
    """Whether any answer (a model, an exception, a response) carries the secret or key."""
    for answer in answers:
        if hasattr(answer, "model_dump_json"):
            text = answer.model_dump_json()
        elif hasattr(answer, "body"):
            text = bytes(answer.body).decode()
        else:
            text = str(getattr(answer, "detail", answer))
        if SECRET in text:
            return True
    return False


RUN_KEYS = {
    "runs/r1/pipeline_info/params.json": b"{}",
    "runs/r1/multiqc/multiqc_data/multiqc.parquet": b"PAR1",
    "runs/r1/notes.txt": b"x",
    "runs/r2/pipeline_info/p.json": b"{}",
}


# ── RunStorageIn: validated as a saved config is ─────────────────────────────


def test_the_bucket_comes_from_the_location():
    settings_in = _storage().settings_for(f"s3://{PRIVATE}/runs/r1/")
    assert settings_in.bucket == PRIVATE
    assert settings_in.secret_access_key == SECRET
    # Kept out of the model's repr, the typed-in one's and the validated one's.
    assert SECRET not in repr(settings_in) and SECRET not in repr(_storage())


def test_an_empty_endpoint_is_aws_and_needs_no_gating(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "nothing.example")
    settings_in = _storage(endpoint_url="", region=None).settings_for(f"s3://{PRIVATE}/")
    assert (settings_in.endpoint_url, settings_in.region) == ("", "us-east-1")
    target = remote_fetch.s3_read_target(
        f"s3://{PRIVATE}/runs/",
        from_run._run_folder_read_config(storage_config.read_settings(settings_in)),
    )
    assert (target.kind, target.endpoint_url) == ("project", None)


@pytest.mark.parametrize(
    "endpoint", ["https://192.168.1.10:9000", "http://10.0.0.5", "ftp://s3.example.org"]
)
def test_an_endpoint_the_gating_refuses_is_a_400(monkeypatch, no_client, endpoint):
    monkeypatch.delenv("DEPICTIO_REMOTE_URL_ALLOWLIST")
    with pytest.raises(HTTPException) as exc:
        _storage(endpoint_url=endpoint).settings_for(f"s3://{PRIVATE}/runs/")
    assert exc.value.status_code == 400


def test_the_instance_endpoint_is_exempt_but_not_its_bucket(monkeypatch):
    monkeypatch.setattr(settings.s3, "service_name", "s3-under-test")
    monkeypatch.setattr(settings.s3, "service_port", 9000)
    storage = _storage(endpoint_url="http://s3-under-test:9000")
    assert storage.settings_for(f"s3://{PRIVATE}/").endpoint_url == "http://s3-under-test:9000"
    with pytest.raises(S3AccessRefused, match="instance's own data"):
        storage.settings_for(f"s3://{INSTANCE}/projects/")


@pytest.mark.parametrize(
    ("overrides", "says"),
    [
        ({"secret_access_key": None}, "Enter the secret for this access key."),
        ({"access_key_id": None}, "A secret access key needs its access key ID."),
        ({"access_key_id": "  "}, "A secret access key needs its access key ID."),
        ({"region": "x@evil.example/"}, "The region must be a plain name"),
    ],
)
def test_settings_no_read_could_use_are_a_422_without_the_secret(overrides, says):
    with pytest.raises(HTTPException) as exc:
        _storage(**overrides).settings_for(f"s3://{PRIVATE}/runs/")
    assert exc.value.status_code == 422
    assert says in exc.value.detail
    assert not _echoed(exc.value)
    # Nothing chained either, so no traceback shows the validation input.
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None or exc.value.__suppress_context__


def test_no_keys_at_all_reads_unsigned_at_the_endpoint():
    settings_in = _storage(access_key_id=None, secret_access_key=None).settings_for(
        f"s3://{PRIVATE}/"
    )
    target = remote_fetch.s3_read_target(
        f"s3://{PRIVATE}/",
        from_run._run_folder_read_config(storage_config.read_settings(settings_in)),
    )
    assert (target.kind, target.unsigned, target.endpoint_url) == ("project", True, ENDPOINT)


@pytest.mark.asyncio
async def test_a_body_missing_a_field_is_not_echoed_back():
    """A missing field's error carries the whole body as its input: the handler drops it."""
    from depictio.api.main import validation_exception_handler

    body = {"storage": {"access_key_id": KEY_ID, "secret_access_key": SECRET}}
    with pytest.raises(ValidationError) as exc:
        from_run.FromRunRequest.model_validate(body)
    assert SECRET in str(exc.value.errors())  # what the handler used to answer

    response = await validation_exception_handler(None, RequestValidationError(exc.value.errors()))
    assert response.status_code == 422
    assert "data_root" in bytes(response.body).decode()
    assert not _echoed(response)


# ── the POST twins: read with the storage alone ──────────────────────────────


def test_s3_dirs_with_storage_reads_an_unlisted_bucket_with_it(monkeypatch):
    seen = _serve(monkeypatch, StubS3Client(RUN_KEYS))
    listing = run_folders.list_s3_dirs(f"s3://{PRIVATE}/runs", _storage())

    assert [e.name for e in listing.entries] == ["r1", "r2"]
    # The keys say what is readable: the bucket itself is the root.
    assert (listing.path, listing.root, listing.parent) == (
        f"s3://{PRIVATE}/runs/",
        f"s3://{PRIVATE}/",
        f"s3://{PRIVATE}/",
    )
    top = run_folders.list_s3_dirs(f"s3://{PRIVATE}/", _storage())
    assert top.parent is None and [e.name for e in top.entries] == ["runs"]
    _assert_read_with_the_storage(seen)
    assert not _echoed(listing, top)


@pytest.mark.parametrize("bucket_list", ["PUBLIC", "CREDENTIALED"])
def test_with_storage_the_bucket_lists_do_not_apply(monkeypatch, bucket_list):
    """No public, ambient or instance fallback: the settings typed in decide alone."""
    monkeypatch.setenv(f"DEPICTIO_REMOTE_{bucket_list}_S3_BUCKETS", PRIVATE)
    seen = _serve(monkeypatch, StubS3Client(RUN_KEYS))
    run_folders.list_s3_dirs(f"s3://{PRIVATE}/runs/", _storage())
    run_folders.find_runs(
        f"s3://{PRIVATE}/runs/", storage=_storage(), request=_request(), current_user=_user()
    )
    _assert_read_with_the_storage(seen)


def test_without_storage_an_unlisted_bucket_is_still_refused(no_client):
    with pytest.raises(S3AccessRefused):
        run_folders.list_s3_dirs(f"s3://{PRIVATE}/runs/")


def test_without_a_url_the_storage_is_not_used(monkeypatch, no_client):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")
    listing = run_folders.list_s3_dirs(None, _storage())
    assert [e.name for e in listing.entries] == ["open-data"]


def _run_tree(prefix: str) -> dict[str, bytes]:
    versions = "Workflow:\n    nf-core/ampliseq: v2.16.0\n    Nextflow: 25.10.0\n"
    tree = {
        "pipeline_info/software_versions.yml": versions.encode(),
        "pipeline_info/params_2026-01-01_10-00-00.json": b'{"run_name": "r"}',
        "multiqc/multiqc_data/multiqc.parquet": b"PAR1",
        "input/samplesheet.csv": b"sampleID\nS1\n",
    }
    return {f"{prefix}{rel}": body for rel, body in tree.items()}


def test_folder_inspect_with_storage_reads_and_detects_with_it(monkeypatch):
    seen = _serve(monkeypatch, StubS3Client(_run_tree("runs/r1/")))
    inspection = run_folders.inspect_folder(
        f"s3://{PRIVATE}/runs/r1", storage=_storage(), request=_request(), current_user=_user()
    )
    assert inspection.markers == ["multiqc", "pipeline_info"]
    assert inspection.detected is not None
    assert (inspection.detected.template_id, inspection.detected.match) == (TEMPLATE_ID, "exact")
    # The page, then the detection's own listing: both with the storage.
    assert len(seen) >= 2
    _assert_read_with_the_storage(seen)


def test_find_runs_with_storage(monkeypatch):
    seen = _serve(monkeypatch, StubS3Client(RUN_KEYS))
    found = run_folders.find_runs(
        f"s3://{PRIVATE}/runs/", storage=_storage(), request=_request(), current_user=_user()
    )
    assert [run.relative for run in found.runs] == ["r1", "r2"]
    _assert_read_with_the_storage(seen)


@pytest.mark.parametrize("context", ["server", "CLI"])
def test_the_instance_bucket_is_refused_even_with_storage(monkeypatch, no_client, context):
    monkeypatch.setenv("DEPICTIO_CONTEXT", context)
    for read in (
        lambda: run_folders.list_s3_dirs(f"s3://{INSTANCE}/projects/", _storage()),
        lambda: run_folders.inspect_folder(
            f"s3://{INSTANCE}/x/", storage=_storage(), request=_request(), current_user=_user()
        ),
        lambda: run_folders.find_runs(
            f"s3://{INSTANCE}/", storage=_storage(), request=_request(), current_user=_user()
        ),
    ):
        with pytest.raises(S3AccessRefused, match="instance's own data") as exc:
            read()
        assert exc.value.code == "s3_refused"


def test_a_denied_read_with_storage_keeps_its_code_and_says_nothing_of_the_keys(monkeypatch):
    _serve(monkeypatch, FailingS3Client("AccessDenied", 403))
    with pytest.raises(S3AccessFailed) as exc:
        run_folders.inspect_folder(
            f"s3://{PRIVATE}/runs/", storage=_storage(), request=_request(), current_user=_user()
        )
    assert (exc.value.status_code, exc.value.code) == (422, "s3_access_denied")
    assert "storage" in exc.value.detail
    assert KEY_ID not in exc.value.detail and not _echoed(exc.value)


# ── the routes ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_post_routes_answer_with_the_storage(monkeypatch):
    seen = _serve(monkeypatch, StubS3Client(_run_tree("runs/r1/")))
    user = _user()
    listing = await routes.post_s3_dirs(
        S3DirsRequest(url=f"s3://{PRIVATE}/runs/", storage=_storage()), current_user=user
    )
    inspection = await routes.post_folder_inspect(
        FolderInspectRequest(location=f"s3://{PRIVATE}/runs/r1/", detect=False, storage=_storage()),
        _request(),
        current_user=user,
    )
    found = await routes.post_find_runs(
        FindRunsRequest(location=f"s3://{PRIVATE}/runs/", storage=_storage()),
        _request(),
        current_user=user,
    )
    assert [e.name for e in listing.entries] == ["r1"]
    assert inspection.looks_like_run is True
    assert [run.relative for run in found.runs] == ["r1"]
    _assert_read_with_the_storage(seen)
    assert not _echoed(listing, inspection, found)


@pytest.mark.asyncio
async def test_the_post_routes_without_storage_answer_as_the_get_routes(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")
    listing = await routes.post_s3_dirs(S3DirsRequest(), current_user=_user())
    assert [e.name for e in listing.entries] == ["open-data"]
    # A local location ignores the storage and keeps the local guards.
    response = await routes.post_folder_inspect(
        FolderInspectRequest(location="/tmp/run", storage=_storage()),
        _request("evil.example"),
        current_user=_user(),
    )
    assert json.loads(response.body)["code"] == "local_folders_off"


@pytest.mark.asyncio
async def test_the_new_routes_need_a_user():
    test_body = RunStorageTestRequest(location=f"s3://{PRIVATE}/", storage=_storage())
    for call in (
        routes.post_s3_dirs(S3DirsRequest(), current_user=None),
        routes.post_folder_inspect(
            FolderInspectRequest(location="/x"), _request(), current_user=None
        ),
        routes.post_find_runs(FindRunsRequest(location="/x"), _request(), current_user=None),
        routes.test_run_storage(test_body, current_user=None),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_public_mode_keeps_storage_to_administrators(no_client):
    """The callers of POST /projects/from_run: a demo visitor is not one of them."""
    public = MagicMock()
    public.auth.is_public_mode = True
    visitor = _user(is_admin=False)
    with patch.object(routes, "settings", public):
        for call in (
            routes.post_s3_dirs(
                S3DirsRequest(url=f"s3://{PRIVATE}/", storage=_storage()), current_user=visitor
            ),
            routes.post_find_runs(
                FindRunsRequest(location=f"s3://{PRIVATE}/", storage=_storage()),
                _request(),
                current_user=visitor,
            ),
            routes.test_run_storage(
                RunStorageTestRequest(location=f"s3://{PRIVATE}/", storage=_storage()),
                current_user=visitor,
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.status_code == 403
        # Without storage the browse stays open to every signed-in user.
        listing = await routes.post_s3_dirs(S3DirsRequest(), current_user=visitor)
        assert isinstance(listing, S3DirListing)


# ── POST /projects/storage_test ──────────────────────────────────────────────


class _StubbedS3:
    """One stubbed boto3 client for every target, recording them; ``Stubber`` fails any
    unexpected call and checks the parameters of the expected ones."""

    def __init__(self, monkeypatch):
        self.client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
        )
        self.stubber = Stubber(self.client)
        self.stubber.activate()
        self.targets = _serve(monkeypatch, self.client)

    def head(self, region: str | None = None):
        headers = {"x-amz-bucket-region": region} if region else {}
        self.stubber.add_response(
            "head_bucket",
            {"ResponseMetadata": {"HTTPStatusCode": 200, "HTTPHeaders": headers}},
            {"Bucket": PRIVATE},
        )

    def list_one(self, prefix: str, key_count: int = 1):
        self.stubber.add_response(
            "list_objects_v2",
            {"KeyCount": key_count, "IsTruncated": False},
            {"Bucket": PRIVATE, "Prefix": prefix, "MaxKeys": 1},
        )


@pytest.fixture()
def stubbed_s3(monkeypatch):
    stub = _StubbedS3(monkeypatch)
    yield stub
    stub.stubber.assert_no_pending_responses()


@pytest.fixture()
def storage_db():
    database = mongomock.MongoClient()["depictio_test"]
    with patch.object(storage_config, "project_storage_collection", database["storage"]):
        yield database


def test_storage_test_heads_then_lists_one_key_under_the_prefix(stubbed_s3, storage_db):
    stubbed_s3.head("eu-west-1")
    stubbed_s3.list_one("runs/r1/")

    result = storage_config._test_run_storage(f"s3://{PRIVATE}/runs/r1", _storage())

    assert result.success is True
    assert (result.detected_region, result.message) == (
        "eu-west-1",
        f"Bucket '{PRIVATE}' is reachable. Its region is eu-west-1.",
    )
    # The listing went to the detected region; the region is answered, not saved.
    assert [t.region for t in stubbed_s3.targets] == ["us-east-1", "eu-west-1"]
    _assert_read_with_the_storage(stubbed_s3.targets)
    assert storage_db["storage"].count_documents({}) == 0
    assert not _echoed(result)


def test_storage_test_says_when_the_prefix_holds_nothing(stubbed_s3):
    stubbed_s3.head(None)
    stubbed_s3.list_one("runs/gone/", key_count=0)
    result = storage_config._test_run_storage(f"s3://{PRIVATE}/runs/gone/", _storage())
    assert result.success is True
    assert result.detected_region is None
    assert f"Nothing is stored under s3://{PRIVATE}/runs/gone/." in result.message


def test_storage_test_a_404_prefix_is_an_empty_one(stubbed_s3):
    stubbed_s3.head(None)
    stubbed_s3.stubber.add_client_error(
        "list_objects_v2", service_error_code="NoSuchKey", http_status_code=404
    )
    assert storage_config._test_run_storage(f"s3://{PRIVATE}/runs/x/", _storage()).success is True


def test_storage_test_failures_use_the_sanitized_mapping(stubbed_s3, secret_never_logged):
    stubbed_s3.stubber.add_client_error(
        "head_bucket",
        service_error_code="403",
        http_status_code=403,
        response_meta={"RequestId": "REQ-0123456789"},
    )
    result = storage_config._test_run_storage(f"s3://{PRIVATE}/runs/", _storage())

    assert result.success is False
    assert "denied" in result.message and PRIVATE in result.message
    for leaked in ("REQ-0123456789", KEY_ID, SECRET):
        assert leaked not in result.message
    # The failure was logged (so the log check of this suite looks at something).
    assert any("Storage test failed" in r.getMessage() for r in secret_never_logged.records)


@pytest.mark.parametrize(
    ("location", "overrides", "says"),
    [
        (f"s3://{INSTANCE}/projects/", {}, "instance's own data"),
        (f"s3://{PRIVATE}/", {"endpoint_url": "https://other.example.org"}, "allowlist"),
        (f"s3://{PRIVATE}/", {"secret_access_key": None}, "Enter the secret"),
    ],
)
def test_storage_test_answers_unusable_settings_without_a_request(
    no_client, location, overrides, says
):
    result = storage_config._test_run_storage(location, _storage(**overrides))
    assert result.success is False
    assert says in result.message
    assert not _echoed(result)


def test_storage_test_refuses_a_location_that_is_not_s3(no_client):
    with pytest.raises(S3AccessRefused):
        storage_config._test_run_storage("https://example.org/runs/", _storage())


@pytest.mark.asyncio
async def test_storage_test_route(stubbed_s3):
    stubbed_s3.head(None)
    stubbed_s3.list_one("runs/")
    result = await routes.test_run_storage(
        RunStorageTestRequest(location=f"s3://{PRIVATE}/runs/", storage=_storage()),
        current_user=_user(),
    )
    assert result.success is True


# ── POST /projects/from_run ──────────────────────────────────────────────────


@pytest.fixture()
def mock_db():
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(from_run, "projects_collection", database["projects"]),
        patch.object(routes, "projects_collection", database["projects"]),
        patch.object(manifest_ingest, "projects_collection", database["projects"]),
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
        patch.object(storage_config, "project_storage_collection", database["project_storage"]),
    ):
        yield database


@pytest.fixture()
def megatest(monkeypatch):
    """The megatest tree, with the versions file detection reads, in a bucket no list
    names; returns the targets the reads were made with."""
    versions = b"Workflow:\n    nf-core/ampliseq: v2.16.0\n    Nextflow: 25.10.0\n"
    tree = {**MEGATEST_TREE, "pipeline_info/software_versions.yml": versions}
    return _serve(
        monkeypatch, StubS3Client({f"{S3_KEY_PREFIX}{rel}": body for rel, body in tree.items()})
    )


def _from_run(**kwargs):
    kwargs.setdefault("data_root", S3_ROOT)
    kwargs.setdefault("template_id", TEMPLATE_ID)
    kwargs.setdefault("current_user", _user())
    return from_run._create_project_from_run(**kwargs)


def test_without_storage_a_private_run_folder_is_refused(no_client):
    with pytest.raises(S3AccessRefused, match="cannot be read by the server"):
        _from_run(dry_run=True)


def test_a_dry_run_reads_and_detects_with_the_storage_and_stores_nothing(mock_db, megatest):
    report = _from_run(template_id=None, dry_run=True, storage=_storage())

    assert report.success is True
    assert report.detected_template is not None
    assert report.detected_template.template_id == TEMPLATE_ID
    assert report.storage_saved is False
    assert report.project_id is None
    _assert_read_with_the_storage(megatest)
    assert mock_db["projects"].count_documents({}) == 0
    assert mock_db["project_storage"].count_documents({}) == 0
    # Not even the secrets key was made: nothing was encrypted.
    assert not settings.auth.keys_dir.exists()
    assert not _echoed(report)


def test_the_instance_bucket_is_refused_as_a_run_folder_even_with_storage(mock_db, no_client):
    with pytest.raises(S3AccessRefused, match="instance's own data"):
        _from_run(data_root=f"s3://{INSTANCE}/runs/r1", storage=_storage())
    assert mock_db["projects"].count_documents({}) == 0


def test_invalid_storage_is_refused_before_anything_is_read_or_created(
    monkeypatch, mock_db, no_client
):
    with pytest.raises(HTTPException) as exc:
        _from_run(storage=_storage(secret_access_key=None))
    assert exc.value.status_code == 422
    monkeypatch.delenv("DEPICTIO_REMOTE_URL_ALLOWLIST")
    with pytest.raises(HTTPException) as exc:
        _from_run(storage=_storage(endpoint_url="https://192.168.1.10:9000"))
    assert exc.value.status_code == 400
    assert mock_db["projects"].count_documents({}) == 0


def test_storage_with_a_local_folder_is_ignored(mock_db, tmp_path):
    from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException

    with pytest.raises(CodedHTTPException) as exc:
        _from_run(data_root=str(tmp_path), dry_run=True, storage=_storage(secret_access_key=None))
    assert exc.value.code == "local_folders_off"


def _token_doc(user: UserBase) -> dict:
    later = datetime.now() + timedelta(days=1)
    return {
        "user_id": user.id,
        "access_token": "a.b.c",
        "refresh_token": "d.e.f",
        "expire_datetime": later,
        "refresh_expire_datetime": later,
    }


def _create(mock_db, user, **kwargs):
    """Create for real, the dashboard import and the broker stubbed. Returns the report,
    the stored settings each dispatched task would have read, and the task and importer."""
    from depictio.api.v1.monitoring import store as monitoring_store

    at_dispatch: list = []

    def _dispatch(*args, **call_kwargs):
        payload = (call_kwargs.get("args") or args[0])[0]
        at_dispatch.append(storage_config.project_storage_for(payload["project_id"]))

    with (
        patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.import_dashboard_yaml_content",
            return_value={"success": True, "dashboard_id": str(ObjectId()), "title": "Overview"},
        ) as importer,
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task,
    ):
        task.apply_async.side_effect = _dispatch
        report = _from_run(current_user=user, project_name="private42", **kwargs)
    return report, at_dispatch, task, importer


def test_a_creation_stores_the_storage_before_dispatching_and_the_workers_read_with_it(
    mock_db, megatest, tmp_path
):
    user = _user()
    report, at_dispatch, task, _importer = _create(mock_db, user, storage=_storage())

    assert report.success is True
    assert report.storage_saved is True
    assert not _echoed(report)
    preview_target = megatest[0]
    _assert_read_with_the_storage(megatest)

    # Stored on the new project, the secret encrypted, before any task went out.
    stored = mock_db["project_storage"].find_one({"project_id": ObjectId(report.project_id)})
    assert stored["bucket"] == S3_BUCKET
    assert (stored["endpoint_url"], stored["access_key_id"]) == (ENDPOINT, KEY_ID)
    assert SECRET not in str(stored)
    assert task.apply_async.call_count == len(at_dispatch) > 0
    assert all(
        config is not None
        and (config.bucket, config.access_key_id, config.secret_access_key)
        == (S3_BUCKET, KEY_ID, SECRET)
        for config in at_dispatch
    )

    # A worker builds its configuration from the stored settings, as for any refresh:
    # the same target as the preview's, for the listing, the scans and the MultiQC fetch.
    mock_db["tokens"].insert_one(_token_doc(user))
    worker_config = dc_utils._build_cli_config_for_user(
        user, remote_storage_options=storage_config.project_storage_for(report.project_id)
    )
    assert remote_fetch.s3_read_target(preview_target.location, worker_config) == preview_target

    reads_before = len(megatest)
    objects, _truncated = data_root_module.list_s3_objects(f"{S3_ROOT}/multiqc/", worker_config)
    assert [obj.relative for obj in objects] == ["multiqc_data/multiqc.parquet"]
    size = multiqc_processor._download_s3_report(
        f"{S3_ROOT}/multiqc/multiqc_data/multiqc.parquet",
        str(tmp_path / "multiqc.parquet"),
        worker_config,
        1_000_000,
    )
    assert size == len(b"PAR1")
    _assert_read_with_the_storage(megatest[reads_before:])


def test_a_creation_without_storage_stores_none(mock_db, monkeypatch, megatest):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)
    report, _at_dispatch, _task, _importer = _create(mock_db, _user())
    assert report.storage_saved is False
    assert mock_db["project_storage"].count_documents({}) == 0


def test_a_failed_save_removes_the_project_and_starts_nothing(mock_db, megatest):
    def _broken(_secret):
        raise OSError(f"keys directory is read-only, cannot encrypt {SECRET}")

    with (
        patch("depictio.api.v1.crypto.encrypt_secret", side_effect=_broken),
        pytest.raises(HTTPException) as exc,
    ):
        _create(mock_db, _user(), storage=_storage())

    assert exc.value.status_code == 500
    assert "not created" in exc.value.detail
    assert not _echoed(exc.value)
    assert exc.value.__suppress_context__
    assert mock_db["projects"].count_documents({}) == 0
    assert mock_db["project_storage"].count_documents({}) == 0
    assert mock_db["ingestion_runs"].count_documents({}) == 0


def test_a_failed_store_write_removes_the_project_too(mock_db, megatest):
    with (
        patch.object(
            storage_config.project_storage_collection,
            "update_one",
            side_effect=RuntimeError("write refused"),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        _create(mock_db, _user(), storage=_storage())
    assert exc.value.status_code == 500
    assert mock_db["projects"].count_documents({}) == 0


def test_a_refusal_at_save_time_is_answered_as_it_is(mock_db, megatest, monkeypatch):
    """The endpoint is gated again when stored, as on PUT: refused then, it is a 400."""
    real = storage_config._check_storage_settings
    calls = []

    def _gate_tightened_after_preview(payload, *, has_secret):
        calls.append(payload)
        if len(calls) > 1:
            raise HTTPException(status_code=400, detail="Host 's3.example.org' is denied.")
        return real(payload, has_secret=has_secret)

    monkeypatch.setattr(storage_config, "_check_storage_settings", _gate_tightened_after_preview)
    with pytest.raises(HTTPException) as exc:
        _create(mock_db, _user(), storage=_storage())
    assert exc.value.status_code == 400
    assert mock_db["projects"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_the_from_run_route_passes_the_storage_on(mock_db, megatest):
    payload = from_run.FromRunRequest(data_root=S3_ROOT, dry_run=True, storage=_storage())
    report = await routes.create_project_from_run(payload, _request(), current_user=_user())
    assert report.storage_saved is False
    _assert_read_with_the_storage(megatest)


def test_a_denied_preview_with_storage_says_nothing_of_the_keys(mock_db, monkeypatch):
    _serve(monkeypatch, FailingS3Client("SignatureDoesNotMatch", 403))
    with pytest.raises(S3AccessFailed) as exc:
        _from_run(dry_run=True, storage=_storage())
    assert exc.value.code == "s3_access_denied"
    assert KEY_ID not in exc.value.detail and not _echoed(exc.value)
    assert mock_db["projects"].count_documents({}) == 0


def test_a_get_object_denied_is_mapped(monkeypatch):
    """The worker's MultiQC fetch with the stored settings, denied: coded, keys unsaid."""

    class _Denied(StubS3Client):
        def get_object(self, Bucket, Key):  # noqa: N803
            raise s3_client_error("AccessDenied", 403, "GetObject")

    _serve(monkeypatch, _Denied({}))
    config = from_run._run_folder_read_config(
        storage_config.read_settings(_storage().settings_for(f"{S3_ROOT}/"))
    )
    with pytest.raises(S3AccessFailed) as exc:
        multiqc_processor._download_s3_report(f"{S3_ROOT}/m.parquet", "/dev/null", config, 10)
    assert exc.value.code == "s3_access_denied" and not _echoed(exc.value)
