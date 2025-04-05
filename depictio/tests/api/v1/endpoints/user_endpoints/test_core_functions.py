import pytest
from unittest.mock import MagicMock, patch, AsyncMock, create_autospec
from bson import ObjectId
from typing import Optional


from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    fetch_user_from_email,
)
from depictio_models.models.users import UserBeanie
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    async_fetch_user_from_token,
)

# ------------------------------------------------------
# Test async_fetch_user_from_token function
# ------------------------------------------------------


class TestAsyncFetchUserFromToken:
    def setup_method(self):
        # Set up patches
        self.token_find_patcher = patch(
            "depictio_models.models.users.TokenBeanie.find_one", new_callable=AsyncMock
        )
        self.mock_token_find = self.token_find_patcher.start()

        self.user_get_patcher = patch(
            "depictio_models.models.users.UserBeanie.get", new_callable=AsyncMock
        )
        self.mock_user_get = self.user_get_patcher.start()

        # Create sample test data
        self.test_token = "test_token_12345abcdef"
        self.test_user_id = ObjectId("60d5ec9af682dcd2651257a1")

        # Mock token and user objects
        self.mock_token = MagicMock()
        self.mock_token.user_id = self.test_user_id

        self.mock_user = MagicMock()
        self.mock_user.fetch_all_links = AsyncMock()

    def teardown_method(self):
        # Stop all patches
        for patcher_attr in ["token_find_patcher", "user_get_patcher"]:
            if hasattr(self, patcher_attr):
                getattr(self, patcher_attr).stop()

    @pytest.mark.asyncio
    async def test_fetch_user_from_token_success(self):
        """Test successful user fetch from a valid token."""
        # Arrange
        self.mock_token_find.return_value = self.mock_token
        self.mock_user_get.return_value = self.mock_user

        # Act
        result = await async_fetch_user_from_token(self.test_token)

        # Assert
        self.mock_token_find.assert_called_once_with({"access_token": self.test_token})
        self.mock_user_get.assert_called_once_with(self.test_user_id)
        self.mock_user.fetch_all_links.assert_called_once()
        assert result == self.mock_user

    @pytest.mark.asyncio
    async def test_fetch_user_from_token_invalid_type(self):
        """Test with a non-string token."""
        # Arrange
        invalid_token = 12345  # Not a string

        # Act
        result = await async_fetch_user_from_token(invalid_token)

        # Assert
        assert result is None
        self.mock_token_find.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_user_from_token_empty_token(self):
        """Test with an empty token string."""
        # Act
        result = await async_fetch_user_from_token("")

        # Assert
        assert result is None
        self.mock_token_find.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_user_from_token_no_token_found(self):
        """Test when no token document is found."""
        # Arrange
        self.mock_token_find.return_value = None

        # Act
        result = await async_fetch_user_from_token(self.test_token)

        # Assert
        assert result is None
        self.mock_token_find.assert_called_once()
        self.mock_user_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_user_from_token_no_user_found(self):
        """Test when token exists but no matching user is found."""
        # Arrange
        self.mock_token_find.return_value = self.mock_token
        self.mock_user_get.return_value = None

        # Act
        result = await async_fetch_user_from_token(self.test_token)

        # Assert
        assert result is None
        self.mock_token_find.assert_called_once()
        self.mock_user_get.assert_called_once()


class TestFetchUserFromEmail:
    def setup_method(self):
        # Set up patches
        self.user_find_one_patcher = patch(
            "depictio_models.models.users.UserBeanie.find_one", new_callable=AsyncMock
        )
        self.mock_user_find_one = self.user_find_one_patcher.start()

        self.logger_patcher = patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.logger"
        )
        self.mock_logger = self.logger_patcher.start()

        # Test data
        self.test_email = "test@example.com"

    def teardown_method(self):
        # Stop all patches
        for patcher_attr in ["user_find_one_patcher", "logger_patcher"]:
            if hasattr(self, patcher_attr):
                getattr(self, patcher_attr).stop()

    @pytest.mark.asyncio
    async def test_fetch_user_from_email_success(self):
        """Test successful user fetch by email."""
        # Arrange
        mock_user = MagicMock(spec=UserBeanie)
        mock_user.fetch_all_links = AsyncMock()
        self.mock_user_find_one.return_value = mock_user

        # Act
        result = await fetch_user_from_email(self.test_email)

        # Assert
        self.mock_user_find_one.assert_called_once_with({"email": self.test_email})
        mock_user.fetch_all_links.assert_called_once()
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_fetch_user_from_email_not_found(self):
        """Test when no user is found for the given email."""
        # Arrange
        self.mock_user_find_one.return_value = None

        # Act
        result = await fetch_user_from_email(self.test_email)

        # Assert
        self.mock_user_find_one.assert_called_once_with({"email": self.test_email})
        assert result is None
        self.mock_logger.debug.assert_called_with(
            f"No user found with email {self.test_email}"
        )

    @pytest.mark.asyncio
    async def test_fetch_user_from_email_exception(self):
        """Test handling of database query exceptions."""
        # Arrange
        self.mock_user_find_one.side_effect = Exception("Database connection error")

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            await fetch_user_from_email(self.test_email)

        # Verify the exception details
        assert "Database connection error" in str(exc_info.value)
        self.mock_user_find_one.assert_called_once_with({"email": self.test_email})
