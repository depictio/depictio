"""Per-user, per-dashboard state for cross-tab global filters and stories.

Stored in the ``user_dashboard_state`` MongoDB collection. A document is
keyed by ``(user_id, parent_dashboard_id)`` so two users on the same
dashboard maintain independent last-used filter values and last-active
story. Documents are created lazily on first write; their absence is
equivalent to "no overrides — use definition defaults".
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict, Field, field_serializer

from depictio.models.models.base import MongoModel, PyObjectId


class UserDashboardState(MongoModel):
    user_id: PyObjectId
    parent_dashboard_id: PyObjectId
    global_filter_values: dict[str, Any] = Field(default_factory=dict)
    last_active_story_id: Optional[str] = None
    last_active_tab_id: Optional[PyObjectId] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_serializer("user_id")
    def serialize_user_id(self, user_id: PyObjectId) -> str:
        return str(user_id)

    @field_serializer("parent_dashboard_id")
    def serialize_parent_dashboard_id(self, parent_dashboard_id: PyObjectId) -> str:
        return str(parent_dashboard_id)

    @field_serializer("last_active_tab_id")
    def serialize_last_active_tab_id(
        self, last_active_tab_id: Optional[PyObjectId]
    ) -> Optional[str]:
        return str(last_active_tab_id) if last_active_tab_id else None
