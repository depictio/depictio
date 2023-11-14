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


datacollections_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]
users_collection = db["users"]


@datacollections_endpoint_router.post("/scan/{workflow_id}/{data_collection_id}")
async def scan_data_collection(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    runs_collection.drop()
    files_collection.drop()

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

    workflow_cursor = workflows_collection.find_one(query)
    print(workflow_cursor)

    if not workflow_cursor:
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_id} found for the current user.",
        )

    workflow = Workflow.from_mongo(workflow_cursor)
    # retrieve data collection from workflow where data_collection_id matches
    data_collection = [
        dc for dc in workflow.data_collections if dc.id == data_collection_oid
    ][0]
    print(workflow)
    print(data_collection)

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


@datacollections_endpoint_router.post(
    "/aggregate_data/{workflow_id}/{data_collection_id}"
)
async def aggregate_data(
    # data_collection: DataCollection,
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    # data_collections_collection.drop()

    files_collection

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

    workflow_cursor = workflows_collection.find_one(query)
    print(workflow_cursor)

    if not workflow_cursor:
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )

    data_collection_config = [
        dc
        for dc in workflow_cursor["data_collections"]
        if dc["_id"] == data_collection_oid
    ][0]["config"]

    # Using the config, find relevant files
    files = list(files_collection.find({"data_collection._id": data_collection_oid}))
    print(files)
    assert isinstance(files, list)
    assert len(files) > 0
    files = [File.from_mongo(file) for file in files]

    # Define the path to your Delta table
    delta_table_path = f"/Users/tweber/Gits/depictio/data/delta_lake/{user_oid}/{workflow_oid}/{data_collection_oid}"
    print(delta_table_path)
    # os.remove(delta_table_path)
    user = User.from_mongo(users_collection.find_one({"_id": user_oid}))
    # fix this below
    deltaTable = DeltaTableAggregated(
        delta_table_location=delta_table_path,
        aggregation=[
            Aggregation(
                aggregation_time=datetime.now(),
                aggregation_by=user,
                aggregation_version=1,
            )
        ],
    )

    data_frames = []

    for file_info in files:
        print(file_info)
        # if file_info.aggregated == True:
        #     continue  # Skip already processed files

        file_path = file_info.file_location
        df = pl.read_csv(
            file_path,
            **data_collection_config["polars_kwargs"],
        )
        print(df)
        raw_cols = df.columns
        df = df.with_columns(pl.lit(file_info.run_id).alias("depictio_run_id"))
        df = df.select(["depictio_run_id"] + raw_cols)
        data_frames.append(df)

        # Update the file_info in MongoDB to mark it as processed
        files_collection.update_one(
            {"_id": ObjectId(file_info.id)},
            {
                "$set": {
                    "aggregated": True,
                    "data_collection.deltaTable": deltaTable.mongo(),
                }
            },
        )
        print("Updated file_info in MongoDB")
        print("\n")

    # Aggregate data
    if data_frames:
        aggregated_df = pl.concat(data_frames)
        print(aggregated_df)
        # Write aggregated dataframe to Delta Lake
        aggregated_df.write_delta(delta_table_path)

    # data_frames = []

    # for file_info in files:
    #     file_path = file_info["file_location"]

    #     # Read the file using pandas and the given config
    #     with open(file_path, "r") as file:
    #         df = pd.read_csv(
    #             file,
    #             **data_collection_config["pandas_kwargs"],
    #         )
    #         raw_cols = df.columns.tolist()
    #         df["depictio_run_id"] = file_info["run_id"]
    #         df = df[["depictio_run_id"] + raw_cols]
    #         data_frames.append(df)

    # # Aggregate data
    # aggregated_df = pd.concat(data_frames, axis=0, ignore_index=True)

    # # Convert aggregated dataframe to bytes and save to GridFS
    # output = BytesIO()
    # aggregated_df.to_parquet(output)
    # output.seek(0)  # Rewind to the start

    # # Using a naming convention for directories in GridFS
    # filename_structure = f"aggregates/{data_collection.workflow_id}/{data_collection.data_collection_id}.pkl"
    # file_id = grid_fs.put(output, filename=filename_structure)

    results = collections.defaultdict(dict)

    # For each column in the DataFrame
    for column in aggregated_df.columns:
        # Identify the column data type
        col_type = str(aggregated_df[column].dtype)
        results[column]["type"] = col_type.lower()

        # Check if the type exists in the agg_functions dict
        if col_type in agg_functions:
            methods = agg_functions[col_type]["card_methods"]

            # Initialize an empty dictionary to store results

            # For each method in the card_methods
            for method_name, method_info in methods.items():
                print(column, method_name)
                pandas_method = method_info["pandas"]

                # Check if the method is callable or a string
                if callable(pandas_method):
                    result = pandas_method(aggregated_df[column])
                elif isinstance(pandas_method, str):
                    result = getattr(aggregated_df[column], pandas_method)()
                else:
                    continue  # Skip if method is not available

                result = result.values if isinstance(result, np.ndarray) else result
                if method_name == "mode" and isinstance(result.values, np.ndarray):
                    result = result[0]
                results[column][str(method_name)] = numpy_to_python(result)

    # Update the data_collection_config with the GridFS file_id
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {
            "$set": {
                "data_collections.$[elem].deltaTable": deltaTable.mongo(),
                "data_collections.$[elem].columns_list": aggregated_df.columns,
                "data_collections.$[elem].columns_specs": serialize_for_mongo(results),
            }
        },
        array_filters=[{"elem._id": data_collection_oid}]
    )
    # data_collections_collection.create_index(
    #     [("data_collection_id", 1), ("workflow_id", 1)]
    # )

    return {
        "message": f"Data successfully aggregated and saved for data_collection: {data_collection_id} of workflow: {workflow_id}, aggregation id: {deltaTable.id}",
    }


@datacollections_endpoint_router.get("/files", response_model=List[GridFSFileInfo])
async def list_files():
    """
    Fetch all files from GridFS.
    """
    try:
        file_list = list(grid_fs.find())
        result = [
            {"filename": file.filename, "file_id": str(file._id), "length": file.length}
            for file in file_list
        ]
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching files: {e}")


@datacollections_endpoint_router.get("/delete_all_files")
async def delete_all_files():
    """
    Delete all files from GridFS.
    """
    try:
        # Fetch all files from GridFS
        file_list = list(grid_fs.find())

        # Remove each file
        for file in file_list:
            grid_fs.delete(file._id)

        return {"message": "All files deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting files: {e}")


@datacollections_endpoint_router.get(
    "/get_aggregated_file_id/{workflow_engine}/{workflow_name}/{data_collection_id}"
)
async def get_files(workflow_engine: str, workflow_name: str, data_collection_id: str):
    """
    Fetch an aggregated datacollection from GridFS.
    """
    document = data_collections_collection.find_one(
        {
            "data_collection_id": data_collection_id,
            "workflow_id": f"{workflow_engine}/{workflow_name}",
        }
    )
    print(document)

    # # Fetch all files from GridFS
    # associated_file = grid_fs.get(ObjectId(document["gridfs_file_id"]))
    # print(associated_file)
    # # df = pd.read_parquet(associated_file).to_dict()
    # return associated_file
    return {"gridfs_file_id": document["gridfs_file_id"]}


@datacollections_endpoint_router.get(
    "/get_columns/{workflow_engine}/{workflow_name}/{data_collection_id}"
)
async def get_files(workflow_engine: str, workflow_name: str, data_collection_id: str):
    """
    Fetch columns list and specs from data collection
    """
    document = data_collections_collection.find_one(
        {
            "data_collection_id": data_collection_id,
            "workflow_id": f"{workflow_engine}/{workflow_name}",
        }
    )
    print(document.keys())

    return {
        "columns_list": document["columns_list"],
        "columns_specs": document["columns_specs"],
    }
