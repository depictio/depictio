"""
DeltaTables API endpoints for managing data collection delta tables.

Provides CRUD operations for DeltaTableAggregated objects including
upsert, fetch, batch existence checks, and shape queries.
"""

import hashlib
import math
from datetime import datetime

import boto3
import polars as pl
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
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

    Args:
        payload: Delta table configuration and location.
        current_user: Authenticated user making the request.

    Returns:
        Success message on completion.

    Raises:
        HTTPException: If project or data collection not found.
    """
    data_collection_oid = payload.data_collection_id

    query = {
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.is_admin": True},
        ],
        "workflows.data_collections._id": data_collection_oid,
    }

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"No projects containing Data Collection id {data_collection_oid} found for the current user.",
        )

    dc_data = None
    for workflow in project.get("workflows", []):
        dc_data = next(
            (
                dc
                for dc in workflow.get("data_collections", [])
                if str(dc["_id"]) == str(data_collection_oid)
            ),
            None,
        )
        if dc_data:
            break

    if not dc_data:
        raise HTTPException(
            status_code=404,
            detail=f"Data collection with ID {data_collection_oid} not found in any project workflow.",
        )

    df = pl.read_delta(payload.delta_table_location, storage_options=polars_s3_config)
    results = precompute_columns_specs(df, agg_functions, dc_data)

    hash_series = df.hash_rows(seed=0)
    hash_bytes = hash_series.to_numpy().tobytes()
    hash_df = hashlib.sha256(hash_bytes).hexdigest()
    final_hash = hashlib.sha256(
        f"{payload.delta_table_location}{datetime.now()}{hash_df}".encode()
    ).hexdigest()

    query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})
    if query_dt:
        deltatable = DeltaTableAggregated.from_mongo(query_dt)
        version = (
            1 if not deltatable.aggregation else deltatable.aggregation[-1].aggregation_version + 1
        )
    else:
        deltatable = DeltaTableAggregated(
            data_collection_id=data_collection_oid,
            delta_table_location=str(payload.delta_table_location),
        )
        version = 1

    user = User.from_mongo(users_collection.find_one({"_id": ObjectId(current_user.id)}))  # type: ignore[invalid-argument-type]
    userbase = user.turn_to_userbase()

    deltatable.aggregation.append(
        Aggregation(
            aggregation_time=datetime.now(),
            aggregation_by=userbase,
            aggregation_version=version,
            aggregation_hash=final_hash,
            aggregation_columns_specs=results,
        )
    )

    if payload.deltatable_size_bytes is not None:
        projects_collection.update_one(
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

        projects_collection.update_one(
            {"workflows.data_collections._id": data_collection_oid},
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

    if payload.update:
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
        query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})
        if query_dt:
            raise HTTPException(
                status_code=400,
                detail=f"DeltaTableAggregated with id {data_collection_oid} already exists, use update=True to update it.",
            )
        deltatables_collection.insert_one(deltatable.mongo())

    return {"message": "DeltaTableAggregated upserted successfully", "result": "success"}


def _build_permission_pipeline(data_collection_id: PyObjectId, user_id) -> list[dict]:
    """Build MongoDB aggregation pipeline for permission checking."""
    return [
        {
            "$match": {
                "workflows.data_collections._id": ObjectId(data_collection_id),
                "$or": [
                    {"permissions.owners._id": user_id},
                    {"permissions.viewers._id": user_id},
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        {"$unwind": "$workflows"},
        {"$unwind": "$workflows.data_collections"},
        {"$match": {"workflows.data_collections._id": ObjectId(data_collection_id)}},
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]


@deltatables_endpoint_router.get("/get/{data_collection_id}")
async def get_deltatable(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
):
    """
    Fetch a DeltaTableAggregated object by data collection ID.

    Args:
        data_collection_id: The data collection identifier.
        current_user: Authenticated or anonymous user.

    Returns:
        DeltaTableAggregated data with ObjectIds converted to strings.

    Raises:
        HTTPException: If data collection not found or access denied.
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user.id)  # type: ignore[possibly-unbound-attribute]
    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatable_cursor = list(
        deltatables_collection.find({"data_collection_id": data_collection_id})
    )
    if not deltatable_cursor:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTableAggregated found for Data Collection ID {data_collection_id}.",
        )

    return convert_objectid_to_str(sanitize_for_json(deltatable_cursor[-1]))


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
        data_collection_ids: List of data collection IDs to check.
        current_user: Current authenticated user.

    Returns:
        Dict mapping data collection ID to existence status and location.
    """
    deltatable_cursor = deltatables_collection.find(
        {"data_collection_id": {"$in": data_collection_ids}},
        {"data_collection_id": 1, "delta_table_location": 1},
    )

    found_deltatables = {
        str(dt["data_collection_id"]): dt.get("delta_table_location") for dt in deltatable_cursor
    }

    return {
        str(dc_id): {
            "exists": str(dc_id) in found_deltatables,
            "delta_table_location": found_deltatables.get(str(dc_id)),
        }
        for dc_id in data_collection_ids
    }


@deltatables_endpoint_router.get("/specs/{data_collection_id}")
async def specs(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
):
    """
    Fetch columns list and specs from data collection.

    Args:
        data_collection_id: The data collection identifier.
        current_user: Authenticated or anonymous user.

    Returns:
        Column specifications from the latest aggregation.

    Raises:
        HTTPException: If data collection not found or access denied.

    Note:
        Currently returns the last aggregation; versioning support planned.
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user.id)  # type: ignore[possibly-unbound-attribute]
    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatable_cursor = deltatables_collection.find({"data_collection_id": data_collection_id})
    deltatables = sanitize_for_json(list(deltatable_cursor)[0])

    return convert_objectid_to_str(deltatables["aggregation"][-1]["aggregation_columns_specs"])


@deltatables_endpoint_router.get("/shape/{data_collection_id}")
async def get_shape(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
):
    """
    Get shape information (number of rows and columns) for a data collection.

    Args:
        data_collection_id: The data collection identifier.
        current_user: Authenticated or anonymous user.

    Returns:
        Dictionary with num_rows and num_columns.

    Raises:
        HTTPException: If data collection not found or delta table read fails.
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user.id)  # type: ignore[possibly-unbound-attribute]
    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatables_list = list(deltatables_collection.find({"data_collection_id": data_collection_id}))
    if not deltatables_list:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTable found for Data Collection ID {data_collection_id}.",
        )

    delta_table_location = deltatables_list[-1].get("delta_table_location")
    if not delta_table_location:
        raise HTTPException(
            status_code=404, detail="Delta table location not found in deltatable document."
        )

    try:
        df = pl.scan_delta(delta_table_location, storage_options=polars_s3_config).collect()
        num_rows, num_columns = df.shape
        return {"num_rows": num_rows, "num_columns": num_columns}
    except Exception as e:
        logger.error(f"Error reading delta table shape: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read delta table shape: {e}")


@deltatables_endpoint_router.delete("/delete/{deltatable_id}")
async def delete_deltatable(
    deltatable_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Delete a DeltaTableAggregated and its S3 objects.

    Args:
        deltatable_id: The deltatable identifier to delete.
        current_user: Authenticated user making the request.

    Returns:
        Success message on completion.

    Raises:
        HTTPException: If deltatable not found or S3 deletion fails.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not deltatable_id:
        raise HTTPException(status_code=400, detail="Data Collection ID is required")

    deltatable_oid = ObjectId(deltatable_id)
    user_oid = ObjectId(current_user.id)

    deltatable = deltatables_collection.find_one({"_id": deltatable_oid})
    if not deltatable:
        raise HTTPException(
            status_code=404, detail=f"No deltatable with id {deltatable_oid} found."
        )

    data_collection_oid = ObjectId(deltatable["data_collection_id"])
    deltatable_location = deltatable["delta_table_location"].lstrip("/")
    bucket_name = settings.minio.bucket

    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.minio.endpoint,  # type: ignore[possibly-unbound-attribute]
        aws_access_key_id=settings.minio.access_key,  # type: ignore[possibly-unbound-attribute]
        aws_secret_access_key=settings.minio.secret_key,  # type: ignore[possibly-unbound-attribute]
        region_name="us-east-1",
    )

    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=deltatable_location)
        if "Contents" in response:
            objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]
            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})
    except ClientError as e:
        logger.error(f"Failed to delete S3 objects: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete S3 objects.")

    query = {
        "$or": [{"permissions.owners._id": user_oid}, {"permissions.is_admin": True}],
        "data_collections._id": data_collection_oid,
    }
    if not projects_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {deltatable_oid} found for the current user.",
        )

    deltatables_collection.delete_one({"_id": deltatable_oid})
    return {"message": f"DeltaTableAggregated with id {deltatable_oid} deleted successfully."}
