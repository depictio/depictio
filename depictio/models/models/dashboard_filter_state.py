"""Per-user, per-dashboard persisted filter state.

Stores the viewer's applied filters (left-panel controls plus scatter/table/
map/image selections — they all share one ``InteractiveFilter[]`` array on the
client) so a user gets their view back when returning to a dashboard, from any
browser. Deliberately separate from ``DashboardData``: saving the dashboard
requires *editor* permission, while filter state must be writable by anyone
who can view the dashboard.

The ``filters`` entries are opaque client state — the server never interprets
them for this feature — so they stay untyped dicts rather than coupling the
backend to the frontend ``InteractiveFilter`` shape.
"""

import json
from datetime import datetime
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field, field_serializer, field_validator
from pymongo import IndexModel

from depictio.models.models.base import MongoModel

MAX_FILTER_ENTRIES = 200
MAX_FILTERS_JSON_BYTES = 200_000


class DashboardFilterState(MongoModel):
    user_id: PydanticObjectId
    dashboard_id: PydanticObjectId
    filters: list[dict[str, Any]] = Field(default_factory=list)
    # Mirrors the client's "Remember filters" toggle so the OFF preference
    # roams across browsers; ``filters`` is kept empty while disabled.
    enabled: bool = True
    updated_at: datetime

    @field_serializer("user_id", "dashboard_id")
    def serialize_object_ids(self, value: PydanticObjectId) -> str:
        return str(value)


class DashboardFilterStateBeanie(DashboardFilterState, Document):
    class Settings:
        name = "dashboard_filter_states"
        indexes = [
            # One state per (user, dashboard); writes are upserts against this key.
            IndexModel([("user_id", 1), ("dashboard_id", 1)], unique=True),
        ]


class DashboardFilterStatePayload(BaseModel):
    """Body of ``PUT /dashboards/filter_state/{dashboard_id}``."""

    filters: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(v) > MAX_FILTER_ENTRIES:
            raise ValueError(f"too many filter entries (max {MAX_FILTER_ENTRIES})")
        for entry in v:
            if not isinstance(entry.get("index"), str):
                raise ValueError("every filter entry needs a string 'index'")
        if len(json.dumps(v, default=str).encode()) > MAX_FILTERS_JSON_BYTES:
            raise ValueError(f"filters payload too large (max {MAX_FILTERS_JSON_BYTES} bytes)")
        return v
