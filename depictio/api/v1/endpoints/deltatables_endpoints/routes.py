import collections
from datetime import datetime
import hashlib
import os
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
import polars as pl
import numpy as np

from depictio.api.v1.configs.config import settings, logger
from depictio.api.v1.db import workflows_collection, files_collection, users_collection, deltatables_collection
from depictio.api.v1.s3 import minio_storage_options
from depictio.api.v1.endpoints.deltatables_endpoints.models import Aggregation, DeltaTableAggregated
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.utils import (
    numpy_to_python,
    serialize_for_mongo,
)

from depictio.dash.modules.card_component.agg_functions import agg_functions

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
    query = {"data_collection_id": data_collection_oid}
    deltatable_cursor = deltatables_collection.find(query)
    deltatables = list(deltatable_cursor)[0]
    # logger.info(deltatable)

    return convert_objectid_to_str(deltatables)


def read_table_for_DC_table(file_info, data_collection_config_raw, deltaTable):
    """
    Read a table file and return a Polars DataFrame.
    """
    # logger.info("file_info")
    # logger.info(file_info)
    # logger.info("data_collection_config")
    # logger.info(data_collection_config)
    # if file_info.aggregated == True:
    #     continue  # Skip already processed files

    file_path = file_info.file_location
    data_collection_config = data_collection_config_raw["dc_specific_properties"]

    if data_collection_config["format"].lower() in ["csv", "tsv", "txt"]:
        # Read the file using polars

        df = pl.read_csv(
            file_path,
            **dict(data_collection_config["polars_kwargs"]),
        )
    elif data_collection_config["format"].lower() in ["parquet"]:
        df = pl.read_parquet(file_path, **dict(data_collection_config["polars_kwargs"]))

    elif data_collection_config["format"].lower() in ["feather"]:
        df = pl.read_feather(file_path, **dict(data_collection_config["polars_kwargs"]))

    elif data_collection_config["format"].lower() in ["xls", "xlsx"]:
        df = pl.read_excel(file_path, **dict(data_collection_config["polars_kwargs"]))

    # logger.info(df)
    raw_cols = df.columns
    no_run_id = False
    logger.info(f"data_collection_config : {data_collection_config_raw}")
    if "metatype" in data_collection_config_raw:
        logger.info(f'metatype : {data_collection_config_raw["metatype"]}')

        if data_collection_config_raw["metatype"].lower() == "metadata":
            logger.info("Metadata file detected")
            no_run_id = True
    if not no_run_id:
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
    # logger.info("Updated file_info in MongoDB")
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
            logger.info(f"Uploading {local_path} to {bucket_name}/{s3_path}...")
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
        # logger.info(col_type)
        tmp_dict["type"] = col_type.lower()
        # logger.info(agg_functions)
        # Check if the type exists in the agg_functions dict
        if col_type in agg_functions:
            methods = agg_functions[col_type]["card_methods"]

            # Initialize an empty dictionary to store results

            # For each method in the card_methods
            for method_name, method_info in methods.items():
                # logger.info(column, method_name)
                pandas_method = method_info["pandas"]
                # logger.info(pandas_method)
                # Check if the method is callable or a string
                if callable(pandas_method):
                    result = pandas_method(aggregated_df[column])
                    # logger.info(result)
                elif isinstance(pandas_method, str):
                    result = getattr(aggregated_df[column], pandas_method)()
                    # logger.info(result)
                else:
                    continue  # Skip if method is not available

                result = result.values if isinstance(result, np.ndarray) else result
                # logger.info(result)
                if method_name == "mode" and isinstance(result.values, np.ndarray):
                    result = result[0]
                tmp_dict["specs"][str(method_name)] = numpy_to_python(result)
        results.append(tmp_dict)
    logger.info(results)
    return results


@deltatables_endpoint_router.get("/specs/{workflow_id}/{data_collection_id}")
# @workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def specs(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch columns list and specs from data collection
    # TODO: currently returns the last aggregation, need to fix with versioning
    """
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

    # Query to find deltatable associated with the data collection
    query = {"data_collection_id": data_collection_oid}
    deltatable_cursor = deltatables_collection.find(query)
    deltatables = list(deltatable_cursor)[0]

    # TODO - fix with versioning
    column_specs = deltatables["aggregation"][-1]["aggregation_columns_specs"]

    if not data_collection:
        raise HTTPException(status_code=404, detail="No workflows found for the current user.")

    return column_specs


@deltatables_endpoint_router.post("/create/{workflow_id}/{data_collection_id}")
async def aggregate_data(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    logger.info("Aggregating data...")

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
                "data_collection._id": data_collection_oid,
            }
        )
    )

    # Assert that files is a list and not empty
    assert isinstance(files, list)
    assert len(files) > 0

    # Convert the files to File objects
    files = [File.from_mongo(file) for file in files]

    # Create a DeltaTableAggregated object
    destination_file_name = f"s3://{settings.minio.bucket}/{user_oid}/{workflow_oid}/{data_collection_oid}/"  # Destination path in MinIO
    # destination_file_name = f"{settings.minio.data_dir}/{settings.minio.bucket}/{user_oid}/{workflow_oid}/{data_collection_oid}/"  # Destination path in MinIO
    os.makedirs(destination_file_name, exist_ok=True)

    # Get the user object to use as aggregation_by
    user = User.from_mongo(users_collection.find_one({"_id": user_oid}))

    # Check if a DeltaTableAggregated already exists in the deltatables_collection
    query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})

    # Check if the DeltaTableAggregated exists, if not create a new one, else update the existing one
    logger.info("Checking if deltatable exists")
    if query_dt:
        logger.info("DeltaTable exists")
        deltatable = DeltaTableAggregated.from_mongo(query_dt)
    else:
        logger.info("DeltaTable does not exist")
        deltatable = DeltaTableAggregated(
            delta_table_location=destination_file_name,
            data_collection_id=data_collection_oid,
        )
        # deltatable.id = ObjectId()

    # Read each file and append to data_frames list for futher aggregation
    data_frames = []
    for file_info in files:
        logger.info(f"TESTTT : Reading file: {file_info.file_location}")
        data_frames.append(read_table_for_DC_table(file_info, dc_config, deltatable))

    # Aggregate data
    if not data_frames:
        raise HTTPException(
            status_code=404,
            detail=f"No files found for data_collection: {data_collection_id} of workflow: {workflow_id}.",
        )

    logger.info(f"data_frames : {data_frames}")

    # Aggregate the dataframes
    aggregated_df = pl.concat(data_frames)

    # TODO: remove - just for testing
    # Add timestamp column
    aggregated_df = aggregated_df.with_columns(depictio_aggregation_time=pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    logger.info("aggregated_df")
    logger.info(aggregated_df)

    aggregated_df.write_delta(destination_file_name, mode="overwrite", storage_options=minio_storage_options, delta_write_options={"overwrite_schema": "True"})

    logger.info("Write complete to MinIO at destination: ", destination_file_name)

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

    logger.info("DeltaTableAggregated")
    logger.info(deltatable)

    if query_dt:
        logger.info("Updating existing DeltaTableAggregated")
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
        logger.info("Inserting new DeltaTableAggregated")
        logger.info(serialize_for_mongo(deltatable))
        deltatables_collection.insert_one(serialize_for_mongo(deltatable))

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
    logger.info(query)
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
