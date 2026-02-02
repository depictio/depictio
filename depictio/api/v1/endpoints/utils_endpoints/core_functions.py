from typing import Any

from botocore.exceptions import ClientError
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
    except Exception as e:
        logger.error(f"Failed to create bucket '{bucket_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Bucket creation failed: {str(e)}")


def create_bucket(current_user: UserBeanie) -> BucketResponse:
    """
    Create a bucket in the MinIO server if it doesn't exist.

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

    bucket_name = settings.minio.bucket

    if check_bucket_exists(s3_client, bucket_name):
        return BucketResponse(message="Bucket already exists", bucket_name=bucket_name)
    return create_s3_bucket(s3_client, bucket_name)


async def cleanup_orphaned_s3_files(dry_run: bool = True, force: bool = False) -> dict[str, Any]:
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

    Returns:
        Dict with cleanup results including:
        - deleted_count: Number of files/objects deleted
        - total_size_bytes: Total size of deleted files in bytes
        - orphaned_prefixes: List of data collection IDs that were orphaned
        - orphaned_prefixes_count: Count of orphaned data collection prefixes
        - dry_run: Whether this was a dry run
    """

    bucket_name = settings.minio.bucket
    deleted_count = 0
    total_size_bytes = 0
    orphaned_prefixes = []

    try:
        valid_dc_ids = set()

        # Collect data collection IDs from deltatables
        cursor = deltatables_collection.find({}, {"data_collection_id": 1})
        for doc in cursor:
            if "data_collection_id" in doc:
                valid_dc_ids.add(str(doc["data_collection_id"]))

        # Collect data collection IDs from multiqc
        cursor = multiqc_collection.find({}, {"data_collection_id": 1})
        for doc in cursor:
            if "data_collection_id" in doc:
                valid_dc_ids.add(str(doc["data_collection_id"]))

        # List all top-level prefixes in S3 bucket (data collection IDs)
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

        # Find orphaned prefixes (in S3 but not in MongoDB)
        orphaned_prefixes = list(s3_prefixes - valid_dc_ids)

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
        for dc_id in orphaned_prefixes:
            prefix = f"{dc_id}/"

            # List all objects under this prefix
            objects_to_delete = []
            pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        objects_to_delete.append({"Key": obj["Key"]})
                        total_size_bytes += obj.get("Size", 0)
                        deleted_count += 1

            if objects_to_delete:
                if not dry_run:
                    # Delete objects in batches of 1000 (S3 limit)
                    batch_size = 1000
                    for i in range(0, len(objects_to_delete), batch_size):
                        batch = objects_to_delete[i : i + batch_size]
                        response = s3_client.delete_objects(
                            Bucket=bucket_name, Delete={"Objects": batch}
                        )

                        len(response.get("Deleted", []))
                        errors = response.get("Errors", [])

                        if errors:
                            logger.error(f"Errors deleting objects: {errors}")
                        else:
                            pass
                else:
                    pass

        # Log cleanup summary
        if orphaned_prefixes:
            logger.info(
                f"Cleaned up {len(orphaned_prefixes)} orphaned S3 prefixes: "
                f"{', '.join(orphaned_prefixes[:5])}"
                + ("..." if len(orphaned_prefixes) > 5 else "")
            )

        result = {
            "deleted_count": deleted_count,
            "total_size_bytes": total_size_bytes,
            "orphaned_prefixes": orphaned_prefixes,
            "orphaned_prefixes_count": len(orphaned_prefixes),
            "dry_run": dry_run,
        }

        if dry_run:
            pass
        else:
            pass
        return result

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
