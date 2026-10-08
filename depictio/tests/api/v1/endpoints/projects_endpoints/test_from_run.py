"""Tests for POST /projects/from_run (`_create_project_from_run`).

Orchestration-contract tests: the data root has to be an ``s3://`` prefix this
server is allowed to read (decided from configuration, before any request goes
out, and from the inputs the workers decide from), a resolved template may not
point outside that prefix, a dry run creates nothing, and a real run creates
the project under a free name, imports its dashboards keyed as the CLI keys
them and hands one Celery task per ingestable data collection to the refresh
machinery.

No network. The S3 listing is the shared CLI stub (``depictio/tests/cli/
s3_stubs.py``): the key list handed to it *is* the bucket, so the real
``nf-core/ampliseq/2.16.0`` template resolves against a fixture shaped like the
AWS megatest prefix. The heavy legs (scan → Delta, dashboard tag binding) are
covered by their own suites and patched at their seams here.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from starlette.requests import Request

from depictio.api.v1 import remote_fetch
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import (
    from_run,
    manifest_ingest,
    routes,
    storage_config,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.models.models.users import UserBase
from depictio.models.s3_access import S3AccessFailed, S3AccessRefused, S3Target
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_KEY_PREFIX,
    S3_ROOT,
    FailingS3Client,
    install_s3_client,
    install_s3_listing,
    write_tree,
)

TEMPLATE_ID = "nf-core/ampliseq/2.16.0"

# Where a template that escaped its run folder could reach: the container path
# the JWT signing key is mounted under.
ESCAPING_LOCATION = "/app/depictio/keys/private_key.pem"


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _call(
    data_root: str = S3_ROOT,
    template_id: str | None = TEMPLATE_ID,
    user=None,
    project_name: str | None = None,
    variables: dict[str, str] | None = None,
    dry_run: bool = False,
    request=None,
):
    return from_run._create_project_from_run(
        data_root=data_root,
        template_id=template_id,
        current_user=user or _user(),
        project_name=project_name,
        variables=variables,
        dry_run=dry_run,
        request=request,
    )


def _request(host: str | None = "localhost:8058") -> Request:
    """The incoming request, as far as the Host guard reads it."""
    headers = [(b"host", host.encode())] if host is not None else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context, the suite's default. Importing the CLI app sets
    ``DEPICTIO_CONTEXT=CLI`` for the whole process, and how a location is read
    depends on it. Local folders off unless a test turns them on."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)


@pytest.fixture()
def no_bucket_lists(monkeypatch):
    """No bucket an administrator listed, public or credentialed."""
    monkeypatch.delenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", raising=False)


@pytest.fixture()
def allowlisted_bucket(monkeypatch, no_bucket_lists):
    """The megatest bucket marked public, the way an administrator would."""
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)


@pytest.fixture()
def no_client(monkeypatch):
    """Fail the test if any S3 client is built: a refusal needs none."""
    monkeypatch.setattr(S3Target, "client", lambda _target: pytest.fail("an S3 client was built"))


@pytest.fixture()
def mock_db(monkeypatch):
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(from_run, "projects_collection", database["projects"]),
        # The duplicate-name check is POST /projects/create's, which reads here.
        patch.object(routes, "projects_collection", database["projects"]),
        patch.object(manifest_ingest, "projects_collection", database["projects"]),
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
        patch.object(storage_config, "project_storage_collection", database["project_storage"]),
    ):
        yield database


@pytest.fixture()
def megatest_s3(monkeypatch, allowlisted_bucket):
    """Serve the megatest fixture tree; returns an installer for a variant tree."""

    def _install(tree: dict[str, bytes] | None = None):
        return install_s3_listing(
            monkeypatch, MEGATEST_TREE if tree is None else tree, key_prefix=S3_KEY_PREFIX
        )

    return _install


def _rows(report) -> dict[str, object]:
    return {row.data_collection_tag: row for row in report.data_collections}


def _dispatched_payloads(task) -> list[dict]:
    """The task payload of every ``apply_async(args=[payload])`` call."""
    return [
        (call.kwargs.get("args") or call.args[0])[0] for call in task.apply_async.call_args_list
    ]


# ── the data root ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "data_root",
    ["/mnt/runs/run1", "https://example.org/run1", "file:///runs/run1", "gs://bucket/run1"],
)
def test_non_s3_data_root_422(data_root, no_bucket_lists):
    with pytest.raises(HTTPException) as exc:
        _call(data_root=data_root, dry_run=True)
    assert exc.value.status_code == 422
    assert "s3://" in exc.value.detail


def test_an_unlisted_bucket_is_refused_without_ever_building_a_client(monkeypatch, no_client):
    """Neither public nor credentialed: refused from configuration alone.

    Nothing may go out over the wire: the error S3 returns for a bucket that
    exists but is not ours would otherwise turn any bucket name into an
    existence-and-region oracle. The refusal is coded, so the API answers
    ``{detail, code}``.
    """
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "some-other-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")  # the server's own keys do not count

    with pytest.raises(S3AccessRefused) as exc:
        _call(data_root="s3://private-bucket/run1", dry_run=True)
    assert (exc.value.status_code, exc.value.code) == (422, "s3_refused")
    assert "s3://private-bucket/run1" in exc.value.detail


def test_the_instance_bucket_is_refused_as_a_run_folder(monkeypatch, no_client):
    """It holds every project's data: refused in server context, public or not.

    The instance bucket is the one the server is configured with, which is
    what the workers refuse too, not a default read from the environment.
    """
    monkeypatch.setattr(settings.s3, "bucket", "instance-data")
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "instance-data")

    with pytest.raises(S3AccessRefused, match="instance's own data") as exc:
        _call(data_root="s3://instance-data/projects/run42", dry_run=True)
    assert exc.value.code == "s3_refused"


def test_a_failed_listing_answers_with_its_code(monkeypatch, allowlisted_bucket):
    """A store's refusal is coded and sanitized, never a raw botocore text or a 500."""
    install_s3_client(monkeypatch, FailingS3Client("AccessDenied", 403))

    with pytest.raises(S3AccessFailed) as exc:
        _call(dry_run=True)
    assert (exc.value.status_code, exc.value.code) == (422, "s3_access_denied")
    assert S3_ROOT in exc.value.detail
    assert "RequestId" not in exc.value.detail


def test_malformed_s3_prefix_422(no_bucket_lists):
    with pytest.raises(HTTPException) as exc:
        _call(data_root="s3://", dry_run=True)
    assert exc.value.status_code == 422


# ── template resolution ──────────────────────────────────────────────────────


def test_unknown_template_404(megatest_s3):
    megatest_s3()
    with pytest.raises(HTTPException) as exc:
        _call(template_id="nf-core/does-not-exist/1", dry_run=True)
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail


def test_path_like_template_id_422_before_any_lookup(mock_db, no_bucket_lists):
    with pytest.raises(HTTPException) as exc:
        _call(template_id="../../etc/passwd", dry_run=True)
    assert exc.value.status_code == 422
    assert "slash-separated" in exc.value.detail
    assert mock_db["projects"].count_documents({}) == 0


@pytest.mark.parametrize("template_id", ["../x", "/etc/passwd", "generic/../../x", "~/x", ""])
def test_request_rejects_path_like_template_ids(template_id):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="slash-separated"):
        from_run.FromRunRequest(data_root=S3_ROOT, template_id=template_id)


# ── confinement ──────────────────────────────────────────────────────────────


def _escaping_resolver(tag: str = "samplesheet", location: str = ESCAPING_LOCATION):
    """Resolve for real, then point one data collection outside the root.

    Stands in for a template bundle that does not use ``{DATA_ROOT}``. Nothing
    downstream would notice: ``ScanSingle.validate_filename`` does no path
    validation in server context, ``remote_scan_for_dc`` copies a ``single``
    collection's filename verbatim into ``url`` mode, and the preview reports
    an off-root location as ``ok`` with nothing matched.
    """
    from depictio.cli.cli.utils import templates as templates_module

    real = templates_module.resolve_template

    def _resolve(*args, **kwargs):
        config, metadata, origin, dashboards, resolved = real(*args, **kwargs)
        for workflow in config["workflows"]:
            for dc in workflow["data_collections"]:
                if dc["data_collection_tag"] == tag:
                    dc["config"]["scan"] = {
                        "mode": "url",
                        "scan_parameters": {"url": location},
                    }
        return config, metadata, origin, dashboards, resolved

    return patch.object(templates_module, "resolve_template", side_effect=_resolve)


def test_a_dc_that_escapes_the_data_root_is_refused(mock_db, megatest_s3):
    megatest_s3()
    with _escaping_resolver(), pytest.raises(HTTPException) as exc:
        _call(project_name="escapee")
    assert exc.value.status_code == 422
    assert "samplesheet" in exc.value.detail
    assert ESCAPING_LOCATION in exc.value.detail
    assert mock_db["projects"].count_documents({}) == 0


def test_a_dc_on_another_bucket_is_refused(mock_db, megatest_s3):
    megatest_s3()
    other = "s3://someone-elses-bucket/secrets.csv"
    with _escaping_resolver(location=other), pytest.raises(HTTPException) as exc:
        _call(project_name="escapee", dry_run=True)
    assert exc.value.status_code == 422
    assert other in exc.value.detail


# ── variable confinement ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "/etc/hostname",
        "s3://someone-elses-bucket/x",
        "input/../../x",
    ],
)
def test_a_variable_pointing_outside_the_root_is_refused(mock_db, megatest_s3, value):
    megatest_s3()
    with pytest.raises(HTTPException) as exc:
        _call(project_name="escapee", variables={"METADATA_FILE": value}, dry_run=True)
    assert exc.value.status_code == 422
    assert "METADATA_FILE" in exc.value.detail
    assert mock_db["projects"].count_documents({}) == 0


def test_variables_that_stay_under_the_root_are_accepted(mock_db, megatest_s3):
    megatest_s3()
    same_root_file = f"{S3_ROOT}/input/Metadata_full.tsv"
    report = _call(
        project_name="run42",
        # An s3:// URL under the same root, and a plain relative key: neither
        # is refused.
        variables={"METADATA_FILE": same_root_file, "GROUP_COL": "habitat"},
        dry_run=True,
    )
    assert report.success is True


# ── dry run ──────────────────────────────────────────────────────────────────


def test_dry_run_reports_every_collection_and_creates_nothing(mock_db, megatest_s3):
    megatest_s3()
    report = _call(project_name="run42", dry_run=True)

    assert report.success is True
    assert report.dry_run is True
    assert report.project_id is None
    assert report.run_id is None
    assert report.dashboards == []
    assert report.project_name == "run42"
    assert report.template_id == TEMPLATE_ID
    assert report.data_root == S3_ROOT
    assert report.truncated is False
    # ampliseq is a `flat` structure, so there are no per-run directories.
    assert report.detected_runs == []
    # The derived decisions the conditionals gate on ride along.
    assert report.resolved_variables["GROUP_COL"] == "habitat"

    rows = _rows(report)
    # A remote root turns the recursive multiqc scan into a prefix scan.
    assert (rows["multiqc_data"].kind, rows["multiqc_data"].mode) == ("scan", "s3_prefix")
    assert (rows["multiqc_data"].status, rows["multiqc_data"].matched) == ("ok", 1)
    assert rows["samplesheet"].location.startswith(S3_ROOT)
    # A recipe whose required source is absent from this run folder.
    assert rows["alpha_rarefaction"].kind == "recipe"
    assert rows["alpha_rarefaction"].status == "missing"
    assert rows["alpha_rarefaction"].missing_sources

    assert mock_db["projects"].count_documents({}) == 0


def test_dry_run_reports_a_pruned_optional_collection(mock_db, megatest_s3):
    without_tree = {
        rel: body
        for rel, body in MEGATEST_TREE.items()
        if rel != "qiime2/phylogenetic_tree/tree.nwk"
    }
    megatest_s3(without_tree)
    report = _call(dry_run=True)

    assert report.pruned_optional_dcs == ["phylogenetic_tree_canonical"]
    row = _rows(report)["phylogenetic_tree_canonical"]
    assert (row.status, row.optional, row.matched) == ("pruned", True, 0)


# ── creation + background ingestion ──────────────────────────────────────────


def _imported_dashboard():
    return patch(
        "depictio.api.v1.endpoints.dashboards_endpoints.routes.import_dashboard_yaml_content",
        return_value={
            "success": True,
            "dashboard_id": str(ObjectId()),
            "title": "Ampliseq Overview",
        },
    )


def _run_from_folder(mock_db, user=None, project_name: str = "run42"):
    """Create the project for real, with the dashboard import and broker stubbed."""
    from depictio.api.v1.monitoring import store as monitoring_store

    user = user or _user()
    with (
        _imported_dashboard() as importer,
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task,
    ):
        report = _call(user=user, project_name=project_name)
    return report, user, importer, task


def test_a_real_run_creates_the_project_and_dispatches_one_task_per_collection(
    mock_db, megatest_s3
):
    megatest_s3()
    report, user, importer, task = _run_from_folder(mock_db)

    assert report.success is True
    assert report.dry_run is False
    assert report.project_id is not None
    assert report.run_id is not None

    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    assert stored is not None
    assert stored["name"] == "run42"
    assert stored["permissions"]["owners"][0]["_id"] == user.id

    # The template's dashboard was imported against the new project.
    assert importer.call_count == 1
    assert report.dashboards[0].success is True
    assert report.dashboards[0].title == "Ampliseq Overview"

    rows = _rows(report)
    ingestable = sorted(tag for tag, row in rows.items() if row.status != "missing")
    missing = {tag: row for tag, row in rows.items() if row.status == "missing"}
    # The template marks most of these collections optional (seed-only
    # canonicals, route-specific outputs); a couple are required.
    required_missing = sorted(tag for tag, row in missing.items() if not row.optional)
    optional_missing = sorted(tag for tag, row in missing.items() if row.optional)
    assert ingestable and required_missing and optional_missing  # exercises all three

    payloads = _dispatched_payloads(task)
    assert sorted(p["dc_tag"] for p in payloads) == ingestable
    assert all(p["run_id"] == report.run_id for p in payloads)
    assert all(p["project_id"] == report.project_id for p in payloads)
    assert all(p["dc_id"] and p["sync_files"] is True for p in payloads)
    assert all(p["user"]["id"] == str(user.id) for p in payloads)

    # A recipe DC's payload waits on its own recipe's dc_ref sources, only
    # those that still have a step in this run, never on a DC that has none.
    payloads_by_tag = {p["dc_tag"]: p for p in payloads}
    # Which recipes chain on which is the template's business; the invariant
    # is that every dependency named is a collection this run seeds a step for
    # (ingestable, or required-missing and so failed from the start).
    seeded = set(ingestable) | set(required_missing) | set(optional_missing)
    dependent = {tag: p["depends_on"] for tag, p in payloads_by_tag.items() if p.get("depends_on")}
    assert dependent, "at least one recipe collection waits on another"
    assert all(set(deps) <= seeded for deps in dependent.values())
    assert "depends_on" not in payloads_by_tag["multiqc_data"]
    assert "depends_on" not in payloads_by_tag["samplesheet"]
    assert "depends_on" not in payloads_by_tag["taxonomy_composition"]

    # A collection whose source is absent never reaches a worker. A required
    # one is seeded as a failed step saying why; one the template marks
    # optional is a nominal absence, seeded "skipped" instead.
    run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
    assert run_doc["command"] == "from_run"
    assert run_doc["data_root"] == S3_ROOT
    assert run_doc["project_id"] == report.project_id
    steps = {step["name"]: step for step in run_doc["steps"]}
    assert sorted(name for name, s in steps.items() if s["status"] == "pending") == ingestable
    assert sorted(name for name, s in steps.items() if s["status"] == "failed") == required_missing
    assert sorted(name for name, s in steps.items() if s["status"] == "skipped") == optional_missing
    assert all(steps[name]["detail"] for name in required_missing)
    assert all(
        steps[name]["detail"].startswith("Skipped optional collection:")
        for name in optional_missing
    )
    # The run records each collection's real scan mode, not "manifest".
    modes = {dc["tag"]: dc["scan_mode"] for dc in run_doc["data_collections"]}
    assert modes["multiqc_data"] == "s3_prefix"
    assert modes["samplesheet"] == "url"
    assert modes["taxonomy_composition"] == "recipe"


def test_a_pruned_collection_is_absent_from_the_project_and_the_run(mock_db, megatest_s3):
    without_tree = {
        rel: body
        for rel, body in MEGATEST_TREE.items()
        if rel != "qiime2/phylogenetic_tree/tree.nwk"
    }
    megatest_s3(without_tree)
    report, _user_, _importer, task = _run_from_folder(mock_db)

    assert report.pruned_optional_dcs == ["phylogenetic_tree_canonical"]
    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    tags = {
        dc["data_collection_tag"] for wf in stored["workflows"] for dc in wf["data_collections"]
    }
    assert "phylogenetic_tree_canonical" not in tags
    dispatched = {payload["dc_tag"] for payload in _dispatched_payloads(task)}
    assert "phylogenetic_tree_canonical" not in dispatched


def test_dashboards_are_keyed_as_the_cli_keys_them(mock_db, megatest_s3):
    """A later ``depictio ingest`` of this project with the template finds them.

    ``nf-core/ampliseq:dashboards/base.yaml`` is the source key the CLI sends
    for the same file, so a re-import keeps or replaces the dashboard instead of
    adding a copy.
    """
    megatest_s3()
    report, _user_, importer, _task = _run_from_folder(mock_db)

    (call,) = importer.call_args_list
    assert call.args == ()
    assert call.kwargs["source_key"] == "nf-core/ampliseq:dashboards/base.yaml"
    assert call.kwargs["project_id"] == ObjectId(report.project_id)
    assert call.kwargs["keep_titles"] is True
    assert call.kwargs["existing"] == "keep"


def test_a_taken_project_name_is_refused_as_create_refuses_it(mock_db, megatest_s3):
    """The same check and error as POST /projects/create, before anything is written."""
    megatest_s3()
    first, user, _importer, _task = _run_from_folder(mock_db)

    with pytest.raises(HTTPException) as exc:
        _run_from_folder(mock_db, user=user)
    assert exc.value.status_code == 409
    assert exc.value.detail == routes._project_taken("name")["message"]
    assert mock_db["projects"].count_documents({}) == 1
    assert mock_db["ingestion_runs"].count_documents({}) == 1
    assert first.project_id is not None


def _token_doc(user: UserBase) -> dict:
    """A stored CLI token, what ``_build_cli_config_for_user`` needs to build a config."""
    later = datetime.now() + timedelta(days=1)
    return {
        "user_id": user.id,
        "access_token": "a.b.c",
        "refresh_token": "d.e.f",
        "expire_datetime": later,
        "refresh_expire_datetime": later,
    }


@pytest.mark.parametrize("bucket_list", ["PUBLIC", "CREDENTIALED"])
def test_the_preview_reads_the_run_folder_as_the_workers_will(
    mock_db, megatest_s3, monkeypatch, bucket_list
):
    """Same inputs, same target: the preview never accepts what ingestion refuses.

    A worker reads with ``_build_cli_config_for_user`` and the project's storage
    settings (``project_storage_for``), which a project made from a run folder
    does not have.
    """
    monkeypatch.delenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS")
    monkeypatch.setenv(f"DEPICTIO_REMOTE_{bucket_list}_S3_BUCKETS", S3_BUCKET)
    megatest_s3()
    decided: list[tuple[str, S3Target]] = []
    real = remote_fetch.s3_read_target

    def _spy(url, CLI_config=None):
        decided.append((url, real(url, CLI_config)))
        return decided[-1][1]

    monkeypatch.setattr(remote_fetch, "s3_read_target", _spy)
    report, user, _importer, _task = _run_from_folder(mock_db)

    # One decision, for the one listing that answered the whole request.
    ((url, previewed),) = decided
    assert url == f"s3://{S3_BUCKET}/{S3_KEY_PREFIX}"
    mock_db["tokens"].insert_one(_token_doc(user))
    worker_config = dc_utils._build_cli_config_for_user(
        user, remote_storage_options=storage_config.project_storage_for(report.project_id)
    )
    assert worker_config.remote_storage_options is None
    assert real(url, worker_config) == previewed
    assert previewed.kind == ("public" if bucket_list == "PUBLIC" else "ambient")


def test_poll_route_serves_a_from_run_ingestion(mock_db, megatest_s3):
    """`GET /projects/refresh_manifest/{run_id}` answers for this flow too."""
    from depictio.api.v1.monitoring import store as monitoring_store

    megatest_s3()
    report, user, _importer, _task = _run_from_folder(mock_db)

    with patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]):
        polled = manifest_ingest._get_refresh_run_report(report.run_id, user)

    assert polled.project_id == report.project_id
    assert polled.run_id == report.run_id
    assert polled.success is False  # still running
    rows = _rows(report)
    by_tag = {row.data_collection_tag: row for row in polled.refreshed}
    assert by_tag["multiqc_data"].status == "dispatched"
    assert by_tag["multiqc_data"].data_collection_id
    assert by_tag["alpha_rarefaction"].status == "failed"
    assert "alpha_rarefaction" not in [tag for tag, row in rows.items() if row.status != "missing"]
    # An optional collection the run folder doesn't produce polls "skipped",
    # not "failed": a nominal absence, not something that went wrong. Derived
    # from the report rather than named, since which optional collections a
    # megatest folder misses follows the template's recipes.
    optional_missing = [t for t, row in rows.items() if row.status == "missing" and row.optional]
    assert optional_missing
    assert all(by_tag[tag].status == "skipped" for tag in optional_missing)

    # A run belonging to somebody else is not readable.
    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        pytest.raises(HTTPException) as exc,
    ):
        manifest_ingest._get_refresh_run_report(report.run_id, _user())
    assert exc.value.status_code == 403


def test_an_unknown_command_is_still_not_pollable(mock_db):
    """Widening the poll route must not make every ingestion run readable."""
    from depictio.api.v1.monitoring import store as monitoring_store

    mock_db["ingestion_runs"].insert_one(
        {"run_id": "cli123", "command": "run", "user_id": "someone", "steps": []}
    )
    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        pytest.raises(HTTPException) as exc,
    ):
        manifest_ingest._get_refresh_run_report("cli123", _user(is_admin=True))
    assert exc.value.status_code == 404


# ── the route's own gates ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_public_mode_blocks_a_non_admin():
    from depictio.api.v1.endpoints.projects_endpoints import routes

    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = True
    payload = from_run.FromRunRequest(data_root=S3_ROOT, template_id=TEMPLATE_ID, dry_run=True)
    with (
        patch.object(routes, "settings", mock_settings),
        patch.object(routes, "_create_project_from_run") as work,
        pytest.raises(HTTPException) as exc,
    ):
        await routes.create_project_from_run(
            payload, _request(), current_user=_user(is_admin=False)
        )

    assert exc.value.status_code == 403
    assert "public/demo mode" in str(exc.value.detail)
    work.assert_not_called()


@pytest.mark.asyncio
async def test_an_admin_passes_the_public_mode_gate():
    from depictio.api.v1.endpoints.projects_endpoints import routes

    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = True
    payload = from_run.FromRunRequest(data_root=S3_ROOT, template_id=TEMPLATE_ID, dry_run=True)
    with (
        patch.object(routes, "settings", mock_settings),
        patch.object(routes, "_create_project_from_run", return_value={"gate": "passed"}) as work,
    ):
        await routes.create_project_from_run(payload, _request(), current_user=_user(is_admin=True))

    work.assert_called_once()


@pytest.mark.asyncio
async def test_no_user_401():
    from depictio.api.v1.endpoints.projects_endpoints import routes

    payload = from_run.FromRunRequest(data_root=S3_ROOT, template_id=TEMPLATE_ID)
    with pytest.raises(HTTPException) as exc:
        await routes.create_project_from_run(payload, _request(), current_user=None)
    assert exc.value.status_code == 401


# ── a run folder on the server's own disk (depictio local) ───────────────────


@pytest.fixture()
def local_home(tmp_path, monkeypatch):
    """Local folders on, ``home/`` the one root, the megatest tree at ``home/run42``."""
    home = tmp_path / "home"
    write_tree(home / "run42", MEGATEST_TREE)
    (home / ".hidden-runs" / "run1").mkdir(parents=True)
    (home / "depictio-local").mkdir()
    outside = tmp_path / "outside"
    write_tree(outside, MEGATEST_TREE)
    (home / "escape").symlink_to(outside)
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(home))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(home / "depictio-local"))
    return home


def _local_refusal(data_root: str, *, request=None, user=None):
    with pytest.raises(CodedHTTPException) as exc:
        _call(
            data_root=data_root,
            dry_run=True,
            request=_request() if request is None else request,
            user=user or _user(is_admin=True),
        )
    return exc.value


def test_a_local_folder_is_a_data_root_when_local_folders_are_on(mock_db, local_home):
    report = _call(
        data_root=str(local_home / "run42"),
        dry_run=True,
        request=_request(),
        user=_user(is_admin=True),
    )
    assert report.success is True
    assert report.data_root == os.path.realpath(local_home / "run42")
    rows = _rows(report)
    # A local root keeps the recursive multiqc scan, which a prefix turns into s3_prefix.
    assert (rows["multiqc_data"].mode, rows["multiqc_data"].status) == ("recursive", "ok")
    assert rows["samplesheet"].location.startswith(os.path.realpath(local_home / "run42"))
    assert mock_db["projects"].count_documents({}) == 0


def test_a_tilde_path_is_the_servers_home(mock_db, local_home, monkeypatch):
    monkeypatch.setenv("HOME", str(local_home))
    report = _call(data_root="~/run42", dry_run=True, request=_request(), user=_user(is_admin=True))
    assert report.data_root == os.path.realpath(local_home / "run42")


def test_a_local_folder_is_refused_when_local_folders_are_off(tmp_path):
    write_tree(tmp_path / "run42", MEGATEST_TREE)
    refused = _local_refusal(str(tmp_path / "run42"))
    assert (refused.status_code, refused.code) == (422, "local_folders_off")
    assert "s3://" in refused.detail


def test_with_local_folders_on_another_scheme_names_both_kinds(local_home):
    refused = _local_refusal("https://example.org/run1")
    assert (refused.status_code, refused.code) == (422, "data_root_unsupported")
    assert refused.detail == from_run.DATA_ROOT_RULE_LOCAL


@pytest.mark.parametrize("host", ["evil.example:8058", "depictio-backend:8058", None])
def test_a_local_folder_needs_a_loopback_host(local_home, host):
    request = _request(host) if host else _request(None)
    refused = _local_refusal(str(local_home / "run42"), request=request)
    assert (refused.status_code, refused.code) == (403, "non_loopback_host")


def test_a_local_folder_with_no_request_at_all_is_refused(local_home):
    with pytest.raises(CodedHTTPException) as exc:
        _call(data_root=str(local_home / "run42"), dry_run=True, user=_user(is_admin=True))
    assert exc.value.code == "non_loopback_host"


def test_a_local_folder_needs_an_administrator(local_home):
    refused = _local_refusal(str(local_home / "run42"), user=_user(is_admin=False))
    assert (refused.status_code, refused.code) == (403, "local_admin_only")


@pytest.mark.parametrize(
    ("rel", "code"),
    [
        ("escape", "local_path_outside"),
        ("run42/../../outside", "local_path_outside"),
        (".hidden-runs/run1", "local_path_hidden"),
        ("depictio-local", "local_path_denied"),
        ("nope", "local_path_missing"),
        ("run42/input/samplesheet.csv", "local_path_not_a_folder"),
    ],
)
def test_a_local_folder_the_policy_refuses_is_a_422_naming_only_the_typed_path(
    local_home, rel, code
):
    typed = f"{local_home}/{rel}"
    refused = _local_refusal(typed)
    assert (refused.status_code, refused.code) == (422, code)
    assert typed in refused.detail
    assert str(local_home.parent / "outside") not in refused.detail.replace(typed, "")


def test_a_relative_path_is_not_a_local_folder(local_home):
    refused = _local_refusal("run42")
    assert refused.code == "data_root_unsupported"


def test_an_oversized_folder_is_refused_before_resolution(local_home, monkeypatch):
    monkeypatch.setattr(from_run, "MAX_LOCAL_RUN_FILES", len(MEGATEST_TREE) - 1)
    with patch("depictio.cli.cli.utils.templates.resolve_template") as resolve:
        refused = _local_refusal(str(local_home / "run42"))
    assert (refused.status_code, refused.code) == (422, "local_run_too_large")
    resolve.assert_not_called()


def test_a_folder_at_the_cap_is_not_oversized(local_home, monkeypatch, mock_db):
    monkeypatch.setattr(from_run, "MAX_LOCAL_RUN_FILES", len(MEGATEST_TREE))
    report = _call(
        data_root=str(local_home / "run42"),
        dry_run=True,
        request=_request(),
        user=_user(is_admin=True),
    )
    assert report.success is True


def test_the_file_count_does_not_follow_links(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "one.csv").write_text("x")
    big = tmp_path / "big"
    big.mkdir()
    for index in range(5):
        (big / f"{index}.csv").write_text("x")
    (tmp_path / "run" / "linked").symlink_to(big)
    assert from_run._holds_more_files_than(str(tmp_path / "run"), 1) is False
    assert from_run._holds_more_files_than(str(big), 4) is True


def test_a_real_local_run_makes_the_recursive_scan_its_own_leader(mock_db, local_home):
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user(is_admin=True)
    with (
        _imported_dashboard(),
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task,
    ):
        report = _call(
            data_root=str(local_home / "run42"),
            project_name="local42",
            request=_request(),
            user=user,
        )
    assert report.success is True
    payloads = {p["dc_tag"]: p for p in _dispatched_payloads(task)}
    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    recursive = [
        str(dc["_id"])
        for wf in stored["workflows"]
        for dc in wf["data_collections"]
        if ((dc.get("config") or {}).get("scan") or {}).get("mode") == "recursive"
    ]
    assert recursive  # multiqc_data at least
    leaders = [p for p in payloads.values() if p.get("scan_dc_ids")]
    assert len(leaders) == 1
    assert sorted(leaders[0]["scan_dc_ids"]) == sorted(
        p["dc_id"] for p in payloads.values() if p["dc_id"] in recursive
    )
    run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
    assert run_doc["data_root"] == os.path.realpath(local_home / "run42")


# ── template detection ───────────────────────────────────────────────────────


def _detects(monkeypatch, template_id, info=None):
    from depictio.cli.cli.utils import run_detection

    seen = []

    def _detect(root):
        seen.append(root)
        return template_id, info

    monkeypatch.setattr(run_detection, "detect_template_for_root", _detect)
    return seen


def _ampliseq_info():
    from depictio.models.models.run_info import WorkflowRunInfo

    return WorkflowRunInfo(
        engine="nextflow", pipeline_name="nf-core/ampliseq", pipeline_version="2.16.0"
    )


def test_the_template_is_detected_when_none_is_given(mock_db, megatest_s3, monkeypatch):
    megatest_s3()
    seen = _detects(monkeypatch, TEMPLATE_ID, _ampliseq_info())
    report = _call(template_id=None, dry_run=True)

    assert report.template_id == TEMPLATE_ID
    assert report.detected_template is not None
    assert report.detected_template.model_dump() == {
        "template_id": TEMPLATE_ID,
        "pipeline": "nf-core/ampliseq",
        "version": "2.16.0",
        "engine": "nextflow",
    }
    # Detection reads the very root the preview reads: one listing.
    assert len(seen) == 1 and seen[0].location == S3_ROOT


def test_a_given_template_skips_detection(mock_db, megatest_s3, monkeypatch):
    megatest_s3()
    seen = _detects(monkeypatch, "nf-core/other/1")
    report = _call(dry_run=True)
    assert seen == []
    assert report.detected_template is None


def test_detection_on_a_local_folder(mock_db, local_home, monkeypatch):
    seen = _detects(monkeypatch, TEMPLATE_ID, _ampliseq_info())
    report = _call(
        data_root=str(local_home / "run42"),
        template_id=None,
        dry_run=True,
        request=_request(),
        user=_user(is_admin=True),
    )
    assert report.detected_template.template_id == TEMPLATE_ID
    assert seen[0].location == os.path.realpath(local_home / "run42")


def test_an_unrecognised_folder_is_template_not_detected(megatest_s3, monkeypatch):
    megatest_s3()
    _detects(monkeypatch, None)
    with pytest.raises(CodedHTTPException) as exc:
        _call(template_id=None, dry_run=True)
    assert (exc.value.status_code, exc.value.code) == (422, "template_not_detected")
    assert "not recognised" in exc.value.detail


def test_a_recognised_pipeline_with_no_template_says_which(megatest_s3, monkeypatch):
    from depictio.models.models.run_info import WorkflowRunInfo

    megatest_s3()
    _detects(
        monkeypatch,
        None,
        WorkflowRunInfo(engine="nextflow", pipeline_name="nf-core/sarek", pipeline_version="3.5.1"),
    )
    with pytest.raises(CodedHTTPException) as exc:
        _call(template_id=None, dry_run=True)
    assert exc.value.code == "template_not_detected"
    assert "nf-core/sarek 3.5.1" in exc.value.detail


def test_a_failed_read_during_detection_is_not_detected(megatest_s3, monkeypatch):
    from depictio.cli.cli.utils import run_detection

    megatest_s3()

    def _broken(_root):
        raise OSError("disk went away")

    monkeypatch.setattr(run_detection, "detect_template_for_root", _broken)
    with pytest.raises(CodedHTTPException) as exc:
        _call(template_id=None, dry_run=True)
    assert exc.value.code == "template_not_detected"
    assert "disk went away" not in exc.value.detail


def test_an_s3_failure_during_detection_keeps_its_code(megatest_s3, monkeypatch):
    from depictio.cli.cli.utils import run_detection

    megatest_s3()

    def _denied(_root):
        raise S3AccessFailed("denied", code="s3_access_denied", status_code=422)

    monkeypatch.setattr(run_detection, "detect_template_for_root", _denied)
    with pytest.raises(S3AccessFailed) as exc:
        _call(template_id=None, dry_run=True)
    assert exc.value.code == "s3_access_denied"


def test_the_request_may_leave_the_template_out():
    assert from_run.FromRunRequest(data_root=S3_ROOT).template_id is None
    assert from_run.FromRunRequest(data_root=S3_ROOT, template_id=None).template_id is None


@pytest.mark.asyncio
async def test_the_route_answers_template_not_detected_with_detail_and_code(
    megatest_s3, monkeypatch
):
    import json

    megatest_s3()
    _detects(monkeypatch, None)
    payload = from_run.FromRunRequest(data_root=S3_ROOT, dry_run=True)
    response = await routes.create_project_from_run(payload, _request(), current_user=_user())
    assert response.status_code == 422
    assert json.loads(response.body) == {
        "detail": "The pipeline that produced this folder was not recognised. Pick a "
        "template to continue.",
        "code": "template_not_detected",
    }


@pytest.mark.asyncio
async def test_the_route_passes_the_request_on(local_home):
    payload = from_run.FromRunRequest(data_root=str(local_home / "run42"), dry_run=True)
    response = await routes.create_project_from_run(
        payload, _request("evil.example"), current_user=_user(is_admin=True)
    )
    assert response.status_code == 403
    assert response.body and b"non_loopback_host" in response.body
