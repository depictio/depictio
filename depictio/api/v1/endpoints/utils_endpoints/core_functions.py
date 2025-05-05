from pydantic import BaseModel
from fastapi import HTTPException
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client

from depictio.api.v1.configs.custom_logging import logger
from depictio.api.v1.configs.config import settings
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
        logger.info(f"Bucket '{bucket_name}' created successfully.")
        return BucketResponse(
            message="Bucket created successfully", bucket_name=bucket_name
        )
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
    # Validate user is an admin
    if not current_user.is_admin:
        logger.warning(
            f"Unauthorized bucket creation attempt by user: {current_user.email}"
        )
        raise HTTPException(status_code=403, detail="User is not an admin")

    # Get bucket name from settings
    logger.info(f"Minio settings: {settings.minio}")
    bucket_name = settings.minio.bucket
    logger.debug(f"Bucket name retrieved from settings: {bucket_name}")

    # Check if bucket exists and create if needed
    if check_bucket_exists(s3_client, bucket_name):
        logger.info(f"Bucket '{bucket_name}' already exists.")
        return BucketResponse(message="Bucket already exists", bucket_name=bucket_name)
    else:
        logger.info(f"Bucket '{bucket_name}' does not exist. Creating...")
        return create_s3_bucket(s3_client, bucket_name)
