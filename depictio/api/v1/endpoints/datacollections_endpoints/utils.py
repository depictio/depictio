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


def _delete_orphan_links_for_dc(data_collection_id: str) -> int:
    """Remove any project.links[] entry referencing this DC as source/target.

    Returns the number of projects whose links array was modified.
    """
    orphan_query = {
        "$or": [
            {"source_dc_id": data_collection_id},
            {"target_dc_id": data_collection_id},
        ]
    }
    result = projects_collection.update_many(
        {"links": {"$elemMatch": orphan_query}},
        {"$pull": {"links": orphan_query}},
    )
    return result.modified_count


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

    links_pulled = _delete_orphan_links_for_dc(data_collection_id)
    if links_pulled:
        logger.info(
            f"Removed orphan cross-DC links from {links_pulled} project(s) after deleting DC {data_collection_id}"
        )

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


def _create_dc_from_upload(
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

    Synchronous on purpose: the CLI helpers it calls (process_data_collection_helper)
    use a sync httpx client to talk back to this same FastAPI process. Running this
    on the event loop would deadlock — the loop would be parked awaiting its own
    response. Callers must dispatch via `asyncio.to_thread`.
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


# =============================================================================
# MultiQC DC creation helpers (in-process, used by both Dash and the React API)
# =============================================================================

_MULTIQC_MAX_PER_FILE_BYTES = 50 * 1024 * 1024
_MULTIQC_MAX_TOTAL_BYTES = 500 * 1024 * 1024


def _extract_multiqc_folder_name(filename: str, fallback_idx: int) -> str:
    """Derive a folder identifier from a multiqc.parquet relative path.

    Browsers preserve the directory structure under ``webkitRelativePath`` for
    folder-mode uploads. The frontend forwards that as the file's effective
    name so paths like ``run_01/multiqc_data/multiqc.parquet`` reach Python
    here. The MultiQC processor's discovery glob is
    ``*/multiqc_data/multiqc.parquet`` — keying each report by the parent of
    ``multiqc_data/`` (else the immediate parent, else an ordinal) gives each
    report a stable, unique folder slot under the temp dir.
    """
    parts = [p for p in filename.replace("\\", "/").split("/") if p]
    if len(parts) >= 3 and parts[-2] == "multiqc_data":
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return f"report_{fallback_idx}"


def _save_multiqc_uploads_to_temp_dir(
    decoded_files: list[tuple[bytes, str]],
    temp_dir: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Filter, validate, and save multiqc.parquet uploads under per-folder subdirs.

    ``decoded_files`` is a list of (raw_bytes, original_filename). Returns
    (folder_assignments, skipped_names). Raises HTTPException on validation
    failure so callers don't have to thread error envelopes manually.
    """
    kept: list[tuple[int, str, bytes]] = []
    skipped_names: list[str] = []
    for i, (decoded, fname) in enumerate(decoded_files):
        basename = os.path.basename(fname.replace("\\", "/"))
        if basename != "multiqc.parquet":
            skipped_names.append(fname)
            continue
        if not decoded:
            raise HTTPException(status_code=400, detail=f"File '{fname}' is empty.")
        if len(decoded) > _MULTIQC_MAX_PER_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File '{fname}' is {len(decoded) / (1024 * 1024):.1f}MB; per-file cap is 50MB."
                ),
            )
        kept.append((i, fname, decoded))

    if not kept:
        raise HTTPException(
            status_code=400,
            detail=(
                "No files named 'multiqc.parquet' found in the upload. "
                "Drop one or more folders that each contain a multiqc.parquet file."
            ),
        )

    total_size = sum(len(decoded) for _, _, decoded in kept)
    if total_size > _MULTIQC_MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(f"Total upload size {total_size / (1024 * 1024):.1f}MB exceeds 500MB limit."),
        )

    used_folders: set[str] = set()
    folder_assignments: list[tuple[str, str]] = []
    for i, fname, decoded in kept:
        base_folder = _extract_multiqc_folder_name(fname, i)
        folder = base_folder
        suffix = 1
        while folder in used_folders:
            folder = f"{base_folder}_{suffix}"
            suffix += 1
        used_folders.add(folder)
        subdir = os.path.join(temp_dir, folder, "multiqc_data")
        os.makedirs(subdir, exist_ok=True)
        target = os.path.join(subdir, "multiqc.parquet")
        with open(target, "wb") as fh:
            fh.write(decoded)
        folder_assignments.append((folder, fname))

    logger.info(
        f"Ingested {len(folder_assignments)} multiqc.parquet across folders: "
        f"{sorted(used_folders)}; skipped {len(skipped_names)} non-multiqc files"
    )
    return folder_assignments, skipped_names


def _build_multiqc_workflow(name: str, description: str, temp_dir: str):
    """Construct a single-DC Workflow wrapping a MultiQC DC pointed at temp_dir."""
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
    )
    from depictio.models.models.data_collections_types.multiqc import DCMultiQC
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    dc_config = DataCollectionConfig(
        type="multiqc",
        metatype="metadata",
        dc_specific_properties=DCMultiQC(),
    )
    data_collection = DataCollection(
        data_collection_tag=name.strip(),
        description=description or "",
        config=dc_config,
    )
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
    return workflow, data_collection


def _build_cli_config_for_user(current_user):
    """Build a CLIConfig for in-process processor calls.

    The CLI helpers expect a stored token doc (they call back into the API
    over httpx). Mirrors the table-DC flow at ``_create_dc_from_upload``.
    """
    from depictio.models.models.cli import CLIConfig, UserBaseCLIConfig

    full_token = tokens_collection.find_one({"user_id": current_user.id})
    if not full_token:
        raise HTTPException(status_code=401, detail="No API token on file for this user.")

    return CLIConfig(
        user=UserBaseCLIConfig(
            id=current_user.id,
            email=current_user.email,
            is_admin=getattr(current_user, "is_admin", False),
            token=full_token,
        ),
        api_base_url=settings.fastapi.url,
        s3_storage=settings.minio,
    )


def _create_multiqc_dc_from_uploads(
    *,
    project_id: str,
    name: str,
    description: str,
    decoded_files: list[tuple[bytes, str]],
    current_user,
) -> dict:
    """Create a MultiQC data collection from a list of (bytes, filename) uploads.

    Synchronous on purpose — ``process_data_collection_helper`` uses a sync
    httpx client back to this same FastAPI process. Callers MUST dispatch
    via ``asyncio.to_thread``.
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Data collection name is required.")
    if not decoded_files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    from depictio.cli.cli.utils.helpers import process_data_collection_helper

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

    cli_config = _build_cli_config_for_user(current_user)

    temp_dir = tempfile.mkdtemp(prefix="depictio_multiqc_upload_")
    try:
        folder_assignments, skipped_names = _save_multiqc_uploads_to_temp_dir(
            decoded_files, temp_dir
        )
        workflow, data_collection = _build_multiqc_workflow(name, description, temp_dir)

        # Atomically attach the new workflow before processing so the API can
        # locate the DC via its $push'd entry. Roll back on processor failure.
        push_result = projects_collection.update_one(
            {"_id": project_oid},
            {"$push": {"workflows": workflow.mongo()}},
        )
        if push_result.modified_count == 0:
            raise HTTPException(
                status_code=500,
                detail="Failed to attach workflow to project (no document modified).",
            )

        try:
            # MultiQC has no scan step — process discovers parquets via the
            # workflow's data_location glob.
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
                    detail=f"MultiQC processing failed: "
                    f"{(process_result or {}).get('message', 'unknown error')}",
                )

            # Same uniformity check the replace/append flows run — without it,
            # the processor's union-merge silently produces half-populated
            # figures when modules / plots / versions disagree across reports.
            from depictio.api.v1.endpoints.multiqc_endpoints.uniformity import (
                validate_multiqc_reports_uniform,
            )
            from depictio.api.v1.endpoints.multiqc_endpoints.utils import (
                _fetch_dc_reports_raw,
            )

            new_reports = _fetch_dc_reports_raw(str(data_collection.id))
            logger.info(
                f"MultiQC create: running uniformity checks on {len(new_reports)} report(s) "
                f"(DC '{name.strip()}')"
            )
            validate_multiqc_reports_uniform(new_reports)
            if len(new_reports) > 1:
                logger.info(
                    f"MultiQC create: uniformity checks passed — modules, plots, "
                    f"version, samples consistent across {len(new_reports)} reports"
                )
        except Exception:
            projects_collection.update_one(
                {"_id": project_oid},
                {"$pull": {"workflows": {"_id": ObjectId(str(workflow.id))}}},
            )
            raise

        return {
            "success": True,
            "message": (
                f"MultiQC data collection '{name.strip()}' created "
                f"({len(folder_assignments)} folder(s) ingested"
                + (f", {len(skipped_names)} non-multiqc file(s) ignored" if skipped_names else "")
                + ")."
            ),
            "data_collection_id": str(data_collection.id),
            "workflow_id": str(workflow.id),
            "ingested_folders": sorted({folder for folder, _ in folder_assignments}),
            "skipped_count": len(skipped_names),
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
