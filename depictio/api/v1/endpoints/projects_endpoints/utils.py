from bson import ObjectId
from fastapi import APIRouter, HTTPException

from depictio.api.v1.configs.custom_logging import logger
from depictio.api.v1.db import projects_collection
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.projects import Project
from depictio.models.models.users import User

# Define the router
projects_endpoint_router = APIRouter()


# Core functions
def _async_get_all_projects(current_user: User, projects_collection) -> list[Project]:
    """Core function to get all projects for a user."""
    current_user_id = ObjectId(current_user.id)

    query = {
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }

    if current_user.is_admin:
        query = {}

    projects = list(projects_collection.find(query))
    if projects:
        projects = [Project.from_mongo(project) for project in projects]
        return projects
    else:
        return []


def _async_get_project_from_id(
    project_id: PyObjectId, current_user: User, projects_collection
) -> dict:
    """Core function to get a project by ID."""
    current_user_id = ObjectId(current_user.id)
    query = {
        "_id": ObjectId(project_id),
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }

    if current_user.is_admin:
        query = {"_id": ObjectId(project_id)}

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    project = convert_objectid_to_str(project)
    return project


def _async_get_project_from_name(
    project_name: str, current_user: User, projects_collection
) -> dict:
    """Core function to get a project by name."""
    # Find projects where current_user is either an owner or a viewer
    query = {
        "name": project_name,
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {"permissions.viewers": "*"},  # This makes projects with "*" publicly accessible
        ],
    }

    if current_user.is_admin:
        query = {"name": project_name}

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    project = convert_objectid_to_str(Project.from_mongo(project).model_dump())
    return project


# @validate_call(validate_return=True)
async def _helper_create_project_beanie(project: Project) -> dict:
    """Helper function to create a project in the database.

    Args:
        project (ProjectBeanie): Project object containing project information

    Raises:
        HTTPException: If the project already exists in the database

    Returns:
        dict: Project creation result with project details
    """

    # Check if the project already exists
    existing_project = projects_collection.find_one({"name": project.name})
    logger.debug(f"Existing project: {existing_project}")
    if existing_project:
        raise HTTPException(
            status_code=400,
            detail=f"Project with name '{project.name}' already exists.",
        )

    # Use project.mongo() to ensure all nested 'id' fields are converted to '_id'
    logger.debug(f"Project before conversion: {project}")
    mongo_project = project.mongo()
    logger.debug(f"Mongo project: {mongo_project}")

    # Save the project to the database using PyMongo's insert_one
    result = projects_collection.insert_one(mongo_project)

    # Update the project's id with the inserted _id
    project.id = result.inserted_id

    return {
        "project": project,
        "message": "Project created successfully.",
        "success": True,
    }
