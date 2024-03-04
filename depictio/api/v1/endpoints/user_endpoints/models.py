from typing import List, Optional, Set
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


class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: Optional[int] = None
    scope: Optional[str] = None
    user_id: PyObjectId

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class TokenData(BaseModel):
    user_id: PyObjectId
    exp: Optional[int] = None
    is_admin: bool = False


###################
# User management #
###################


class User(MongoModel):
    user_id: PyObjectId = Field(default_factory=PyObjectId)
    username: str
    email: EmailStr

    class Config:
        json_encoders = {ObjectId: lambda v: str(v)}

    def __hash__(self):
        # Hash based on the unique user_id
        return hash(self.user_id)

    def __eq__(self, other):
        # Equality based on the unique user_id
        if isinstance(other, User):
            return self.user_id == other.user_id
        return False


class Group(BaseModel):
    user_id: PyObjectId = Field(default_factory=PyObjectId)
    name: str
    members: Set[User]  # Set of User objects instead of ObjectId

    @validator("members", each_item=True, pre=True)
    def ensure_unique_users(cls, user):
        if not isinstance(user, User):
            raise ValueError(
                f"Each member must be an instance of User, got {type(user)}"
            )
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
        # Before converting to list, let's print the owners and viewers
        # print("Converting to dict - Owners and Viewers as objects:")
        # print("Owners:", self.owners)
        # print("Viewers:", self.viewers)

        # Generate list of owner and viewer dictionaries
        owners_list = [owner.dict(**kwargs) for owner in self.owners]
        viewers_list = [viewer.dict(**kwargs) for viewer in self.viewers]

        # print("Converting to dict - Owners and Viewers as lists of dicts:")
        # print("Owners Dict List:", owners_list)
        # print("Viewers Dict List:", viewers_list)

        return {"owners": owners_list, "viewers": viewers_list}

    @validator("owners", "viewers", pre=True, each_item=True)
    def convert_dict_to_user(cls, v):
        if isinstance(v, dict):
            return User(
                **v
            )  # Assuming `User` is a Pydantic model and can be instantiated like this
        elif not isinstance(v, User):
            raise ValueError("Permissions should be assigned to User instances.")
        return v

    @root_validator(pre=True)
    def validate_permissions(cls, values):
        # print("Inside validate_permissions - Raw input values:")
        # print(values)

        owners = values.get("owners", set())
        viewers = values.get("viewers", set())

        # print("Inside validate_permissions - Parsed owners and viewers:")
        # print("Owners:", owners)
        # print("Viewers:", viewers)

        # Check if owners and viewers are sets and contain only User instances
        if not owners:
            raise ValueError("At least one owner is required.")

        # if not isinstance(owners, set) or any(not isinstance(owner, User) for owner in owners):
        #     raise ValueError("All owners must be User instances.")

        # if viewers and (not isinstance(viewers, set) or any(not isinstance(viewer, User) for viewer in viewers)):
        #     raise ValueError("All viewers must be User instances if provided.")

        return values

    # Here we ensure that there are no duplicate users across owners and viewers
    @root_validator
    def ensure_owners_and_viewers_are_unique(cls, values):
        owners = values.get("owners", set())
        viewers = values.get("viewers", set())
        owner_ids = {owner.user_id for owner in owners}
        viewer_ids = {viewer.user_id for viewer in viewers}

        # Check if there is any intersection between owners and viewers
        if not owner_ids.isdisjoint(viewer_ids):
            raise ValueError("A User cannot be both an owner and a viewer.")

        # You would add additional checks here to ensure all users exist in your database
        # If you're pulling from a real database, this would be the place to query it and validate

        return values



