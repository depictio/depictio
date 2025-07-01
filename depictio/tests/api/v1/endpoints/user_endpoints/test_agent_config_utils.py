import datetime

import pydantic
import pytest
from beanie import PydanticObjectId

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.endpoints.user_endpoints.agent_config_utils import _generate_agent_config
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
