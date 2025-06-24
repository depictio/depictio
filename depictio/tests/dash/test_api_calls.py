from unittest.mock import MagicMock, patch

from depictio.dash.api_calls import (
    api_call_cleanup_expired_temporary_users,
    api_call_create_temporary_user,
    api_call_get_anonymous_user_session,
    api_call_upgrade_to_temporary_user,
)

# ------------------------------------------------------
# Test api_call_get_anonymous_user_session function
# ------------------------------------------------------


class TestApiCallGetAnonymousUserSession:
    def setup_method(self):
        """Set up test fixtures."""
        # Mock httpx.get
        self.httpx_get_patcher = patch("depictio.dash.api_calls.httpx.get")
        self.mock_httpx_get = self.httpx_get_patcher.start()

        # Mock settings
        self.settings_patcher = patch("depictio.dash.api_calls.settings")
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.auth.internal_api_key = "test_api_key"

        # Mock API_BASE_URL
        self.api_base_url_patcher = patch("depictio.dash.api_calls.API_BASE_URL", "http://test-api")
        self.api_base_url_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.httpx_get_patcher.stop()
        self.settings_patcher.stop()
        self.api_base_url_patcher.stop()

    def test_get_anonymous_user_session_success(self):
        """Test successful retrieval of anonymous user session."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "logged_in": True,
            "email": "anon@depictio.io",
            "is_anonymous": True,
            "access_token": "test_token",
        }
        self.mock_httpx_get.return_value = mock_response

        # Act
        result = api_call_get_anonymous_user_session()

        # Assert
        assert result is not None
        assert result["logged_in"] is True
        assert result["email"] == "anon@depictio.io"
        assert result["is_anonymous"] is True

        # Verify HTTP call was made correctly
        self.mock_httpx_get.assert_called_once_with(
            "http://test-api/depictio/api/v1/auth/get_anonymous_user_session",
            headers={"api-key": "test_api_key"},
            timeout=10,
        )

    def test_get_anonymous_user_session_unauthenticated_mode_disabled(self):
        """Test when unauthenticated mode is disabled (403 status)."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 403
        self.mock_httpx_get.return_value = mock_response

        # Act
        result = api_call_get_anonymous_user_session()

        # Assert
        assert result is None
        self.mock_httpx_get.assert_called_once()

    def test_get_anonymous_user_session_api_error(self):
        """Test handling of API errors."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        self.mock_httpx_get.return_value = mock_response

        # Act
        result = api_call_get_anonymous_user_session()

        # Assert
        assert result is None
        self.mock_httpx_get.assert_called_once()


# ------------------------------------------------------
# Test api_call_create_temporary_user function
# ------------------------------------------------------


class TestApiCallCreateTemporaryUser:
    def setup_method(self):
        """Set up test fixtures."""
        # Mock httpx.post
        self.httpx_post_patcher = patch("depictio.dash.api_calls.httpx.post")
        self.mock_httpx_post = self.httpx_post_patcher.start()

        # Mock settings
        self.settings_patcher = patch("depictio.dash.api_calls.settings")
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.auth.internal_api_key = "test_api_key"

        # Mock API_BASE_URL
        self.api_base_url_patcher = patch("depictio.dash.api_calls.API_BASE_URL", "http://test-api")
        self.api_base_url_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.httpx_post_patcher.stop()
        self.settings_patcher.stop()
        self.api_base_url_patcher.stop()

    def test_create_temporary_user_success(self):
        """Test successful creation of temporary user."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "logged_in": True,
            "email": "temp_user_abc123@depictio.temp",
            "is_temporary": True,
            "access_token": "temp_token",
            "expiration_time": "2024-01-02T12:00:00",
        }
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_create_temporary_user(expiry_hours=48)

        # Assert
        assert result is not None
        assert result["logged_in"] is True
        assert result["is_temporary"] is True
        assert "temp_user_" in result["email"]

        # Verify HTTP call was made correctly
        self.mock_httpx_post.assert_called_once_with(
            "http://test-api/depictio/api/v1/auth/create_temporary_user",
            params={"expiry_hours": 48},
            headers={"api-key": "test_api_key"},
            timeout=30.0,
        )

    def test_create_temporary_user_default_expiry(self):
        """Test temporary user creation with default expiry."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"logged_in": True, "is_temporary": True}
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_create_temporary_user()

        # Assert
        assert result is not None

        # Verify default expiry_hours parameter
        self.mock_httpx_post.assert_called_once_with(
            "http://test-api/depictio/api/v1/auth/create_temporary_user",
            params={"expiry_hours": 24},
            headers={"api-key": "test_api_key"},
            timeout=30.0,
        )

    def test_create_temporary_user_api_error(self):
        """Test handling of API errors during user creation."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Database error"
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_create_temporary_user()

        # Assert
        assert result is None
        self.mock_httpx_post.assert_called_once()


# ------------------------------------------------------
# Test api_call_cleanup_expired_temporary_users function
# ------------------------------------------------------


class TestApiCallCleanupExpiredTemporaryUsers:
    def setup_method(self):
        """Set up test fixtures."""
        # Mock httpx.post
        self.httpx_post_patcher = patch("depictio.dash.api_calls.httpx.post")
        self.mock_httpx_post = self.httpx_post_patcher.start()

        # Mock settings
        self.settings_patcher = patch("depictio.dash.api_calls.settings")
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.auth.internal_api_key = "test_api_key"

        # Mock API_BASE_URL
        self.api_base_url_patcher = patch("depictio.dash.api_calls.API_BASE_URL", "http://test-api")
        self.api_base_url_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.httpx_post_patcher.stop()
        self.settings_patcher.stop()
        self.api_base_url_patcher.stop()

    def test_cleanup_expired_temporary_users_success(self):
        """Test successful cleanup of expired temporary users."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "expired_users_found": 5,
            "users_deleted": 5,
            "tokens_deleted": 8,
            "errors": [],
        }
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_cleanup_expired_temporary_users()

        # Assert
        assert result is not None
        assert result["users_deleted"] == 5
        assert result["tokens_deleted"] == 8
        assert len(result["errors"]) == 0

        # Verify HTTP call was made correctly
        self.mock_httpx_post.assert_called_once_with(
            "http://test-api/depictio/api/v1/auth/cleanup_expired_temporary_users",
            headers={"api-key": "test_api_key"},
            timeout=30.0,
        )

    def test_cleanup_expired_temporary_users_no_users(self):
        """Test cleanup when no expired users exist."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "expired_users_found": 0,
            "users_deleted": 0,
            "tokens_deleted": 0,
            "errors": [],
        }
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_cleanup_expired_temporary_users()

        # Assert
        assert result is not None
        assert result["users_deleted"] == 0
        assert result["tokens_deleted"] == 0

    def test_cleanup_expired_temporary_users_api_error(self):
        """Test handling of API errors during cleanup."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Cleanup failed"
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_cleanup_expired_temporary_users()

        # Assert
        assert result is None
        self.mock_httpx_post.assert_called_once()


# ------------------------------------------------------
# Test api_call_upgrade_to_temporary_user function
# ------------------------------------------------------


class TestApiCallUpgradeToTemporaryUser:
    def setup_method(self):
        """Set up test fixtures."""
        # Mock httpx.post
        self.httpx_post_patcher = patch("depictio.dash.api_calls.httpx.post")
        self.mock_httpx_post = self.httpx_post_patcher.start()

        # Mock API_BASE_URL
        self.api_base_url_patcher = patch("depictio.dash.api_calls.API_BASE_URL", "http://test-api")
        self.api_base_url_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.httpx_post_patcher.stop()
        self.api_base_url_patcher.stop()

    def test_upgrade_to_temporary_user_success(self):
        """Test successful upgrade from anonymous to temporary user."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "logged_in": True,
            "email": "temp_user_upgraded@depictio.temp",
            "is_temporary": True,
            "access_token": "new_temp_token",
            "expiration_time": "2024-01-02T12:00:00",
        }
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_upgrade_to_temporary_user("anon_token", expiry_hours=72)

        # Assert
        assert result is not None
        assert result["is_temporary"] is True
        assert "temp_user_" in result["email"]

        # Verify HTTP call was made correctly
        self.mock_httpx_post.assert_called_once_with(
            "http://test-api/depictio/api/v1/auth/upgrade_to_temporary_user",
            params={"expiry_hours": 72},
            headers={"Authorization": "Bearer anon_token"},
            timeout=30.0,
        )

    def test_upgrade_to_temporary_user_already_temporary(self):
        """Test upgrade when user is already temporary (400 status)."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 400
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_upgrade_to_temporary_user("temp_token")

        # Assert
        assert result is None
        self.mock_httpx_post.assert_called_once()

        # Verify default expiry_hours parameter
        called_args = self.mock_httpx_post.call_args
        assert called_args[1]["params"]["expiry_hours"] == 24

    def test_upgrade_to_temporary_user_api_error(self):
        """Test handling of API errors during upgrade."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Upgrade failed"
        self.mock_httpx_post.return_value = mock_response

        # Act
        result = api_call_upgrade_to_temporary_user("valid_token")

        # Assert
        assert result is None
        self.mock_httpx_post.assert_called_once()
