from typing import Dict, List, Optional, Set
from bson import ObjectId
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    validator,
    root_validator,
)

from depictio.api.v1.models.base import MongoModel, PyObjectId


##################
# Authentication #
##################


class Token(MongoModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    access_token: str
    # token_type: str
    expire_datetime: str
    name: Optional[str] = None
    # scope: Optional[str] = None
    # user_id: PyObjectId

    @root_validator(pre=True)
    def set_default_id(cls, values):
        if values is None or "_id" not in values or values["_id"] is None:
            return values  # Ensure we don't proceed if values is None
        values["_id"] = PyObjectId()
        return values

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: lambda v: str(v)}


class TokenData(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId
    exp: Optional[int] = None
    is_admin: bool = False

    @root_validator(pre=True)
    def set_default_id(cls, values):
        if values is None or "_id" not in values or values["_id"] is None:
            return values  # Ensure we don't proceed if values is None
        values["_id"] = PyObjectId()
        return values

###################
# User management #
###################


class User(MongoModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    # user_id: Optional[PyObjectId] = None
    # username: str
    email: EmailStr
    tokens: List[Token] = Field(default_factory=list)
    is_active: bool = True
    is_admin: bool = False
    is_verified: bool = False
    last_login: Optional[str] = None
    registration_date: Optional[str] = None
    groups: Optional[List[PyObjectId]] = Field(default_factory=list)
    password: str

    @root_validator(pre=True)
    def set_default_id(cls, values):
        if values is None or "_id" not in values or values["_id"] is None:
            return values  # Ensure we don't proceed if values is None
        values["_id"] = PyObjectId()
        return values

    @validator("password", pre=True)
    def hash_password(cls, v):
        # check that the password is hashed
        if v.startswith("$2b$"):
            return v

    class Config:
        json_encoders = {ObjectId: lambda v: str(v)}

    def __hash__(self):
        # Hash based on the unique user_id
        return hash(self.user_id)

    def __eq__(self, other):
        # Equality based on the unique user_id
        if isinstance(other, User):
            return all(getattr(self, field) == getattr(other, field) for field in self.__fields__.keys() if field not in ["user_id", "registration_time"])
        return False


class Group(BaseModel):
    user_id: PyObjectId = Field(default_factory=PyObjectId)
    name: str
    members: Set[User]  # Set of User objects instead of ObjectId

    @validator("members", each_item=True, pre=True)
    def ensure_unique_users(cls, user):
        if not isinstance(user, User):
            raise ValueError(f"Each member must be an instance of User, got {type(user)}")
        return user

    # This function ensures there are no duplicate users in the group
    @root_validator(pre=True)
    def ensure_unique_member_ids(cls, values):
        members = values.get("members", [])
        unique_members = {member.user_id: member for member in members}.values()
        return {"members": set(unique_members)}

    # This function validates that each user_id in the members is unique
    @root_validator
    def check_user_ids_are_unique(cls, values):
        seen = set()
        members = values.get("members", [])
        for member in members:
            if member.user_id in seen:
                raise ValueError("Duplicate user_id found in group members.")
            seen.add(member.user_id)
        return values


class Permission(BaseModel):
    owners: List[User]
    viewers: Optional[List[User]] = set()  # Set default to empty set

    def dict(self, **kwargs):
        # Generate list of owner and viewer dictionaries
        owners_list = [owner.dict(**kwargs) for owner in self.owners]
        viewers_list = [viewer.dict(**kwargs) for viewer in self.viewers]
        return {"owners": owners_list, "viewers": viewers_list}

    @validator("owners", "viewers", pre=True, each_item=True)
    def convert_dict_to_user(cls, v):
        if isinstance(v, dict):
            return User(**v)  # Assuming `User` is a Pydantic model and can be instantiated like this
        elif not isinstance(v, User):
            raise ValueError("Permissions should be assigned to User instances.")
        return v

    @root_validator(pre=True)
    def validate_permissions(cls, values):
        owners = values.get("owners", set())
        viewers = values.get("viewers", set())
        if not owners:
            raise ValueError("At least one owner is required.")

        return values

    # Here we ensure that there are no duplicate users across owners and viewers
    @root_validator
    def ensure_owners_and_viewers_are_unique(cls, values):
        owners = values.get("owners", set())
        viewers = values.get("viewers", set())
        owner_ids = {owner.user_id for owner in owners}
        viewer_ids = {viewer.user_id for viewer in viewers}

        if not owner_ids.isdisjoint(viewer_ids):
            raise ValueError("A User cannot be both an owner and a viewer.")

        return values

class TokenRequest(MongoModel):
    user: User
    token: Token