from datetime import datetime, timedelta, timezone
from typing import Any

from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import HTTPException
from mypy_boto3_s3.client import S3Client
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    deltatables_collection,
    multiqc_collection,
)
from depictio.api.v1.s3 import s3_client
from depictio.models.models.users import UserBeanie


class BucketResponse(BaseModel):
    """Response model for bucket operations"""

    message: str
    bucket_name: str


def check_bucket_exists(s3_client: S3Client, bucket_name: str) -> bool:
    """
    Check if a bucket exists in the S3 storage.

    Args:
        s3_client: The S3 client to use for checking
        bucket_name: Name of the bucket to check

    Returns:
        True if the bucket exists, False otherwise

    Raises:
        HTTPException: If there's an error checking the bucket status
    """
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == "404":
            return False
        logger.error(f"Error checking bucket existence: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error checking bucket existence: {error_code}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during bucket existence check: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Unexpected error occurred checking bucket existence",
        )


def create_s3_bucket(s3_client: S3Client, bucket_name: str) -> BucketResponse:
    """
    Create a new bucket in the S3 storage.

    Args:
        s3_client: The S3 client to use for creation
        bucket_name: Name of the bucket to create

    Returns:
        BucketResponse with success message

    Raises:
        HTTPException: If there's an error creating the bucket
    """
    try:
        s3_client.create_bucket(Bucket=bucket_name)
        return BucketResponse(message="Bucket created successfully", bucket_name=bucket_name)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        # BucketAlreadyOwnedByYou / BucketAlreadyExists mean the bucket is already
        # there - treat as success. Happens in race conditions during initialization
        # with multiple workers, and on every boot with the bundled SeaweedFS
        # (S3_BUCKET pre-creates the bucket at container start).
        if error_code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            logger.info(f"Bucket '{bucket_name}' already exists and is owned by us")
            return BucketResponse(message="Bucket already exists", bucket_name=bucket_name)
        logger.error(f"Failed to create bucket '{bucket_name}': {error_code}")
        raise HTTPException(status_code=500, detail=f"Bucket creation failed: {error_code}")
    except Exception as e:
        logger.error(f"Unexpected error creating bucket '{bucket_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Bucket creation failed: {str(e)}")


def create_bucket(current_user: UserBeanie) -> BucketResponse:
    """
    Create the configured bucket in the S3 store if it doesn't exist.

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

    bucket_name = settings.s3.bucket

    if check_bucket_exists(s3_client, bucket_name):
        return BucketResponse(message="Bucket already exists", bucket_name=bucket_name)
    return create_s3_bucket(s3_client, bucket_name)


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

    bucket_name = settings.s3.bucket
    deleted_count = 0
    total_size_bytes = 0
    orphaned_prefixes = []

    try:
        # List all top-level prefixes in S3 bucket (data collection IDs). S3 is
        # listed before MongoDB is read, so a table registered in between counts
        # as registered rather than orphaned.
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket_name, Delimiter="/")

        s3_prefixes = set()
        for page in pages:
            if "CommonPrefixes" in page:
                for prefix_obj in page["CommonPrefixes"]:
                    prefix = prefix_obj["Prefix"].rstrip("/")
                    # Only consider prefixes that look like MongoDB ObjectIds (24 hex chars)
                    # This excludes raw file storage folders like "image_demo", "uploads", etc.
                    if len(prefix) == 24 and all(c in "0123456789abcdef" for c in prefix.lower()):
                        s3_prefixes.add(prefix)

        valid_dc_ids = _registered_dc_ids()

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
            objects = [
                obj
                for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix)
                for obj in page.get("Contents", [])
            ]
            if not objects:
                continue

            written_at = [obj["LastModified"] for obj in objects if obj.get("LastModified")]
            if min_age_seconds > 0 and written_at and max(written_at) > cutoff:
                recent_prefixes.append(dc_id)
                continue
            # A write that finished since MongoDB was read is no orphan either.
            if _is_registered(dc_id):
                continue

            deleted_prefixes.append(dc_id)
            deleted_count += len(objects)
            total_size_bytes += sum(obj.get("Size", 0) for obj in objects)

            if not dry_run:
                # Delete objects in batches of 1000 (S3 limit)
                batch_size = 1000
                for i in range(0, len(objects), batch_size):
                    batch = [{"Key": obj["Key"]} for obj in objects[i : i + batch_size]]
                    response = s3_client.delete_objects(
                        Bucket=bucket_name, Delete={"Objects": batch}
                    )
                    errors = response.get("Errors", [])
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
