"""
Analytics service for tracking user sessions and activities.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request
from pymongo import DESCENDING

from depictio.api.v1.endpoints.user_endpoints.core_functions import _async_fetch_user_from_token
from depictio.models.models.analytics import (
    AnalyticsSummary,
    SessionSummary,
    UserActivity,
    UserSession,
)


class AnalyticsService:
    """Service for handling user analytics tracking."""

    def __init__(self, session_timeout_minutes: int = 30, cleanup_days: int = 90):
        self.session_timeout_minutes = session_timeout_minutes
        self.cleanup_days = cleanup_days

    async def get_or_create_session(
        self, request: Request, user_id: Optional[str] = None
    ) -> UserSession:
        """
        Get existing session or create a new one.
        For authenticated users, extracts the MongoDB ObjectId from the auth token.
        For anonymous users, creates a stable hash-based user_id.
        """
        # Extract session info from request
        ip_address = self.get_client_ip(request)
        user_agent = request.headers.get("user-agent", "Unknown")

        # Try to get authenticated user ID from token if user_id not provided
        if not user_id:
            authenticated_user_id = await self.extract_user_id_from_token(request)
            if authenticated_user_id:
                user_id = authenticated_user_id  # Use MongoDB ObjectId
            else:
                # For anonymous users, create a stable user_id based on IP + User-Agent hash
                user_id = f"anon_{hash(f'{ip_address}_{user_agent}') % 1000000:06d}"

        # Try to find existing active session
        session = await self.find_active_session(user_id, ip_address)

        if session:
            # Update last activity
            session.last_activity = datetime.utcnow()
            await session.save()
            return session

        # Create new session
        session_id = str(uuid.uuid4())
        session = UserSession(
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            start_time=datetime.utcnow(),
            last_activity=datetime.utcnow(),
            is_anonymous=user_id.startswith("anon_"),
            page_views=0,
            api_calls=0,
        )

        await session.create()
        return session

    async def find_active_session(self, user_id: str, ip_address: str) -> Optional[UserSession]:
        """
        Find an active session for the user.
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=self.session_timeout_minutes)

        session = await UserSession.find_one(
            UserSession.user_id == user_id,
            UserSession.ip_address == ip_address,
            UserSession.end_time is None,
            UserSession.last_activity >= cutoff_time,
        )

        return session

    async def log_activity(
        self,
        session: UserSession,
        request: Request,
        status_code: int,
        response_time_ms: float,
        project_id: Optional[str] = None,
        dashboard_id: Optional[str] = None,
    ) -> UserActivity:
        """
        Log a user activity.
        """
        path = str(request.url.path)
        method = request.method

        # Determine activity type
        activity_type = self.classify_activity_type(path, method)

        # Create activity record
        activity = UserActivity(
            session_id=session.session_id,
            user_id=session.user_id,
            timestamp=datetime.utcnow(),
            activity_type=activity_type,
            path=path,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            project_id=project_id,
            dashboard_id=dashboard_id,
        )

        await activity.create()

        # Update session counters
        if activity_type == "page_view":
            session.page_views += 1
        elif activity_type == "api_call":
            session.api_calls += 1

        session.last_activity = datetime.utcnow()
        await session.save()

        return activity

    def classify_activity_type(self, path: str, method: str) -> str:
        """
        Classify the type of activity based on path and method.
        """
        if path.startswith("/api/"):
            if path.startswith("/api/v1/auth/login"):
                return "login"
            elif path.startswith("/api/v1/auth/logout"):
                return "logout"
            else:
                return "api_call"
        else:
            return "page_view"

    def get_client_ip(self, request: Request) -> str:
        """
        Extract client IP address from request.
        """
        # Try to get real IP from headers (for reverse proxy setups)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fallback to direct client IP
        if hasattr(request.client, "host"):
            return request.client.host

        return "unknown"

    async def extract_user_id_from_token(self, request: Request) -> Optional[str]:
        """
        Extract the MongoDB ObjectId from an authentication token in the request.
        Returns None if no valid token is found.
        """
        # Try to get token from Authorization header
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")

            # Fetch user using the token
            user = await _async_fetch_user_from_token(token)
            if user:
                return str(user.id)  # Return the MongoDB ObjectId as string

        return None

    async def resolve_user_from_analytics_id(self, user_id: str):
        """
        Resolve a user_id from analytics data back to a UserBeanie document.
        Returns None for anonymous users or if user not found.

        Args:
            user_id: The user_id from analytics data (ObjectId string for authenticated users,
                    "anon_XXXXXX" format for anonymous users)

        Returns:
            UserBeanie object if authenticated user is found, None otherwise
        """
        # Skip anonymous users
        if user_id.startswith("anon_"):
            return None

        try:
            # Try to get user by MongoDB ObjectId
            from bson import ObjectId

            from depictio.models.models.users import UserBeanie

            user = await UserBeanie.get(ObjectId(user_id))
            return user
        except Exception:
            # Invalid ObjectId or user not found
            return None

    async def end_session(self, session_id: str) -> Optional[UserSession]:
        """
        End a session and calculate final duration.
        """
        session = await UserSession.find_one(UserSession.session_id == session_id)
        if not session or session.end_time:
            return None

        session.end_time = datetime.utcnow()
        session.duration_seconds = session.calculate_duration()
        await session.save()

        return session

    async def cleanup_old_sessions(self, days_to_keep: Optional[int] = None) -> dict:
        """
        Clean up old sessions and activities.

        Args:
            days_to_keep: Override default cleanup_days if provided
        """
        cleanup_days = days_to_keep if days_to_keep is not None else self.cleanup_days
        cutoff_date = datetime.utcnow() - timedelta(days=cleanup_days)

        # End inactive sessions
        inactive_sessions = await UserSession.find(
            UserSession.end_time is None,
            UserSession.last_activity
            < datetime.utcnow() - timedelta(minutes=self.session_timeout_minutes),
        ).to_list()

        ended_count = 0
        for session in inactive_sessions:
            session.end_time = session.last_activity
            session.duration_seconds = session.calculate_duration()
            await session.save()
            ended_count += 1

        # Delete old data
        old_sessions = await UserSession.find(UserSession.start_time < cutoff_date).delete()

        old_activities = await UserActivity.find(UserActivity.timestamp < cutoff_date).delete()

        return {
            "ended_sessions": ended_count,
            "deleted_sessions": old_sessions.deleted_count
            if hasattr(old_sessions, "deleted_count")
            else 0,
            "deleted_activities": old_activities.deleted_count
            if hasattr(old_activities, "deleted_count")
            else 0,
        }

    async def get_analytics_summary(self) -> AnalyticsSummary:
        """
        Get analytics summary for dashboard.
        """
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Active sessions
        active_sessions = await UserSession.find(
            UserSession.end_time is None,
            UserSession.last_activity >= now - timedelta(minutes=self.session_timeout_minutes),
        ).count()

        # Today's sessions
        todays_sessions = await UserSession.find(UserSession.start_time >= today_start).count()

        # Today's activities
        try:
            todays_activities = await UserActivity.find(
                UserActivity.timestamp >= today_start
            ).to_list()
            if not isinstance(todays_activities, list):
                todays_activities = []
        except Exception:
            todays_activities = []

        page_views_today = len([a for a in todays_activities if a.activity_type == "page_view"])
        api_calls_today = len([a for a in todays_activities if a.activity_type == "api_call"])

        # User counts
        try:
            all_sessions = await UserSession.find().to_list()
            if not isinstance(all_sessions, list):
                all_sessions = []
        except Exception:
            all_sessions = []

        unique_users = set(session.user_id for session in all_sessions)
        total_users = len(unique_users)

        try:
            anonymous_sessions = await UserSession.find(UserSession.is_anonymous).to_list()
            if not isinstance(anonymous_sessions, list):
                anonymous_sessions = []
        except Exception:
            anonymous_sessions = []

        anonymous_user_ids = set(session.user_id for session in anonymous_sessions)
        anonymous_users_count = len(anonymous_user_ids)
        authenticated_users = total_users - anonymous_users_count

        # Average session duration
        try:
            completed_sessions = await UserSession.find(
                UserSession.duration_seconds is not None, UserSession.start_time >= today_start
            ).to_list()
            if not isinstance(completed_sessions, list):
                completed_sessions = []
        except Exception:
            completed_sessions = []

        avg_duration = 0
        if completed_sessions:
            avg_duration = (
                sum(s.duration_seconds for s in completed_sessions) / len(completed_sessions) / 60
            )

        # Top pages
        page_activities = [a for a in todays_activities if a.activity_type == "page_view"]
        page_counts = {}
        for activity in page_activities:
            page_counts[activity.path] = page_counts.get(activity.path, 0) + 1

        top_pages = [
            {"path": path, "views": count}
            for path, count in sorted(page_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        # Hourly activity (last 24 hours)
        hourly_activity = []
        for i in range(24):
            hour_start = now - timedelta(hours=i + 1)
            hour_end = now - timedelta(hours=i)
            hour_activities = [a for a in todays_activities if hour_start <= a.timestamp < hour_end]
            hourly_activity.append(
                {"hour": hour_start.strftime("%H:00"), "activities": len(hour_activities)}
            )

        return AnalyticsSummary(
            total_users=total_users,
            active_sessions=active_sessions,
            total_sessions_today=todays_sessions,
            total_page_views_today=page_views_today,
            total_api_calls_today=api_calls_today,
            anonymous_users=anonymous_users_count,
            authenticated_users=authenticated_users,
            avg_session_duration_minutes=avg_duration,
            top_pages=top_pages,
            hourly_activity=hourly_activity,
        )

    async def get_active_sessions(self, limit: int = 50) -> list[SessionSummary]:
        """
        Get list of active sessions.
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=self.session_timeout_minutes)

        sessions = (
            await UserSession.find(
                UserSession.end_time is None, UserSession.last_activity >= cutoff_time
            )
            .sort([(UserSession.last_activity, DESCENDING)])
            .limit(limit)
            .to_list()
        )

        return [
            SessionSummary(
                session_id=session.session_id,
                user_id=session.user_id,
                is_anonymous=session.is_anonymous,
                start_time=session.start_time,
                last_activity=session.last_activity,
                duration_minutes=(session.last_activity - session.start_time).total_seconds() / 60,
                page_views=session.page_views,
                api_calls=session.api_calls,
                ip_address=session.ip_address,
                user_agent=session.user_agent,
            )
            for session in sessions
        ]
