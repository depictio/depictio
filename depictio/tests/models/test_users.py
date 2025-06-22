from datetime import datetime, timedelta

import pytest
from beanie import PydanticObjectId, init_beanie
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from depictio.models.models.users import (  # UserBaseGroupLess,
    Group,
    GroupBeanie,
    Permission,
    RequestEditPassword,
    Token,
    TokenBase,
    TokenBeanie,
    TokenData,
    User,
    UserBase,
    UserBaseCLIConfig,
    UserBeanie,
)

# ---------------------------------
# Tests for TokenData
# ---------------------------------


class TestTokenData:
    def test_token_data_default_creation(self):
        """Test creating TokenData with default values."""
        sub = PydanticObjectId()
        token_data = TokenData(sub=sub)

        assert token_data.name is None
        assert token_data.token_lifetime == "short-lived"
        assert token_data.token_type == "bearer"
        assert str(token_data.sub) == str(sub)

    def test_token_data_custom_creation(self):
        """Test creating TokenData with custom values."""
        sub = PydanticObjectId()
        token_data = TokenData(
            name="Test User", token_lifetime="long-lived", token_type="custom", sub=sub
        )

        assert token_data.name == "Test User"
        assert token_data.token_lifetime == "long-lived"
        assert token_data.token_type == "custom"
        assert str(token_data.sub) == str(sub)

    def test_token_data_permanent(self):
        sub = PydanticObjectId()
        token_data = TokenData(sub=sub, token_lifetime="permanent")
        assert token_data.token_lifetime == "permanent"

    def test_token_data_invalid_lifetime(self):
        """Test validation of token lifetime."""
        sub = PydanticObjectId()
        with pytest.raises(ValidationError) as exc_info:
            TokenData(sub=sub, token_lifetime="invalid-lifetime")

        # Check that the error is related to pattern mismatch
        assert any(
            error.get("type") == "string_pattern_mismatch" for error in exc_info.value.errors()
        )

        # Optional: more detailed error checking
        error_messages = [error.get("msg") for error in exc_info.value.errors()]
        assert any("pattern" in msg for msg in error_messages)

    def test_token_data_invalid_type(self):
        """Test validation of token type."""
        sub = PydanticObjectId()
        with pytest.raises(ValidationError) as exc_info:
            TokenData(sub=sub, token_type="invalid-type")

        # Check that the error is related to pattern mismatch
        assert any(
            error.get("type") == "string_pattern_mismatch" for error in exc_info.value.errors()
        )

        # Optional: more detailed error checking
        error_messages = [error.get("msg") for error in exc_info.value.errors()]
        assert any("pattern" in msg for msg in error_messages)


# ---------------------------------
# Tests for Token
# ---------------------------------


class TestToken:
    def test_token_creation(self):
        """Test creating a complete Token instance."""
        sub = PydanticObjectId()
        future_time = datetime.now() + timedelta(hours=1)

        token = Token(access_token="ValidToken123", expire_datetime=future_time, sub=sub)

        assert token.access_token == "ValidToken123"
        assert token.expire_datetime == future_time
        assert str(token.sub) == str(sub)
        assert token.token_lifetime == "short-lived"
        assert token.token_type == "bearer"

    def test_token_invalid_expiration(self):
        """Test validation of token expiration."""
        sub = PydanticObjectId()

        # Past datetime
        past_time = datetime.now() - timedelta(hours=1)
        with pytest.raises(ValidationError, match="Expiration datetime must be in the future"):
            Token(access_token="ValidToken123", expire_datetime=past_time, sub=sub)

    def test_token_invalid_access_token(self):
        """Test validation of access token."""
        sub = PydanticObjectId()
        future_time = datetime.now() + timedelta(hours=1)

        # Token without mix of characters
        with pytest.raises(
            ValidationError,
            match="Access token must contain uppercase, lowercase, and numeric characters",
        ):
            Token(access_token="lowercase_only", expire_datetime=future_time, sub=sub)

        # Token too short
        with pytest.raises(ValidationError):
            Token(access_token="Short1", expire_datetime=future_time, sub=sub)

    def test_token_serialization(self):
        """Test serialization of Token model."""
        sub = PydanticObjectId()
        future_time = datetime.now() + timedelta(hours=1)

        token = Token(access_token="ValidToken123", expire_datetime=future_time, sub=sub)

        # Test JSON serialization
        token_dict = token.model_dump()
        assert isinstance(token_dict["sub"], str)
        assert isinstance(token_dict["expire_datetime"], str)

        # Verify ISO format for datetime
        assert token_dict["expire_datetime"] == future_time.isoformat()

    def test_token_permanent_lifetime(self):
        """Tokens with permanent lifetime should allow max datetime."""
        sub = PydanticObjectId()
        token = Token(
            access_token="ValidToken123A1",
            expire_datetime=datetime.max,
            sub=sub,
            token_lifetime="permanent",
        )
        assert token.token_lifetime == "permanent"
        assert token.expire_datetime == datetime.max


# ---------------------------------
# Tests for TokenBeanie
# ---------------------------------


@pytest.mark.asyncio
class TestTokenBeanie:
    async def test_token_beanie_creation(self):
        """Test creating and inserting a TokenBeanie document with refresh token support."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        user_id = PydanticObjectId()
        access_expire = datetime.now() + timedelta(hours=1)
        refresh_expire = datetime.now() + timedelta(days=7)

        # Create a token instance with refresh token fields
        token = TokenBeanie(
            user_id=user_id,
            access_token="test_access_token",
            expire_datetime=access_expire,
            name="test_token",
            refresh_token="test_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )

        # Insert the document
        await token.save()

        # Retrieve the document
        retrieved_token = await TokenBeanie.find_one(TokenBeanie.user_id == user_id)

        assert retrieved_token is not None
        assert retrieved_token.user_id == user_id
        assert retrieved_token.access_token == "test_access_token"
        assert retrieved_token.token_type == "bearer"
        assert retrieved_token.token_lifetime == "short-lived"
        assert retrieved_token.name == "test_token"

        # Check expire_datetime is approximately the same (allowing for millisecond differences)
        assert abs((retrieved_token.expire_datetime - access_expire).total_seconds()) < 1

        # Assert refresh token fields
        assert retrieved_token.refresh_token == "test_refresh_token"
        assert abs((retrieved_token.refresh_expire_datetime - refresh_expire).total_seconds()) < 1

    async def test_token_beanie_multiple_tokens(self):
        """Test creating and retrieving multiple tokens with refresh support."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        user_id1 = PydanticObjectId()
        user_id2 = PydanticObjectId()
        access_expire = datetime.now() + timedelta(hours=1)
        refresh_expire = datetime.now() + timedelta(days=7)

        # Create two tokens for different users with refresh tokens
        token1 = TokenBeanie(
            user_id=user_id1,
            access_token="token1_access_token",
            expire_datetime=access_expire,
            name="token1",
            refresh_token="token1_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )
        token2 = TokenBeanie(
            user_id=user_id2,
            access_token="token2_access_token",
            expire_datetime=access_expire,
            name="token2",
            refresh_token="token2_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )

        await token1.save()
        await token2.save()

        # Retrieve tokens using Beanie's query interface
        retrieved_tokens = await TokenBeanie.find(
            {"user_id": {"$in": [user_id1, user_id2]}}
        ).to_list()

        assert len(retrieved_tokens) == 2

        # Convert ObjectIds to strings for comparison
        retrieved_user_ids = [str(token.user_id) for token in retrieved_tokens]
        assert str(user_id1) in retrieved_user_ids
        assert str(user_id2) in retrieved_user_ids

        # Test filtering by user_id for a single user
        user1_tokens = await TokenBeanie.find({"user_id": user_id1}).to_list()
        assert len(user1_tokens) == 1
        assert str(user1_tokens[0].user_id) == str(user_id1)

        # Test querying by refresh token
        refresh_token_result = await TokenBeanie.find_one({"refresh_token": "token1_refresh_token"})
        assert refresh_token_result is not None
        assert str(refresh_token_result.user_id) == str(user_id1)

    async def test_token_to_response_dict(self):
        """Test the to_response_dict method with refresh token fields."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        user_id = PydanticObjectId()
        access_expire = datetime.now() + timedelta(hours=1)
        refresh_expire = datetime.now() + timedelta(days=7)

        token = TokenBeanie(
            user_id=user_id,
            access_token="test_access_token",
            expire_datetime=access_expire,
            name="test_token",
            refresh_token="test_refresh_token",
            refresh_expire_datetime=refresh_expire,
        )

        await token.save()

        # Get the response dict
        response_dict = token.model_dump()
        print(f"Response dict: {response_dict}")

        # Verify the current fields in the response dict
        assert "id" in response_dict
        assert "user_id" in response_dict
        assert "access_token" in response_dict
        assert "token_type" in response_dict
        assert "expire_datetime" in response_dict
        assert "created_at" in response_dict

        # Check current values
        assert response_dict["user_id"] == str(user_id)
        assert response_dict["access_token"] == "test_access_token"
        assert response_dict["token_type"] == "bearer"

        # Verify access token expiry timing
        print(f"Expire datetime: {response_dict['expire_datetime']}")
        expire_datetime = datetime.fromisoformat(response_dict["expire_datetime"])
        print(f"Expire datetime: {expire_datetime}")
        expire_in_secs = int((expire_datetime - datetime.now()).total_seconds())
        print(f"Expire in seconds: {expire_in_secs}")
        assert 3500 < expire_in_secs < 3600

        # Assert refresh token fields in response
        assert "refresh_token" in response_dict
        assert "refresh_expire_datetime" in response_dict
        assert response_dict["refresh_token"] == "test_refresh_token"

        # Verify refresh token expiry timing (should be much longer than access)
        refresh_expire_datetime = datetime.fromisoformat(response_dict["refresh_expire_datetime"])
        refresh_expire_in_secs = int((refresh_expire_datetime - datetime.now()).total_seconds())
        assert refresh_expire_in_secs > expire_in_secs  # Refresh should expire later
        assert refresh_expire_in_secs > 500000  # Should be more than ~6 days

    async def test_token_expiration(self):
        """Test querying tokens based on access and refresh token expiration."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[TokenBeanie])

        user_id = PydanticObjectId()
        current_time = datetime.now()

        # Create tokens with different expiration scenarios
        # 1. Both access and refresh expired
        both_expired_token = TokenBeanie(
            user_id=user_id,
            access_token="both_expired_token",
            expire_datetime=current_time - timedelta(hours=2),  # Expired
            name="both_expired",
            refresh_token="both_expired_refresh",
            refresh_expire_datetime=current_time - timedelta(hours=1),  # Also expired
        )

        # 2. Access expired but refresh valid
        access_expired_token = TokenBeanie(
            user_id=user_id,
            access_token="access_expired_token",
            expire_datetime=current_time - timedelta(hours=1),  # Expired
            name="access_expired",
            refresh_token="access_expired_refresh",
            refresh_expire_datetime=current_time + timedelta(days=6),  # Valid
        )

        # 3. Both access and refresh valid
        both_valid_token = TokenBeanie(
            user_id=user_id,
            access_token="both_valid_token",
            expire_datetime=current_time + timedelta(hours=1),  # Valid
            name="both_valid",
            refresh_token="both_valid_refresh",
            refresh_expire_datetime=current_time + timedelta(days=7),  # Valid
        )

        await both_expired_token.save()
        await access_expired_token.save()
        await both_valid_token.save()

        # Current tests: Find valid access tokens
        valid_access_tokens = await TokenBeanie.find(
            {"expire_datetime": {"$gt": current_time}}
        ).to_list()
        assert len(valid_access_tokens) == 1
        assert valid_access_tokens[0].access_token == "both_valid_token"

        # Current tests: Find expired access tokens
        expired_access_tokens = await TokenBeanie.find(
            {"expire_datetime": {"$lt": current_time}}
        ).to_list()
        assert len(expired_access_tokens) == 2
        expired_access_token_names = [token.access_token for token in expired_access_tokens]
        assert "both_expired_token" in expired_access_token_names
        assert "access_expired_token" in expired_access_token_names

        # Find valid refresh tokens
        valid_refresh_tokens = await TokenBeanie.find(
            {"refresh_expire_datetime": {"$gt": current_time}}
        ).to_list()
        assert (
            len(valid_refresh_tokens) == 2
        )  # access_expired and both_valid should have valid refresh

        # Find tokens where access expired but refresh valid (can refresh)
        refreshable_tokens = await TokenBeanie.find(
            {
                "expire_datetime": {"$lt": current_time},  # Access expired
                "refresh_expire_datetime": {"$gt": current_time},  # Refresh valid
            }
        ).to_list()
        assert len(refreshable_tokens) == 1
        assert refreshable_tokens[0].access_token == "access_expired_token"


# ---------------------
# Tests for TokenBase
# ---------------------


class TestTokenBase:
    def test_token_base_creation(self):
        """Test creating a complete TokenBase instance with refresh token support."""
        user_id = PydanticObjectId()
        access_expire = datetime.now() + timedelta(hours=1)
        refresh_expire = datetime.now() + timedelta(days=7)

        token_base = TokenBase(
            user_id=user_id,
            access_token="ValidToken123",
            expire_datetime=access_expire,
            name="Test Token",
            refresh_token="ValidRefreshToken456",
            refresh_expire_datetime=refresh_expire,
        )

        assert token_base.user_id == user_id
        assert token_base.access_token == "ValidToken123"
        assert token_base.expire_datetime == access_expire
        assert token_base.name == "Test Token"
        assert token_base.token_type == "bearer"
        assert token_base.token_lifetime == "short-lived"
        assert token_base.logged_in is False

        # Assert refresh token fields
        assert token_base.refresh_token == "ValidRefreshToken456"
        assert token_base.refresh_expire_datetime == refresh_expire

    def test_token_base_serializers(self):
        """Test serialization methods of TokenBase including refresh token fields."""
        user_id = PydanticObjectId()
        access_expire = datetime.now() + timedelta(hours=1)
        refresh_expire = datetime.now() + timedelta(days=7)
        creation_time = datetime.now()

        token_base = TokenBase(
            user_id=user_id,
            access_token="ValidToken123",
            expire_datetime=access_expire,
            created_at=creation_time,
            refresh_token="ValidRefreshToken456",
            refresh_expire_datetime=refresh_expire,
        )

        # Test current serializers
        if hasattr(token_base, "id"):
            assert isinstance(token_base.serialize_id(token_base.id), str)

        assert isinstance(token_base.serialize_user_id(user_id), str)
        assert token_base.serialize_expire_datetime(access_expire) == access_expire.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        assert token_base.serialize_created_at(creation_time) == creation_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # Test refresh token serializers
        assert hasattr(token_base, "serialize_refresh_expire_datetime")
        assert token_base.serialize_refresh_expire_datetime(
            refresh_expire
        ) == refresh_expire.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------
# Tests for Group
# ---------------------------------


class TestGroup:
    def test_group_creation(self):
        """Test creating a Group instance."""
        group = Group(name="Test Group")

        assert group.name == "Test Group"

    def test_group_serialization(self):
        """Test Group serialization."""
        group = Group(name="Test Group")
        group_dict = group.model_dump()

        assert group_dict["name"] == "Test Group"


# ---------------------------------
# Tests for UserBase
# ---------------------------------


class TestUserBase:
    def test_user_base_creation(self):
        """Test creating a UserBase instance."""
        # groups = [Group(name="Group 1"), Group(name="Group 2")]
        user = UserBase(email="test@example.com")
        # user = UserBase(email="test@example.com", groups=groups)

        assert user.email == "test@example.com"
        assert user.is_admin is False
        # assert len(user.groups) == 2
        # assert user.groups[0].name == "Group 1"
        # assert user.groups[1].name == "Group 2"

    def test_user_base_with_admin_flag(self):
        """Test creating UserBase with admin flag."""
        # groups = [Group(name="Admin Group")]
        user = UserBase(email="admin@example.com", is_admin=True)
        # user = UserBase(email="admin@example.com", is_admin=True, groups=groups)

        assert user.email == "admin@example.com"
        assert user.is_admin is True
        # assert len(user.groups) == 1
        # assert user.groups[0].name == "Admin Group"

    def test_user_base_empty_groups(self):
        """Test creating UserBase with empty groups list."""
        user = UserBase(email="test@example.com")
        # user = UserBase(email="test@example.com", groups=[])

        assert user.email == "test@example.com"
        # assert len(user.groups) == 0


# ---------------------------------
# Tests for User
# ---------------------------------


class TestUser:
    def test_user_creation(self):
        """Test creating a User instance."""
        # groups = [Group(name="Group 1")]
        user = User(
            email="test@example.com",
            # groups=groups,
            password="$2b$12$abcdefghijklmnopqrstuvwxyz",
            is_active=True,
            is_verified=False,
        )

        assert user.email == "test@example.com"
        assert user.is_admin is False
        # assert len(user.groups) == 1
        # assert user.groups[0].name == "Group 1"
        assert user.password == "$2b$12$abcdefghijklmnopqrstuvwxyz"
        assert user.is_active is True
        assert user.is_verified is False
        assert user.last_login is None
        assert user.registration_date is None

    def test_user_password_validation(self):
        """Test password validation in User."""
        # groups = [Group(name="Group 1")]

        # Test with already hashed password
        user = User(
            # email="test@example.com", groups=groups, password="$2b$12$abcdefghijklmnopqrstuvwxyz"
            email="test@example.com",
            password="$2b$12$abcdefghijklmnopqrstuvwxyz",
        )
        assert user.password == "$2b$12$abcdefghijklmnopqrstuvwxyz"

        # Test with unhashed password - should fail validation
        with pytest.raises(ValueError):
            # User(email="test@example.com", groups=groups, password="plaintext_password")
            User(email="test@example.com", password="plaintext_password")

    def test_turn_to_userbase(self):
        """Test turn_to_userbase method."""
        # groups = [Group(name="Group 1")]
        user = User(
            email="test@example.com",
            # groups=groups,
            password="$2b$12$abcdefghijklmnopqrstuvwxyz",
            is_admin=True,
        )

        userbase = user.turn_to_userbase()

        assert isinstance(userbase, UserBase)
        assert userbase.email == "test@example.com"
        assert userbase.is_admin is True
        # assert len(userbase.groups) == 1
        # assert userbase.groups[0].name == "Group 1"

    # def test_turn_to_userbasegroupless(self):
    #     """Test turn_to_userbasegroupless method."""
    #     groups = [Group(name="Group 1")]
    #     user = User(
    #         email="test@example.com",
    #         groups=groups,
    #         password="$2b$12$abcdefghijklmnopqrstuvwxyz",
    #         is_admin=True,
    #     )

    #     userbasegroupless = user.turn_to_userbasegroupless()

    #     assert isinstance(userbasegroupless, UserBaseGroupLess)
    #     assert userbasegroupless.email == "test@example.com"
    #     assert userbasegroupless.is_admin is True
    #     assert not hasattr(userbasegroupless, "groups")


# ---------------------------------
# Tests for UserBeanie
# ---------------------------------


@pytest.mark.asyncio
class TestUserBeanie:
    async def test_user_beanie_creation(self):
        """Test creating and inserting a UserBeanie document."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[UserBeanie])
        # await init_beanie(database=client.test_db, document_models=[UserBeanie, GroupBeanie])

        # Create a user instance
        user = UserBeanie(
            email="test@example.com",
            password="$2b$12$abcdefghijklmnopqrstuvwxyz",
        )

        # Insert the document
        await user.save()

        # Retrieve the document
        retrieved_user = await UserBeanie.find_one(UserBeanie.email == "test@example.com")

        assert retrieved_user is not None
        assert retrieved_user.email == "test@example.com"
        assert retrieved_user.is_admin is False
        # assert len(retrieved_user.groups) == 1
        # assert retrieved_user.groups[0].name == "Test Group"
        assert retrieved_user.password == "$2b$12$abcdefghijklmnopqrstuvwxyz"
        assert retrieved_user.is_active is True
        assert retrieved_user.is_verified is False

    async def test_user_beanie_multiple_users(self):
        """Test creating and retrieving multiple users."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[UserBeanie])

        # Create two users
        user1 = UserBeanie(
            email="user1@example.com",
            password="$2b$12$abcdefghijklmnopqrstuvwxyz",
        )
        user2 = UserBeanie(
            email="user2@example.com",
            password="$2b$12$abcdefghijklmnopqrstuvwxyz",
            is_admin=True,
        )

        await user1.save()
        await user2.save()

        # Retrieve users using Beanie's query interface
        all_users = await UserBeanie.find().to_list()
        print(all_users)

        assert len(all_users) == 2

        # Convert emails to a list for easier comparison
        emails = [user.email for user in all_users]
        assert "user1@example.com" in emails
        assert "user2@example.com" in emails

        # Test filtering by is_admin
        admin_users = await UserBeanie.find({"is_admin": True}).to_list()  # noqa: E712
        assert len(admin_users) == 1
        assert admin_users[0].email == "user2@example.com"

    async def test_user_beanie_conversion_methods(self):
        """Test the conversion methods from UserBeanie."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[UserBeanie])

        # Create a user instance
        user = UserBeanie(
            email="admin@example.com",
            password="$2b$12$abcdefghijklmnopqrstuvwxyz",
            is_admin=True,
        )

        # Insert the document
        await user.save()

        # Retrieve the document
        retrieved_user = await UserBeanie.find_one(UserBeanie.email == "admin@example.com")

        # Test turn_to_userbase method
        userbase = retrieved_user.turn_to_userbase()
        assert isinstance(userbase, UserBase)
        assert userbase.email == "admin@example.com"
        assert userbase.is_admin is True
        # assert len(userbase.groups) == 1
        # assert userbase.groups[0].name == "Admin Group"

        # # Test turn_to_userbasegroupless method
        # userbasegroupless = retrieved_user.turn_to_userbasegroupless()
        # assert isinstance(userbasegroupless, UserBaseGroupLess)
        # assert userbasegroupless.email == "admin@example.com"
        # assert userbasegroupless.is_admin is True
        # assert not hasattr(userbasegroupless, "groups")


# ---------------------
# Tests for GroupBeanie
# ---------------------


@pytest.mark.asyncio
class TestGroupBeanie:
    async def test_group_beanie_creation(self):
        """Test creating and inserting a GroupBeanie document."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[GroupBeanie])

        # Create a group instance
        group = GroupBeanie(name="Test Group")

        # Insert the document
        await group.save()

        # Retrieve the document
        retrieved_group = await GroupBeanie.find_one(GroupBeanie.name == "Test Group")

        assert retrieved_group is not None
        assert retrieved_group.name == "Test Group"

    async def test_group_beanie_multiple_groups(self):
        """Test creating and retrieving multiple groups."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[GroupBeanie])

        # Create multiple groups
        group1 = GroupBeanie(name="Group 1")
        group2 = GroupBeanie(name="Group 2")
        group3 = GroupBeanie(name="Group 3")

        await group1.save()
        await group2.save()
        await group3.save()

        # Retrieve all groups
        all_groups = await GroupBeanie.find().to_list()

        assert len(all_groups) == 3

        # Convert names to a list for easier comparison
        group_names = [group.name for group in all_groups]
        assert "Group 1" in group_names
        assert "Group 2" in group_names
        assert "Group 3" in group_names

        # Test filtering by name
        filtered_groups = await GroupBeanie.find(GroupBeanie.name == "Group 2").to_list()
        assert len(filtered_groups) == 1
        assert filtered_groups[0].name == "Group 2"

    async def test_group_beanie_update(self):
        """Test updating a GroupBeanie document."""
        # Initialize Beanie directly in the test
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[GroupBeanie])

        # Create a group
        group = GroupBeanie(name="Original Name")
        await group.save()

        # Retrieve and update the group
        retrieved_group = await GroupBeanie.find_one(GroupBeanie.name == "Original Name")
        retrieved_group.name = "Updated Name"
        await retrieved_group.save()

        # Check the update was successful
        updated_group = await GroupBeanie.find_one(GroupBeanie.name == "Updated Name")
        assert updated_group is not None
        assert updated_group.name == "Updated Name"

        # Ensure the old name doesn't exist
        old_group = await GroupBeanie.find_one(GroupBeanie.name == "Original Name")
        assert old_group is None


# ---------------------
# Tests for Permission
# ---------------------


class TestPermission:
    def test_permission_creation_empty(self):
        """Test creating a Permission with default empty lists."""
        permission = Permission()

        assert permission.owners == []
        assert permission.editors == []
        assert permission.viewers == []

        # Test dict method with empty lists
        perm_dict = permission.dict()
        assert perm_dict == {"owners": [], "editors": [], "viewers": []}

    def test_permission_with_users(self):
        """Test creating a Permission with valid users."""
        # Create users for testing
        user1 = UserBase(
            email="owner@example.com",
            is_admin=True,
        )
        user2 = UserBase(
            email="editor@example.com",
            is_admin=False,
        )
        user3 = UserBase(
            email="viewer@example.com",
            is_admin=False,
        )

        # Add ID attributes to simulate DB objects
        user1.id = "user1_id"
        user2.id = "user2_id"
        user3.id = "user3_id"

        permission = Permission(owners=[user1], editors=[user2], viewers=[user3])

        assert len(permission.owners) == 1
        assert permission.owners[0].email == "owner@example.com"
        assert len(permission.editors) == 1
        assert permission.editors[0].email == "editor@example.com"
        assert len(permission.viewers) == 1
        assert permission.viewers[0].email == "viewer@example.com"

    def test_permission_with_wildcard_viewer(self):
        """Test Permission with wildcard viewer."""
        # Create users for testing
        user1 = UserBase(
            email="owner@example.com",
            is_admin=True,
        )
        user1.id = "user1_id"

        permission = Permission(
            owners=[user1],
            viewers=["*"],  # Wildcard viewer
        )

        assert len(permission.owners) == 1
        assert len(permission.editors) == 0
        assert len(permission.viewers) == 1
        assert permission.viewers[0] == "*"

        # Test dict method with wildcard
        perm_dict = permission.dict()
        assert perm_dict["viewers"] == ["*"]

    def test_permission_from_dict(self):
        """Test creating a Permission from dictionaries."""
        owner = UserBase(
            **{
                "id": PydanticObjectId(),
                "email": "owner@example.com",
                "is_admin": True,
                # "groups": [{"name": "Admin"}],
            }
        )

        editor = UserBase(
            **{
                "id": PydanticObjectId(),
                "email": "editor@example.com",
                "is_admin": False,
                # "groups": [{"name": "Editor"}],
            }
        )

        permission = Permission(owners=[owner], editors=[editor], viewers=["*"])

        assert len(permission.owners) == 1
        assert isinstance(permission.owners[0], UserBase)
        assert permission.owners[0].email == "owner@example.com"

        assert len(permission.editors) == 1
        assert isinstance(permission.editors[0], UserBase)
        assert permission.editors[0].email == "editor@example.com"

    def test_permission_unique_validation(self):
        """Test validation that prevents users from being in multiple roles."""
        # Create users with the same ID to test validation
        user = UserBase(
            email="user@example.com",
            is_admin=True,
        )
        user.id = "same_id"

        # Test user in owners and editors
        with pytest.raises(ValidationError, match="A User cannot be both an owner and an editor"):
            Permission(owners=[user], editors=[user])

        # Test user in owners and viewers
        with pytest.raises(ValidationError, match="A User cannot be both an owner and a viewer"):
            Permission(owners=[user], viewers=[user])

        # Test user in editors and viewers
        with pytest.raises(ValidationError, match="A User cannot be both an editor and a viewer"):
            Permission(editors=[user], viewers=[user])

    def test_permission_invalid_types(self):
        """Test validation of invalid types in lists."""
        # Test invalid type in owners
        with pytest.raises(ValueError):
            Permission(owners=[123])

        # Test invalid type in editors
        with pytest.raises(ValueError):
            Permission(editors=["not_a_wildcard"])

        # Test non-list input
        with pytest.raises(ValueError, match="Expected a list"):
            Permission(owners="not_a_list")

    def test_permission_dict_method(self):
        """Test the dict method for correct serialization."""
        user1 = UserBase(
            email="owner@example.com",
            is_admin=True,
        )
        user2 = UserBase(
            email="editor@example.com",
            is_admin=False,
        )
        user1.id = "user1_id"
        user2.id = "user2_id"

        permission = Permission(owners=[user1], editors=[user2], viewers=["*"])

        perm_dict = permission.dict()

        assert "owners" in perm_dict
        assert "editors" in perm_dict
        assert "viewers" in perm_dict

        assert len(perm_dict["owners"]) == 1
        assert perm_dict["owners"][0]["email"] == "owner@example.com"

        assert len(perm_dict["editors"]) == 1
        assert perm_dict["editors"][0]["email"] == "editor@example.com"

        assert perm_dict["viewers"] == ["*"]

    def test_permission_with_existing_ids(self):
        """Test creating a Permission with existing user IDs."""
        user1_id = PydanticObjectId()
        user1 = UserBase(
            id=user1_id,
            email="user1@example.com",
            is_admin=True,
        )
        user2_id = PydanticObjectId()
        user2 = UserBase(
            id=user2_id,
            email="user2@example.com",
            is_admin=False,
        )

        permission = Permission(owners=[user1], editors=[user2], viewers=[])
        assert len(permission.owners) == 1
        assert len(permission.editors) == 1
        assert len(permission.viewers) == 0

        # Check that the IDs are correctly set
        assert permission.owners[0].id == user1_id
        assert permission.editors[0].id == user2_id
        assert permission.viewers == []
        # Test dict method with existing IDs
        perm_dict = permission.dict()
        assert perm_dict["owners"][0]["id"] == str(user1_id)
        assert perm_dict["editors"][0]["id"] == str(user2_id)


# ---------------------------------
# Tests for RequestEditPassword
# ---------------------------------


class TestRequestEditPassword:
    """Tests for the RequestEditPassword pydantic model."""

    def test_valid_password_inputs(self):
        """Test valid password input combinations."""
        # Valid scenario: old_password is hashed, new_password is plain
        valid_data = {
            "old_password": "$2b$12$validhashedpassword",
            "new_password": "newplainpassword123",
        }

        model = RequestEditPassword(**valid_data)
        assert model.old_password == "$2b$12$validhashedpassword"
        assert model.new_password == "newplainpassword123"

    def test_unhashed_old_password(self):
        """Test that unhashed old_password raises validation error."""
        invalid_data = {
            "old_password": "plainoldpassword",
            "new_password": "newpassword123",
        }

        with pytest.raises(ValidationError) as exc_info:
            RequestEditPassword(**invalid_data)

        # Check that the error message mentions hashing
        error_details = str(exc_info.value)
        assert "Password must be hashed" in error_details

    def test_hashed_new_password(self):
        """Test that hashed new_password raises validation error."""
        invalid_data = {
            "old_password": "$2b$12$validhashedpassword",
            "new_password": "$2b$12$anotheralreadyhashed",
        }

        with pytest.raises(ValidationError) as exc_info:
            RequestEditPassword(**invalid_data)

        # Check that the error message mentions already hashed
        error_details = str(exc_info.value)
        assert "Password is already hashed" in error_details

    def test_missing_fields(self):
        """Test that missing required fields raise validation errors."""
        # Missing old_password
        with pytest.raises(ValidationError):
            RequestEditPassword(new_password="newpassword123")

        # Missing new_password
        with pytest.raises(ValidationError):
            RequestEditPassword(old_password="$2b$12$validhashedpassword")

        # Empty dict (missing both)
        with pytest.raises(ValidationError):
            RequestEditPassword()


# ---------------------------------
# Tests for UserBaseCLIConfig
# ---------------------------------


class TestUserBaseCLIConfig:
    def test_user_base_cli_config_creation(self):
        """Test creating UserBaseCLIConfig with valid data."""
        user_id = PydanticObjectId()
        expire_time = datetime.now() + timedelta(hours=1)

        token = TokenBase(
            user_id=user_id,
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            expire_datetime=expire_time,
            refresh_expire_datetime=expire_time + timedelta(days=7),
        )

        user_config = UserBaseCLIConfig(email="test@example.com", token=token)

        assert user_config.email == "test@example.com"
        assert user_config.token.access_token == "test_access_token"
        assert user_config.token.user_id == user_id

    def test_user_base_cli_config_missing_token(self):
        """Test validation when token is missing."""
        with pytest.raises(ValidationError) as exc_info:
            UserBaseCLIConfig(
                email="test@example.com",
            )

        # Check that the error is related to missing field
        assert any(
            error.get("type") == "missing" and error.get("loc")[0] == "token"
            for error in exc_info.value.errors()
        )

    def test_user_base_cli_config_invalid_email(self):
        """Test validation of email format."""
        user_id = PydanticObjectId()
        expire_time = datetime.now() + timedelta(hours=1)

        token = TokenBase(
            user_id=user_id,
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            expire_datetime=expire_time,
            refresh_expire_datetime=expire_time + timedelta(days=7),
        )

        with pytest.raises(ValidationError) as exc_info:
            UserBaseCLIConfig(email="invalid-email", token=token)

        # Check that the error is related to email format
        assert any(
            error.get("type") == "value_error" and "email" in str(error.get("msg")).lower()
            for error in exc_info.value.errors()
        )
