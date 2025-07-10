from abc import ABC

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from pydantic import validate_call

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.logging import logger
from depictio.models.models.s3 import PolarsStorageOptions


class S3ProviderBase(ABC):
    def __init__(self, config: S3DepictioCLIConfig):
        self.config = config
        self.bucket_name = config.bucket
        self.endpoint_url = config.endpoint_url
        self.service_name = config.service_name
        self.access_key = config.root_user
        self.secret_key = config.root_password
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )

    def check_s3_accessibility(self) -> bool:
        """
        Check only S3 storage accessibility without checking specific bucket.

        Returns:
            bool: True if S3 is accessible, False otherwise
        """
        try:
            self.s3_client.list_buckets()
            logger.info("S3 storage is accessible.")
            return True
        except (NoCredentialsError, PartialCredentialsError):
            logger.error("Invalid credentials for S3.")
            return False
        except Exception as e:
            logger.error(f"Error accessing S3: {e}")
            return False

    def check_bucket_accessibility(self) -> bool:
        """
        Check if the specific bucket is accessible.

        Returns:
            bool: True if bucket exists and is accessible, False otherwise
        """
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"Bucket '{self.bucket_name}' is accessible.")
            return True
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                logger.error(f"Bucket '{self.bucket_name}' does not exist.")
            else:
                logger.error(
                    f"Bucket '{self.bucket_name}' is not accessible: {e.response['Error']['Message']}"
                )
            return False

    def check_write_policy(self) -> bool:
        """
        Check if write operations are possible in the bucket.

        Returns:
            bool: True if write is possible, False otherwise
        """
        try:
            test_key = ".depictio/write_test"
            self.s3_client.put_object(Bucket=self.bucket_name, Key=test_key, Body="test")
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=test_key)
            logger.info("Write policy is correctly configured.")
            return True
        except ClientError as e:
            logger.error(f"Write policy check failed: {e.response['Error']['Message']}")
            return False

    def suggest_adjustments(self, checks: list[str] | None = None) -> None:
        """
        Perform specified S3 checks and suggest adjustments.

        Args:
            checks: Optional list of checks to perform.
                    Options: ['s3', 'bucket', 'write']
        """
        if checks is None:
            checks = ["s3", "bucket", "write"]

        suggestions = []

        if "s3" in checks and not self.check_s3_accessibility():
            suggestions.append("Verify the endpoint URL, access key, and secret key.")

        if "bucket" in checks and not self.check_bucket_accessibility():
            suggestions.append(f"Ensure the bucket '{self.bucket_name}' exists and is accessible.")

        if "write" in checks and not self.check_write_policy():
            suggestions.append("Adjust bucket policies to allow write access for this client.")

        if suggestions:
            logger.error("Suggested Adjustments:")
            for suggestion in suggestions:
                logger.error(f"- {suggestion}")
            raise Exception("S3 storage is not correctly configured.")
        else:
            logger.info("No adjustments needed.")


class MinIOManager(S3ProviderBase):
    def __init__(self, config: S3DepictioCLIConfig):
        logger.info("Initializing MinIOManager...")
        logger.info(f"DEPICTIO_CONTEXT: {DEPICTIO_CONTEXT}")
        logger.info(f"Initializing MinIOManager with bucket '{config.bucket}'")
        super().__init__(config)


@validate_call
def S3_storage_checks(s3_config: S3DepictioCLIConfig, checks: list[str] | None = None):
    """
    Flexible S3 storage checks.

    Args:
        s3_config: S3 configuration
        checks: Optional list of checks to perform.
                Options: ['s3', 'bucket', 'write']
    """
    logger.info("Checking S3 accessibility...")
    logger.debug(f"S3 config: {s3_config}")
    minio_manager = MinIOManager(s3_config)
    logger.info("MinIOManager initialized.")
    minio_manager.suggest_adjustments(checks)


@validate_call
def turn_S3_config_into_polars_storage_options(
    s3_config: S3DepictioCLIConfig,
) -> PolarsStorageOptions:
    """
    Convert S3 configuration into storage options for the client.
    """
    logger.debug("Converting S3 config to Polars storage options...")
    logger.debug(f"S3 config: {s3_config}")
    logger.debug("Using endpoint URL: %s", s3_config.endpoint_url)
    logger.debug("Using public URL: %s", s3_config.public_url)

    # return PolarsStorageOptions(
    #     endpoint_url=s3_config.endpoint_url,
    #     aws_access_key_id=s3_config.root_user,
    #     aws_secret_access_key=s3_config.root_password,
    # )
    return PolarsStorageOptions.from_s3_config(s3_config)
