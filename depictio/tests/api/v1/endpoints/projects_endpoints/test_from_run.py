"""Tests for POST /projects/from_run (`_create_project_from_run`).

Orchestration-contract tests: the data root has to be an ``s3://`` prefix this
server is allowed to read (decided from configuration, before any request goes
out), a resolved template may not point outside that prefix, a dry run creates
nothing, and a real run creates the project, imports its dashboards and hands
one Celery task per ingestable data collection to the refresh machinery.

No network. The S3 listing is the shared CLI stub (``depictio/tests/cli/
s3_stubs.py``): the key list handed to it *is* the bucket, so the real
``nf-core/ampliseq/2.16.0`` template resolves against a fixture shaped like the
AWS megatest prefix. The heavy legs (scan → Delta, dashboard tag binding) are
covered by their own suites and patched at their seams here.
"""

from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import from_run, manifest_ingest
from depictio.cli.cli.utils import data_root as data_root_module
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import MEGATEST_TREE, S3_BUCKET, S3_ROOT, install_s3_listing

TEMPLATE_ID = "nf-core/ampliseq/2.16.0"

# Where a template that escaped its run folder could reach: the container path
# the JWT signing key is mounted under.
ESCAPING_LOCATION = "/app/depictio/keys/private_key.pem"

# Credential env vars boto3's own chain would pick up. ``S3DataRoot`` counts
# them as "credentials are configured for this", which is exactly what the
# allowlist test must not have.
_AMBIENT_AWS_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_PROFILE",
    "AWS_ROLE_ARN",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
)


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _call(
    data_root: str = S3_ROOT,
    template_id: str = TEMPLATE_ID,
    user=None,
    project_name: str | None = None,
    variables: dict[str, str] | None = None,
    dry_run: bool = False,
):
    return from_run._create_project_from_run(
        data_root=data_root,
        template_id=template_id,
        current_user=user or _user(),
        project_name=project_name,
        variables=variables,
        dry_run=dry_run,
    )


@pytest.fixture()
def no_ambient_credentials(monkeypatch):
    """A server with no S3 credentials of its own, so the allowlist decides."""
    for name in _AMBIENT_AWS_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def allowlisted_bucket(monkeypatch, no_ambient_credentials):
    """The megatest bucket marked public, the way an administrator would."""
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)


@pytest.fixture()
def mock_db(monkeypatch):
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(from_run, "projects_collection", database["projects"]),
        patch.object(manifest_ingest, "projects_collection", database["projects"]),
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
    ):
        yield database


@pytest.fixture()
def megatest_s3(monkeypatch, allowlisted_bucket):
    """Serve the megatest fixture tree; returns an installer for a variant tree."""
    from depictio.tests.cli.s3_stubs import S3_KEY_PREFIX

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
def test_non_s3_data_root_422(data_root, no_ambient_credentials):
    with pytest.raises(HTTPException) as exc:
        _call(data_root=data_root, dry_run=True)
    assert exc.value.status_code == 422
    assert "s3://" in exc.value.detail


def test_unreadable_bucket_422_without_ever_building_a_client(monkeypatch, no_ambient_credentials):
    """Neither allowlisted nor credentialed: refused from configuration alone.

    Nothing may go out over the wire — the error S3 returns for a bucket that
    exists but is not ours would otherwise turn any bucket name into an
    existence-and-region oracle.
    """
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "some-other-bucket")

    def _never(*_args, **_kwargs):
        raise AssertionError("an S3 client was built for a bucket that was refused")

    monkeypatch.setattr(data_root_module, "s3_read_client", _never)

    with pytest.raises(HTTPException) as exc:
        _call(data_root="s3://private-bucket/run1", dry_run=True)
    assert exc.value.status_code == 422
    assert "DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS" in exc.value.detail


def test_malformed_s3_prefix_422(no_ambient_credentials):
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


def test_path_like_template_id_422_before_any_lookup(mock_db, no_ambient_credentials):
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
    assert payloads_by_tag["taxonomy_heatmap"]["depends_on"] == [
        "taxonomy_rel_abundance",
        "metadata",
    ]
    assert payloads_by_tag["embedding_pcoa"]["depends_on"] == ["taxonomy_heatmap", "metadata"]
    # bray_curtis_canonical's only dc_ref (taxonomy_rel_abundance) is a
    # required-missing collection: seeded failed (terminal) from the start,
    # still named as a dependency so the worker never has to guess why.
    assert payloads_by_tag["bray_curtis_canonical"]["depends_on"] == ["taxonomy_rel_abundance"]
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


def test_duplicate_project_name_409(mock_db, megatest_s3):
    megatest_s3()
    mock_db["projects"].insert_one({"_id": ObjectId(), "name": "run42"})
    with pytest.raises(HTTPException) as exc:
        _call(project_name="run42")
    assert exc.value.status_code == 409
    assert mock_db["projects"].count_documents({}) == 1


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
    # not "failed": a nominal absence, not something that went wrong.
    assert by_tag["sankey_canonical"].status == "skipped"

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
        await routes.create_project_from_run(payload, current_user=_user(is_admin=False))

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
        await routes.create_project_from_run(payload, current_user=_user(is_admin=True))

    work.assert_called_once()


@pytest.mark.asyncio
async def test_no_user_401():
    from depictio.api.v1.endpoints.projects_endpoints import routes

    payload = from_run.FromRunRequest(data_root=S3_ROOT, template_id=TEMPLATE_ID)
    with pytest.raises(HTTPException) as exc:
        await routes.create_project_from_run(payload, current_user=None)
    assert exc.value.status_code == 401
