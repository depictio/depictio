from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
from pymongo import ReturnDocument

from depictio.api.v1.configs.config import logger
from depictio.api.v1.db import workflows_collection
from depictio.api.v1.endpoints.deltatables_endpoints.routes import delete_deltatable
from depictio.api.v1.endpoints.files_endpoints.routes import delete_files
from depictio.api.v1.models.base import convert_objectid_to_str
from depictio.api.v1.models.top_structure import (
    Workflow,
)
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user

# Define the router
workflows_endpoint_router = APIRouter()



@workflows_endpoint_router.get("/get_all_workflows")
# @workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_all_workflows(current_user: str = Depends(get_current_user)):
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
    workflows_cursor = list(workflows_collection.find(query))
    logger.info(f"workflows_cursor: {workflows_cursor}")
    if not workflows_cursor or len(workflows_cursor) == 0:
        return []
    workflows = [Workflow(**convert_objectid_to_str(w)) for w in workflows_cursor]
    return workflows



@workflows_endpoint_router.get("/get")
# @workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflow(workflow_id: str, current_user: str = Depends(get_current_user)):
    logger.info(f"workflow_id: {workflow_id}")
    # Assuming the 'current_user' now holds a 'user_id' as an ObjectId after being parsed in 'get_current_user'
    user_id = current_user.user_id  # This should be the ObjectId

    # Find workflows where current_user is either an owner or a viewer
    query = {
        "_id": ObjectId(workflow_id),
        "$or": [
            {"permissions.owners.user_id": user_id},
            {"permissions.viewers.user_id": user_id},
        ],
    }
    logger.info(f"query: {query}")

    # Retrieve the workflows & convert them to Workflow objects to validate the model
    workflows_cursor = [Workflow(**convert_objectid_to_str(w)) for w in list(workflows_collection.find(query))]
    workflows = convert_objectid_to_str(list(workflows_cursor))
    logger.info(f"workflows: {workflows}")

    if not workflows:
        raise HTTPException(status_code=404, detail=f"No workflow found for the current user with ID {workflow_id}.")

    return workflows[0]


@workflows_endpoint_router.post("/create")
async def create_workflow(workflow: Workflow, current_user: str = Depends(get_current_user)):
    existing_workflow = workflows_collection.find_one(
        {
            "workflow_tag": workflow.workflow_tag,
            "permissions.owners.user_id": current_user.user_id,
        }
    )

    if existing_workflow:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow with name '{workflow.workflow_tag}' already exists. Use update option to modify it.",
        )

    # Create new workflow
    print(workflow)

    # Assign PyObjectId to workflow ID and data collection IDs
    workflow.id = ObjectId()
    for data_collection in workflow.data_collections:
        data_collection.id = ObjectId()
    print("\n\n\n")
    print("create_workflow")
    print(workflow)
    assert isinstance(workflow.id, ObjectId)
    res = workflows_collection.insert_one(workflow.mongo())
    assert res.inserted_id == workflow.id
    return_dict = {str(workflow.id): [str(data_collection.id) for data_collection in workflow.data_collections]}

    return_dict = convert_objectid_to_str(workflow)
    return return_dict


@workflows_endpoint_router.put("/update")
async def update_workflow(workflow: Workflow, current_user: str = Depends(get_current_user)):
    existing_workflow = workflows_collection.find_one(
        {
            "workflow_tag": workflow.workflow_tag,
            "permissions.owners.user_id": current_user.user_id,
        }
    )

    if not existing_workflow:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow with name '{workflow.workflow_tag}' does not exist. Use create option to create it.",
        )
    # Preserve existing data collection IDs
    print("existing_workflow")
    print(existing_workflow)
    existing_data_collections = {dc["data_collection_tag"]: dc["_id"] for dc in existing_workflow.get("data_collections", [])}
    for dc in workflow.data_collections:
        if dc.data_collection_tag in existing_data_collections:
            # If the data collection exists, preserve its ID
            dc.id = existing_data_collections[dc.data_collection_tag]

    # Update the workflow with potentially new or modified data collections
    updated_workflow_data = workflow.mongo()
    updated_workflow_data["_id"] = existing_workflow["_id"]  # Ensure the workflow ID is preserved

    res = workflows_collection.find_one_and_update({"_id": existing_workflow["_id"]}, {"$set": updated_workflow_data}, return_document=ReturnDocument.AFTER)

    # Verify the update was successful
    # if not res:
    #     raise HTTPException(status_code=500, detail="Failed to update the workflow.")

    # Return a mapping of workflow ID to data collection IDs
    updated_data_collection_ids = [str(dc.id) for dc in workflow.data_collections]
    print("upddate")
    print(updated_workflow_data)
    return_data = convert_objectid_to_str(updated_workflow_data)

    return return_data

    # return {str(existing_workflow["_id"]): updated_data_collection_ids}


@workflows_endpoint_router.delete("/delete/{workflow_id}")
async def delete_workflow(workflow_id: str, current_user: str = Depends(get_current_user)):
    # Find the workflow by ID
    workflow_oid = ObjectId(workflow_id)
    assert isinstance(workflow_oid, ObjectId)
    existing_workflow = workflows_collection.find_one({"_id": workflow_oid})

    print(existing_workflow)

    if not existing_workflow:
        raise HTTPException(status_code=404, detail=f"Workflow with ID '{workflow_id}' does not exist.")

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
    if user_id not in [u["user_id"] for u in existing_workflow["permissions"]["owners"]]:
        raise HTTPException(
            status_code=403,
            detail=f"User with ID '{user_id}' is not authorized to delete workflow with ID '{workflow_id}'",
        )
    # Delete the workflow
    workflows_collection.delete_one({"_id": workflow_oid})
    assert workflows_collection.find_one({"_id": workflow_oid}) is None

    for data_collection in data_collections:
        delete_files_message = await delete_files(workflow_id, data_collection["data_collection_id"], current_user)

        delete_datatable_message = await delete_deltatable(workflow_id, data_collection["data_collection_id"], current_user)

    return {"message": f"Workflow {workflow_tag} with ID '{id}' deleted successfully, as well as all files"}
