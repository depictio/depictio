from depictio.api.v1.endpoints.user_endpoints.core_functions import add_token_to_user
from unittest.mock import patch, MagicMock
from bson import ObjectId

def test_basic():
    assert True

class TestAddTokenToUser:
    def test_add_token_with_objectid(self):
        
        # Setup
        class MockUser:
            def __init__(self):
                self.id = ObjectId()
                
        user = MockUser()
        token = {"access_token": "test_token", "expire_datetime": "2030-01-01 00:00:00"}
        
        with patch("src.depictio.api.v1.endpoints.user_endpoints.core_functions.users_collection") as mock_users_collection:
            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_users_collection.update_one.return_value = mock_result
            
            # Execute
            result = add_token_to_user(user, token)
            
            # Assert
            mock_users_collection.update_one.assert_called_once_with(
                {"_id": user.id}, 
                {"$push": {"tokens": token}}
            )
            assert result == {"success": True}

    def test_add_token_with_string_id(self):
        
        # Setup
        class MockUser:
            def __init__(self, id_value):
                self.id = id_value
                
        user_id_str = str(ObjectId())
        user = MockUser(user_id_str)
        token = {"access_token": "test_token", "expire_datetime": "2030-01-01 00:00:00"}
        
        with patch("src.depictio.api.v1.endpoints.user_endpoints.core_functions.users_collection") as mock_users_collection:
            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_users_collection.update_one.return_value = mock_result
            
            # Execute
            result = add_token_to_user(user, token)
            
            # Assert
            mock_users_collection.update_one.assert_called_once()
            called_args = mock_users_collection.update_one.call_args[0]
            assert str(called_args[0]["_id"]) == user_id_str
            assert called_args[1] == {"$push": {"tokens": token}}
            assert result == {"success": True}

    def test_add_token_with_oid_dict(self):
        
        # Setup
        class MockUser:
            def __init__(self, id_value):
                self.id = id_value
                
        oid_str = str(ObjectId())
        user = MockUser({"$oid": oid_str})
        token = {"access_token": "test_token", "expire_datetime": "2030-01-01 00:00:00"}
        
        with patch("src.depictio.api.v1.endpoints.user_endpoints.core_functions.users_collection") as mock_users_collection:
            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_users_collection.update_one.return_value = mock_result
            
            # Execute
            result = add_token_to_user(user, token)
            
            # Assert
            mock_users_collection.update_one.assert_called_once()
            called_args = mock_users_collection.update_one.call_args[0]
            assert str(called_args[0]["_id"]) == oid_str
            assert called_args[1] == {"$push": {"tokens": token}}
            assert result == {"success": True}

    def test_add_token_no_modification(self):
        
        # Setup
        class MockUser:
            def __init__(self):
                self.id = ObjectId()
                
        user = MockUser()
        token = {"access_token": "test_token", "expire_datetime": "2030-01-01 00:00:00"}
        
        with patch("src.depictio.api.v1.endpoints.user_endpoints.core_functions.users_collection") as mock_users_collection:
            mock_result = MagicMock()
            mock_result.modified_count = 0  # No document modified
            mock_users_collection.update_one.return_value = mock_result
            
            # Execute
            result = add_token_to_user(user, token)
            
            # Assert
            mock_users_collection.update_one.assert_called_once_with(
                {"_id": user.id}, 
                {"$push": {"tokens": token}}
            )
            assert result == {"success": False}
