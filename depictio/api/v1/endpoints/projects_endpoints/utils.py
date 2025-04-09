from fastapi import HTTPException
from depictio_models.models.projects import ProjectBeanie


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

    # Save the project to the database
    await project.insert()
    return {
        "project": project,
        "message": "Project created successfully.",
        "success": True,
    }
