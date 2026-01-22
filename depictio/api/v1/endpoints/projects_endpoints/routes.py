from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from depictio.api.v1.db import dashboards_collection, deltatables_collection, projects_collection
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


# Endpoints
@projects_endpoint_router.get("/get/all", response_model=list[Project])
async def get_all_projects(current_user=Depends(get_current_user)) -> list:
    """Get all projects accessible for the current user.

    Args:
        current_user (User, optional): _description_. Defaults to Depends(get_current_user).

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
async def get_project_from_name(project_name: str, current_user=Depends(get_current_user)):
    """Get a project by name.

    Args:
        project_name (str): _Description of the project name to be retrieved.
        current_user (User, optional): _description_. Defaults to Depends(get_current_user).

    Returns:
        _type_: Project: The project object retrieved from the database.
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
async def create_project(project: Project, current_user=Depends(get_current_user)):
    """Create a new project."""
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
    # Find the project using simple query (no aggregation pipeline)
    # We don't need delta_location enrichment for deletion
    project_dict = _async_get_project_from_id(project_id, current_user, projects_collection)

    # Convert ObjectIds to strings
    project = ProjectResponse.from_mongo(project_dict)

    # Ensure the current_user is an owner
    if (
        current_user.id not in [owner.id for owner in project.permissions.owners]
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to delete this project.",
        )

    # Delete the project
    projects_collection.delete_one({"_id": ObjectId(project_id)})

    return {
        "success": True,
        "message": f"Project '{project.name}' with ID '{project.id}' deleted.",
    }


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
    ) or (not current_user.is_admin):
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
        or not current_user.is_admin
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
