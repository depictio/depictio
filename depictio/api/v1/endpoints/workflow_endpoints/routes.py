import collections
import os
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
from typing import List

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.endpoints.datacollections_endpoints.routes import (
    delete_datacollection,
)
from depictio.api.v1.endpoints.deltatables_endpoints.routes import delete_deltatable
from depictio.api.v1.endpoints.files_endpoints.routes import delete_files
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


@workflows_endpoint_router.get("/get")
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


@workflows_endpoint_router.post("/create")
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

    # found = workflows_collection.find_one({"_id": res.inserted_id})
    return str(res.inserted_id)


# @workflows_endpoint_router.put("/update_workflow/{workflow_id}")
# async def update_workflow(
#     workflow_id: str, updated_workflow: Workflow, current_user: str = Depends(get_current_user)
# ):
#     # Find the workflow by ID
#     existing_workflow = workflows_collection.find_one({"id": workflow_id})
#     workflow_tag = existing_workflow["workflow_tag"]

#     if not existing_workflow:
#         raise HTTPException(
#             status_code=404, detail=f"Workflow with ID '{workflow_id}' does not exist."
#         )

#     # Ensure that the current user is authorized to update the workflow
#     user_id = current_user.user_id
#     if user_id not in existing_workflow["permissions"]["owners"]:
#         raise HTTPException(
#             status_code=403,
#             detail=f"User with ID '{user_id}' is not authorized to update workflow with ID '{id}'",
#         )

#     # Update the workflow
#     updated_data = updated_workflow.dict()
#     workflows_collection.update_one({"id": id}, {"$set": updated_data})

#     return {"message": f"Workflow {workflow_tag} with ID '{id}' updated successfully"}


@workflows_endpoint_router.delete("/delete/{workflow_id}")
async def delete_workflow(
    workflow_id: str, current_user: str = Depends(get_current_user)
):
    # Find the workflow by ID
    workflow_oid = ObjectId(workflow_id)
    assert isinstance(workflow_oid, ObjectId)
    existing_workflow = workflows_collection.find_one({"_id": workflow_oid})

    print(existing_workflow)

    if not existing_workflow:
        raise HTTPException(
            status_code=404, detail=f"Workflow with ID '{workflow_id}' does not exist."
        )

    workflow_tag = existing_workflow["workflow_tag"]

    data_collections = existing_workflow["data_collections"]

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
            detail=f"User with ID '{user_id}' is not authorized to delete workflow with ID '{workflow_id}'",
        )
    # Delete the workflow
    workflows_collection.delete_one({"_id": workflow_oid})
    assert workflows_collection.find_one({"_id": workflow_oid}) is None

    for data_collection in data_collections:
        delete_files_message = await delete_files(
            workflow_id, data_collection["data_collection_id"], current_user
        )

        delete_datatable_message = await delete_deltatable(
            workflow_id, data_collection["data_collection_id"], current_user
        )

    return {
        "message": f"Workflow {workflow_tag} with ID '{id}' deleted successfully, as well as all files"
    }

@workflows_endpoint_router.get("/get_join_tables/{workflow_id}")
async def get_join_tables(workflow_id: str, current_user: str = Depends(get_current_user)):
    # Find the workflow by ID
    workflow_oid = ObjectId(workflow_id)
    assert isinstance(workflow_oid, ObjectId)
    existing_workflow = workflows_collection.find_one({"_id": workflow_oid})

    if not existing_workflow:
        raise HTTPException(
            status_code=404, detail=f"Workflow with ID '{workflow_id}' does not exist."
        )

    data_collections = existing_workflow["data_collections"]



    # Initialize a map to track join details
    join_details_map = collections.defaultdict(list)
    for data_collection in data_collections:
        if "join" in data_collection["config"]:
            dc_id = str(data_collection["_id"])
            join_details_map[dc_id].append(data_collection["config"]["join"])

            for sub_dc_id in data_collection["config"]["join"]["with_dc"]:
                tmp_dict = data_collection["config"]["join"]
                tmp_dict["with_dc"] = [e for e in tmp_dict["with_dc"] if e != dc_id and e != sub_dc_id]
                tmp_dict["with_dc"].append(dc_id)
                join_details_map[sub_dc_id].append(tmp_dict)


    return join_details_map