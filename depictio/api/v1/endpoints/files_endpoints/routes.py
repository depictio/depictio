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
from depictio.api.v1.db import db, grid_fs
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.models.pydantic_models import (
    Aggregation,
    DeltaTableAggregated,
    User,
    Workflow,
    File,
    DataCollection,
    WorkflowRun,
)
from depictio.api.v1.models.pydantic_models import GridFSFileInfo
from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    numpy_to_python,
    scan_runs,
    serialize_for_mongo,
    agg_functions,
)


files_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]
users_collection = db["users"]


@files_endpoint_router.get("/list/{workflow_id}/{data_collection_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def list_registered_files(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """

    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.user_id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)

    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
        "data_collections._id": data_collection_oid,
    }
    print(query)
    if not workflows_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )
    
    query_files = {
        "data_collection._id": data_collection_oid,
    }
    files = list(files_collection.find(query_files))
    return convert_objectid_to_str(files)


@files_endpoint_router.post("/scan/{workflow_id}/{data_collection_id}")
async def scan_data_collection(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    runs_collection.drop()
    files_collection.drop()

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
    # # retrieve data collection from workflow where data_collection_id matches
    # data_collection = [
    #     dc for dc in workflow.data_collections if dc.id == data_collection_oid
    # ][0]
    # print(workflow)
    # print(data_collection)

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

    # Retrieve the workflow_config from the workflow
    locations = workflow.workflow_config.parent_runs_location

    print(locations)

    # Scan the runs and retrieve the files
    for location in locations:
        print(location)
        runs_and_content = scan_runs(
            location, workflow.workflow_config, data_collection
        )
        runs_and_content = serialize_for_mongo(runs_and_content)

        if isinstance(runs_and_content, list) and all(
            isinstance(item, dict) for item in runs_and_content
        ):
            return_dict = {workflow.id: collections.defaultdict(list)}
            for run in runs_and_content:
                files = run.pop("files", [])

                run = WorkflowRun(**run)

                # Insert the run into runs_collection and retrieve its id
                inserted_run = runs_collection.insert_one(run.mongo())
                # run_id = inserted_run.inserted_id

                # Add run_id to each file before inserting
                for file in files:
                    file = File(**file)
                    # file["run_id"] = run.get("run_id")
                    files_collection.insert_one(file.mongo())
                    # return_dict[workflow.id][run.get("run_id")].append(
                    #     file.get("file_location")
                    # )

        # return_dict = json.dumps(return_dict, indent=4)

        return {
            "message": f"Files successfully scanned and created for data_collection: {data_collection.id} of workflow: {workflow.id}"
        }
    else:
        return {"Warning: runs_and_content is not a list of dictionaries."}


@files_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_files(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),

):
    """
    Delete all files from GridFS.
    """

    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.user_id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)
    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
        "data_collections._id": data_collection_oid,
    }
    print(query)
    if not workflows_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )
    
    # Query to find files associated with the data collection
    query_files = {"data_collection_id": data_collection_oid}
    
    # Batch delete the files
    delete_result = files_collection.delete_many(query_files)

    # Optionally, update the workflow document to reflect the deletion
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {"$pull": {"data_collections": {"_id": data_collection_oid}}}
    )
    
    return {"message": f"Deleted {delete_result.deleted_count} files successfully"}
