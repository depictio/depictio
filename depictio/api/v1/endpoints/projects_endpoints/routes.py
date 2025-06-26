from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

# depictio imports
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.endpoints.projects_endpoints.utils import (
    _async_get_all_projects,
    _async_get_project_from_id,
    _async_get_project_from_name,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.models.models.base import PyObjectId

## depictio-models imports
from depictio.models.models.projects import Project, ProjectPermissionRequest
from depictio.models.models.users import User

# Define the router
projects_endpoint_router = APIRouter()


# Endpoints
@projects_endpoint_router.get("/get/all", response_model=list[Project])
async def get_all_projects(current_user: User = Depends(get_current_user)) -> list:
    """Get all projects accessible for the current user.

    Args:
        current_user (User, optional): _description_. Defaults to Depends(get_current_user).

    Returns:
        List: List of projects.
    """
    return _async_get_all_projects(current_user, projects_collection)


@projects_endpoint_router.get("/get/from_id", response_model=Project)
async def get_project_from_id(
    project_id: PyObjectId = Query(default="646b0f3c1e4a2d7f8e5b8c9a"),
    current_user: User = Depends(get_user_or_anonymous),
):
    """Get a project by ID.
    This endpoint retrieves a project from the database using its ID. It checks if the user has the necessary permissions to access the project.

    Args:
        project_id (PyObjectId, optional): _description_. Defaults to Query(default="646b0f3c1e4a2d7f8e5b8c9a").
        current_user (User, optional): _description_. Defaults to Depends(get_current_user).

    Returns:
        _type_: Project: The project object retrieved from the database.
    """
    return _async_get_project_from_id(project_id, current_user, projects_collection)


@projects_endpoint_router.get("/get/from_name/{project_name}", response_model=Project)
async def get_project_from_name(project_name: str, current_user: User = Depends(get_current_user)):
    """Get a project by name.

    Args:
        project_name (str): _Description of the project name to be retrieved.
        current_user (User, optional): _description_. Defaults to Depends(get_current_user).

    Returns:
        _type_: Project: The project object retrieved from the database.
    """
    return _async_get_project_from_name(project_name, current_user, projects_collection)


@projects_endpoint_router.get("/get/from_dashboard_id/{dashboard_id}", response_model=Project)
async def get_project_from_dashboard_id(
    dashboard_id: PyObjectId, current_user: User = Depends(get_user_or_anonymous)
):
    logger.info(f"Getting project with dashboard ID: {dashboard_id}")
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Complex query to first retrieve the project ID from the dashboard ID inside the dashboards_collection & then retrieve the project from the projects_collection
    query = {
        "dashboard_id": dashboard_id,
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {"permissions.viewers": "*"},  # This makes projects with "*" publicly accessible
            {"is_public": True},  # Allow access to public dashboards
        ],
    }
    response = dashboards_collection.find_one(query)
    if not response:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    if not response.get("project_id"):
        raise HTTPException(status_code=404, detail="Project not found.")
    project_id = response.get("project_id")

    project = await get_project_from_id(str(project_id), current_user)
    return project


@projects_endpoint_router.post("/create")
async def create_project(project: Project, current_user: User = Depends(get_current_user)):
    try:
        # Ensure the current_user is an owner
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
        if e.status_code != 404:  # If error is not "not found"
            return {"success": False, "message": str(e.detail), "status_code": e.status_code}

    logger.info(f"Creating project: {project}")
    logger.info(f"Creating mongo project: {project.mongo()}")

    # Save the project to the database
    projects_collection.insert_one(project.mongo())

    return {
        "success": True,
        "message": f"Project '{project.name}' with ID '{project.id}' created.",
        # "status_code": 201,
    }


@projects_endpoint_router.put("/update")
async def update_project(project: Project, current_user: User = Depends(get_current_user)):
    # Convert project to Project object
    # project = Project.from_mongo(project)
    logger.info(f"Updating project: {project}")

    # Ensure the current_user is an owner
    if (
        current_user.id not in [owner.id for owner in project.permissions.owners]
        or not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to update this project.",
        )

    try:
        existing_project = await get_project_from_name(project.name, current_user)
        if not existing_project:
            raise HTTPException(status_code=404, detail="Project not found.")
    except HTTPException as e:
        raise e

    existing_project = Project.from_mongo(existing_project)
    logger.info(f"Existing project: {existing_project}")

    # Update the project in the database
    projects_collection.update_one({"_id": project.id}, {"$set": project.mongo()})

    return {
        "success": True,
        "message": f"Project '{project.name}' with ID '{project.id}' updated.",
    }


@projects_endpoint_router.delete("/delete")
async def delete_project(project_id: PyObjectId, current_user: User = Depends(get_current_user)):
    # Find the project
    project = await get_project_from_id(project_id, current_user)

    # Ensure the current_user is an owner
    if (
        current_user.id not in [owner.id for owner in project.permissions.owners]
        or not current_user.is_admin
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
    current_user: str = Depends(get_current_user),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find the project
    project = await get_project_from_id(permission_request.project_id, current_user)
    logger.info(f"Project: {project}")
    logger.info(f"Owners ids : {[owner['_id'] for owner in project['permissions']['owners']]}")
    logger.info(f"Current user id: {current_user.id}")
    logger.info(f"Is admin: {current_user.is_admin}")

    # Ensure the current_user is an owner
    if (
        str(current_user.id)
        not in [str(owner["_id"]) for owner in project["permissions"]["owners"]]
    ) or (not current_user.is_admin):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to update permissions for this project.",
        )

    logger.info(f"Adding/Updating permission: {permission_request}")

    # Update the project permissions only in the database
    logger.info(f"Updating project permissions: {project}")
    logger.info(f"Permission: {permission_request.permissions}")
    logger.info(f"Before update: {project['permissions']}")
    project["permissions"] = permission_request.permissions
    logger.info(f"Updated project permissions: {project['permissions']}")
    project = Project.from_mongo(project)
    logger.info(f"Project: {project}")
    project = project.mongo()
    logger.info(f"Project: {project}")

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
    project_id: str, is_public: str, current_user: str = Depends(get_current_user)
):
    logger.info(f"Toggle project with ID: {project_id}")
    logger.info(f"Is public: {is_public}")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find the project
    project = await get_project_from_id(project_id, current_user)

    # Ensure the current_user is an owner
    if (
        str(current_user.id)
        not in [str(owner["_id"]) for owner in project["permissions"]["owners"]]
        or not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to update this project.",
        )

    # Convert string to proper boolean
    is_public_bool = True if is_public.lower() == "true" else False

    # Toggle the project's is_public field
    project["is_public"] = is_public_bool
    logger.info(f"Project: {project}")

    # Update the project in the database
    projects_collection.update_one(
        {"_id": ObjectId(project_id)}, {"$set": {"is_public": is_public_bool}}
    )

    return {
        "success": True,
        "message": f"Project '{project['name']}' with ID '{project_id}' is now {'public' if is_public_bool else 'private'}.",
    }
