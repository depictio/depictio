import boto3

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

polars_s3_config = turn_S3_config_into_polars_storage_options(settings.minio).model_dump(
    exclude_none=True
)
logger.debug(f"polars_s3_config: {polars_s3_config}")


# Initialize your S3 client outside of your endpoint function
s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.minio.root_user,
    aws_secret_access_key=settings.minio.root_password,
    endpoint_url=settings.minio.endpoint_url,
    # aws_session_token=None,
    # verify=False,
)
logger.debug(f"minio s3 client {s3_client}")
logger.info(f"Successfully created S3 client with endpoint: {settings.minio.endpoint_url}")
