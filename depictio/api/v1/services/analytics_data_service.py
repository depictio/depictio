"""
Analytics Data Service - Transform MongoDB analytics to Depictio-readable format.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import polars as pl
from bson import ObjectId
from bson.errors import InvalidId

from depictio.api.v1.configs.config import settings
from depictio.models.models.analytics import UserActivity, UserSession
from depictio.models.models.users import UserBeanie


class AnalyticsDataService:
    """Convert MongoDB analytics data to Depictio-readable Delta format."""

    def __init__(self):
        self.s3_base_path = f"s3://{settings.minio.bucket}/analytics"

    @staticmethod
    def is_valid_objectid(user_id: str) -> bool:
        """Check if a user_id string is a valid MongoDB ObjectId format."""
        if not user_id or len(user_id) != 24:
            return False
        try:
            ObjectId(user_id)
            return True
        except InvalidId:
            return False

    @staticmethod
    async def safe_get_user_by_id(user_id: str) -> Optional[UserBeanie]:
        """Safely get a user by ID, handling both ObjectId and UUID formats."""
        if not user_id or user_id.startswith("anon_"):
            return None

        # Only try to get user if it's a valid ObjectId format
        if not AnalyticsDataService.is_valid_objectid(user_id):
            # Invalid ObjectId format (likely UUID), skip this user
            return None

        try:
            return await UserBeanie.get(ObjectId(user_id))
        except Exception:
            # User not found or other error, return None
            return None

    async def extract_user_sessions(self, start_date: datetime, end_date: datetime) -> pl.DataFrame:
        """Extract and transform user sessions data into Polars DataFrame."""
        # Query MongoDB analytics
        sessions = await UserSession.find(
            UserSession.start_time >= start_date, UserSession.start_time <= end_date
        ).to_list()
        if not isinstance(sessions, list):
            sessions = []

        if not sessions:
            return pl.DataFrame(
                {
                    "user_id": pl.Series([], dtype=pl.String),
                    "session_id": pl.Series([], dtype=pl.String),
                    "start_time": pl.Series([], dtype=pl.String),
                    "end_time": pl.Series([], dtype=pl.String),
                    "duration_minutes": pl.Series([], dtype=pl.Float64),
                    "page_views": pl.Series([], dtype=pl.Int64),
                    "api_calls": pl.Series([], dtype=pl.Int64),
                    "is_anonymous": pl.Series([], dtype=pl.Boolean),
                    "ip_address": pl.Series([], dtype=pl.String),
                    "user_agent": pl.Series([], dtype=pl.String),
                }
            )

        # Transform to Polars DataFrame
        df = pl.DataFrame(
            {
                "user_id": [s.user_id for s in sessions],
                "session_id": [s.session_id for s in sessions],
                "start_time": [s.start_time for s in sessions],
                "end_time": [s.end_time for s in sessions],
                "duration_minutes": [
                    s.duration_seconds / 60 if s.duration_seconds else 0 for s in sessions
                ],
                "page_views": [s.page_views for s in sessions],
                "api_calls": [s.api_calls for s in sessions],
                "is_anonymous": [s.is_anonymous for s in sessions],
                "ip_address": [s.ip_address for s in sessions],
                "user_agent": [s.user_agent[:100] for s in sessions],  # Truncate long user agents
            }
        )

        return await self.enrich_user_data(df)

    async def enrich_user_data(self, df: pl.DataFrame) -> pl.DataFrame:
        """Enrich analytics data with user information from UserBeanie."""
        if df.height == 0:
            return df

        # Get unique authenticated user IDs (exclude anonymous)
        auth_user_ids = df.filter(~pl.col("is_anonymous"))["user_id"].unique().to_list()

        if not auth_user_ids:
            # Add empty user info columns for anonymous-only data
            return df.with_columns(
                [
                    pl.lit(None).alias("user_email"),
                    pl.lit(False).alias("user_is_admin"),
                    pl.lit(None).alias("user_registration_date"),
                ]
            )

        # Query user information
        user_data = {}
        for user_id_str in auth_user_ids:
            user = await self.safe_get_user_by_id(user_id_str)
            if user:
                user_data[user_id_str] = {
                    "email": user.email,
                    "is_admin": user.is_admin,
                    "registration_date": getattr(user, "registration_date", None),
                }

        # Create user info mapping
        user_emails = []
        user_is_admins = []
        user_reg_dates = []

        for row in df.iter_rows(named=True):
            user_id = row["user_id"]
            if row["is_anonymous"] or user_id not in user_data:
                user_emails.append("Anonymous")
                user_is_admins.append(False)
                user_reg_dates.append(None)
            else:
                user_info = user_data[user_id]
                user_emails.append(user_info["email"])
                user_is_admins.append(user_info["is_admin"])
                user_reg_dates.append(user_info["registration_date"])

        return df.with_columns(
            [
                pl.Series("user_email", user_emails),
                pl.Series("user_is_admin", user_is_admins),
                pl.Series("user_registration_date", user_reg_dates),
            ]
        )

    async def extract_user_activities(
        self, start_date: datetime, end_date: datetime
    ) -> pl.DataFrame:
        """Extract user activities data into Polars DataFrame."""
        activities = await UserActivity.find(
            UserActivity.timestamp >= start_date, UserActivity.timestamp <= end_date
        ).to_list()
        if not isinstance(activities, list):
            activities = []

        if not activities:
            return pl.DataFrame(
                {
                    "user_id": pl.Series([], dtype=pl.String),
                    "session_id": pl.Series([], dtype=pl.String),
                    "timestamp": pl.Series([], dtype=pl.String),
                    "activity_type": pl.Series([], dtype=pl.String),
                    "path": pl.Series([], dtype=pl.String),
                    "method": pl.Series([], dtype=pl.String),
                    "status_code": pl.Series([], dtype=pl.Int64),
                    "response_time_ms": pl.Series([], dtype=pl.Float64),
                }
            )

        return pl.DataFrame(
            {
                "user_id": [a.user_id for a in activities],
                "session_id": [a.session_id for a in activities],
                "timestamp": [a.timestamp for a in activities],
                "activity_type": [a.activity_type for a in activities],
                "path": [a.path for a in activities],
                "method": [a.method for a in activities],
                "status_code": [a.status_code for a in activities],
                "response_time_ms": [a.response_time_ms for a in activities],
            }
        )

    async def create_user_summary_delta(self, days: int = 30) -> Dict[str, Any]:
        """Create Delta table with user analytics summary."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        # Extract sessions data
        sessions_df = await self.extract_user_sessions(start_date, end_date)

        if sessions_df.height == 0:
            return {"success": False, "message": "No session data found", "records": 0}

        # Create user summary aggregations
        user_summary = (
            sessions_df.group_by("user_id")
            .agg(
                [
                    pl.count("session_id").alias("total_sessions"),
                    pl.sum("duration_minutes").alias("total_time_minutes"),
                    pl.sum("page_views").alias("total_page_views"),
                    pl.sum("api_calls").alias("total_api_calls"),
                    pl.max("start_time").alias("last_activity"),
                    pl.first("is_anonymous").alias("is_anonymous"),
                    pl.first("user_email").alias("user_email"),
                    pl.first("user_is_admin").alias("user_is_admin"),
                ]
            )
            .with_columns(
                [pl.lit(datetime.utcnow()).alias("generated_at"), pl.lit(days).alias("period_days")]
            )
        )

        # Save to temporary location (in production, this would go to S3/MinIO)
        temp_path = Path("/tmp/depictio_analytics")
        temp_path.mkdir(exist_ok=True)
        delta_path = temp_path / "user_summary.parquet"

        # Write as Parquet for now (Delta support can be added later)
        user_summary.write_parquet(delta_path)

        return {
            "success": True,
            "delta_path": str(delta_path),
            "records": user_summary.height,
            "generated_at": datetime.utcnow(),
        }

    async def create_activity_trends_delta(self, days: int = 7) -> Dict[str, Any]:
        """Create Delta table with activity trends data."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        # Extract activities data
        activities_df = await self.extract_user_activities(start_date, end_date)

        if activities_df.height == 0:
            return {"success": False, "message": "No activity data found", "records": 0}

        # Create daily activity trends
        daily_trends = (
            activities_df.with_columns(
                [
                    pl.col("timestamp").dt.truncate("1d").alias("date"),
                    pl.col("timestamp").dt.hour().alias("hour"),
                ]
            )
            .group_by(["date", "activity_type"])
            .agg(
                [
                    pl.count("timestamp").alias("activity_count"),
                    pl.mean("response_time_ms").alias("avg_response_time_ms"),
                ]
            )
            .with_columns([pl.lit(datetime.utcnow()).alias("generated_at")])
        )

        # Save trends data
        temp_path = Path("/tmp/depictio_analytics")
        temp_path.mkdir(exist_ok=True)
        delta_path = temp_path / "activity_trends.parquet"

        daily_trends.write_parquet(delta_path)

        return {
            "success": True,
            "delta_path": str(delta_path),
            "records": daily_trends.height,
            "generated_at": datetime.utcnow(),
        }

    async def get_realtime_metrics(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_type: str = "all",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get real-time analytics metrics using filtered data sources."""
        now = datetime.utcnow()

        # Use the same filtered data approach as user summary
        user_summary_df = await self.load_user_summary_data(
            start_date=start_date, end_date=end_date, user_type=user_type, user_id=user_id
        )

        # Calculate metrics from filtered user data
        if user_summary_df.height > 0:
            # Total unique users (active users count)
            total_users = user_summary_df.height

            # Total sessions from user summary
            total_sessions = user_summary_df["total_sessions"].sum()

            # API calls from session data
            total_api_calls = user_summary_df["total_api_calls"].sum()
        else:
            total_users = 0
            total_sessions = 0
            total_api_calls = 0

        # For response time, we still need to query activities directly but with date filtering
        if end_date is None:
            end_datetime = datetime.utcnow()
        else:
            end_datetime = datetime.combine(end_date, datetime.max.time())

        if start_date is None:
            end_datetime - timedelta(days=30)  # Default last 30 days
        else:
            datetime.combine(start_date, datetime.min.time())

        # Get today's activities for response time and page view calculation
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        todays_activities = await UserActivity.find(
            UserActivity.timestamp >= today_start,
            UserActivity.timestamp <= now,
        ).to_list()
        if not isinstance(todays_activities, list):
            todays_activities = []

        # Calculate page views from activities (more accurate than session counters)
        page_view_activities_today = [
            a for a in todays_activities if a.activity_type == "page_view"
        ]
        total_page_views = len(page_view_activities_today)

        # Calculate average response time from API activities
        api_activities_today = [a for a in todays_activities if a.activity_type == "api_call"]
        avg_response_time = 0
        if api_activities_today:
            avg_response_time = sum(a.response_time_ms for a in api_activities_today) / len(
                api_activities_today
            )

        # Calculate page views per hour (based on today's page views)
        hours_since_midnight = (now - today_start).total_seconds() / 3600
        page_views_per_hour = total_page_views / max(hours_since_midnight, 1)

        return {
            "active_sessions": total_users,  # Use total users as "active" metric
            "sessions_today": total_sessions,  # Use total sessions from filtered data
            "page_views_today": total_page_views,
            "page_views_per_hour": round(page_views_per_hour, 1),
            "api_calls_today": total_api_calls,
            "avg_response_time_ms": round(avg_response_time, 2),
            "timestamp": now.isoformat(),
        }

    async def load_user_summary_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_type: str = "all",
        user_id: Optional[str] = None,
    ) -> pl.DataFrame:
        """Load user summary data with automatic refresh for real-time updates."""
        # Always use fresh data for better responsiveness to new users
        # This bypasses the cache completely to ensure new users appear immediately
        return await self._generate_fresh_user_summary(start_date, end_date, user_type, user_id)

    async def _apply_user_summary_filters(
        self,
        df: pl.DataFrame,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_type: str = "all",
        user_id: Optional[str] = None,
    ) -> pl.DataFrame:
        """Apply filters to user summary DataFrame."""
        filtered_df = df

        # Apply user type filtering
        if user_type == "authenticated":
            filtered_df = filtered_df.filter(~pl.col("is_anonymous"))
        elif user_type == "anonymous":
            filtered_df = filtered_df.filter(pl.col("is_anonymous"))
        elif user_type == "admin":
            filtered_df = filtered_df.filter(pl.col("user_is_admin"))

        # Apply specific user filtering
        if user_id:
            filtered_df = filtered_df.filter(pl.col("user_id") == user_id)

        # Note: Date filtering for user summary would require re-aggregating from raw data
        # For now, we'll return the filtered results without date filtering
        # In a production system, you might want to implement this by going back to raw activities

        return filtered_df

    async def _generate_fresh_user_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_type: str = "all",
        user_id: Optional[str] = None,
    ) -> pl.DataFrame:
        """Generate fresh user summary data directly from MongoDB, including ALL users."""
        # Use provided dates or default to last 30 days
        if end_date is None:
            end_datetime = datetime.utcnow()
        else:
            end_datetime = datetime.combine(end_date, datetime.max.time())

        if start_date is None:
            start_datetime = end_datetime - timedelta(days=30)
        else:
            start_datetime = datetime.combine(start_date, datetime.min.time())

        # Get ALL registered users first
        all_user_data = {}
        from depictio.models.models.users import UserBeanie

        all_users = await UserBeanie.find().to_list()

        for user in all_users:
            user_id_str = str(user.id)
            all_user_data[user_id_str] = {
                "user_id": user_id_str,
                "total_sessions": 0,
                "total_time_minutes": 0.0,
                "total_page_views": 0,
                "total_api_calls": 0,
                "last_activity": None,
                "is_anonymous": False,
                "user_email": user.email,
                "user_is_admin": user.is_admin,
            }

        # Extract sessions data with date filtering and update user data
        sessions_df = await self.extract_user_sessions(start_datetime, end_datetime)

        if sessions_df.height > 0:
            # Update user data with actual session statistics
            user_summary = sessions_df.group_by("user_id").agg(
                [
                    pl.count("session_id").alias("total_sessions"),
                    pl.sum("duration_minutes").alias("total_time_minutes"),
                    pl.sum("page_views").alias("total_page_views"),
                    pl.sum("api_calls").alias("total_api_calls"),
                    pl.max("start_time").alias("last_activity"),
                    pl.first("is_anonymous").alias("is_anonymous"),
                    pl.first("user_email").alias("user_email"),
                    pl.first("user_is_admin").alias("user_is_admin"),
                ]
            )

            # Update the all_user_data with actual session data
            for row in user_summary.iter_rows(named=True):
                user_id_str = row["user_id"]
                if user_id_str in all_user_data:
                    all_user_data[user_id_str].update(
                        {
                            "total_sessions": row["total_sessions"],
                            "total_time_minutes": row["total_time_minutes"],
                            "total_page_views": row["total_page_views"],
                            "total_api_calls": row["total_api_calls"],
                            "last_activity": row["last_activity"],
                            "is_anonymous": row["is_anonymous"],
                        }
                    )

        # Convert to DataFrame (includes users with zero activity)
        if all_user_data:
            user_summary = pl.DataFrame(list(all_user_data.values()))
        else:
            user_summary = pl.DataFrame(
                {
                    "user_id": pl.Series([], dtype=pl.String),
                    "total_sessions": pl.Series([], dtype=pl.Int64),
                    "total_time_minutes": pl.Series([], dtype=pl.Float64),
                    "total_page_views": pl.Series([], dtype=pl.Int64),
                    "total_api_calls": pl.Series([], dtype=pl.Int64),
                    "last_activity": pl.Series([], dtype=pl.String),
                    "is_anonymous": pl.Series([], dtype=pl.Boolean),
                    "user_email": pl.Series([], dtype=pl.String),
                    "user_is_admin": pl.Series([], dtype=pl.Boolean),
                }
            )

        # Apply filters
        return await self._apply_user_summary_filters(
            user_summary, start_date, end_date, user_type, user_id
        )

    async def load_activity_trends_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_type: str = "all",
        user_id: Optional[str] = None,
    ) -> pl.DataFrame:
        """Load activity trends data with filtering support."""
        # Use provided dates or default to last 7 days
        if end_date is None:
            end_datetime = datetime.utcnow()
        else:
            end_datetime = datetime.combine(end_date, datetime.max.time())

        if start_date is None:
            start_datetime = end_datetime - timedelta(days=7)
        else:
            start_datetime = datetime.combine(start_date, datetime.min.time())

        # Extract activities data with date filtering
        activities_df = await self.extract_user_activities(start_datetime, end_datetime)

        if activities_df.height == 0:
            return pl.DataFrame(
                {
                    "date": pl.Series([], dtype=pl.String),
                    "activity_type": pl.Series([], dtype=pl.String),
                    "activity_count": pl.Series([], dtype=pl.Int64),
                    "avg_response_time_ms": pl.Series([], dtype=pl.Float64),
                }
            )

        # Apply user filtering if needed
        if user_id:
            activities_df = activities_df.filter(pl.col("user_id") == user_id)
        elif user_type != "all":
            # For user type filtering, we need to get session info for each activity
            # This is more complex, so we'll implement a simplified version for now
            # In a production system, you might want to denormalize this data
            pass

        # Create daily activity trends
        daily_trends = (
            activities_df.with_columns(
                [
                    pl.col("timestamp").dt.truncate("1d").alias("date"),
                ]
            )
            .group_by(["date", "activity_type"])
            .agg(
                [
                    pl.count("timestamp").alias("activity_count"),
                    pl.mean("response_time_ms").alias("avg_response_time_ms"),
                ]
            )
            .sort("date")
        )

        return daily_trends

    async def refresh_all_analytics_data(self) -> Dict[str, Any]:
        """Refresh all analytics Delta tables and clear cache."""
        results = {}

        # Clear any existing cache files to force fresh data generation
        cache_dir = Path("/tmp/depictio_analytics")
        if cache_dir.exists():
            for cache_file in cache_dir.glob("*.parquet"):
                try:
                    cache_file.unlink()
                    results[f"cleared_cache_{cache_file.name}"] = True
                except Exception as e:
                    results[f"failed_to_clear_{cache_file.name}"] = str(e)

        # Refresh user summary
        user_summary_result = await self.create_user_summary_delta()
        results["user_summary"] = user_summary_result

        # Refresh activity trends
        activity_trends_result = await self.create_activity_trends_delta()
        results["activity_trends"] = activity_trends_result

        return {"refresh_completed_at": datetime.utcnow().isoformat(), "results": results}

    async def get_top_pages(
        self,
        limit: int = 10,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_type: str = "all",
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """Get top pages by page view count."""
        # Use provided dates or default to last 30 days
        if end_date is None:
            end_datetime = datetime.utcnow()
        else:
            end_datetime = datetime.combine(end_date, datetime.max.time())

        if start_date is None:
            start_datetime = end_datetime - timedelta(days=30)
        else:
            start_datetime = datetime.combine(start_date, datetime.min.time())

        # Build query filters
        query_filters = [
            UserActivity.timestamp >= start_datetime,
            UserActivity.timestamp <= end_datetime,
            UserActivity.activity_type == "page_view",
        ]

        # Add user-specific filters if needed
        if user_id:
            query_filters.append(UserActivity.user_id == user_id)

        activities = await UserActivity.find(*query_filters).to_list()

        if not isinstance(activities, list) or not activities:
            return []

        # Filter activities based on user type if needed
        if user_type != "all":
            filtered_activities = []
            for activity in activities:
                # Get session info to check user type
                session = await UserSession.find_one(UserSession.session_id == activity.session_id)
                if session:
                    if user_type == "anonymous" and session.is_anonymous:
                        filtered_activities.append(activity)
                    elif user_type == "authenticated" and not session.is_anonymous:
                        filtered_activities.append(activity)
                    elif user_type == "admin":
                        # Check if user is admin (need to lookup user)
                        if not session.is_anonymous:
                            user = await self.safe_get_user_by_id(session.user_id)
                            if user and user.is_admin:
                                filtered_activities.append(activity)
            activities = filtered_activities

        # Count page views by path
        page_counts = {}
        for activity in activities:
            path = activity.path
            # Clean up path for display
            if path.startswith("/"):
                path = path[1:]  # Remove leading slash
            if not path:
                path = "Home"

            page_counts[path] = page_counts.get(path, 0) + 1

        # Sort by count and return top pages
        top_pages = sorted(page_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

        return [
            {
                "path": path,
                "page_views": count,
                "percentage": round((count / sum(page_counts.values())) * 100, 1)
                if page_counts
                else 0,
            }
            for path, count in top_pages
        ]

    async def get_user_list(self) -> list[dict]:
        """Get list of users for filter dropdown, including all registered users."""
        user_data = {}

        # First, get users from sessions (users who have activity)
        sessions = await UserSession.find().to_list()
        if isinstance(sessions, list):
            for session in sessions:
                if not session.is_anonymous and session.user_id not in user_data:
                    user_data[session.user_id] = {"has_activity": True}

        # Then, get ALL registered users from UserBeanie to include new users
        from depictio.models.models.users import UserBeanie

        all_users = await UserBeanie.find().to_list()
        if isinstance(all_users, list):
            for user in all_users:
                user_id_str = str(user.id)
                user_data[user_id_str] = {
                    "value": user_id_str,
                    "label": f"{user.email}{'*' if user_id_str not in user_data or not user_data[user_id_str].get('has_activity') else ''}",
                    "is_admin": user.is_admin,
                    "has_activity": user_data.get(user_id_str, {}).get("has_activity", False),
                }

        # For any session users we couldn't resolve, add fallback entries
        sessions = await UserSession.find().to_list()
        if isinstance(sessions, list):
            for session in sessions:
                if not session.is_anonymous and session.user_id not in user_data:
                    user_data[session.user_id] = {
                        "value": session.user_id,
                        "label": f"User {session.user_id[:8]}...",
                        "is_admin": False,
                        "has_activity": True,
                    }

        # Filter out entries that are just activity markers and sort by label
        valid_users = [
            entry
            for entry in user_data.values()
            if isinstance(entry, dict) and "value" in entry and "label" in entry
        ]

        return sorted(valid_users, key=lambda x: x["label"])

    async def get_users_active_today(self) -> Dict[str, Any]:
        """Get count of users active in the last 24 hours."""
        now = datetime.utcnow()
        today_start = now - timedelta(hours=24)

        # Get sessions from last 24 hours
        recent_sessions = await UserSession.find(UserSession.last_activity >= today_start).to_list()

        if not isinstance(recent_sessions, list):
            recent_sessions = []

        # Count unique authenticated users
        active_authenticated_users = len(
            set(
                s.user_id
                for s in recent_sessions
                if not s.is_anonymous and self.is_valid_objectid(s.user_id)
            )
        )

        # Count anonymous sessions
        active_anonymous_sessions = len([s for s in recent_sessions if s.is_anonymous])

        return {
            "authenticated_users": active_authenticated_users,
            "anonymous_sessions": active_anonymous_sessions,
            "total_active": active_authenticated_users + active_anonymous_sessions,
        }

    async def get_comprehensive_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_type: str = "all",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get comprehensive analytics summary for the selected period."""
        # Get filtered user summary data
        user_summary_df = await self.load_user_summary_data(
            start_date=start_date, end_date=end_date, user_type=user_type, user_id=user_id
        )

        # Get activity trends data for the same period
        activity_trends_df = await self.load_activity_trends_data(
            start_date=start_date, end_date=end_date, user_type=user_type, user_id=user_id
        )

        if user_summary_df.height == 0:
            return {
                "period_summary": {
                    "total_users": 0,
                    "total_sessions": 0,
                    "total_page_views": 0,
                    "total_api_calls": 0,
                    "total_time_minutes": 0.0,
                    "avg_session_duration": 0.0,
                    "unique_authenticated_users": 0,
                    "unique_anonymous_users": 0,
                },
                "user_breakdown": [],
                "activity_summary": {
                    "total_activities": 0,
                    "avg_response_time_ms": 0.0,
                    "activity_by_type": {},
                },
            }

        # Calculate overall summary metrics
        total_users = user_summary_df.height
        total_sessions = user_summary_df["total_sessions"].sum()
        total_api_calls = user_summary_df["total_api_calls"].sum()
        # Note: total_time_minutes will be calculated from actual session data below
        total_time_minutes = 0.0

        # Get page views directly from activities (more accurate than session counters)
        if end_date is None:
            end_datetime = datetime.utcnow()
        else:
            end_datetime = datetime.combine(end_date, datetime.max.time())

        if start_date is None:
            start_datetime = end_datetime - timedelta(days=30)
        else:
            start_datetime = datetime.combine(start_date, datetime.min.time())

        # Query page view activities directly
        page_view_activities = await UserActivity.find(
            UserActivity.timestamp >= start_datetime,
            UserActivity.timestamp <= end_datetime,
            UserActivity.activity_type == "page_view",
        ).to_list()

        total_page_views = len(page_view_activities) if page_view_activities else 0

        # Count user types
        authenticated_users = user_summary_df.filter(~pl.col("is_anonymous")).height
        anonymous_users = user_summary_df.filter(pl.col("is_anonymous")).height

        # Create user ID mapping from sessions to activities
        # Get all sessions for this period to map session_id -> user_id
        session_user_mapping = {}
        sessions_data = await UserSession.find(
            UserSession.start_time >= start_datetime,
            UserSession.start_time <= end_datetime,
        ).to_list()

        for session in sessions_data:
            session_user_mapping[session.session_id] = session.user_id

        # Create detailed user breakdown with accurate page view counts
        user_breakdown = []
        total_calculated_time = 0.0  # Track total time from individual calculations
        total_attributed_views = 0  # Track how many page views we successfully attribute

        for row in user_summary_df.iter_rows(named=True):
            user_id = row["user_id"]
            user_email = row["user_email"]

            # Get all session IDs for this user
            user_session_ids = [
                s.session_id for s in sessions_data if str(s.user_id) == str(user_id)
            ]

            # Count page views from activities that have this user's session IDs
            user_page_views = 0

            # Try to match page views to users via session mapping or direct user ID
            session_matched_views = sum(
                1 for activity in page_view_activities if activity.session_id in user_session_ids
            )
            direct_matched_views = sum(
                1 for activity in page_view_activities if str(activity.user_id) == str(user_id)
            )
            user_page_views = max(session_matched_views, direct_matched_views)

            # Calculate session time from actual session data
            user_sessions = [s for s in sessions_data if str(s.user_id) == str(user_id)]
            total_session_time = 0.0
            for session in user_sessions:
                session_duration = 0.0
                if session.duration_seconds:
                    session_duration = session.duration_seconds / 60  # Convert to minutes
                elif session.end_time and session.start_time:
                    session_duration = (session.end_time - session.start_time).total_seconds() / 60
                elif session.last_activity and session.start_time:
                    # Use last_activity as proxy for session duration
                    session_duration = (
                        session.last_activity - session.start_time
                    ).total_seconds() / 60
                total_session_time += session_duration

            # Add to total calculated time for period summary
            total_calculated_time += total_session_time
            total_attributed_views += user_page_views

            user_breakdown.append(
                {
                    "user_email": user_email,
                    "is_anonymous": row["is_anonymous"],
                    "is_admin": row["user_is_admin"],
                    "sessions": row["total_sessions"],
                    "page_views": user_page_views,  # Will be updated by fallback if needed
                    "api_calls": row["total_api_calls"],
                    "time_minutes": round(total_session_time, 1),  # Fixed time calculation
                    "avg_session_duration": round(
                        total_session_time / max(row["total_sessions"], 1), 1
                    ),  # Fixed avg
                    "last_activity": row["last_activity"].isoformat()
                    if row["last_activity"]
                    else None,
                }
            )

        # If no page views were attributed to users but we have total page views,
        # distribute them proportionally based on session time
        if total_attributed_views == 0 and total_page_views > 0 and total_calculated_time > 0:
            for user_data in user_breakdown:
                if user_data["time_minutes"] > 0:
                    # Proportional distribution based on time spent
                    proportion = user_data["time_minutes"] / total_calculated_time
                    distributed_views = int(total_page_views * proportion)
                    user_data["page_views"] = distributed_views

        # Update total time minutes with calculated value
        total_time_minutes = total_calculated_time

        # Calculate average session duration using the correctly calculated total time
        avg_session_duration = total_calculated_time / max(total_sessions, 1)

        # Sort by total activity (sessions + page views + api calls)
        user_breakdown.sort(
            key=lambda x: x["sessions"] + x["page_views"] + x["api_calls"], reverse=True
        )

        # Calculate activity summary
        activity_summary = {
            "total_activities": 0,
            "avg_response_time_ms": 0.0,
            "activity_by_type": {},
        }

        if activity_trends_df.height > 0:
            total_activities = activity_trends_df["activity_count"].sum()
            avg_response_time = activity_trends_df["avg_response_time_ms"].mean()

            # Group by activity type
            activity_by_type = {}
            for row in activity_trends_df.iter_rows(named=True):
                activity_type = row["activity_type"]
                if activity_type not in activity_by_type:
                    activity_by_type[activity_type] = 0
                activity_by_type[activity_type] += row["activity_count"]

            import math

            activity_summary = {
                "total_activities": total_activities,
                "avg_response_time_ms": round(avg_response_time, 2)
                if not math.isnan(avg_response_time)
                else 0.0,
                "activity_by_type": activity_by_type,
            }

        return {
            "period_summary": {
                "total_users": total_users,
                "total_sessions": total_sessions,
                "total_page_views": total_page_views,
                "total_api_calls": total_api_calls,
                "total_time_minutes": round(total_time_minutes, 1),
                "avg_session_duration": round(avg_session_duration, 1),
                "unique_authenticated_users": authenticated_users,
                "unique_anonymous_users": anonymous_users,
            },
            "user_breakdown": user_breakdown,
            "activity_summary": activity_summary,
        }
