# app/db.py
from datetime import datetime
from typing import List, Optional

import motor.motor_asyncio
from beanie import Document, PydanticObjectId
from fastapi_users.db import BaseOAuthAccount, BeanieBaseUser
from fastapi_users_db_beanie import BeanieUserDatabase
from pydantic import Field

DATABASE_URL = "mongodb://localhost:27018"
client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL, uuidRepresentation="standard")
db = client["fastapi_users_db"]


class OAuthAccount(BaseOAuthAccount):
    pass


class Group(Document):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "groups"


class User(BeanieBaseUser, Document):
    # Adding custom fields to the user model
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    groups_ids: List[PydanticObjectId] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    oauth_accounts: list[OAuthAccount] = Field(default_factory=list)

    class Settings:
        name = "users"
        email_collation = None  # Or set to the appropriate MongoDB collation


async def get_user_db():
    yield BeanieUserDatabase(User, OAuthAccount)
