import boto3
from depictio.api.v1.configs.config import settings

minio_storage_options = {
    "endpoint_url": f"{settings.minio.internal_endpoint}:{settings.minio.port}",
    "aws_access_key_id": settings.minio.access_key,
    "aws_secret_access_key": settings.minio.secret_key,
    "use_ssl": "false",
    "AWS_REGION": "us-east-1",
    "signature_version": "s3v4",
    "AWS_ALLOW_HTTP": "true",
    "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
}


# Initialize your S3 client outside of your endpoint function
s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.minio.access_key,
    aws_secret_access_key=settings.minio.secret_key,
    endpoint_url=f"{settings.minio.internal_endpoint}:{settings.minio.port}",
)

