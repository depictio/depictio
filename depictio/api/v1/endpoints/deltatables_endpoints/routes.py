import hashlib
import math
from datetime import datetime

import boto3
import polars as pl
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import format_pydantic, logger
from depictio.api.v1.db import (deltatables_collection, projects_collection,
                                users_collection)
from depictio.api.v1.endpoints.deltatables_endpoints.utils import \
    precompute_columns_specs
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.s3 import polars_s3_config
from depictio.api.v1.utils import agg_functions
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.deltatables import (Aggregation,
                                                DeltaTableAggregated,
                                                UpsertDeltaTableAggregated)
from depictio.models.models.users import User

deltatables_endpoint_router = APIRouter()


def sanitize_for_json(obj):
    """
    Recursively sanitizes data for JSON serialization by replacing NaN and Infinity with None.
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(i) for i in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


@deltatables_endpoint_router.post("/upsert")
async def upsert_deltatable(
    payload: UpsertDeltaTableAggregated,
    current_user: str = Depends(get_current_user),
):
    """
    Upsert a DeltaTableAggregated object.
    """
    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    if not payload:
        raise HTTPException(
            status_code=400,
            detail="Payload is required",
        )
    if not payload.data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Data Collection ID is required",
        )
    if not payload.delta_table_location:
        raise HTTPException(
            status_code=400,
            detail="DeltaTableAggregated is required",
        )
    data_collection_oid = ObjectId(payload.data_collection_id)
    assert isinstance(data_collection_oid, ObjectId)
    # Construct the query to look into the projects_collection if the user is an admin or has permissions over the project by looking at the data_collection id
    query = {
        "$or": [
            {"permissions.owners._id": ObjectId(current_user.id)},
            {"permissions.is_admin": True},
        ],
        "workflows.data_collections._id": data_collection_oid,
    }
    logger.info(query)

    project = projects_collection.find_one(query)

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"No projects containing Data Collection id {data_collection_oid} found for the current user.",
        )
    else:
        # Search for the correct data collection inside workflows
        dc_config = None
        for workflow in project.get("workflows", []):  # Iterate through workflows
            dc_config = next(
                (
                    dc
                    for dc in workflow.get("data_collections", [])
                    if str(dc["_id"]) == str(data_collection_oid)
                ),
                None,
            )
            if dc_config:  # Stop if found
                break
            else:
                dc_config = dc_config.get("config", None)

    # read deltatable using polars
    df = pl.read_delta(payload.delta_table_location, storage_options=polars_s3_config)
    logger.info(f"DeltaTableAggregated read from MinIO at location: {payload.delta_table_location}")

    # Precompute columns specs
    results = precompute_columns_specs(df, agg_functions, dc_config)

    # 6. Compute hash
    # Compute hash rows (returns a Polars Series)
    hash_series = df.hash_rows(seed=0)

    # Ensure it's converted to bytes
    hash_bytes = hash_series.to_numpy().tobytes()

    # Compute SHA-256 hash
    hash_df = hashlib.sha256(hash_bytes).hexdigest()

    logger.info(f"Hash DataFrame: {hash_df}")

    # Generate final hash string
    final_hash = hashlib.sha256(
        f"{payload.delta_table_location}{datetime.now()}{hash_df}".encode()
    ).hexdigest()

    query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})
    if query_dt:
        logger.warning("DeltaTable exists")
        deltatable = DeltaTableAggregated.from_mongo(query_dt)
        version = (
            1 if not deltatable.aggregation else deltatable.aggregation[-1].aggregation_version + 1
        )
    else:
        logger.info("DeltaTable does not exist")
        logger.info(f"DeltaTableAggregated: {payload.delta_table_location}")
        deltatable = DeltaTableAggregated(
            data_collection_id=data_collection_oid,
            delta_table_location=str(payload.delta_table_location),
        )
        version = 1

    logger.info(f"DeltaTableAggregated: {format_pydantic(deltatable)}")

    user = User.from_mongo(users_collection.find_one({"_id": ObjectId(current_user.id)}))

    userbase = user.turn_to_userbase()
    logger.info(f"UserBase: {userbase}")

    deltatable.aggregation.append(
        Aggregation(
            aggregation_time=datetime.now(),
            aggregation_by=userbase,
            aggregation_version=version,
            aggregation_hash=final_hash,
            aggregation_columns_specs=results,
        )
    )
    logger.info(f"DeltaTableAggregated: {deltatable}")

    # deltatable = convert_objectid_to_str(deltatable.model_dump())
    # logger.info(f"DeltaTableAggregated Mongo: {deltatable}")

    # Query to find files associated with the data collection
    # Check if the DeltaTableAggregated exists, if not create a new one, else update the existing one
    logger.info("Checking if deltatable exists")
    if payload.update:
        logger.warning("DeltaTable exists, updating ...")
        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid},
            {
                "$set": {
                    "delta_table_location": payload.delta_table_location,
                    "aggregation": [a.mongo() for a in deltatable.aggregation],
                }
            },
            upsert=True,
        )
    else:
        # check if the DeltaTableAggregated exists
        query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})
        if query_dt:
            # stop
            raise HTTPException(
                status_code=400,
                detail=f"DeltaTableAggregated with id {data_collection_oid} already exists, use update=True to update it.",
            )

        logger.info("Inserting new DeltaTableAggregated")
        # logger.debug(serialize_for_mongo(deltatable))
        deltatables_collection.insert_one(deltatable.model_dump())
    return {
        "message": "DeltaTableAggregated upserted successfully",
        "result": "success",
    }


@deltatables_endpoint_router.get("/get/{data_collection_id}")
async def list_registered_files(
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )
    if not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Data Collection ID is required",
        )
    logger.info(f"Data Collection ID: {data_collection_id}")
    data_collection_oid = ObjectId(data_collection_id)
    logger.info(f"Data Collection OID: {data_collection_oid}")

    # Query to find deltatable associated with the data collection
    query = {"data_collection_id": data_collection_oid}
    logger.info(f"Query: {query}")
    deltatable_cursor = list(deltatables_collection.find(query))
    logger.info(f"Deltatable Cursor: {deltatable_cursor}")
    if len(list(deltatable_cursor)) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTableAggregated found for Data Collection ID {data_collection_oid}.",
        )
    deltatables = list(deltatable_cursor)[0]
    logger.info(f"Deltatables: {deltatables}")

    deltatables = sanitize_for_json(deltatables)
    logger.info(f"Deltatables sanitized: {deltatables}")

    return convert_objectid_to_str(deltatables)
    # return convert_objectid_to_str(deltatables)


@deltatables_endpoint_router.get("/specs/{data_collection_id}")
async def specs(
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch columns list and specs from data collection
    # TODO: currently returns the last aggregation, need to fix with versioning
    """

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )
    if not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Data Collection ID is required",
        )
    data_collection_oid = ObjectId(data_collection_id)
    # Query to find deltatable associated with the data collection
    query = {"data_collection_id": data_collection_oid}
    deltatable_cursor = deltatables_collection.find(query)
    deltatables = list(deltatable_cursor)[0]

    deltatables = sanitize_for_json(deltatables)
    logger.info(f"Deltatables sanitized: {deltatables}")

    # TODO - fix with versioning
    column_specs = deltatables["aggregation"][-1]["aggregation_columns_specs"]

    return column_specs


@deltatables_endpoint_router.delete("/delete/{deltatable_id}")
async def delete_deltatable(
    deltatable_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Delete all files from GridFS.
    """

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )
    if not deltatable_id:
        raise HTTPException(
            status_code=400,
            detail="Data Collection ID is required",
        )

    deltatable_oid = ObjectId(deltatable_id)
    user_oid = ObjectId(current_user.id)  # This should be the ObjectId

    # Retrieve data collection id from the deltatables_collection
    query = {"_id": deltatable_oid}
    deltatable = deltatables_collection.find_one(query)
    if not deltatable:
        raise HTTPException(
            status_code=404,
            detail=f"No deltatable with id {deltatable_oid} found.",
        )
    data_collection_oid = ObjectId(deltatable["data_collection_id"])

    # Delete S3 DeltaTable
    deltatable_location = deltatable["delta_table_location"].lstrip("/")  # Ensure no leading "/"
    bucket_name = settings.minio.bucket

    # Initialize S3 client
    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.minio.endpoint,  # Ensure MinIO endpoint is used
        aws_access_key_id=settings.minio.access_key,
        aws_secret_access_key=settings.minio.secret_key,
        region_name="us-east-1",  # MinIO default region
    )

    # Delete all objects in the Delta table directory
    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=deltatable_location)
        if "Contents" in response:
            objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]
            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})
            logger.info(f"Deleted DeltaTable at {deltatable_location}")
        else:
            logger.warning(f"DeltaTable not found at {deltatable_location}")
    except ClientError as e:
        logger.error(f"Failed to delete S3 objects: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete S3 objects.")

    # Check if the user is an admin or has permissions over the project by looking at the data_collection id by looking at the projects_collection
    query = {
        "$or": [{"permissions.owners._id": user_oid}, {"permissions.is_admin": True}],
        "data_collections._id": data_collection_oid,
    }
    logger.info(query)
    if not projects_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {deltatable_oid} found for the current user.",
        )

    # Delete the DeltaTableAggregated
    deltatables_collection.delete_one({"_id": deltatable_oid})
    return {"message": f"DeltaTableAggregated with id {deltatable_oid} deleted successfully."}
