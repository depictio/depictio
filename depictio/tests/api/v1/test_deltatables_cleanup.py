"""Tests for Delta table cleanup functionality using actual S3 models."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.api.v1.endpoints.datacollections_endpoints.utils import _cleanup_s3_delta_table
from depictio.models.models.s3 import PolarsStorageOptions
from depictio.models.s3_utils import S3ProviderBase


class TestDeltaTableCleanupWithS3Models:
    """Test suite for Delta table cleanup using actual S3 models."""

    def setup_method(self):
        """Set up test fixtures."""
        # Sample data collection IDs
        self.dc_id = "507f1f77bcf86cd799439011"

        # Create proper S3 configuration using actual model
        self.s3_config = S3DepictioCLIConfig(
            service_name="minio",
            service_port=9000,
            external_host="localhost",
            external_port=9000,
            external_protocol="http",
            root_user="test_key",
            root_password="test_secret",
            bucket="test-bucket",
        )

        # Sample S3 objects for Delta table
        self.delta_objects = [
            {"Key": f"{self.dc_id}/part-00000-001.parquet"},
            {"Key": f"{self.dc_id}/part-00001-001.parquet"},
            {"Key": f"{self.dc_id}/_delta_log/00000000000000000000.json"},
            {"Key": f"{self.dc_id}/_delta_log/00000000000000000001.json"},
            {"Key": f"{self.dc_id}/_delta_log/00000000000000000001.checkpoint.parquet"},
        ]

    @pytest.mark.asyncio
    @patch("depictio.api.v1.endpoints.datacollections_endpoints.utils.settings")
    async def test_cleanup_s3_delta_table_success_with_models(self, mock_settings):
        """Test successful S3 Delta table cleanup using actual S3 models."""
        # Arrange - use actual S3 configuration model
        mock_settings.minio = self.s3_config

        with patch("boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.list_objects_v2.return_value = {"Contents": self.delta_objects}
            mock_boto3.return_value = mock_s3_client

            # Act
            await _cleanup_s3_delta_table(self.dc_id)

            # Assert
            mock_boto3.assert_called_once_with(
                "s3",
                endpoint_url=self.s3_config.endpoint_url,
                aws_access_key_id=self.s3_config.root_user,
                aws_secret_access_key=self.s3_config.root_password,
                region_name="us-east-1",
            )
            mock_s3_client.list_objects_v2.assert_called_once_with(
                Bucket=self.s3_config.bucket, Prefix=self.dc_id
            )
            mock_s3_client.delete_objects.assert_called_once()

            # Verify all Delta table files were included in deletion
            delete_call_args = mock_s3_client.delete_objects.call_args[1]
            deleted_keys = [obj["Key"] for obj in delete_call_args["Delete"]["Objects"]]
            assert len(deleted_keys) == 5
            assert all(key.startswith(self.dc_id) for key in deleted_keys)

    @pytest.mark.asyncio
    @patch("depictio.api.v1.endpoints.datacollections_endpoints.utils.settings")
    async def test_cleanup_s3_delta_table_empty_bucket_with_models(self, mock_settings):
        """Test cleanup when no objects exist using actual S3 models."""
        # Arrange
        mock_settings.minio = self.s3_config

        with patch("boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.list_objects_v2.return_value = {}  # No Contents key
            mock_boto3.return_value = mock_s3_client

            # Act
            await _cleanup_s3_delta_table(self.dc_id)

            # Assert
            mock_s3_client.list_objects_v2.assert_called_once()
            mock_s3_client.delete_objects.assert_not_called()

    @pytest.mark.asyncio
    @patch("depictio.api.v1.endpoints.datacollections_endpoints.utils.settings")
    async def test_cleanup_s3_delta_table_client_error_with_models(self, mock_settings):
        """Test error handling during S3 cleanup using actual S3 models."""
        # Arrange
        mock_settings.minio = self.s3_config

        with patch("boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.list_objects_v2.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},  # type: ignore[arg-type]
                "ListObjectsV2",
            )
            mock_boto3.return_value = mock_s3_client

            # Act (should not raise exception)
            await _cleanup_s3_delta_table(self.dc_id)

            # Assert
            mock_s3_client.list_objects_v2.assert_called_once()
            mock_s3_client.delete_objects.assert_not_called()


class TestS3ProviderWithActualModels:
    """Test suite for S3Provider using actual models from depictio.models."""

    def setup_method(self):
        """Set up test fixtures using actual S3 models."""
        self.s3_config = S3DepictioCLIConfig(
            service_name="minio",
            service_port=9000,
            external_host="localhost",
            external_port=9000,
            external_protocol="http",
            root_user="test_key",
            root_password="test_secret",
            bucket="test-bucket",
        )

    def test_s3_provider_initialization_with_actual_config(self):
        """Test S3Provider initialization with actual S3DepictioCLIConfig."""
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_boto3.return_value = mock_s3_client

            # Act
            s3_provider = S3ProviderBase(self.s3_config)

            # Assert
            assert s3_provider.bucket_name == self.s3_config.bucket
            assert s3_provider.endpoint_url == self.s3_config.endpoint_url
            assert s3_provider.access_key == self.s3_config.root_user
            assert s3_provider.secret_key == self.s3_config.root_password
            mock_boto3.assert_called_once_with(
                "s3",
                endpoint_url=self.s3_config.endpoint_url,
                aws_access_key_id=self.s3_config.root_user,
                aws_secret_access_key=self.s3_config.root_password,
            )

    def test_s3_provider_check_accessibility_success_with_models(self):
        """Test successful S3 accessibility check using actual models."""
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.list_buckets.return_value = {"Buckets": []}
            mock_boto3.return_value = mock_s3_client

            s3_provider = S3ProviderBase(self.s3_config)

            # Act
            result = s3_provider.check_s3_accessibility()

            # Assert
            assert result is True
            mock_s3_client.list_buckets.assert_called_once()

    def test_s3_provider_check_accessibility_failure_with_models(self):
        """Test S3 accessibility check failure using actual models."""
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.list_buckets.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},  # type: ignore[arg-type]
                "ListBuckets",
            )
            mock_boto3.return_value = mock_s3_client

            s3_provider = S3ProviderBase(self.s3_config)

            # Act
            result = s3_provider.check_s3_accessibility()

            # Assert
            assert result is False
            mock_s3_client.list_buckets.assert_called_once()

    def test_polars_storage_options_from_s3_config(self):
        """Test PolarsStorageOptions creation from S3DepictioCLIConfig."""
        # Act
        storage_options = PolarsStorageOptions.from_s3_config(self.s3_config)

        # Assert
        assert storage_options.endpoint_url == self.s3_config.url
        assert storage_options.aws_access_key_id == self.s3_config.root_user
        assert storage_options.aws_secret_access_key == self.s3_config.root_password
        assert storage_options.use_ssl == "false"
        assert storage_options.signature_version == "s3v4"
        assert storage_options.region == "us-east-1"

    def test_polars_storage_options_validation(self):
        """Test PolarsStorageOptions validation."""
        # Test valid configuration
        valid_options = PolarsStorageOptions(
            endpoint_url="http://localhost:9000",
            aws_access_key_id="test_key",
            aws_secret_access_key="test_secret",
        )
        assert valid_options.endpoint_url == "http://localhost:9000"

        # Test empty endpoint URL validation
        with pytest.raises(ValueError, match="Endpoint URL cannot be empty"):
            PolarsStorageOptions(
                endpoint_url="", aws_access_key_id="test_key", aws_secret_access_key="test_secret"
            )

    def test_s3_provider_bucket_accessibility_check(self):
        """Test S3Provider bucket accessibility check."""
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.head_bucket.return_value = {}
            mock_boto3.return_value = mock_s3_client

            s3_provider = S3ProviderBase(self.s3_config)

            # Act
            result = s3_provider.check_bucket_accessibility()

            # Assert
            assert result is True
            mock_s3_client.head_bucket.assert_called_once_with(Bucket=self.s3_config.bucket)

    def test_s3_provider_bucket_not_found(self):
        """Test S3Provider when bucket doesn't exist."""
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.head_bucket.side_effect = ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},  # type: ignore[arg-type]
                "HeadBucket",
            )
            mock_boto3.return_value = mock_s3_client

            s3_provider = S3ProviderBase(self.s3_config)

            # Act
            result = s3_provider.check_bucket_accessibility()

            # Assert
            assert result is False
            mock_s3_client.head_bucket.assert_called_once_with(Bucket=self.s3_config.bucket)

    def test_s3_provider_write_policy_check_success(self):
        """Test S3Provider write policy check success."""
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.put_object.return_value = {}
            mock_s3_client.delete_object.return_value = {}
            mock_boto3.return_value = mock_s3_client

            s3_provider = S3ProviderBase(self.s3_config)

            # Act
            result = s3_provider.check_write_policy()

            # Assert
            assert result is True
            mock_s3_client.put_object.assert_called_once_with(
                Bucket=self.s3_config.bucket, Key=".depictio/write_test", Body="test"
            )
            mock_s3_client.delete_object.assert_called_once_with(
                Bucket=self.s3_config.bucket, Key=".depictio/write_test"
            )

    def test_s3_provider_write_policy_check_failure(self):
        """Test S3Provider write policy check failure."""
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_s3_client = MagicMock()
            mock_s3_client.put_object.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Write access denied"}},  # type: ignore[arg-type]
                "PutObject",
            )
            mock_boto3.return_value = mock_s3_client

            s3_provider = S3ProviderBase(self.s3_config)

            # Act
            result = s3_provider.check_write_policy()

            # Assert
            assert result is False
            mock_s3_client.put_object.assert_called_once()

    def test_s3_config_model_validation(self):
        """Test S3DepictioCLIConfig model validation."""
        # Test valid configuration
        config = S3DepictioCLIConfig(
            service_name="minio",
            service_port=9000,
            external_host="localhost",
            external_port=9000,
            external_protocol="http",
            root_user="user",
            root_password="password",
            bucket="test-bucket",
        )
        assert config.service_name == "minio"
        assert config.external_host == "localhost"
        assert config.bucket == "test-bucket"

    def test_integrated_s3_storage_workflow(self):
        """Test integrated workflow using S3 models."""
        # Create S3 config
        config = S3DepictioCLIConfig(
            service_name="minio",
            service_port=9000,
            external_host="localhost",
            external_port=9000,
            external_protocol="http",
            root_user="test_user",
            root_password="test_pass",
            bucket="integration-bucket",
        )

        # Create PolarsStorageOptions from config
        storage_options = PolarsStorageOptions.from_s3_config(config)

        # Verify integration
        assert storage_options.endpoint_url == config.url
        assert storage_options.aws_access_key_id == config.root_user
        assert storage_options.aws_secret_access_key == config.root_password

        # Test S3Provider initialization
        with patch("depictio.models.s3_utils.boto3.client") as mock_boto3:
            mock_boto3.return_value = MagicMock()

            s3_provider = S3ProviderBase(config)
            assert s3_provider.bucket_name == config.bucket
            assert s3_provider.endpoint_url == config.endpoint_url
