"""The CLI configuration models tolerate a newer server's CLI.yaml.

A CLI.yaml is written by the server it was downloaded from. When that server is
newer, it may carry settings the installed CLI has never heard of: the CLI
configuration models ignore those (the CLI's loader reports them) instead of
failing, while required fields stay required.
"""

import pytest
from pydantic import ValidationError

from depictio.models.models.cli import CLIConfig, UserBaseCLIConfig

VALID_CONFIG = {
    "api_base_url": "https://api.depictio.dev",
    "user": {
        "email": "test@example.com",
        "is_admin": False,
        "id": "507f1f77bcf86cd799439011",
        "token": {
            "user_id": "507f1f77bcf86cd799439011",
            "access_token": "access-token-example",
            "refresh_token": "refresh-token-example",
            "token_type": "bearer",
            "token_lifetime": "short-lived",
            "expire_datetime": "2099-12-31T23:59:59",
            "refresh_expire_datetime": "2099-12-31T23:59:59",
            "name": "test_token",
            "created_at": "2025-06-30T18:00:00",
            "logged_in": False,
        },
    },
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


class TestCLIConfigExtraBehaviour:
    def test_unknown_top_level_settings_are_ignored(self):
        config = CLIConfig(**VALID_CONFIG, deployment_notes={"operator": "it"})

        assert config.api_base_url == "https://api.depictio.dev"
        # Unknown keys are not kept on the model either: they would otherwise
        # leak back into anything dumping the configuration.
        assert not hasattr(config, "deployment_notes")

    def test_unknown_user_settings_are_ignored(self):
        user = {**VALID_CONFIG["user"], "sso_provider": "okta"}

        parsed = UserBaseCLIConfig(**user)

        assert parsed.email == "test@example.com"
        assert not hasattr(parsed, "sso_provider")

    def test_required_fields_are_still_required(self):
        broken = {**VALID_CONFIG, "api_base_url": None}

        with pytest.raises(ValidationError) as excinfo:
            CLIConfig(**broken)

        assert "api_base_url" in str(excinfo.value)

    def test_a_missing_token_field_still_fails(self):
        broken_user = {**VALID_CONFIG["user"]}
        broken_user["token"] = {
            key: value for key, value in broken_user["token"].items() if key != "access_token"
        }

        with pytest.raises(ValidationError) as excinfo:
            CLIConfig(**{**VALID_CONFIG, "user": broken_user})

        assert "access_token" in str(excinfo.value)
