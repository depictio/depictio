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


@files_endpoint_router.get("/list_registered_files/{workflow_id}/{data_collection_id}")
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

@files_endpoint_router.delete("/delete_files/{workflow_id}/{data_collection_id}")
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
