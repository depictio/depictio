import boto3

from depictio.api.v1.configs.config import settings
from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

polars_s3_config = turn_S3_config_into_polars_storage_options(settings.s3).model_dump(
    exclude_none=True
)


# Initialize your S3 client outside of your endpoint function
s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.s3.aws_access_key_id,
    aws_secret_access_key=settings.s3.aws_secret_access_key,
    endpoint_url=settings.s3.endpoint_url,
    verify=settings.s3.verify_tls,
)
