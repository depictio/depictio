from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

# Import the functions to test
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.models.models.users import TokenBeanie, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

# ------------------------------------------------------
# Test get_current_user function
# ------------------------------------------------------


class TestGetCurrentUser:
    def setup_method(self):
        # Mock TokenBeanie.find_one directly to prevent CollectionWasNotInitialized
        self.token_find_one_patcher = patch(
            "depictio.models.models.users.TokenBeanie.find_one", new_callable=AsyncMock
        )
        self.mock_token_find_one = self.token_find_one_patcher.start()

        # Mock UserBeanie.get (which might be called in async_fetch_user_from_token)
        self.user_get_patcher = patch(
            "depictio.models.models.users.UserBeanie.get", new_callable=AsyncMock
        )
        self.mock_user_get = self.user_get_patcher.start()

        # Configure mocks for a successful path
        mock_token = MagicMock()
        mock_token.user_id = "test_user_id"
        self.mock_token_find_one.return_value = mock_token

        self.mock_user = MagicMock(spec=UserBeanie)
        self.mock_user_get.return_value = self.mock_user

        # Test data
        self.test_token = "test_token_12345abcdef"

    def teardown_method(self):
        # Stop all patches
        for patcher_attr in ["token_find_one_patcher", "user_get_patcher"]:
            if hasattr(self, patcher_attr):
                getattr(self, patcher_attr).stop()

    @pytest.mark.asyncio
    async def test_get_current_user_success(self):
        """Test successful retrieval of current user."""
        # Act
        result = await get_current_user(self.test_token)

        # Assert
        self.mock_token_find_one.assert_called_once_with({"access_token": self.test_token})
        self.mock_user_get.assert_called_once()
        assert result == self.mock_user

    @pytest.mark.asyncio
    async def test_get_current_user_none_token(self):
        """Test with a None token value."""
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(None)  # type: ignore[invalid-argument-type]

        # Verify the exception
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"
        self.mock_token_find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self):
        """Test with a token that doesn't correspond to a user."""
        # Arrange - No token found for this test
        self.mock_token_find_one.return_value = None

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(self.test_token)

        # Verify the exception
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"
        self.mock_token_find_one.assert_called_once()
        self.mock_user_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_current_user_no_user_found(self):
        """Test when token exists but user doesn't."""
        # Arrange - Token found but no user
        mock_token = MagicMock()
        mock_token.user_id = "test_user_id"
        self.mock_token_find_one.return_value = mock_token
        self.mock_user_get.return_value = None

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(self.test_token)

        # Verify the exception
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"
        self.mock_token_find_one.assert_called_once()
        self.mock_user_get.assert_called_once()


# Mock for oauth2_scheme dependency
@pytest.fixture
def mock_oauth2_scheme():
    async def _oauth2_scheme():
        return "mock_token"

    return _oauth2_scheme


# ------------------------------------------------------
# Test login endpoint
# ------------------------------------------------------


class TestLoginEndpoint:
    # Password hashing fixture

    @beanie_setup([UserBeanie, TokenBeanie])
    @pytest.mark.asyncio
    # Patch both _check_password AND _verify_password to be safe

    async def test_login_success(
        self,
        test_client,
        generate_hashed_password,
    ):
        """Test successful login."""

        user = UserBeanie(
            email="test@example.com",
            password=generate_hashed_password("password123"),
        )
        await user.insert()

        # Perform the login request
        response = test_client.post(
            "/depictio/api/v1/auth/login",
            data={"username": "test@example.com", "password": "password123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        print(response.json())

        # Verify response
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert "access_token" in response_data
        assert response_data["token_type"] == "bearer"

    @pytest.mark.asyncio
    @beanie_setup([UserBeanie, TokenBeanie])
    async def test_login_invalid_credentials(self, test_client):
        """Test login with invalid credentials."""
        # Perform the login request with invalid credentials
        response = test_client.post(
            "/depictio/api/v1/auth/login",
            data={
                "username": "non_existing_user@example.com",
                "password": "wrong_password",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        print(response.json())
        # Verify response
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ------------------------------------------------------
# Test get_user_or_anonymous function
# ------------------------------------------------------


class TestGetUserOrAnonymous:
    def setup_method(self):
        """Set up test fixtures."""
        # Mock get_current_user
        self.get_current_user_patcher = patch(
            "depictio.api.v1.endpoints.user_endpoints.routes.get_current_user",
            new_callable=AsyncMock,
        )
        self.mock_get_current_user = self.get_current_user_patcher.start()

        # Mock UserBeanie.find_one for anonymous user lookup
        self.user_find_one_patcher = patch(
            "depictio.api.v1.endpoints.user_endpoints.routes.UserBeanie.find_one",
            new_callable=AsyncMock,
        )
        self.mock_user_find_one = self.user_find_one_patcher.start()

        # Mock settings
        self.settings_patcher = patch("depictio.api.v1.endpoints.user_endpoints.routes.settings")
        self.mock_settings = self.settings_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.get_current_user_patcher.stop()
        self.user_find_one_patcher.stop()
        self.settings_patcher.stop()

    @pytest.mark.asyncio
    async def test_get_user_or_anonymous_valid_token(self):
        """Test successful authentication with valid token."""
        # Arrange
        mock_user = MagicMock(spec=UserBeanie)
        self.mock_get_current_user.return_value = mock_user

        # Act
        result = await get_user_or_anonymous(token="valid_token")

        # Assert
        self.mock_get_current_user.assert_called_once_with("valid_token")
        assert result == mock_user
        # Anonymous user lookup should not be called
        self.mock_user_find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_or_anonymous_invalid_token_unauthenticated_mode(self):
        """Test fallback to anonymous user when token is invalid and unauthenticated mode is enabled."""
        # Arrange
        self.mock_get_current_user.side_effect = HTTPException(
            status_code=401, detail="Invalid token"
        )
        self.mock_settings.auth.unauthenticated_mode = True
        self.mock_settings.auth.anonymous_user_email = "anon@depictio.io"

        mock_anonymous_user = MagicMock(spec=UserBeanie)
        self.mock_user_find_one.return_value = mock_anonymous_user

        # Act
        result = await get_user_or_anonymous(token="invalid_token")

        # Assert
        self.mock_get_current_user.assert_called_once_with("invalid_token")
        self.mock_user_find_one.assert_called_once_with({"email": "anon@depictio.io"})
        assert result == mock_anonymous_user

    @pytest.mark.asyncio
    async def test_get_user_or_anonymous_no_token_authenticated_mode(self):
        """Test rejection when no token provided and authenticated mode is enabled."""
        # Arrange
        self.mock_settings.auth.unauthenticated_mode = False

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_user_or_anonymous(token=None)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"
        # get_current_user should not be called when token is None
        self.mock_get_current_user.assert_not_called()
        self.mock_user_find_one.assert_not_called()
