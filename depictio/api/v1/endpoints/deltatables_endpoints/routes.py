import collections
from datetime import datetime
import hashlib
import os
from pprint import pprint
import shutil
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
import deltalake
import polars as pl
import numpy as np

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db, workflows_collection, files_collection, users_collection, deltatables_collection
from depictio.api.v1.s3 import s3_client
from depictio.api.v1.endpoints.deltatables_endpoints.models import Aggregation, DeltaTableAggregated
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    numpy_to_python,
    serialize_for_mongo,
    agg_functions,
)


deltatables_endpoint_router = APIRouter()


@deltatables_endpoint_router.get("/get/{workflow_id}/{data_collection_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def list_registered_files(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """

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

    # Query to find deltatable associated with the data collection
    query = {"_id": workflow_oid, "data_collections._id": data_collection_oid}
    deltatable_cursor = workflows_collection.find(query, {"data_collections.$": 1})
    deltatable = list(deltatable_cursor)[0]["data_collections"][0]["deltatable"]
    # print(deltatable)

    return convert_objectid_to_str(deltatable)


def read_table_for_DC_table(file_info, data_collection_config, deltaTable):
    """
    Read a table file and return a Polars DataFrame.
    """
    # print("file_info")
    # print(file_info)
    # print("data_collection_config")
    # print(data_collection_config)
    # if file_info.aggregated == True:
    #     continue  # Skip already processed files

    file_path = file_info.file_location
    df = pl.read_csv(
        file_path,
        **dict(data_collection_config["polars_kwargs"]),
    )
    # print(df)
    raw_cols = df.columns
    df = df.with_columns(pl.lit(file_info.run_id).alias("depictio_run_id"))
    df = df.select(["depictio_run_id"] + raw_cols)
    # data_frames.append(df)

    # Update the file_info in MongoDB to mark it as processed
    files_collection.update_one(
        {"_id": ObjectId(file_info.id)},
        {
            "$set": {
                "aggregated": True,
                "data_collection.deltatable": deltaTable.mongo(),
            }
        },
    )
    # print("Updated file_info in MongoDB")
    return df


def upload_dir_to_s3(bucket_name, s3_folder, local_dir, s3_client):
    """
    Recursively uploads a directory to S3 preserving the directory structure.
    """
    for root, dirs, files in os.walk(local_dir):
        for filename in files:
            # construct the full local path
            local_path = os.path.join(root, filename)

            # construct the full S3 path
            relative_path = os.path.relpath(local_path, local_dir)
            s3_path = os.path.join(s3_folder, relative_path).replace("\\", "/")

            # upload the file
            print(f"Uploading {local_path} to {bucket_name}/{s3_path}...")
            s3_client.upload_file(local_path, bucket_name, s3_path)


def precompute_columns_specs(aggregated_df: pl.DataFrame, agg_functions: dict):
    """
    Aggregate dataframes and return a list of dictionaries with column names, types and specs.
    """
    # TODO: performance improvement: use polars instead of pandas
    aggregated_df = aggregated_df.to_pandas()

    results = list()
    # For each column in the DataFrame
    for column in aggregated_df.columns:
        tmp_dict = collections.defaultdict(dict)
        tmp_dict["name"] = column
        # Identify the column data type
        col_type = str(aggregated_df[column].dtype).lower()
        # print(col_type)
        tmp_dict["type"] = col_type.lower()
        # print(agg_functions)
        # Check if the type exists in the agg_functions dict
        if col_type in agg_functions:
            methods = agg_functions[col_type]["card_methods"]

            # Initialize an empty dictionary to store results

            # For each method in the card_methods
            for method_name, method_info in methods.items():
                # print(column, method_name)
                pandas_method = method_info["pandas"]
                # print(pandas_method)
                # Check if the method is callable or a string
                if callable(pandas_method):
                    result = pandas_method(aggregated_df[column])
                    # print(result)
                elif isinstance(pandas_method, str):
                    result = getattr(aggregated_df[column], pandas_method)()
                    # print(result)
                else:
                    continue  # Skip if method is not available

                result = result.values if isinstance(result, np.ndarray) else result
                # print(result)
                if method_name == "mode" and isinstance(result.values, np.ndarray):
                    result = result[0]
                tmp_dict["specs"][str(method_name)] = numpy_to_python(result)
        results.append(tmp_dict)
    print(results)
    return results


@deltatables_endpoint_router.post("/create/{workflow_id}/{data_collection_id}")
async def aggregate_data(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    print("Aggregating data...")

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

    # Extract the data_collection_config from the workflow
    dc_config = data_collection.config

    # Assert type of data_collection_config is Table
    assert dc_config.type == "Table", "Data collection type must be Table"
    dc_config = convert_objectid_to_str(dc_config.mongo())

    # Using the config, find files associated with the data collection
    files = list(
        files_collection.find(
            {
                "data_collection.id": data_collection_oid,
            }
        )
    )

    # Assert that files is a list and not empty
    assert isinstance(files, list)
    assert len(files) > 0

    # Convert the files to File objects
    files = [File.from_mongo(file) for file in files]

    # Create a DeltaTableAggregated object
    # root_dir = "/Users/tweber/Gits/depictio"
    destination_file_name = f"minio_data/{settings.minio.bucket}/{user_oid}/{workflow_oid}/{data_collection_oid}/"  # Destination path in MinIO
    os.makedirs(destination_file_name, exist_ok=True)

    # Get the user object to use as aggregation_by
    user = User.from_mongo(users_collection.find_one({"_id": user_oid}))

    # Check if a DeltaTableAggregated already exists in the deltatables_collection
    query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})

    # Check if the DeltaTableAggregated exists, if not create a new one, else update the existing one
    print("Checking if deltatable exists")
    if query_dt:
        print("DeltaTable exists")
        deltatable = DeltaTableAggregated.from_mongo(query_dt)
    else:
        print("DeltaTable does not exist")
        deltatable = DeltaTableAggregated(
            delta_table_location=destination_file_name,
            data_collection_id=data_collection_oid,
        )
        deltatable.id = ObjectId()

    # Read each file and append to data_frames list for futher aggregation
    data_frames = []
    for file_info in files:
        data_frames.append(read_table_for_DC_table(file_info, dc_config["dc_specific_properties"], deltatable))

    # Aggregate data
    if not data_frames:
        raise HTTPException(
            status_code=404,
            detail=f"No files found for data_collection: {data_collection_id} of workflow: {workflow_id}.",
        )

    # Aggregate the dataframes
    aggregated_df = pl.concat(data_frames)

    # TODO: remove - just for testing
    # Add timestamp column
    aggregated_df = aggregated_df.with_columns(depictio_aggregation_time=pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    print("aggregated_df")
    print(aggregated_df)

    # TODO: solve the issue of writing to MinIO using polars
    # TMP solution: write to Delta Lake locally and then upload to MinIO
    # Write aggregated dataframe to Delta Lake
    aggregated_df.write_delta(destination_file_name, mode="overwrite", overwrite_schema=True)

    # Upload the Delta Lake to MinIO
    # upload_dir_to_s3(
    #     settings.minio.bucket,
    #     f"{user_oid}/{workflow_oid}/{data_collection_oid}",
    #     destination_file_name,
    #     s3_client,
    # )

    print("Write complete to MinIO at destination: ", destination_file_name)

    # Precompute columns specs
    results = precompute_columns_specs(aggregated_df, agg_functions)

    # Compute the hash of the aggregated data using the filename, time, and size
    filesize = os.path.getsize(destination_file_name)
    hash_str = f"{destination_file_name}{datetime.now()}{filesize}"
    hash_str = hash_str.encode("utf-8")
    hash_str = hashlib.sha256(hash_str).hexdigest()

    version = 1 if not deltatable.aggregation else deltatable.aggregation[-1].aggregation_version + 1

    deltatable.aggregation.append(
        Aggregation(
            aggregation_time=datetime.now(),
            aggregation_by=user,
            aggregation_version=version,
            aggregation_hash=hash_str,
            aggregation_columns_specs=results,
        )
    )

    print("DeltaTableAggregated")
    print(deltatable)

    if query_dt:
        print("Updating existing DeltaTableAggregated")
        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid},
            {
                "$set": {
                    "delta_table_location": destination_file_name,
                    "aggregation": serialize_for_mongo(deltatable.aggregation),
                }
            },
        )
    else:
        print("Inserting new DeltaTableAggregated")
        deltatables_collection.insert_one(deltatable.mongo())

    return {
        "message": f"Data successfully aggregated and saved for data_collection: {data_collection_id} of workflow: {workflow_id}, aggregation id: {deltatable.id}",
    }


@deltatables_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_deltatable(
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
        {"$pull": {"data_collections": {"_id": data_collection_oid}}},
    )

    return {"message": f"Deleted {delete_result.deleted_count} files successfully"}
