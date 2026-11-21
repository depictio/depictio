import datetime

import pydantic
import pytest
from beanie import PydanticObjectId

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.api.v1.endpoints.user_endpoints.agent_config_utils import (
    SERVER_ONLY_S3_FIELDS,
    _generate_agent_config,
    cli_config_to_payload,
)
from depictio.models.models.cli import CLIConfig
from depictio.models.models.users import TokenBeanie, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup


@pytest.mark.asyncio
class TestGenerateAgentConfig:
    """Tests for the _generate_agent_config function."""

    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_generate_agent_config_success(self, generate_hashed_password):
        """Test successful generation of agent configuration."""
        # Create and save user
        user = UserBeanie(
            email="test@example.com",
            password=generate_hashed_password("test_password"),
        )
        await user.save()

        # Create and save token
        assert user.id is not None, "User ID should be set after saving"
        # Convert to PydanticObjectId since TokenBeanie expects it
        user_id = (
            user.id if isinstance(user.id, PydanticObjectId) else PydanticObjectId(str(user.id))
        )
        token = TokenBeanie(
            name="test_token",
            access_token="test_access_token",
            expire_datetime=datetime.datetime.now() + datetime.timedelta(days=1),
            refresh_token="test_refresh_token",
            refresh_expire_datetime=datetime.datetime.now() + datetime.timedelta(days=1),
            token_type="bearer",
            user_id=user_id,
            logged_in=True,
        )
        await token.save()

        # Call the function
        result = await _generate_agent_config(user, token)
        print(format_pydantic(result))

        # Verify result
        assert isinstance(result, CLIConfig)
        assert result.user.id == user.id
        assert result.user.email == "test@example.com"
        assert result.user.is_admin is False
        assert result.user.token == token
        assert "http://" in result.api_base_url

    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_generate_agent_config_invalid_user(self):
        """Test generation of agent configuration with invalid user."""
        # Create and save token
        token = TokenBeanie(
            name="test_token",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            expire_datetime=datetime.datetime.now() + datetime.timedelta(days=1),
            refresh_expire_datetime=datetime.datetime.now() + datetime.timedelta(days=1),
            token_type="bearer",
            user_id=PydanticObjectId(),
            logged_in=True,
        )
        await token.save()

        # Test with None user - should raise ValueError or ValidationError
        with pytest.raises((ValueError, TypeError, pydantic.ValidationError)):
            await _generate_agent_config(None, token)


@pytest.mark.asyncio
class TestCliConfigPayload:
    """The CLI.yaml payload carries only what a CLI reads."""

    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_server_only_s3_fields_left_out(self, generate_hashed_password):
        user = UserBeanie(email="payload@example.com", password=generate_hashed_password("pw"))
        await user.save()
        token = TokenBeanie(
            name="payload_token",
            access_token="access",
            expire_datetime=datetime.datetime.now() + datetime.timedelta(days=1),
            refresh_token="refresh",
            refresh_expire_datetime=datetime.datetime.now() + datetime.timedelta(days=1),
            token_type="bearer",
            user_id=PydanticObjectId(str(user.id)),
            logged_in=True,
        )
        await token.save()

        payload = cli_config_to_payload(await _generate_agent_config(user, token))

        assert SERVER_ONLY_S3_FIELDS.isdisjoint(payload["s3_storage"])
        # The secret is still delivered unmasked, the rest of s3_storage intact.
        assert payload["s3_storage"]["root_password"] != "**********"
        assert "bucket" in payload["s3_storage"]

    def test_server_only_fields_exist_on_the_settings_model(self):
        """A renamed or removed setting must be dropped from the list too."""
        assert SERVER_ONLY_S3_FIELDS <= set(S3DepictioCLIConfig.model_fields)
