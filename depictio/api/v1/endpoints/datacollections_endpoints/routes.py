import collections
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import PosixPath
import re
from bson import ObjectId
from deltalake import DeltaTable
from fastapi import HTTPException, Depends, APIRouter
from typing import List

import pandas as pd
import polars as pl
import numpy as np
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.endpoints.files_endpoints.routes import delete_files
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    numpy_to_python,
    scan_runs,
    serialize_for_mongo,
    agg_functions,
)


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
         workflows_collection, current_user.user_id, workflow_id, data_collection_id, 
    )

    data_collection = convert_objectid_to_str(data_collection)

    if not data_collection:
        raise HTTPException(
            status_code=404, detail="No workflows found for the current user."
        )

    return data_collection



@datacollections_endpoint_router.delete(
    "/delete/{workflow_id}/{data_collection_id}"
)
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
         workflows_collection, current_user.user_id, workflow_id, data_collection_id, 
    )

    # delete the data collection from the workflow
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {"$pull": {"data_collections": data_collection}},
    )
    delete_files_message = await delete_files(
        workflow_id, data_collection_id, current_user
    )
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


@datacollections_endpoint_router.get("/get_join_tables/{workflow_id}")
async def get_join_tables(workflow_id: str, current_user: str = Depends(get_current_user)):
    # Find the workflow by ID
    workflow_oid = ObjectId(workflow_id)
    assert isinstance(workflow_oid, ObjectId)
    existing_workflow = workflows_collection.find_one({"_id": workflow_oid})

    if not existing_workflow:
        raise HTTPException(status_code=404, detail=f"Workflow with ID '{workflow_id}' does not exist.")

    data_collections = existing_workflow["data_collections"]

    # Initialize a map to track join details
    join_details_map = collections.defaultdict(list)
    for data_collection in data_collections:
        if "join" in data_collection["config"]:
            dc_id = str(data_collection["_id"])
            join_details_map[dc_id].append(data_collection["config"]["join"].copy())
            for sub_dc_id in data_collection["config"]["join"]["with_dc"]:
                tmp_dict = data_collection["config"]["join"]
                tmp_dict["with_dc"] = [e for e in tmp_dict["with_dc"] if e != dc_id and e != sub_dc_id]
                tmp_dict["with_dc"].append(dc_id)
                join_details_map[sub_dc_id].append(tmp_dict)

    print(join_details_map)
    return join_details_map
