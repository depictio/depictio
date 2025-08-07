import collections

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import db, projects_collection
from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _delete_data_collection_by_id,
    _get_data_collection_specs,
    _update_data_collection_name,
    generate_join_dict,
    normalize_join_details,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.endpoints.workflow_endpoints.routes import (
    get_all_workflows,
    get_workflow_from_id,
)
from depictio.dash.utils import return_dc_tag_from_id, return_mongoid
from depictio.models.models.base import PyObjectId, convert_objectid_to_str

datacollections_endpoint_router = APIRouter()


data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db["users"]


@datacollections_endpoint_router.get("/specs/{data_collection_id}")
async def specs(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
):
    return await _get_data_collection_specs(data_collection_id, current_user)


@datacollections_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_datacollection(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.id,  # type: ignore[possibly-unbound-attribute]
        workflow_id,
        data_collection_id,
    )

    # delete the data collection from the workflow
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {"$pull": {"data_collections": data_collection}},
    )
    # delete_files_message = await delete_files(workflow_id, data_collection_id, current_user)
    return {"message": "Data collection deleted successfully."}


@datacollections_endpoint_router.get("/get_join_tables/{workflow_id}/{data_collection_id}")
async def get_join_tables(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_user_or_anonymous),
):
    """
    Retrieve join details for the data collections in a workflow.
    """

    # Retrieve all workflows
    workflows = await get_all_workflows(current_user=current_user)
    workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]

    # Retrieve the workflow corresponding to the given ID and extract its data collections
    workflow = [e for e in workflows if e["_id"] == workflow_id][0]
    data_collections = workflow.get("data_collections", [])

    # Extract join details for each data collection
    join_details_map = collections.defaultdict(list)
    for dc in data_collections:
        logger.info(f"Data collection: {dc}")
        if dc["config"]["type"].lower() == "table" and "join" in dc["config"]:
            dc_id = str(dc["_id"])
            join_config = dc["config"]["join"]
            zip_ids_list = [
                return_mongoid(
                    workflow_id=ObjectId(workflow_id),
                    data_collection_tag=dc_tag,
                    workflows=workflows,
                )[1]
                for dc_tag in join_config["with_dc"]
            ]
            join_config["with_dc_id"] = zip_ids_list
            logger.info(f"Join config: {join_config}")
            if join_config:
                logger.info(f"IN : Join config: {join_config}")
                join_details_map[dc_id].append(join_config)

    # Ensure symmetric join details across all related data collections
    join_details_map = normalize_join_details(join_details_map)
    # Map the IDs back to tags
    for dc_id in join_details_map:
        TOKEN = current_user["access_token"]  # type: ignore[call-non-callable]
        join_details_map[dc_id]["with_dc"] = [
            return_dc_tag_from_id(dc_id, workflows, TOKEN)  # type: ignore[too-many-positional-arguments]
            for dc_id in join_details_map[dc_id]["with_dc_id"]
        ]

    logger.info(f"Join details: {join_details_map}")

    return join_details_map


@datacollections_endpoint_router.get("/get_dc_joined/{workflow_id}")
async def get_dc_joined(workflow_id: str, current_user: str = Depends(get_user_or_anonymous)):
    """
    Retrieve join details for the data collections in a workflow.
    """

    logger.debug(f"Workflow ID: {workflow_id}")

    # Retrieve workflow
    workflow = await get_workflow_from_id(workflow_id, current_user=current_user)

    join_details_map = generate_join_dict(workflow)

    logger.debug(f"Join details: {join_details_map}")

    return join_details_map


@datacollections_endpoint_router.get("/get_tag_from_id/{data_collection_id}")
async def get_tag_from_id(
    data_collection_id: str,
    current_user: str = Depends(get_user_or_anonymous),
):
    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Use MongoDB aggregation to directly retrieve the specific data collection
    pipeline = [
        # Match projects containing this collection and with appropriate permissions
        {
            "$match": {
                "workflows.data_collections._id": data_collection_oid,
                "$or": [
                    {"permissions.owners._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        # Unwind the workflows array
        {"$unwind": "$workflows"},
        # Unwind the data_collections array
        {"$unwind": "$workflows.data_collections"},
        # Match the specific data collection ID
        {"$match": {"workflows.data_collections._id": data_collection_oid}},
        # Return only the data collection
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]

    result = list(projects_collection.aggregate(pipeline))

    if not result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    if len(result) > 1:
        raise HTTPException(
            status_code=500, detail="Multiple data collections found for the same ID."
        )

    dc_tag = result[0]["data_collection_tag"]

    return dc_tag


@datacollections_endpoint_router.put("/{data_collection_id}/name")
async def update_data_collection_name(
    data_collection_id: str,
    request_data: dict,
    current_user: str = Depends(get_current_user),
):
    """Update the name of a data collection."""
    new_name = request_data.get("new_name")
    if new_name is None:
        raise HTTPException(status_code=400, detail="new_name is required")
    return await _update_data_collection_name(data_collection_id, new_name, current_user)


@datacollections_endpoint_router.delete("/{data_collection_id}")
async def delete_data_collection_by_id(
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """Delete a data collection by its ID."""
    return await _delete_data_collection_by_id(data_collection_id, current_user)
