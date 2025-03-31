import boto3
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging import logger


from depictio_models.s3_utils import S3_storage_checks
from depictio_models.models.s3 import MinIOS3Config


minio_storage_options = {
    "endpoint_url": f"{settings.minio.internal_endpoint}:{settings.minio.port}",
    "aws_access_key_id": settings.minio.root_user,
    "aws_secret_access_key": settings.minio.root_password,
    "use_ssl": "false",
    "AWS_REGION": "us-east-1",
    "signature_version": "s3v4",
    "AWS_ALLOW_HTTP": "true",
    "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
}
logger.info(f"minio_storage_options {minio_storage_options}")

minios3_external_config = MinIOS3Config(
    provider="minio",
    bucket=settings.minio.bucket,
    endpoint=f"{settings.minio.external_endpoint}",
    port=settings.minio.port,
    minio_root_user=settings.minio.root_user,
    minio_root_password=settings.minio.root_password,
)

minios3_internal_config = MinIOS3Config(
    provider="minio",
    bucket=settings.minio.bucket,
    endpoint=f"{settings.minio.internal_endpoint}",
    port=settings.minio.port,
    minio_root_user=settings.minio.root_user,
    minio_root_password=settings.minio.root_password,
)


# Initialize your S3 client outside of your endpoint function
s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.minio.root_user,
    aws_secret_access_key=settings.minio.root_password,
    endpoint_url=f"{settings.minio.internal_endpoint}:{settings.minio.port}",
)
