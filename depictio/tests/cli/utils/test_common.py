from datetime import datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from typer import Exit

# Remove this line as we already import datetime later
from depictio.cli.cli.utils.common import (
    format_timestamp,
    generate_api_headers,
    load_depictio_config,
    validate_depictio_cli_config,
)
from depictio.models.models.cli import CLIConfig


class TestCommon:
    """Test suite for common utility functions"""

    @pytest.fixture
    def sample_cli_config(self):
        """Sample CLI configuration dictionary"""
        return {
            "user": {
                "email": "test@example.com",
                "is_admin": False,
                "id": "507f1f77bcf86cd799439011",
                "token": {
                    "user_id": "507f1f77bcf86cd799439011",
                    "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l",
                    "refresh_token": "refresh-token-example",
                    "token_type": "bearer",
                    "token_lifetime": "short-lived",
                    "expire_datetime": "2025-12-31T23:59:59",
                    "refresh_expire_datetime": "2025-12-31T23:59:59",
                    "name": "test_token",
                    "created_at": "2025-06-30T18:00:00",
                    "logged_in": False,
                },
            },
            "api_base_url": "https://api.depictio.dev",
            "s3_storage": {
                "service_name": "minio",
                "service_port": 9000,
                "external_host": "localhost",
                "external_port": 9000,
                "external_protocol": "http",
                "root_user": "minio",
                "root_password": "minio123",
                "bucket": "depictio-bucket",
            },
        }

    @pytest.fixture
    def sample_cli_config_object(self, sample_cli_config):
        """Sample CLI configuration as a CLIConfig object"""
        return CLIConfig(**sample_cli_config)  # type: ignore[missing-argument]

    class TestGenerateApiHeaders:
        """Tests for generate_api_headers function"""

        def test_with_dict(self, sample_cli_config):
            """Test generate_api_headers with dictionary input"""
            headers = generate_api_headers(sample_cli_config)
            assert headers == {
                "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l"
            }
            assert len(headers) == 1
            assert "Authorization" in headers

        def test_with_object(self, sample_cli_config_object):
            """Test generate_api_headers with CLIConfig object input"""
            headers = generate_api_headers(sample_cli_config_object)
            assert headers == {
                "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l"
            }

        def test_with_invalid_input(self):
            """Test generate_api_headers with invalid input type"""
            with pytest.raises(ValidationError):
                generate_api_headers("not_a_dict_or_object")

        def test_with_empty_input(self):
            """Test generate_api_headers with empty input"""
            with pytest.raises(ValueError):
                generate_api_headers(None)

    class TestFormatTimestamp:
        """Tests for format_timestamp function"""

        def test_valid_timestamp(self):
            """Test format_timestamp with a valid timestamp"""
            # Using a fixed timestamp (2023-01-01 12:00:00)
            timestamp = 1672574400.0
            formatted = format_timestamp(timestamp)
            # Instead of hardcoding the expected time, calculate it based on the same method
            expected = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            assert formatted == expected

        def test_invalid_timestamp(self):
            """Test format_timestamp with an invalid timestamp"""
            # Using an invalid timestamp
            with pytest.raises(ValidationError):
                format_timestamp("not_a_timestamp")

    class TestValidateDepictioCliConfig:
        """Tests for validate_depictio_cli_config function"""

        def test_valid_config(self, sample_cli_config):
            """Test validate_depictio_cli_config with valid config"""
            with patch("depictio.cli.cli.utils.common.logger"):
                result = validate_depictio_cli_config(sample_cli_config)
                assert isinstance(result, CLIConfig)
                config_dict = result.model_dump()
                assert (
                    config_dict["user"]["token"]["access_token"]
                    == "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l"
                )
                assert config_dict["api_base_url"] == "https://api.depictio.dev"
                assert config_dict["s3_storage"]["bucket"] == "depictio-bucket"

        def test_invalid_config(self):
            """Test validate_depictio_cli_config with invalid config"""
            with pytest.raises(Exception):
                validate_depictio_cli_config({"invalid": "config"})

    class TestLoadDepictioConfig:
        """Tests for load_depictio_config function"""

        def test_success(self):
            """Test successful loading of config file"""
            mock_config = {
                "user": {
                    "email": "test@example.com",
                    "is_admin": False,
                    "id": "507f1f77bcf86cd799439011",
                    "token": {
                        "user_id": "507f1f77bcf86cd799439011",
                        "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l",
                        "refresh_token": "refresh-token-example",
                        "token_type": "bearer",
                        "token_lifetime": "short-lived",
                        "expire_datetime": "2025-12-31T23:59:59",
                        "refresh_expire_datetime": "2025-12-31T23:59:59",
                        "name": "test_token",
                        "created_at": "2025-06-30T18:00:00",
                        "logged_in": False,
                    },
                },
                "api_base_url": "https://api.depictio.dev",
                "s3_storage": {
                    "service_name": "minio",
                    "service_port": 9000,
                    "external_host": "localhost",
                    "external_port": 9000,
                    "external_protocol": "http",
                    "root_user": "minio",
                    "root_password": "minio123",
                    "bucket": "depictio-bucket",
                },
            }

            # Mock the get_config and validate_depictio_cli_config functions
            with (
                patch("depictio.cli.cli.utils.common.get_config") as mock_get_config,
                patch(
                    "depictio.cli.cli.utils.common.validate_depictio_cli_config"
                ) as mock_validate,
                patch("depictio.cli.cli.utils.common.rich_print_checked_statement"),
            ):
                mock_get_config.return_value = mock_config
                mock_validate.return_value = CLIConfig(
                    api_base_url=mock_config["api_base_url"],
                    user=mock_config["user"],
                    s3_storage=mock_config["s3_storage"],
                )

                result = load_depictio_config()

                # Verify that the functions were called
                mock_get_config.assert_called_once()
                mock_validate.assert_called_once_with(mock_config)

                # Verify the result
                assert isinstance(result, CLIConfig)

        def test_file_not_found(self):
            """Test load_depictio_config when file is not found"""
            # Mock the get_config function to raise FileNotFoundError
            with (
                patch("depictio.cli.cli.utils.common.get_config") as mock_get_config,
                patch("depictio.cli.cli.utils.common.rich_print_checked_statement"),
                patch("depictio.cli.cli.utils.common.logger"),
            ):
                mock_get_config.side_effect = FileNotFoundError()

                with pytest.raises(Exit):
                    load_depictio_config()
