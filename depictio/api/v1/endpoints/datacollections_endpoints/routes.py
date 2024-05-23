import collections
from fastapi import HTTPException, Depends, APIRouter
from typing import Dict, List

from depictio.api.v1.configs.config import settings, logger
from depictio.api.v1.db import db
from depictio.api.v1.endpoints.files_endpoints.routes import delete_files
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.endpoints.workflow_endpoints.routes import get_all_workflows, get_workflow
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
    # Assuming the 'current_user' now holds a 'user_id' as an ObjectId after being parsed in 'get_current_user'
    # workflow_oid = ObjectId(workflow_id)
    # data_collection_oid = ObjectId(data_collection_id)
    # user_oid = ObjectId(current_user.user_id)  # This should be the ObjectId
    # assert isinstance(workflow_oid, ObjectId)
    # assert isinstance(data_collection_oid, ObjectId)
    # assert isinstance(user_oid, ObjectId)

    # # Construct the query
    # query = {
    #     "_id": workflow_oid,
    #     "permissions.owners.user_id": user_oid,
    #     "data_collections._id": data_collection_oid,
    # }
    # print(query)

    # workflow_cursor = workflows_collection.find_one(query)
    # print(workflow_cursor)

    # if not workflow_cursor:
    #     raise HTTPException(
    #         status_code=404,
    #         detail=f"No workflows with id {workflow_id} found for the current user.",
    #     )

    # workflow = Workflow.from_mongo(workflow_cursor)
    # print(workflow)
    # # retrieve data collection from workflow where data_collection_id matches
    # data_collection = [
    #     dc for dc in workflow.data_collections if dc.id == data_collection_oid
    # ][0]

    # Use the utility function to validate and retrieve necessary info
    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.user_id,
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
    # workflow_oid = ObjectId(workflow_id)
    # data_collection_oid = ObjectId(data_collection_id)
    # user_oid = ObjectId(current_user.user_id)  # This should be the ObjectId
    # assert isinstance(workflow_oid, ObjectId)
    # assert isinstance(data_collection_oid, ObjectId)
    # assert isinstance(user_oid, ObjectId)

    # # Construct the query
    # query = {
    #     "_id": workflow_oid,
    #     "permissions.owners.user_id": user_oid,
    #     "data_collections._id": data_collection_oid,
    # }
    # print(query)

    # workflow_cursor = workflows_collection.find_one(query)
    # print(workflow_cursor)

    # if not workflow_cursor:
    #     raise HTTPException(
    #         status_code=404,
    #         detail=f"No workflows with id {workflow_oid} found for the current user.",
    #     )

    # data_collection = [
    #     dc
    #     for dc in workflow_cursor["data_collections"]
    #     if dc["_id"] == data_collection_oid
    # ][0]

    # Use the utility function to validate and retrieve necessary info
    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.user_id,
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

    # delete corresponding files from files_collection

    # # Ensure that the current user is authorized to update the workflow
    # user_id = current_user.user_id
    # print(
    #     user_id,
    #     type(user_id),
    #     existing_workflow["permissions"]["owners"],
    #     [u["user_id"] for u in existing_workflow["permissions"]["owners"]],
    # )
    # if user_id not in [
    #     u["user_id"] for u in existing_workflow["permissions"]["owners"]
    # ]:
    #     raise HTTPException(
    #         status_code=403,
    #         detail=f"User with ID '{user_id}' is not authorized to delete workflow with ID '{workflow_id}'",
    #     )
    # # Delete the workflow
    # workflows_collection.delete_one({"_id": id})
    # assert workflows_collection.find_one({"_id": id}) is None

    # return {"message": f"Workflow {workflow_tag} with ID '{id}' deleted successfully"}


# @datacollections_endpoint_router.get(
#     "/get_aggregated_file_id/{workflow_engine}/{workflow_name}/{data_collection_id}"
# )
# async def get_files(workflow_engine: str, workflow_name: str, data_collection_id: str):
#     """
#     Fetch an aggregated datacollection from GridFS.
#     """
#     document = data_collections_collection.find_one(
#         {
#             "data_collection_id": data_collection_id,
#             "workflow_id": f"{workflow_engine}/{workflow_name}",
#         }
#     )
#     print(document)

#     # # Fetch all files from GridFS
#     # associated_file = grid_fs.get(ObjectId(document["gridfs_file_id"]))
#     # print(associated_file)
#     # # df = pd.read_parquet(associated_file).to_dict()
#     # return associated_file
#     return {"gridfs_file_id": document["gridfs_file_id"]}


# @datacollections_endpoint_router.get(
#     "/get_columns/{workflow_engine}/{workflow_name}/{data_collection_id}"
# )
# async def get_files(workflow_engine: str, workflow_name: str, data_collection_id: str):
#     """
#     Fetch columns list and specs from data collection
#     """
#     document = data_collections_collection.find_one(
#         {
#             "data_collection_id": data_collection_id,
#             "workflow_id": f"{workflow_engine}/{workflow_name}",
#         }
#     )
#     print(document.keys())

#     return {
#         "columns_list": document["columns_list"],
#         "columns_specs": document["columns_specs"],
#     }


def symmetrize_join_details(join_details_map: Dict[str, List[dict]]):
    """Ensure symmetric join details across all related data collections."""
    # Create a list of items to iterate over, so the original dict can be modified
    items = list(join_details_map.items())
    for dc_id, joins in items:
        for join in joins:
            for related_dc_id in join["with_dc"]:
                # Initialize related_dc_join list if not already present
                if related_dc_id not in join_details_map:
                    join_details_map[related_dc_id] = []

                # Check if related data collection already has symmetric join details with the current one
                related_joins = join_details_map[related_dc_id]
                symmetric_join_exists = any(dc_id in join_detail["with_dc"] for join_detail in related_joins)

                if not symmetric_join_exists:
                    # Create symmetric join detail for related data collection
                    symmetric_join = {
                        "on_columns": join["on_columns"],
                        "how": join["how"],
                        "with_dc": [dc_id],  # Link back to the current data collection
                    }
                    join_details_map[related_dc_id].append(symmetric_join)


def generate_join_dict(workflow):
    join_dict = {}

    wf_id = str(workflow["_id"])
    join_dict[wf_id] = {}

    dc_ids = {str(dc["_id"]): dc for dc in workflow["data_collections"] if dc["config"]["type"].lower() == "table"}
    visited = set()

    def find_joins(dc_id, join_configs):
        if dc_id in visited:
            return
        visited.add(dc_id)
        if "join" in dc_ids[dc_id]["config"]:
            join_info = dc_ids[dc_id]["config"]["join"]
            for related_dc_tag in join_info.get("with_dc", []):
                related_dc_id = next((str(dc["_id"]) for dc in workflow["data_collections"] if dc["data_collection_tag"] == related_dc_tag), None)
                if related_dc_id:
                    join_configs[f"{dc_id}--{related_dc_id}"] = {
                        "how": join_info["how"],
                        "on_columns": join_info["on_columns"],
                        "dc_tags": [dc_ids[dc_id]["data_collection_tag"], dc_ids[related_dc_id]["data_collection_tag"]],
                    }
                    find_joins(related_dc_id, join_configs)

    for dc_id in dc_ids:
        if dc_id not in visited:
            join_configs = {}
            find_joins(dc_id, join_configs)
            join_dict[wf_id].update(join_configs)

    return join_dict


def normalize_join_details(join_details):
    normalized_details = {}

    # Initialize entries for all DCs
    for dc_id, joins in join_details.items():
        for join in joins:
            if dc_id not in normalized_details:
                normalized_details[dc_id] = {
                    "on_columns": join["on_columns"],
                    "how": join["how"],
                    "with_dc": set(join.get("with_dc", [])),  # Use set for unique elements
                    "with_dc_id": set(join.get("with_dc_id", [])),  # Use set for unique elements
                }

    # Update relationships
    for dc_id, joins in join_details.items():
        for join in joins:
            # Update related by ID
            for related_dc_id in join.get("with_dc_id", []):
                # Ensure reciprocal relationship exists
                normalized_details[dc_id]["with_dc_id"].add(related_dc_id)
                if related_dc_id not in normalized_details:
                    normalized_details[related_dc_id] = {"on_columns": join["on_columns"], "how": join["how"], "with_dc": set(), "with_dc_id": set()}
                normalized_details[related_dc_id]["with_dc_id"].add(dc_id)

            # Update related by Tag
            for related_dc_tag in join.get("with_dc", []):
                normalized_details[dc_id]["with_dc"].add(related_dc_tag)
                # This assumes tags to IDs resolution happens elsewhere or they're handled as equivalent identifiers
                # If 'related_dc_tag' could also appear in 'normalized_details', consider adding reciprocal logic here

    # Convert sets back to lists for the final output
    for dc_id in normalized_details:
        normalized_details[dc_id]["with_dc"] = list(normalized_details[dc_id]["with_dc"])
        normalized_details[dc_id]["with_dc_id"] = list(normalized_details[dc_id]["with_dc_id"])

    return normalized_details


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
        join_details_map[dc_id]["with_dc"] = [return_dc_tag_from_id(workflow_id, dc_id, workflows) for dc_id in join_details_map[dc_id]["with_dc_id"]]

    logger.info(f"Join details: {join_details_map}")

    return join_details_map


@datacollections_endpoint_router.get("/get_dc_joined/{workflow_id}")
async def get_dc_joined(workflow_id: str, current_user: str = Depends(get_current_user)):
    """
    Retrieve join details for the data collections in a workflow.
    """

    # Retrieve workflow
    workflow = await get_workflow(workflow_id, current_user=current_user)
    workflow = workflow.mongo()
    logger.info(f"Workflow: {workflow}")
    logger.info(f"type(workflow): {type(workflow)}")

    join_details_map = generate_join_dict(workflow)

    logger.info(f"Join details: {join_details_map}")

    return join_details_map
