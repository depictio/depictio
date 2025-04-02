from depictio.api.v1.configs.logging import logger
from depictio.api.v1.configs.config import settings
from depictio.api.v1.s3 import s3_client
from fastapi import HTTPException
from botocore.exceptions import ClientError

def create_bucket(current_user):
    """
    Create a bucket in the MinIO server.
    """
    # Check if the user is an admin
    if not current_user.is_admin:
        logger.warning(f"Unauthorized bucket creation attempt by user: {current_user.email}")
        raise HTTPException(status_code=403, detail="User is not an admin.")

    bucket_name = settings.minio.bucket
    logger.debug(f"Bucket name retrieved from settings: {bucket_name}")

    # Check if the bucket already exists
    try:
        logger.info(f"Checking if bucket '{bucket_name}' already exists.")
        s3_client.head_bucket(Bucket=bucket_name)
        logger.info(f"Bucket '{bucket_name}' already exists.")
        return {"message": "Bucket already exists"}
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            logger.info(f"Bucket '{bucket_name}' does not exist. Attempting to create it.")
            try:
                s3_client.create_bucket(Bucket=bucket_name)
                logger.info(f"Bucket '{bucket_name}' created successfully.")
                return {"message": "Bucket created"}
            except Exception as create_error:
                logger.error(f"Failed to create bucket '{bucket_name}': {str(create_error)}")
                raise HTTPException(status_code=500, detail="Bucket creation failed.")
        else:
            logger.error(f"Error checking bucket existence: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error checking bucket existence: {error_code}")
    except Exception as e:
        logger.error(f"Unexpected error during bucket existence check: {str(e)}")
        raise HTTPException(status_code=500, detail="Unexpected error occurred.")