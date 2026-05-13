import boto3
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

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
)
from depictio.api.v1.endpoints.migrate_endpoints.routes import _collect_s3_locations_for_project
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

projects_endpoint_router = APIRouter()

# Seed projects shipped via ``db_init`` and the ``depictio/projects/`` tree.
# Source of truth: each project's ``project.yaml`` ``id:`` field. Kept here so
# the ``/admin/clean_examples`` endpoint can wipe exactly these without
# string-matching project names.
SEED_PROJECT_IDS: tuple[str, ...] = (
    "646b0f3c1e4a2d7f8e5b8c9a",  # Iris — depictio/projects/init/iris/project.yaml
    "646b0f3c1e4a2d7f8e5b8c9d",  # Penguins — depictio/projects/init/penguins/project.yaml
    "646b0f3c1e4a2d7f8e5b8ca2",  # nf-core/ampliseq 2.14.0 — depictio/projects/nf-core/ampliseq/2.14.0/project.yaml
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
                    aws_access_key_id=settings.minio.root_user,
                    aws_secret_access_key=settings.minio.root_password,
                    region_name="us-east-1",
                    verify=False,
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


@projects_endpoint_router.post("/create")
async def create_project(project: Project, current_user=Depends(get_user_or_anonymous)):
    """Create a new project.

    Tolerates missing tokens so single-user / public mode can create projects
    without a persisted token — the inline owner / ``is_admin`` gate below
    still rejects callers who aren't listed as owners and aren't admins.

    Public/demo mode hard-blocks creation regardless of token: visitors are
    auto-minted as authenticated temp users, so the standard owner/admin gate
    wouldn't stop them from POSTing here directly. The frontend disables the
    "Create Project" button in public mode (see Dash
    `app_layout.return_create_project_button` and React `ProjectsApp.tsx`),
    and this check is the matching server-side enforcement.
    """
    if settings.auth.is_public_mode:
        raise HTTPException(
            status_code=403,
            detail="Project creation is disabled in public/demo mode",
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

    project["permissions"] = permission_request.permissions
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
