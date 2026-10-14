from datetime import datetime
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, EmailStr, Field, field_serializer, field_validator, model_validator
from pymongo import IndexModel

# from depictio.models.models.s3 import S3DepictioCLIConfig
from depictio.models.models.base import MongoModel, PyObjectId


class TokenData(BaseModel):
    name: str | None = None
    token_lifetime: str = Field(
        default="short-lived",
        description="Lifetime of the token",
        pattern="^(short-lived|long-lived|permanent)$",
    )
    token_type: str = Field(
        default="bearer",
        description="Type of authentication token",
        pattern="^(bearer|custom)$",
    )
    sub: PyObjectId = Field(
        default=PyObjectId(),
        description="Subject of the token, typically the user ID",
    )

    @field_serializer("sub")
    def serialize_sub(sub: PydanticObjectId) -> str:
        return str(sub)

    @field_validator("token_lifetime")
    @classmethod
    def validate_token_lifetime(cls, v: str) -> str:
        """
        Validate token lifetime value.
        """
        allowed_lifetimes = ["short-lived", "long-lived", "permanent"]
        if v not in allowed_lifetimes:
            raise ValueError(f"Token lifetime must be one of {allowed_lifetimes}")
        return v

    @field_validator("token_type")
    @classmethod
    def validate_token_type(cls, v: str) -> str:
        """
        Validate token type value.
        """
        allowed_types = ["bearer", "custom"]
        if v not in allowed_types:
            raise ValueError(f"Token type must be one of {allowed_types}")
        return v


class Token(TokenData):
    access_token: str = Field(
        description="Authentication access token",
        min_length=10,  # Minimum token length
        max_length=512,  # Maximum reasonable token length
    )
    expire_datetime: datetime = Field(description="Token expiration timestamp")

    @field_serializer("expire_datetime")
    def serialize_datetime(self, dt: datetime) -> str:
        """
        Serialize datetime to ISO format string.
        """
        return dt.isoformat()

    @field_validator("expire_datetime")
    @classmethod
    def validate_expiration(cls, v: datetime) -> datetime:
        """
        Validate that expiration datetime is in the future.
        """
        if v != datetime.max and v <= datetime.now():
            raise ValueError("Expiration datetime must be in the future")
        return v

    @field_validator("access_token")
    @classmethod
    def validate_access_token(cls, v: str) -> str:
        """
        Additional validation for access token.
        """
        # Example validation: ensure token contains a mix of characters
        if not (
            any(c.isupper() for c in v)
            and any(c.islower() for c in v)
            and any(c.isdigit() for c in v)
        ):
            raise ValueError(
                "Access token must contain uppercase, lowercase, and numeric characters"
            )
        return v


class TokenBase(MongoModel):
    # id: PydanticObjectId = Field(default_factory=PydanticObjectId, alias="_id")
    user_id: PydanticObjectId  # Reference to User's ObjectId
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    token_lifetime: str = "short-lived"
    expire_datetime: datetime
    refresh_expire_datetime: datetime
    name: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    model_config = {"arbitrary_types_allowed": True}
    logged_in: bool = False

    # Field serializers for Pydantic v2
    @field_serializer("id")
    def serialize_id(self, id: PyObjectId) -> str:
        return str(id)

    @field_serializer("user_id")
    def serialize_user_id(self, user_id: PydanticObjectId) -> str:
        return str(user_id)

    @field_serializer("expire_datetime")
    def serialize_expire_datetime(self, expire_datetime: datetime) -> str:
        return expire_datetime.strftime("%Y-%m-%d %H:%M:%S")

    @field_serializer("refresh_expire_datetime")
    def serialize_refresh_expire_datetime(self, refresh_expire_datetime: datetime) -> str:
        return refresh_expire_datetime.strftime("%Y-%m-%d %H:%M:%S")

    @field_serializer("created_at")
    def serialize_created_at(self, created_at: datetime) -> str:
        return created_at.strftime("%Y-%m-%d %H:%M:%S")

    # For consistent responses in the API
    # def to_response_dict(self):

    # return {
    #     "id": self.id,
    #     "user_id": self.user_id,
    #     "access_token": self.access_token,
    #     "token_type": self.token_type,
    #     # "expires_in": int((self.expire_datetime - datetime.now()).total_seconds()),
    #     # "expires_at": self.expire_datetime,
    #     "created_at": self.created_at,
    # }


class TokenBeanie(TokenBase, Document):
    class Settings:
        name = "tokens"  # Collection name


class MagicLinkTicket(MongoModel):
    """A short-lived, single-use ticket that logs a user in without a password.

    The opaque ``ticket`` secret travels in the login URL; everything else
    (the real session) is minted server-side when the ticket is redeemed. The
    ticket is invalidated on first use (``used=True``) and ignored past
    ``expire_datetime``.
    """

    ticket: str  # opaque random secret carried in the magic-link URL
    user_id: PydanticObjectId
    expire_datetime: datetime
    used: bool = False
    created_at: datetime = Field(default_factory=datetime.now)

    @field_serializer("user_id")
    def serialize_user_id(self, user_id: PydanticObjectId) -> str:
        return str(user_id)


class MagicLinkTicketBeanie(MagicLinkTicket, Document):
    class Settings:
        name = "magic_link_tickets"  # Collection name
        indexes = [
            # Ticket secrets are looked up directly and must be unique.
            IndexModel([("ticket", 1)], unique=True),
            # TTL index: MongoDB auto-deletes a ticket once it passes
            # ``expire_datetime`` (used or not), so consumed/expired tickets
            # never accumulate — no cleanup job needed.
            IndexModel([("expire_datetime", 1)], expireAfterSeconds=0),
        ]


class Group(MongoModel):
    name: str
    users_ids: list[PyObjectId] = Field(default_factory=list)
    admin_ids: list[PyObjectId] = Field(default_factory=list)
    pi_id: PyObjectId | None = None
    # Email of a P.I. designated before that person has a Depictio account.
    # Claimed on their first login in any auth mode (password registration,
    # OAuth, SAML) — see api/v1/endpoints/groups_endpoints/pending_pi.py.
    pending_pi_email: EmailStr | None = None
    sso_managed: bool = False

    @field_validator("pending_pi_email", mode="before")
    @classmethod
    def _normalize_pending_pi_email(cls, value: Any) -> Any:
        """Store the parked email casefolded so the claim lookup is a plain
        equality match; blank strings mean "no pending P.I."."""
        if isinstance(value, str):
            return value.strip().lower() or None
        return value

    @field_serializer("admin_ids")
    def serialize_admin_ids(self, admin_ids: list[PyObjectId]) -> list[str]:
        return [str(admin_id) for admin_id in admin_ids]

    @field_serializer("pi_id")
    def serialize_pi_id(self, pi_id: PyObjectId | None) -> str | None:
        return str(pi_id) if pi_id is not None else None

    @model_validator(mode="after")
    def _admins_and_pi_are_members(self):
        """Group admins and the P.I. are always members: auto-add rather than
        reject, so callers (db_init seeding, SSO sync, promote endpoints) can
        pass admins without pre-listing them in users_ids."""
        member_ids = {str(user_id) for user_id in self.users_ids}
        for admin_id in self.admin_ids:
            if str(admin_id) not in member_ids:
                self.users_ids.append(admin_id)
                member_ids.add(str(admin_id))
        if self.pi_id is not None and str(self.pi_id) not in member_ids:
            self.users_ids.append(self.pi_id)
        # A resolved P.I. always wins over a parked designation.
        if self.pi_id is not None:
            self.pending_pi_email = None
        return self


class GroupBase(MongoModel):
    """Denormalized group snapshot embedded in Permission documents.

    Mirrors UserBase's role: only identity fields (id, name) are stored inside
    permissions.group_* arrays; membership is always resolved live from the
    groups collection."""

    name: str


class UserBase(MongoModel):
    email: EmailStr
    is_admin: bool = False
    is_anonymous: bool = False
    is_temporary: bool = False
    expiration_time: datetime | None = None


class UserContext:
    """
    User context helper class for consolidated API cache system.

    This class provides compatibility with existing UserBase/User classes
    while optimizing API calls through caching.
    """

    def __init__(self, id: str, email: str, is_admin: bool, is_anonymous: bool):
        self.id = PyObjectId(id) if isinstance(id, str) else id
        self.email = email
        self.is_admin = is_admin
        self.is_anonymous = is_anonymous
        self.is_temporary = False  # Default for cached users
        self.expiration_time = None  # Default for cached users

    @property
    def name(self) -> str:
        """Get user display name from email."""
        return self.email.split("@")[0] if self.email else "Unknown"

    def turn_to_userbase(self) -> UserBase:
        """Convert to UserBase for compatibility with existing code."""
        return UserBase(
            id=self.id,
            email=self.email,
            is_admin=self.is_admin,
            is_anonymous=self.is_anonymous,
            is_temporary=self.is_temporary,
            expiration_time=self.expiration_time,
        )

    @staticmethod
    def from_cache(user_cache_data: dict | None) -> "UserContext | None":
        """Create UserContext from consolidated cache data."""
        if not user_cache_data or not user_cache_data.get("user"):
            return None

        # Check if cache is still valid (5 minute timeout)
        import time

        current_time = time.time()
        if (current_time - user_cache_data.get("timestamp", 0)) > 300:
            return None

        user_data = user_cache_data["user"]
        return UserContext(
            id=user_data["id"],
            email=user_data["email"],
            is_admin=user_data["is_admin"],
            is_anonymous=user_data["is_anonymous"],
        )


class UserBaseUI(UserBase):
    # tokens: List[Token] = Field(default_factory=list)
    # current_access_token: Optional[str] = None
    is_active: bool = True
    is_verified: bool = False
    last_login: str | None = None
    registration_date: str | None = None
    # SSO-provided profile attributes (populated by sso_sync on SAML/OAuth login)
    display_name: str | None = None
    title: str | None = None
    login: str | None = None
    sso_provider: str | None = None


class User(UserBaseUI):
    password: str

    @field_validator("password", mode="before")
    def hash_password(cls, v):
        # check that the password is hashed
        if v.startswith("$2b$"):
            return v
        else:
            # Raise an error if the password is not hashed
            raise ValueError("Password must be hashed")

    def turn_to_userbaseui(self):
        userbaseui = UserBaseUI(
            id=self.id,
            email=self.email,
            is_admin=self.is_admin,
            is_active=self.is_active,
            is_verified=self.is_verified,
            last_login=self.last_login,
            registration_date=self.registration_date,
        )
        return userbaseui

    def turn_to_userbase(self):
        userbase = UserBase(
            id=self.id,
            email=self.email,
            is_admin=self.is_admin,
            # email=model_dump["email"], is_admin=model_dump["is_admin"], groups=model_dump["groups"]
        )
        return userbase


class UserBeanie(User, Document):
    class Settings:
        name = "users"


class GroupBeanie(Group, Document):
    # Membership is stored as plain ObjectIds (inherited from Group) — the
    # documents on disk are raw ObjectIds, not DBRefs, and nothing fetch_links
    # on groups.
    class Settings:
        name = "groups"  # Collection name


class Permission(BaseModel):
    owners: list[UserBase] = []  # Default to an empty list
    editors: list[UserBase] = []  # Default to an empty list
    viewers: list[UserBase | str] = []  # Allow string wildcard "*" in viewers
    # Group-level sharing: snapshots of groups granted a role on the resource.
    # Defaults keep every pre-groups document valid without migration.
    group_owners: list[GroupBase] = []
    group_editors: list[GroupBase] = []
    group_viewers: list[GroupBase] = []

    def dict(self, **kwargs):
        # Generate list of owner and viewer dictionaries
        owners_list = [owner.model_dump(**kwargs) for owner in self.owners]
        editors_list = [editor.model_dump(**kwargs) for editor in self.editors]
        viewers_list = [
            viewer.model_dump(**kwargs) if isinstance(viewer, UserBase) else viewer
            for viewer in self.viewers
        ]
        return {
            "owners": owners_list,
            "editors": editors_list,
            "viewers": viewers_list,
            "group_owners": [group.model_dump(**kwargs) for group in self.group_owners],
            "group_editors": [group.model_dump(**kwargs) for group in self.group_editors],
            "group_viewers": [group.model_dump(**kwargs) for group in self.group_viewers],
        }

    # Step 1: Convert lists to UserBase or validate items
    @field_validator("owners", "editors", "viewers", mode="before")
    def convert_list_to_userbase(cls, v):
        if not isinstance(v, list):
            raise ValueError(f"Expected a list, got {type(v)}")

        result = []
        # logger.debug(f"Converting list to UserBase: {v}")
        for item in v:
            # logger.debug(f"Converting {item} to UserBase")
            if isinstance(item, dict):
                # keep only id, email, is_admin
                item = {
                    key: value
                    for key, value in item.items()
                    if key in ["id", "_id", "email", "is_admin"]
                }
                # logger.debug(f"Filtered dictionary: {item}")

                result.append(UserBase.from_mongo(item))  # Convert dict to UserBase
            elif isinstance(item, str) and item == "*":
                result.append(item)  # Allow wildcard "*" for viewers
            elif isinstance(item, UserBase):
                result.append(item)  # Already a UserBase instance
            else:
                raise ValueError(
                    "Owners, editors, and viewers must be UserBase instances or valid types"
                )
        # logger.debug(f"Converted list to UserBase: {result}")
        return result

    @field_validator("group_owners", "group_editors", "group_viewers", mode="before")
    def convert_list_to_groupbase(cls, v):
        if not isinstance(v, list):
            raise ValueError(f"Expected a list, got {type(v)}")

        result = []
        for item in v:
            if isinstance(item, dict):
                # keep only identity fields — membership is never embedded
                item = {key: value for key, value in item.items() if key in ["id", "_id", "name"]}
                result.append(GroupBase.from_mongo(item))
            elif isinstance(item, GroupBase):
                result.append(item)
            else:
                raise ValueError("Group permission entries must be GroupBase instances or dicts")
        return result

    # Step 2: Validate permissions after field-level validation
    @model_validator(mode="after")
    def ensure_owners_and_viewers_are_unique(self):
        """A user may hold at most one DIRECT role, and a group at most one
        group role. There is deliberately NO cross-check between the user lists
        and the group lists: a user may be e.g. a direct viewer while one of
        their groups is an owner — the effective role resolves to the highest
        at read time (see depictio.api.v1.permissions)."""
        owners = self.owners
        editors = self.editors
        viewers = self.viewers
        # logger.debug(f"Owners: {owners}")
        # logger.debug(f"Editors: {editors}")
        # logger.debug(f"Viewers: {viewers}")

        owner_ids = {owner.id for owner in owners}
        editor_ids = {editor.id for editor in editors if isinstance(editor, UserBase)}
        viewer_ids = {viewer.id for viewer in viewers if isinstance(viewer, UserBase)}

        if not owner_ids.isdisjoint(editor_ids):
            raise ValueError("A User cannot be both an owner and an editor.")
        if not owner_ids.isdisjoint(viewer_ids):
            raise ValueError("A User cannot be both an owner and a viewer.")
        if not editor_ids.isdisjoint(viewer_ids):
            raise ValueError("A User cannot be both an editor and a viewer.")

        group_owner_ids = {group.id for group in self.group_owners}
        group_editor_ids = {group.id for group in self.group_editors}
        group_viewer_ids = {group.id for group in self.group_viewers}

        if not group_owner_ids.isdisjoint(group_editor_ids):
            raise ValueError("A Group cannot be both an owner and an editor.")
        if not group_owner_ids.isdisjoint(group_viewer_ids):
            raise ValueError("A Group cannot be both an owner and a viewer.")
        if not group_editor_ids.isdisjoint(group_viewer_ids):
            raise ValueError("A Group cannot be both an editor and a viewer.")

        return self


class RequestEditPassword(BaseModel):
    old_password: str
    new_password: str

    @field_validator("old_password")
    def validate_old_password(cls, v):
        # The route verifies the old password with bcrypt.checkpw(plaintext,
        # stored_hash) — a client-side bcrypt hash can never match (random
        # salt), so requiring a pre-hashed value here made the endpoint
        # unusable. Plaintext over TLS is the contract, same as login.
        if v.startswith("$2b$"):
            raise ValueError("Password must be sent in plaintext, not pre-hashed")
        return v

    @field_validator("new_password")
    def hash_new_password(cls, v):
        if v.startswith("$2b$"):
            raise ValueError("Password is already hashed")
        return v


class RequestUserRegistration(BaseModel):
    email: EmailStr
    password: str
    # NOTE: ``is_admin`` is intentionally absent. Admin promotion is gated by
    # /auth/turn_sysadmin (admin-only). Accepting an is_admin flag here would
    # let any registering user self-promote.
    # is_active: bool = True
    # is_verified: bool = False
    # last_login: Optional[str] = None
    # registration_date: Optional[str] = None

    # @field_validator("password")
    # def hash_password(cls, v):
    #     if v.startswith("$2b$"):
    #         return v
    #     else:
    #         # Raise an error if the password is not hashed
    #         raise ValueError("Password must be hashed")
