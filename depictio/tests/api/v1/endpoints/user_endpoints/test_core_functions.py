from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest
from beanie import PydanticObjectId, init_beanie
from bson import ObjectId
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient
from motor.core import AgnosticDatabase

from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _add_token,
    _async_fetch_user_from_email,
    _async_fetch_user_from_id,
    _async_fetch_user_from_token,
    _check_if_token_is_valid,
    _cleanup_expired_temporary_users,
    _create_temporary_user,
    _create_temporary_user_session,
    _delete_token,
    _edit_password,
    _get_anonymous_user_session,
    _hash_password,
    _list_tokens,
    _purge_expired_tokens,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import TokenBase, TokenBeanie, TokenData, UserBase, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

# ------------------------------------------------------
# Test _async_fetch_user_from_token function
# ------------------------------------------------------


class TestAsyncFetchUserFromToken:
    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_token_success(self):
        """Test successful user fetch from a valid token."""

        # Set up test data
        test_token = "test_token_12345abcdef"
        test_user_id = ObjectId("60d5ec9af682dcd2651257a1")

        # IMPORTANT: Make sure to patch the exact path where the function is imported
        # Not where it's defined, but where it's imported in the module being tested
        with (
            patch(
                "depictio.api.v1.endpoints.user_endpoints.core_functions.TokenBeanie.find_one",
                new_callable=AsyncMock,
            ) as mock_token_find,
            patch(
                "depictio.api.v1.endpoints.user_endpoints.core_functions.UserBeanie.get",
                new_callable=AsyncMock,
            ) as mock_user_get,
        ):
            # Mock token and user objects
            mock_token = MagicMock()
            mock_token.user_id = test_user_id
            mock_user = MagicMock(spec=UserBeanie)

            # Configure mocks
            mock_token_find.return_value = mock_token
            mock_user_get.return_value = mock_user

            # Act
            result = await _async_fetch_user_from_token(test_token)
            print(f"Result: {result}")

            # Assert
            mock_token_find.assert_called_once_with({"access_token": test_token})
            mock_user_get.assert_called_once_with(test_user_id)
            assert result == mock_user

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_token_invalid_type(self):
        """Test with a non-string token."""

        # Arrange
        invalid_token = "12345"  # Convert to string to pass validation

        # We'll patch the core function that actually does the database lookup
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.TokenBeanie.find_one",
            new_callable=AsyncMock,
        ) as mock_token_find:
            mock_token_find.return_value = None

            # Act
            result = await _async_fetch_user_from_token(invalid_token)

            # Assert
            assert result is None
            # Since we're passing a string now, the function will proceed to token lookup
            mock_token_find.assert_called_once_with({"access_token": invalid_token})

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_token_empty_token(self):
        """Test with an empty token string."""

        # Set up the mock
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.TokenBeanie.find_one",
            new_callable=AsyncMock,
        ) as mock_token_find:
            # Act
            result = await _async_fetch_user_from_token("")

            # Assert
            assert result is None
            mock_token_find.assert_not_called()

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_token_no_token_found(self):
        """Test when no token document is found."""
        # Set up test data
        test_token = "test_token_12345abcdef"

        # Arrange with mocks
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.TokenBeanie.find_one",
            new_callable=AsyncMock,
        ) as mock_token_find:
            mock_token_find.return_value = None

            # Act
            result = await _async_fetch_user_from_token(test_token)

            # Assert
            assert result is None
            mock_token_find.assert_called_once_with({"access_token": test_token})

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_token_no_user_found(self):
        """Test when token exists but no matching user is found."""

        # Set up test data
        test_token = "test_token_12345abcdef"
        test_user_id = ObjectId("60d5ec9af682dcd2651257a1")

        # Arrange with mocks
        with (
            patch(
                "depictio.api.v1.endpoints.user_endpoints.core_functions.TokenBeanie.find_one",
                new_callable=AsyncMock,
            ) as mock_token_find,
            patch(
                "depictio.api.v1.endpoints.user_endpoints.core_functions.UserBeanie.get",
                new_callable=AsyncMock,
            ) as mock_user_get,
        ):
            # Create mock token
            mock_token = MagicMock()
            mock_token.user_id = test_user_id

            # Configure mocks
            mock_token_find.return_value = mock_token
            mock_user_get.return_value = None

            # Act
            result = await _async_fetch_user_from_token(test_token)

            # Assert
            assert result is None
            mock_token_find.assert_called_once_with({"access_token": test_token})
            mock_user_get.assert_called_once_with(test_user_id)


# ------------------------------------------------------
# Test _async_fetch_user_from_email function
# ------------------------------------------------------


class TestAsyncFetchUserFromEmail:
    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_email_success(self):
        # Test data
        test_email = "test@example.com"

        # Set up mocks
        with (
            patch(
                "depictio.api.v1.endpoints.user_endpoints.core_functions.UserBeanie.find_one",
                new_callable=AsyncMock,
            ) as mock_user_find_one,
            patch(
                "depictio.api.v1.endpoints.user_endpoints.core_functions.format_pydantic"
            ) as mock_format_pydantic,
        ):
            # Configure mocks
            mock_user = MagicMock(spec=UserBeanie)
            mock_user_find_one.return_value = mock_user
            mock_format_pydantic.return_value = "formatted_user_output"

            # Act
            result = await _async_fetch_user_from_email(test_email)

            # Assert
            mock_user_find_one.assert_called_once_with({"email": test_email})
            assert result == mock_user

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_email_not_found(self):
        # Test data
        test_email = "test@example.com"

        # Set up mocks
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.UserBeanie.find_one",
            new_callable=AsyncMock,
        ) as mock_user_find_one:
            # Configure mocks
            mock_user_find_one.return_value = None

            # Act
            result = await _async_fetch_user_from_email(test_email)

            # Assert
            mock_user_find_one.assert_called_once_with({"email": test_email})
            assert result is None

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_email_with_mock_data(self):
        """Test fetching a user that actually exists in the mock database."""
        # Create test data
        test_email = "real_test@example.com"

        # Create and save a real user in the mock database
        # hash a password
        password = "hashed_password"
        hash_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        # Create a real user object
        real_user = UserBeanie(
            email=test_email,
            # Add other required fields for your UserBeanie model
            password=hash_password,
            # Add any other required fields
        )
        await real_user.save()

        # Act - Use the actual function without mocking
        result = await _async_fetch_user_from_email(test_email)

        # Assert
        assert result is not None
        assert result.email == test_email
        # check password is hashed
        assert result.password == hash_password
        assert isinstance(result, UserBeanie)
        # Additional assertions on other fields as needed


# ------------------------------------------------------
# Test async_fetch_user_from_id function
# ------------------------------------------------------


@pytest.mark.asyncio
class TestAsyncFetchUserFromId:
    # @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_id_success(self):
        """Test successful user fetch from a valid ID."""
        # Create test data
        test_user_id = PydanticObjectId()

        # Create and save a real user in the mock database
        # hash a password
        password = "hashed_password"
        hash_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        # Create a real user object
        real_user = UserBeanie(
            id=PyObjectId(str(test_user_id)),
            email="test_id@example.com",
            password=hash_password,
            # Add any other required fields
        )
        await real_user.save()

        # Act - Use the actual function without mocking
        result = await _async_fetch_user_from_id(test_user_id)

        # Assert
        assert result is not None
        assert str(result.id) == str(test_user_id)
        assert result.email == "test_id@example.com"
        assert result.password == hash_password
        assert isinstance(result, UserBeanie)

    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_fetch_user_from_id_not_found(self):
        """Test when no user is found with the given ID."""
        # Use a random ID that doesn't exist in the database
        non_existent_id = PydanticObjectId()

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await _async_fetch_user_from_id(non_existent_id)

        # Verify the exception
        assert exc_info.value.status_code == 404  # type: ignore[unresolved-attribute]
        assert exc_info.value.detail == "User not found"  # type: ignore[unresolved-attribute]


# ------------------------------------------------------
# Test _purge_expired_tokens function
# ------------------------------------------------------


@pytest.mark.asyncio
class TestPurgeExpiredTokensFromUser:
    async def test_purge_expired_tokens_successful(self):
        """Test successful purging of expired tokens."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        database: AgnosticDatabase = client.test_db
        await init_beanie(database=database, document_models=[TokenBeanie, UserBeanie])

        # Set up test data
        user_id = PydanticObjectId()

        # Create expired tokens
        expired_time = datetime.now() - timedelta(hours=1)
        for i in range(3):
            token = TokenBeanie(
                user_id=user_id,
                access_token=f"expired_token_{i}",
                expire_datetime=expired_time,
                name=f"expired_token_{i}",
                refresh_token=f"expired_refresh_token_{i}",
                refresh_expire_datetime=expired_time - timedelta(days=1),
            )
            await token.save()

        # Create a non-expired token (to verify it doesn't get deleted)
        future_time = datetime.now() + timedelta(hours=1)
        valid_token = TokenBeanie(
            user_id=user_id,
            access_token="valid_token",
            expire_datetime=future_time,
            name="valid_token",
            refresh_token="valid_refresh_token",
            refresh_expire_datetime=future_time + timedelta(days=7),
        )
        await valid_token.save()

        # Act
        result = await _purge_expired_tokens(
            user=UserBase(id=PyObjectId(str(user_id)), email="test_email@example.com")
        )

        # Assert
        # Verify the result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "deleted_count" in result
        assert result["success"] is True
        assert result["deleted_count"] == 3

        # Verify only expired tokens were deleted
        remaining_tokens = await TokenBeanie.find({"user_id": user_id}).to_list()
        assert len(remaining_tokens) == 1
        assert remaining_tokens[0].access_token == "valid_token"

    async def test_purge_expired_tokens_none_deleted(self):
        """Test when no expired tokens are found to delete."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        database: AgnosticDatabase = client.test_db
        await init_beanie(database=database, document_models=[TokenBeanie, UserBeanie])

        # Set up test data
        user_id = PydanticObjectId()

        # Create only non-expired tokens
        future_time = datetime.now() + timedelta(hours=1)
        for i in range(2):
            token = TokenBeanie(
                user_id=user_id,
                access_token=f"valid_token_{i}",
                expire_datetime=future_time,
                name=f"valid_token_{i}",
                refresh_token=f"valid_refresh_token_{i}",
                refresh_expire_datetime=future_time + timedelta(days=7),
            )
            await token.save()

        # Act
        result = await _purge_expired_tokens(
            user=UserBase(id=PyObjectId(str(user_id)), email="test_email@example.com")
        )

        # Assert
        assert result["success"] is True
        assert result["deleted_count"] == 0

        # Verify all tokens still exist
        remaining_tokens = await TokenBeanie.find({"user_id": user_id}).to_list()
        assert len(remaining_tokens) == 2

    async def test_purge_expired_tokens_no_tokens(self):
        """Test when user has no tokens at all."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        database: AgnosticDatabase = client.test_db
        await init_beanie(database=database, document_models=[TokenBeanie, UserBeanie])

        # Act
        result = await _purge_expired_tokens(
            user=UserBase(id=PyObjectId(), email="test_email@example.com")
        )

        # Assert
        assert result["success"] is True
        assert result["deleted_count"] == 0


class TestCheckIfTokenIsValidWithRefresh:
    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_check_if_token_valid_access_and_refresh(self):
        """Test when both access and refresh tokens are valid."""
        # Arrange
        user_id = PydanticObjectId()
        current_time = datetime.now()
        access_expire = current_time + timedelta(hours=1)
        refresh_expire = current_time + timedelta(days=7)

        # Create and save token with refresh token fields
        token_doc = TokenBeanie(
            user_id=user_id,
            access_token="valid_access_token",
            expire_datetime=access_expire,
            name="test_token",
            refresh_token="valid_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )
        await token_doc.save()

        token_to_check = TokenBase(
            user_id=user_id,
            access_token="valid_access_token",
            expire_datetime=access_expire,
            refresh_token="valid_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )

        # Act
        result = await _check_if_token_is_valid(token_to_check)

        # Assert enhanced behavior with refresh tokens implemented
        assert isinstance(result, dict)
        assert result["access_valid"] is True
        assert result["refresh_valid"] is True
        assert result["can_refresh"] is True
        assert result["action"] == "valid"

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_check_if_token_access_expired_refresh_valid(self):
        """Test when access token expired but refresh token valid."""
        # Arrange
        user_id = PydanticObjectId()
        current_time = datetime.now()
        access_expire = current_time - timedelta(hours=1)  # Expired
        refresh_expire = current_time + timedelta(days=7)  # Valid

        token_doc = TokenBeanie(
            user_id=user_id,
            access_token="expired_access_token",
            expire_datetime=access_expire,
            name="test_token",
            refresh_token="valid_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )
        await token_doc.save()

        token_to_check = TokenBase(
            user_id=user_id,
            access_token="expired_access_token",
            expire_datetime=access_expire,
            refresh_token="valid_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )

        # Act
        result = await _check_if_token_is_valid(token_to_check)

        # Assert refresh token behavior
        assert isinstance(result, dict)
        assert result["access_valid"] is False
        assert result["refresh_valid"] is True
        assert result["can_refresh"] is True
        assert result["action"] == "refresh"

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_check_if_token_both_expired(self):
        """Test when both access and refresh tokens are expired."""
        # Arrange
        user_id = PydanticObjectId()
        current_time = datetime.now()
        access_expire = current_time - timedelta(hours=2)  # Expired
        refresh_expire = current_time - timedelta(hours=1)  # Also expired

        token_doc = TokenBeanie(
            user_id=user_id,
            access_token="expired_token",
            expire_datetime=access_expire,
            name="test_token",
            refresh_token="expired_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )
        await token_doc.save()

        token_to_check = TokenBase(
            user_id=user_id,
            access_token="expired_token",
            expire_datetime=access_expire,
            refresh_token="expired_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )

        # Act
        result = await _check_if_token_is_valid(token_to_check)

        # Assert both tokens expired behavior
        assert isinstance(result, dict)
        assert result["access_valid"] is False
        assert result["refresh_valid"] is False
        assert result["can_refresh"] is False
        assert result["action"] == "logout"


# ------------------------------------------------------
# Test _list_tokens function
# ------------------------------------------------------


class TestListTokens:
    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_list_tokens_no_lifetime_filter(self):
        """Test listing tokens without specifying a token_lifetime."""
        # Create test data
        user_id = PydanticObjectId()

        # Create and save tokens with different lifetimes
        current_time = datetime.now()
        future_time = current_time + timedelta(hours=1)

        # Create short-lived token
        short_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="short_lived_token",
            expire_datetime=future_time,
            name="short_lived_token",
            token_lifetime="short-lived",
            refresh_token="short_lived_refresh_token",
            refresh_expire_datetime=future_time + timedelta(days=7),
        )
        await short_lived_token.save()

        # Create long-lived token
        long_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="long_lived_token",
            expire_datetime=future_time,
            name="long_lived_token",
            token_lifetime="long-lived",
            refresh_token="long_lived_refresh_token",
            refresh_expire_datetime=future_time + timedelta(days=30),
        )
        await long_lived_token.save()

        # Act
        result = await _list_tokens(user_id)

        # Assert
        assert len(result) == 2
        token_lifetimes = [token.token_lifetime for token in result]
        assert "short-lived" in token_lifetimes
        assert "long-lived" in token_lifetimes

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_list_tokens_with_short_lived_filter(self):
        """Test listing tokens with token_lifetime='short-lived'."""
        # Create test data
        user_id = PydanticObjectId()

        # Create and save tokens with different lifetimes
        current_time = datetime.now()
        future_time = current_time + timedelta(hours=1)

        # Create short-lived token
        short_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="short_lived_token",
            expire_datetime=future_time,
            name="short_lived_token",
            token_lifetime="short-lived",
            refresh_token="short_lived_refresh_token",
            refresh_expire_datetime=future_time + timedelta(days=7),
        )
        await short_lived_token.save()

        # Create long-lived token
        long_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="long_lived_token",
            expire_datetime=future_time,
            name="long_lived_token",
            token_lifetime="long-lived",
            refresh_token="long_lived_refresh_token",
            refresh_expire_datetime=future_time + timedelta(days=30),
        )
        await long_lived_token.save()

        # Act
        result = await _list_tokens(user_id, token_lifetime="short-lived")

        # Assert
        assert len(result) == 1
        assert result[0].token_lifetime == "short-lived"
        assert result[0].access_token == "short_lived_token"

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_list_tokens_with_long_lived_filter(self):
        """Test listing tokens with token_lifetime='long-lived'."""
        # Create test data
        user_id = PydanticObjectId()

        # Create and save tokens with different lifetimes
        current_time = datetime.now()
        future_time = current_time + timedelta(hours=1)

        # Create short-lived token
        short_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="short_lived_token",
            expire_datetime=future_time,
            name="short_lived_token",
            token_lifetime="short-lived",
            refresh_token="short_lived_refresh_token",
            refresh_expire_datetime=future_time + timedelta(days=7),
        )
        await short_lived_token.save()

        # Create long-lived token
        long_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="long_lived_token",
            expire_datetime=future_time,
            name="long_lived_token",
            token_lifetime="long-lived",
            refresh_token="long_lived_refresh_token",
            refresh_expire_datetime=future_time + timedelta(days=30),
        )
        await long_lived_token.save()

        # Act
        result = await _list_tokens(user_id, token_lifetime="long-lived")

        # Assert
        assert len(result) == 1
        assert result[0].token_lifetime == "long-lived"
        assert result[0].access_token == "long_lived_token"

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_list_tokens_invalid_lifetime(self):
        """Test that an invalid token_lifetime raises HTTPException."""
        # Create test data
        user_id = PydanticObjectId()

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await _list_tokens(user_id, token_lifetime="invalid-lifetime")

        # Verify the exception
        assert exc_info.value.status_code == 400  # type: ignore[unresolved-attribute]
        assert "Invalid token_lifetime" in exc_info.value.detail  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_list_tokens_empty_result(self):
        """Test when no tokens are found."""
        # Create test data - user with no tokens
        user_id = PydanticObjectId()

        # Act
        result = await _list_tokens(user_id)

        # Assert
        assert len(result) == 0
        assert isinstance(result, list)


# ------------------------------------------------------
# Test _delete_token function
# ------------------------------------------------------


class TestDeleteToken:
    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_delete_token_success(self):
        """Test successful token deletion."""

        # Create a token
        token = TokenBeanie(
            user_id=PydanticObjectId(),
            access_token="token_to_delete",
            expire_datetime=datetime.now() + timedelta(hours=1),
            name="token_to_delete",
            refresh_token="refresh_token_to_delete",
            refresh_expire_datetime=datetime.now() + timedelta(days=7),
        )
        await token.save()

        token_id = token.id

        # Act
        result = await _delete_token(token_id)

        # Assert
        assert result is True

        # Verify the token was actually deleted
        deleted_token = await TokenBeanie.get(token_id)
        assert deleted_token is None

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_delete_token_nonexistent(self):
        """Test deleting a token that doesn't exist."""
        # Create a non-existent token ID
        nonexistent_token_id = PydanticObjectId()

        # Act
        result = await _delete_token(nonexistent_token_id)

        # Assert
        assert result is False


# ------------------------------------------------------
# Test _edit_password function
# ------------------------------------------------------


class TestEditPassword:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_edit_password_success(self, generate_hashed_password):
        """Test successful password update."""
        # Arrange
        user_id = PydanticObjectId()
        new_password = generate_hashed_password("new_secure_password123")
        print(f"New password: {new_password}")

        # Create test user
        test_user = UserBeanie(
            id=PyObjectId(str(user_id)),
            email="test@example.com",
            password=generate_hashed_password("old_password123"),
        )
        await test_user.save()

        # Act
        result = await _edit_password(user_id, new_password)

        # Assert
        assert result is True

        # Verify password was updated in database
        updated_user = await UserBeanie.get(user_id)
        assert updated_user is not None
        assert updated_user.password == new_password

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_edit_password_user_not_found(self, generate_hashed_password):
        """Test password update when user doesn't exist."""
        # Arrange
        non_existent_user_id = PydanticObjectId()
        new_password = generate_hashed_password("new_secure_password123")

        # Act
        result = await _edit_password(non_existent_user_id, new_password)

        # Assert
        assert result is False


# ------------------------------------------------------
# Test _add_token function
# ------------------------------------------------------


class TestAddToken:
    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_add_token_success(self):
        """Test successful token creation and storage."""
        # Arrange
        user_id = PydanticObjectId()
        token_data = TokenData(
            sub=PyObjectId(str(user_id)),
            name="Test Token",
            token_lifetime="short-lived",
        )

        # Act
        result = await _add_token(token_data)

        # Assert
        assert result is not None
        assert isinstance(result, TokenBeanie)
        assert result.name == "Test Token"
        assert result.token_lifetime == "short-lived"
        assert result.user_id == user_id

        # Verify token exists in database with correct properties
        saved_token = await TokenBeanie.find_one({"user_id": user_id})
        assert saved_token is not None
        assert saved_token.name == "Test Token"
        assert saved_token.token_lifetime == "short-lived"
        assert saved_token.user_id == user_id

        # Verify refresh token fields are set
        assert saved_token.refresh_token is not None
        assert len(saved_token.refresh_token) > 0
        assert saved_token.refresh_expire_datetime > datetime.now()

        # Verify token has valid access token and expiration
        assert saved_token.access_token is not None
        assert len(saved_token.access_token) > 0

        # Verify the expiration datetime is in the future
        assert saved_token.expire_datetime > datetime.now()

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_add_token_database_error(self):
        """Test token creation when database save fails."""
        # Arrange
        user_id = PydanticObjectId()
        token_data = TokenData(
            sub=PyObjectId(str(user_id)),
            name="Test Token",
            token_lifetime="short-lived",
        )

        # We need to patch the TokenBeanie.save method
        with patch.object(TokenBeanie, "save", side_effect=Exception("Database error")):
            # Act & Assert
            with pytest.raises(Exception):
                await _add_token(token_data)

            # Verify no token was saved to the database
            saved_token = await TokenBeanie.find_one({"user_id": user_id})
            assert saved_token is None

    @pytest.mark.asyncio
    @beanie_setup(models=[TokenBeanie])
    async def test_add_token_with_different_lifetimes(self):
        """Test token creation with different lifetime values."""
        # Arrange
        user_id = PydanticObjectId()
        lifetimes = ["short-lived", "long-lived", "permanent"]

        for lifetime in lifetimes:
            token_data = TokenData(
                sub=PyObjectId(str(user_id)),
                name=f"Test Token {lifetime}",
                token_lifetime=lifetime,
            )

            # Act
            result = await _add_token(token_data)

            # Assert
            assert result is not None
            assert result.token_lifetime == lifetime

            # Verify token was saved to the database with correct properties
            saved_token = await TokenBeanie.find_one({"name": f"Test Token {lifetime}"})
            assert saved_token is not None
            assert saved_token.token_lifetime == lifetime
            assert saved_token.user_id == user_id

            # Verify refresh token fields are set
            assert saved_token.refresh_token is not None
            if lifetime != "permanent":
                assert len(saved_token.refresh_token) > 0
                assert saved_token.refresh_expire_datetime > datetime.now()


# ------------------------------------------------------
# Test _create_temporary_user function
# ------------------------------------------------------


class TestCreateTemporaryUser:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_create_temporary_user_default_expiry(self):
        """Test creating a temporary user with default 24-hour expiry."""
        # Act
        result = await _create_temporary_user()

        # Assert
        assert result is not None
        assert isinstance(result, UserBeanie)
        assert result.is_temporary is True
        assert result.is_anonymous is False
        assert result.is_admin is False
        assert result.email.startswith("temp_user_")
        assert result.email.endswith("@depictio.temp")
        assert result.expiration_time is not None

        # Check expiration time is approximately 24 hours from now
        time_diff = result.expiration_time - datetime.now()
        assert 23.5 <= time_diff.total_seconds() / 3600 <= 24.5

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_create_temporary_user_custom_expiry(self):
        """Test creating a temporary user with custom expiry time."""
        custom_hours = 48

        # Act
        result = await _create_temporary_user(expiry_hours=custom_hours)

        # Assert
        assert result is not None
        assert result.is_temporary is True

        # Check expiration time is approximately 48 hours from now
        time_diff = result.expiration_time - datetime.now()
        assert 47.5 <= time_diff.total_seconds() / 3600 <= 48.5

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_create_temporary_user_unique_emails(self):
        """Test that multiple temporary users get unique emails."""
        # Act - Create multiple temporary users
        user1 = await _create_temporary_user()
        user2 = await _create_temporary_user()

        # Assert - All emails should be different
        assert user1.email != user2.email

        # All should follow the temp user email pattern
        for user in [user1, user2]:
            assert user.email.startswith("temp_user_")
            assert user.email.endswith("@depictio.temp")


# ------------------------------------------------------
# Test _create_temporary_user_session function
# ------------------------------------------------------


class TestCreateTemporaryUserSession:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_create_temporary_user_session_success(self):
        """Test successful creation of temporary user session."""
        # Arrange - Create a temporary user first
        temp_user = await _create_temporary_user(expiry_hours=12)

        # Act
        session_data = await _create_temporary_user_session(temp_user)

        # Assert session data structure
        assert isinstance(session_data, dict)
        assert session_data["logged_in"] is True
        assert session_data["email"] == temp_user.email
        assert session_data["user_id"] == str(temp_user.id)
        assert session_data["is_temporary"] is True
        assert session_data["access_token"] is not None
        assert session_data["token_lifetime"] == "long-lived"
        assert session_data["token_type"] == "bearer"

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_create_temporary_user_session_expiry_calculation(self):
        """Test that session expiry matches user expiry time."""
        # Arrange - Create temp user with specific expiry
        expiry_hours = 6
        temp_user = await _create_temporary_user(expiry_hours=expiry_hours)

        # Act
        session_data = await _create_temporary_user_session(temp_user)

        # Assert - Token expiry should be close to user expiry
        token_expiry = datetime.fromisoformat(session_data["expire_datetime"])
        user_expiry = temp_user.expiration_time

        # Should be within a few seconds of each other
        time_diff = abs((token_expiry - user_expiry).total_seconds())
        assert time_diff < 60 * 60 * expiry_hours

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_create_temporary_user_session_no_expiration_time(self):
        """Test session creation when user has no expiration time."""
        # Arrange - Create user manually without expiration time
        temp_user = UserBeanie(
            email="temp_no_expiry@depictio.temp",
            password=_hash_password("temp_pass"),
            is_temporary=True,
            is_anonymous=False,
            is_admin=False,
            # expiration_time=None (not set)
        )
        await temp_user.create()

        # Act
        session_data = await _create_temporary_user_session(temp_user)

        # Assert - Should still work with default 24-hour expiry
        assert session_data["logged_in"] is True
        assert session_data["expiration_time"] is None


# ------------------------------------------------------
# Test _cleanup_expired_temporary_users function
# ------------------------------------------------------


class TestCleanupExpiredTemporaryUsers:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_cleanup_expired_users_success(self):
        """Test successful cleanup of expired temporary users."""
        # Arrange - Create expired and non-expired temporary users
        current_time = datetime.now()

        # Create expired user
        expired_user = UserBeanie(
            email="expired@depictio.temp",
            password=_hash_password("expired_pass"),
            is_temporary=True,
            expiration_time=current_time - timedelta(hours=1),
        )
        await expired_user.create()

        # Create non-expired user
        valid_user = UserBeanie(
            email="valid@depictio.temp",
            password=_hash_password("valid_pass"),
            is_temporary=True,
            expiration_time=current_time + timedelta(hours=1),
        )
        await valid_user.create()

        # Create token for expired user
        assert expired_user.id is not None, "Expired user ID should be set after creation"
        user_id = (
            expired_user.id
            if isinstance(expired_user.id, PydanticObjectId)
            else PydanticObjectId(str(expired_user.id))
        )
        token = TokenBeanie(
            user_id=user_id,
            access_token="expired_token",
            refresh_token="expired_refresh_token",
            expire_datetime=current_time + timedelta(hours=1),
            refresh_expire_datetime=current_time + timedelta(days=7),
            name="expired_user_token",
        )
        await token.save()

        # Act
        result = await _cleanup_expired_temporary_users()

        # Assert cleanup results
        assert result["expired_users_found"] == 1
        assert result["users_deleted"] == 1
        assert result["tokens_deleted"] == 1
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_cleanup_no_expired_users(self):
        """Test cleanup when no expired users exist."""
        # Arrange - Create only non-expired users
        current_time = datetime.now()

        valid_user = UserBeanie(
            email="valid@depictio.temp",
            password=_hash_password("valid_pass"),
            is_temporary=True,
            expiration_time=current_time + timedelta(hours=1),
        )
        await valid_user.create()

        # Act
        result = await _cleanup_expired_temporary_users()

        # Assert
        assert result["expired_users_found"] == 0
        assert result["users_deleted"] == 0
        assert result["tokens_deleted"] == 0
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_cleanup_excludes_non_temporary_users(self):
        """Test that cleanup doesn't affect non-temporary users."""
        # Arrange - Create regular users with past dates
        current_time = datetime.now()

        regular_user = UserBeanie(
            email="regular@example.com",
            password=_hash_password("regular_pass"),
            is_temporary=False,  # Regular user
            expiration_time=current_time - timedelta(hours=1),  # Past date
        )
        await regular_user.create()

        # Act
        result = await _cleanup_expired_temporary_users()

        # Assert - No users should be deleted
        assert result["expired_users_found"] == 0
        assert result["users_deleted"] == 0


# ------------------------------------------------------
# Test _get_anonymous_user_session function
# ------------------------------------------------------


class TestGetAnonymousUserSession:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_get_anonymous_user_session_success(self):
        """Test successful retrieval of anonymous user session."""
        # Arrange - Create anonymous user and permanent token
        anonymous_email = "anon@depictio.io"

        anon_user = UserBeanie(
            email=anonymous_email,
            password=_hash_password("hashed_empty_password"),
            is_anonymous=True,
            is_admin=False,
        )
        await anon_user.create()

        # Create permanent token
        assert anon_user.id is not None, "Anonymous user ID should be set after creation"
        user_id_pydantic = (
            anon_user.id
            if isinstance(anon_user.id, PydanticObjectId)
            else PydanticObjectId(str(anon_user.id))
        )
        permanent_token = TokenBeanie(
            user_id=user_id_pydantic,
            access_token="permanent_access_token",
            refresh_token="permanent_refresh_token",
            expire_datetime=datetime.max,
            refresh_expire_datetime=datetime.max,
            name="anonymous_permanent_token",
            token_lifetime="permanent",
            logged_in=True,
            token_type="bearer",
        )
        await permanent_token.save()

        # Mock settings to return our test email
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.settings"
        ) as mock_settings:
            mock_settings.auth.anonymous_user_email = anonymous_email

            # Act
            session_data = await _get_anonymous_user_session()

        # Assert session data structure
        assert isinstance(session_data, dict)
        assert session_data["logged_in"] is True
        assert session_data["email"] == anonymous_email
        assert session_data["is_anonymous"] is True
        assert session_data["access_token"] == "permanent_access_token"
        assert session_data["token_lifetime"] == "permanent"

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_get_anonymous_user_session_user_not_found(self):
        """Test error when anonymous user doesn't exist."""
        # Mock settings with non-existent user email
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.settings"
        ) as mock_settings:
            mock_settings.auth.anonymous_user_email = "nonexistent@example.com"

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _get_anonymous_user_session()

            assert exc_info.value.status_code == 404  # type: ignore[unresolved-attribute]
            assert "Anonymous user not found" in str(exc_info.value.detail)  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_get_anonymous_user_session_no_permanent_token(self):
        """Test error when anonymous user has no permanent token."""
        # Arrange - Create anonymous user without permanent token
        anonymous_email = "anon@depictio.io"

        anon_user = UserBeanie(
            email=anonymous_email,
            password=_hash_password("hashed_empty_password"),
            is_anonymous=True,
            is_admin=False,
        )
        await anon_user.create()

        # Create only short-lived token (not permanent)
        assert anon_user.id is not None, "Anonymous user ID should be set after creation"
        user_id_pydantic = (
            anon_user.id
            if isinstance(anon_user.id, PydanticObjectId)
            else PydanticObjectId(str(anon_user.id))
        )
        short_token = TokenBeanie(
            user_id=user_id_pydantic,
            access_token="short_lived_token",
            refresh_token="short_lived_refresh_token",
            expire_datetime=datetime.now() + timedelta(hours=1),
            refresh_expire_datetime=datetime.now() + timedelta(days=1),
            name="short_lived_token",
            token_lifetime="short-lived",
        )
        await short_token.save()

        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.settings"
        ) as mock_settings:
            mock_settings.auth.anonymous_user_email = anonymous_email

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _get_anonymous_user_session()

            assert exc_info.value.status_code == 404  # type: ignore[unresolved-attribute]
            assert "No permanent token found" in str(exc_info.value.detail)  # type: ignore[unresolved-attribute]
