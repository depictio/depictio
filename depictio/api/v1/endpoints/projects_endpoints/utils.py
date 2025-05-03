from fastapi import HTTPException
from pydantic import validate_call
from depictio.models.models.projects import Project
from depictio.api.v1.configs.custom_logging import format_pydantic, logger
from depictio.api.v1.db import projects_collection
from bson import ObjectId


# @validate_call(validate_return=True)
async def helper_create_project_beanie(project: Project) -> dict:
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
