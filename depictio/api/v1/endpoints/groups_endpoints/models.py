"""Wire (request/response) models for the groups management API.

Deliberately kept OUTSIDE ``depictio/models/`` (the ``ty``-gated package):
these shapes exist only for the ``/groups`` router — they are never persisted
and never shared with the CLI/models layer. The persisted schema lives in
``depictio.models.models.users.Group`` / ``GroupBeanie``.
"""

from pydantic import BaseModel, Field, field_validator

from depictio.models.models.base import PyObjectId


class GroupSummary(BaseModel):
    """Minimal group info for pickers/lists — no member identities leaked."""

    id: str
    name: str
    description: str | None = None
    member_count: int
    sso_managed: bool = False


class MyGroup(GroupSummary):
    """A group the caller belongs to, annotated with their role in it."""

    is_group_admin: bool
    is_pi: bool


class GroupMemberOut(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    is_group_admin: bool
    is_pi: bool


class GroupDetail(BaseModel):
    id: str
    name: str
    description: str | None = None
    sso_managed: bool = False
    pi_id: str | None = None
    admin_ids: list[str] = Field(default_factory=list)
    members: list[GroupMemberOut] = Field(default_factory=list)


def _validate_group_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Group name cannot be empty")
    return value


class GroupCreateRequest(BaseModel):
    name: str
    description: str | None = None
    pi_id: PyObjectId | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        return _validate_group_name(v)


class GroupUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_group_name(v)
