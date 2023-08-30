import collections
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import PosixPath
import re
from bson import ObjectId
from fastapi import HTTPException
from fastapi import APIRouter
from typing import List

import pandas as pd
import numpy as np
from pydantic import BaseModel

from configs.config import settings
from db import db, grid_fs


# from modules.datacollections_endpoints.models import File
# from modules.workflow_endpoints.models import Workflow
from depictio.fastapi_backend.configs.models import Workflow, File, DataCollection
from depictio.fastapi_backend.configs.models import GridFSFileInfo
from depictio.fastapi_backend.utils import (
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


@datacollections_endpoint_router.post("/scan")
async def scan_data_collection(workflow: Workflow, data_collection: DataCollection):
    print(data_collection)

    # print(mongo_models)

    # runs_collection.drop()
    # files_collection.drop()

    location = workflow.workflow_config.parent_runs_location

    runs_and_content = scan_runs(location, workflow.workflow_config, data_collection)
    runs_and_content = serialize_for_mongo(runs_and_content)
    # print

    if isinstance(runs_and_content, list) and all(
        isinstance(item, dict) for item in runs_and_content
    ):
        return_dict = {workflow.workflow_id: collections.defaultdict(list)}
        for run in runs_and_content:
            files = run.pop("files", [])

            # Insert the run into runs_collection and retrieve its id
            inserted_run = runs_collection.insert_one(run)
            # run_id = inserted_run.inserted_id

            # Add run_id to each file before inserting
            for file in files:
                file["run_id"] = run.get("run_id")
                files_collection.insert_one(file)
                return_dict[workflow.workflow_id][run.get("run_id")].append(
                    file.get("file_location")
                )

        # return_dict = json.dumps(return_dict, indent=4)

        return {"message": f"Files successfully scanned and created: {return_dict}"}
    else:
        return {"Warning: runs_and_content is not a list of dictionaries."}


@datacollections_endpoint_router.post("/aggregate_workflow_data")
async def aggregate_workflow_data(data_collection: DataCollection):
    # data_collections_collection.drop()

    print(data_collection)
    # Retrieve configuration based on workflow_data_collection_id
    data_collection_config = data_collections_collection.find_one(
        {"data_collection_id": data_collection.data_collection_id}
    )
    print(data_collection_config)

    if not data_collection_config:
        raise HTTPException(status_code=404, detail="Data Collection not found")

    # Using the config, find relevant files
    files = files_collection.find(
        {"data_collection_id": data_collection.data_collection_id}
    )

    data_frames = []

    for file_info in files:
        file_path = file_info["file_location"]

        # Read the file using pandas and the given config
        with open(file_path, "r") as file:
            config = data_collection_config["config"]
            df = pd.read_csv(
                file,
                **config["pandas_kwargs"],
            )
            raw_cols = df.columns.tolist()
            df["depictio_run_id"] = file_info["run_id"]
            df = df[["depictio_run_id"] + raw_cols]
            data_frames.append(df)

    # Aggregate data
    aggregated_df = pd.concat(data_frames, axis=0, ignore_index=True)

    # Convert aggregated dataframe to bytes and save to GridFS
    output = BytesIO()
    aggregated_df.to_parquet(output)
    output.seek(0)  # Rewind to the start

    # Using a naming convention for directories in GridFS
    filename_structure = f"aggregates/{data_collection.workflow_id}/{data_collection.data_collection_id}.pkl"
    file_id = grid_fs.put(output, filename=filename_structure)

    results = collections.defaultdict(dict)

    # For each column in the DataFrame
    for column in aggregated_df.columns:
        # Identify the column data type
        col_type = str(aggregated_df[column].dtype)
        results[column]["type"] = col_type

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
    data_collections_collection.update_one(
        {"data_collection_id": data_collection.data_collection_id},
        {
            "$set": {
                "gridfs_file_id": str(file_id),
                "columns_list": aggregated_df.columns.tolist(),
                "columns_specs": serialize_for_mongo(results),
            },
        },
    )
    data_collections_collection.create_index(
        [("data_collection_id", 1), ("workflow_id", 1)]
    )

    return {
        "message": "Data successfully aggregated and saved",
        "file_id": str(file_id),
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
    print(document.keys())

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
