import re
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

# from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.models.s3 import PolarsStorageOptions, S3DepictioCLIConfig
from depictio.models.s3_utils import S3_storage_checks, turn_S3_config_into_polars_storage_options


class TestS3DepictioCLIConfig:
    def test_endpoint_url_with_client_context(self):
        """Test that endpoint URL remains unchanged in client context."""
        with patch("depictio.models.models.s3.DEPICTIO_CONTEXT", "cli"):
            config = S3DepictioCLIConfig(
                service_name="test-service",
                endpoint_url="http://original-endpoint:8000",
                on_premise_service=False,
            )

            # Verify endpoint_url remains unchanged in client context
            assert config.endpoint_url == "http://original-endpoint:8000"
            # Verify port was extracted correctly
            assert config.port == 8000

    def test_endpoint_url_with_server_context(self):
        """Test that endpoint URL is updated in server context with on-premise service."""
        with patch("depictio.models.models.s3.DEPICTIO_CONTEXT", "server"):
            config = S3DepictioCLIConfig(
                service_name="test-service",
                endpoint_url="http://original-endpoint:8000",
                on_premise_service=True,
            )

            # Verify endpoint_url was updated in server context with on-premise service
            assert config.endpoint_url == "http://test-service:8000"

    def test_endpoint_url_with_server_context_but_not_on_premise(self):
        """Test that endpoint URL remains unchanged in server context but not on-premise."""
        with patch("depictio.models.models.s3.DEPICTIO_CONTEXT", "server"):
            config = S3DepictioCLIConfig(
                service_name="test-service",
                endpoint_url="http://original-endpoint:8000",
                on_premise_service=False,
            )

            # Verify endpoint_url remains unchanged when not on-premise
            assert config.endpoint_url == "http://original-endpoint:8000"

    def test_default_port_when_not_specified(self):
        """Test that default port is used when not specified in the endpoint URL."""
        with patch("depictio.models.models.s3.DEPICTIO_CONTEXT", "server"):
            config = S3DepictioCLIConfig(
                service_name="test-service",
                endpoint_url="http://original-endpoint",
                on_premise_service=True,
            )

            # Verify default port is used
            assert config.endpoint_url == "http://test-service:9000"
            assert config.port == 0  # Default value from Field

    def test_custom_port_override(self):
        """Test that explicitly setting port overrides extracted port."""
        with patch("depictio.models.models.s3.DEPICTIO_CONTEXT", "server"):
            config = S3DepictioCLIConfig(
                service_name="test-service",
                endpoint_url="http://original-endpoint:8000",
                port=7000,  # Explicitly set different port
                on_premise_service=True,
            )

            # Port from URL should be extracted, but endpoint should use the port field value
            assert config.port == 8000  # Port extracted from URL
            assert config.endpoint_url == "http://test-service:8000"  # Uses extracted port

    def test_with_none_context(self):
        """Test behavior when DEPICTIO_CONTEXT is None."""
        with patch("depictio.models.models.s3.DEPICTIO_CONTEXT", None):
            config = S3DepictioCLIConfig(
                service_name="test-service",
                endpoint_url="http://original-endpoint:8000",
                on_premise_service=False,
            )

            # Verify endpoint_url remains unchanged when context is None
            assert config.endpoint_url == "http://original-endpoint:8000"

    def test_environment_variable_override(self):
        """Test that environment variables override default values."""
        with (
            patch("depictio.models.models.s3.DEPICTIO_CONTEXT", "server"),
            patch.dict(
                "os.environ",
                {
                    "DEPICTIO_MINIO_SERVICE_NAME": "env-service",
                    "DEPICTIO_MINIO_ENDPOINT_URL": "http://env-endpoint:9999",
                    "DEPICTIO_MINIO_ON_PREMISE_SERVICE": "true",
                },
            ),
        ):
            # Force reload of settings from environment
            config = S3DepictioCLIConfig()

            # Verify values from environment are used
            assert config.service_name == "env-service"
            assert config.endpoint_url == "http://env-service:9999"  # Updated by validator
            assert config.port == 9999
            assert config.on_premise_service is True

    def test_port_extraction_from_complex_url(self):
        """Test port extraction from URLs with various formats."""
        test_cases = [
            # URL, expected port
            ("http://localhost:1234", 1234),
            ("https://service.domain.com:443", 443),
            ("http://service:80", 80),
            # No port cases
            ("http://localhost", 0),  # Should use default
        ]

        for url, expected_port in test_cases:
            config = S3DepictioCLIConfig(endpoint_url=url)
            port_match = re.search(r":(\d+)(?:/|$)", config.endpoint_url)
            extracted_port = int(port_match.group(1)) if port_match else 0

            assert extracted_port == expected_port, f"Failed to extract port from {url}"


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
            # drop the port from model
            sample_s3_config.port = 0

            print(sample_s3_config.endpoint_url)
            print(f"Sample config: {sample_s3_config}")

            # Call the function
            result = turn_S3_config_into_polars_storage_options(sample_s3_config)
            print(f"Result: {result}")

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
