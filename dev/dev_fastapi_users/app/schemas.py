# app/schemas.py
from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi_users import schemas
from pydantic import BaseModel


class UserRead(schemas.BaseUser[PydanticObjectId]):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    groups: List[PydanticObjectId] = []
    created_at: datetime


class UserCreate(schemas.BaseUserCreate):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserUpdate(schemas.BaseUserUpdate):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


# Group schemas
class GroupBase(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []


class GroupCreate(GroupBase):
    pass


class GroupRead(GroupBase):
    id: PydanticObjectId
    created_at: datetime

    class Config:
        from_attributes = True


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None
