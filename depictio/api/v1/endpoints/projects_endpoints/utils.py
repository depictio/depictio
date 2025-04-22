from fastapi import HTTPException
from depictio.models.models.projects import ProjectBeanie
from depictio.api.v1.configs.custom_logging import logger

async def helper_create_project_beanie(project: ProjectBeanie) -> ProjectBeanie:
    """Helper function to create a project in the database.

    Args:
        project (Project): Project object containing project information

    Raises:
        HTTPException: If the project already exists in the database

    Returns:
        Project: The created project object
    """

    # Check if the project already exists
    existing_project = await ProjectBeanie.find_one({"name": project.name})
    if existing_project:
        raise HTTPException(
            status_code=400,
            detail=f"Project with name '{project.name}' already exists.",
        )

    # Import the projects_collection to use PyMongo's insert_one method
    from depictio.api.v1.db import projects_collection
    
    # Use project.mongo() to ensure all nested 'id' fields are converted to '_id'
    logger.debug(f"Project before conversion: {project}")
    mongo_project = project.mongo()
    logger.debug(f"Mongo project: {mongo_project}") 
    
    # Ensure top-level _id is an ObjectId
    if "_id" in mongo_project and isinstance(mongo_project["_id"], str):
        from bson import ObjectId
        if ObjectId.is_valid(mongo_project["_id"]):
            mongo_project["_id"] = ObjectId(mongo_project["_id"])
    
    # Save the project to the database using PyMongo's insert_one
    result = projects_collection.insert_one(mongo_project)
    
    # Update the project's id with the inserted _id
    project.id = result.inserted_id
    return {
        "project": project,
        "message": "Project created successfully.",
        "success": True,
    }
