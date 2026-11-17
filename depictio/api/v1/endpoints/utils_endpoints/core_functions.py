from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    deltatables_collection,
    migration_requests_collection,
    multiqc_collection,
)
from depictio.api.v1.s3 import instance_backend
from depictio.models.models.users import UserBeanie
from depictio.models.storage import StorageError


class BucketResponse(BaseModel):
    """Response model for bucket operations"""

    message: str
    bucket_name: str


def create_bucket(current_user: UserBeanie) -> BucketResponse:
    """
    Create the instance bucket if it doesn't exist.

    A backend that cannot create buckets (GCS: a bucket needs a project and a
    location) only checks that it exists.

    Args:
        current_user: The user requesting bucket creation, must be an admin

    Returns:
        BucketResponse with operation result

    Raises:
        HTTPException: If the user is not an admin or if bucket operations fail
    """
    if not current_user.is_admin:
        logger.warning(f"Unauthorized bucket creation attempt by user: {current_user.email}")
        raise HTTPException(status_code=403, detail="User is not an admin")

    bucket_name = instance_backend.bucket
    try:
        created = instance_backend.ensure_bucket()
    except StorageError as e:
        logger.error(f"Bucket '{bucket_name}' is not usable: {e}")
        raise HTTPException(status_code=500, detail=f"Bucket creation failed: {e.code or e}")
    if created:
        return BucketResponse(message="Bucket created successfully", bucket_name=bucket_name)
    return BucketResponse(message="Bucket already exists", bucket_name=bucket_name)


#: A prefix written this recently is never treated as orphaned. Every Delta write
#: lands on S3 before its ``deltatables`` document exists (the CLI writes the
#: table, then registers it), so a prefix with no document may just as well be a
#: table being created right now: reference seeding at boot, a CLI ingest, a
#: refresh. Deleting it then leaves a collection that is registered with no table,
#: or never registered at all. An hour is far longer than any write-then-register
#: gap, and a real orphan only waits one more cleanup cycle.
ORPHAN_MIN_AGE_SECONDS = 3600


def _registered_dc_ids() -> set[str]:
    """Data collection ids MongoDB knows, from deltatables and MultiQC reports."""
    registered: set[str] = set()
    for collection in (deltatables_collection, multiqc_collection):
        for doc in collection.find({}, {"data_collection_id": 1}):
            if "data_collection_id" in doc:
                registered.add(str(doc["data_collection_id"]))
    return registered


def _importing_dc_ids() -> set[str]:
    """Data collection ids of pushed projects being imported right now (#1303).

    An approved import writes the project's objects to S3 before its documents
    exist, so for a while those prefixes look orphaned. The requests record
    the bundle's data collection ids for exactly this reason.
    """
    ids: set[str] = set()
    for doc in migration_requests_collection.find({"status": "importing"}, {"dc_ids": 1}):
        ids.update(str(i) for i in doc.get("dc_ids") or [])
    return ids


def _is_registered(dc_id: str) -> bool:
    """Whether MongoDB knows ``dc_id`` now. Ids are stored as ObjectId or as string."""
    query = {"data_collection_id": {"$in": [ObjectId(dc_id), dc_id]}}
    return any(
        collection.find_one(query, {"_id": 1}) is not None
        for collection in (deltatables_collection, multiqc_collection)
    )


async def cleanup_orphaned_s3_files(
    dry_run: bool = True,
    force: bool = False,
    min_age_seconds: int = ORPHAN_MIN_AGE_SECONDS,
) -> dict[str, Any]:
    """
    Clean up S3 files from data collections that no longer exist in MongoDB.

    This function scans the S3 bucket for data collection prefixes and checks
    if the corresponding data collection exists in MongoDB (either in deltatables
    or multiqc_reports collections). If not, it deletes the orphaned files.

    Note: MultiQC data collections use their own dedicated API endpoints and
    MongoDB collection (MultiQCReport) - they do NOT require deltatable entries.

    Args:
        dry_run: If True, only report what would be deleted without actually deleting
        force: If True, bypass safety check when all prefixes appear orphaned
               (useful when DB was legitimately cleaned but S3 wasn't)
        min_age_seconds: Keep an unregistered prefix whose newest object is younger
               than this (see ``ORPHAN_MIN_AGE_SECONDS``). 0 deletes whatever its
               age, which is only safe when nothing can be writing.

    Returns:
        Dict with cleanup results including:
        - deleted_count: Number of files/objects deleted
        - total_size_bytes: Total size of deleted files in bytes
        - orphaned_prefixes: List of data collection IDs that were deleted
        - orphaned_prefixes_count: Count of deleted data collection prefixes
        - recent_prefixes: Unregistered prefixes kept because they were written recently
        - dry_run: Whether this was a dry run
    """

    deleted_count = 0
    total_size_bytes = 0
    orphaned_prefixes = []

    try:
        # List all top-level prefixes in S3 bucket (data collection IDs). S3 is
        # listed before MongoDB is read, so a table registered in between counts
        # as registered rather than orphaned.
        s3_prefixes = {
            prefix
            for prefix in instance_backend.list_folders()
            # Only consider prefixes that look like MongoDB ObjectIds (24 hex chars)
            # This excludes raw file storage folders like "image_demo", "uploads", etc.
            if len(prefix) == 24 and all(c in "0123456789abcdef" for c in prefix.lower())
        }

        # The staging prefix holds pushed bundles awaiting a decision. It can
        # never look like an ObjectId (MigrationConfig refuses that), but the
        # sweep spares it by name too rather than by that coincidence.
        s3_prefixes.discard(settings.migration.staging_prefix)

        valid_dc_ids = _registered_dc_ids() | _importing_dc_ids()

        # Find orphaned prefixes (in S3 but not in MongoDB)
        orphaned_prefixes = sorted(s3_prefixes - valid_dc_ids)

        # Safety check: if all prefixes are orphaned, something might be wrong
        if len(s3_prefixes) > 0 and len(orphaned_prefixes) == len(s3_prefixes) and not force:
            logger.error(
                "SAFETY CHECK FAILED: All S3 prefixes appear orphaned! "
                "This suggests either: (1) DB was cleaned but S3 wasn't, or (2) a bug in ID comparison. "
                "Aborting cleanup. Use force=True to bypass this check if DB was legitimately cleaned."
            )
            return {
                "deleted_count": 0,
                "total_size_bytes": 0,
                "orphaned_prefixes": [],
                "orphaned_prefixes_count": 0,
                "dry_run": dry_run,
                "error": "Safety check failed - all prefixes orphaned (use force=True to bypass)",
            }

        if force and len(orphaned_prefixes) == len(s3_prefixes):
            logger.warning(
                f"FORCE MODE: Bypassing safety check. Will clean {len(orphaned_prefixes)} prefixes "
                f"even though all S3 prefixes appear orphaned."
            )

        # Delete files under orphaned prefixes
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)
        deleted_prefixes: list[str] = []
        recent_prefixes: list[str] = []
        for dc_id in orphaned_prefixes:
            prefix = f"{dc_id}/"

            # List all objects under this prefix
            objects = list(instance_backend.list_objects(prefix))
            if not objects:
                continue

            written_at = [obj.last_modified for obj in objects if obj.last_modified]
            if min_age_seconds > 0 and written_at and max(written_at) > cutoff:
                recent_prefixes.append(dc_id)
                continue
            # A write that finished since MongoDB was read is no orphan either.
            if _is_registered(dc_id):
                continue

            deleted_prefixes.append(dc_id)
            deleted_count += len(objects)
            total_size_bytes += sum(obj.size for obj in objects)

            if not dry_run:
                errors = instance_backend.delete_keys(obj.key for obj in objects)
                if errors:
                    logger.error(f"Errors deleting objects: {errors}")

        if recent_prefixes:
            logger.info(
                f"Kept {len(recent_prefixes)} unregistered S3 prefixes written in the last "
                f"{min_age_seconds}s: {', '.join(recent_prefixes[:5])}"
                + ("..." if len(recent_prefixes) > 5 else "")
            )

        # Log cleanup summary
        if deleted_prefixes:
            logger.info(
                f"Cleaned up {len(deleted_prefixes)} orphaned S3 prefixes: "
                f"{', '.join(deleted_prefixes[:5])}" + ("..." if len(deleted_prefixes) > 5 else "")
            )

        return {
            "deleted_count": deleted_count,
            "total_size_bytes": total_size_bytes,
            "orphaned_prefixes": deleted_prefixes,
            "orphaned_prefixes_count": len(deleted_prefixes),
            "recent_prefixes": recent_prefixes,
            "dry_run": dry_run,
        }

    except Exception as e:
        logger.error(f"Error during S3 cleanup: {e}")
        # Don't raise HTTPException in background tasks - it kills the worker!
        # Return error in result dict instead
        return {
            "deleted_count": 0,
            "total_size_bytes": 0,
            "orphaned_prefixes": [],
            "orphaned_prefixes_count": 0,
            "dry_run": dry_run,
            "error": f"S3 cleanup failed: {str(e)}",
        }
