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
from unittest.mock import AsyncMock, MagicMock, patch

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
        mock_settings.auth.is_single_user_mode = False  # Not in single-user mode, so is_admin=False

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
        mock_settings.auth.is_single_user_mode = False  # Not in single-user mode

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
        mock_settings.auth.is_public_mode = False
        mock_settings.auth.is_single_user_mode = False

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
        """Test get_user_or_anonymous in public/single-user mode."""
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
        mock_settings.auth.is_public_mode = True
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.anonymous_user_email = "anon@test.com"

        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            result = await get_user_or_anonymous(token=None)

            assert result.email == anon_user.email
            assert result.is_anonymous is True


class TestDisabledFeatures:
    """Test that certain features are disabled in unauthenticated mode."""

    @pytest.mark.asyncio
    async def test_user_registration_disabled(self):
        """Test that user registration is disabled in public mode."""
        from fastapi import HTTPException

        from depictio.api.v1.endpoints.user_endpoints.routes import register
        from depictio.models.models.users import RequestUserRegistration

        mock_settings = MagicMock()
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.is_public_mode = True

        registration = RequestUserRegistration(email="test@example.com", password="password123")
        # The mode check fires before rate limiting, so the request mock is never
        # inspected — it only needs to satisfy the (now required) parameter.
        mock_request = MagicMock()

        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await register(registration, mock_request)

            assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]
            assert "User registration disabled" in str(
                exc_info.value.detail  # type: ignore[unresolved-attribute]
            )


class TestPublicModeAdminBypass:
    """In public/demo mode, admin callers bypass write-action gates that block
    anonymous + temporary users (project creation, CLI token creation, CLI
    config generation). Verifies the matching server-side enforcement for
    `app_layout.return_create_project_button` / `ProjectsApp.tsx`.
    """

    @staticmethod
    def _admin() -> MagicMock:
        u = MagicMock()
        u.is_admin = True
        u.is_anonymous = False
        u.is_temporary = False
        return u

    @staticmethod
    def _anonymous() -> MagicMock:
        u = MagicMock()
        u.is_admin = False
        u.is_anonymous = True
        u.is_temporary = False
        return u

    @staticmethod
    def _temp() -> MagicMock:
        u = MagicMock()
        u.is_admin = False
        u.is_anonymous = False
        u.is_temporary = True
        return u

    @pytest.mark.parametrize("user_factory", [_anonymous, _temp])
    @pytest.mark.asyncio
    async def test_create_project_blocks_non_admin_in_public_mode(self, user_factory):
        from fastapi import HTTPException

        from depictio.api.v1.endpoints.projects_endpoints.routes import create_project

        mock_settings = MagicMock()
        mock_settings.auth.is_public_mode = True
        with patch("depictio.api.v1.endpoints.projects_endpoints.routes.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await create_project(project=MagicMock(), current_user=user_factory())
        assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]
        assert "non-admin" in str(exc_info.value.detail).lower()  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    async def test_create_project_admin_bypasses_public_mode_gate(self):
        """Admin call must reach past the public-mode gate. We model a
        genuinely-absent existing project (both lookups return None) so the
        success path is reached on its own merits, not via the swallow-404
        branch inside `create_project`.
        """
        from depictio.api.v1.endpoints.projects_endpoints.routes import create_project

        mock_settings = MagicMock()
        mock_settings.auth.is_public_mode = True
        with (
            patch(
                "depictio.api.v1.endpoints.projects_endpoints.routes.settings",
                mock_settings,
            ),
            patch(
                "depictio.api.v1.endpoints.projects_endpoints.routes.get_project_from_name",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "depictio.api.v1.endpoints.projects_endpoints.routes.get_project_from_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "depictio.api.v1.endpoints.projects_endpoints.routes.validate_workflow_uniqueness_in_project"
            ),
            patch(
                "depictio.api.v1.endpoints.projects_endpoints.routes.projects_collection"
            ) as mock_collection,
        ):
            project = MagicMock()
            project.permissions.owners = []
            project.name = "admin-test"
            project.id = "abc"
            project.mongo.return_value = {}
            result = await create_project(project=project, current_user=self._admin())

        assert result["success"] is True
        mock_collection.insert_one.assert_called_once()

    @pytest.mark.parametrize("user_factory", [_anonymous, _temp])
    @pytest.mark.asyncio
    async def test_create_my_token_blocks_non_admin_in_public_mode(self, user_factory):
        from fastapi import HTTPException

        from depictio.api.v1.endpoints.user_endpoints.routes import (
            _CreateMeTokenRequest,
            create_my_token,
        )

        mock_settings = MagicMock()
        mock_settings.auth.is_public_mode = True
        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await create_my_token(
                    request=_CreateMeTokenRequest(name="t"),
                    current_user=user_factory(),
                )
        assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]
        assert "non-admin" in str(exc_info.value.detail).lower()  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    async def test_create_my_token_admin_bypasses_public_mode_gate(self):
        """Admin must pass the public-mode gate and reach token creation."""
        from bson import ObjectId

        from depictio.api.v1.endpoints.user_endpoints.routes import (
            _CreateMeTokenRequest,
            create_my_token,
        )

        mock_settings = MagicMock()
        mock_settings.auth.is_public_mode = True
        admin = self._admin()
        admin.id = ObjectId()  # TokenData(sub=...) validates ObjectId-shape
        sentinel_token = MagicMock(name="created-token")
        with (
            patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings),
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.TokenBeanie.find_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes._add_token",
                new_callable=AsyncMock,
                return_value=sentinel_token,
            ) as mock_add_token,
        ):
            result = await create_my_token(
                request=_CreateMeTokenRequest(name="t"),
                current_user=admin,
            )
        assert result is sentinel_token
        mock_add_token.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_factory", [_anonymous, _temp])
    @pytest.mark.asyncio
    async def test_generate_agent_config_blocks_non_admin_in_public_mode(self, user_factory):
        from fastapi import HTTPException

        from depictio.api.v1.endpoints.user_endpoints.routes import (
            generate_agent_config_endpoint,
        )

        mock_settings = MagicMock()
        mock_settings.auth.is_public_mode = True
        mock_settings.auth.is_demo_mode = False
        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await generate_agent_config_endpoint(token=MagicMock(), current_user=user_factory())
        assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]
        assert "non-admin" in str(exc_info.value.detail).lower()  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    async def test_generate_agent_config_blocks_non_admin_in_demo_mode(self):
        """Demo mode shares the same admin-bypass logic as public mode."""
        from fastapi import HTTPException

        from depictio.api.v1.endpoints.user_endpoints.routes import (
            generate_agent_config_endpoint,
        )

        mock_settings = MagicMock()
        mock_settings.auth.is_public_mode = False
        mock_settings.auth.is_demo_mode = True
        with patch("depictio.api.v1.endpoints.user_endpoints.routes.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await generate_agent_config_endpoint(token=MagicMock(), current_user=self._temp())
        assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    async def test_generate_agent_config_admin_bypasses_public_mode_gate(self):
        from depictio.api.v1.endpoints.user_endpoints.routes import (
            generate_agent_config_endpoint,
        )

        mock_settings = MagicMock()
        mock_settings.auth.is_public_mode = True
        mock_settings.auth.is_demo_mode = True
        admin = self._admin()
        with (
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.settings",
                mock_settings,
            ),
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes._generate_agent_config",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ) as mock_generate,
            # The endpoint serializes via cli_config_to_payload (deliberate
            # SecretStr unwrap) — stub it so the sentinel passes through.
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.cli_config_to_payload",
                return_value="OK-CONFIG",
            ),
        ):
            result = await generate_agent_config_endpoint(token=MagicMock(), current_user=admin)
        assert result == "OK-CONFIG"
        mock_generate.assert_awaited_once()


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
        """Test that initialization creates anonymous user in public/single-user mode."""
        from depictio.api.v1.initialization import run_initialization

        mock_settings = MagicMock()
        mock_settings.auth.requires_anonymous_user = True  # Triggers anonymous user creation
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.is_public_mode = True
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
                                "depictio.api.v1.db.initialization_collection"
                            ) as mock_collection:
                                mock_collection.insert_one = MagicMock()

                                await run_initialization()

                                mock_create_anon.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialization_skips_anonymous_user_in_authenticated_mode(self):
        """Test that initialization skips anonymous user creation in authenticated mode."""
        from depictio.api.v1.initialization import run_initialization

        mock_settings = MagicMock()
        mock_settings.auth.requires_anonymous_user = False  # Skips anonymous user creation
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.is_public_mode = False
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
                                "depictio.api.v1.db.initialization_collection"
                            ) as mock_collection:
                                mock_collection.insert_one = MagicMock()

                                await run_initialization()

                                mock_create_anon.assert_not_called()


class TestAnonymousDashboardListing:
    """Regression tests for anonymous-user dashboard listing in public mode.

    Anonymous users must see dashboards in *any* public project, consistent
    with how projects are listed, while private dashboards must not leak.
    """

    def _make_anonymous_user(self):
        user = MagicMock()
        user.is_anonymous = True
        user.is_admin = False
        return user

    def test_anonymous_sees_dashboards_in_non_admin_public_project(self):
        """Public dashboards in a non-admin-owned public project must be listed."""
        from bson import ObjectId

        from depictio.api.v1.endpoints.dashboards_endpoints import core_functions

        owner_id = ObjectId()
        project_id = ObjectId()

        mock_settings = MagicMock()
        mock_settings.auth.is_single_user_mode = False

        projects_coll = MagicMock()
        # Non-admin-owned public project returned by the project visibility query.
        projects_coll.find.return_value = [{"_id": project_id}]

        dashboards_coll = MagicMock()
        dashboards_coll.find.return_value = [
            {
                "_id": ObjectId(),
                "dashboard_id": "dash-1",
                "title": "Public Dashboard",
                "project_id": project_id,
                "is_public": True,
            }
        ]

        with patch.object(core_functions, "projects_collection", projects_coll):
            with patch.object(core_functions, "dashboards_collection", dashboards_coll):
                with patch("depictio.api.v1.configs.config.settings", mock_settings):
                    result = core_functions.load_dashboards_from_db(
                        owner=str(owner_id),
                        user=self._make_anonymous_user(),
                    )

        assert result["success"] is True
        assert len(result["dashboards"]) == 1
        assert result["dashboards"][0]["dashboard_id"] == "dash-1"

        # The widened project visibility must NOT loosen the dashboard-level
        # guard: anonymous users still only get public dashboards (or ones they
        # own), so private dashboards in a public project never leak.
        dashboard_query = dashboards_coll.find.call_args[0][0]
        assert {"is_public": True} in dashboard_query["$or"]

    def test_anonymous_project_query_has_no_admin_owner_filter(self):
        """The anonymous project-visibility query must not require an admin owner."""
        from bson import ObjectId

        from depictio.api.v1.endpoints.dashboards_endpoints import core_functions

        mock_settings = MagicMock()
        mock_settings.auth.is_single_user_mode = False

        projects_coll = MagicMock()
        projects_coll.find.return_value = []

        dashboards_coll = MagicMock()
        dashboards_coll.find.return_value = []

        with patch.object(core_functions, "projects_collection", projects_coll):
            with patch.object(core_functions, "dashboards_collection", dashboards_coll):
                with patch("depictio.api.v1.configs.config.settings", mock_settings):
                    core_functions.load_dashboards_from_db(
                        owner=str(ObjectId()),
                        user=self._make_anonymous_user(),
                    )

        project_query = projects_coll.find.call_args[0][0]
        assert project_query == {"is_public": True}
        assert "permissions.owners.is_admin" not in project_query
