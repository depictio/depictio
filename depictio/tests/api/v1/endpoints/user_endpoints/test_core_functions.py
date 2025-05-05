from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest
from beanie import PydanticObjectId, init_beanie
from bson import ObjectId
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _add_token,
    _async_fetch_user_from_email,
    _async_fetch_user_from_id,
    _async_fetch_user_from_token,
    _check_if_token_is_valid,
    _delete_token,
    _edit_password,
    _list_tokens,
    _purge_expired_tokens,
)
from depictio.models.models.users import TokenBeanie, TokenData, UserBase, UserBeanie
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
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.TokenBeanie.find_one",
            new_callable=AsyncMock,
        ) as mock_token_find, patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.UserBeanie.get",
            new_callable=AsyncMock,
        ) as mock_user_get:
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
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.TokenBeanie.find_one",
            new_callable=AsyncMock,
        ) as mock_token_find, patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.UserBeanie.get",
            new_callable=AsyncMock,
        ) as mock_user_get:
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
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.UserBeanie.find_one",
            new_callable=AsyncMock,
        ) as mock_user_find_one, patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.format_pydantic"
        ) as mock_format_pydantic:
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
        hash_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
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
        hash_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        # Create a real user object
        real_user = UserBeanie(
            id=test_user_id,
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

    async def test_fetch_user_from_id_not_found(self):
        """Test when no user is found with the given ID."""
        # Use a random ID that doesn't exist in the database
        non_existent_id = PydanticObjectId()

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await _async_fetch_user_from_id(non_existent_id)

        # Verify the exception
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"


# ------------------------------------------------------
# Test _purge_expired_tokens function
# ------------------------------------------------------


@pytest.mark.asyncio
class TestPurgeExpiredTokensFromUser:
    async def test_purge_expired_tokens_successful(self):
        """Test successful purging of expired tokens."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(
            database=client.test_db, document_models=[TokenBeanie, UserBeanie]
        )

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
            )
            await token.save()

        # Create a non-expired token (to verify it doesn't get deleted)
        future_time = datetime.now() + timedelta(hours=1)
        valid_token = TokenBeanie(
            user_id=user_id,
            access_token="valid_token",
            expire_datetime=future_time,
            name="valid_token",
        )
        await valid_token.save()

        # Act
        result = await _purge_expired_tokens(
            user=UserBase(id=user_id, email="test_email@example.com")
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
        await init_beanie(
            database=client.test_db, document_models=[TokenBeanie, UserBeanie]
        )

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
            )
            await token.save()

        # Act
        result = await _purge_expired_tokens(
            user=UserBase(id=user_id, email="test_email@example.com")
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
        await init_beanie(
            database=client.test_db, document_models=[TokenBeanie, UserBeanie]
        )

        # Act
        result = await _purge_expired_tokens(
            user=UserBase(id=PydanticObjectId(), email="test_email@example.com")
        )

        # Assert
        assert result["success"] is True
        assert result["deleted_count"] == 0


@pytest.mark.asyncio
class TestCheckIfTokenIsValid:
    async def test_check_if_token_is_valid_token_exists(self):
        """Test when token exists and is not expired."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        # Set up test data
        user_id = PydanticObjectId()
        future_time = datetime.now() + timedelta(hours=1)

        # Create a valid token
        token = TokenBeanie(
            user_id=user_id,
            access_token="valid_token",
            expire_datetime=future_time,
            name="valid_token",
        )
        print(format_pydantic(token))

        await token.save()

        # Act
        result = await _check_if_token_is_valid(token)

        print(result)

        # Assert
        assert result is True

    async def test_check_if_token_is_valid_token_expired(self):
        """Test when token exists but is expired."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        # Set up test data
        user_id = PydanticObjectId()
        expired_time = datetime.now() - timedelta(hours=1)

        # Create an expired token
        token = TokenBeanie(
            user_id=user_id,
            access_token="expired_token",
            expire_datetime=expired_time,
            name="expired_token",
        )
        await token.save()

        # Patch the logger to avoid actual logging during tests
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.logger"
        ) as mock_logger:
            # Act
            result = await _check_if_token_is_valid(token)

            # Assert
            assert result is False

            # Verify logging
            mock_logger.debug.assert_called_once()

    async def test_check_if_token_is_valid_token_not_found(self):
        """Test when token does not exist in database."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        # Set up test data - token not saved to database
        user_id = PydanticObjectId()
        future_time = datetime.now() + timedelta(hours=1)

        # Create a token but don't save it
        token = TokenBeanie(
            user_id=user_id,
            access_token="unsaved_token",
            expire_datetime=future_time,
            name="unsaved_token",
        )

        # Patch the logger to avoid actual logging during tests
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.logger"
        ) as mock_logger:
            # Act
            result = await _check_if_token_is_valid(token)

            # Assert
            assert result is False

            # Verify logging
            mock_logger.debug.assert_called_once()

    async def test_check_if_token_is_valid_wrong_user(self):
        """Test when token exists but for a different user."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        # Set up test data
        user_id1 = PydanticObjectId()
        user_id2 = PydanticObjectId()  # Different user
        future_time = datetime.now() + timedelta(hours=1)

        # Create a token for user1
        token = TokenBeanie(
            user_id=user_id1,
            access_token="valid_token",
            expire_datetime=future_time,
            name="valid_token",
        )
        await token.save()

        # But try to validate it for user2
        token_to_check = TokenBeanie(
            user_id=user_id2,  # Different user
            access_token="valid_token",  # Same token
            expire_datetime=future_time,
            name="valid_token",
        )

        # Patch the logger to avoid actual logging during tests
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions.logger"
        ) as mock_logger:
            # Act
            result = await _check_if_token_is_valid(token_to_check)

            # Assert
            assert result is False

            # Verify logging
            mock_logger.debug.assert_called_once()


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
        )
        await short_lived_token.save()

        # Create long-lived token
        long_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="long_lived_token",
            expire_datetime=future_time,
            name="long_lived_token",
            token_lifetime="long-lived",
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
        )
        await short_lived_token.save()

        # Create long-lived token
        long_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="long_lived_token",
            expire_datetime=future_time,
            name="long_lived_token",
            token_lifetime="long-lived",
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
        )
        await short_lived_token.save()

        # Create long-lived token
        long_lived_token = TokenBeanie(
            user_id=user_id,
            access_token="long_lived_token",
            expire_datetime=future_time,
            name="long_lived_token",
            token_lifetime="long-lived",
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
        assert exc_info.value.status_code == 400
        assert "Invalid token_lifetime" in exc_info.value.detail

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
            id=user_id,
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
            sub=user_id,
            name="Test Token",
            token_lifetime="short-lived",
            exp=datetime.now() + timedelta(hours=1),
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
            sub=user_id,
            name="Test Token",
            token_lifetime="short-lived",
            exp=datetime.now() + timedelta(hours=1),
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
        lifetimes = ["short-lived", "long-lived"]

        for lifetime in lifetimes:
            token_data = TokenData(
                sub=user_id,
                name=f"Test Token {lifetime}",
                token_lifetime=lifetime,
                exp=datetime.now() + timedelta(hours=1),
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
