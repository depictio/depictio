import json

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo import ReturnDocument

from depictio.api.v1.db import projects_collection, workflows_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.endpoints.workflow_endpoints.utils import compare_models
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.users import User, UserBase
from depictio.models.models.workflows import Workflow

workflows_endpoint_router = APIRouter()


@workflows_endpoint_router.get("/get_all_workflows")
async def get_all_workflows(current_user: User = Depends(get_current_user)):
    """Get all workflows accessible to the current user."""
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found.")

    user_id = current_user.id

    query = {
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers._id": user_id},
            {"permissions.viewers": "*"},
            {"is_public": True},
        ]
    }

    workflows_cursor = list(workflows_collection.find(query))
    if not workflows_cursor:
        return []

    return [convert_objectid_to_str(w) for w in workflows_cursor]


@workflows_endpoint_router.get("/get/from_args")
async def get_workflow_from_args(
    name: str,
    engine: str,
    permissions: str | None = None,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Get a workflow by name and engine."""
    permissions_request = None
    if permissions:
        try:
            permissions_request = json.loads(permissions)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in permissions")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if not name or not engine:
        raise HTTPException(
            status_code=400,
            detail="Workflow name and engine are required to get a workflow.",
        )

    user_id = current_user.id

    base_query = {"name": name, "engine": engine}
    base_permissions = {
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers._id": user_id},
            {"permissions.viewers": "*"},
            {"is_public": True},
        ]
    }

    if permissions_request:
        for elem in permissions_request["$or"]:
            for k, v in elem.items():
                if k in ("permissions.owners._id", "permissions.viewers._id"):
                    permissions_request["$or"][k] = ObjectId(v)
        query = {**base_query, **permissions_request}
    else:
        query = {**base_query, **base_permissions}

    workflows = list(workflows_collection.find(query))

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

    return convert_objectid_to_str(workflows)[0]


@workflows_endpoint_router.get("/get/from_id")
async def get_workflow_from_id(
    workflow_id: str, current_user: User = Depends(get_user_or_anonymous)
):
    """Get a workflow by ID."""
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
        # Add project_id to workflow before returning
        {
            "$addFields": {
                "workflows.project_id": "$_id"  # Add parent project ID to workflow
            }
        },
        # Return only the workflow (now with project_id)
        {"$replaceRoot": {"newRoot": "$workflows"}},
    ]

    result = list(projects_collection.aggregate(pipeline))

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No workflow found for the current user with ID {workflow_id}.",
        )

    return convert_objectid_to_str(result[0])


@workflows_endpoint_router.get("/get_tag_from_id/{workflow_id}")
async def get_workflow_tag_from_id(
    workflow_id: str, current_user: User = Depends(get_user_or_anonymous)
):
    """Get a workflow tag by workflow ID."""
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

    workflow = convert_objectid_to_str(result[0])
    return workflow["workflow_tag"]


@workflows_endpoint_router.post("/create")
async def create_workflow(workflow: dict, current_user: User = Depends(get_current_user)):
    """Create a new workflow."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if not workflow:
        raise HTTPException(status_code=400, detail="Workflow is required to create it.")

    existing_workflow = workflows_collection.find_one(
        {
            "workflow_tag": workflow["workflow_tag"],
            "permissions.owners._id": current_user.id,
        }
    )

    if existing_workflow:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow with name '{workflow['workflow_tag']}' already exists. Use update option to modify it.",
        )

    new_owner = UserBase(id=current_user.id, email=current_user.email, groups=current_user.groups)  # type: ignore[unknown-argument]
    workflow = Workflow(**workflow)  # type: ignore[invalid-assignment,missing-argument]
    workflow.permissions.owners.append(new_owner)  # type: ignore[unresolved-attribute]
    workflow.id = ObjectId()  # type: ignore[unresolved-attribute]

    for data_collection in workflow.data_collections:  # type: ignore[unresolved-attribute]
        data_collection.id = ObjectId()  # type: ignore[invalid-assignment]

    res = workflows_collection.insert_one(workflow.mongo())  # type: ignore[unresolved-attribute]
    assert res.inserted_id == workflow.id  # type: ignore[unresolved-attribute]

    return convert_objectid_to_str(workflow)


@workflows_endpoint_router.put("/update")
async def update_workflow(workflow: Workflow, current_user: User = Depends(get_current_user)):
    """Update an existing workflow."""
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
            dc.id = existing_data_collections[dc.data_collection_tag]

    updated_workflow_data = workflow.mongo()
    updated_workflow_data["_id"] = existing_workflow["_id"]
    updated_workflow_data["permissions"] = existing_workflow["permissions"]

    workflows_collection.find_one_and_update(
        {"_id": existing_workflow["_id"]},
        {"$set": updated_workflow_data},
        return_document=ReturnDocument.AFTER,
    )

    return convert_objectid_to_str(updated_workflow_data)


@workflows_endpoint_router.delete("/delete/{workflow_id}")
async def delete_workflow(workflow_id: str, current_user: User = Depends(get_current_user)):
    """Delete a workflow by ID."""
    workflow_oid = ObjectId(workflow_id)
    existing_workflow = workflows_collection.find_one({"_id": workflow_oid})

    if not existing_workflow:
        raise HTTPException(
            status_code=404, detail=f"Workflow with ID '{workflow_id}' does not exist."
        )

    workflow_tag = existing_workflow["workflow_tag"]
    user_id = current_user.id  # type: ignore[possibly-unbound-attribute]

    if user_id not in [u["user_id"] for u in existing_workflow["permissions"]["owners"]]:
        raise HTTPException(
            status_code=403,
            detail=f"User with ID '{user_id}' is not authorized to delete workflow with ID '{workflow_id}'",
        )

    workflows_collection.delete_one({"_id": workflow_oid})

    return {"message": f"Workflow {workflow_tag} with ID '{workflow_id}' deleted successfully"}


@workflows_endpoint_router.post("/compare_workflow_models")
async def compare_models_endpoint(
    new_workflow: Workflow,
    existing_workflow: Workflow,
    current_user=Depends(get_current_user),
):
    """Compare two workflow models for equality."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    if not new_workflow or not existing_workflow:
        raise HTTPException(
            status_code=400,
            detail="Both new and existing workflows are required to compare them.",
        )

    result = compare_models(new_workflow, existing_workflow)  # type: ignore[invalid-argument-type]

    return {
        "exists": True,
        "match": result,
        "message": f"Workflow with name '{new_workflow.workflow_tag}' exists.",
    }
