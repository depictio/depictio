"""
Analytics Data Service - Transform MongoDB analytics to Depictio-readable format.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import polars as pl

from depictio.api.v1.configs.config import settings
from depictio.models.models.analytics import UserActivity, UserSession
from depictio.models.models.users import UserBeanie


class AnalyticsDataService:
    """Convert MongoDB analytics data to Depictio-readable Delta format."""

    def __init__(self):
        self.s3_base_path = f"s3://{settings.minio.bucket}/analytics"

    async def extract_user_sessions(self, start_date: datetime, end_date: datetime) -> pl.DataFrame:
        """Extract and transform user sessions data into Polars DataFrame."""
        # Query MongoDB analytics
        try:
            sessions = await UserSession.find(
                UserSession.start_time >= start_date, UserSession.start_time <= end_date
            ).to_list()
            if not isinstance(sessions, list):
                sessions = []
        except Exception:
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
            try:
                from bson import ObjectId

                user = await UserBeanie.get(ObjectId(user_id_str))
                if user:
                    user_data[user_id_str] = {
                        "email": user.email,
                        "is_admin": user.is_admin,
                        "registration_date": getattr(user, "registration_date", None),
                    }
            except Exception:
                # Handle invalid ObjectIds or missing users
                continue

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
        try:
            activities = await UserActivity.find(
                UserActivity.timestamp >= start_date, UserActivity.timestamp <= end_date
            ).to_list()
            if not isinstance(activities, list):
                activities = []
        except Exception:
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

    async def get_realtime_metrics(self) -> Dict[str, Any]:
        """Get real-time analytics metrics without Delta tables."""
        now = datetime.utcnow()

        # Active sessions (last 30 minutes)
        try:
            active_sessions = await UserSession.find(
                UserSession.last_activity >= now - timedelta(minutes=30)
            ).count()
        except Exception:
            active_sessions = 0

        # Today's sessions
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            todays_sessions = await UserSession.find(UserSession.start_time >= today_start).count()
        except Exception:
            todays_sessions = 0

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

        # Average response time today
        api_activities_today = [a for a in todays_activities if a.activity_type == "api_call"]
        avg_response_time = 0
        if api_activities_today:
            avg_response_time = sum(a.response_time_ms for a in api_activities_today) / len(
                api_activities_today
            )

        return {
            "active_sessions": active_sessions,
            "sessions_today": todays_sessions,
            "page_views_today": page_views_today,
            "api_calls_today": api_calls_today,
            "avg_response_time_ms": round(avg_response_time, 2),
            "timestamp": now.isoformat(),
        }

    async def load_user_summary_data(self) -> pl.DataFrame:
        """Load user summary data from Delta table."""
        delta_path = Path("/tmp/depictio_analytics/user_summary.parquet")

        if not delta_path.exists():
            # Create initial data if doesn't exist
            await self.create_user_summary_delta()

        try:
            return pl.read_parquet(delta_path)
        except Exception:
            # Return empty DataFrame with correct schema if read fails
            return pl.DataFrame(
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

    async def load_activity_trends_data(self) -> pl.DataFrame:
        """Load activity trends data from Delta table."""
        delta_path = Path("/tmp/depictio_analytics/activity_trends.parquet")

        if not delta_path.exists():
            # Create initial data if doesn't exist
            await self.create_activity_trends_delta()

        try:
            return pl.read_parquet(delta_path)
        except Exception:
            return pl.DataFrame(
                {
                    "date": pl.Series([], dtype=pl.String),
                    "activity_type": pl.Series([], dtype=pl.String),
                    "activity_count": pl.Series([], dtype=pl.Int64),
                    "avg_response_time_ms": pl.Series([], dtype=pl.Float64),
                }
            )

    async def refresh_all_analytics_data(self) -> Dict[str, Any]:
        """Refresh all analytics Delta tables."""
        results = {}

        # Refresh user summary
        user_summary_result = await self.create_user_summary_delta()
        results["user_summary"] = user_summary_result

        # Refresh activity trends
        activity_trends_result = await self.create_activity_trends_delta()
        results["activity_trends"] = activity_trends_result

        return {"refresh_completed_at": datetime.utcnow().isoformat(), "results": results}
