from typing import List
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter

# depictio imports
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.db import projects_collection, dashboards_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

## depictio-models imports
from depictio_models.models.projects import Project
from depictio_models.models.base import convert_objectid_to_str

# Define the router
projects_endpoint_router = APIRouter()


@projects_endpoint_router.get("/get/all")
async def get_all_projects(current_user: str = Depends(get_current_user)) -> List:
    logger.info("Getting all projects")
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find projects where current_user is either an owner or a viewer
    query = {
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {
                "permissions.viewers": "*"
            },  # This makes projects with "*" publicly accessible
        ],
    }

    if current_user.is_admin:
        query = {}

    projects = projects_collection.find(query)
    if projects:
        projects = [convert_objectid_to_str(project) for project in projects]
        return projects
    else:
        return []


@projects_endpoint_router.get("/get/from_id/{project_id}")
async def get_project_from_id(
    project_id: str, current_user: str = Depends(get_current_user)
):
    logger.info(f"Getting project with ID: {project_id}")
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find projects where current_user is either an owner or a viewer
    query = {
        "_id": ObjectId(project_id),
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {
                "permissions.viewers": "*"
            },  # This makes projects with "*" publicly accessible
        ],
    }

    if current_user.is_admin:
        query = {"_id": ObjectId(project_id)}

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    project = convert_objectid_to_str(project)

    return project


@projects_endpoint_router.get("/get/from_dashboard_id/{dashboard_id}")
async def get_project_from_dashboard_id(
    dashboard_id: str, current_user: str = Depends(get_current_user)
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
            {
                "permissions.viewers": "*"
            },  # This makes projects with "*" publicly accessible
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


@projects_endpoint_router.get("/get/from_name/{project_name}")
async def get_project_from_name(
    project_name: str, current_user: str = Depends(get_current_user)
):
    logger.info(f"Getting project with ID: {project_name}")
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find projects where current_user is either an owner or a viewer
    query = {
        "name": project_name,
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {
                "permissions.viewers": "*"
            },  # This makes projects with "*" publicly accessible
        ],
    }

    if current_user.is_admin:
        query = {"name": project_name}

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    project = convert_objectid_to_str(Project.from_mongo(project).model_dump())

    return project


@projects_endpoint_router.post("/create")
async def create_project(project: dict, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Convert project to Project object
    project = Project.from_mongo(project)

    # Ensure the current_user is an owner
    if (
        current_user.id not in [owner.id for owner in project.permissions.owners]
        or not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to create this project.",
        )

    try:
        existing_project = await get_project_from_name(project.name, current_user)
        if existing_project:
            raise HTTPException(status_code=409, detail="Project already exists.")
    except HTTPException as e:
        if e.status_code != 404:  # Re-raise if error is not "not found"
            raise e

    logger.info(f"Creating project: {project}")
    logger.info(f"Creating mongo project: {project.mongo()}")

    # Save the project to the database
    projects_collection.insert_one(project.mongo())

    return {
        "success": True,
        "message": f"Project '{project.name}' with ID '{project.id}' created.",
    }


@projects_endpoint_router.put("/update")
async def update_project(project: dict, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Convert project to Project object
    project = Project.from_mongo(project)
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
async def delete_project(
    project_id: str, current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

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
