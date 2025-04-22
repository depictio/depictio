from bson import ObjectId
import pytest
import bcrypt
from unittest.mock import patch, MagicMock, call
import mongomock

from depictio.api.v1.endpoints.user_endpoints.utils import (
    hash_password,
    verify_password,
)
from depictio.models.models.users import Group


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
            "depictio.api.v1.endpoints.user_endpoints.utils.async_fetch_user_from_email"
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
        # from depictio.models.models.users import Group
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
        # from depictio.models.models.users import Group
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


from depictio.api.v1.endpoints.user_endpoints.utils import (
    create_user_in_db,
)
from beanie import init_beanie
from depictio.models.models.users import UserBeanie, GroupBeanie
from unittest.mock import AsyncMock
from depictio.models.models.base import PyObjectId
from mongomock_motor import AsyncMongoMockClient
from fastapi import HTTPException
from unittest.mock import patch

# -------------------------------
# Test for create_user_in_db
# -------------------------------

@pytest.mark.asyncio
class TestCreateUserInDb:
    async def test_create_user_success(self):
        """Test successful user creation with valid data."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[UserBeanie])
        
        # Set up test data
        email = "test@example.com"
        password = "securepassword"
        
        # Mock the hash_password function
        with patch('depictio.api.v1.endpoints.user_endpoints.utils.hash_password') as mock_hash:
            mock_hash.return_value = "$2b$12$mockedhashedpassword"
            
            # Call the function
            payload = await create_user_in_db(email=email, password=password)
            result = payload["user"]    
            
            # Assertions
            assert result is not None
            assert result.email == email
            assert result.password == "$2b$12$mockedhashedpassword"
            assert result.is_admin is False
            assert result.is_active is True
            assert result.is_verified is False
            assert result.registration_date is not None
            assert result.last_login is not None
            
            # Verify hash_password was called with the correct password
            mock_hash.assert_called_once_with(password)
            
            # Verify user is saved to database
            db_user = await UserBeanie.find_one(UserBeanie.email == email)
            assert db_user is not None
            assert db_user.id == result.id

    async def test_create_admin_user(self):
        """Test creating an admin user."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[UserBeanie])
        
        # Set up test data
        email = "admin@example.com"
        password = "securepassword"
        
        # Mock the hash_password function
        with patch('depictio.api.v1.endpoints.user_endpoints.utils.hash_password') as mock_hash:
            mock_hash.return_value = "$2b$12$mockedhashedpassword"
            
            # Call the function with is_admin=True
            payload = await create_user_in_db(email=email, password=password, is_admin=True)
            result = payload["user"]
            
            # Assertions
            assert result is not None
            assert result.email == email
            assert result.is_admin is True
            
            # Verify user is saved to database
            db_user = await UserBeanie.find_one(UserBeanie.email == email)
            assert db_user is not None
            assert db_user.is_admin is True

    async def test_user_already_exists(self):
        """Test attempting to create a user that already exists."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[UserBeanie])
        
        # Set up test data
        email = "existing@example.com"
        password = "securepassword"
        
        # Create a user first
        with patch('depictio.api.v1.endpoints.user_endpoints.utils.hash_password') as mock_hash:
            mock_hash.return_value = "$2b$12$mockedhashedpassword"
            existing_user = await create_user_in_db(email=email, password=password)
            existing_user= existing_user["user"]
        
        # Now try to create the same user again
        with patch('depictio.api.v1.endpoints.user_endpoints.utils.hash_password') as mock_hash:
            mock_hash.return_value = "$2b$12$mockedhashedpassword"
            
            # Call the function and expect a response with success=False
            response = await create_user_in_db(email=email, password=password)
            
            # Verify the response details
            assert response["success"] is False
            assert response["message"] == "User already exists"
            # Instead of directly comparing objects, verify key attributes match
            response_user = response["user"]
            print(response_user)
            print(existing_user)
            assert response_user.id == existing_user.id
            assert response_user.email == existing_user.email
            assert response_user.password == existing_user.password

    # async def test_timestamp_format(self):
    #     """Test that timestamps are formatted correctly."""
    #     # Initialize Beanie directly in the test
    #     client = AsyncMongoMockClient()
    #     await init_beanie(database=client.test_db, document_models=[UserBeanie])
        
    #     # Set up test data
    #     email = "timestamp@example.com"
    #     password = "securepassword"
        
    #     # Mock the hash_password function
    #     with patch('depictio.api.v1.endpoints.user_endpoints.utils.hash_password') as mock_hash:
    #         mock_hash.return_value = "$2b$12$mockedhashedpassword"
            
    #         # Call the function
    #         result = await create_user_in_db(email=email, password=password)
            
    #         # Verify timestamp format (YYYY-MM-DD HH:MM:SS)
    #         import re
    #         timestamp_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
            
    #         assert isinstance(result.registration_date, str)
    #         assert isinstance(result.last_login, str)
    #         assert re.match(timestamp_pattern, result.registration_date)
    #         assert re.match(timestamp_pattern, result.last_login)

    # async def test_create_user_with_group(self):
    #     """Test creating a user with a specific group."""
    #     # Initialize Beanie directly in the test
    #     client = AsyncMongoMockClient()
    #     await init_beanie(database=client.test_db, document_models=[UserBeanie, GroupBeanie])
        
    #     # Set up test data
    #     email = "group@example.com"
    #     password = "securepassword"
    #     group_name = "TestGroup"
        
    #     # Create test group
    #     # Note: This functionality is commented out in the provided code,
    #     # but I'm including it for completeness
        
    #     # Mock the hash_password function
    #     with patch('depictio.api.v1.endpoints.user_endpoints.utils.hash_password') as mock_hash, \
    #          patch('depictio.api.v1.endpoints.user_endpoints.utils.get_users_group') as mock_group:
            
    #         mock_hash.return_value = "$2b$12$mockedhashedpassword"
    #         mock_group.return_value = Group(name=group_name)
            
    #         # Call the function with a group
    #         result = await create_user_in_db(
    #             email=email, 
    #             password=password, 
    #             group=group_name
    #         )
            
    #         # Assertions
    #         assert result is not None
    #         assert result.email == email
            
    #         # Note: Group functionality is commented out in the provided code
    #         # If uncommented, add appropriate assertions here