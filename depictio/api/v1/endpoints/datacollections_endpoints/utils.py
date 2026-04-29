import os
import shutil
import tempfile
import time
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import projects_collection, tokens_collection
from depictio.models.models.base import PyObjectId, convert_objectid_to_str


def generate_join_dict(workflow: dict, project: dict | None = None) -> dict[str, dict[str, dict]]:
    """
    Generate join dictionary from project-level joins (new approach).

    Args:
        workflow: Workflow dict with data_collections
        project: Project dict with joins[] array (optional for backward compatibility)

    Returns:
        {
            "workflow_id": {
                "result_dc_id": {
                    "how": "inner",
                    "on_columns": ["col1", "col2"],
                    "dc_tags": ["left_dc_tag", "right_dc_tag"],
                    "join_name": "penguins_complete",
                    "description": "Complete penguin dataset"
                }
            }
        }
    """
    workflow_id = str(workflow.get("_id", workflow.get("id", "")))
    workflow_name = workflow.get("name", "")
    join_details_map: dict[str, dict[str, dict]] = {workflow_id: {}}

    # If no project provided or no joins defined, return empty
    if not project or "joins" not in project:
        return join_details_map

    project_joins = project.get("joins", [])

    for join_def in project_joins:
        join_name = join_def.get("name", "unnamed")
        join_workflow_name = join_def.get("workflow_name", "")
        result_dc_id = join_def.get("result_dc_id")

        # Skip if join is for a different workflow
        if join_workflow_name and join_workflow_name != workflow_name:
            continue

        # Skip if join hasn't been executed yet (no result_dc_id)
        if not result_dc_id:
            logger.warning(f"Join '{join_name}' skipped: no result_dc_id (join not executed)")
            continue

        # Create join entry with result_dc_id as the key
        join_details_map[workflow_id][str(result_dc_id)] = {
            "how": join_def.get("how", "inner"),
            "on_columns": join_def.get("on_columns", []),
            "dc_tags": [join_def.get("left_dc", ""), join_def.get("right_dc", "")],
            "join_name": join_name,
            "description": join_def.get("description", ""),
        }
        logger.info(f"Added join '{join_name}' to result dict")

    return join_details_map


async def _get_data_collection_specs(data_collection_id: PyObjectId, current_user) -> dict:
    """Core function to retrieve data collection specifications.

    Args:
        data_collection_id: ObjectId of the data collection
        current_user: User object with permissions

    Returns:
        dict: Data collection specifications

    Raises:
        HTTPException: If data collection not found or access denied
    """
    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Use MongoDB aggregation to directly retrieve the specific data collection
    pipeline = [
        # Match projects containing this collection and with appropriate permissions
        {
            "$match": {
                "workflows.data_collections._id": data_collection_oid,
                "$or": [
                    {"permissions.owners._id": current_user.id},
                    {"permissions.viewers._id": current_user.id},
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
        {"$match": {"workflows.data_collections._id": data_collection_oid}},
        # Return only the data collection
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]

    result = list(projects_collection.aggregate(pipeline))

    if not result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    return convert_objectid_to_str(result[0])


async def _delete_data_collection_by_id(data_collection_id: str, current_user) -> dict:
    """Core function to delete a data collection by its ID.

    Args:
        data_collection_id: String ID of the data collection
        current_user: User object with permissions

    Returns:
        dict: Success message

    Raises:
        HTTPException: If data collection not found or access denied
    """
    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Find the project containing this data collection
    project = projects_collection.find_one(
        {
            "workflows.data_collections._id": data_collection_oid,
            "$or": [
                {"permissions.owners._id": current_user.id},
                {"permissions.viewers._id": current_user.id},
            ],
        }
    )

    if not project:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied")

    # Remove the data collection from the project
    result = projects_collection.update_one(
        {"_id": project["_id"]},
        {"$pull": {"workflows.$[].data_collections": {"_id": data_collection_oid}}},
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Data collection not found")

    # Cleanup associated S3 data and Delta tables
    await _cleanup_s3_delta_table(data_collection_id)

    return {"message": "Data collection deleted successfully"}


async def _update_data_collection_name(
    data_collection_id: str, new_name: str, current_user
) -> dict:
    """Core function to update data collection name.

    Args:
        data_collection_id: String ID of the data collection
        new_name: New name for the data collection
        current_user: User object with permissions

    Returns:
        dict: Success message

    Raises:
        HTTPException: If data collection not found or access denied
    """
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")

    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Find the project containing this data collection
    project = projects_collection.find_one(
        {
            "workflows.data_collections._id": data_collection_oid,
            "$or": [
                {"permissions.owners._id": current_user.id},
                {"permissions.viewers._id": current_user.id},
            ],
        }
    )

    if not project:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied")

    # Update the data collection name in the project
    result = projects_collection.update_one(
        {"_id": project["_id"], "workflows.data_collections._id": data_collection_oid},
        {"$set": {"workflows.$[].data_collections.$[dc].data_collection_tag": new_name}},
        array_filters=[{"dc._id": data_collection_oid}],
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Data collection not found")

    return {"message": f"Data collection name updated to '{new_name}' successfully"}


async def _update_dc_specific_properties(
    data_collection_id: str, properties: dict, current_user
) -> dict:
    """Update dc_specific_properties fields for a data collection.

    Performs a partial update: only the keys present in *properties* are
    modified; existing keys that are not mentioned are left untouched.

    Args:
        data_collection_id: String ID of the data collection.
        properties: Dict of field-name → value to set inside dc_specific_properties.
        current_user: Authenticated user object.

    Returns:
        dict with a success message.

    Raises:
        HTTPException: 400/404 on bad input or missing DC.
    """
    if not properties:
        raise HTTPException(status_code=400, detail="properties dict must not be empty")

    try:
        dc_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    project = projects_collection.find_one(
        {
            "workflows.data_collections._id": dc_oid,
            "$or": [
                {"permissions.owners._id": current_user.id},
                {"permissions.viewers._id": current_user.id},
            ],
        }
    )
    if not project:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied")

    # Build $set paths for each property key
    set_fields = {
        f"workflows.$[].data_collections.$[dc].config.dc_specific_properties.{key}": value
        for key, value in properties.items()
    }

    result = projects_collection.update_one(
        {"_id": project["_id"], "workflows.data_collections._id": dc_oid},
        {"$set": set_fields},
        array_filters=[{"dc._id": dc_oid}],
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Data collection not found or no changes applied"
        )

    logger.info(
        f"Updated dc_specific_properties for DC {data_collection_id}: {list(properties.keys())}"
    )
    return {"message": "dc_specific_properties updated successfully"}


async def _cleanup_s3_delta_table(data_collection_id: str) -> None:
    """Core function to cleanup S3 Delta table objects.

    Args:
        data_collection_id: String ID of the data collection
    """
    try:
        import boto3
        from botocore.exceptions import ClientError

        # Initialize S3 client for MinIO
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.minio.endpoint_url,
            aws_access_key_id=settings.minio.aws_access_key_id,
            aws_secret_access_key=settings.minio.aws_secret_access_key,
            region_name="us-east-1",
        )

        # Delta table is stored with data_collection_id as the key
        delta_table_prefix = data_collection_id
        bucket_name = settings.minio.bucket

        # Delete all objects in the Delta table directory
        logger.info(f"Deleting Delta table for data collection: {data_collection_id}")
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=delta_table_prefix)

        if "Contents" in response:
            objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]
            if objects_to_delete:
                s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})
                logger.info(
                    f"Deleted {len(objects_to_delete)} Delta table objects for data collection {data_collection_id}"
                )
            else:
                logger.info(
                    f"No Delta table objects found for data collection {data_collection_id}"
                )
        else:
            logger.info(f"No Delta table found for data collection {data_collection_id}")

    except ClientError as e:
        logger.error(
            f"Failed to delete S3 Delta table objects for data collection {data_collection_id}: {e}"
        )
        # Don't fail the entire operation if S3 cleanup fails, just log the error
    except Exception as e:
        logger.error(
            f"Unexpected error during S3 cleanup for data collection {data_collection_id}: {e}"
        )
        # Don't fail the entire operation if S3 cleanup fails, just log the error


_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _build_polars_kwargs(
    file_format: str,
    separator: str,
    custom_separator: str | None,
    compression: str,
    has_header: bool,
) -> dict[str, Any]:
    """Mirror dash/api_calls._build_polars_kwargs — kept here so the API
    side has no Dash dependency."""
    polars_kwargs: dict[str, Any] = {}
    if file_format in ("csv", "tsv"):
        if separator == "custom" and custom_separator:
            polars_kwargs["separator"] = custom_separator
        elif separator == "\t":
            polars_kwargs["separator"] = "\t"
        elif separator in (",", ";", "|"):
            polars_kwargs["separator"] = separator
        else:
            polars_kwargs["separator"] = "," if file_format == "csv" else "\t"
        polars_kwargs["has_header"] = has_header
    if compression and compression != "none":
        polars_kwargs["compression"] = compression
    return polars_kwargs


def _user_can_edit_project(project_dict: dict, user_id: ObjectId, is_admin: bool) -> bool:
    if is_admin:
        return True
    perms = project_dict.get("permissions") or {}
    for level in ("owners", "editors"):
        for entry in perms.get(level, []) or []:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("_id") or entry.get("id")
            if entry_id and ObjectId(str(entry_id)) == user_id:
                return True
    return False


async def _create_dc_from_upload(
    *,
    project_id: str,
    name: str,
    description: str,
    data_type: str,
    file_format: str,
    separator: str,
    custom_separator: str | None,
    compression: str,
    has_header: bool,
    file_bytes: bytes,
    filename: str,
    current_user,
) -> dict:
    """Create a basic-project data collection from an uploaded file.

    Mirrors the legacy Dash flow at dash/api_calls.py:api_call_create_data_collection
    but runs entirely server-side: no base64 round-trip, no second API hop.
    Steps: validate → build models → push workflow into project doc →
    scan files → process (aggregate to delta) → return ids.
    """
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload.")
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(file_bytes) / (1024 * 1024):.1f}MB > 50MB limit).",
        )
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Data collection name is required.")

    # Localised imports — keep API import-time cheap and avoid pulling the
    # CLI graph until someone actually uploads.
    from depictio.cli.cli.utils.helpers import process_data_collection_helper
    from depictio.models.models.cli import CLIConfig, UserBaseCLIConfig
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanSingle,
    )
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    try:
        project_oid = ObjectId(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid project_id: {exc}")

    project_dict = projects_collection.find_one({"_id": project_oid})
    if not project_dict:
        raise HTTPException(status_code=404, detail="Project not found.")

    if not _user_can_edit_project(
        project_dict, current_user.id, getattr(current_user, "is_admin", False)
    ):
        raise HTTPException(
            status_code=403,
            detail="You don't have edit permission on this project.",
        )

    # The CLI helpers expect the user's full token document (they call back
    # into the API with it). Grab any active token for this user — the dash
    # flow does the same thing.
    full_token = tokens_collection.find_one({"user_id": current_user.id})
    if not full_token:
        raise HTTPException(status_code=401, detail="No API token on file for this user.")

    temp_dir = tempfile.mkdtemp(prefix="depictio_upload_")
    try:
        temp_file_path = os.path.join(temp_dir, filename or "upload.dat")
        with open(temp_file_path, "wb") as fh:
            fh.write(file_bytes)
        logger.debug(f"Wrote {len(file_bytes)} bytes to {temp_file_path}")

        polars_kwargs = _build_polars_kwargs(
            file_format, separator, custom_separator, compression, has_header
        )

        dc_table_config = DCTableConfig(
            format=file_format,
            polars_kwargs=polars_kwargs,
            keep_columns=[],
            columns_description={},
        )
        scan_config = Scan(mode="single", scan_parameters=ScanSingle(filename=temp_file_path))
        dc_config = DataCollectionConfig(
            type=data_type,
            metatype="metadata",
            scan=scan_config,
            dc_specific_properties=dc_table_config,
        )
        data_collection = DataCollection(
            data_collection_tag=name.strip(),
            description=description or "",
            config=dc_config,
        )

        # Basic projects can have many DCs in unique workflows; advanced
        # projects have a real upstream pipeline so we still wrap in one
        # workflow per DC for parity with the existing Dash code path.
        timestamp_ms = int(time.time() * 1000)
        workflow_tag = f"{name.strip()}_workflow_{timestamp_ms}"
        workflow = Workflow(
            name=workflow_tag,
            workflow_tag=workflow_tag,
            engine=WorkflowEngine(name="python", version="3.12"),
            config=WorkflowConfig(),
            data_location=WorkflowDataLocation(structure="flat", locations=[temp_dir]),
            data_collections=[data_collection],
        )

        # Atomically append the new workflow onto the project document.
        push_result = projects_collection.update_one(
            {"_id": project_oid},
            {"$push": {"workflows": workflow.mongo()}},
        )
        if push_result.modified_count == 0:
            raise HTTPException(
                status_code=500,
                detail="Failed to attach workflow to project (no document modified).",
            )

        # From here on, any error must roll back the $push — otherwise a
        # failed scan/process leaves a ghost workflow in the project doc
        # with no delta table behind it.
        try:
            cli_config = CLIConfig(
                user=UserBaseCLIConfig(
                    id=current_user.id,
                    email=current_user.email,
                    is_admin=getattr(current_user, "is_admin", False),
                    token=full_token,
                ),
                api_base_url=settings.fastapi.url,
                s3_storage=settings.minio,
            )

            scan_result = process_data_collection_helper(
                CLI_config=cli_config,
                wf=workflow,
                dc_id=str(data_collection.id),
                mode="scan",
            )
            if (scan_result or {}).get("result") != "success":
                raise HTTPException(
                    status_code=500,
                    detail=f"Scan failed: {(scan_result or {}).get('message', 'unknown error')}",
                )

            process_result = process_data_collection_helper(
                CLI_config=cli_config,
                wf=workflow,
                dc_id=str(data_collection.id),
                mode="process",
                command_parameters={"overwrite": True},
            )
            if (process_result or {}).get("result") != "success":
                raise HTTPException(
                    status_code=500,
                    detail=f"Processing failed: {(process_result or {}).get('message', 'unknown error')}",
                )
        except Exception:
            projects_collection.update_one(
                {"_id": project_oid},
                {"$pull": {"workflows": {"_id": ObjectId(str(workflow.id))}}},
            )
            raise

        return {
            "success": True,
            "message": f"Data collection '{name.strip()}' created.",
            "data_collection_id": str(data_collection.id),
            "workflow_id": str(workflow.id),
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
