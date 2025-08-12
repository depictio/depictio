"""
Analytics Data API endpoints - ETL and data serving for admin dashboard.
"""

from datetime import date
from typing import Any, Dict, Optional

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.analytics_endpoints.routes import verify_internal_api_key
from depictio.api.v1.services.analytics_data_service import AnalyticsDataService

router = APIRouter()


def get_analytics_data_service() -> AnalyticsDataService:
    """Dependency to get analytics data service."""
    return AnalyticsDataService()


@router.post("/etl/refresh")
async def refresh_analytics_etl(
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Trigger refresh of all analytics Delta tables.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        result = await analytics_data_service.refresh_all_analytics_data()
        return {"success": True, "message": "Analytics ETL refresh completed", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ETL refresh failed: {str(e)}")


@router.get("/etl/user-summary")
async def refresh_user_summary(
    days: int = Query(30, ge=1, le=365, description="Days of data to include"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Refresh user summary Delta table.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        result = await analytics_data_service.create_user_summary_delta(days)
        return {
            "success": True,
            "message": f"User summary Delta table refreshed for {days} days",
            "result": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"User summary refresh failed: {str(e)}")


@router.get("/dashboard/realtime-metrics")
async def get_dashboard_realtime_metrics(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get real-time metrics for admin dashboard.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        metrics = await analytics_data_service.get_realtime_metrics(
            start_date=start_date, end_date=end_date, user_type=user_type or "all", user_id=user_id
        )
        return {"success": True, "data": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get realtime metrics: {str(e)}")


@router.get("/dashboard/user-summary")
async def get_dashboard_user_summary(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get user summary data for dashboard charts.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        df = await analytics_data_service.load_user_summary_data(
            start_date=start_date, end_date=end_date, user_type=user_type or "all", user_id=user_id
        )

        # Convert to JSON-serializable format
        data = df.to_dicts() if df.height > 0 else []

        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get user summary: {str(e)}")


@router.get("/dashboard/activity-trends")
async def get_dashboard_activity_trends(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get activity trends data for dashboard charts.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        df = await analytics_data_service.load_activity_trends_data(
            start_date=start_date, end_date=end_date, user_type=user_type or "all", user_id=user_id
        )

        # Convert to JSON-serializable format
        data = df.to_dicts() if df.height > 0 else []

        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get activity trends: {str(e)}")


@router.get("/dashboard/top-users")
async def get_dashboard_top_users(
    limit: int = Query(10, ge=1, le=50, description="Number of top users to return"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get top users by activity for dashboard table.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        df = await analytics_data_service.load_user_summary_data(
            start_date=start_date, end_date=end_date, user_type=user_type or "all", user_id=user_id
        )

        if df.height == 0:
            return {"success": True, "data": [], "count": 0}

        # Get top users by total page views
        logger.debug(f"Top users - DataFrame info: shape={df.shape}, schema={df.schema}")
        logger.debug(f"Top users - DataFrame columns: {df.columns}")
        logger.debug(f"Top users - DataFrame dtypes: {df.dtypes}")
        logger.debug(f"Top users - Requested limit: {limit}")

        # Apply user type filtering
        filtered_df = df
        if user_type == "authenticated":
            filtered_df = df.filter(~pl.col("is_anonymous"))
        elif user_type == "anonymous":
            filtered_df = df.filter(pl.col("is_anonymous"))
        elif user_type == "admin":
            filtered_df = df.filter(pl.col("user_is_admin"))
        else:  # "all"
            filtered_df = df.filter(
                ~pl.col("is_anonymous")
            )  # Still exclude anonymous for top users

        top_users = filtered_df.sort("total_page_views", descending=True).head(limit)

        logger.debug(f"Top users - Filtered result shape: {top_users.shape}")
        data = top_users.to_dicts()
        logger.debug(f"Top users - Final data count: {len(data)}")

        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get top users: {str(e)}")


@router.get("/dashboard/user-types-distribution")
async def get_user_types_distribution(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get user types distribution for pie chart.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        df = await analytics_data_service.load_user_summary_data(
            start_date=start_date, end_date=end_date, user_type=user_type or "all", user_id=user_id
        )

        if df.height == 0:
            return {"success": True, "data": [{"user_type": "No Data", "count": 0}]}

        # Calculate user type distribution
        logger.debug(
            f"User types distribution - DataFrame info: shape={df.shape}, schema={df.schema}"
        )
        logger.debug(f"User types distribution - DataFrame columns: {df.columns}")
        logger.debug(f"User types distribution - DataFrame dtypes: {df.dtypes}")

        distribution = (
            df.group_by("is_anonymous")
            .agg(pl.count("user_id").alias("count"))
            .with_columns(
                [
                    pl.when(pl.col("is_anonymous"))
                    .then(pl.lit("Anonymous"))
                    .otherwise(pl.lit("Authenticated"))
                    .alias("user_type")
                ]
            )
            .select(["user_type", "count"])
        )

        logger.debug(f"User types distribution - Aggregation result shape: {distribution.shape}")
        data = distribution.to_dicts()
        logger.debug(f"User types distribution - Final data: {data}")

        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get user types distribution: {str(e)}"
        )


@router.get("/dashboard/daily-activity-chart")
async def get_daily_activity_chart_data(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get daily activity data for line chart.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        df = await analytics_data_service.load_activity_trends_data(
            start_date=start_date, end_date=end_date, user_type=user_type or "all", user_id=user_id
        )

        if df.height == 0:
            return {"success": True, "data": [], "count": 0}

        # Aggregate by date across activity types
        logger.debug(f"Daily activity chart - DataFrame info: shape={df.shape}, schema={df.schema}")
        logger.debug(f"Daily activity chart - DataFrame columns: {df.columns}")
        logger.debug(f"Daily activity chart - DataFrame dtypes: {df.dtypes}")

        daily_totals = (
            df.group_by("date").agg(pl.sum("activity_count").alias("total_activities")).sort("date")
        )

        logger.debug(f"Daily activity chart - Aggregation result shape: {daily_totals.shape}")
        data = daily_totals.to_dicts()
        logger.debug(f"Daily activity chart - Final data: {data}")

        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get daily activity data: {str(e)}")


@router.get("/dashboard/top-pages")
async def get_top_pages(
    limit: int = Query(10, ge=1, le=50, description="Number of top pages to return"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get top pages by activity for dashboard display.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        data = await analytics_data_service.get_top_pages(
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            user_type=user_type or "all",
            user_id=user_id,
        )
        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get top pages: {str(e)}")


@router.get("/dashboard/user-list")
async def get_user_list(
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get list of users for filter dropdown.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        users = await analytics_data_service.get_user_list()
        return {"success": True, "data": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get user list: {str(e)}")


@router.get("/dashboard/comprehensive-summary")
async def get_comprehensive_analytics_summary(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    user_type: Optional[str] = Query("all", description="User type filter"),
    user_id: Optional[str] = Query(None, description="Specific user ID filter"),
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get comprehensive analytics summary including period totals and detailed breakdowns.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        summary = await analytics_data_service.get_comprehensive_summary(
            start_date=start_date, end_date=end_date, user_type=user_type or "all", user_id=user_id
        )
        return {"success": True, "data": summary}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get comprehensive summary: {str(e)}"
        )


@router.get("/dashboard/users-active-today")
async def get_users_active_today(
    analytics_data_service: AnalyticsDataService = Depends(get_analytics_data_service),
    _: None = Depends(verify_internal_api_key),
) -> Dict[str, Any]:
    """
    Get count of users active in the last 24 hours.
    """
    if not settings.analytics.enabled:
        raise HTTPException(status_code=404, detail="Analytics not enabled")

    try:
        data = await analytics_data_service.get_users_active_today()
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get active users today: {str(e)}")
