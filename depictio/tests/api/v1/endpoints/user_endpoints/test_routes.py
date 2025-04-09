import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from bson import ObjectId

# Import the function to test
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio_models.models.users import TokenBeanie, UserBeanie
from depictio.api.main import app

# ------------------------------------------------------
# Test get_current_user function
# ------------------------------------------------------

class TestGetCurrentUser:
    def setup_method(self):
        # Mock TokenBeanie.find_one directly to prevent CollectionWasNotInitialized
        self.token_find_one_patcher = patch(
            "depictio_models.models.users.TokenBeanie.find_one", new_callable=AsyncMock
        )
        self.mock_token_find_one = self.token_find_one_patcher.start()

        # Mock UserBeanie.get (which might be called in async_fetch_user_from_token)
        self.user_get_patcher = patch(
            "depictio_models.models.users.UserBeanie.get", new_callable=AsyncMock
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


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# ------------------------------------------------------
# Test login endpoint
# ------------------------------------------------------

class TestLoginEndpoint:
    """Tests for the login endpoint using direct mocking of all database calls."""

    @pytest.mark.asyncio
    @patch(
        "depictio.api.v1.endpoints.user_endpoints.routes.check_password",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.user_endpoints.routes.async_fetch_user_from_email",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.user_endpoints.routes.add_token",
        new_callable=AsyncMock,
    )
    async def test_login_success(
        self, mock_add_token, mock_fetch_user, mock_check_password, test_client
    ):
        """Test successful login."""
        # Setup mocks
        mock_check_password.return_value = True

        # Create a mock user
        user_id = ObjectId()
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_fetch_user.return_value = mock_user

        # Create a mock token
        mock_token = MagicMock(spec=TokenBeanie)
        mock_token.access_token = "test_access_token"
        mock_token.token_type = "bearer"
        mock_token.user_id = user_id
        mock_add_token.return_value = mock_token

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

        # Verify mock calls
        mock_check_password.assert_called_once_with("test@example.com", "password123")
        mock_fetch_user.assert_called_once_with("test@example.com")
        mock_add_token.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "depictio.api.v1.endpoints.user_endpoints.routes.check_password",
        new_callable=AsyncMock,
    )
    async def test_login_invalid_credentials(self, mock_check_password, test_client):
        """Test login with invalid credentials."""
        # Setup mock to return False (invalid credentials)
        mock_check_password.return_value = False

        # Perform the login request
        response = test_client.post(
            "/depictio/api/v1/auth/login",
            data={"username": "test@example.com", "password": "wrong_password"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Verify response
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        response_data = response.json()
        assert response_data["detail"] == "Invalid credentials"

        # Verify mock call
        mock_check_password.assert_called_once_with(
            "test@example.com", "wrong_password"
        )

    @pytest.mark.asyncio
    @patch(
        "depictio.api.v1.endpoints.user_endpoints.routes.check_password",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.user_endpoints.routes.async_fetch_user_from_email",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.user_endpoints.routes.add_token",
        new_callable=AsyncMock,
    )
    async def test_login_token_creation_failure(
        self, mock_add_token, mock_fetch_user, mock_check_password, test_client
    ):
        """Test login when token creation fails."""
        # Setup mocks
        mock_check_password.return_value = True

        # Create a mock user
        user_id = ObjectId()
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_fetch_user.return_value = mock_user

        # Configure add_token to return None (token creation failure)
        mock_add_token.return_value = None

        # Perform the login request
        response = test_client.post(
            "/depictio/api/v1/auth/login",
            data={"username": "test@example.com", "password": "password123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Verify response
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_data = response.json()
        assert response_data["detail"] == "Token with the same name already exists"

        # Verify mock calls
        mock_check_password.assert_called_once_with("test@example.com", "password123")
        mock_fetch_user.assert_called_once_with("test@example.com")
        mock_add_token.assert_called_once()
