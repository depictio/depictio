from datetime import datetime
import hashlib
import os
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
import polars as pl

from depictio.api.v1.configs.config import settings, logger
from depictio.api.v1.db import workflows_collection, files_collection, users_collection, deltatables_collection
from depictio.api.v1.endpoints.deltatables_endpoints.utils import get_s3_folder_size, precompute_columns_specs, read_table_for_DC_table
from depictio.api.v1.s3 import minio_storage_options
from depictio.api.v1.endpoints.deltatables_endpoints.models import Aggregation, DeltaTableAggregated
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    serialize_for_mongo,
    agg_functions,
)


deltatables_endpoint_router = APIRouter()


@deltatables_endpoint_router.get("/get/{workflow_id}/{data_collection_id}")
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
        current_user.id,
        workflow_id,
        data_collection_id,
    )

    # Query to find deltatable associated with the data collection
    query = {"data_collection_id": data_collection_oid}
    deltatable_cursor = deltatables_collection.find(query)
    deltatables = list(deltatable_cursor)[0]
    # logger.info(deltatable)

    return convert_objectid_to_str(deltatables)


@deltatables_endpoint_router.get("/specs/{workflow_id}/{data_collection_id}")
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
        current_user.id,
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

    if not workflow_id or not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Workflow ID and Data Collection ID are required",
        )

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    # Use the utility function to validate and retrieve necessary info
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

    # Extract the data_collection_config from the workflow
    dc_config = data_collection.config

    # Assert type of data_collection_config is Table
    assert dc_config.type == "Table", "Data collection type must be Table"
    dc_config = convert_objectid_to_str(dc_config.mongo())

    logger.debug(f"Data Collection Config: {dc_config}")
    logger.debug(f"Data Collection ID: {data_collection_oid}")

    # Using the config, find files associated with the data collection
    files = list(
        files_collection.find(
            {
                "data_collection._id": data_collection_oid,
            }
        )
    )

    logger.debug(f"Len of Files: {len(files)}")

    # Assert that files is a list and not empty
    assert isinstance(files, list)
    assert len(files) > 0

    # Convert the files to File objects
    files = [File.from_mongo(file) for file in files]

    # Create a DeltaTableAggregated object
    destination_file_key = f"{user_oid}/{workflow_oid}/{data_collection_oid}/" 
    destination_file_name = f"s3://{settings.minio.bucket}/{destination_file_key}" 
    # destination_file_name = f"{settings.minio.data_dir}/{settings.minio.bucket}/{user_oid}/{workflow_oid}/{data_collection_oid}/"  # Destination path in MinIO
    # os.makedirs(destination_file_name, exist_ok=True)

    # Get the user object to use as aggregation_by
    user = UserBase.from_mongo(users_collection.find_one({"_id": user_oid}))

    # Check if a DeltaTableAggregated already exists in the deltatables_collection
    query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})

    # Check if the DeltaTableAggregated exists, if not create a new one, else update the existing one
    logger.info("Checking if deltatable exists")
    if query_dt:
        logger.warn("DeltaTable exists")
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
        logger.debug(f"Reading file: {file_info.file_location}")
        data_frames.append(read_table_for_DC_table(file_info, dc_config, deltatable))

    # Aggregate data
    if not data_frames:
        raise HTTPException(
            status_code=404,
            detail=f"No files found for data_collection: {data_collection_id} of workflow: {workflow_id}.",
        )

    logger.debug(f"data_frames : {data_frames}")

    # Aggregate the dataframes
    aggregated_df = pl.concat(data_frames)

    # TODO: remove - just for testing
    # Add timestamp column
    aggregated_df = aggregated_df.with_columns(depictio_aggregation_time=pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    logger.debug(f"aggregated_df : {aggregated_df}")

    aggregated_df.write_delta(destination_file_name, mode="overwrite", storage_options=minio_storage_options, delta_write_options={"schema_mode": "overwrite"})

    logger.info(f"Write complete to MinIO at destination: {destination_file_name}")

    # Precompute columns specs
    results = precompute_columns_specs(aggregated_df, agg_functions)

    # Compute the hash of the aggregated data using the filename, time, and size
    # filesize = os.path.getsize(destination_file_name)

    # Retrieve the bucket name from settings
    bucket_name = settings.minio.bucket

    # Get the size of the object in the bucket
    try:
        filesize = get_s3_folder_size(bucket_name, destination_file_key)
        logger.info(f"Size of the object '{destination_file_key}' in bucket '{bucket_name}' is {filesize} bytes.")
    except HTTPException as e:
        logger.error(f"Failed to get the size of the object: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get the size of the object.")

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

    logger.debug(f"DeltaTableAggregated : {deltatable}")

    if query_dt:
        logger.warn("Updating existing DeltaTableAggregated")
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
        logger.debug(serialize_for_mongo(deltatable))
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
    user_oid = ObjectId(current_user.id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)
    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners._id": user_oid,
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
