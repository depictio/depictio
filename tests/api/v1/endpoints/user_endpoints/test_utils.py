import pytest
import jwt
import bcrypt
import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, Mock
from bson import ObjectId
# from depictio_models.models.users import Token, User, Group, UserBaseGroupLess

from depictio.api.v1.endpoints.user_endpoints.utils import (
    login_user, logout_user, 
    # is_user_logged_in, hash_password, verify_password,
    # find_user, create_access_token, check_token_validity, check_password,
    # add_token, delete_token, list_existing_tokens, purge_expired_tokens,
    # get_users_group, get_groups, add_user, edit_password, fetch_user_from_token,
    # generate_agent_config, create_group_helper, delete_group_helper,
    # update_group_in_users_helper, api_create_group, api_update_group_in_users
)

# Session related tests
def test_login_user():
    result = login_user("test@example.com")
    assert result == {"logged_in": True, "email": "test@example.com"}

def test_logout_user():
    result = logout_user()
    assert result == {"logged_in": False, "access_token": None}

# def test_is_user_logged_in():
#     # Test when user is logged in
#     session_data = {"logged_in": True}
#     assert is_user_logged_in(session_data) is True
    
#     # Test when user is not logged in
#     session_data = {"logged_in": False}
#     assert is_user_logged_in(session_data) is False
    
#     # Test with empty session data
#     session_data = {}
#     assert is_user_logged_in(session_data) is False

# # Password related tests
# def test_hash_password():
#     password = "test_password"
#     hashed = hash_password(password)
#     assert isinstance(hashed, str)
#     assert hashed != password
#     # Verify bcrypt format
#     assert hashed.startswith("$2b$")

# def test_verify_password():
#     password = "test_password"
#     hashed = hash_password(password)
#     assert verify_password(hashed, password) is True
#     assert verify_password(hashed, "wrong_password") is False

# # User related tests
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.fetch_user_from_email")
# def test_find_user(mock_fetch):
#     # Setup mock
#     mock_user = MagicMock()
#     mock_fetch.return_value = mock_user
    
#     # Test with existing user
#     result = find_user("test@example.com")
#     mock_fetch.assert_called_once_with("test@example.com", False)
#     assert result == mock_user
    
#     # Test with non-existing user
#     mock_fetch.reset_mock()
#     mock_fetch.return_value = None
#     result = find_user("nonexistent@example.com")
#     assert result is None

# @patch("depictio.api.v1.endpoints.user_endpoints.utils.check_password")
# def test_check_password(mock_verify):
#     # Setup cases
#     mock_verify.side_effect = [True, False]
    
#     # Test successful verification
#     assert check_password("user@example.com", "correct_password") is True
    
#     # Test failed verification
#     assert check_password("user@example.com", "wrong_password") is False

# # Token related tests
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.PRIVATE_KEY", "test_key")
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.ALGORITHM", "HS256")
# def test_create_access_token():
#     # Test short-lived token
#     token_data = {"sub": "user@example.com", "token_lifetime": "short-lived", "name": "test-token"}
#     token, expire = create_access_token(token_data)
#     assert isinstance(token, str)
#     assert isinstance(expire, datetime)
#     assert (expire - datetime.now()).total_seconds() > 11 * 60 * 60  # Almost 12 hours
    
#     # Test long-lived token
#     token_data = {"sub": "user@example.com", "token_lifetime": "long-lived", "name": "test-token"}
#     token, expire = create_access_token(token_data)
#     assert (expire - datetime.now()).total_seconds() > 364 * 24 * 60 * 60  # Almost 365 days
    
#     # Test invalid token type
#     token_data = {"sub": "user@example.com", "token_lifetime": "invalid-type", "name": "test-token"}
#     with pytest.raises(ValueError):
#         create_access_token(token_data)

# @patch("depictio.api.v1.endpoints.user_endpoints.utils.httpx.post")
# def test_check_token_validity(mock_post):
#     # Setup mock response
#     mock_response = MagicMock()
#     mock_post.return_value = mock_response
    
#     # Test valid token
#     mock_response.status_code = 200
#     assert check_token_validity("valid_token") is True
    
#     # Test invalid token
#     mock_response.status_code = 401
#     assert check_token_validity("invalid_token") is False

# @patch("depictio.api.v1.endpoints.user_endpoints.utils.find_user")
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.create_access_token")
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.list_existing_tokens")
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.add_token_to_user")
# def test_add_token(mock_add_token_to_user, mock_list_tokens, mock_create_token, mock_find_user):
#     # Setup mocks
#     mock_user = MagicMock()
#     mock_find_user.return_value = mock_user
#     mock_create_token.return_value = ("test_token", datetime.now() + timedelta(hours=12))
#     mock_list_tokens.return_value = []
#     mock_add_token_to_user.return_value = {"success": True}
    
#     # Test adding a token
#     token_data = {
#         "sub": "user@example.com",
#         "name": "test-token",
#         "token_lifetime": "short-lived"
#     }
#     result = add_token(token_data)
#     assert isinstance(result, Token)
#     assert result.name == "test-token"
    
#     # Test duplicate token name
#     mock_list_tokens.return_value = [{"name": "test-token"}]
#     result = add_token(token_data)
#     assert result is None

# # API integration tests
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.httpx.get")
# def test_get_groups(mock_get):
#     # Setup mock response
#     mock_response = MagicMock()
#     mock_get.return_value = mock_response
    
#     # Test successful response
#     mock_response.status_code = 200
#     mock_response.json.return_value = [{"name": "group1"}, {"name": "group2"}]
#     result = get_groups("test_token")
#     assert result == [{"name": "group1"}, {"name": "group2"}]
    
#     # Test failed response
#     mock_response.status_code = 401
#     result = get_groups("test_token")
#     assert result == []

# @patch("depictio.api.v1.endpoints.user_endpoints.utils.httpx.get")
# def test_get_users_group(mock_get):
#     # Setup mock response
#     mock_response = MagicMock()
#     mock_get.return_value = mock_response
    
#     # Test successful response
#     mock_response.status_code = 200
#     mock_response.json.return_value = {"name": "users", "_id": "123"}
#     result = get_users_group()
#     assert isinstance(result, Group)
    
#     # Test failed response
#     mock_response.status_code = 401
#     result = get_users_group()
#     assert result == []

# @patch("depictio.api.v1.endpoints.user_endpoints.utils.httpx.post")
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.get_users_group")
# @patch("depictio.api.v1.endpoints.user_endpoints.utils.hash_password")
# def test_add_user(mock_hash, mock_get_group, mock_post):
#     # Setup mocks
#     mock_hash.return_value = "hashed_password"
#     mock_group = Group(id=ObjectId(), name="users")
#     mock_get_group.return_value = mock_group
#     mock_response = MagicMock()
#     mock_post.return_value = mock_response
    
#     # Test successful user addition
#     mock_response.status_code = 200
#     result = add_user("test@example.com", "password")
#     assert result == mock_response

# @patch("depictio.api.v1.db.groups_collection.find_one")
# @patch("depictio.api.v1.db.groups_collection.insert_one")
# def test_create_group_helper(mock_insert, mock_find_one):
#     # Test when group already exists
#     mock_find_one.return_value = {"_id": ObjectId(), "name": "test_group"}
#     group_dict = {"name": "test_group"}
#     result = create_group_helper(group_dict)
#     assert result["name"] == "test_group"
#     mock_insert.assert_not_called()
    
#     # Test when group does not exist
#     mock_find_one.return_value = None
#     result = create_group_helper(group_dict)
#     mock_insert.assert_called_once()

# @patch("depictio.api.v1.db.groups_collection.find")
# @patch("depictio.api.v1.db.groups_collection.delete_one")
# def test_delete_group_helper(mock_delete, mock_find):
#     # Setup protected groups
#     mock_find.return_value = [
#         {"_id": "1", "name": "users"}, 
#         {"_id": "2", "name": "admin"}
#     ]
    
#     # Test deleting protected group
#     result = delete_group_helper("1")
#     assert result["success"] is False
    
#     # Test deleting non-protected group
#     mock_delete.return_value.deleted_count = 1
#     result = delete_group_helper("3")
#     assert result["success"] is True