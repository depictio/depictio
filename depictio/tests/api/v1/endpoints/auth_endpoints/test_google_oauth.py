"""
Unit tests for Google OAuth authentication endpoints.

These tests follow TDD approach - designed before implementation.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User


@pytest.fixture
def google_oauth_config():
    """Mock Google OAuth configuration."""
    return {
        "google_oauth_client_id": "test-client-id.googleusercontent.com",
        "google_oauth_client_secret": "test-client-secret",
        "google_oauth_redirect_uri": "http://localhost:8000/depictio/api/v1/auth/google/callback",
        "google_oauth_enabled": True,
    }


@pytest.fixture
def google_user_info():
    """Mock Google user info response."""
    return {
        "id": "123456789",
        "email": "test@gmail.com",
        "name": "Test User",
        "given_name": "Test",
        "family_name": "User",
        "picture": "https://lh3.googleusercontent.com/a/example",
        "verified_email": True,
        "locale": "en",
    }


@pytest.fixture
def google_token_response():
    """Mock Google OAuth token response."""
    return {
        "access_token": "ya29.example_access_token",
        "expires_in": 3599,
        "refresh_token": "1//example_refresh_token",
        "scope": "openid email profile",
        "token_type": "Bearer",
        "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6ImV4YW1wbGUifQ.example_id_token",
    }


@pytest.fixture
def mock_existing_user():
    """Create mock existing user for OAuth testing."""
    return User(
        id=PyObjectId("507f1f77bcf86cd799439011"),
        email="test@gmail.com",
        password="$2b$12$example.hashed.password.string",
        is_admin=False,
        is_active=True,
        is_verified=True,
    )


@pytest.fixture
def client():
    """Create test client for OAuth endpoints."""
    from fastapi import FastAPI

    app = FastAPI()

    # Will be implemented later
    from depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes import google_oauth_router

    app.include_router(google_oauth_router, prefix="/auth/google")
    return TestClient(app)


class TestGoogleOAuthLogin:
    """Test Google OAuth login initiation endpoint."""

    def test_google_oauth_login_redirect_url_generation(self, client, google_oauth_config):
        """Test that Google OAuth login generates correct redirect URL."""
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_client_id = google_oauth_config[
                "google_oauth_client_id"
            ]
            mock_settings.auth.google_oauth_enabled = True
            mock_settings.auth.google_oauth_redirect_uri = google_oauth_config[
                "google_oauth_redirect_uri"
            ]

            response = client.get("/auth/google/login")

            assert response.status_code == 200
            response_data = response.json()

            # Should return Google OAuth authorization URL
            assert "authorization_url" in response_data
            assert "state" in response_data
            assert "https://accounts.google.com/o/oauth2/auth" in response_data["authorization_url"]
            assert (
                google_oauth_config["google_oauth_client_id"] in response_data["authorization_url"]
            )
            assert "scope=openid+email+profile" in response_data["authorization_url"]

    def test_google_oauth_login_when_disabled(self, client):
        """Test that Google OAuth login fails when disabled."""
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_enabled = False

            response = client.get("/auth/google/login")

            assert response.status_code == 403
            assert "Google OAuth is not enabled" in response.json()["detail"]

    def test_google_oauth_login_missing_config(self, client):
        """Test that Google OAuth login fails with missing configuration."""
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_enabled = True
            mock_settings.auth.google_oauth_client_id = None

            response = client.get("/auth/google/login")

            assert response.status_code == 500
            assert "Google OAuth configuration incomplete" in response.json()["detail"]


class TestGoogleOAuthCallback:
    """Test Google OAuth callback endpoint."""

    @patch("depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.validate_oauth_state")
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.fetch_google_user_info",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.exchange_code_for_token",
        new_callable=AsyncMock,
    )
    @patch("depictio.api.v1.endpoints.auth_endpoints.utils.UserBeanie")
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes._add_token",
        new_callable=AsyncMock,
    )
    def test_google_oauth_callback_new_user_success(
        self,
        mock_add_token,
        mock_user_beanie,
        mock_exchange_code,
        mock_fetch_user_info,
        mock_validate_state,
        client,
        google_oauth_config,
        google_token_response,
        google_user_info,
    ):
        """Test successful OAuth callback for new user registration."""
        # Mock state validation to return True
        mock_validate_state.return_value = True

        # Mock exchange_code_for_token to return token data
        mock_exchange_code.return_value = google_token_response

        # Mock fetch_google_user_info to return user info
        from depictio.models.models.google_oauth import GoogleUserInfo

        mock_fetch_user_info.return_value = GoogleUserInfo(**google_user_info)

        # Mock user not found (new user) - UserBeanie.find_one is a class method
        mock_user_beanie.find_one = AsyncMock(return_value=None)

        # Mock user creation
        new_user_mock = MagicMock()
        new_user_mock.id = PyObjectId("507f1f77bcf86cd799439011")
        new_user_mock.email = google_user_info["email"]
        new_user_mock.password = "$2b$12$oauth.user.no.password"
        new_user_mock.is_admin = False
        new_user_mock.is_active = True
        new_user_mock.is_verified = True
        new_user_mock.save = AsyncMock()

        mock_user_beanie.return_value = new_user_mock

        # Mock token creation - _add_token is async, configure the async mock properly
        mock_token = MagicMock()
        mock_token.user_id = new_user_mock.id
        mock_token.access_token = "test_access_token"
        mock_token.refresh_token = "test_refresh_token"
        mock_token.token_type = "bearer"
        mock_token.token_lifetime = "short-lived"
        mock_token.expire_datetime = datetime.now() + timedelta(hours=1)
        mock_token.refresh_expire_datetime = datetime.now() + timedelta(days=7)
        mock_token.name = "google_oauth_token"
        # For AsyncMock, we need to configure the return value of the coroutine
        mock_add_token.return_value = mock_token

        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_client_id = google_oauth_config[
                "google_oauth_client_id"
            ]
            mock_settings.auth.google_oauth_client_secret = google_oauth_config[
                "google_oauth_client_secret"
            ]
            mock_settings.auth.google_oauth_redirect_uri = google_oauth_config[
                "google_oauth_redirect_uri"
            ]
            mock_settings.auth.google_oauth_enabled = True

            response = client.get(
                "/auth/google/callback",
                params={"code": "test_auth_code", "state": "test_state"},
            )

            if response.status_code != 200:
                print(f"Response status: {response.status_code}")
                print(f"Response body: {response.json()}")

            assert response.status_code == 200
            response_data = response.json()

            # Should return token data for new user
            assert response_data["success"] is True
            assert response_data["message"] == "OAuth login successful"
            assert response_data["user_created"] is True
            assert "token" in response_data
            assert response_data["token"]["access_token"] == "test_access_token"
            assert response_data["user"]["email"] == google_user_info["email"]

            # Verify user creation was called
            mock_user_beanie.assert_called()
            new_user_mock.save.assert_called_once()

    @patch("depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.validate_oauth_state")
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.fetch_google_user_info",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.exchange_code_for_token",
        new_callable=AsyncMock,
    )
    @patch("depictio.api.v1.endpoints.auth_endpoints.utils.UserBeanie")
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes._add_token",
        new_callable=AsyncMock,
    )
    def test_google_oauth_callback_existing_user_success(
        self,
        mock_add_token,
        mock_user_beanie,
        mock_exchange_code,
        mock_fetch_user_info,
        mock_validate_state,
        client,
        google_oauth_config,
        google_token_response,
        google_user_info,
        mock_existing_user,
    ):
        """Test successful OAuth callback for existing user login."""
        # Mock state validation to return True
        mock_validate_state.return_value = True

        # Mock exchange_code_for_token to return token data
        mock_exchange_code.return_value = google_token_response

        # Mock fetch_google_user_info to return user info
        from depictio.models.models.google_oauth import GoogleUserInfo

        mock_fetch_user_info.return_value = GoogleUserInfo(**google_user_info)

        # Mock existing user found
        mock_user_beanie.find_one = AsyncMock(return_value=mock_existing_user)

        # Mock token creation
        mock_token = MagicMock()
        mock_token.user_id = mock_existing_user.id
        mock_token.access_token = "test_access_token"
        mock_token.refresh_token = "test_refresh_token"
        mock_token.token_type = "bearer"
        mock_token.token_lifetime = "short-lived"
        mock_token.expire_datetime = datetime.now() + timedelta(hours=1)
        mock_token.refresh_expire_datetime = datetime.now() + timedelta(days=7)
        mock_token.name = "google_oauth_token"
        mock_add_token.return_value = mock_token

        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_client_id = google_oauth_config[
                "google_oauth_client_id"
            ]
            mock_settings.auth.google_oauth_client_secret = google_oauth_config[
                "google_oauth_client_secret"
            ]
            mock_settings.auth.google_oauth_redirect_uri = google_oauth_config[
                "google_oauth_redirect_uri"
            ]
            mock_settings.auth.google_oauth_enabled = True

            response = client.get(
                "/auth/google/callback",
                params={"code": "test_auth_code", "state": "test_state"},
            )

            assert response.status_code == 200
            response_data = response.json()

            # Should return token data for existing user
            assert response_data["success"] is True
            assert response_data["message"] == "OAuth login successful"
            assert response_data["user_created"] is False
            assert "token" in response_data
            assert response_data["token"]["access_token"] == "test_access_token"
            assert response_data["user"]["email"] == google_user_info["email"]

    def test_google_oauth_callback_missing_code(self, client):
        """Test OAuth callback fails without authorization code."""
        response = client.get("/auth/google/callback")

        # FastAPI returns 422 for missing required query parameters
        assert response.status_code == 422
        assert "field required" in str(response.json()["detail"]).lower()

    @patch("depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.validate_oauth_state")
    @patch("depictio.api.v1.endpoints.auth_endpoints.utils.httpx.AsyncClient")
    def test_google_oauth_callback_token_exchange_failure(
        self, mock_httpx_client, mock_validate_state, client, google_oauth_config
    ):
        """Test OAuth callback handles token exchange failure."""
        # Mock state validation to return True
        mock_validate_state.return_value = True

        # Mock HTTP client for failed token exchange
        mock_client_instance = AsyncMock()
        mock_httpx_client.return_value.__aenter__.return_value = mock_client_instance

        token_response_mock = AsyncMock()
        token_response_mock.status_code = 400
        token_response_mock.json.return_value = {"error": "invalid_grant"}
        mock_client_instance.post.return_value = token_response_mock

        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_client_id = google_oauth_config[
                "google_oauth_client_id"
            ]
            mock_settings.auth.google_oauth_client_secret = google_oauth_config[
                "google_oauth_client_secret"
            ]
            mock_settings.auth.google_oauth_redirect_uri = google_oauth_config[
                "google_oauth_redirect_uri"
            ]
            mock_settings.auth.google_oauth_enabled = True

            response = client.get(
                "/auth/google/callback",
                params={"code": "invalid_code", "state": "test_state"},
            )

            assert response.status_code == 400
            assert "Failed to exchange authorization code" in response.json()["detail"]

    @patch("depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.validate_oauth_state")
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.fetch_google_user_info",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.exchange_code_for_token",
        new_callable=AsyncMock,
    )
    def test_google_oauth_callback_user_info_failure(
        self,
        mock_exchange_code,
        mock_fetch_user_info,
        mock_validate_state,
        client,
        google_oauth_config,
        google_token_response,
    ):
        """Test OAuth callback handles user info fetch failure."""
        # Mock state validation to return True
        mock_validate_state.return_value = True

        # Mock successful token exchange
        mock_exchange_code.return_value = google_token_response

        # Mock failed user info fetch - raise the exception that would be raised
        from fastapi import HTTPException

        mock_fetch_user_info.side_effect = HTTPException(
            status_code=400,
            detail="Failed to fetch user information from Google: {'error': 'invalid_token'}",
        )

        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_client_id = google_oauth_config[
                "google_oauth_client_id"
            ]
            mock_settings.auth.google_oauth_client_secret = google_oauth_config[
                "google_oauth_client_secret"
            ]
            mock_settings.auth.google_oauth_redirect_uri = google_oauth_config[
                "google_oauth_redirect_uri"
            ]
            mock_settings.auth.google_oauth_enabled = True

            response = client.get(
                "/auth/google/callback",
                params={"code": "test_auth_code", "state": "test_state"},
            )

            assert response.status_code == 400
            assert "Failed to fetch user information" in response.json()["detail"]


class TestGoogleOAuthModels:
    """Test Pydantic models for Google OAuth."""

    def test_google_oauth_request_model_validation(self):
        """Test GoogleOAuthRequest model validation."""
        # Will be implemented after creating the model
        from depictio.models.models.google_oauth import GoogleOAuthRequest

        # Valid request (state must be at least 16 characters)
        request = GoogleOAuthRequest(
            code="test_auth_code", state="test_state_12345678", scope="openid email profile"
        )
        assert request.code == "test_auth_code"
        assert request.state == "test_state_12345678"
        assert request.scope == "openid email profile"

        # Missing required fields should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            GoogleOAuthRequest()

    def test_google_user_info_model_validation(self, google_user_info):
        """Test GoogleUserInfo model validation."""
        from depictio.models.models.google_oauth import GoogleUserInfo

        # Valid user info
        user_info = GoogleUserInfo(**google_user_info)
        assert user_info.email == "test@gmail.com"
        assert user_info.verified_email is True
        assert user_info.name == "Test User"

        # Invalid email should raise validation error
        invalid_user_info = google_user_info.copy()
        invalid_user_info["email"] = "invalid-email"
        with pytest.raises(Exception):  # Pydantic ValidationError
            GoogleUserInfo(**invalid_user_info)

    def test_google_oauth_response_model_validation(self):
        """Test GoogleOAuthResponse model validation."""
        from depictio.models.models.google_oauth import GoogleOAuthResponse

        # Valid response
        response = GoogleOAuthResponse(
            success=True,
            message="OAuth login successful",
            user_created=True,
            user={"id": "123", "email": "test@gmail.com"},
            token={"access_token": "token123"},
        )
        assert response.success is True
        assert response.user_created is True

        # Test with minimal required fields
        minimal_response = GoogleOAuthResponse(
            success=False, message="OAuth login failed", user_created=False
        )
        assert minimal_response.user is None
        assert minimal_response.token is None


class TestGoogleOAuthIntegration:
    """Integration tests for Google OAuth flow."""

    @patch("depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.validate_oauth_state")
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.fetch_google_user_info",
        new_callable=AsyncMock,
    )
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.exchange_code_for_token",
        new_callable=AsyncMock,
    )
    @patch("depictio.api.v1.endpoints.auth_endpoints.utils.UserBeanie")
    @patch(
        "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes._add_token",
        new_callable=AsyncMock,
    )
    def test_complete_oauth_flow_new_user(
        self,
        mock_add_token,
        mock_user_beanie,
        mock_exchange_code,
        mock_fetch_user_info,
        mock_validate_state,
        client,
        google_oauth_config,
        google_token_response,
        google_user_info,
    ):
        """Test complete OAuth flow from login to callback for new user."""
        # Step 1: Test login initiation
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_client_id = google_oauth_config[
                "google_oauth_client_id"
            ]
            mock_settings.auth.google_oauth_enabled = True
            mock_settings.auth.google_oauth_redirect_uri = google_oauth_config[
                "google_oauth_redirect_uri"
            ]

            login_response = client.get("/auth/google/login")
            assert login_response.status_code == 200

            login_data = login_response.json()
            assert "authorization_url" in login_data
            assert "state" in login_data

            # Step 2: Test callback with the state from login
            state = login_data["state"]

            # Mock state validation to return True
            mock_validate_state.return_value = True

            # Mock exchange_code_for_token to return token data
            mock_exchange_code.return_value = google_token_response

            # Mock fetch_google_user_info to return user info
            from depictio.models.models.google_oauth import GoogleUserInfo

            mock_fetch_user_info.return_value = GoogleUserInfo(**google_user_info)

            # Mock user not found (new user)
            mock_user_beanie.find_one = AsyncMock(return_value=None)

            new_user_mock = MagicMock()
            new_user_mock.id = PyObjectId("507f1f77bcf86cd799439011")
            new_user_mock.email = google_user_info["email"]
            new_user_mock.password = "$2b$12$oauth.user.no.password"
            new_user_mock.is_admin = False
            new_user_mock.is_active = True
            new_user_mock.is_verified = True
            new_user_mock.save = AsyncMock()

            mock_user_beanie.return_value = new_user_mock

            mock_token = MagicMock()
            mock_token.user_id = new_user_mock.id
            mock_token.access_token = "test_access_token"
            mock_token.refresh_token = "test_refresh_token"
            mock_token.token_type = "bearer"
            mock_token.token_lifetime = "short-lived"
            mock_token.expire_datetime = datetime.now() + timedelta(hours=1)
            mock_token.refresh_expire_datetime = datetime.now() + timedelta(days=7)
            mock_token.name = "google_oauth_token"
            mock_add_token.return_value = mock_token

            mock_settings.auth.google_oauth_client_secret = google_oauth_config[
                "google_oauth_client_secret"
            ]

            callback_response = client.get(
                "/auth/google/callback", params={"code": "test_auth_code", "state": state}
            )

            assert callback_response.status_code == 200
            callback_data = callback_response.json()

            assert callback_data["success"] is True
            assert callback_data["user_created"] is True
            assert callback_data["user"]["email"] == google_user_info["email"]
            assert "token" in callback_data

    def test_oauth_disabled_scenario(self, client):
        """Test that OAuth endpoints properly handle disabled OAuth."""
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.google_oauth_routes.settings"
        ) as mock_settings:
            mock_settings.auth.google_oauth_enabled = False

            # Both endpoints should return 403
            login_response = client.get("/auth/google/login")
            assert login_response.status_code == 403

            callback_response = client.get(
                "/auth/google/callback", params={"code": "test", "state": "test"}
            )
            assert callback_response.status_code == 403
