from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

# Import the function to test
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_current_user,
)
from depictio.models.models.users import TokenBeanie, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import (
    beanie_setup,
)

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
        self.mock_token_find_one.assert_called_once_with(
            {"access_token": self.test_token}
        )
        self.mock_user_get.assert_called_once()
        assert result == self.mock_user

    @pytest.mark.asyncio
    async def test_get_current_user_none_token(self):
        """Test with a None token value."""
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(None)

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
