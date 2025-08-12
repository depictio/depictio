"""
Analytics middleware for tracking user requests and sessions.
"""

import time
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from depictio.api.v1.configs.config import settings
from depictio.api.v1.services.analytics_service import AnalyticsService


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track user sessions and activities.
    """

    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        self.analytics_service = AnalyticsService(
            session_timeout_minutes=getattr(settings.analytics, "session_timeout_minutes", 30),
            cleanup_days=getattr(settings.analytics, "cleanup_days", 90),
        )

    async def dispatch(self, request: Request, call_next):
        # Skip analytics for health checks and internal endpoints
        if not self.enabled or self.should_skip_path(request.url.path):
            return await call_next(request)

        # Record start time
        start_time = time.time()

        # Process the request first
        response = await call_next(request)

        try:
            # Get or create user session
            user_id = await self.extract_user_id(request)

            # Don't create anonymous sessions if unauthenticated mode is disabled
            if not user_id and not settings.auth.unauthenticated_mode:
                # Skip analytics for unauthenticated requests when unauthenticated mode is disabled
                return response

            session = await self.analytics_service.get_or_create_session(request, user_id)

            # Store session in request state for other handlers
            request.state.analytics_session = session

            # Calculate response time
            response_time_ms = (time.time() - start_time) * 1000

            # Log the activity
            await self.analytics_service.log_activity(
                session=session,
                request=request,
                status_code=response.status_code,
                response_time_ms=response_time_ms,
                project_id=await self.extract_project_id(request),
                dashboard_id=await self.extract_dashboard_id(request),
            )

        except Exception as e:
            # Don't let analytics errors break the application
            print(f"Analytics middleware error: {e}")

        return response

    def should_skip_path(self, path: str) -> bool:
        """
        Determine if we should skip analytics for this path.
        """
        skip_paths = [
            "/health",
            "/metrics",
            "/favicon.ico",
            "/robots.txt",
            "/_dash-",  # Dash internal endpoints
            "/depictio/api/v1/analytics",  # Skip analytics endpoints to avoid recursion
            "/depictio/api/v1/analytics-data",  # Skip analytics data endpoints
            "/depictio/api/v1/auth/check_token_validity",  # Skip frequent auth checks
            "/depictio/api/v1/auth/purge_expired_tokens",  # Skip cleanup operations
            "/depictio/api/v1/utils/status",  # Skip status checks
        ]

        # Skip frequent internal API calls that aren't user-initiated
        frequent_patterns = [
            "/depictio/api/v1/deltatables/get/",  # Data fetching
            "/depictio/api/v1/projects/get/from_id",  # Project lookups
            "/depictio/api/v1/auth/fetch_user/from_token",  # User validation
            "/depictio/api/v1/auth/me",  # User info requests
            "/depictio/api/v1/auth/list",  # Auth token listing
            "/depictio/api/v1/dashboards/get/",  # Dashboard data
        ]

        for skip_path in skip_paths:
            if path.startswith(skip_path):
                return True

        for pattern in frequent_patterns:
            if path.startswith(pattern):
                return True

        return False

    async def extract_user_id(self, request: Request) -> Optional[str]:
        """
        Extract user ID from request (JWT token, session, etc.).
        """
        try:
            # Try to get user from JWT token
            authorization = request.headers.get("Authorization")
            if authorization and authorization.startswith("Bearer "):
                # Use the analytics service method to get user ID from token
                user_id = await self.analytics_service.extract_user_id_from_token(request)
                if user_id:
                    return user_id

            # Try to get user from session/cookies
            # TODO: Implement session-based user extraction

            return None  # Will create anonymous user ID

        except Exception:
            return None

    async def extract_project_id(self, request: Request) -> Optional[str]:
        """
        Extract project ID from request path or query parameters.
        """
        try:
            # Check query parameters
            project_id = request.query_params.get("project_id")
            if project_id:
                return project_id

            # Check path parameters (e.g., /api/v1/projects/{project_id})
            path_parts = request.url.path.split("/")
            if "projects" in path_parts:
                project_index = path_parts.index("projects")
                if project_index + 1 < len(path_parts):
                    return path_parts[project_index + 1]

            return None

        except Exception:
            return None

    async def extract_dashboard_id(self, request: Request) -> Optional[str]:
        """
        Extract dashboard ID from request.
        """
        try:
            # Check query parameters
            dashboard_id = request.query_params.get("dashboard_id")
            if dashboard_id:
                return dashboard_id

            # Check path for dashboard references
            path_parts = request.url.path.split("/")
            if "dashboards" in path_parts:
                dashboard_index = path_parts.index("dashboards")
                if dashboard_index + 1 < len(path_parts):
                    return path_parts[dashboard_index + 1]

            return None

        except Exception:
            return None
