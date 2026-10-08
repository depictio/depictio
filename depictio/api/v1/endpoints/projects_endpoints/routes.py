import asyncio
from collections.abc import Awaitable

import boto3
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    jbrowse_collection,
    multiqc_collection,
    project_storage_collection,
    projects_collection,
    runs_collection,
    users_collection,
)
from depictio.api.v1.endpoints.comments_endpoints.cascade import delete_threads_for_project
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import (
    cascade_project_visibility,
)
from depictio.api.v1.endpoints.dashboards_endpoints.version_store import (
    delete_project_versions,
)
from depictio.api.v1.endpoints.migrate_endpoints.routes import _collect_s3_locations_for_project
from depictio.api.v1.endpoints.projects_endpoints.export_template import (
    ExportTemplateRequest,
    build_template_bundle,
    bundle_to_zip,
)
from depictio.api.v1.endpoints.projects_endpoints.from_manifest import (
    FromManifestReport,
    FromManifestRequest,
    _create_project_from_manifest,
)
from depictio.api.v1.endpoints.projects_endpoints.from_run import (
    FromRunReport,
    FromRunRequest,
    _create_project_from_run,
)
from depictio.api.v1.endpoints.projects_endpoints.ingestion_report import (
    IngestionReport,
    IngestionSummary,
    build_ingestion_report,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import (
    CodedHTTPException,
    LocalDirListing,
    list_local_dirs,
)
from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import (
    IngestManifestRequest,
    ManifestIngestReport,
    ManifestRefreshReport,
    RefreshManifestRequest,
    _get_refresh_run_report,
    _ingest_manifest_into_project,
    _refresh_manifest_in_project,
)
from depictio.api.v1.endpoints.projects_endpoints.run_folders import (
    FindRunsRequest,
    FolderInspection,
    FolderInspectRequest,
    FoundRuns,
    S3DirListing,
    S3DirsRequest,
    find_runs,
    inspect_folder,
    list_s3_dirs,
)
from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
    ProjectStorageConfigIn,
    ProjectStorageConfigOut,
    ProjectStorageUnusable,
    RunStorageTestRequest,
    StorageTestResult,
    _delete_project_storage,
    _get_project_storage,
    _set_project_storage,
    _test_project_storage,
    _test_run_storage,
)
from depictio.api.v1.endpoints.projects_endpoints.templates_catalog import (
    TemplateCatalog,
    list_templates_catalog,
)
from depictio.api.v1.endpoints.projects_endpoints.utils import (
    _async_get_all_projects,
    _async_get_project_from_id,
    _async_get_project_from_name,
    get_project_with_delta_locations,
    validate_workflow_uniqueness_in_project,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.ingestion_roots import roots_refusal
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.projects import Project, ProjectPermissionRequest, ProjectResponse
from depictio.models.models.users import Permission, UserBase
from depictio.models.timestamps import preserved_creation_time, utc_now_str

projects_endpoint_router = APIRouter()

# Seed projects shipped via ``db_init`` and the ``depictio/projects/`` tree.
# Source of truth: each project's ``project.yaml`` ``id:`` field. Kept here so
# the ``/admin/clean_examples`` endpoint can wipe exactly these without
# string-matching project names.
SEED_PROJECT_IDS: tuple[str, ...] = (
    "646b0f3c1e4a2d7f8e5b8c9a",  # Iris — depictio/projects/init/iris/project.yaml
    "646b0f3c1e4a2d7f8e5b8c9d",  # Penguins — depictio/projects/init/penguins/project.yaml
    "646b0f3c1e4a2d7f8e5b8ca2",  # nf-core/ampliseq, latest version seeded: depictio/projects/nf-core/ampliseq/2.18.0/template.yaml
    "646b0f3c1e4a2d7f8e5b8d00",  # Advanced Visualisations — depictio/projects/init/advanced_viz_showcase/project.yaml
    "746b0f3c1e4a2d7f8e5b9ca2",  # nf-core/viralrecon 3.0.0 — depictio/projects/nf-core/viralrecon/3.0.0/template.yaml
)


def _cascade_delete_project(project_id: PyObjectId, project_name: str) -> None:
    """Delete a project's S3 objects, dependent Mongo documents, and the project
    document itself. Permission checks must already have been done by the caller —
    this helper is purely the cascade body extracted from ``delete_project``.
    """
    dc_agg = list(
        projects_collection.aggregate(
            [
                {"$match": {"_id": ObjectId(project_id)}},
                {"$unwind": "$workflows"},
                {"$unwind": "$workflows.data_collections"},
                {
                    "$project": {
                        "_id": 0,
                        "dc_id": "$workflows.data_collections._id",
                        "wf_id": "$workflows._id",
                    }
                },
            ]
        )
    )
    dc_ids: list[ObjectId] = [r["dc_id"] for r in dc_agg if isinstance(r.get("dc_id"), ObjectId)]
    # A run belongs to a workflow, not to a collection: `WorkflowRun` has a
    # `workflow_id` and no `data_collection_id` at all. This cascade used to
    # delete runs by collection, which could never match, so run documents
    # outlived their project. Not just litter: a scan skips runs it has already
    # registered, so re-creating a project on the same (static) workflow id
    # inherited the stale runs and silently registered no files for any
    # recursive-scan collection.
    wf_ids: list[ObjectId] = list(
        {r["wf_id"] for r in dc_agg if isinstance(r.get("wf_id"), ObjectId)}
    )

    # S3 cleanup is best-effort — Mongo cascade still runs even if the S3 store is down.
    if dc_ids:
        try:
            s3_paths = _collect_s3_locations_for_project(dc_ids, settings.s3.bucket)
            if s3_paths:
                s3_client = boto3.client(
                    "s3",
                    endpoint_url=settings.s3.endpoint_url,
                    aws_access_key_id=settings.s3.aws_access_key_id,
                    aws_secret_access_key=settings.s3.aws_secret_access_key,
                    region_name="us-east-1",
                    verify=settings.s3.verify_tls,
                )
                for prefix in s3_paths:
                    paginator = s3_client.get_paginator("list_objects_v2")
                    for page in paginator.paginate(
                        Bucket=settings.s3.bucket, Prefix=prefix.strip("/")
                    ):
                        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                        if keys:
                            s3_client.delete_objects(
                                Bucket=settings.s3.bucket, Delete={"Objects": keys}
                            )
                logger.info(f"Deleted S3 objects for project {project_id}: {s3_paths}")
        except Exception as exc:
            logger.warning(f"S3 cleanup failed for project {project_id} (non-fatal): {exc}")

    # data_collection_id may be stored as ObjectId or plain string depending on
    # the code path that wrote it — query both forms.
    if dc_ids:
        dc_query: dict = {"$in": dc_ids + [str(dc_id) for dc_id in dc_ids]}
        files_collection.delete_many({"data_collection_id": dc_query})
        deltatables_collection.delete_many({"data_collection_id": dc_query})
        multiqc_collection.delete_many({"data_collection_id": dc_query})
        jbrowse_collection.delete_many({"data_collection_id": dc_query})
        data_collections_collection.delete_many({"_id": {"$in": dc_ids}})

    if wf_ids:
        runs_collection.delete_many(
            {"workflow_id": {"$in": wf_ids + [str(wf_id) for wf_id in wf_ids]}}
        )

    dashboards_collection.delete_many({"project_id": ObjectId(project_id)})
    delete_threads_for_project(project_id)
    # The dashboards went without the dashboard delete route, so their version
    # ledgers and sequence counters have to follow here or outlive them.
    delete_project_versions(project_id)
    # Per-project storage credentials live in their own collection (never on
    # the project document); an orphaned config would keep an encrypted
    # secret around for a project that no longer exists.
    project_storage_collection.delete_one({"project_id": ObjectId(project_id)})
    projects_collection.delete_one({"_id": ObjectId(project_id)})
    logger.info(f"Project '{project_name}' ({project_id}) deleted with cascade.")


async def _run_ingest_off_loop(fn, **kwargs):
    """Run a sync ingest helper via ``asyncio.to_thread``.

    A project's stored storage config that cannot be used (secret encrypted
    with a key this instance does not have, endpoint no longer allowed) is
    turned into a clean HTTP error carrying the client-safe ``detail`` instead
    of a 500 traceback; the operator context stays in the log line.
    """
    try:
        return await asyncio.to_thread(fn, **kwargs)
    except ProjectStorageUnusable as exc:
        logger.error(f"Project storage unusable during {fn.__name__}: {exc}")
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _reject_non_admin_in_public_mode(current_user, action: str) -> None:
    """Public/demo-mode gate shared by the project-mutating manifest routes.

    Mirrors ``create_project``: visitors are auto-minted as authenticated temp
    users, so the per-project owner/editor gate alone would not stop them
    from ingesting arbitrary remote data into (or exporting) a project they
    can edit. Admins bypass it so they can still administer a demo.
    """
    if settings.auth.is_public_mode and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"{action} is disabled in public/demo mode for non-admin users",
        )


# Endpoints
@projects_endpoint_router.get("/get/all", response_model=list[Project])
async def get_all_projects(current_user=Depends(get_user_or_anonymous)) -> list:
    """Get all projects accessible for the current user.

    Uses ``get_user_or_anonymous`` so single-user / public mode works without a
    persisted token: the anonymous user (admin in single-user mode) hits the
    ``is_admin`` bypass in ``_async_get_all_projects`` and sees seed projects.

    Args:
        current_user (User, optional): Defaults to ``Depends(get_user_or_anonymous)``.

    Returns:
        List: List of projects.
    """
    return _async_get_all_projects(current_user, projects_collection)


@projects_endpoint_router.get("/get/from_id")
async def get_project_from_id(
    project_id: PyObjectId = Query(default="646b0f3c1e4a2d7f8e5b8c9a"),
    skip_enrichment: bool = Query(default=False),
    current_user=Depends(get_user_or_anonymous),
):
    """Get a project by ID, optionally with delta_locations joined via MongoDB aggregation.

    This endpoint retrieves a project from the database using its ID. By default, it joins
    delta_table_location data from the DeltaTableAggregated collection at query time.
    Set skip_enrichment=true for simple queries without delta_location joins (faster, safer).

    Args:
        project_id (PyObjectId, optional): The project ID to retrieve.
        skip_enrichment (bool, optional): Skip delta_location aggregation pipeline (default: False).
                                          Use True for project updates to get complete workflow objects.
        current_user (User, optional): The authenticated user. Defaults to Depends(get_user_or_anonymous).

    Returns:
        dict: Project document. If skip_enrichment=False (default), includes:
              - delta_location: S3 path to delta table (per data collection)
              - last_aggregation: Most recent aggregation metadata with column specs
              If skip_enrichment=True, returns basic project structure without enrichment.
    """
    if skip_enrichment:
        # Use simple query without aggregation pipeline
        project_dict = _async_get_project_from_id(project_id, current_user, projects_collection)
        return convert_objectid_to_str(project_dict)
    else:
        # Use aggregation pipeline with delta_location enrichment
        return await get_project_with_delta_locations(project_id, current_user)


@projects_endpoint_router.get("/get/from_name/{project_name}", response_model=Project)
async def get_project_from_name(project_name: str, current_user=Depends(get_user_or_anonymous)):
    """Get a project by name.

    Uses ``get_user_or_anonymous`` for parity with ``get/all`` so single-user /
    public mode resolves to the anonymous (admin) user and the admin bypass in
    ``_async_get_project_from_name`` returns the project.

    Args:
        project_name (str): The project name to be retrieved.
        current_user (User, optional): Defaults to ``Depends(get_user_or_anonymous)``.

    Returns:
        Project: The project object retrieved from the database.
    """
    return _async_get_project_from_name(project_name, current_user, projects_collection)


@projects_endpoint_router.get("/get/from_dashboard_id/{dashboard_id}")
async def get_project_from_dashboard_id(
    dashboard_id: PyObjectId, current_user=Depends(get_user_or_anonymous)
):
    """Get a project by dashboard ID with delta table locations."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    dashboard_response = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_response:
        raise HTTPException(status_code=404, detail="Dashboard not found.")

    if not dashboard_response.get("project_id"):
        raise HTTPException(status_code=404, detail="Project not found for this dashboard.")

    project_id = dashboard_response.get("project_id")
    project = await get_project_with_delta_locations(PyObjectId(project_id), current_user)

    dc_ids = []
    workflows = project.get("workflows", []) if isinstance(project, dict) else project.workflows
    if workflows:
        for workflow in workflows:
            data_collections = (
                workflow.get("data_collections", [])
                if isinstance(workflow, dict)
                else workflow.data_collections
            )
            if data_collections:
                for dc in data_collections:
                    dc_id = dc.get("_id") if isinstance(dc, dict) else dc.id
                    if dc_id:
                        dc_ids.append(dc_id)

    delta_locations = {}
    if dc_ids:
        deltatables_cursor = deltatables_collection.find(
            {"data_collection_id": {"$in": dc_ids}},
            {"data_collection_id": 1, "delta_table_location": 1},
        )

        for dt in deltatables_cursor:
            dc_id = str(dt["data_collection_id"])
            delta_locations[dc_id] = dt.get("delta_table_location")

    return {
        "project": project,
        "delta_locations": delta_locations,
    }


@projects_endpoint_router.get("/ingestion-report/{project_id}", response_model=IngestionReport)
async def get_ingestion_report(project_id: PyObjectId, current_user=Depends(get_user_or_anonymous)):
    """Traceable summary of what a template execution ingested vs. what it expected.

    Compares the project's frozen expected-DC manifest (required + optional, with
    gating reasons) against the latest scan stats and aggregation state, so the UI
    can show which data collections were identified, found-empty, or gated out.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    project = _async_get_project_from_id(project_id, current_user, projects_collection)
    return build_ingestion_report(project)


@projects_endpoint_router.get("/ingestion-health/{project_id}", response_model=IngestionSummary)
async def get_ingestion_health(project_id: PyObjectId, current_user=Depends(get_user_or_anonymous)):
    """Lightweight ingestion health summary (counts + health flag) for the dashboard banner."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    project = _async_get_project_from_id(project_id, current_user, projects_collection)
    return build_ingestion_report(project).summary


async def _project_exists(lookup: Awaitable[object]) -> bool:
    """Whether a project lookup found one. A 404, or nothing returned, means the value
    is free."""
    try:
        return await lookup is not None
    except HTTPException as e:
        if e.status_code == 404:
            return False
        raise


def _project_taken(reason_tag: str) -> dict:
    return {
        "success": False,
        "message": f"Project already exists using this {reason_tag}.",
        "status_code": 409,
    }


# Fields describing the *operator's machine* rather than the project's data:
# absolute paths on someone's laptop or a login node, the hostname they ran on,
# the exact command line. Interesting to whoever runs the ingestion, nobody
# else's business.
_OPERATOR_FIELDS = (
    "command_line",
    "cli_config_path",
    "project_config_path",
    "data_root",
    "cli_hostname",
)

# The same class of leak one level down: per-data-collection scan paths, and
# sample_rejected, which holds real paths the scan saw but did not match.
_DC_PATH_FIELDS = ("locations", "scan_pattern", "sample_rejected")

# A step's free text, written by the CLI from whatever it was doing.
_STEP_TEXT_FIELDS = ("detail", "error")


def _redact_run(run: dict, *, full: bool) -> dict:
    """Strip operator-machine details from a run unless the caller may see them.

    The case this exists for: a project with ``is_public: True`` passes
    ``_async_get_project_from_id`` for *any* authenticated user, including an
    anonymous one. Without redaction, publishing a project would also publish
    `/home/alice/...` and `hpc-login1` to strangers.

    Kept for everyone: status, steps with their counters and timings,
    progress, per-DC tallies, run error messages, timings, instance label,
    trigger. That is what makes the pane useful to a viewer trying to
    understand whether the data they are looking at is current.

    A step's free text is not kept: the CLI writes whatever it was doing into
    ``detail`` and ``error``, which is how a scan failure ends up carrying
    "The directory '/home/...' does not exist" and the provisioning step an
    email address.
    """
    if full:
        return run
    redacted = {k: v for k, v in run.items() if k not in _OPERATOR_FIELDS}
    # Emails of other users are a directory leak in a public project.
    redacted.pop("email", None)
    redacted.pop("user_id", None)
    steps = redacted.get("steps")
    if isinstance(steps, list):
        redacted["steps"] = [
            {k: v for k, v in step.items() if k not in _STEP_TEXT_FIELDS}
            if isinstance(step, dict)
            else step
            for step in steps
        ]
    collections = redacted.get("data_collections")
    if isinstance(collections, list):
        redacted["data_collections"] = [
            {k: v for k, v in dc.items() if k not in _DC_PATH_FIELDS}
            if isinstance(dc, dict)
            else dc
            for dc in collections
        ]
    errors = redacted.get("errors")
    if isinstance(errors, list):
        redacted["errors"] = [
            {k: v for k, v in err.items() if k != "file_path"} if isinstance(err, dict) else err
            for err in errors
        ]
    return redacted


@projects_endpoint_router.get("/ingestion-runs/{project_id}")
async def get_project_ingestion_runs(
    project_id: PyObjectId,
    limit: int = 50,
    skip: int = 0,
    current_user=Depends(get_user_or_anonymous),
):
    """Ingestion-run history for one project, newest first.

    Deliberately *not* an extension of the admin monitoring gate: that gate is
    all-or-nothing across every project, whereas the people who most need this
    are project editors who are not admins. Guarded instead by the same
    ``_async_get_project_from_id`` the ingestion report already uses, so
    visibility follows project permissions.

    Owners, editors and admins see runs in full; everyone else gets the
    operator-machine fields removed (see ``_redact_run``).
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")

    project = _async_get_project_from_id(project_id, current_user, projects_collection)
    # The people who may run an ingestion are the ones who may see how it ran.
    full = _may_trigger_ingestion(project, current_user)

    from depictio.api.v1.monitoring import store as monitoring_store

    # Sweep first, as the admin read paths do, so a run whose CLI died shows as
    # abandoned here too rather than "running" forever.
    await asyncio.to_thread(monitoring_store.mark_stale_ingestion_runs)
    runs = await asyncio.to_thread(
        monitoring_store.query_ingestion_runs,
        project_id=str(project_id),
        limit=limit,
        skip=skip,
    )
    return {"runs": [_redact_run(run, full=full) for run in runs], "redacted": not full}


def _unreachable_data_locations(project: dict) -> list[str]:
    """Configured data locations this server cannot read.

    A browser-triggered ingestion runs inside the API's own container, so the
    data has to be on a filesystem that container has mounted. On a deployment
    where the CLI runs on an HPC node and the API does not share its storage,
    every location here comes back unreadable — which is the honest answer, and
    much better than starting a run that finds nothing and reports success.
    """
    import os

    missing: list[str] = []
    for workflow in project.get("workflows", []) or []:
        for location in (workflow.get("data_location") or {}).get("locations") or []:
            if not os.path.isdir(location):
                missing.append(location)
    return missing


def _may_trigger_ingestion(project: dict, current_user) -> bool:
    """Owners, editors and admins may start an ingestion; viewers may not.

    Same bar as writing to the project, because that is what this does — it
    rewrites data collections.
    """
    if getattr(current_user, "is_admin", False):
        return True
    permissions = project.get("permissions") or {}
    user_id = str(current_user.id)
    return any(
        str(entry.get("_id")) == user_id
        for group in ("owners", "editors")
        for entry in (permissions.get(group) or [])
    )


@projects_endpoint_router.get("/ingestion/trigger-status/{project_id}")
async def get_ingestion_trigger_status(
    project_id: PyObjectId,
    current_user=Depends(get_user_or_anonymous),
):
    """Whether this project can be re-ingested from the browser, and why not.

    Two separate booleans, because they drive different UI. ``enabled`` is
    whether the server offers this at all — when it is false the control is not
    rendered, since a permanently dead button on every deployment that never
    turns the flag on is just noise. ``available`` is whether *this* caller can
    use it *right now*; when that is false the control is rendered and disabled
    with ``reason`` attached, because "the server cannot read /data/runs" is
    actionable and a missing button is not.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    project = _async_get_project_from_id(project_id, current_user, projects_collection)

    # Jobs off means there is nowhere to record the work, so the feature is not
    # merely unavailable — it is not offered.
    enabled = settings.ingestion.browser_trigger and settings.jobs.enabled
    if not enabled:
        return {"enabled": False, "available": False, "reason": None}

    if not _may_trigger_ingestion(project, current_user):
        return {
            "enabled": True,
            "available": False,
            "reason": "You need editor access to run an ingestion.",
        }

    # Server paths go to admins only, here and in every refusal below: whether
    # a path exists on this server is exactly what someone pointing a project
    # at arbitrary paths wants to learn. Everyone else gets a count.
    is_admin = bool(getattr(current_user, "is_admin", False))

    # The allowlist first, so the existence check below only ever runs on
    # paths inside it.
    refusal, outside = await asyncio.to_thread(roots_refusal, project)
    if refusal:
        status = {
            "enabled": True,
            "available": False,
            "reason": refusal,
            "outside_roots_count": len(outside),
        }
        if is_admin and outside:
            status["outside_roots"] = outside[:5]
        return status

    unreachable = await asyncio.to_thread(_unreachable_data_locations, project)
    if unreachable:
        status = {
            "enabled": True,
            "available": False,
            "reason": (
                "This server cannot read the project's data. Run the ingestion from a "
                "machine that can see it."
            ),
            "unreachable_count": len(unreachable),
        }
        if is_admin:
            status["unreachable_locations"] = unreachable[:5]
        return status
    return {"enabled": True, "available": True, "reason": None}


@projects_endpoint_router.post("/ingestion/trigger/{project_id}")
async def trigger_project_ingestion(
    project_id: PyObjectId,
    overwrite: bool = False,
    current_user=Depends(get_current_user),
):
    """Start a server-side ingestion of this project. Returns a job to poll.

    Off by default (``DEPICTIO_INGESTION_BROWSER_TRIGGER``) and useless where
    the API cannot see the data, so every precondition is checked here rather
    than discovered by a task that fails ten minutes later. Every path the
    project names must also sit inside ``DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS``
    (see ``ingestion_roots``); the task checks that again before it reads.
    """
    if not settings.ingestion.browser_trigger:
        raise HTTPException(status_code=404, detail="Browser-triggered ingestion is disabled.")
    if not settings.jobs.enabled:
        raise HTTPException(
            status_code=503,
            detail="Job tracking is disabled, so an ingestion could not be followed.",
        )

    project = _async_get_project_from_id(project_id, current_user, projects_collection)
    if not _may_trigger_ingestion(project, current_user):
        raise HTTPException(status_code=403, detail="Editor access is required to run ingestion.")

    is_admin = bool(getattr(current_user, "is_admin", False))
    refusal, outside = await asyncio.to_thread(roots_refusal, project)
    if refusal:
        if is_admin and outside:
            refusal += f" Outside: {', '.join(outside[:3])}"
        raise HTTPException(status_code=403, detail=refusal)

    unreachable = await asyncio.to_thread(_unreachable_data_locations, project)
    if unreachable:
        where = f": {', '.join(unreachable[:3])}" if is_admin else f" ({len(unreachable)})"
        raise HTTPException(
            status_code=409,
            detail=(
                f"This server cannot read the project's data locations{where}. "
                "Run the ingestion from a machine that can."
            ),
        )

    import uuid

    from depictio.api.v1.ingestion_tasks import run_project_ingestion
    from depictio.api.v1.jobs import store as jobs_store
    from depictio.models.models.jobs import Job

    # One ingestion per project at a time. Hand back whatever is already running
    # rather than starting a second full rewrite of the same tables.
    active = await asyncio.to_thread(
        jobs_store.find_active_job, kind="project.ingest", project_id=str(project_id)
    )
    if active:
        return {
            "job_id": active["job_id"],
            "run_id": active.get("ingestion_run_id"),
            "already_running": True,
        }

    run_id = str(uuid.uuid4())
    job, _created = await asyncio.to_thread(
        jobs_store.create_job,
        Job(
            job_id=uuid.uuid4().hex,
            kind="project.ingest",
            user_id=str(current_user.id),
            project_id=str(project_id),
            ingestion_run_id=run_id,
        ),
    )

    try:
        # Off the event loop: with the broker down, apply_async blocks on its
        # connection retries before it raises.
        async_result = await asyncio.to_thread(
            run_project_ingestion.apply_async,
            args=[
                {
                    "job_id": job.job_id,
                    "run_id": run_id,
                    "project_id": str(project_id),
                    "user_id": str(current_user.id),
                    "overwrite": overwrite,
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001 - kombu raises several types for a dead broker
        logger.error(f"Browser-triggered ingestion for project {project_id} not queued: {exc}")
        # Fail the job, or find_active_job would answer "already running" for
        # this project until the job's retention expires.
        await asyncio.to_thread(
            jobs_store.finish_job,
            job.job_id,
            status="failed",
            error=f"The ingestion could not be queued: {exc}",
        )
        raise HTTPException(
            status_code=503,
            detail="The ingestion could not be queued: the task broker is unreachable. "
            "Try again once the worker queue is back.",
        ) from exc
    await asyncio.to_thread(jobs_store.attach_task, job.job_id, async_result.id)
    logger.info(f"Browser-triggered ingestion for project {project_id}: job {job.job_id}")
    return {"job_id": job.job_id, "run_id": run_id, "already_running": False}


@projects_endpoint_router.post("/ingest_manifest", response_model=ManifestIngestReport)
async def ingest_manifest(
    payload: IngestManifestRequest,
    current_user=Depends(get_user_or_anonymous),
):
    """Ingest a remote Data Manifest into an existing project.

    Maps the manifest's ``type`` values onto the project's data-collection
    tags, switches each matched DC to ``scan.mode: manifest``, then runs
    scan + process in-process (same pipeline as ``/create_from_upload``).
    ``dry_run=true`` returns the type→tag mapping plan without touching the
    project. The manifest URL goes through the SSRF gateway before any fetch.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    _reject_non_admin_in_public_mode(current_user, "Manifest ingestion")
    if not payload.dry_run:
        from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
            _ensure_user_cli_token,
        )

        await _ensure_user_cli_token(current_user)
    return await _run_ingest_off_loop(
        _ingest_manifest_into_project,
        project_id=payload.project_id,
        manifest_url=payload.manifest_url,
        current_user=current_user,
        id_field=payload.id_field,
        url_field=payload.url_field,
        type_field=payload.type_field,
        run_field=payload.run_field,
        dry_run=payload.dry_run,
    )


@projects_endpoint_router.post("/refresh_manifest", response_model=ManifestRefreshReport)
async def refresh_manifest(
    payload: RefreshManifestRequest,
    current_user=Depends(get_user_or_anonymous),
):
    """Re-fetch and re-ingest a project's manifest-backed data collections.

    Overwrite-with-report semantics: File records sync to the manifest's
    current entries (``sync_files`` beats the identity-hash skip) and each
    Delta table is rebuilt from the resulting file set. A DC whose manifest
    no longer lists its type is reported failed and left untouched.
    ``dry_run=true`` reports what would refresh (per-DC entry counts) without
    touching any data.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    _reject_non_admin_in_public_mode(current_user, "Manifest refresh")
    if not payload.dry_run:
        from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
            _ensure_user_cli_token,
        )

        await _ensure_user_cli_token(current_user)
    return await _run_ingest_off_loop(
        _refresh_manifest_in_project,
        project_id=payload.project_id,
        current_user=current_user,
        data_collection_tag=payload.data_collection_tag,
        dry_run=payload.dry_run,
        async_run=payload.async_run,
    )


@projects_endpoint_router.get("/refresh_manifest/{run_id}", response_model=ManifestRefreshReport)
async def get_refresh_manifest_run(
    run_id: str,
    current_user=Depends(get_user_or_anonymous),
):
    """Poll an async manifest refresh (``async_run=true``) by its run_id.

    Aggregates the ingestion-run steps back into the same report shape as a
    synchronous refresh; ``success`` flips once every worker finished green.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    return await asyncio.to_thread(_get_refresh_run_report, run_id, current_user)


@projects_endpoint_router.post("/{project_id}/export_template")
async def export_project_template(
    project_id: str,
    payload: ExportTemplateRequest,
    current_user=Depends(get_user_or_anonymous),
):
    """Export the project and its dashboards as a template bundle (ZIP).

    The archive holds ``template.yaml`` + ``dashboards/*.yaml`` ready to drop
    into ``depictio/projects/<template_id>/``: runtime fields stripped, stored
    manifest URLs re-parameterized to ``{MANIFEST_URL}``, an optional local
    ``data_root`` prefix to ``{DATA_ROOT}``, dashboard references as portable
    tags. The bundle is round-trip-checked before it is returned.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    _reject_non_admin_in_public_mode(current_user, "Template export")
    bundle = await asyncio.to_thread(
        build_template_bundle,
        project_id,
        current_user,
        template_id=payload.template_id,
        description=payload.description,
        version=payload.version,
        data_root=payload.data_root,
    )
    return Response(
        content=bundle_to_zip(bundle),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{payload.template_id.replace("/", "_")}.zip"'
            )
        },
    )


@projects_endpoint_router.get("/{project_id}/storage", response_model=ProjectStorageConfigOut)
async def get_project_storage(project_id: str, current_user=Depends(get_user_or_anonymous)):
    """Storage config of a project (secret never returned — only ``has_secret``)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    return await asyncio.to_thread(_get_project_storage, project_id, current_user)


@projects_endpoint_router.put("/{project_id}/storage", response_model=ProjectStorageConfigOut)
async def set_project_storage(
    project_id: str,
    payload: ProjectStorageConfigIn,
    current_user=Depends(get_user_or_anonymous),
):
    """Attach S3-compatible credentials to a project (owners only).

    The secret is write-only: it is encrypted at rest and omitted secrets keep
    the stored value. The endpoint URL goes through the same host gating as
    remote data URLs.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    return await asyncio.to_thread(_set_project_storage, project_id, payload, current_user)


@projects_endpoint_router.delete("/{project_id}/storage")
async def delete_project_storage(project_id: str, current_user=Depends(get_user_or_anonymous)):
    """Remove a project's storage credentials (owners only)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    return await asyncio.to_thread(_delete_project_storage, project_id, current_user)


@projects_endpoint_router.post("/{project_id}/storage/test", response_model=StorageTestResult)
async def test_project_storage(project_id: str, current_user=Depends(get_user_or_anonymous)):
    """Probe the configured endpoint/bucket with the stored credentials."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    return await asyncio.to_thread(_test_project_storage, project_id, current_user)


# Storage settings typed in for a private bucket before the project exists: the
# same callers as POST /projects/from_run, which stores them.
PRIVATE_BUCKET_ACTION = "Reading a private bucket"


@projects_endpoint_router.post("/storage_test", response_model=StorageTestResult)
async def test_run_storage(
    payload: RunStorageTestRequest,
    current_user=Depends(get_user_or_anonymous),
):
    """Probe the bucket of ``location`` with storage settings that are not stored anywhere.

    The probes of ``POST /projects/{project_id}/storage/test`` (HeadBucket,
    region detection, one one-key listing under the location's prefix), for
    the settings of a project not created yet. Settings without an access key
    and its secret are a 422; other settings no read could use, and failed
    probes, answer ``success: false``. The detected region is answered, not
    saved.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    _reject_non_admin_in_public_mode(current_user, PRIVATE_BUCKET_ACTION)
    return await asyncio.to_thread(_test_run_storage, payload.location, payload.storage)


@projects_endpoint_router.get("/templates", response_model=TemplateCatalog)
async def list_project_templates(current_user=Depends(get_user_or_anonymous)):
    """List the project templates shipped with this instance.

    Backs the builder UI's template picker — the ``manifest_capable`` flag
    marks templates usable with ``POST /projects/from_manifest``. Purely
    filesystem-derived; template YAMLs that fail to parse are skipped.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    return await asyncio.to_thread(list_templates_catalog)


@projects_endpoint_router.post("/from_manifest", response_model=FromManifestReport)
async def create_project_from_manifest(
    payload: FromManifestRequest,
    current_user=Depends(get_user_or_anonymous),
):
    """Create a project (and its dashboards) from a template + a Data Manifest.

    The zero-install flow: fetch the manifest through the SSRF gateway,
    resolve the manifest-driven template server-side, coverage-check the
    manifest's ``type`` values against the template's DCs, create the
    project, ingest every manifest DC, and import the template's dashboards
    in-process. ``dry_run=true`` returns the plan (coverage + per-DC entry
    counts) without creating anything.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    # Mirror POST /projects/create's public/demo-mode gate.
    _reject_non_admin_in_public_mode(current_user, "Project creation")
    if not payload.dry_run:
        from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
            _ensure_user_cli_token,
        )

        await _ensure_user_cli_token(current_user)
    return await asyncio.to_thread(
        _create_project_from_manifest,
        manifest_url=payload.manifest_url,
        template_id=payload.template_id,
        current_user=current_user,
        project_name=payload.project_name,
        variables=payload.variables,
        dry_run=payload.dry_run,
    )


@projects_endpoint_router.post("/from_run", response_model=FromRunReport)
async def create_project_from_run(
    payload: FromRunRequest,
    request: Request,
    current_user=Depends(get_user_or_anonymous),
):
    """Create a project (and its dashboards) from a template + a run folder.

    The browser twin of ``depictio ingest <run folder> --template <id>``:
    resolve the template against the run folder, report per data collection
    what it would find there, create the project, import its dashboards, and
    hand the ingestion itself to Celery workers, since a real run folder is
    minutes of work, far past a request. The response carries a ``run_id`` to
    poll via ``GET /projects/refresh_manifest/{run_id}``. ``dry_run=true``
    returns the same per-collection plan and creates nothing.

    The run folder is an ``s3://`` prefix or, when local folders are on, a
    folder on the server's disk. Without ``template_id`` the pipeline is
    recognised from the folder (``detected_template`` in the report).

    A run folder in a private bucket comes with ``storage``: it is read with
    those settings alone, and they are stored on the created project before
    its ingestion starts (``storage_saved``); a failure to store them removes
    the project. A dry run stores nothing.

    A taken project name is a 409, as on ``POST /projects/create``. A run
    folder the server may not read, or whose read fails, and a pipeline that
    is not recognised answer ``{detail, code}``.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    # Mirror POST /projects/create's public/demo-mode gate.
    _reject_non_admin_in_public_mode(current_user, "Project creation")
    if not payload.dry_run:
        from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
            _ensure_user_cli_token,
        )

        await _ensure_user_cli_token(current_user)
    try:
        return await asyncio.to_thread(
            _create_project_from_run,
            data_root=payload.data_root,
            template_id=payload.template_id,
            current_user=current_user,
            project_name=payload.project_name,
            variables=payload.variables,
            dry_run=payload.dry_run,
            request=request,
            storage=payload.storage,
        )
    except CodedHTTPException as exc:
        return exc.response()


@projects_endpoint_router.get("/local_dirs", response_model=LocalDirListing)
async def get_local_dirs(
    request: Request,
    path: str | None = Query(default=None),
    current_user=Depends(get_user_or_anonymous),
):
    """List the sub-folders of ``path`` on the server's own disk, or the allowed roots.

    For ``depictio local``, where the server is the user's computer: backs the
    folder picker of ``POST /projects/from_run``. Sub-directories only, sorted,
    hidden folders and symlinks that leave the allowed roots left out, at most
    500 (``truncated`` says when there were more). 404 when local folders are
    off or the path is outside the allowed roots, refused or missing; 403 for a
    non-administrator or a request whose ``Host`` is not this machine.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    try:
        return await asyncio.to_thread(
            list_local_dirs, path, request=request, current_user=current_user
        )
    except CodedHTTPException as exc:
        return exc.response()


@projects_endpoint_router.get("/s3_dirs", response_model=S3DirListing)
async def get_s3_dirs(
    url: str | None = Query(default=None),
    current_user=Depends(get_user_or_anonymous),
):
    """List the sub-folders of ``url``, or the S3 locations an administrator listed.

    The S3 twin of ``GET /projects/local_dirs``, for any signed-in user: the
    locations are the public and credentialed bucket lists, the instance's own
    bucket never among them. One listing page per call, at most 500 folders
    (``truncated`` says when there were more). A location outside the lists,
    and a read the store refuses or fails, answer ``{detail, code}``.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    return await asyncio.to_thread(list_s3_dirs, url)


@projects_endpoint_router.post("/s3_dirs", response_model=S3DirListing)
async def post_s3_dirs(
    payload: S3DirsRequest,
    current_user=Depends(get_user_or_anonymous),
):
    """``GET /projects/s3_dirs``, with storage settings for a private bucket in the body.

    With ``storage``, ``url`` is read with those settings alone: the bucket
    lists do not apply and the bucket itself is the root. The settings are not
    stored. Without ``storage``, the GET route's answer.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if payload.storage is not None:
        _reject_non_admin_in_public_mode(current_user, PRIVATE_BUCKET_ACTION)
    return await asyncio.to_thread(list_s3_dirs, payload.url, payload.storage)


@projects_endpoint_router.get("/folder_inspect", response_model=FolderInspection)
async def get_folder_inspect(
    request: Request,
    location: str = Query(...),
    detect: bool = Query(default=True),
    current_user=Depends(get_user_or_anonymous),
):
    """Describe one folder: its direct sub-folders and files, whether it looks
    like a run, and (``detect``, the default) the template its run fits.

    ``location`` is a folder on this computer (``depictio local``, with the
    guards of ``GET /projects/local_dirs``) or an ``s3://`` location (with
    those of ``GET /projects/s3_dirs``). Refusals answer ``{detail, code}``.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    try:
        return await asyncio.to_thread(
            inspect_folder, location, detect=detect, request=request, current_user=current_user
        )
    except CodedHTTPException as exc:
        return exc.response()


@projects_endpoint_router.post("/folder_inspect", response_model=FolderInspection)
async def post_folder_inspect(
    payload: FolderInspectRequest,
    request: Request,
    current_user=Depends(get_user_or_anonymous),
):
    """``GET /projects/folder_inspect``, with storage settings for a private bucket.

    An ``s3://`` location is read, and its run detected, with ``storage``
    alone when given. The settings are not stored.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if payload.storage is not None:
        _reject_non_admin_in_public_mode(current_user, PRIVATE_BUCKET_ACTION)
    try:
        return await asyncio.to_thread(
            inspect_folder,
            payload.location,
            detect=payload.detect,
            storage=payload.storage,
            request=request,
            current_user=current_user,
        )
    except CodedHTTPException as exc:
        return exc.response()


@projects_endpoint_router.get("/find_runs", response_model=FoundRuns)
async def get_find_runs(
    request: Request,
    location: str = Query(...),
    current_user=Depends(get_user_or_anonymous),
):
    """Find the run folders (holding ``pipeline_info/`` or ``multiqc/``) below ``location``.

    Bounded: six levels and 5,000 folders below a local folder, 20,000 keys
    below an ``s3://`` prefix, 100 runs; ``truncated`` says when a bound
    stopped the search. Below a local folder the first 50 runs carry their
    detected template. Same locations and refusals as
    ``GET /projects/folder_inspect``.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    try:
        return await asyncio.to_thread(
            find_runs, location, request=request, current_user=current_user
        )
    except CodedHTTPException as exc:
        return exc.response()


@projects_endpoint_router.post("/find_runs", response_model=FoundRuns)
async def post_find_runs(
    payload: FindRunsRequest,
    request: Request,
    current_user=Depends(get_user_or_anonymous),
):
    """``GET /projects/find_runs``, with storage settings for a private bucket.

    An ``s3://`` location is listed with ``storage`` alone when given. The
    settings are not stored.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if payload.storage is not None:
        _reject_non_admin_in_public_mode(current_user, PRIVATE_BUCKET_ACTION)
    try:
        return await asyncio.to_thread(
            find_runs,
            payload.location,
            storage=payload.storage,
            request=request,
            current_user=current_user,
        )
    except CodedHTTPException as exc:
        return exc.response()


@projects_endpoint_router.post("/create")
async def create_project(project: Project, current_user=Depends(get_user_or_anonymous)):
    """Create a new project.

    Tolerates missing tokens so single-user / public mode can create projects
    without a persisted token — the inline owner / ``is_admin`` gate below
    still rejects callers who aren't listed as owners and aren't admins.

    Public/demo mode blocks creation for non-admin callers (anonymous + temp
    users) regardless of token: visitors are auto-minted as authenticated temp
    users, so the standard owner/admin gate wouldn't stop them from POSTing
    here directly. Admins bypass this gate so they can still administer a
    public/demo deployment. The frontend mirrors this (see Dash
    `app_layout.return_create_project_button` and React `ProjectsApp.tsx`).
    """
    if settings.auth.is_public_mode and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Project creation is disabled in public/demo mode for non-admin users",
        )

    if (
        current_user.id not in [owner.id for owner in project.permissions.owners]
        and not current_user.is_admin
    ):
        return {
            "success": False,
            "message": "User does not have permission to create this project.",
            "status_code": 403,
        }

    # One `_project_exists` per lookup, so a free name (its 404) does not skip the id
    # check. By keyword: get_project_from_id's second parameter is `skip_enrichment`.
    try:
        name_taken = await _project_exists(
            get_project_from_name(project_name=project.name, current_user=current_user)
        )
        id_taken = not name_taken and await _project_exists(
            get_project_from_id(
                project_id=project.id, skip_enrichment=True, current_user=current_user
            )
        )
    except HTTPException as e:
        return {"success": False, "message": str(e.detail), "status_code": e.status_code}
    if name_taken or id_taken:
        return _project_taken("name" if name_taken else "id")

    try:
        validate_workflow_uniqueness_in_project(project)
    except HTTPException as e:
        return {"success": False, "message": str(e.detail), "status_code": e.status_code}

    create_payload = project.mongo()
    create_payload["registration_time"] = utc_now_str()
    create_payload["last_modified"] = create_payload["registration_time"]
    try:
        projects_collection.insert_one(create_payload)
    except DuplicateKeyError:
        # The id lookup above only sees the projects this user may read.
        return _project_taken("id")

    return {
        "success": True,
        "message": f"Project '{project.name}' with ID '{project.id}' created.",
    }


@projects_endpoint_router.put("/update")
async def update_project(project: Project, current_user=Depends(get_current_user)):
    """Update an existing project."""
    if (
        current_user.id not in [owner.id for owner in project.permissions.owners]
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to update this project.",
        )

    existing_project_dict = _async_get_project_from_id(
        project.id, current_user, projects_collection
    )
    if not existing_project_dict:
        raise HTTPException(status_code=404, detail="Project not found.")

    validate_workflow_uniqueness_in_project(project)
    update_payload = project.mongo()
    # `registration_time` is write-once: the client round-trips the whole project
    # document, so trusting its payload would let an update reset the creation
    # date and make both time columns show the same value (issue #932).
    update_payload["registration_time"] = preserved_creation_time(
        existing_project_dict, project.id, utc_now_str()
    )
    # Visibility has a dedicated owner-gated path (`/toggle_public_private`)
    # that also cascades to the project's dashboards. The client round-trips
    # the whole project document, so honoring `is_public` here would flip
    # visibility silently without the cascade.
    update_payload["is_public"] = existing_project_dict.get("is_public", False)
    update_payload["last_modified"] = utc_now_str()
    projects_collection.update_one({"_id": project.id}, {"$set": update_payload})

    return {
        "success": True,
        "message": f"Project '{project.name}' with ID '{project.id}' updated.",
    }


@projects_endpoint_router.delete("/delete")
async def delete_project(project_id: PyObjectId, current_user=Depends(get_current_user)):
    project_dict = _async_get_project_from_id(project_id, current_user, projects_collection)
    project = ProjectResponse.from_mongo(project_dict)

    if (
        current_user.id not in [owner.id for owner in project.permissions.owners]
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to delete this project.",
        )

    _cascade_delete_project(project_id, project.name)

    return {
        "success": True,
        "message": f"Project '{project.name}' with ID '{project.id}' deleted.",
    }


@projects_endpoint_router.get("/admin/examples")
async def list_example_projects(current_user=Depends(get_user_or_anonymous)):
    """List seed projects that currently exist in Mongo. Admin-only.

    Tolerates anonymous (single-user / public mode) so the React admin page
    loads without a persisted token — the inline ``is_admin`` gate below still
    blocks non-admin users.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    rows = list(
        projects_collection.find(
            {"_id": {"$in": [ObjectId(pid) for pid in SEED_PROJECT_IDS]}},
            {"_id": 1, "name": 1},
        )
    )
    return [{"id": str(r["_id"]), "name": r.get("name", "")} for r in rows]


@projects_endpoint_router.post("/admin/clean_examples")
async def clean_example_projects(current_user=Depends(get_user_or_anonymous)):
    """Delete every seed project listed in ``SEED_PROJECT_IDS`` that still
    exists, cascading dashboards / workflows / data collections / S3 objects
    via ``_cascade_delete_project``. Admin-only.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    deleted: list[dict] = []
    for pid in SEED_PROJECT_IDS:
        row = projects_collection.find_one({"_id": ObjectId(pid)}, {"name": 1})
        if not row:
            continue
        _cascade_delete_project(PyObjectId(pid), row.get("name", ""))
        deleted.append({"id": pid, "name": row.get("name", "")})
    return {"deleted": deleted}


@projects_endpoint_router.post("/update_project_permissions")
async def add_or_update_permission(
    permission_request: ProjectPermissionRequest,
    current_user=Depends(get_current_user),
):
    """Update project permissions."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    project = _async_get_project_from_id(
        PyObjectId(permission_request.project_id), current_user, projects_collection
    )

    if (
        str(current_user.id)
        not in [str(owner["_id"]) for owner in project["permissions"]["owners"]]
    ) and (not current_user.is_admin):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to update permissions for this project.",
        )

    # Validate the incoming permissions through the Permission schema instead of
    # writing the caller-supplied dict raw into the document (mass-assignment).
    # ``Permission`` strips unknown keys per entry, resolves user references and
    # enforces that no user is simultaneously owner/editor/viewer.
    try:
        validated_permissions = Permission.model_validate(permission_request.permissions)
    except (ValidationError, ValueError) as exc:
        logger.warning(
            f"Rejected invalid permissions payload for project "
            f"'{permission_request.project_id}': {exc}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Invalid permissions payload: {exc}",
        )

    # A project must always keep at least one owner, otherwise it becomes
    # orphaned / unmanageable.
    if not validated_permissions.owners:
        raise HTTPException(
            status_code=400,
            detail="A project must keep at least one owner.",
        )

    # Sanity-check that every referenced user (owners/editors and non-wildcard
    # viewers) actually exists, so the caller cannot inject phantom principals.
    referenced_user_ids = {
        ObjectId(member.id)
        for group in (
            validated_permissions.owners,
            validated_permissions.editors,
            validated_permissions.viewers,
        )
        for member in group
        if isinstance(member, UserBase)
    }
    if referenced_user_ids:
        existing_count = users_collection.count_documents(
            {"_id": {"$in": list(referenced_user_ids)}}
        )
        if existing_count != len(referenced_user_ids):
            raise HTTPException(
                status_code=400,
                detail="Permissions reference one or more users that do not exist.",
            )

    project["permissions"] = validated_permissions.dict()
    project = ProjectResponse.from_mongo(project)
    project = project.mongo()

    project["last_modified"] = utc_now_str()
    projects_collection.update_one(
        {"_id": ObjectId(permission_request.project_id)},
        {"$set": project},
    )

    return {
        "success": True,
        "message": f"Succesfully updated permissions for project with ID '{permission_request.project_id}'.",
    }


@projects_endpoint_router.post("/toggle_public_private/{project_id}")
async def toggle_public_private(
    project_id: str, is_public: str, current_user=Depends(get_current_user)
):
    """Toggle project public/private visibility."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    project = _async_get_project_from_id(PyObjectId(project_id), current_user, projects_collection)

    if (
        str(current_user.id)
        not in [str(owner["_id"]) for owner in project["permissions"]["owners"]]
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to update this project.",
        )

    is_public_bool = is_public.lower() == "true"

    projects_collection.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"is_public": is_public_bool, "last_modified": utc_now_str()}},
    )

    # Visibility is project-driven: dashboards carry a derived `is_public`
    # flag (read by listings and badges) that must follow the project.
    cascade_counts = cascade_project_visibility(project_id, is_public_bool)

    return {
        "success": True,
        "message": f"Project '{project['name']}' with ID '{project_id}' is now {'public' if is_public_bool else 'private'}.",
        **cascade_counts,
    }
