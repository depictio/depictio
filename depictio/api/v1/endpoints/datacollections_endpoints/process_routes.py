"""
Endpoint for processing data collections from S3 source files.

Provides a single endpoint that reads a source file (CSV, Parquet, etc.)
directly from S3, converts it to a Delta Lake table, and upserts the
metadata in MongoDB. Designed for external service integration where
data is pushed to S3 and Depictio needs to create the Delta table.
"""

import hashlib
from datetime import datetime

import polars as pl
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import deltatables_collection, projects_collection, users_collection
from depictio.api.v1.endpoints.deltatables_endpoints.utils import precompute_columns_specs
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.s3 import polars_s3_config
from depictio.api.v1.utils import agg_functions
from depictio.models.models.deltatables import Aggregation, DeltaTableAggregated
from depictio.models.models.users import User

process_s3_router = APIRouter()


class ProcessS3Request(BaseModel):
    """Request model for processing a data collection from an S3 source file.

    Attributes:
        s3_source_path: Full S3 path to the source file (e.g. 's3://bucket/path/file.csv').
        overwrite: Whether to overwrite an existing Delta table. Defaults to True.
        file_format: Optional file format override. If None, uses the DC config format.
    """

    s3_source_path: str
    overwrite: bool = True
    file_format: str | None = None


class ProcessS3Response(BaseModel):
    """Response model for the process-s3 endpoint.

    Attributes:
        result: Either 'success' or 'error'.
        message: Human-readable description of the outcome.
        delta_table_location: S3 path of the created Delta table.
        rows: Number of rows in the resulting table.
        columns: Number of columns in the resulting table.
    """

    result: str
    message: str
    delta_table_location: str | None = None
    rows: int | None = None
    columns: int | None = None


def _find_dc_in_project(project: dict, data_collection_oid: ObjectId) -> dict | None:
    """Find a data collection within a project's workflows.

    Args:
        project: MongoDB project document.
        data_collection_oid: ObjectId of the data collection to find.

    Returns:
        The data collection dict if found, None otherwise.
    """
    for workflow in project.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            if dc["_id"] == data_collection_oid:
                return dc
    return None


def _read_source_from_s3(
    s3_path: str,
    file_format: str,
    polars_kwargs: dict,
) -> pl.DataFrame:
    """Read a source file from S3 into a Polars DataFrame.

    Supports CSV, TSV, TXT, Parquet, Feather, and Excel formats.

    Args:
        s3_path: Full S3 path to the source file.
        file_format: File format string (e.g. 'csv', 'parquet').
        polars_kwargs: Additional keyword arguments for the Polars reader.

    Returns:
        Materialized Polars DataFrame with an aggregation_time column added.

    Raises:
        HTTPException: If the file format is unsupported or reading fails.
    """
    try:
        if file_format in ("csv", "tsv", "txt"):
            lf = pl.scan_csv(s3_path, storage_options=polars_s3_config, **polars_kwargs)
        elif file_format == "parquet":
            lf = pl.scan_parquet(s3_path, storage_options=polars_s3_config, **polars_kwargs)
        elif file_format == "feather":
            lf = pl.scan_ipc(s3_path, storage_options=polars_s3_config, **polars_kwargs)
        elif file_format in ("xls", "xlsx"):
            # Excel doesn't support lazy scanning — read eagerly
            df = pl.read_excel(s3_path, **polars_kwargs)
            df = df.with_columns(
                pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).alias("aggregation_time")
            )
            return df
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format: {file_format}",
            )

        # Add aggregation timestamp and materialize
        lf = lf.with_columns(
            pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).alias("aggregation_time")
        )
        return lf.collect()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read source file from S3: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read file from S3 at '{s3_path}': {e}",
        )


def _upsert_deltatable_metadata(
    data_collection_oid: ObjectId,
    delta_table_location: str,
    df: pl.DataFrame,
    dc_data: dict,
    current_user: User,
    update: bool,
) -> None:
    """Upsert DeltaTableAggregated metadata in MongoDB.

    Computes column specs, hash, and aggregation info, then creates or
    updates the DeltaTableAggregated document and DC size metadata.

    Args:
        data_collection_oid: ObjectId of the data collection.
        delta_table_location: S3 path of the Delta table.
        df: The materialized DataFrame (for hash and column spec computation).
        dc_data: Raw data collection dict from MongoDB.
        current_user: Authenticated user performing the operation.
        update: Whether to update an existing record.

    Raises:
        HTTPException: If the deltatable already exists and update is False.
    """
    # Compute hash from DataFrame contents
    hash_series = df.hash_rows(seed=0)
    hash_bytes = hash_series.to_numpy().tobytes()
    hash_df = hashlib.sha256(hash_bytes).hexdigest()
    final_hash = hashlib.sha256(
        f"{delta_table_location}{datetime.now()}{hash_df}".encode()
    ).hexdigest()

    # Compute column specs
    column_specs = precompute_columns_specs(df, agg_functions, dc_data)

    # Get or create DeltaTableAggregated
    existing_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})
    if existing_dt:
        deltatable = DeltaTableAggregated.from_mongo(existing_dt)
        version = (
            1 if not deltatable.aggregation else deltatable.aggregation[-1].aggregation_version + 1
        )
    else:
        deltatable = DeltaTableAggregated(
            data_collection_id=data_collection_oid,
            delta_table_location=delta_table_location,
        )
        version = 1

    # Get user info for aggregation record
    user_doc = users_collection.find_one({"_id": ObjectId(current_user.id)})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found in database.")
    user = User.from_mongo(user_doc)
    userbase = user.turn_to_userbase()

    deltatable.aggregation.append(
        Aggregation(
            aggregation_time=datetime.now(),
            aggregation_by=userbase,
            aggregation_version=version,
            aggregation_hash=final_hash,
            aggregation_columns_specs=column_specs,
        )
    )

    # Calculate size
    size_bytes = int(df.estimated_size("b"))

    # Update size in project's DC flexible_metadata
    _update_dc_size_metadata(data_collection_oid, size_bytes)

    # Upsert the DeltaTableAggregated document
    if update or existing_dt:
        update_doc: dict = {
            "$set": {
                "delta_table_location": delta_table_location,
                "aggregation": [a.mongo() for a in deltatable.aggregation],
            }
        }
        update_doc["$set"]["flexible_metadata.deltatable_size_bytes"] = size_bytes
        update_doc["$set"]["flexible_metadata.deltatable_size_mb"] = round(
            size_bytes / (1024 * 1024), 2
        )
        update_doc["$set"]["flexible_metadata.deltatable_size_updated"] = datetime.now().isoformat()

        # Ensure flexible_metadata is not null before setting nested fields
        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid, "flexible_metadata": None},
            {"$set": {"flexible_metadata": {}}},
        )

        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid},
            update_doc,
            upsert=True,
        )
    else:
        deltatables_collection.insert_one(deltatable.mongo())

        # Set size metadata on newly inserted doc
        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid, "flexible_metadata": None},
            {"$set": {"flexible_metadata": {}}},
        )
        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid},
            {
                "$set": {
                    "flexible_metadata.deltatable_size_bytes": size_bytes,
                    "flexible_metadata.deltatable_size_mb": round(size_bytes / (1024 * 1024), 2),
                    "flexible_metadata.deltatable_size_updated": datetime.now().isoformat(),
                }
            },
        )


def _update_dc_size_metadata(data_collection_oid: ObjectId, size_bytes: int) -> None:
    """Update the data collection's size metadata in the project document.

    Args:
        data_collection_oid: ObjectId of the data collection.
        size_bytes: Size of the Delta table in bytes.
    """
    # Ensure flexible_metadata field exists
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

    # Set size values
    projects_collection.update_one(
        {"workflows.data_collections._id": data_collection_oid},
        {
            "$set": {
                "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_bytes": size_bytes,
                "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_mb": round(
                    size_bytes / (1024 * 1024), 2
                ),
                "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_updated": datetime.now().isoformat(),
            }
        },
        array_filters=[
            {"workflow.data_collections": {"$exists": True}},
            {"dc._id": data_collection_oid},
        ],
    )


@process_s3_router.post("/{data_collection_id}/process-s3", response_model=ProcessS3Response)
async def process_dc_from_s3(
    data_collection_id: str,
    request: ProcessS3Request,
    current_user: User = Depends(get_current_user),
) -> ProcessS3Response:
    """Process a data collection by reading a source file from S3.

    Reads the source file from S3, converts it to a Delta Lake table stored
    at ``s3://{bucket}/{dc_id}/``, and upserts the metadata in MongoDB.
    This endpoint is designed for external services that push data to S3
    and need Depictio to create/update the corresponding Delta table.

    Args:
        data_collection_id: The data collection ID to process.
        request: Request body with S3 source path and options.
        current_user: Authenticated user (injected via dependency).

    Returns:
        ProcessS3Response with result status and table shape info.

    Raises:
        HTTPException: On validation, permission, or processing errors.
    """
    # Validate S3 path format
    if not request.s3_source_path.startswith("s3://"):
        raise HTTPException(
            status_code=400,
            detail="s3_source_path must start with 's3://'",
        )

    # Validate DC access
    data_collection_oid = ObjectId(data_collection_id)
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
            detail=f"Data collection {data_collection_id} not found or access denied.",
        )

    # Find DC config
    dc_data = _find_dc_in_project(project, data_collection_oid)
    if not dc_data:
        raise HTTPException(
            status_code=404,
            detail=f"Data collection {data_collection_id} not found in project workflows.",
        )

    # Extract file format and polars kwargs from DC config
    dc_props = dc_data.get("config", {}).get("dc_specific_properties", {})
    file_format = (request.file_format or dc_props.get("format", "csv")).lower()
    polars_kwargs = dict(dc_props.get("polars_kwargs", {}))

    logger.info(
        f"Processing DC {data_collection_id} from S3: {request.s3_source_path} "
        f"(format={file_format}, overwrite={request.overwrite})"
    )

    # Read source file from S3
    df = _read_source_from_s3(request.s3_source_path, file_format, polars_kwargs)
    logger.info(f"Read {df.shape[0]} rows, {df.shape[1]} columns from {request.s3_source_path}")

    # Write Delta table to S3
    destination = f"s3://{settings.minio.bucket}/{data_collection_id}"

    try:
        df.write_delta(
            destination,
            storage_options=polars_s3_config,
            delta_write_options={"schema_mode": "overwrite"},
            mode="overwrite",
        )
        logger.info(f"Delta table written to {destination}")
    except Exception as e:
        logger.error(f"Failed to write Delta table: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write Delta table to S3: {e}",
        )

    # Upsert metadata in MongoDB
    try:
        _upsert_deltatable_metadata(
            data_collection_oid=data_collection_oid,
            delta_table_location=destination,
            df=df,
            dc_data=dc_data,
            current_user=current_user,
            update=request.overwrite,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upsert deltatable metadata: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Delta table written to S3 but metadata upsert failed: {e}",
        )

    return ProcessS3Response(
        result="success",
        message=f"Processed {df.shape[0]} rows, {df.shape[1]} columns from {request.s3_source_path}",
        delta_table_location=destination,
        rows=df.shape[0],
        columns=df.shape[1],
    )
