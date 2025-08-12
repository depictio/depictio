"""
Analytics API endpoints.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from pymongo import DESCENDING

from depictio.api.v1.configs.config import settings
from depictio.api.v1.services.analytics_data_service import AnalyticsDataService
from depictio.api.v1.services.analytics_service import AnalyticsService
from depictio.models.models.analytics import (
    AnalyticsSummary,
    SessionSummary,
    UserActivity,
    UserSession,
)

router = APIRouter()


class ClientPageView(BaseModel):
    """Client-side page view tracking data."""

    page_path: str
    page_title: Optional[str] = None
    user_type: Optional[str] = None  # "anonymous", "temporary", "authenticated"
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    referrer: Optional[str] = None
    timestamp: Optional[datetime] = None


def get_analytics_service() -> AnalyticsService:
    """Dependency to get analytics service."""
    return AnalyticsService(
        session_timeout_minutes=settings.analytics.session_timeout_minutes,
        cleanup_days=settings.analytics.cleanup_days,
    )


def verify_internal_api_key(
    x_api_key: str = Header(
        ..., alias="X-Api-Key", description="Internal API key for authentication"
    ),
) -> None:
    """Dependency to verify internal API key for protected analytics endpoints."""
    if x_api_key != settings.auth.internal_api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )


@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    _: None = Depends(verify_internal_api_key),
) -> AnalyticsSummary:
    """
    Get analytics summary with key metrics.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    return await analytics_service.get_analytics_summary()


@router.get("/sessions/active", response_model=List[SessionSummary])
async def get_active_sessions(
    limit: int = Query(50, ge=1, le=200),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    _: None = Depends(verify_internal_api_key),
) -> List[SessionSummary]:
    """
    Get list of currently active sessions.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    return await analytics_service.get_active_sessions(limit=limit)


@router.get("/sessions", response_model=List[UserSession])
async def get_sessions(
    user_id: Optional[str] = Query(None),
    is_anonymous: Optional[bool] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    _: None = Depends(verify_internal_api_key),
) -> List[UserSession]:
    """
    Get user sessions with optional filtering.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    # Build query filters
    filters = []

    if user_id:
        filters.append(UserSession.user_id == user_id)

    if is_anonymous is not None:
        filters.append(UserSession.is_anonymous == is_anonymous)

    if start_date:
        filters.append(UserSession.start_time >= start_date)

    if end_date:
        filters.append(UserSession.start_time <= end_date)

    # Execute query
    query = UserSession.find(*filters) if filters else UserSession.find()
    sessions = (
        await query.sort([(UserSession.start_time, DESCENDING)]).skip(skip).limit(limit).to_list()
    )

    return sessions


@router.get("/activities", response_model=List[UserActivity])
async def get_activities(
    session_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    activity_type: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    _: None = Depends(verify_internal_api_key),
) -> List[UserActivity]:
    """
    Get user activities with optional filtering.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    # Build query filters
    filters = []

    if session_id:
        filters.append(UserActivity.session_id == session_id)

    if user_id:
        filters.append(UserActivity.user_id == user_id)

    if activity_type:
        filters.append(UserActivity.activity_type == activity_type)

    if start_date:
        filters.append(UserActivity.timestamp >= start_date)

    if end_date:
        filters.append(UserActivity.timestamp <= end_date)

    # Execute query
    query = UserActivity.find(*filters) if filters else UserActivity.find()
    activities = (
        await query.sort([(UserActivity.timestamp, DESCENDING)]).skip(skip).limit(limit).to_list()
    )

    return activities


@router.get("/sessions/{session_id}", response_model=UserSession)
async def get_session(session_id: str, _: None = Depends(verify_internal_api_key)) -> UserSession:
    """
    Get specific session by ID.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    session = await UserSession.find_one(UserSession.session_id == session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


@router.get("/sessions/{session_id}/activities", response_model=List[UserActivity])
async def get_session_activities(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    _: None = Depends(verify_internal_api_key),
) -> List[UserActivity]:
    """
    Get all activities for a specific session.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    # Check if session exists
    session = await UserSession.find_one(UserSession.session_id == session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get activities
    activities = (
        await UserActivity.find(UserActivity.session_id == session_id)
        .sort([(UserActivity.timestamp, DESCENDING)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    return activities


@router.delete("/sessions/{session_id}")
async def end_session(
    session_id: str,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    _: None = Depends(verify_internal_api_key),
) -> dict:
    """
    Manually end a session.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    session = await analytics_service.end_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or already ended")

    return {"message": "Session ended successfully", "session_id": session_id}


@router.post("/cleanup")
async def cleanup_old_data(
    days_to_keep: Optional[int] = Query(
        None, ge=1, description="Days of data to keep (overrides default)"
    ),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    _: None = Depends(verify_internal_api_key),
) -> dict:
    """
    Manually trigger cleanup of old analytics data.

    Args:
        days_to_keep: Optional override for how many days of data to keep
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    result = await analytics_service.cleanup_old_sessions(days_to_keep)
    return {
        "message": "Cleanup completed successfully",
        "days_kept": days_to_keep or settings.analytics.cleanup_days,
        "result": result,
    }


@router.get("/stats/users")
async def get_user_stats(
    days: int = Query(30, ge=1, le=365), _: None = Depends(verify_internal_api_key)
) -> dict:
    """
    Get user statistics for the specified period.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    start_date = datetime.utcnow() - timedelta(days=days)

    # Total unique users
    period_sessions = await UserSession.find(UserSession.start_time >= start_date).to_list()
    unique_user_ids = set(session.user_id for session in period_sessions)
    total_users = len(unique_user_ids)

    # Anonymous vs authenticated
    anonymous_sessions = await UserSession.find(
        UserSession.start_time >= start_date, UserSession.is_anonymous
    ).to_list()
    anonymous_user_ids = set(session.user_id for session in anonymous_sessions)
    anonymous_users = len(anonymous_user_ids)

    authenticated_users = total_users - anonymous_users

    # Sessions per day
    sessions_by_day = {}
    for i in range(days):
        day_start = (start_date + timedelta(days=i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)

        daily_sessions = await UserSession.find(
            UserSession.start_time >= day_start, UserSession.start_time < day_end
        ).count()

        sessions_by_day[day_start.strftime("%Y-%m-%d")] = daily_sessions

    return {
        "period_days": days,
        "total_users": total_users,
        "anonymous_users": anonymous_users,
        "authenticated_users": authenticated_users,
        "sessions_by_day": sessions_by_day,
    }


@router.get("/stats/activities")
async def get_activity_stats(
    days: int = Query(7, ge=1, le=90), _: None = Depends(verify_internal_api_key)
) -> dict:
    """
    Get activity statistics for the specified period.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    start_date = datetime.utcnow() - timedelta(days=days)

    # Get all activities in period
    activities = await UserActivity.find(UserActivity.timestamp >= start_date).to_list()

    # Count by type
    activity_counts = {}
    for activity in activities:
        activity_counts[activity.activity_type] = activity_counts.get(activity.activity_type, 0) + 1

    # Top pages
    page_views = [a for a in activities if a.activity_type == "page_view"]
    page_counts = {}
    for activity in page_views:
        page_counts[activity.path] = page_counts.get(activity.path, 0) + 1

    top_pages = [
        {"path": path, "views": count}
        for path, count in sorted(page_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    ]

    # Average response time
    api_calls = [a for a in activities if a.activity_type == "api_call"]
    avg_response_time = 0
    if api_calls:
        avg_response_time = sum(a.response_time_ms for a in api_calls) / len(api_calls)

    return {
        "period_days": days,
        "activity_counts": activity_counts,
        "total_activities": len(activities),
        "top_pages": top_pages,
        "avg_response_time_ms": avg_response_time,
    }


@router.post("/track/pageview")
async def track_client_pageview(
    pageview: ClientPageView,
    request: Request,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> dict:
    """
    Track a client-side page view from Dash frontend.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        # Get or create session
        # Don't use random session_id from client as user_id - let the service determine proper user_id
        user_id = (
            pageview.user_id
            if pageview.user_id and not pageview.user_id.startswith("anon_")
            else None
        )
        session = await analytics_service.get_or_create_session(request, user_id)

        # Create a mock request object for the page view

        # Log as page view activity
        await analytics_service.log_activity(
            session=session,
            request=request,  # Use the API request but with modified path
            status_code=200,  # Assume successful page view
            response_time_ms=0,  # Client-side navigation is instant
            project_id=None,  # TODO: Extract from page_path if needed
            dashboard_id=None,  # TODO: Extract from page_path if needed
        )

        # Update the activity with correct page info
        latest_activity = (
            await UserActivity.find(UserActivity.session_id == session.session_id)
            .sort([(UserActivity.timestamp, DESCENDING)])
            .limit(1)
            .first_or_none()
        )

        if latest_activity:
            latest_activity.path = pageview.page_path
            latest_activity.activity_type = "page_view"
            if pageview.page_title:
                # Store page title in a custom field if needed
                pass
            await latest_activity.save()

        return {
            "success": True,
            "session_id": session.session_id,
            "user_id": session.user_id,
            "message": "Page view tracked successfully",
        }

    except Exception as e:
        # Don't let analytics errors break the frontend
        print(f"Client analytics error: {e}")
        return {"success": False, "error": str(e)}


def get_analytics_data_service() -> AnalyticsDataService:
    """Dependency to get analytics data service."""
    return AnalyticsDataService()


@router.get("/unique-connections")
async def get_unique_connections_analytics(
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format"),
    data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
):
    """
    Get analytics for unique IP addresses and connections.

    Returns information about unique connections, IP-to-user mapping,
    and connection patterns for identifying unique visitors.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        # Parse dates if provided
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD"
                )

        if end_date:
            try:
                parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        # Get unique connections analytics
        result = await data_service.get_unique_connections_analytics(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in unique connections analytics: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get unique connections analytics: {str(e)}"
        )


@router.post("/admin/consolidate-sessions")
async def consolidate_duplicate_sessions(
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    _: None = Depends(verify_internal_api_key),
):
    """
    Consolidate duplicate sessions from the same IP address.

    This endpoint fixes legacy data where multiple sessions exist per IP
    due to different user agents creating separate anonymous user IDs.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        result = await analytics_service.consolidate_duplicate_sessions()

        if result["success"]:
            return {
                "success": True,
                "message": "Session consolidation completed",
                "details": {
                    "consolidated_ips": result["consolidated_ips"],
                    "removed_sessions": result["removed_sessions"],
                    "total_duplicate_ips": result["total_duplicate_ips"],
                },
            }
        else:
            raise HTTPException(status_code=500, detail=f"Consolidation failed: {result['error']}")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in session consolidation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to consolidate sessions: {str(e)}")


@router.delete("/admin/cleanup-anonymous-sessions")
async def cleanup_anonymous_sessions(
    _: None = Depends(verify_internal_api_key),
):
    """
    Clean up anonymous sessions when unauthenticated mode is disabled.

    This removes all anonymous sessions and their associated activities
    since anonymous sessions shouldn't exist when unauthenticated mode is disabled.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    # Only allow cleanup when unauthenticated mode is disabled
    if settings.auth.unauthenticated_mode:
        raise HTTPException(
            status_code=400,
            detail="Cannot cleanup anonymous sessions when unauthenticated mode is enabled",
        )

    try:
        # Delete anonymous sessions and their activities
        anonymous_sessions = await UserSession.find(UserSession.is_anonymous).to_list()
        session_ids = [session.session_id for session in anonymous_sessions]

        # Delete activities first (foreign key constraint)
        deleted_activities = 0
        if session_ids:
            activities_result = await UserActivity.find(
                {"session_id": {"$in": session_ids}}
            ).delete()
            deleted_activities = getattr(activities_result, "deleted_count", 0)

        # Delete anonymous sessions
        sessions_result = await UserSession.find(UserSession.is_anonymous).delete()
        deleted_sessions = getattr(sessions_result, "deleted_count", 0)

        return {
            "success": True,
            "message": "Anonymous sessions cleanup completed",
            "details": {
                "deleted_sessions": deleted_sessions,
                "deleted_activities": deleted_activities,
                "reason": "Unauthenticated mode is disabled - anonymous sessions not allowed",
            },
        }

    except Exception as e:
        print(f"Error in anonymous session cleanup: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cleanup anonymous sessions: {str(e)}"
        )
