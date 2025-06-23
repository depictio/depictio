import hashlib
import json

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo import ReturnDocument

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import projects_collection, users_collection, workflows_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.endpoints.workflow_endpoints.utils import compare_models
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.users import UserBase
from depictio.models.models.workflows import Workflow

# Define the router
workflows_endpoint_router = APIRouter()


# FIXME: refactor that endpoint to be compliant with new architecture


@workflows_endpoint_router.get("/get_all_workflows")
async def get_all_workflows(current_user: str = Depends(get_current_user)):
    logger.debug(f"current_user: {current_user}")

    if not current_user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Assuming the 'current_user' now holds a 'user_id' as an ObjectId after being parsed in 'get_current_user'
    user_id = current_user.id  # This should be the ObjectId

    # DEBUG - Find all workflows regardless of permissions
    workflows_cursor = list(workflows_collection.find())
    logger.debug(f"workflows_cursor - ALL: {workflows_cursor}")

    # Find workflows where current_user is either an owner or a viewer
    query = {
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers._id": user_id},
            {"permissions.viewers": "*"},  # This makes workflows with "*" publicly accessible
            {"is_public": True},  # Allow access to public workflows
        ]
    }

    # Retrieve the workflows & convert them to Workflow objects to validate the model
    workflows_cursor = list(workflows_collection.find(query))
    logger.debug(f"workflows_cursor: {workflows_cursor}")
    if not workflows_cursor or len(workflows_cursor) == 0:
        return []
    workflows = [convert_objectid_to_str(w) for w in workflows_cursor]
    logger.debug(f"workflows: {workflows}")
    # workflows = [Workflow(**convert_objectid_to_str(w)) for w in workflows_cursor]
    return workflows


@workflows_endpoint_router.get("/get/from_args")
async def get_workflow_from_args(
    name: str,
    engine: str,
    permissions: str | None = None,
    current_user: str = Depends(get_user_or_anonymous),
):
    logger.debug(f"workflow_name: {name}")
    logger.debug(f"workflow_engine: {engine}")
    logger.debug(f"permissions: {permissions}")

    # Parse the permissions if provided
    if permissions:
        try:
            logger.debug(f"permissions: {permissions}")
            permissions_request = json.loads(permissions)
            logger.debug(f"permissions_request: {permissions_request}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in permissions")
    else:
        permissions_request = None

    logger.debug(
        f"Name: {name}, Engine: {engine}, Permissions: {permissions_request}, User: {current_user}"
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if not name or not engine:
        raise HTTPException(
            status_code=400,
            detail="Workflow name and engine are required to get a workflow.",
        )

    # current_user = api_call_fetch_user_from_token(token)

    logger.debug(f"current_user: {current_user}")

    # Assuming the 'current_user' now holds a 'user_id' as an ObjectId after being parsed in 'get_current_user'
    user_id = current_user.id

    base_query = {
        "name": name,
        "engine": engine,
    }

    base_permissions = {
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers._id": user_id},
            {"permissions.viewers": "*"},  # This makes workflows with "*" publicly accessible
            {"is_public": True},  # Allow access to public workflows
        ]
    }

    if permissions_request:
        logger.debug(f"permissions_request: {permissions_request}")
        logger.debug(f"type(permissions_request): {type(permissions_request)}")
        logger.debug(f"permissions_request['$or']: {permissions_request['$or']}")

        # turn the user_id into an ObjectId
        for elem in permissions_request["$or"]:
            for k, v in elem.items():
                if k == "permissions.owners._id" or k == "permissions.viewers._id":
                    permissions_request["$or"][k] = ObjectId(v)

        query = {
            **base_query,
            **permissions_request,
        }
    else:
        query = {
            **base_query,
            **base_permissions,
        }

    # Find workflows where current_user is either an owner or a viewer
    # query = {
    #     "name": name,
    #     "engine": engine,
    # }

    # Retrieve the workflows & convert them to Workflow objects to validate the model
    workflows = list(workflows_collection.find(query))
    logger.debug(f"workflows: {workflows}")

    if not workflows:
        raise HTTPException(
            status_code=404,
            detail=f"No workflow found for the current user with name {name} and engine {engine}.",
        )

    if len(workflows) > 1:
        raise HTTPException(
            status_code=500,
            detail=f"Multiple workflows found for the current user with name {name} and engine {engine}.",
        )

    workflows = convert_objectid_to_str(workflows)

    return workflows[0]


@workflows_endpoint_router.get("/get/from_id")
# @workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflow_from_id(
    workflow_id: str, current_user: str = Depends(get_user_or_anonymous)
):
    logger.debug(f"workflow_id: {workflow_id}")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    try:
        workflow_oid = ObjectId(workflow_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Use MongoDB aggregation to directly retrieve the specific workflow
    pipeline = [
        # Match projects containing this workflow and with appropriate permissions
        {
            "$match": {
                "workflows._id": workflow_oid,
                "$or": [
                    {"permissions.owners._id": current_user.id},
                    {"permissions.viewers._id": current_user.id},
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        # Unwind the workflows array
        {"$unwind": "$workflows"},
        # Match the specific workflow ID
        {"$match": {"workflows._id": workflow_oid}},
        # Return only the workflow
        {"$replaceRoot": {"newRoot": "$workflows"}},
    ]

    result = list(projects_collection.aggregate(pipeline))

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No workflow found for the current user with ID {workflow_id}.",
        )

    workflow = result[0]
    workflow = convert_objectid_to_str(workflow)

    return workflow


@workflows_endpoint_router.get("/get_tag_from_id/{workflow_id}")
async def get_workflow_tag_from_id(
    workflow_id: str, current_user: str = Depends(get_user_or_anonymous)
):
    logger.debug(f"workflow_id: {workflow_id}")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    try:
        workflow_oid = ObjectId(workflow_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Use MongoDB aggregation to directly retrieve the specific workflow
    pipeline = [
        # Match projects containing this workflow and with appropriate permissions
        {
            "$match": {
                "workflows._id": workflow_oid,
                "$or": [
                    {"permissions.owners._id": current_user.id},
                    {"permissions.viewers._id": current_user.id},
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        # Unwind the workflows array
        {"$unwind": "$workflows"},
        # Match the specific workflow ID
        {"$match": {"workflows._id": workflow_oid}},
        # Return only the workflow
        {"$replaceRoot": {"newRoot": "$workflows"}},
    ]

    result = list(projects_collection.aggregate(pipeline))

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No workflow found for the current user with ID {workflow_id}.",
        )

    workflow = result[0]
    workflow = convert_objectid_to_str(workflow)
    wf_tag = workflow["workflow_tag"]

    return wf_tag


@workflows_endpoint_router.post("/create")
async def create_workflow(workflow: dict, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    logger.debug(f"current_user: {current_user}")

    current_access_token = current_user.current_access_token
    # hash the token
    token_hash = hashlib.sha256(current_access_token.encode()).hexdigest()
    logger.debug(f"Token hash: {token_hash}")

    # fetch user DB object from the token
    response_user = users_collection.find_one({"_id": ObjectId(current_user.id)})
    logger.debug(f"response_user: {response_user}")

    if not workflow:
        raise HTTPException(status_code=400, detail="Workflow is required to create it.")

    existing_workflow = workflows_collection.find_one(
        {
            "workflow_tag": workflow["workflow_tag"],
            # "workflow_tag": workflow.workflow_tag,
            "permissions.owners._id": current_user.id,
        }
    )
    logger.debug(f"existing_workflow: {existing_workflow}")

    if existing_workflow:
        raise HTTPException(
            status_code=400,
            # detail=f"Workflow with name '{workflow.workflow_tag}' already exists. Use update option to modify it.",
            detail=f"Workflow with name '{workflow['workflow_tag']}' already exists. Use update option to modify it.",
        )

    # Correctly update the owners list in the permissions attribute
    new_owner = UserBase(id=current_user.id, email=current_user.email, groups=current_user.groups)
    logger.debug(f"new_owner: {new_owner}")
    # new_owner = convert_objectid_to_str(new_owner.mongo())
    # logger.debug(f"new_owner: {new_owner}")

    # Replace or extend the owners list as needed
    # workflow["permissions"]["owners"].append(new_owner)  # Appending the new owner

    logger.debug(f"workflow: {workflow}")

    # Convert the workflow to a Workflow object
    workflow = Workflow(**workflow)

    logger.debug(f"workflow: {workflow}")

    # Add the new owner to the permissions
    workflow.permissions.owners.append(new_owner)

    logger.debug(f"workflow: {workflow}")

    # Assign PyObjectId to workflow ID and data collection IDs
    workflow.id = ObjectId()

    logger.debug(f"workflow: {workflow}")

    for data_collection in workflow.data_collections:
        data_collection.id = ObjectId()
    assert isinstance(workflow.id, ObjectId)

    logger.debug(f"Workflow: {workflow}")

    res = workflows_collection.insert_one(workflow.mongo())
    assert res.inserted_id == workflow.id

    logger.debug(f"res: {res}")

    # check if the workflow was created in the DB
    res = workflows_collection.find_one({"_id": workflow.id})
    logger.debug(f"res query : {res}")

    # check if the workflow was created in the DB using the workflow_tag
    res = workflows_collection.find_one({"workflow_tag": workflow.workflow_tag})
    logger.debug(f"res query tag : {res}")

    return_dict = {
        str(workflow.id): [str(data_collection.id) for data_collection in workflow.data_collections]
    }

    return_dict = convert_objectid_to_str(workflow)
    logger.debug(f"return_dict: {return_dict}")
    return return_dict


@workflows_endpoint_router.put("/update")
async def update_workflow(workflow: Workflow, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Token is required to update a workflow.")

    if not workflow:
        raise HTTPException(status_code=400, detail="Workflow is required to update it.")

    existing_workflow = workflows_collection.find_one(
        {
            "workflow_tag": workflow.workflow_tag,
            "permissions.owners._id": current_user.id,
        }
    )

    logger.debug(f"existing_workflow: {existing_workflow}")

    if not existing_workflow:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow with name '{workflow.workflow_tag}' does not exist. Use create option to create it.",
        )
    existing_data_collections = {
        dc["data_collection_tag"]: dc["_id"] for dc in existing_workflow.get("data_collections", [])
    }
    for dc in workflow.data_collections:
        if dc.data_collection_tag in existing_data_collections:
            # If the data collection exists, preserve its ID
            dc.id = existing_data_collections[dc.data_collection_tag]

    # Update the workflow with potentially new or modified data collections
    updated_workflow_data = workflow.mongo()
    updated_workflow_data["_id"] = existing_workflow["_id"]  # Ensure the workflow ID is preserved
    updated_workflow_data["permissions"] = existing_workflow[
        "permissions"
    ]  # Ensure the permissions are preserved
    res = workflows_collection.find_one_and_update(
        {"_id": existing_workflow["_id"]},
        {"$set": updated_workflow_data},
        return_document=ReturnDocument.AFTER,
    )

    logger.debug(f"res: {res}")

    # Verify the update was successful
    # if not res:
    #     raise HTTPException(status_code=500, detail="Failed to update the workflow.")

    # Return a mapping of workflow ID to data collection IDs
    # updated_data_collection_ids = [str(dc.id) for dc in workflow.data_collections]
    return_data = convert_objectid_to_str(updated_workflow_data)

    return return_data

    # return {str(existing_workflow["_id"]): updated_data_collection_ids}


@workflows_endpoint_router.delete("/delete/{workflow_id}")
async def delete_workflow(workflow_id: str, current_user: str = Depends(get_current_user)):
    # Find the workflow by ID
    workflow_oid = ObjectId(workflow_id)
    assert isinstance(workflow_oid, ObjectId)
    existing_workflow = workflows_collection.find_one({"_id": workflow_oid})

    logger.debug(existing_workflow)

    if not existing_workflow:
        raise HTTPException(
            status_code=404, detail=f"Workflow with ID '{workflow_id}' does not exist."
        )

    workflow_tag = existing_workflow["workflow_tag"]

    # data_collections = existing_workflow["data_collections"]

    # Ensure that the current user is authorized to update the workflow
    user_id = current_user.id
    logger.debug(
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

    # for data_collection in data_collections:
    #     delete_files_message = await delete_files(workflow_id, data_collection["data_collection_id"], current_user)

    #     delete_datatable_message = await delete_deltatable(workflow_id, data_collection["data_collection_id"], current_user)

    return {
        "message": f"Workflow {workflow_tag} with ID '{id}' deleted successfully, as well as all files"
    }


@workflows_endpoint_router.post("/compare_workflow_models")
async def compare_models_endpoint(
    new_workflow: Workflow,
    existing_workflow: Workflow,
    current_user=Depends(get_current_user),
):
    logger.debug(f"new_workflow: {new_workflow}")
    logger.debug(f"existing_workflow: {existing_workflow}")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    if not new_workflow or not existing_workflow:
        raise HTTPException(
            status_code=400,
            detail="Both new and existing workflows are required to compare them.",
        )

    result = compare_models(new_workflow, existing_workflow)

    return {
        "exists": True,
        "match": result,
        "message": f"Workflow with name '{new_workflow.workflow_tag}' exists.",
    }
