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
from depictio_models.utils import convert_model_to_dict

# Define the router
projects_endpoint_router = APIRouter()


# {
#   "_id": {
#     "$oid": "67a25c82fea6466823de362b"
#   },
#   "description": null,
#   "flexible_metadata": null,
#   "name": "Strand-Seq data analysis",
#     "permissions": {
#     "owners": [
#       {
#         "_id": "67658ba033c8b59ad489d7c7",
#         "email": "admin@embl.de",
#         "is_admin": true,
#         "groups": [
#           {
#             "id": "678e275019fcb5bbbf26a0d2",
#             "description": null,
#             "flexible_metadata": null,
#             "hash": null,
#             "name": "admin"
#           },
#           {
#             "id": "67dc70fe7cb9e9eb04955423",
#             "description": null,
#             "flexible_metadata": null,
#             "hash": null,
#             "name": "TEST"
#           },
#           {
#             "id": "67e18bd14fa5941c4ded00a8",
#             "description": null,
#             "flexible_metadata": null,
#             "hash": null,
#             "name": "TOTO"
#           }
#         ]
#       }
#     ],
#     "editors": [
#       {
#         "_id": "67d9ae8ae77e0f469332abbf",
#         "email": "t@t.com",
#         "is_admin": false,
#         "groups": [
#           {
#             "id": "67d155ae9870d172f406087a",
#             "description": null,
#             "flexible_metadata": null,
#             "hash": null,
#             "name": "users"
#           },
#           {
#             "id": "67dc70fe7cb9e9eb04955423",
#             "description": null,
#             "flexible_metadata": null,
#             "hash": null,
#             "name": "TEST"
#           }
#         ]
#       }
#     ],
#     "viewers": []
#   },
#   "is_public": false,
#   "hash": "36011a3f7ff5eeba9044f9506bdf7037",
#   "registration_time": "2025-02-25 10:22:05"
# }


@projects_endpoint_router.get("/get/all")
async def get_all_projects(current_user: str = Depends(get_current_user)) -> List:
    logger.info("Getting all projects")
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Find projects where current_user is either an owner or a viewer
    current_user_id = ObjectId(current_user.id)
    logger.info(f"Current user ID: {current_user_id}")
    query = {
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }
    logger.info(f"Query: {query}")

    if current_user.is_admin:
        query = {}
    logger.info(f"Query: {query}")

    projects = list(projects_collection.find(query))
    logger.info(f"Projects: {projects}")
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

    current_user_id = ObjectId(current_user.id)
    query = {
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }
    logger.info(f"Query: {query}")

    if current_user.is_admin:
        query = {"_id": ObjectId(project_id)}

    logger.info(f"Query: {query}")

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


# endpoint and PermissionRequest to add or update permission of a user to a project

from pydantic import BaseModel, ConfigDict, field_validator
from depictio_models.models.users import Permission


class ProjectPermissionRequest(BaseModel):
    project_id: str
    permissions: dict
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # class Config:
    #     arbitrary_types_allowed = True


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
    logger.info(
        f"Owners ids : {[owner['_id'] for owner in project['permissions']['owners']]}"
    )
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
