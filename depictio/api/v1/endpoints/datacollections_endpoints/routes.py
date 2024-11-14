import collections
from fastapi import HTTPException, Depends, APIRouter


from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.datacollections_endpoints.utils import generate_join_dict, normalize_join_details
from depictio.api.v1.endpoints.files_endpoints.routes import delete_files
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.endpoints.workflow_endpoints.routes import get_all_workflows, get_workflow_from_id
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.dash.utils import return_dc_tag_from_id, return_mongoid


datacollections_endpoint_router = APIRouter()


data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db["users"]


@datacollections_endpoint_router.get("/specs/{workflow_id}/{data_collection_id}")
# @workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def specs(
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
        current_user.id,
        workflow_id,
        data_collection_id,
    )

    data_collection = convert_objectid_to_str(data_collection)

    if not data_collection:
        raise HTTPException(status_code=404, detail="No workflows found for the current user.")

    return data_collection


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
        current_user.id,
        workflow_id,
        data_collection_id,
    )

    # delete the data collection from the workflow
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {"$pull": {"data_collections": data_collection}},
    )
    delete_files_message = await delete_files(workflow_id, data_collection_id, current_user)
    return delete_files_message


@datacollections_endpoint_router.get("/get_join_tables/{workflow_id}/{data_collection_id}")
async def get_join_tables(workflow_id: str, data_collection_id: str, current_user: str = Depends(get_current_user)):
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
            zip_ids_list = [return_mongoid(workflow_id=workflow_id, data_collection_tag=dc_tag, workflows=workflows)[1] for dc_tag in join_config["with_dc"]]
            join_config["with_dc_id"] = zip_ids_list
            logger.info(f"Join config: {join_config}")
            if join_config:
                logger.info(f"IN : Join config: {join_config}")
                join_details_map[dc_id].append(join_config)

    # Ensure symmetric join details across all related data collections
    join_details_map = normalize_join_details(join_details_map)
    # Map the IDs back to tags
    for dc_id in join_details_map:
        TOKEN = current_user["access_token"]
        join_details_map[dc_id]["with_dc"] = [return_dc_tag_from_id(workflow_id, dc_id, workflows, TOKEN) for dc_id in join_details_map[dc_id]["with_dc_id"]]

    logger.info(f"Join details: {join_details_map}")

    return join_details_map


@datacollections_endpoint_router.get("/get_dc_joined/{workflow_id}")
async def get_dc_joined(workflow_id: str, current_user: str = Depends(get_current_user)):
    """
    Retrieve join details for the data collections in a workflow.
    """

    logger.info(f"Workflow ID: {workflow_id}")
    logger.info(f"Current user: {current_user}")

    # Retrieve workflow
    workflow = await get_workflow_from_id(workflow_id, current_user=current_user)
    workflow = workflow.mongo()
    logger.info(f"Workflow: {workflow}")
    logger.info(f"type(workflow): {type(workflow)}")

    join_details_map = generate_join_dict(workflow)

    logger.info(f"Join details: {join_details_map}")

    return join_details_map
