import os
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
from typing import List

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.models.base import PyObjectId, convert_objectid_to_str
from depictio.api.v1.models.orm_models import (
    DataCollectionConfigORM,
    DataCollectionORM,
    PermissionORM,
    WorkflowConfigORM,
    WorkflowORM,
)
from depictio.api.v1.models.pydantic_models import (
    DataCollection,
    Permission,
    RootConfig,
    User,
    Workflow,
    WorkflowConfig,
)
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user


# from modules.workflow_endpoints.models import Workflow

workflows_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]
fschunks_collection = db["fs.chunks"]
fsfiles_collection = db["fs.files"]
permissions_collection = db["permissions"]
workflow_config_collection = db["workflow_config"]
data_collection_config_collection = db["data_collection_config"]
users_collection = db["users"]


@workflows_endpoint_router.post("/create_workflow")
async def create_workflow(
    workflow: Workflow, current_user: str = Depends(get_current_user)
):
    workflows_collection.drop()
    data_collections_collection.drop()
    runs_collection.drop()
    files_collection.drop()
    fschunks_collection.drop()
    fsfiles_collection.drop()
    permissions_collection.drop()
    workflow_config_collection.drop()
    data_collection_config_collection.drop()

    existing_workflow = workflows_collection.find_one(
        {
            "workflow_tag": workflow.workflow_tag,
            "permissions.owners.user_id": current_user.user_id,
        }
    )
    if existing_workflow:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow with name '{workflow.workflow_tag}' already exists.",
        )

    assert isinstance(workflow.id, ObjectId)
    res = workflows_collection.insert_one(workflow.mongo())
    assert res.inserted_id == workflow.id

    found = workflows_collection.find_one({"_id": res.inserted_id})
    return Workflow.from_mongo(found)


@workflows_endpoint_router.get("/get_workflows")
# @workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflows(current_user: str = Depends(get_current_user)):
    # Assuming the 'current_user' now holds a 'user_id' as an ObjectId after being parsed in 'get_current_user'
    user_id = current_user.user_id  # This should be the ObjectId

    # Find workflows where current_user is either an owner or a viewer
    query = {
        "$or": [
            {"permissions.owners.user_id": user_id},
            {"permissions.viewers.user_id": user_id},
        ]
    }

    # Retrieve the workflows & convert them to Workflow objects to validate the model
    workflows_cursor = [Workflow(**w) for w in list(workflows_collection.find(query))]

    workflows = convert_objectid_to_str(list(workflows_cursor))

    if not workflows:
        raise HTTPException(
            status_code=404, detail="No workflows found for the current user."
        )

    return workflows


@workflows_endpoint_router.put("/update_workflow/{id}")
async def update_workflow(
    id: str, updated_workflow: Workflow, current_user: str = Depends(get_current_user)
):
    # Find the workflow by ID
    existing_workflow = workflows_collection.find_one({"id": id})
    workflow_tag = existing_workflow["workflow_tag"]

    if not existing_workflow:
        raise HTTPException(
            status_code=404, detail=f"Workflow with ID '{id}' does not exist."
        )

    # Ensure that the current user is authorized to update the workflow
    user_id = current_user.user_id
    if user_id not in existing_workflow["permissions"]["owners"]:
        raise HTTPException(
            status_code=403,
            detail=f"User with ID '{user_id}' is not authorized to update workflow with ID '{id}'",
        )

    # Update the workflow
    updated_data = updated_workflow.dict()
    workflows_collection.update_one({"id": id}, {"$set": updated_data})

    return {"message": f"Workflow {workflow_tag} with ID '{id}' updated successfully"}


@workflows_endpoint_router.delete("/delete_workflow/{id}")
async def delete_workflow(id: str, current_user: str = Depends(get_current_user)):
    # Find the workflow by ID
    id = ObjectId(id)
    assert isinstance(id, ObjectId)
    existing_workflow = workflows_collection.find_one({"_id": id})

    print(existing_workflow)

    if not existing_workflow:
        raise HTTPException(
            status_code=404, detail=f"Workflow with ID '{id}' does not exist."
        )

    workflow_tag = existing_workflow["workflow_tag"]

    # Ensure that the current user is authorized to update the workflow
    user_id = current_user.user_id
    print(
        user_id,
        type(user_id),
        existing_workflow["permissions"]["owners"],
        [u["user_id"] for u in existing_workflow["permissions"]["owners"]],
    )
    if user_id not in [
        u["user_id"] for u in existing_workflow["permissions"]["owners"]
    ]:
        raise HTTPException(
            status_code=403,
            detail=f"User with ID '{user_id}' is not authorized to delete workflow with ID '{id}'",
        )
    # Delete the workflow
    workflows_collection.delete_one({"_id": id})
    assert workflows_collection.find_one({"_id": id}) is None

    return {"message": f"Workflow {workflow_tag} with ID '{id}' deleted successfully"}
