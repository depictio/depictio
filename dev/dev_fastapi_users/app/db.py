# app/db.py
import motor.motor_asyncio
from beanie import Document, Link
from fastapi_users.db import BeanieBaseUser, BaseOAuthAccount
from fastapi_users_db_beanie import BeanieUserDatabase
from typing import List, Optional
from datetime import datetime
from pydantic import Field

DATABASE_URL = "mongodb://localhost:27018"
client = motor.motor_asyncio.AsyncIOMotorClient(
    DATABASE_URL, uuidRepresentation="standard"
)
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
    groups: List[Link[Group]] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    oauth_accounts: list[OAuthAccount] = Field(default_factory=list)

    class Settings:
        name = "users"
        email_collation = None  # Or set to the appropriate MongoDB collation



async def get_user_db():
    yield BeanieUserDatabase(User, OAuthAccount)