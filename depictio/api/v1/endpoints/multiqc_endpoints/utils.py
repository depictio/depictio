"""Utility functions for MultiQC endpoints."""

from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import multiqc_collection
from depictio.api.v1.s3 import s3_client

# Import build_sample_mapping from CLI utils to avoid code duplication
# This function is now shared between API and CLI without circular dependencies
from depictio.cli.cli.utils.sample_mapping import build_sample_mapping
from depictio.models.models.multiqc_reports import MultiQCReport

# Re-export for backward compatibility
__all__ = ["build_sample_mapping"]


async def check_duplicate_multiqc_report(
    data_collection_id: str, original_file_path: str
) -> Optional[MultiQCReport]:
    """
    Check if a MultiQC report already exists for the same data collection and file path.

    Args:
        data_collection_id: ID of the data collection
        original_file_path: Original local file path of the MultiQC report

    Returns:
        Existing MultiQC report if found, None otherwise
    """
    try:
        query = {
            "data_collection_id": data_collection_id,
            "original_file_path": original_file_path,
        }
        report_doc = multiqc_collection.find_one(query)

        if report_doc:
            report_doc["id"] = str(report_doc["_id"])
            logger.info(
                f"Found existing MultiQC report for DC {data_collection_id}, file {original_file_path}"
            )
            return MultiQCReport(**report_doc)

        return None

    except Exception as e:
        logger.warning(f"Failed to check for duplicate MultiQC report: {e}")
        return None


async def create_multiqc_report_in_db(report: MultiQCReport) -> MultiQCReport:
    """
    Create a new MultiQC report in the database.

    Args:
        report: MultiQC report data to save

    Returns:
        Created MultiQC report with assigned ID

    Raises:
        HTTPException: If database insertion fails
    """
    try:
        # Convert report to MongoDB document format
        report_dict = report.model_dump()

        # Generate new ObjectId for the document
        new_id = ObjectId()
        report_dict["_id"] = new_id
        report_dict["id"] = str(new_id)

        # Insert into MongoDB
        result = multiqc_collection.insert_one(report_dict)

        if not result.inserted_id:
            raise HTTPException(
                status_code=500, detail="Failed to insert MultiQC report into database"
            )

        # Return the saved report
        return MultiQCReport(**report_dict)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create MultiQC report: {str(e)}")


async def update_multiqc_report_by_id(
    report_id: str, updated_report: MultiQCReport
) -> MultiQCReport:
    """
    Update an existing MultiQC report in the database.

    Args:
        report_id: ID of the MultiQC report to update
        updated_report: Updated MultiQC report data

    Returns:
        Updated MultiQC report

    Raises:
        HTTPException: If report not found or update fails
    """
    try:
        # Verify the report exists
        existing_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not existing_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert updated report to dict, excluding id fields
        update_dict = updated_report.model_dump(exclude={"id"}, exclude_none=True)

        # Update the document
        result = multiqc_collection.update_one({"_id": ObjectId(report_id)}, {"$set": update_dict})

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        if result.modified_count == 0:
            logger.warning(f"MultiQC report {report_id} was matched but not modified")

        # Fetch and return the updated report
        updated_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if updated_doc:
            updated_doc["id"] = str(updated_doc["_id"])
            return MultiQCReport(**updated_doc)
        else:
            raise HTTPException(status_code=500, detail="Failed to retrieve updated report")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update MultiQC report: {str(e)}")


async def get_multiqc_reports_by_data_collection(
    data_collection_id: str, limit: int = 50, offset: int = 0
) -> tuple[List[MultiQCReport], int]:
    """
    Get MultiQC reports for a specific data collection.

    Args:
        data_collection_id: ID of the data collection
        limit: Maximum number of reports to return
        offset: Number of reports to skip

    Returns:
        Tuple of (reports list, total count)

    Raises:
        HTTPException: If database query fails
    """
    try:
        # Query for all reports associated with this data collection
        query = {"data_collection_id": data_collection_id}
        total_count = multiqc_collection.count_documents(query)
        cursor = multiqc_collection.find(query).skip(offset).limit(limit).sort("processed_at", -1)

        reports = []
        for doc in cursor:
            try:
                # Convert ObjectId to string for proper serialization
                if "_id" in doc:
                    doc["id"] = str(doc["_id"])
                reports.append(MultiQCReport(**doc))
            except Exception as doc_error:
                logger.warning(f"Failed to parse MultiQC report document: {doc_error}")
                continue

        logger.info(
            f"Found {len(reports)} MultiQC reports for data collection {data_collection_id}"
        )
        return reports, total_count

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve MultiQC reports: {str(e)}")


async def get_multiqc_report_by_id(report_id: str) -> MultiQCReport:
    """
    Get a specific MultiQC report by ID.

    Args:
        report_id: ID of the MultiQC report

    Returns:
        MultiQC report

    Raises:
        HTTPException: If report not found or database query fails
    """
    try:
        # Find the report by ID
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert ObjectId to string for proper serialization
        report_doc["id"] = str(report_doc["_id"])
        return MultiQCReport(**report_doc)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve MultiQC report: {str(e)}")


async def delete_multiqc_report_by_id(report_id: str, delete_s3_file: bool = False) -> dict:
    """
    Delete a MultiQC report and optionally its S3 file.

    Args:
        report_id: ID of the MultiQC report to delete
        delete_s3_file: Whether to also delete the associated S3 file

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If report not found or deletion fails
    """
    try:
        # Find the report first
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert and get the report object for potential S3 deletion
        report_doc["id"] = str(report_doc["_id"])
        report = MultiQCReport(**report_doc)

        # Delete S3 file if requested
        s3_file_deleted = False
        if delete_s3_file and report.s3_location:
            try:
                # Parse S3 location to get bucket and key
                # Format: s3://bucket/data_collection_id/timestamp_id/multiqc.parquet
                s3_path = report.s3_location.replace("s3://", "")
                bucket_name = settings.minio.bucket

                # Extract the prefix (everything after bucket name)
                if "/" in s3_path:
                    s3_key_prefix = s3_path.split("/", 1)[1]

                    # List all objects with this prefix and delete them
                    paginator = s3_client.get_paginator("list_objects_v2")
                    pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_key_prefix)

                    objects_to_delete = []
                    for page in pages:
                        if "Contents" in page:
                            for obj in page["Contents"]:
                                objects_to_delete.append({"Key": obj["Key"]})

                    if objects_to_delete:
                        # Delete in batches of 1000 (S3 limit)
                        batch_size = 1000
                        for i in range(0, len(objects_to_delete), batch_size):
                            batch = objects_to_delete[i : i + batch_size]
                            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": batch})

                        logger.info(
                            f"Deleted {len(objects_to_delete)} S3 objects from: {report.s3_location}"
                        )
                        s3_file_deleted = True
                    else:
                        logger.warning(f"No S3 objects found at: {report.s3_location}")
                        s3_file_deleted = False
                else:
                    logger.warning(f"Invalid S3 location format: {report.s3_location}")
                    s3_file_deleted = False

            except Exception as s3_error:
                logger.warning(f"Failed to delete S3 file: {s3_error}")
                s3_file_deleted = False

        # Delete the report from database
        result = multiqc_collection.delete_one({"_id": ObjectId(report_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        return {
            "deleted": True,
            "s3_file_deleted": s3_file_deleted,
            "message": f"MultiQC report {report_id} deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete MultiQC report: {str(e)}")


async def delete_all_multiqc_reports_for_dc(
    data_collection_id: str,
    delete_s3_files: bool = False,
) -> dict:
    """
    Delete every MultiQC report for a data collection in one Mongo delete_many call.

    Optionally also deletes the source parquet objects from S3. Individual S3
    failures are logged and do not block the bulk Mongo delete.

    Returns: {"deleted_count": int, "deleted_s3_count": int}
    """
    deleted_s3_count = 0

    if delete_s3_files:
        bucket_name = settings.minio.bucket
        # Project to s3_location only — report docs carry full plots/sample
        # mappings payloads which can be large; we just need the location.
        cursor = multiqc_collection.find(
            {"data_collection_id": data_collection_id},
            {"s3_location": 1},
        )
        for report_doc in cursor:
            s3_location = report_doc.get("s3_location")
            if not s3_location:
                continue
            try:
                # Format: s3://bucket/data_collection_id/timestamp_id/multiqc.parquet
                s3_path = s3_location.replace("s3://", "")
                if "/" not in s3_path:
                    logger.warning(f"Invalid S3 location format: {s3_location}")
                    continue
                s3_key_prefix = s3_path.split("/", 1)[1]

                paginator = s3_client.get_paginator("list_objects_v2")
                pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_key_prefix)
                objects_to_delete = [
                    {"Key": obj["Key"]} for page in pages for obj in page.get("Contents", [])
                ]

                if not objects_to_delete:
                    logger.warning(f"No S3 objects found at: {s3_location}")
                    continue
                batch_size = 1000
                for i in range(0, len(objects_to_delete), batch_size):
                    batch = objects_to_delete[i : i + batch_size]
                    s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": batch})
                logger.info(f"Deleted {len(objects_to_delete)} S3 objects from: {s3_location}")
                deleted_s3_count += 1
            except Exception as s3_error:
                logger.warning(f"Failed to delete S3 file at {s3_location}: {s3_error}")

    try:
        result = multiqc_collection.delete_many({"data_collection_id": data_collection_id})
        deleted_count = int(result.deleted_count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete MultiQC reports: {str(e)}")

    logger.info(
        f"Bulk-deleted {deleted_count} MultiQC reports for data collection "
        f"{data_collection_id} (S3 deletions: {deleted_s3_count})"
    )

    return {"deleted_count": deleted_count, "deleted_s3_count": deleted_s3_count}


async def get_multiqc_report_metadata_by_id(report_id: str) -> dict:
    """
    Get the extracted metadata from a MultiQC report.

    Args:
        report_id: ID of the MultiQC report

    Returns:
        MultiQC metadata including samples, modules, and plots

    Raises:
        HTTPException: If report not found or query fails
    """
    try:
        # Find the report by ID
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert ObjectId to string for proper serialization
        report_doc["id"] = str(report_doc["_id"])
        report = MultiQCReport(**report_doc)
        return report.metadata.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve MultiQC metadata: {str(e)}"
        )


async def generate_multiqc_download_url(report_id: str, expiration_hours: int = 24) -> dict:
    """
    Generate a presigned URL to download the MultiQC parquet file from S3.

    Args:
        report_id: ID of the MultiQC report
        expiration_hours: How long the download URL should be valid (1-168 hours)

    Returns:
        Presigned download URL and metadata

    Raises:
        HTTPException: If report not found or URL generation fails
    """
    try:
        # Find the report by ID
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert ObjectId to string for proper serialization
        report_doc["id"] = str(report_doc["_id"])
        report = MultiQCReport(**report_doc)

        if not report.s3_location:
            raise HTTPException(status_code=400, detail="No S3 location available for this report")

        # TODO: Implement presigned URL generation when S3 utility functions are available
        # presigned_url = generate_presigned_url(
        #     report.s3_location,
        #     expiration_seconds=expiration_hours * 3600
        # )

        # For now, return the S3 location directly (in production, this would be a presigned URL)
        return {
            "download_url": report.s3_location,  # This should be a presigned URL in production
            "expires_in_hours": expiration_hours,
            "file_size_bytes": report.file_size_bytes,
            "s3_location": report.s3_location,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate download URL: {str(e)}")


# =============================================================================
# In-process append / replace helpers for the React management modal.
#
# Mirror the Dash flow at ``dash/api_calls.py:api_call_overwrite_*`` and
# ``api_call_append_*`` but operate on raw bytes and via direct DB access
# rather than httpx callbacks. The Dash helpers stay where they are so the
# Dash UI continues to work.
# =============================================================================


def _load_workflow_and_dc(project_doc: dict, dc_id: str):
    """Locate (Workflow, DataCollection) Pydantic models for a DC inside a project.

    Returns (None, None) if not found.
    """
    from depictio.models.models.workflows import Workflow

    workflows = project_doc.get("workflows", []) or []
    for wf_dict in workflows:
        for dc_dict in wf_dict.get("data_collections", []) or []:
            current_id = dc_dict.get("id") or dc_dict.get("_id")
            if current_id and str(current_id) == str(dc_id):
                try:
                    workflow = Workflow(**wf_dict)
                except Exception as exc:
                    logger.error(f"Failed to parse workflow for DC {dc_id}: {exc}")
                    return None, None
                for dc in workflow.data_collections:
                    if str(dc.id) == str(dc_id):
                        return workflow, dc
                return workflow, None
    return None, None


def _download_parquet_from_s3(s3_location: str, local_path: str) -> None:
    """Download s3://bucket/key to local_path, creating parent dirs.

    Used by the append flow: existing reports' parquets are pulled back so
    the processor sees the full file set on every run.
    """
    import os as _os

    if not s3_location.startswith("s3://"):
        raise ValueError(f"Invalid S3 location: {s3_location!r}")
    rest = s3_location[len("s3://") :]
    if "/" not in rest:
        raise ValueError(f"Invalid S3 location: {s3_location!r} (missing key)")
    bucket, key = rest.split("/", 1)
    if not bucket or not key:
        raise ValueError(f"Invalid S3 location: {s3_location!r}")
    _os.makedirs(_os.path.dirname(local_path), exist_ok=True)
    s3_client.download_file(bucket, key, local_path)


def _replace_multiqc_dc_uploads(
    *,
    data_collection_id: str,
    decoded_files: list[tuple[bytes, str]],
    current_user,
) -> dict:
    """Bulk-delete + reprocess a MultiQC DC with the new uploads.

    Synchronous; caller must dispatch via ``asyncio.to_thread``.
    """
    import asyncio
    import shutil
    import tempfile

    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _build_cli_config_for_user,
        _save_multiqc_uploads_to_temp_dir,
        _user_can_edit_project,
    )
    from depictio.cli.cli.utils.helpers import process_data_collection_helper

    project_doc = projects_collection.find_one(
        {"workflows.data_collections._id": ObjectId(data_collection_id)}
    )
    if not project_doc:
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )
    if not _user_can_edit_project(
        project_doc, current_user.id, getattr(current_user, "is_admin", False)
    ):
        # 404 (not 403) — don't leak DC existence to non-members.
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )

    workflow, dc = _load_workflow_and_dc(project_doc, data_collection_id)
    if workflow is None or dc is None:
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )

    cli_config = _build_cli_config_for_user(current_user)

    temp_dir = tempfile.mkdtemp(prefix="depictio_multiqc_replace_")
    try:
        folder_assignments, skipped_names = _save_multiqc_uploads_to_temp_dir(
            decoded_files, temp_dir
        )

        # Wipe Mongo + S3 before reprocessing — caller asked for "Replace all".
        delete_result = asyncio.run(
            delete_all_multiqc_reports_for_dc(data_collection_id, delete_s3_files=True)
        )

        workflow.data_location.locations = [temp_dir]
        process_result = process_data_collection_helper(
            CLI_config=cli_config,
            wf=workflow,
            dc_id=str(dc.id),
            mode="process",
            command_parameters={"overwrite": True},
        )
        if (process_result or {}).get("result") != "success":
            raise HTTPException(
                status_code=500,
                detail=(
                    f"MultiQC processing failed: "
                    f"{(process_result or {}).get('message', 'unknown error')}"
                ),
            )

        return {
            "success": True,
            "message": (
                f"MultiQC DC replaced ({len(folder_assignments)} folder(s) ingested, "
                f"{delete_result.get('deleted_count', 0)} previous report(s) removed)."
            ),
            "data_collection_id": str(dc.id),
            "ingested_folders": sorted({folder for folder, _ in folder_assignments}),
            "skipped_count": len(skipped_names),
            "deleted_count": int(delete_result.get("deleted_count", 0)),
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _append_multiqc_dc_uploads(
    *,
    data_collection_id: str,
    decoded_files: list[tuple[bytes, str]],
    current_user,
) -> dict:
    """Append new folders to an existing MultiQC DC.

    The processor only sees what's under the workflow's data_location at run
    time, so existing parquets are pulled back from S3 into the temp dir
    alongside the new uploads. Old report rows are dropped only after the
    reprocess succeeds (defer-on-failure preserves user data on partial
    error).
    """
    import os as _os
    import shutil
    import tempfile

    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _build_cli_config_for_user,
        _extract_multiqc_folder_name,
        _save_multiqc_uploads_to_temp_dir,
        _user_can_edit_project,
    )
    from depictio.cli.cli.utils.helpers import process_data_collection_helper

    project_doc = projects_collection.find_one(
        {"workflows.data_collections._id": ObjectId(data_collection_id)}
    )
    if not project_doc:
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )
    if not _user_can_edit_project(
        project_doc, current_user.id, getattr(current_user, "is_admin", False)
    ):
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )

    workflow, dc = _load_workflow_and_dc(project_doc, data_collection_id)
    if workflow is None or dc is None:
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )

    cli_config = _build_cli_config_for_user(current_user)

    temp_dir = tempfile.mkdtemp(prefix="depictio_multiqc_append_")
    try:
        # 1. Drop the new uploads first; this claims folder slots.
        folder_assignments, skipped_names = _save_multiqc_uploads_to_temp_dir(
            decoded_files, temp_dir
        )
        new_folders = {folder for folder, _ in folder_assignments}

        # 2. Pull existing reports' parquets back from S3 under non-colliding
        #    folder names (new uploads win on collision).
        fetched_from_s3 = 0
        existing_cursor = multiqc_collection.find({"data_collection_id": str(data_collection_id)})
        existing_reports = list(existing_cursor)
        used_folders: set[str] = set(new_folders)
        for idx, report in enumerate(existing_reports):
            base_folder = _extract_multiqc_folder_name(report.get("original_file_path") or "", idx)
            if not base_folder or base_folder == f"report_{idx}":
                fallback = report.get("id") or report.get("_id") or f"report_{idx}"
                base_folder = str(fallback)
            if base_folder in new_folders:
                # New upload supersedes this folder slot.
                continue
            folder = base_folder
            suffix = 1
            while folder in used_folders:
                folder = f"{base_folder}_{suffix}"
                suffix += 1
            used_folders.add(folder)

            s3_location = report.get("s3_location")
            if not s3_location:
                logger.warning(
                    f"Append: existing report {report.get('_id')} has no s3_location; skipping"
                )
                continue
            target = _os.path.join(temp_dir, folder, "multiqc_data", "multiqc.parquet")
            _download_parquet_from_s3(s3_location, target)
            fetched_from_s3 += 1

        # 3. Capture old report ids for cleanup *after* successful reprocess.
        old_report_ids = [
            str(rid) for r in existing_reports if (rid := r.get("id") or r.get("_id"))
        ]

        # 4. Re-ingest the merged folder set.
        workflow.data_location.locations = [temp_dir]
        process_result = process_data_collection_helper(
            CLI_config=cli_config,
            wf=workflow,
            dc_id=str(dc.id),
            mode="process",
            command_parameters={"overwrite": True},
        )
        if (process_result or {}).get("result") != "success":
            raise HTTPException(
                status_code=500,
                detail=(
                    f"MultiQC processing failed: "
                    f"{(process_result or {}).get('message', 'unknown error')}"
                ),
            )

        # 5. Drop the old report rows (one-by-one — bulk-delete would catch
        #    the freshly-inserted rows). Don't delete S3 here; the reprocess
        #    already wrote new parquets at fresh keys.
        cleanup_failed = 0
        for rid in old_report_ids:
            try:
                multiqc_collection.delete_one({"_id": ObjectId(rid)})
            except Exception as exc:
                cleanup_failed += 1
                logger.warning(f"Append cleanup: stale report {rid} delete failed: {exc}")

        return {
            "success": True,
            "message": (
                f"MultiQC DC appended ({len(folder_assignments)} new folder(s), "
                f"{fetched_from_s3} existing folder(s) preserved"
                + (f", {cleanup_failed} stale rows left behind" if cleanup_failed else "")
                + ")."
            ),
            "data_collection_id": str(dc.id),
            "ingested_folders": sorted(new_folders),
            "skipped_count": len(skipped_names),
            "fetched_from_s3_count": fetched_from_s3,
            "cleanup_failed": cleanup_failed,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
