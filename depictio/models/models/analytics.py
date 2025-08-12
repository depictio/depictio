"""
Analytics models for tracking user sessions and activities.
"""

from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import BaseModel, Field

from depictio.models.models.base import MongoModel


class UserSession(MongoModel, Document):
    """
    Tracks user sessions including anonymous users.
    """

    user_id: str = Field(..., description="User identifier (email or anonymous ID)")
    session_id: str = Field(..., description="Unique session identifier")
    ip_address: str = Field(..., description="Client IP address")
    user_agent: str = Field(..., description="Browser/client info")
    start_time: datetime = Field(..., description="Session start time")
    last_activity: datetime = Field(..., description="Last request time")
    end_time: Optional[datetime] = Field(None, description="Session end time (null if active)")
    is_anonymous: bool = Field(..., description="True for unauthenticated users")
    page_views: int = Field(default=0, description="Count of pages viewed")
    api_calls: int = Field(default=0, description="Count of API requests")
    duration_seconds: Optional[int] = Field(None, description="Total session duration")

    class Settings:
        name = "user_sessions"
        indexes = [
            "user_id",
            "session_id",
            "start_time",
            "is_anonymous",
            [("user_id", 1), ("start_time", -1)],
        ]

    def calculate_duration(self) -> int:
        """Calculate session duration in seconds."""
        if self.end_time:
            return int((self.end_time - self.start_time).total_seconds())
        else:
            return int((self.last_activity - self.start_time).total_seconds())

    def is_active(self, timeout_minutes: int = 30) -> bool:
        """Check if session is still active based on last activity."""
        if self.end_time:
            return False

        inactive_duration = (datetime.utcnow() - self.last_activity).total_seconds() / 60
        return inactive_duration < timeout_minutes


class UserActivity(MongoModel, Document):
    """
    Tracks individual user activities and requests.
    """

    session_id: str = Field(..., description="Links to user_sessions")
    user_id: str = Field(..., description="User identifier")
    timestamp: datetime = Field(..., description="Activity timestamp")
    activity_type: str = Field(..., description="Type: page_view, api_call, login, logout")
    path: str = Field(..., description="URL path or API endpoint")
    method: str = Field(..., description="HTTP method")
    status_code: int = Field(..., description="Response status code")
    response_time_ms: float = Field(..., description="Request duration in milliseconds")
    project_id: Optional[str] = Field(None, description="Associated project ID")
    dashboard_id: Optional[str] = Field(None, description="Associated dashboard ID")

    class Settings:
        name = "user_activities"
        indexes = [
            "session_id",
            "user_id",
            "timestamp",
            "activity_type",
            [("user_id", 1), ("timestamp", -1)],
            [("session_id", 1), ("timestamp", -1)],
        ]


class AnalyticsSummary(BaseModel):
    """
    Summary statistics for analytics dashboard.
    """

    total_users: int
    active_sessions: int
    total_sessions_today: int
    total_page_views_today: int
    total_api_calls_today: int
    anonymous_users: int
    authenticated_users: int
    avg_session_duration_minutes: float
    top_pages: list[dict]
    hourly_activity: list[dict]


class SessionSummary(BaseModel):
    """
    Summary of a user session.
    """

    session_id: str
    user_id: str
    is_anonymous: bool
    start_time: datetime
    last_activity: datetime
    duration_minutes: float
    page_views: int
    api_calls: int
    ip_address: str
    user_agent: str
