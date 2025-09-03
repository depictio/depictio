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

    logger.info("🔧 CONSOLIDATED API: Registering async background callback...")

    # TEMPORARY: Use regular async callback instead of background callback
    # The background callback manager has an issue - this is a workaround
    @app.callback(
        [
            Output("user-cache-store", "data"),
            Output("server-status-cache", "data"),
            Output("project-cache-store", "data"),
        ],
        [
            Input("local-store", "data"),
            Input("url", "pathname"),
        ],
        State("user-cache-store", "data"),
        State("server-status-cache", "data"),
        State("project-cache-store", "data"),
        prevent_initial_call=False,
    )
    def consolidated_user_server_and_project_data(
        local_store, pathname, cached_user, cached_server, cached_project
    ):
        """
        Synchronous callback that fetches user data, server status, and project data (async functionality disabled).

        This replaces 20+ individual api_call_fetch_user_from_token() calls across the app
        and eliminates redundant project fetching in design_draggable() with cached requests.
        """

        # logger.info(
        #     f"🚀 CONSOLIDATED CALLBACK TRIGGERED!!! - pathname: {pathname}, local_store: {bool(local_store)}"
        # )
        # logger.info(
        #     f"🚀 CONSOLIDATED CALLBACK: local_store keys: {list(local_store.keys()) if local_store and isinstance(local_store, dict) else 'None or not dict'}"
        # )

        ctx = callback_context
        # if ctx.triggered:
        #     logger.info(f"🔧 CONSOLIDATED CALLBACK TRIGGER: {ctx.triggered[0]['prop_id']}")

        # Skip auth page
        if pathname == "/auth":
            # logger.info("🔧 CONSOLIDATED CALLBACK: Skipping auth page")
            return no_update, no_update, no_update

        # Check if we have a valid token
        if not local_store or not local_store.get("access_token"):
            # logger.info("🔧 CONSOLIDATED CALLBACK: No token found, returning None")
            return None, None, None

        access_token = local_store["access_token"]
        current_time = time.time()

        # Determine what needs updating
        update_user = False
        update_server = False

        # Check if user data needs updating (5 minute cache)
        if not cached_user or (current_time - cached_user.get("timestamp", 0)) > 300:
            update_user = True

        # Check if server status needs updating (2 minute cache)
        if not cached_server or (current_time - cached_server.get("timestamp", 0)) > 120:
            update_server = True

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

        # If triggered by local-store change, always update user
        if ctx.triggered and ctx.triggered[0]["prop_id"] == "local-store.data":
            update_user = True

        # If nothing needs updating, return cached data
        if not update_user and not update_server and not update_project:
            # logger.info("🔧 CONSOLIDATED CALLBACK: Using cached data, no updates needed")
            return cached_user, cached_server, cached_project

        # logger.info(
        #     f"🔄 Consolidated API: Updating user={update_user}, server={update_server}, project={update_project}"
        # )
        # logger.info("🔧 CONSOLIDATED CALLBACK: About to start sync tasks")

        def fetch_user_data(token):
            """Fetch user data with sync timeout (async disabled)."""
            try:
                # logger.info("🔄 Consolidated API: Fetching user data (sync)")

                # Use httpx.Client for sync HTTP
                with httpx.Client(timeout=5) as client:
                    response = client.get(
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
                            "timestamp": current_time,
                        }
                    else:
                        logger.warning(f"User fetch failed: {response.status_code}")
                        return None

            except Exception as e:
                logger.error(f"❌ Consolidated API: Failed to fetch user data: {e}")
                return None

        def fetch_server_status(token):
            """Fetch server status with sync timeout (async disabled)."""
            try:
                logger.info("🔄 Consolidated API: Fetching server status (sync)")

                with httpx.Client(timeout=3) as client:
                    response = client.get(
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

        def fetch_project_data(token, dashboard_id):
            """Fetch project data with sync timeout."""
            try:
                logger.info("🔄 Consolidated API: Fetching project data (sync)")

                with httpx.Client(timeout=5) as client:
                    response = client.get(
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

        # Execute tasks sequentially based on what needs updating (async disabled)
        new_user_data = cached_user
        new_server_data = cached_server
        new_project_data = cached_project

        if update_user:
            try:
                user_result = fetch_user_data(access_token)
                if user_result:
                    new_user_data = user_result
                    logger.info(
                        f"✅ Consolidated API: User data cached for {user_result['user']['email']}"
                    )
            except Exception as e:
                logger.error(f"❌ User fetch exception: {e}")

        if update_server:
            try:
                server_result = fetch_server_status(access_token)
                if server_result:
                    new_server_data = server_result
                    logger.info(
                        f"✅ Consolidated API: Server status cached - {server_result['status']}"
                    )
            except Exception as e:
                logger.error(f"❌ Server fetch exception: {e}")

        if update_project and dashboard_id:
            try:
                project_result = fetch_project_data(access_token, dashboard_id)
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
    if not server_cache:
        return None

    # Check if cache is still valid (2 minute timeout)
    current_time = time.time()
    if (current_time - server_cache.get("timestamp", 0)) > 120:
        return None

    return {
        "status": server_cache.get("status", "offline"),
        "version": server_cache.get("version", "unknown"),
    }
