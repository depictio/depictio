from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter

# depictio imports
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

## depictio-models imports
from depictio_models.models.projects import Project

# Define the router
projects_endpoint_router = APIRouter()


@projects_endpoint_router.get("/get/from_id")
async def get_project_from_id(project_id: str, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find projects where current_user is either an owner or a viewer
    query = {
        "_id": ObjectId(project_id),
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {"permissions.viewers": "*"},  # This makes projects with "*" publicly accessible
        ],
    }

    if current_user.is_admin:
        query = {"_id": ObjectId(project_id)}

    project = settings.projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    project = Project.from_mongo(project)

    return project


@projects_endpoint_router.post("/create")
async def create_project(project: dict, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Ensure the current_user is an owner
    if current_user.id not in [owner.id for owner in project.permissions.owners]:
        raise HTTPException(status_code=403, detail="User does not have permission to create this project.")

    # Ensure the project does not already exist using above function
    existing_project = await get_project_from_id(project_id=project.id, current_user=current_user)
    if existing_project:
        raise HTTPException(status_code=409, detail="Project already exists.")

    # Save the project to the database
    settings.projects_collection.insert_one(project.mongo())

    return {"success": True, "message": f"Project '{project.name}' with ID '{project.id}' created."}
