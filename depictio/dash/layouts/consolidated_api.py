"""
Consolidated API callbacks to reduce redundant API calls across components.

This module provides centralized user data management and API call optimization
to eliminate the 20+ redundant api_call_fetch_user_from_token() calls throughout the app.
"""

import time
from typing import Any, Dict, Optional

import httpx
from dash import Input, Output, State, callback_context, no_update

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger


def register_consolidated_api_callbacks(app):
    """Register consolidated API callbacks to reduce redundant requests."""

    logger.info("🔧 CONSOLIDATED API: Registering async callback for non-blocking HTTP requests...")

    # Use async callback for non-blocking API requests (better performance than background)
    @app.callback(
        [
            Output("user-cache-store", "data"),
            Output("server-status-cache", "data"),
            Output("project-cache-store", "data"),
        ],
        [
            Input("local-store", "data"),
            # Removed Input("url", "pathname") to reduce callback triggers
            # Cache updates should only happen when token data changes, not on navigation
        ],
        [
            State("user-cache-store", "data"),
            State("server-status-cache", "data"),
            State("project-cache-store", "data"),
            State(
                "url", "pathname"
            ),  # Moved pathname to State so we can access it but not trigger on it
        ],
        prevent_initial_call=False,
        # background=True,  # Disabled - using async instead for better performance
    )
    async def consolidated_user_server_and_project_data(
        local_store, cached_user, cached_server, cached_project, pathname
    ):
        """
        Async callback that fetches user data, server status, and project data with non-blocking HTTP requests.

        This replaces 20+ individual api_call_fetch_user_from_token() calls across the app
        and eliminates redundant project fetching in design_draggable() with cached requests.
        Uses async HTTP clients so UI shows no "Loading..." and stays responsive.
        """

        logger.info(
            f"🚀 CONSOLIDATED CALLBACK TRIGGERED!!! - pathname: {pathname}, local_store: {bool(local_store)}"
        )
        logger.info(
            f"🚀 CONSOLIDATED CALLBACK: local_store keys: {list(local_store.keys()) if local_store and isinstance(local_store, dict) else 'None or not dict'}"
        )

        ctx = callback_context
        if ctx.triggered:
            logger.info(f"🔧 CONSOLIDATED CALLBACK TRIGGER: {ctx.triggered[0]['prop_id']}")
            logger.info(
                f"🔧 CONSOLIDATED CALLBACK: All triggers: {[t['prop_id'] for t in ctx.triggered]}"
            )

            # If triggered multiple times for same token, skip subsequent calls
            trigger_id = ctx.triggered[0]["prop_id"]
            if trigger_id != "local-store.data":
                logger.info(f"🔧 CONSOLIDATED CALLBACK: Unexpected trigger {trigger_id}, skipping")
                return cached_user, cached_server, cached_project

        # Skip auth page
        if pathname == "/auth":
            logger.info("🔧 CONSOLIDATED CALLBACK: Skipping auth page")
            return no_update, no_update, no_update

        # Check if we have a valid token
        if not local_store or not local_store.get("access_token"):
            logger.info("🔧 CONSOLIDATED CALLBACK: No token found, returning None")
            return None, None, None

        access_token = local_store["access_token"]
        current_time = time.time()

        # Determine what needs updating
        update_user = False
        update_server = False

        # Check if user data needs updating (5 minute cache)
        if not cached_user or (current_time - cached_user.get("timestamp", 0)) > 300:
            update_user = True

        # Check if server data needs updating (2 minute cache)
        if not cached_server or (current_time - cached_server.get("timestamp", 0)) > 120:
            update_server = True

        user_cache_age = (
            current_time - cached_user.get("timestamp", 0) if cached_user else float("inf")
        )
        server_cache_age = (
            current_time - cached_server.get("timestamp", 0) if cached_server else float("inf")
        )
        logger.info(
            f"🔧 CONSOLIDATED DEBUG: User cache age: {user_cache_age}s, server cache age: {server_cache_age}s"
        )

        # Check if project data needs updating (dashboard-specific, 10 minute cache)
        update_project = False
        dashboard_id = None
        if "/dashboard/" in pathname:
            dashboard_id = pathname.split("/")[-1]
            cache_key = f"project_{dashboard_id}"

            if not cached_project or cached_project.get("cache_key") != cache_key:
                update_project = True
            elif (current_time - cached_project.get("timestamp", 0)) > 600:  # 10 min cache
                update_project = True

        # For local-store triggers, check if token actually changed to prevent unnecessary updates
        if ctx.triggered and ctx.triggered[0]["prop_id"] == "local-store.data":
            # Get current token from local store
            current_token = local_store.get("access_token") if local_store else None

            # Check if we have a previous token stored in user cache metadata
            previous_token = cached_user.get("access_token") if cached_user else None

            logger.info(
                f"🔧 CONSOLIDATED DEBUG: Current token: {current_token[:10] if current_token else None}..."
            )
            logger.info(
                f"🔧 CONSOLIDATED DEBUG: Previous token: {previous_token[:10] if previous_token else None}..."
            )

            # If tokens are the same and cache is still valid, skip updates
            if current_token == previous_token:
                logger.info("🔄 Token unchanged, using cache-based updates only")
            else:
                logger.info("🔄 Token changed, forcing data refresh")
                update_user = True
                update_server = True

        # If nothing needs updating, return cached data
        if not update_user and not update_server and not update_project:
            logger.info("🔧 CONSOLIDATED CALLBACK: Using cached data, no updates needed")
            logger.info(
                f"🔧 DEBUG: Cache ages - user: {(current_time - cached_user.get('timestamp', 0)) if cached_user else 'None'}, server: {server_cache_age if cached_server else 'None'}"
            )
            return cached_user, cached_server, cached_project

        logger.info(
            f"🔄 Consolidated API: Updating user={update_user}, server={update_server}, project={update_project}"
        )
        if update_project:
            logger.info(
                f"🔄 Consolidated API: Will fetch project data for dashboard {dashboard_id}"
            )
        logger.info("🔧 CONSOLIDATED CALLBACK: About to start async tasks")
        logger.info("🚀 ASYNC MODE ENABLED: Using httpx.AsyncClient for non-blocking I/O")

        async def fetch_user_data(token):
            """Fetch user data with async HTTP client."""
            try:
                logger.info("🔄 Consolidated API: Fetching user data (async)")

                # Use httpx.AsyncClient for async HTTP requests
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(
                        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
                        params={"token": token},
                        headers={"api-key": settings.auth.internal_api_key},
                    )

                    if response.status_code == 200:
                        user_data = response.json()
                        from depictio.models.models.users import UserContext

                        current_user = UserContext(
                            id=user_data["id"],
                            email=user_data["email"],
                            is_admin=user_data.get("is_admin", False),
                            is_anonymous=user_data.get("is_anonymous", False),
                        )

                        return {
                            "user": {
                                "id": str(current_user.id),
                                "email": current_user.email,
                                "name": getattr(
                                    current_user, "name", current_user.email.split("@")[0]
                                ),
                                "is_admin": current_user.is_admin,
                                "is_anonymous": getattr(current_user, "is_anonymous", False),
                            },
                            "access_token": access_token,  # Store token for comparison
                            "timestamp": current_time,
                        }
                    else:
                        logger.warning(f"User fetch failed: {response.status_code}")
                        return None

            except Exception as e:
                logger.error(f"❌ Consolidated API: Failed to fetch user data: {e}")
                return None

        async def fetch_server_status(token):
            """Fetch server status with async HTTP client."""
            try:
                logger.info("🔄 Consolidated API: Fetching server status (async)")

                async with httpx.AsyncClient(timeout=3) as client:
                    response = await client.get(
                        f"{API_BASE_URL}/depictio/api/v1/utils/status",
                        headers={"Authorization": f"Bearer {token}"},
                    )

                    if response.status_code == 200:
                        server_data = response.json()
                        return {
                            "status": server_data.get("status", "offline"),
                            "version": server_data.get("version", "unknown"),
                            "timestamp": current_time,
                        }
                    else:
                        return {
                            "status": "offline",
                            "version": "unknown",
                            "timestamp": current_time,
                        }

            except Exception as e:
                logger.error(f"❌ Consolidated API: Failed to fetch server status: {e}")
                return {
                    "status": "offline",
                    "version": "unknown",
                    "timestamp": current_time,
                }

        async def fetch_project_data(token, dashboard_id):
            """Fetch project data with async HTTP client."""
            try:
                logger.info("🔄 Consolidated API: Fetching project data (async)")

                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(
                        f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{dashboard_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    )

                    if response.status_code == 200:
                        project_data = response.json()
                        return {
                            "project": project_data,
                            "cache_key": f"project_{dashboard_id}",
                            "timestamp": current_time,
                        }
                    else:
                        logger.warning(f"Project fetch failed with status {response.status_code}")
                        return None

            except Exception as e:
                logger.error(f"❌ Consolidated API: Failed to fetch project data: {e}")
                return None

        # Execute async tasks with await
        new_user_data = cached_user
        new_server_data = cached_server
        new_project_data = cached_project

        if update_user:
            try:
                user_result = await fetch_user_data(access_token)
                if user_result:
                    new_user_data = user_result
                    logger.info(
                        f"✅ Consolidated API: User data cached for {user_result['user']['email']}"
                    )
            except Exception as e:
                logger.error(f"❌ User fetch exception: {e}")

        if update_server:
            try:
                server_result = await fetch_server_status(access_token)
                if server_result:
                    new_server_data = server_result
                    logger.info(
                        f"✅ Consolidated API: Server status cached - {server_result['status']}"
                    )
            except Exception as e:
                logger.error(f"❌ Server fetch exception: {e}")

        if update_project and dashboard_id:
            try:
                project_result = await fetch_project_data(access_token, dashboard_id)
                if project_result:
                    new_project_data = project_result
                    logger.info(f"✅ Consolidated API: Project data cached - {dashboard_id}")
            except Exception as e:
                logger.error(f"❌ Project fetch exception: {e}")

        if update_user or update_server or update_project:
            logger.info(
                f"🔧 CONSOLIDATED CALLBACK: Returning updated data - user: {bool(new_user_data)}, server: {bool(new_server_data)}, project: {bool(new_project_data)}"
            )
            return new_user_data, new_server_data, new_project_data

        logger.info("🔧 CONSOLIDATED CALLBACK: No tasks executed, returning cached data")
        return cached_user, cached_server, cached_project

    logger.info("✅ CONSOLIDATED API: Callback registered successfully!")


def get_cached_user_data(user_cache: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Helper function to extract user data from cache.

    Args:
        user_cache: The cached user data from user-cache-store

    Returns:
        User data dict or None if not available/expired
    """
    if not user_cache or not user_cache.get("user"):
        return None

    # Check if cache is still valid (5 minute timeout)
    current_time = time.time()
    if (current_time - user_cache.get("timestamp", 0)) > 300:
        return None

    return user_cache["user"]


def get_cached_server_status(server_cache: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Helper function to extract server status from cache.

    Args:
        server_cache: The cached server data from server-status-cache

    Returns:
        Server status dict or None if not available/expired
    """
    logger.info(f"🔧 get_cached_server_status: server_cache = {server_cache}")

    if not server_cache:
        logger.info("🔧 get_cached_server_status: No server_cache provided")
        return None

    # Check if cache is still valid (2 minute timeout)
    current_time = time.time()
    cache_timestamp = server_cache.get("timestamp", 0)
    cache_age = current_time - cache_timestamp
    logger.info(
        f"🔧 get_cached_server_status: cache_age = {cache_age}s, timestamp = {cache_timestamp}"
    )

    if cache_age > 120:
        logger.info(f"🔧 get_cached_server_status: Cache expired (age: {cache_age}s > 120s)")
        return None

    result = {
        "status": server_cache.get("status", "offline"),
        "version": server_cache.get("version", "unknown"),
    }
    logger.info(f"🔧 get_cached_server_status: returning {result}")
    return result
