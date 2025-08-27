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
from depictio.api.v1.db import deltatables_collection, projects_collection, users_collection
from depictio.api.v1.endpoints.deltatables_endpoints.utils import precompute_columns_specs
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.s3 import polars_s3_config
from depictio.api.v1.utils import agg_functions
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.deltatables import (
    Aggregation,
    DeltaTableAggregated,
    UpsertDeltaTableAggregated,
)
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
    current_user: User = Depends(get_current_user),
):
    """
    Upsert a DeltaTableAggregated object.
    """

    data_collection_oid = payload.data_collection_id
    logger.info(f"Data Collection ID: {data_collection_oid}")
    # Construct the query to look into the projects_collection if the user is an admin or has permissions over the project by looking at the data_collection id
    query = {
        "$or": [
            {"permissions.owners._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
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
        dc_data = None
        for workflow in project.get("workflows", []):  # Iterate through workflows
            dc_data = next(
                (
                    dc
                    for dc in workflow.get("data_collections", [])
                    if str(dc["_id"]) == str(data_collection_oid)
                ),
                None,
            )
            if dc_data:  # Stop if found
                break

    # Validate that data collection was found
    if not dc_data:
        raise HTTPException(
            status_code=404,
            detail=f"Data collection with ID {data_collection_oid} not found in any project workflow.",
        )

    # read deltatable using polars
    df = pl.read_delta(payload.delta_table_location, storage_options=polars_s3_config)
    logger.info(f"DeltaTableAggregated read from MinIO at location: {payload.delta_table_location}")

    # Precompute columns specs
    results = precompute_columns_specs(df, agg_functions, dc_data)

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

    user = User.from_mongo(users_collection.find_one({"_id": ObjectId(current_user.id)}))  # type: ignore[invalid-argument-type]

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

    # Update DataCollection flexible_metadata with deltatable size if provided
    logger.info(
        f"🔍 DEBUG: Received payload.deltatable_size_bytes = {payload.deltatable_size_bytes}"
    )
    if payload.deltatable_size_bytes is not None:
        # Find the project and update the specific data collection's flexible_metadata
        logger.info(
            f"Updating DataCollection flexible_metadata with deltatable size: {payload.deltatable_size_bytes} bytes"
        )

        # First, initialize flexible_metadata if it's null
        logger.info("🔍 DEBUG: Ensuring flexible_metadata is initialized...")
        init_result = projects_collection.update_one(
            {
                "workflows.data_collections._id": data_collection_oid,
                "workflows.data_collections.flexible_metadata": None,
            },
            {"$set": {"workflows.$[workflow].data_collections.$[dc].flexible_metadata": {}}},
            array_filters=[
                {"workflow.data_collections": {"$exists": True}},
                {"dc._id": data_collection_oid},
            ],
        )
        logger.info(
            f"🔍 DEBUG: Initialization result - matched: {init_result.matched_count}, modified: {init_result.modified_count}"
        )

        # Now update the data collection with deltatable size information
        update_result = projects_collection.update_one(
            {
                "workflows.data_collections._id": data_collection_oid,
            },
            {
                "$set": {
                    "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_bytes": payload.deltatable_size_bytes,
                    "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_mb": round(
                        payload.deltatable_size_bytes / (1024 * 1024), 2
                    ),
                    "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_updated": datetime.now().isoformat(),
                }
            },
            array_filters=[
                {"workflow.data_collections": {"$exists": True}},
                {"dc._id": data_collection_oid},
            ],
        )
        logger.info(
            f"🔍 DEBUG: MongoDB update result - matched: {update_result.matched_count}, modified: {update_result.modified_count}"
        )
        logger.info("DataCollection flexible_metadata updated successfully")

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
        deltatables_collection.insert_one(deltatable.mongo())
    return {
        "message": "DeltaTableAggregated upserted successfully",
        "result": "success",
    }


@deltatables_endpoint_router.get("/get/{data_collection_id}")
async def get_deltatable(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
):
    """
    Fetch a DeltaTableAggregated object by data collection ID.
    """

    # First check if user has permission to access the data collection via project permissions
    pipeline = [
        # Match projects containing this data collection and with appropriate permissions
        {
            "$match": {
                "workflows.data_collections._id": ObjectId(data_collection_id),
                "$or": [
                    {"permissions.owners._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        # Unwind the workflows array
        {"$unwind": "$workflows"},
        # Unwind the data_collections array
        {"$unwind": "$workflows.data_collections"},
        # Match the specific data collection ID
        {"$match": {"workflows.data_collections._id": ObjectId(data_collection_id)}},
        # Return only the data collection
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]

    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    # Query to find deltatable associated with the data collection
    query = {"data_collection_id": data_collection_id}
    logger.info(f"Query: {query}")
    deltatable_cursor = list(deltatables_collection.find(query))
    # logger.info(f"Deltatable Cursor: {deltatable_cursor}")
    if len(list(deltatable_cursor)) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTableAggregated found for Data Collection ID {data_collection_id}.",
        )
    deltatables = list(deltatable_cursor)[0]
    # logger.info(f"Deltatables: {deltatables}")

    deltatables = sanitize_for_json(deltatables)
    # logger.info(f"Deltatables sanitized: {deltatables}")

    return convert_objectid_to_str(deltatables)
    # return convert_objectid_to_str(deltatables)


@deltatables_endpoint_router.post("/batch/exists")
async def batch_check_deltatables_exist(
    data_collection_ids: list[PyObjectId],
    current_user: str = Depends(get_user_or_anonymous),
):
    """
    Check existence of multiple deltatables in a single call.

    This endpoint eliminates the N+1 query pattern in design_draggable()
    by allowing batch checking of deltatable existence.

    Args:
        data_collection_ids: List of data collection IDs to check
        current_user: Current authenticated user

    Returns:
        Dict mapping data collection ID to existence status and location
    """
    logger.info(
        f"Batch checking deltatable existence for {len(data_collection_ids)} data collections"
    )

    # Single query to find all deltatables
    query = {"data_collection_id": {"$in": data_collection_ids}}
    deltatable_cursor = deltatables_collection.find(
        query, {"data_collection_id": 1, "delta_table_location": 1}
    )

    # Create mapping of found deltatables
    found_deltatables = {}
    for deltatable in deltatable_cursor:
        dc_id = str(deltatable["data_collection_id"])
        found_deltatables[dc_id] = deltatable.get("delta_table_location")

    # Build results for all requested IDs
    results = {}
    for dc_id in data_collection_ids:
        dc_id_str = str(dc_id)
        if dc_id_str in found_deltatables:
            results[dc_id_str] = {
                "exists": True,
                "delta_table_location": found_deltatables[dc_id_str],
            }
        else:
            results[dc_id_str] = {"exists": False, "delta_table_location": None}

    logger.info(
        f"Batch check complete: {sum(1 for r in results.values() if r['exists'])} of {len(data_collection_ids)} deltatables exist"
    )
    return results


@deltatables_endpoint_router.get("/specs/{data_collection_id}")
async def specs(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
):
    """
    Fetch columns list and specs from data collection
    # TODO: currently returns the last aggregation, need to fix with versioning
    """

    # First check if user has permission to access the data collection via project permissions
    pipeline = [
        # Match projects containing this data collection and with appropriate permissions
        {
            "$match": {
                "workflows.data_collections._id": ObjectId(data_collection_id),
                "$or": [
                    {"permissions.owners._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        # Unwind the workflows array
        {"$unwind": "$workflows"},
        # Unwind the data_collections array
        {"$unwind": "$workflows.data_collections"},
        # Match the specific data collection ID
        {"$match": {"workflows.data_collections._id": ObjectId(data_collection_id)}},
        # Return only the data collection
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]

    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    # Query to find deltatable associated with the data collection
    query = {"data_collection_id": data_collection_id}
    deltatable_cursor = deltatables_collection.find(query)
    deltatables = list(deltatable_cursor)[0]

    deltatables = sanitize_for_json(deltatables)
    logger.info(f"Deltatables sanitized: {deltatables}")

    # TODO - fix with versioning
    column_specs = convert_objectid_to_str(
        deltatables["aggregation"][-1]["aggregation_columns_specs"]
    )

    logger.info(f"Column specs: {column_specs}")

    return column_specs


@deltatables_endpoint_router.delete("/delete/{deltatable_id}")
async def delete_deltatable(
    deltatable_id: str,
    current_user: User = Depends(get_current_user),
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
        endpoint_url=settings.minio.endpoint,  # Ensure MinIO endpoint is used  # type: ignore[possibly-unbound-attribute]
        aws_access_key_id=settings.minio.access_key,  # type: ignore[possibly-unbound-attribute]
        aws_secret_access_key=settings.minio.secret_key,  # type: ignore[possibly-unbound-attribute]
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
