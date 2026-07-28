import asyncio

import boto3
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    jbrowse_collection,
    multiqc_collection,
    projects_collection,
    runs_collection,
    users_collection,
)
from depictio.api.v1.endpoints.migrate_endpoints.routes import _collect_s3_locations_for_project
from depictio.api.v1.endpoints.projects_endpoints.ingestion_report import (
    IngestionReport,
    IngestionSummary,
    build_ingestion_report,
)
from depictio.api.v1.endpoints.projects_endpoints.utils import (
    _async_get_all_projects,
    _async_get_project_from_id,
    _async_get_project_from_name,
    get_project_with_delta_locations,
    validate_workflow_uniqueness_in_project,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.projects import Project, ProjectPermissionRequest, ProjectResponse
from depictio.models.models.users import Permission, UserBase

projects_endpoint_router = APIRouter()

# Seed projects shipped via ``db_init`` and the ``depictio/projects/`` tree.
# Source of truth: each project's ``project.yaml`` ``id:`` field. Kept here so
# the ``/admin/clean_examples`` endpoint can wipe exactly these without
# string-matching project names.
SEED_PROJECT_IDS: tuple[str, ...] = (
    "646b0f3c1e4a2d7f8e5b8c9a",  # Iris — depictio/projects/init/iris/project.yaml
    "646b0f3c1e4a2d7f8e5b8c9d",  # Penguins — depictio/projects/init/penguins/project.yaml
    "646b0f3c1e4a2d7f8e5b8ca2",  # nf-core/ampliseq 2.14.0 — depictio/projects/nf-core/ampliseq/2.14.0/project.yaml
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
                {"$project": {"_id": 0, "dc_id": "$workflows.data_collections._id"}},
            ]
        )
    )
    dc_ids: list[ObjectId] = [r["dc_id"] for r in dc_agg if isinstance(r.get("dc_id"), ObjectId)]

    # S3 cleanup is best-effort — Mongo cascade still runs even if MinIO is down.
    if dc_ids:
        try:
            s3_paths = _collect_s3_locations_for_project(dc_ids, settings.minio.bucket)
            if s3_paths:
                s3_client = boto3.client(
                    "s3",
                    endpoint_url=settings.minio.endpoint_url,
                    aws_access_key_id=settings.minio.aws_access_key_id,
                    aws_secret_access_key=settings.minio.aws_secret_access_key,
                    region_name="us-east-1",
                    verify=settings.minio.verify_tls,
                )
                for prefix in s3_paths:
                    paginator = s3_client.get_paginator("list_objects_v2")
                    for page in paginator.paginate(
                        Bucket=settings.minio.bucket, Prefix=prefix.strip("/")
                    ):
                        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                        if keys:
                            s3_client.delete_objects(
                                Bucket=settings.minio.bucket, Delete={"Objects": keys}
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
        runs_collection.delete_many({"data_collection_id": dc_query})
        multiqc_collection.delete_many({"data_collection_id": dc_query})
        jbrowse_collection.delete_many({"data_collection_id": dc_query})
        data_collections_collection.delete_many({"_id": {"$in": dc_ids}})

    dashboards_collection.delete_many({"project_id": ObjectId(project_id)})
    projects_collection.delete_one({"_id": ObjectId(project_id)})
    logger.info(f"Project '{project_name}' ({project_id}) deleted with cascade.")


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
              - delta_location: S3/MinIO path to delta table (per data collection)
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


def _redact_run(run: dict, *, full: bool) -> dict:
    """Strip operator-machine details from a run unless the caller may see them.

    The case this exists for: a project with ``is_public: True`` passes
    ``_async_get_project_from_id`` for *any* authenticated user, including an
    anonymous one. Without redaction, publishing a project would also publish
    `/home/alice/...` and `hpc-login1` to strangers.

    Kept for everyone: status, steps and their counters, progress, per-DC
    tallies, error messages, timings, instance label, trigger. That is what
    makes the pane useful to a viewer trying to understand whether the data
    they are looking at is current.
    """
    if full:
        return run
    redacted = {k: v for k, v in run.items() if k not in _OPERATOR_FIELDS}
    # Emails of other users are a directory leak in a public project.
    redacted.pop("email", None)
    redacted.pop("user_id", None)
    collections = redacted.get("data_collections")
    if isinstance(collections, list):
        redacted["data_collections"] = [
            {k: v for k, v in dc.items() if k not in ("locations", "scan_pattern")}
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
    # sample_rejected holds real paths from the scan — same class of leak.
    for dc in redacted.get("data_collections") or []:
        if isinstance(dc, dict):
            dc.pop("sample_rejected", None)
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

    permissions = project.get("permissions") or {}
    user_id = str(current_user.id)
    full = bool(getattr(current_user, "is_admin", False)) or any(
        str(entry.get("_id")) == user_id
        for group in ("owners", "editors")
        for entry in (permissions.get(group) or [])
    )

    from depictio.api.v1.monitoring import store as monitoring_store

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

    unreachable = await asyncio.to_thread(_unreachable_data_locations, project)
    if unreachable:
        return {
            "enabled": True,
            "available": False,
            "reason": (
                "This server cannot read the project's data. Run the ingestion from a "
                "machine that can see it."
            ),
            "unreachable_locations": unreachable[:5],
        }
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
    than discovered by a task that fails ten minutes later.
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

    unreachable = await asyncio.to_thread(_unreachable_data_locations, project)
    if unreachable:
        raise HTTPException(
            status_code=409,
            detail=(
                "This server cannot read the project's data locations: "
                f"{', '.join(unreachable[:3])}. Run the ingestion from a machine that can."
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

    async_result = run_project_ingestion.apply_async(
        args=[
            {
                "job_id": job.job_id,
                "run_id": run_id,
                "project_id": str(project_id),
                "user_id": str(current_user.id),
                "overwrite": overwrite,
            }
        ]
    )
    await asyncio.to_thread(jobs_store.attach_task, job.job_id, async_result.id)
    logger.info(f"Browser-triggered ingestion for project {project_id}: job {job.job_id}")
    return {"job_id": job.job_id, "run_id": run_id, "already_running": False}


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

    try:
        if (
            current_user.id not in [owner.id for owner in project.permissions.owners]
            and not current_user.is_admin
        ):
            return {
                "success": False,
                "message": "User does not have permission to create this project.",
                "status_code": 403,
            }

        existing_project_using_name = await get_project_from_name(project.name, current_user)
        existing_project_using_id = await get_project_from_id(project.id, current_user)
        if existing_project_using_name or existing_project_using_id:
            reason_tag = "name" if existing_project_using_name else "id"
            return {
                "success": False,
                "message": f"Project already exists using this {reason_tag}.",
                "status_code": 409,
            }
    except HTTPException as e:
        if e.status_code != 404:
            return {"success": False, "message": str(e.detail), "status_code": e.status_code}

    try:
        validate_workflow_uniqueness_in_project(project)
    except HTTPException as e:
        return {"success": False, "message": str(e.detail), "status_code": e.status_code}

    projects_collection.insert_one(project.mongo())

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
    projects_collection.update_one({"_id": project.id}, {"$set": project.mongo()})

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
        {"_id": ObjectId(project_id)}, {"$set": {"is_public": is_public_bool}}
    )

    return {
        "success": True,
        "message": f"Project '{project['name']}' with ID '{project_id}' is now {'public' if is_public_bool else 'private'}.",
    }
