from abc import ABC, abstractmethod
from pydantic import validate_call
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

from depictio.models.models.users import CLIConfig
from depictio.models.models.s3 import MinioConfig, PolarsStorageOptions
from depictio.cli.logging import logger

from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement


class S3ProviderBase(ABC):
    def __init__(self, bucket_name):
        self.bucket_name = bucket_name

    @abstractmethod
    def check_s3_accessibility(self):
        pass

    @abstractmethod
    def check_bucket_accessibility(self):
        pass

    @abstractmethod
    def check_write_policy(self):
        pass

    def suggest_adjustments(self):
        suggestions = []
        if not self.check_s3_accessibility():
            suggestions.append("Verify the endpoint URL, access key, and secret key.")
        if not self.check_bucket_accessibility():
            suggestions.append(
                f"Ensure the bucket '{self.bucket_name}' exists and is accessible."
            )
        if not self.check_write_policy():
            suggestions.append(
                "Adjust bucket policies to allow write access for this client."
            )

        if suggestions:
            rich_print_checked_statement(
                "S3 storage is not correctly configured, use --verbose for more details.",
                "error",
            )
            logger.error("Suggested Adjustments:")
            for suggestion in suggestions:
                logger.error(f"- {suggestion}")
        else:
            rich_print_checked_statement(
                "S3 storage is correctly configured.", "success"
            )
            logger.info("No adjustments needed.")


class MinIOManager(S3ProviderBase):
    def __init__(self, config: MinioConfig):
        logger.info(f"Initializing MinIOManager with bucket '{config.bucket}'")
        super().__init__(config.bucket)
        self.endpoint_url = f"{config.endpoint}:{config.port}"
        self.access_key = config.minio_root_user
        self.secret_key = config.minio_root_password
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )

    def check_s3_accessibility(self):
        try:
            self.s3_client.list_buckets()
            logger.info("S3 is accessible.")
            return True
        except (NoCredentialsError, PartialCredentialsError):
            logger.error("Invalid credentials for S3.")
            return False
        except Exception as e:
            logger.error(f"Error accessing S3: {e}")
            return False

    def check_bucket_accessibility(self):
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

    def check_write_policy(self):
        try:
            test_key = ".depictio/"
            self.s3_client.put_object(
                Bucket=self.bucket_name, Key=test_key, Body="test"
            )
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=test_key)
            logger.info("Write policy is correctly configured.")
            return True
        except ClientError as e:
            logger.info(f"Write policy check failed: {e.response['Error']['Message']}")
            return False


# if __name__ == "__main__":
#     # Load configuration
#     config = MinioConfig()

#     # Initialize MinIOManager with configuration
#     s3_manager = MinIOManager(config)

#     # Perform checks and suggest adjustments
#     s3_manager.suggest_adjustments()


def S3_storage_checks(s3_config: MinioConfig):
    """
    Check if the S3 endpoint, access key, secret key, and bucket are accessible.
    """
    logger.info("Checking S3 accessibility...")
    logger.info(f"S3 config: {s3_config}")
    minio_manager = MinIOManager(s3_config)
    logger.info("MinIOManager initialized.")
    minio_manager.suggest_adjustments()


@validate_call
def turn_S3_config_into_polars_storage_options(cli_config: CLIConfig):
    """
    Convert S3 configuration into storage options for the client.
    """
    s3_config = cli_config.s3
    return PolarsStorageOptions(
        endpoint_url=f"{s3_config.endpoint_url}",
        aws_access_key_id=s3_config.root_user,
        aws_secret_access_key=s3_config.root_password,
    )
