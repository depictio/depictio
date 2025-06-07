import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig

# from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.models.s3 import PolarsStorageOptions
from depictio.models.s3_utils import S3_storage_checks, turn_S3_config_into_polars_storage_options


class TestS3DepictioCLIConfig:
    def test_url_client_and_server_context(self):
        with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "client"}):
            cfg = S3DepictioCLIConfig(
                service_name="svc",
                service_port=9000,
                external_host="example.com",
                external_port=1234,
            )
            assert cfg.url == "http://example.com:1234"
            assert cfg.endpoint_url == "http://example.com:1234"

        with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "server"}):
            cfg = S3DepictioCLIConfig(service_name="svc", service_port=9000)
            assert cfg.url == "http://svc:9000"

    def test_public_url_override(self):
        with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "client"}):
            cfg = S3DepictioCLIConfig(public_url="https://public.example")
            assert cfg.url == "https://public.example"

    def test_aliases(self):
        cfg = S3DepictioCLIConfig(external_host="host", external_port=9999)
        assert cfg.host == "host"
        assert cfg.port == 9999

    def test_environment_variable_override(self):
        env = {
            "DEPICTIO_MINIO_SERVICE_NAME": "env",
            "DEPICTIO_MINIO_EXTERNAL_HOST": "envhost",
            "DEPICTIO_MINIO_EXTERNAL_PORT": "1111",
        }
        with patch.dict(os.environ, env):
            cfg = S3DepictioCLIConfig()
            assert cfg.service_name == "env"
            assert cfg.external_host == "envhost"
            assert cfg.external_port == 1111


class TestS3Utils:
    """Test suite for S3 utility functions"""

    @pytest.fixture
    def sample_s3_config(self):
        """Sample S3 configuration"""
        return S3DepictioCLIConfig(
            external_host="localhost",
            external_port=9000,
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

        def test_conversion_client(self, sample_s3_config):
            """Test conversion of S3 config to Polars storage options for client context"""

            with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "client"}):
                # Call the function
                result = turn_S3_config_into_polars_storage_options(sample_s3_config)

                # Verify the result is a PolarsStorageOptions object
                assert isinstance(result, PolarsStorageOptions)

                # Verify the values were correctly transferred
                assert result.endpoint_url == "http://localhost:9000"
                assert result.aws_access_key_id == "minio"
                assert result.aws_secret_access_key == "minio123"

        def test_conversion_server(self, sample_s3_config):
            """Test conversion of S3 config to Polars storage options for server context"""

            with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "server"}):
                # Call the function
                result = turn_S3_config_into_polars_storage_options(sample_s3_config)

                # Verify the result is a PolarsStorageOptions object
                assert isinstance(result, PolarsStorageOptions)

                # Verify the values were correctly transferred
                assert result.endpoint_url == "http://minio:9000"
                assert result.aws_access_key_id == "minio"
                assert result.aws_secret_access_key == "minio123"

        def test_different_endpoint_client(self, sample_s3_config):
            """Test with a different endpoint URL"""
            with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "client"}):
                # Modify the sample config
                sample_s3_config.public_url = "https://custom-s3.example.com"

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

        def test_different_endpoint_server(self, sample_s3_config):
            """Test with a different endpoint URL"""
            with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "server"}):
                # Modify the sample config
                sample_s3_config.public_url = "https://custom-s3.example.com"

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

        def test_different_credentials_client(self, sample_s3_config):
            """Test with different access credentials"""

            with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "client"}):
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

        def test_different_credentials_server(self, sample_s3_config):
            """Test with different access credentials"""

            with patch.dict(os.environ, {"DEPICTIO_CONTEXT": "server"}):
                # Modify the sample config
                sample_s3_config.root_user = "custom-user"
                sample_s3_config.root_password = "custom-password"

                # Call the function
                result = turn_S3_config_into_polars_storage_options(sample_s3_config)

                # Verify the credentials were correctly transferred
                assert result.aws_access_key_id == "custom-user"
                assert result.aws_secret_access_key == "custom-password"

                # Verify endpoint
                assert result.endpoint_url == "http://minio:9000"

        def test_validation(self):
            """Test that validation is applied to the input"""

            # Try calling with an invalid type
            with pytest.raises(ValidationError):
                turn_S3_config_into_polars_storage_options("not_a_config")
