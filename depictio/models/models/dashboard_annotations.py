"""Per-user session annotations on a dashboard.

A viewer labels the rows of a metadata table (key -> label) to compare the
resulting groups, without changing the table. Each label column belongs to one
table and its key column, so a samplesheet and a metadata sheet can both carry
labels on the same dashboard. The client derives selection
groups from these labels; the server only stores them, one document per
(user, dashboard family main tab).

The wire shape is the client's (camelCase), so the payload round-trips without
a translation layer. Every model refuses unknown fields.
"""

import json
from datetime import datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel
from pymongo import IndexModel

from depictio.models.models.base import MongoModel

MAX_ANNOTATION_COLUMNS = 20
MAX_ANNOTATION_KEYS = 10_000
# Equal to the server's group name cap (`MAX_NAME_LENGTH` in
# `services/figure/groups.py`): every label becomes a group name, and a longer
# one would be cut, so two labels sharing their first 80 characters would
# collapse into one group.
MAX_LABEL_LENGTH = 80
MAX_KEY_LENGTH = 1_000
MAX_ANNOTATIONS_JSON_BYTES = 1_000_000


class _ClientShape(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class AnnotationColumn(_ClientShape):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=MAX_LABEL_LENGTH)
    dc_id: str = Field(min_length=1, max_length=64)
    key_column: str = Field(min_length=1, max_length=1_000)
    values: dict[str, str] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def validate_values(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > MAX_ANNOTATION_KEYS:
            raise ValueError(f"too many keys in one annotation (max {MAX_ANNOTATION_KEYS})")
        for key, label in v.items():
            if not key or len(key) > MAX_KEY_LENGTH:
                raise ValueError(f"keys must be 1 to {MAX_KEY_LENGTH} characters")
            if not label or len(label) > MAX_LABEL_LENGTH:
                raise ValueError(f"labels must be 1 to {MAX_LABEL_LENGTH} characters")
        return v


class DashboardAnnotationsPayload(_ClientShape):
    """Body of ``PUT /dashboards/annotations/{dashboard_id}``."""

    version: Literal[2] = 2
    columns: list[AnnotationColumn] = Field(default_factory=list)
    active_column_id: str | None = None

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, v: list[AnnotationColumn]) -> list[AnnotationColumn]:
        return _check_column_set(v)

    @model_validator(mode="after")
    def validate_whole(self) -> "DashboardAnnotationsPayload":
        # The active column may be one shared on the dashboard rather than one
        # of the reader's own; the client drops an id that names neither.
        if self.active_column_id is not None and len(self.active_column_id) > 64:
            raise ValueError("activeColumnId is too long")
        size = len(json.dumps(self.model_dump(by_alias=True)).encode())
        if size > MAX_ANNOTATIONS_JSON_BYTES:
            raise ValueError(f"annotations too large (max {MAX_ANNOTATIONS_JSON_BYTES} bytes)")
        return self


def _check_column_set(columns: list[AnnotationColumn]) -> list[AnnotationColumn]:
    if len(columns) > MAX_ANNOTATION_COLUMNS:
        raise ValueError(f"too many annotations (max {MAX_ANNOTATION_COLUMNS})")
    if len({c.id for c in columns}) != len(columns):
        raise ValueError("annotation ids must be unique")
    if len({c.name for c in columns}) != len(columns):
        raise ValueError("annotation names must be unique")
    return columns


class SharedLabelsPayload(_ClientShape):
    """Body of ``PUT /dashboards/annotations/{dashboard_id}/shared``: the label
    columns every reader of the dashboard sees, read-only. Same caps as a
    reader's own labels."""

    columns: list[AnnotationColumn] = Field(default_factory=list)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, v: list[AnnotationColumn]) -> list[AnnotationColumn]:
        return _check_column_set(v)

    @model_validator(mode="after")
    def validate_size(self) -> "SharedLabelsPayload":
        size = len(json.dumps(self.model_dump(by_alias=True)).encode())
        if size > MAX_ANNOTATIONS_JSON_BYTES:
            raise ValueError(f"labels too large (max {MAX_ANNOTATIONS_JSON_BYTES} bytes)")
        return self


class DashboardAnnotations(MongoModel):
    user_id: PydanticObjectId
    # Always the family's main tab: annotations belong to the whole dashboard.
    dashboard_id: PydanticObjectId
    annotations: DashboardAnnotationsPayload
    updated_at: datetime

    @field_serializer("user_id", "dashboard_id")
    def serialize_object_ids(self, value: PydanticObjectId) -> str:
        return str(value)


class DashboardAnnotationsBeanie(DashboardAnnotations, Document):
    class Settings:
        name = "dashboard_annotations"
        indexes = [
            # One document per (user, dashboard); writes are upserts against this key.
            IndexModel([("user_id", 1), ("dashboard_id", 1)], unique=True),
        ]
