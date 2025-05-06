from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from depictio.models.models.s3 import PolarsStorageOptions, S3DepictioCLIConfig
from depictio.models.s3_utils import (
    MinIOManager,
    S3_storage_checks,
    turn_S3_config_into_polars_storage_options,
)


class TestS3Utils:
    """Test suite for S3 utility functions"""

    @pytest.fixture
    def sample_s3_config(self):
        """Sample S3 configuration"""
        return S3DepictioCLIConfig(
            endpoint_url="http://localhost:9000",
            root_user="minio",
            root_password="minio123",
            bucket="depictio-bucket",
        )

    class TestS3StorageChecks:
        """Tests for S3_storage_checks function"""

        def test_all_checks_pass(self, sample_s3_config):
            """Test when all S3 checks pass"""

            # Create a mock MinIOManager where all checks return True
            mock_minio_manager = MagicMock()

            # Patch the MinIOManager constructor to return our mock
            with (
                patch(
                    "depictio.models.s3_utils.MinIOManager",
                    return_value=mock_minio_manager,
                ),
                patch("depictio.models.s3_utils.logger"),
            ):
                # Call the function
                S3_storage_checks(sample_s3_config)

                # Verify that suggest_adjustments was called once
                mock_minio_manager.suggest_adjustments.assert_called_once()

        def test_specific_checks(self, sample_s3_config):
            """Test with specific checks provided"""

            # Create a mock MinIOManager
            mock_minio_manager = MagicMock()

            # List of specific checks to perform
            checks = ["s3", "bucket"]

            # Patch the MinIOManager constructor to return our mock
            with (
                patch(
                    "depictio.models.s3_utils.MinIOManager",
                    return_value=mock_minio_manager,
                ),
                patch("depictio.models.s3_utils.logger"),
            ):
                # Call the function with specific checks
                S3_storage_checks(sample_s3_config, checks=checks)

                # Verify suggest_adjustments was called with the right checks
                mock_minio_manager.suggest_adjustments.assert_called_once_with(checks)

        def test_minio_manager_exception(self, sample_s3_config):
            """Test when MinIOManager initialization raises an exception"""

            # Patch MinIOManager to raise an exception
            with (
                patch(
                    "depictio.models.s3_utils.MinIOManager",
                    side_effect=Exception("Connection error"),
                ),
                patch("depictio.models.s3_utils.logger"),
            ):
                # Call should raise the exception
                with pytest.raises(Exception, match="Connection error"):
                    S3_storage_checks(sample_s3_config)

        def test_suggest_adjustments_exception(self, sample_s3_config):
            """Test when suggest_adjustments raises an exception"""

            # Create a mock MinIOManager where suggest_adjustments raises an exception
            mock_minio_manager = MagicMock()
            mock_minio_manager.suggest_adjustments.side_effect = Exception(
                "S3 storage is not correctly configured"
            )

            # Patch the MinIOManager constructor to return our mock
            with (
                patch(
                    "depictio.models.s3_utils.MinIOManager",
                    return_value=mock_minio_manager,
                ),
                patch("depictio.models.s3_utils.logger"),
            ):
                # Call should raise the exception
                with pytest.raises(Exception, match="S3 storage is not correctly configured"):
                    S3_storage_checks(sample_s3_config)

    class TestTurnS3ConfigIntoPolarsStorageOptions:
        """Tests for turn_S3_config_into_polars_storage_options function"""

        def test_conversion(self, sample_s3_config):
            """Test conversion of S3 config to Polars storage options"""

            # Call the function
            result = turn_S3_config_into_polars_storage_options(sample_s3_config)

            # Verify the result is a PolarsStorageOptions object
            assert isinstance(result, PolarsStorageOptions)

            # Verify the values were correctly transferred
            assert result.endpoint_url == "http://localhost:9000"
            assert result.aws_access_key_id == "minio"
            assert result.aws_secret_access_key == "minio123"

        def test_different_endpoint(self, sample_s3_config):
            """Test with a different endpoint URL"""

            # Modify the sample config
            sample_s3_config.endpoint_url = "https://custom-s3.example.com"

            # Call the function
            result = turn_S3_config_into_polars_storage_options(sample_s3_config)

            # Verify the endpoint was correctly transferred
            assert result.endpoint_url == "https://custom-s3.example.com"

            # Verify other fields
            assert result.aws_access_key_id == "minio"
            assert result.aws_secret_access_key == "minio123"

        def test_different_credentials(self, sample_s3_config):
            """Test with different access credentials"""

            # Modify the sample config
            sample_s3_config.root_user = "custom-user"
            sample_s3_config.root_password = "custom-password"

            # Call the function
            result = turn_S3_config_into_polars_storage_options(sample_s3_config)

            # Verify the credentials were correctly transferred
            assert result.aws_access_key_id == "custom-user"
            assert result.aws_secret_access_key == "custom-password"

            # Verify endpoint
            assert result.endpoint_url == "http://localhost:9000"

        def test_validation(self):
            """Test that validation is applied to the input"""

            # Try calling with an invalid type
            with pytest.raises(ValidationError):
                turn_S3_config_into_polars_storage_options("not_a_config")


# Test suite for the MinIOManager class itself, optional but comprehensive
class TestMinIOManager:
    """Test suite for MinIOManager class"""

    @pytest.fixture
    def sample_s3_config(self):
        """Sample S3 configuration"""
        return S3DepictioCLIConfig(
            endpoint_url="http://localhost:9000",
            root_user="minio",
            root_password="minio123",
            bucket="depictio-bucket",
        )

    @pytest.fixture
    def mock_boto3_client(self):
        """Mock boto3 client for S3"""
        mock_client = MagicMock()
        return mock_client

    def test_initialization(self, sample_s3_config):
        """Test MinIOManager initialization"""

        # Patch boto3.client to avoid actual S3 connection
        with (
            patch("boto3.client", return_value=MagicMock()),
            patch("depictio.models.s3_utils.logger"),
        ):
            # Initialize MinIOManager
            manager = MinIOManager(sample_s3_config)

            # Verify attributes
            assert manager.endpoint_url == "http://localhost:9000"
            assert manager.access_key == "minio"
            assert manager.secret_key == "minio123"
            assert manager.bucket_name == "depictio-bucket"

    def test_check_s3_accessibility_success(self, sample_s3_config, mock_boto3_client):
        """Test successful S3 accessibility check"""

        # Patch boto3.client to return our mock
        with (
            patch("boto3.client", return_value=mock_boto3_client),
            patch("depictio.models.s3_utils.logger"),
        ):
            # Initialize MinIOManager
            manager = MinIOManager(sample_s3_config)

            # Mock list_buckets to return successfully
            mock_boto3_client.list_buckets.return_value = {"Buckets": []}

            # Call and verify result
            result = manager.check_s3_accessibility()
            assert result is True
            mock_boto3_client.list_buckets.assert_called_once()

    def test_check_s3_accessibility_error(self, sample_s3_config, mock_boto3_client):
        """Test S3 accessibility check with error"""

        # Patch boto3.client to return our mock
        with (
            patch("boto3.client", return_value=mock_boto3_client),
            patch("depictio.models.s3_utils.logger"),
        ):
            # Initialize MinIOManager
            manager = MinIOManager(sample_s3_config)

            # Mock list_buckets to raise an exception
            mock_boto3_client.list_buckets.side_effect = Exception("Connection error")

            # Call and verify result
            result = manager.check_s3_accessibility()
            assert result is False
            mock_boto3_client.list_buckets.assert_called_once()

    def test_suggest_adjustments_all_pass(self, sample_s3_config):
        """Test suggest_adjustments when all checks pass"""

        # Create a partial mock of MinIOManager to control check results
        with (
            patch("boto3.client", return_value=MagicMock()),
            patch.object(MinIOManager, "check_s3_accessibility", return_value=True),
            patch.object(MinIOManager, "check_bucket_accessibility", return_value=True),
            patch.object(MinIOManager, "check_write_policy", return_value=True),
            patch("depictio.models.s3_utils.logger"),
        ):
            # Initialize MinIOManager
            manager = MinIOManager(sample_s3_config)

            # Call suggest_adjustments
            # Should not raise any exception
            manager.suggest_adjustments()

    def test_suggest_adjustments_with_failures(self, sample_s3_config):
        """Test suggest_adjustments when some checks fail"""

        # Create a partial mock of MinIOManager to control check results
        with (
            patch("boto3.client", return_value=MagicMock()),
            patch.object(MinIOManager, "check_s3_accessibility", return_value=False),
            patch.object(MinIOManager, "check_bucket_accessibility", return_value=True),
            patch.object(MinIOManager, "check_write_policy", return_value=False),
            patch("depictio.models.s3_utils.logger"),
        ):
            # Initialize MinIOManager
            manager = MinIOManager(sample_s3_config)

            # Call suggest_adjustments, should raise exception
            with pytest.raises(Exception, match="S3 storage is not correctly configured"):
                manager.suggest_adjustments()
