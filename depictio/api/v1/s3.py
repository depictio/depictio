import boto3
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.custom_logging import logger


# from depictio_models.s3_utils import S3_storage_checks
from depictio_models.models.s3 import S3DepictioCLIConfig


minio_storage_options = {
    "endpoint_url": f"{settings.minio.endpoint_url}",
    "aws_access_key_id": settings.minio.root_user,
    "aws_secret_access_key": settings.minio.root_password,
    "use_ssl": "false",
    "AWS_REGION": "us-east-1",
    "signature_version": "s3v4",
    "AWS_ALLOW_HTTP": "true",
    "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
}
logger.info(f"minio_storage_options {minio_storage_options}")

minios3_external_config = S3DepictioCLIConfig(
    # provider="minio",
    bucket=settings.minio.bucket,
    endpoint_url=f"{settings.minio.endpoint_url}",
    # port=settings.minio.port,
    # root_user=settings.minio.root_user,
    # root_password=settings.minio.root_password,
)


# Initialize your S3 client outside of your endpoint function
s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.minio.root_user,
    aws_secret_access_key=settings.minio.root_password,
    endpoint_url=settings.minio.endpoint_url,
    # aws_session_token=None,
    # verify=False,
)
logger.info(f"minio s3 client {s3_client}")
logger.info(f"Successfully created S3 client with endpoint: {settings.minio.endpoint_url}")
