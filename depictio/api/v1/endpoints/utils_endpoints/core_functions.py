from depictio.api.v1.configs.config import logger, settings
from depictio.api.v1.s3 import s3_client
from fastapi import HTTPException

def create_bucket(current_user):
    """
    Create a bucket in the MinIO server.
    """
    # Check if the user is an admin
    if not current_user.is_admin:
        logger.warn(f"Unauthorized bucket creation attempt by user: {current_user.username}")
        raise HTTPException(status_code=403, detail="User is not an admin.")

    bucket_name = settings.minio.bucket
    logger.debug(f"Bucket name retrieved from settings: {bucket_name}")

    # Check if the bucket already exists
    try:
        logger.info(f"Checking if bucket '{bucket_name}' already exists.")
        s3_client.head_bucket(Bucket=bucket_name)
        logger.info(f"Bucket '{bucket_name}' already exists.")
        return {"message": "Bucket already exists"}
    except s3_client.exceptions.NoSuchBucket:
        logger.info(f"Bucket '{bucket_name}' does not exist. Attempting to create it.")
        try:
            s3_client.create_bucket(Bucket=bucket_name)
            logger.info(f"Bucket '{bucket_name}' created successfully.")
            return {"message": "Bucket created"}
        except Exception as e:
            logger.error(f"Failed to create bucket '{bucket_name}': {str(e)}")
            return {"message": "Bucket creation failed"}
    except Exception as e:
        logger.error(f"Error checking bucket existence: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking bucket existence.")