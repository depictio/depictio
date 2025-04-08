from bson import ObjectId
import pytest
import bcrypt
from unittest.mock import patch, MagicMock, call
import mongomock

from depictio.api.v1.endpoints.user_endpoints.utils import (
    hash_password,
    verify_password,
)
from depictio_models.models.users import Group


# Patch pymongo.MongoClient before any module using it is imported.
@patch("pymongo.MongoClient", new=mongomock.MongoClient)
def test_dummy_connection():
    # Now import the modules after the patch is in place.
    from depictio.api.v1.db import client  # This will be a mongomock client
    from depictio.api.v1.endpoints.user_endpoints.utils import (
        _ensure_mongodb_connection,
    )

    # Update _dummy_mongodb_connection to call server_info() for example
    result = _ensure_mongodb_connection()  # Ensure this calls client.server_info()

    # Since mongomock doesn't really block, the test should complete immediately.
    # You can assert on the expected behavior.
    # For instance, if _dummy_mongodb_connection() returns server_info(), you can assert:
    assert result == client.server_info()


# -------------------------------
# Test for hash_password
# -------------------------------
class TestHashPassword:
    """
    Test suite for the hash_password function.
    """

    def test_hash_password(self):
        """Test that hash_password returns a valid bcrypt hash."""
        # Arrange
        password = "secure_password123"

        # Act
        hashed_password = hash_password(password)

        # Assert
        # Check that it returns a string
        assert isinstance(hashed_password, str)
        # Check that it starts with the bcrypt identifier
        assert hashed_password.startswith("$2b$")
        # Verify that the hash is valid by checking it against the original password
        assert bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))

    def test_hash_password_with_empty_string(self):
        """Test that hash_password works with an empty string."""
        # Arrange
        password = ""

        # Act
        hashed_password = hash_password(password)

        # Assert
        assert isinstance(hashed_password, str)
        assert bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))

    def test_hash_password_different_inputs_different_hashes(self):
        """Test that different passwords produce different hashes."""
        # Arrange
        password1 = "password1"
        password2 = "password2"

        # Act
        hash1 = hash_password(password1)
        hash2 = hash_password(password2)

        # Assert
        assert hash1 != hash2

    def test_hash_password_same_input_different_salt(self):
        """Test that same password with different salts produces different hashes."""
        # Arrange
        password = "same_password"

        # Act
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Assert
        assert hash1 != hash2  # Different salts should produce different hashes

    @patch("bcrypt.gensalt")
    @patch("bcrypt.hashpw")
    def test_hash_password_internals(self, mock_hashpw, mock_gensalt):
        """Test the internal behavior of hash_password."""
        # Arrange
        mock_salt = b"$2b$12$mockSaltValue"
        mock_gensalt.return_value = mock_salt

        mock_hash = b"$2b$12$mockSaltValueHashedPasswordResult"
        mock_hashpw.return_value = mock_hash

        password = "test_password"

        # Act
        result = hash_password(password)

        # Assert
        mock_gensalt.assert_called_once()
        mock_hashpw.assert_called_once_with(password.encode("utf-8"), mock_salt)
        assert result == mock_hash.decode("utf-8")


# -------------------------------
# Test for verify_password
# -------------------------------
class TestVerifyPassword:
    """Tests for the verify_password function."""

    def test_verify_password_correct(self):
        """Test that verify_password returns True for correct password."""
        # Arrange
        password = "secure_password123"
        hashed_password = hash_password(password)

        # Act
        result = verify_password(hashed_password, password)

        # Assert
        assert result is True

    def test_verify_password_incorrect(self):
        """Test that verify_password returns False for incorrect password."""
        # Arrange
        correct_password = "secure_password123"
        incorrect_password = "wrong_password"
        hashed_password = hash_password(correct_password)

        # Act
        result = verify_password(hashed_password, incorrect_password)

        # Assert
        assert result is False

    def test_verify_password_empty_string(self):
        """Test that verify_password works with empty string."""
        # Arrange
        password = ""
        hashed_password = hash_password(password)

        # Act
        result = verify_password(hashed_password, password)

        # Assert
        assert result is True

    @patch("bcrypt.checkpw")
    def test_verify_password_internals(self, mock_checkpw):
        """Test the internal behavior of verify_password."""
        # Arrange
        stored_hash = "$2b$12$some_hashed_value"
        password = "test_password"
        mock_checkpw.return_value = True

        # Act
        result = verify_password(stored_hash, password)

        # Assert
        mock_checkpw.assert_called_once_with(
            password.encode("utf-8"), stored_hash.encode("utf-8")
        )
        assert result is True


# -------------------------------
# Test for async check_password
# -------------------------------


class TestCheckPassword:
    @classmethod
    def setup_class(cls):
        # Import the function once and store it as a class attribute
        from depictio.api.v1.endpoints.user_endpoints.utils import check_password

        cls.check_password = staticmethod(check_password)

    def setup_method(self, method):
        # Set up patches
        self.fetch_user_patcher = patch(
            "depictio.api.v1.endpoints.user_endpoints.utils.fetch_user_from_email"
        )
        self.mock_fetch_user = self.fetch_user_patcher.start()

        self.logger_patcher = patch(
            "depictio.api.v1.endpoints.user_endpoints.utils.logger"
        )
        self.mock_logger = self.logger_patcher.start()

        self.verify_password_patcher = patch(
            "depictio.api.v1.endpoints.user_endpoints.utils.verify_password"
        )
        self.mock_verify_password = self.verify_password_patcher.start()

    def teardown_method(self, method):
        # Stop all patches
        for patcher_attr in [
            "fetch_user_patcher",
            "verify_password_patcher",
            "logger_patcher",
        ]:
            if hasattr(self, patcher_attr):
                getattr(self, patcher_attr).stop()

    @pytest.mark.asyncio
    async def test_check_password_user_found_password_correct(self):
        """Test when user is found and password is correct."""
        # Arrange
        test_email = "test@example.com"
        test_password = "correct_password"

        # Create a mock user with a password
        mock_user = MagicMock()
        mock_user.password = "hashed_password"

        # Configure mocks
        self.mock_fetch_user.return_value = mock_user
        self.mock_verify_password.return_value = True

        # Act
        result = await self.check_password(test_email, test_password)

        # Assert
        self.mock_fetch_user.assert_called_once_with(test_email)
        self.mock_logger.debug.assert_any_call(
            f"Checking password for user {test_email}."
        )
        self.mock_logger.debug.assert_any_call(f"User found: {mock_user}")
        self.mock_verify_password.assert_called_once_with(
            mock_user.password, test_password
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_check_password_user_found_password_incorrect(self):
        """Test when user is found but password is incorrect."""
        # Arrange
        test_email = "test@example.com"
        test_password = "wrong_password"

        # Create a mock user with a password
        mock_user = MagicMock()
        mock_user.password = "hashed_password"

        # Configure mocks
        self.mock_fetch_user.return_value = mock_user
        self.mock_verify_password.return_value = False

        # Act
        result = await self.check_password(test_email, test_password)

        # Assert
        self.mock_fetch_user.assert_called_once_with(test_email)
        self.mock_logger.debug.assert_any_call(
            f"Checking password for user {test_email}."
        )
        self.mock_logger.debug.assert_any_call(f"User found: {mock_user}")
        self.mock_verify_password.assert_called_once_with(
            mock_user.password, test_password
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_check_password_user_not_found(self):
        """Test when user is not found."""
        # Arrange
        test_email = "nonexistent@example.com"
        test_password = "any_password"

        # Configure mock to return None (user not found)
        self.mock_fetch_user.return_value = None

        # Act
        result = await self.check_password(test_email, test_password)

        # Assert
        self.mock_fetch_user.assert_called_once_with(test_email)
        self.mock_logger.debug.assert_any_call(
            f"Checking password for user {test_email}."
        )
        self.mock_logger.debug.assert_any_call("User found: None")
        self.mock_verify_password.assert_not_called()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_password_exception_handling(self):
        """Test handling of exceptions during password checking."""
        # Arrange
        test_email = "test@example.com"
        test_password = "password"

        # Create a mock user with a password
        mock_user = MagicMock()
        mock_user.password = "hashed_password"

        # Configure fetch_user to raise an exception
        self.mock_fetch_user.side_effect = Exception("Database error")

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            await self.check_password(test_email, test_password)

        # Verify the exception was raised and not caught
        assert "Database error" in str(exc_info.value)
        self.mock_verify_password.assert_not_called()
        self.mock_logger.debug.assert_called_with(
            f"Checking password for user {test_email}."
        )


# -------------------------------
# Test for _ensure_mongodb_connection
# -------------------------------
class TestEnsureMongoDBConnection:
    @classmethod
    def setup_class(cls):
        # Import _ensure_mongodb_connection once and store it as a class attribute.
        from depictio.api.v1.endpoints.user_endpoints.utils import (
            _ensure_mongodb_connection,
        )

        cls._ensure_mongodb_connection = staticmethod(_ensure_mongodb_connection)

    @patch("pymongo.MongoClient", new=mongomock.MongoClient)
    def setup_method(self, method):
        # Import the client (which is now a mongomock client) for use in tests.
        from depictio.api.v1.db import client

        self.db_client = client

    def test_dummy_connection(self):
        # Use the shared _ensure_mongodb_connection from setup_class.
        result = self._ensure_mongodb_connection()
        # Since mongomock's client.server_info() returns a dict, we expect the same output.
        assert result == self.db_client.server_info()

    @patch("time.sleep")
    def test_success_immediate_connection(self, mock_sleep):
        """
        Test that a successful connection on the first attempt logs the expected debug message and does not call sleep.
        """
        # mock_server_info = MagicMock(return_value={})

        # Replace the method with our mock
        self.db_client.server_info = MagicMock(return_value={})

        self._ensure_mongodb_connection()

        # Expect no delay since connection succeeded on the first try.
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_retries_before_success(self, mock_sleep):
        """
        Test that _ensure_mongodb_connection retries the connection when
        initial attempts fail.
        """
        # Configure the mock: first two calls raise exceptions, third returns success.
        self.db_client.server_info = MagicMock(
            side_effect=[
                Exception("Error 1"),
                Exception("Error 2"),
                {},
            ]
        )

        self._ensure_mongodb_connection(max_attempts=3, sleep_interval=5)

        # Verify that server_info was called three times.
        assert self.db_client.server_info.call_count == 3
        # Expect two sleep calls (between three attempts).
        mock_sleep.assert_has_calls([call(5), call(5)])

    @patch("time.sleep")
    def test_failure_after_max_attempts(self, mock_sleep):
        """
        Test that _ensure_mongodb_connection raises a RuntimeError after
        exhausting all connection attempts*.
        """
        # Configure the mock so that every attempt raises an exception.
        self.db_client.server_info = MagicMock(
            side_effect=Exception("Connection refused")
        )

        with pytest.raises(RuntimeError) as exc_info:
            self._ensure_mongodb_connection(max_attempts=3, sleep_interval=5)

        # Check that the error message contains both a general message and the underlying exception.
        assert "Could not connect to MongoDB" in str(exc_info.value)
        assert "Connection refused" in str(exc_info.value)
        # Verify three connection attempts.
        assert self.db_client.server_info.call_count == 3
        # Two sleep calls between three attempts.
        mock_sleep.assert_has_calls([call(5), call(5)])


# -------------------------------
# Test for create_group_helper
# -------------------------------


class TestCreateGroupHelper:
    @classmethod
    def setup_class(cls):
        # Import the function once and store it as a class attribute
        from depictio.api.v1.endpoints.user_endpoints.utils import create_group_helper

        cls.create_group_helper = staticmethod(create_group_helper)

    @patch("pymongo.MongoClient", new=mongomock.MongoClient)
    def setup_method(self, method):
        # Import the collections after mongomock patch is in effect
        from depictio.api.v1.db import groups_collection

        self.groups_collection = groups_collection

        # Set up the objectid conversion mock
        self.convert_objectid_patcher = patch(
            "depictio_models.models.base.convert_objectid_to_str",
            side_effect=lambda x: x,
        )
        self.mock_convert = self.convert_objectid_patcher.start()

    def teardown_method(self, method):
        # Clear the collection between tests
        if hasattr(self, "groups_collection"):
            self.groups_collection.delete_many({})

        # Stop all patches
        for patcher_attr in [
            "convert_objectid_patcher",
            "logger_patcher",
            "ensure_mongodb_patcher",
        ]:
            if hasattr(self, patcher_attr):
                getattr(self, patcher_attr).stop()

    def test_create_new_group_success(self):
        """Test creating a new group successfully."""
        # Create a test group
        # from depictio_models.models.users import Group
        test_group = Group(name="test_group")

        # Call the function
        result = self.create_group_helper(test_group)

        # Check that the group was inserted
        inserted_group = self.groups_collection.find_one({"name": "test_group"})
        assert inserted_group is not None

        # Check the result
        assert result["success"] is True
        assert result["message"] == "Group created successfully"
        assert result["group"] == test_group
        assert "inserted_id" in result

    def test_create_existing_group(self):
        """Test attempting to create a group that already exists."""
        # Insert a group first
        self.groups_collection.insert_one({"name": "existing_group"})

        # Create a test group with the same name
        # from depictio_models.models.users import Group
        test_group = Group(name="existing_group")

        # Call the function
        result = self.create_group_helper(test_group)

        # Check the result
        assert result["success"] is False
        assert result["message"] == "Group already exists"
        assert "group" in result

    def test_create_group_exception(self):
        """Test handling an exception during group creation."""
        # Create a test group
        test_group = Group(name="error_group")

        # Make insert_one raise an exception
        self.groups_collection.insert_one = MagicMock(
            side_effect=Exception("Test error")
        )

        # Call the function
        result = self.create_group_helper(test_group)

        # Check the result
        assert result["success"] is False
        assert "Error creating group" in result["message"]
        assert "Test error" in result["message"]
        assert result["group"] is None


# -------------------------------
# Test for delete_group_helper
# -------------------------------
class TestDeleteGroupHelper:
    @classmethod
    def setup_class(cls):
        # Import the function once and store it as a class attribute
        from depictio.api.v1.endpoints.user_endpoints.utils import delete_group_helper

        cls.delete_group_helper = staticmethod(delete_group_helper)

    @patch("pymongo.MongoClient", new=mongomock.MongoClient)
    def setup_method(self, method):
        # Import the collections after mongomock patch is in effect
        from depictio.api.v1.db import groups_collection

        self.groups_collection = groups_collection

        # Set up the objectid conversion mock
        self.convert_objectid_patcher = patch(
            "depictio_models.models.base.convert_objectid_to_str",
            side_effect=lambda x: x,
        )
        self.mock_convert = self.convert_objectid_patcher.start()

        # Common test data
        self.users_group_id = ObjectId("507f1f77bcf86cd799439011")
        self.admin_group_id = ObjectId("507f1f77bcf86cd799439012")
        self.test_group_id = ObjectId("507f1f77bcf86cd799439013")
        self.nonexistent_group_id = ObjectId("507f1f77bcf86cd799439099")

        # Insert protected groups into the mongomock collection
        self.groups_collection.insert_many(
            [
                {"_id": self.users_group_id, "name": "users"},
                {"_id": self.admin_group_id, "name": "admin"},
            ]
        )

    def teardown_method(self, method):
        # Clear the collection between tests
        if hasattr(self, "groups_collection"):
            self.groups_collection.delete_many({})

        # Stop the objectid conversion patch
        if hasattr(self, "convert_objectid_patcher"):
            self.convert_objectid_patcher.stop()

    def test_delete_regular_group(self):
        # Insert a test group
        self.groups_collection.insert_one(
            {"_id": self.test_group_id, "name": "test_group"}
        )

        # Call the function
        result = self.delete_group_helper(self.test_group_id)

        # Verify the function behavior
        assert self.groups_collection.find_one({"_id": self.test_group_id}) is None

        # Check the result
        assert result["success"] is True
        assert result["message"] == "Group deleted successfully"

    def test_delete_protected_group(self):
        # Try to delete a protected group
        result = self.delete_group_helper(self.admin_group_id)

        # Verify the group still exists
        assert self.groups_collection.find_one({"_id": self.admin_group_id}) is not None

        # Check the result
        assert result["success"] is False
        assert result["message"] == "Cannot delete group admin"

    def test_delete_nonexistent_group(self):
        # Call the function with a non-existent group ID
        result = self.delete_group_helper(self.nonexistent_group_id)

        # Check the result
        assert result["success"] is False
        assert result["message"] == "Group not found"



import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Import the function to test and related models
from depictio.api.v1.endpoints.user_endpoints.utils import add_token
from depictio_models.models.users import TokenBeanie, TokenData

class TestAddToken:
    def setup_method(self):
        # Set up patches
        self.create_access_token_patcher = patch('depictio.api.v1.endpoints.user_endpoints.utils.create_access_token', new_callable=AsyncMock)
        self.mock_create_access_token = self.create_access_token_patcher.start()
        
        # Mock the TokenBeanie class
        self.token_beanie_patcher = patch('depictio.api.v1.endpoints.user_endpoints.utils.TokenBeanie')
        self.mock_token_beanie_class = self.token_beanie_patcher.start()
        
        # Important: Add a class method 'save' to the TokenBeanie class mock
        self.mock_token_beanie_class.save = AsyncMock()
        
        # This will capture the argument passed to TokenBeanie constructor
        self.mock_token_beanie_class.side_effect = lambda **kwargs: MagicMock(spec=TokenBeanie, **kwargs)
        
        self.logger_patcher = patch('depictio.api.v1.endpoints.user_endpoints.utils.logger')
        self.mock_logger = self.logger_patcher.start()
        
        self.format_pydantic_patcher = patch('depictio.api.v1.endpoints.user_endpoints.utils.format_pydantic')
        self.mock_format_pydantic = self.format_pydantic_patcher.start()
        self.mock_format_pydantic.return_value = "formatted_output"
        
        # Test data
        from bson import ObjectId
        self.test_user_id = ObjectId("60d5ec9af682dcd2651257a1")
        self.test_token_name = "test_token"
        self.test_token_value = "jwt_token_12345"
        self.test_expire_datetime = datetime(2023, 12, 31, 23, 59, 59)
        
        # Create test token data
        self.token_data = TokenData(
            name=self.test_token_name,
            token_lifetime="short-lived",
            sub=self.test_user_id
        )
        
        # Configure mock return values
        self.mock_create_access_token.return_value = (self.test_token_value, self.test_expire_datetime)
        
        self.mock_token_instance = self.mock_token_beanie_class.return_value

    def teardown_method(self):
        # Stop all patches
        for patcher_attr in ['create_access_token_patcher', 'token_beanie_patcher', 
                           'logger_patcher', 'format_pydantic_patcher']:
            if hasattr(self, patcher_attr):
                getattr(self, patcher_attr).stop()
    
    @pytest.mark.asyncio
    async def test_add_token_success(self):
        """Test successful token creation and storage."""
        # Act
        result = await add_token(self.token_data)
        
        # Assert
        # Verify create_access_token was called with the right parameters
        self.mock_create_access_token.assert_called_once_with(self.token_data)
        
        # Capture the TokenBeanie instance that was created and saved
        # The constructor is called with the token data we expect
        self.mock_token_beanie_class.assert_called_once()
        created_token = self.mock_token_beanie_class.call_args[1]
        
        # Verify TokenBeanie.save was called with the new instance
        self.mock_token_beanie_class.save.assert_called_once()
        
        # Check that the token was created with the right parameters
        assert created_token['access_token'] == self.test_token_value
        assert created_token['expire_datetime'] == self.test_expire_datetime.strftime("%Y-%m-%d %H:%M:%S")
        assert created_token['name'] == self.test_token_name
        assert created_token['token_lifetime'] == "short-lived"
        assert created_token['user_id'] == self.test_user_id
        
        # Check that the function returned the token instance
        assert result is self.mock_token_beanie_class.save.call_args[0][0]        

    @pytest.mark.asyncio
    async def test_add_token_database_error(self):
        """Test handling of database errors during token saving."""
        # Arrange
        self.mock_token_beanie_class.save.side_effect = Exception("Database error")
        
        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            await add_token(self.token_data)
        
        # Verify the exception
        assert "Database error" in str(exc_info.value)
        
        # Verify create_access_token was still called
        self.mock_create_access_token.assert_called_once_with(self.token_data)
    
    @pytest.mark.asyncio
    async def test_add_token_token_generation_error(self):
        """Test handling of errors in token generation."""
        # Arrange
        self.mock_create_access_token.side_effect = Exception("Token generation error")
        
        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            await add_token(self.token_data)
        
        # Verify the exception
        assert "Token generation error" in str(exc_info.value)
        
        # Verify save was not called
        self.mock_token_instance.save.assert_not_called()