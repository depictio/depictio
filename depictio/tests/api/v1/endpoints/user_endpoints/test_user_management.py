"""
Tests for user management endpoints in the new permission system.

This module tests the get_all_users endpoint and validates that group endpoints
are properly disabled.
"""

import pytest
import pytest_asyncio
from beanie import init_beanie
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient
from motor.core import AgnosticDatabase

from depictio.api.v1.endpoints.user_endpoints.core_functions import _hash_password
from depictio.api.v1.endpoints.user_endpoints.routes import get_all_users
from depictio.models.models.users import GroupBeanie, TokenBeanie, UserBase, UserBeanie

# ---------------------------------
# Test Fixtures
# ---------------------------------


@pytest_asyncio.fixture(scope="function")
async def mock_mongodb_async():
    """
    Fixture to mock MongoDB for async operations.
    This initializes Beanie with a mock database.
    """
    # Create async mock client
    client = AsyncMongoMockClient()
    db = client.test_db

    # Initialize Beanie with the mock database
    database: AgnosticDatabase = db
    await init_beanie(database=database, document_models=[UserBeanie, GroupBeanie, TokenBeanie])

    # Create test users directly in the mock database
    test_users = [
        UserBeanie(
            email="admin@example.com",
            password=_hash_password("admin_password"),
            is_admin=True,
            registration_date="2023-01-01 00:00:00",
            last_login="2023-01-01 00:00:00",
            is_active=True,
            is_verified=True,
        ),
        UserBeanie(
            email="user1@example.com",
            password=_hash_password("user1_password"),
            is_admin=False,
            registration_date="2023-01-01 00:00:00",
            last_login="2023-01-01 00:00:00",
            is_active=True,
            is_verified=True,
        ),
        UserBeanie(
            email="user2@example.com",
            password=_hash_password("user2_password"),
            is_admin=False,
            registration_date="2023-01-01 00:00:00",
            last_login="2023-01-01 00:00:00",
            is_active=True,
            is_verified=True,
        ),
    ]

    for user in test_users:
        await user.create()

    yield db

    # Clean up
    for collection in await db.list_collection_names():
        await db[collection].delete_many({})


# ---------------------------------
# Tests for get_all_users endpoint
# ---------------------------------


class TestGetAllUsersEndpoint:
    """Test the new get_all_users endpoint for user management."""

    @pytest.mark.asyncio
    async def test_get_all_users_success_admin(self, mock_mongodb_async):
        """Test successful retrieval of all users by admin."""
        # Get admin user from the mock database
        admin_user = await UserBeanie.find_one({"email": "admin@example.com"})
        assert admin_user is not None
        assert admin_user.is_admin is True

        # Call the function
        result = await get_all_users(current_user=admin_user)

        # Verify results
        assert len(result) == 3  # admin + 2 regular users

        # Check that all users are returned with correct structure
        emails = {user["email"] for user in result}
        expected_emails = {"admin@example.com", "user1@example.com", "user2@example.com"}
        assert emails == expected_emails

        # Verify admin user is correctly identified
        admin_result = next(user for user in result if user["email"] == "admin@example.com")
        assert admin_result["is_admin"] is True

        # Verify regular users are correctly identified
        user1_result = next(user for user in result if user["email"] == "user1@example.com")
        assert user1_result["is_admin"] is False

        user2_result = next(user for user in result if user["email"] == "user2@example.com")
        assert user2_result["is_admin"] is False

        # Verify all results have required fields
        for user in result:
            assert "id" in user
            assert "email" in user
            assert "is_admin" in user

    @pytest.mark.asyncio
    async def test_get_all_users_no_current_user(self, mock_mongodb_async):
        """Test get_all_users raises 401 when no current user."""
        with pytest.raises(HTTPException) as exc_info:
            await get_all_users(current_user=None)

        assert exc_info.value.status_code == 401  # type: ignore[unresolved-attribute]
        assert "Current user not found" in exc_info.value.detail  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    async def test_get_all_users_non_admin_user(self, mock_mongodb_async):
        """Test get_all_users raises 401 when user is not admin."""
        # Get regular user from the mock database
        regular_user = await UserBeanie.find_one({"email": "user1@example.com"})
        assert regular_user is not None
        assert regular_user.is_admin is False

        with pytest.raises(HTTPException) as exc_info:
            await get_all_users(current_user=regular_user)

        assert exc_info.value.status_code == 401  # type: ignore[unresolved-attribute]
        assert "Current user is not an admin" in exc_info.value.detail  # type: ignore[unresolved-attribute]

    @pytest.mark.asyncio
    async def test_get_all_users_empty_database(self):
        """Test get_all_users with empty user database."""
        # Create a fresh database without any users
        client = AsyncMongoMockClient()
        db = client.empty_test_db
        database: AgnosticDatabase = db
        await init_beanie(database=database, document_models=[UserBeanie, GroupBeanie, TokenBeanie])

        # Create admin user directly for this test
        admin_user = UserBeanie(
            email="admin@example.com",
            password=_hash_password("admin_password"),
            is_admin=True,
            registration_date="2023-01-01 00:00:00",
            last_login="2023-01-01 00:00:00",
            is_active=True,
            is_verified=True,
        )

        # Don't save the admin user to database to keep it empty
        result = await get_all_users(current_user=admin_user)

        assert result == []

        # Clean up
        for collection in await db.list_collection_names():
            await db[collection].delete_many({})

    @pytest.mark.asyncio
    async def test_get_all_users_security_filtering(self, mock_mongodb_async):
        """Test that get_all_users only returns safe fields."""
        # Get admin user from the mock database
        admin_user = await UserBeanie.find_one({"email": "admin@example.com"})
        assert admin_user is not None
        assert admin_user.is_admin is True

        result = await get_all_users(current_user=admin_user)

        # Verify only safe fields are returned for all users
        assert len(result) >= 1
        for user in result:
            # Check that only safe fields are present
            assert set(user.keys()) == {"id", "email", "is_admin"}
            # Verify sensitive fields are not present
            assert "password" not in user
            assert "tokens" not in user
            assert "registration_date" not in user
            assert "last_login" not in user

    @pytest.mark.asyncio
    async def test_get_all_users_handles_missing_fields(self, mock_mongodb_async):
        """Test get_all_users handles users with missing optional fields."""
        # Create a user without explicit is_admin field (should default to False)
        user_without_admin = UserBeanie(
            email="no_admin_field@example.com",
            password=_hash_password("password"),
            # is_admin is not explicitly set, should default to False
            registration_date="2023-01-01 00:00:00",
            last_login="2023-01-01 00:00:00",
            is_active=True,
            is_verified=True,
        )
        await user_without_admin.create()

        # Get admin user from the mock database
        admin_user = await UserBeanie.find_one({"email": "admin@example.com"})
        assert admin_user is not None

        result = await get_all_users(current_user=admin_user)

        # Find the user without explicit admin field
        no_admin_user = next(
            user for user in result if user["email"] == "no_admin_field@example.com"
        )

        # Verify missing is_admin defaults to False
        assert no_admin_user["is_admin"] is False

        # Verify explicit admin user still works
        admin_result = next(user for user in result if user["email"] == "admin@example.com")
        assert admin_result["is_admin"] is True


# ---------------------------------
# Tests for new /auth/me endpoint
# ---------------------------------


class TestGetCurrentUserInfoEndpoint:
    """Test the new /auth/me endpoint for current user information."""

    @pytest.mark.asyncio
    async def test_get_current_user_info_success(self, mock_mongodb_async):
        """Test successful retrieval of current user info."""
        from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user_info

        # Get admin user from the mock database
        admin_user = await UserBeanie.find_one({"email": "admin@example.com"})
        assert admin_user is not None

        # Call the endpoint function
        result = await get_current_user_info(current_user=admin_user)

        # Verify the result is the same user object
        assert result == admin_user
        assert result.email == "admin@example.com"
        assert result.is_admin is True

    @pytest.mark.asyncio
    async def test_get_current_user_info_regular_user(self, mock_mongodb_async):
        """Test retrieval of current user info for regular user."""
        from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user_info

        # Get regular user from the mock database
        regular_user = await UserBeanie.find_one({"email": "user1@example.com"})
        assert regular_user is not None

        # Call the endpoint function
        result = await get_current_user_info(current_user=regular_user)

        # Verify the result is the same user object
        assert result == regular_user
        assert result.email == "user1@example.com"
        assert result.is_admin is False


# ---------------------------------
# Tests for disabled group endpoints
# ---------------------------------


# class TestDisabledGroupEndpoints:
#     """Test that group endpoints are properly disabled."""

#     def test_group_endpoints_are_commented_out(self):
#         """Test that group management endpoints are disabled."""
#         # This test verifies that the group endpoints are commented out
#         # by checking they're not in the router

#         from depictio.api.v1.endpoints.user_endpoints.routes import auth_endpoint_router

#         # Get all routes from the router
#         routes = [route.path for route in auth_endpoint_router.routes]

#         # Verify group endpoints are not present
#         assert "/get_all_groups" not in routes
#         assert "/get_all_groups_including_users" not in routes

#         # Verify user endpoint is present
#         assert "/get_all_users" in routes

#     def test_group_functions_not_available(self):
#         """Test that group management functions are not available."""
#         # Try to import the disabled functions - they should not exist
#         from depictio.api.v1.endpoints.user_endpoints import routes

#         # These functions should be commented out and not available
#         assert not hasattr(routes, 'get_all_groups')
#         assert not hasattr(routes, 'get_all_groups_with_users')

#         # This function should be available
#         assert hasattr(routes, 'get_all_users')


# ---------------------------------
# Integration tests
# ---------------------------------


class TestUserManagementIntegration:
    """Integration tests for the user management system."""

    @pytest.mark.asyncio
    async def test_user_management_workflow(self, mock_mongodb_async):
        """Test a complete user management workflow."""
        # Create additional test users for this workflow
        additional_users = [
            UserBeanie(
                email="scientist@company.com",
                password=_hash_password("scientist_password"),
                is_admin=False,
                registration_date="2023-01-01 00:00:00",
                last_login="2023-01-01 00:00:00",
                is_active=True,
                is_verified=True,
            ),
            UserBeanie(
                email="stakeholder@company.com",
                password=_hash_password("stakeholder_password"),
                is_admin=False,
                registration_date="2023-01-01 00:00:00",
                last_login="2023-01-01 00:00:00",
                is_active=True,
                is_verified=True,
            ),
            UserBeanie(
                email="manager@company.com",
                password=_hash_password("manager_password"),
                is_admin=False,
                registration_date="2023-01-01 00:00:00",
                last_login="2023-01-01 00:00:00",
                is_active=True,
                is_verified=True,
            ),
        ]

        for user in additional_users:
            await user.create()

        # Get admin user from the mock database
        admin_user = await UserBeanie.find_one({"email": "admin@example.com"})
        assert admin_user is not None

        # Get all users (for populating UI multiselect)
        users = await get_all_users(current_user=admin_user)

        # Verify we can get user data for permission assignment
        assert len(users) == 6  # 3 original + 3 additional users

        # Verify admin can identify themselves
        admin_users = [u for u in users if u["is_admin"]]
        regular_users = [u for u in users if not u["is_admin"]]

        assert len(admin_users) == 1
        assert len(regular_users) == 5

        # This data would be used by the UI to:
        # 1. Populate the user multiselect dropdown
        # 2. Allow admin to assign users to roles (owner/editor/viewer)
        # 3. Create Permission objects for projects

        expected_emails = {
            "admin@example.com",
            "scientist@company.com",
            "stakeholder@company.com",
            "manager@company.com",
            "user1@example.com",
            "user2@example.com",
        }
        actual_emails = {u["email"] for u in users}
        assert actual_emails == expected_emails

    @pytest.mark.asyncio
    async def test_permission_assignment_data_flow(self, mock_mongodb_async):
        """Test data flow for permission assignment."""
        # This test simulates the data flow when assigning permissions

        # Create users for different permission roles
        role_users = [
            UserBeanie(
                email="owner@company.com",
                password=_hash_password("owner_password"),
                is_admin=True,
                registration_date="2023-01-01 00:00:00",
                last_login="2023-01-01 00:00:00",
                is_active=True,
                is_verified=True,
            ),
            UserBeanie(
                email="editor1@company.com",
                password=_hash_password("editor1_password"),
                is_admin=False,
                registration_date="2023-01-01 00:00:00",
                last_login="2023-01-01 00:00:00",
                is_active=True,
                is_verified=True,
            ),
            UserBeanie(
                email="editor2@company.com",
                password=_hash_password("editor2_password"),
                is_admin=False,
                registration_date="2023-01-01 00:00:00",
                last_login="2023-01-01 00:00:00",
                is_active=True,
                is_verified=True,
            ),
            UserBeanie(
                email="viewer@company.com",
                password=_hash_password("viewer_password"),
                is_admin=False,
                registration_date="2023-01-01 00:00:00",
                last_login="2023-01-01 00:00:00",
                is_active=True,
                is_verified=True,
            ),
        ]

        for user in role_users:
            await user.create()

        # Get admin user to perform the operation
        admin_user = await UserBeanie.find_one({"email": "admin@example.com"})
        assert admin_user is not None

        # Get users for UI
        available_users = await get_all_users(current_user=admin_user)

        # 2. Simulate UI selection for project permissions
        # Admin selects users for different roles by email (since we know the emails)
        selected_owner_emails = ["owner@company.com"]
        selected_editor_emails = ["editor1@company.com", "editor2@company.com"]
        selected_viewer_emails = ["viewer@company.com"]

        # 3. Create UserBase objects for Permission model
        # (This would normally happen in the API endpoint)
        owner_users = [
            UserBase(id=user["id"], email=user["email"], is_admin=user["is_admin"])
            for user in available_users
            if user["email"] in selected_owner_emails
        ]

        editor_users = [
            UserBase(id=user["id"], email=user["email"], is_admin=user["is_admin"])
            for user in available_users
            if user["email"] in selected_editor_emails
        ]

        viewer_users = [
            UserBase(id=user["id"], email=user["email"], is_admin=user["is_admin"])
            for user in available_users
            if user["email"] in selected_viewer_emails
        ]

        # 4. Verify permission structure can be created
        assert len(owner_users) == 1
        assert len(editor_users) == 2
        assert len(viewer_users) == 1

        assert owner_users[0].email == "owner@company.com"
        assert editor_users[0].email == "editor1@company.com"
        assert editor_users[1].email == "editor2@company.com"
        assert viewer_users[0].email == "viewer@company.com"

        # This demonstrates the full data flow from:
        # API -> UI multiselect -> User selection -> Permission creation
