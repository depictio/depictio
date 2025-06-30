"""
Tests for unauthenticated mode functionality.

This test suite validates:
1. Anonymous user creation and management
2. Permanent token generation for anonymous users
3. Authentication bypassing in unauthenticated mode
4. Disabled features in unauthenticated mode
5. Configuration handling for unauthenticated mode
"""

import os
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _add_token,
    _create_anonymous_user,
    _create_permanent_token,
    _hash_password,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import (
    TokenBeanie,
    TokenData,
    UserBeanie,
)
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup


@contextmanager
def env_vars(env_dict):
    """Context manager for temporarily setting environment variables."""
    original = {key: os.environ.get(key) for key in env_dict}
    try:
        # Set temporary environment variables
        for key, value in env_dict.items():
            if value is not None:
                os.environ[key] = value
            else:
                if key in os.environ:
                    del os.environ[key]
        yield
    finally:
        # Restore original environment
        for key, value in original.items():
            if value is not None:
                os.environ[key] = value
            else:
                if key in os.environ:
                    del os.environ[key]


class TestUnauthenticatedModeSettings:
    """Test unauthenticated mode configuration settings."""

    def test_default_authenticated_mode(self):
        """Test that authenticated mode is the default."""
        env_to_clear = {
            "DEPICTIO_AUTH_UNAUTHENTICATED_MODE": None,
            "DEPICTIO_AUTH_ANONYMOUS_USER_EMAIL": None,
        }

        with env_vars(env_to_clear):
            settings = Settings()
            assert settings.auth.unauthenticated_mode is False
            assert settings.auth.anonymous_user_email == "anonymous@depict.io"

    def test_enable_unauthenticated_mode(self):
        """Test enabling unauthenticated mode via environment variable."""
        env = {
            "DEPICTIO_AUTH_UNAUTHENTICATED_MODE": "true",
            "DEPICTIO_AUTH_ANONYMOUS_USER_EMAIL": "test_anon@example.com",
        }

        with env_vars(env):
            settings = Settings()
            assert settings.auth.unauthenticated_mode is True
            assert settings.auth.anonymous_user_email == "test_anon@example.com"

    def test_custom_anonymous_user_email(self):
        """Test setting custom anonymous user email."""
        env = {
            "DEPICTIO_AUTH_UNAUTHENTICATED_MODE": "false",
            "DEPICTIO_AUTH_ANONYMOUS_USER_EMAIL": "custom_anon@mysite.com",
        }

        with env_vars(env):
            settings = Settings()
            assert settings.auth.unauthenticated_mode is False
            assert settings.auth.anonymous_user_email == "custom_anon@mysite.com"


class TestAnonymousUserCreation:
    """Test anonymous user creation and management."""

    @beanie_setup(models=[UserBeanie])
    async def test_create_anonymous_user_new(self):
        """Test creating a new anonymous user."""
        mock_settings = MagicMock()
        mock_settings.auth.anonymous_user_email = "anon@test.com"

        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.settings", mock_settings
        ):
            with patch(
                "depictio.api.v1.endpoints.user_endpoints.core_functions._create_user_in_db"
            ) as mock_create:
                mock_user = UserBeanie(
                    email="anon@test.com",
                    password=_hash_password(""),  # Hash empty password for anonymous user
                    is_admin=False,
                    is_anonymous=True,
                )
                mock_create.return_value = {"user": mock_user}

                result = await _create_anonymous_user()

                assert result == mock_user
                mock_create.assert_called_once_with(
                    email="anon@test.com",
                    password="",
                    is_admin=False,
                    is_anonymous=True,
                )

    @beanie_setup(models=[UserBeanie])
    async def test_create_anonymous_user_existing(self):
        """Test returning existing anonymous user."""
        # Create an actual anonymous user in the test database
        anon_user = UserBeanie(
            email="anon@test.com",
            password=_hash_password(""),  # Hash empty password for anonymous user
            is_admin=False,
            is_anonymous=True,
        )
        await anon_user.save()

        mock_settings = MagicMock()
        mock_settings.auth.anonymous_user_email = "anon@test.com"

        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.settings", mock_settings
        ):
            result = await _create_anonymous_user()

            assert result.email == anon_user.email
            assert result.is_anonymous is True


class TestPermanentTokenCreation:
    """Test permanent token creation for anonymous users."""

    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_create_permanent_token(self):
        """Test creating a permanent token for anonymous user."""
        # Create test user
        test_user = UserBeanie(
            email="anon@test.com",
            password=_hash_password(""),  # Hash empty password for anonymous user
            is_admin=False,
            is_anonymous=True,
        )
        await test_user.save()

        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.create_access_token"
        ) as mock_create_token:
            mock_create_token.return_value = ("test_access_token", None)

            result = await _create_permanent_token(test_user)

            # Verify token was created
            assert result is not None
            assert result.access_token == "test_access_token"
            # Check that datetime is very close to datetime.max (within a few microseconds)
            assert abs((result.expire_datetime - datetime.max).total_seconds()) < 0.001
            assert abs((result.refresh_expire_datetime - datetime.max).total_seconds()) < 0.001
            assert result.name == "anonymous_permanent_token"
            assert result.token_lifetime == "permanent"
            assert result.user_id == test_user.id
            assert result.logged_in is True

    @beanie_setup(models=[TokenBeanie])
    async def test_add_permanent_token_via_add_token(self):
        """Test creating permanent token via _add_token function."""
        from bson import ObjectId

        token_data = TokenData(
            sub=PyObjectId(str(ObjectId())), name="test_permanent_token", token_lifetime="permanent"
        )

        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.create_access_token"
        ) as mock_create_token:
            mock_create_token.return_value = ("test_access_token", None)

            result = await _add_token(token_data)

            # Verify permanent token handling
            mock_create_token.assert_called_once_with(token_data, expiry_hours=24 * 365)

            assert result.token_lifetime == "permanent"
            # Check that datetime is very close to datetime.max (within a few microseconds)
            assert abs((result.expire_datetime - datetime.max).total_seconds()) < 0.001
            assert abs((result.refresh_expire_datetime - datetime.max).total_seconds()) < 0.001


class TestAuthenticationBypass:
    """Test authentication bypassing in unauthenticated mode."""

    @beanie_setup(models=[UserBeanie])
    async def test_get_user_or_anonymous_authenticated_mode(self):
        """Test get_user_or_anonymous in authenticated mode."""
        from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

        mock_settings = MagicMock()
        mock_settings.auth.unauthenticated_mode = False

        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            with patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.get_current_user"
            ) as mock_get_current:
                mock_user = UserBeanie(
                    email="test@example.com", password=_hash_password("test_password")
                )
                mock_get_current.return_value = mock_user

                result = await get_user_or_anonymous(token="test_token")

                assert result == mock_user
                mock_get_current.assert_called_once_with("test_token")

    @beanie_setup(models=[UserBeanie])
    async def test_get_user_or_anonymous_unauthenticated_mode(self):
        """Test get_user_or_anonymous in unauthenticated mode."""
        from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

        # Create actual anonymous user in test database
        anon_user = UserBeanie(
            email="anon@test.com",
            password=_hash_password(""),  # Hash empty password for anonymous user
            is_admin=False,
            is_anonymous=True,
        )
        await anon_user.save()

        mock_settings = MagicMock()
        mock_settings.auth.unauthenticated_mode = True
        mock_settings.auth.anonymous_user_email = "anon@test.com"

        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            result = await get_user_or_anonymous(token=None)

            assert result.email == anon_user.email
            assert result.is_anonymous is True


class TestDisabledFeatures:
    """Test that certain features are disabled in unauthenticated mode."""

    @pytest.mark.asyncio
    async def test_user_registration_disabled(self):
        """Test that user registration is disabled in unauthenticated mode."""
        from fastapi import HTTPException

        from depictio.api.v1.endpoints.user_endpoints.routes import register
        from depictio.models.models.users import RequestUserRegistration

        mock_settings = MagicMock()
        mock_settings.auth.unauthenticated_mode = True

        request = RequestUserRegistration(
            email="test@example.com", password="password123", is_admin=False
        )

        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await register(request)

            assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]
            assert "User registration disabled in unauthenticated mode" in str(
                exc_info.value.detail  # type: ignore[unresolved-attribute]
            )

    @pytest.mark.asyncio
    async def test_cli_agent_generation_disabled(self):
        """Test that CLI agent generation is disabled in unauthenticated mode."""
        from fastapi import HTTPException

        from depictio.api.v1.endpoints.user_endpoints.routes import generate_agent_config_endpoint

        mock_settings = MagicMock()
        mock_settings.auth.unauthenticated_mode = True

        mock_token = MagicMock()
        mock_user = MagicMock()

        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await generate_agent_config_endpoint(mock_token, mock_user)

            assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]
            assert "CLI agent generation disabled in unauthenticated mode" in str(
                exc_info.value.detail  # type: ignore[unresolved-attribute]
            )


class TestTokenValidation:
    """Test token validation for permanent tokens."""

    def test_permanent_token_validation_in_token_data(self):
        """Test that permanent tokens are accepted in TokenData validation."""
        from bson import ObjectId

        token_data = TokenData(
            name="test_token",
            token_lifetime="permanent",
            token_type="bearer",
            sub=PyObjectId(str(ObjectId())),
        )

        # Should not raise validation error
        assert token_data.token_lifetime == "permanent"

    def test_token_expiration_validation_allows_datetime_max(self):
        """Test that Token validation allows datetime.max for permanent tokens."""
        from bson import ObjectId

        from depictio.models.models.users import Token

        token = Token(
            name="test_token",
            token_lifetime="permanent",
            token_type="bearer",
            sub=PyObjectId(str(ObjectId())),
            access_token="Test123Token456",
            expire_datetime=datetime.max,
        )

        # Should not raise validation error
        assert token.expire_datetime == datetime.max


class TestInitializationProcess:
    """Test the initialization process in unauthenticated mode."""

    @pytest.mark.asyncio
    async def test_initialization_creates_anonymous_user(self):
        """Test that initialization creates anonymous user in unauthenticated mode."""
        from depictio.api.v1.initialization import run_initialization

        mock_settings = MagicMock()
        mock_settings.auth.unauthenticated_mode = True
        mock_settings.minio = MagicMock()
        mock_settings.mongodb = MagicMock()
        mock_settings.mongodb.wipe = False

        mock_anon_user = MagicMock()

        with patch("depictio.api.v1.initialization.settings", mock_settings):
            with patch("depictio.api.v1.initialization.S3_storage_checks"):
                with patch("depictio.api.v1.initialization.initialize_db") as mock_init_db:
                    mock_admin = MagicMock()
                    mock_admin.id = "admin_id"
                    mock_admin.email = "admin@test.com"
                    mock_init_db.return_value = mock_admin

                    with patch("depictio.api.v1.initialization.create_bucket"):
                        with patch(
                            "depictio.api.v1.initialization._create_anonymous_user"
                        ) as mock_create_anon:
                            mock_create_anon.return_value = mock_anon_user

                            with patch(
                                "depictio.api.v1.initialization._create_permanent_token"
                            ) as mock_create_token:
                                with patch(
                                    "depictio.api.v1.db.initialization_collection"
                                ) as mock_collection:
                                    mock_collection.insert_one = MagicMock()

                                    await run_initialization()

                                    mock_create_anon.assert_called_once()
                                    mock_create_token.assert_called_once_with(mock_anon_user)

    @pytest.mark.asyncio
    async def test_initialization_skips_anonymous_user_in_authenticated_mode(self):
        """Test that initialization skips anonymous user creation in authenticated mode."""
        from depictio.api.v1.initialization import run_initialization

        mock_settings = MagicMock()
        mock_settings.auth.unauthenticated_mode = False
        mock_settings.minio = MagicMock()
        mock_settings.mongodb = MagicMock()
        mock_settings.mongodb.wipe = False

        with patch("depictio.api.v1.initialization.settings", mock_settings):
            with patch("depictio.api.v1.initialization.S3_storage_checks"):
                with patch("depictio.api.v1.initialization.initialize_db") as mock_init_db:
                    mock_admin = MagicMock()
                    mock_admin.id = "admin_id"
                    mock_admin.email = "admin@test.com"
                    mock_init_db.return_value = mock_admin

                    with patch("depictio.api.v1.initialization.create_bucket"):
                        with patch(
                            "depictio.api.v1.initialization._create_anonymous_user"
                        ) as mock_create_anon:
                            with patch(
                                "depictio.api.v1.initialization._create_permanent_token"
                            ) as mock_create_token:
                                with patch(
                                    "depictio.api.v1.db.initialization_collection"
                                ) as mock_collection:
                                    mock_collection.insert_one = MagicMock()

                                    await run_initialization()

                                    mock_create_anon.assert_not_called()
                                    mock_create_token.assert_not_called()
