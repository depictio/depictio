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
from depictio.dash.api_calls import api_call_fetch_user_from_token


def register_consolidated_api_callbacks(app):
    """Register consolidated API callbacks to reduce redundant requests."""

    @app.callback(
        [
            Output("user-cache-store", "data"),
            Output("server-status-cache", "data"),
        ],
        [
            Input("local-store", "data"),
            Input("url", "pathname"),
        ],
        State("user-cache-store", "data"),
        State("server-status-cache", "data"),
        prevent_initial_call=False,
    )
    def consolidated_user_and_server_data(local_store, pathname, cached_user, cached_server):
        """
        Consolidated callback that fetches user data and server status in a single update.

        This replaces 20+ individual api_call_fetch_user_from_token() calls across the app
        with a single cached request that all components can use.
        """
        ctx = callback_context

        # Skip auth page
        if pathname == "/auth":
            return no_update, no_update

        # Check if we have a valid token
        if not local_store or not local_store.get("access_token"):
            return None, None

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

        # If triggered by local-store change, always update user
        if ctx.triggered and ctx.triggered[0]["prop_id"] == "local-store.data":
            update_user = True

        # Fetch user data if needed
        new_user_data = cached_user
        if update_user:
            try:
                logger.info("🔄 Consolidated API: Fetching user data")
                current_user = api_call_fetch_user_from_token(access_token)
                if current_user:
                    new_user_data = {
                        "user": {
                            "id": str(current_user.id),
                            "email": current_user.email,
                            "is_admin": current_user.is_admin,
                            "is_anonymous": getattr(current_user, "is_anonymous", False),
                        },
                        "timestamp": current_time,
                    }
                    logger.info(f"✅ Consolidated API: User data cached for {current_user.email}")
                else:
                    new_user_data = None
            except Exception as e:
                logger.error(f"❌ Consolidated API: Failed to fetch user data: {e}")
                new_user_data = None

        # Fetch server status if needed
        new_server_data = cached_server
        if update_server:
            try:
                logger.info("🔄 Consolidated API: Fetching server status")
                response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/utils/status",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=settings.performance.api_request_timeout,
                )

                if response.status_code == 200:
                    server_data = response.json()
                    new_server_data = {
                        "status": server_data.get("status", "offline"),
                        "version": server_data.get("version", "unknown"),
                        "timestamp": current_time,
                    }
                    logger.info(
                        f"✅ Consolidated API: Server status cached - {server_data.get('status', 'offline')}"
                    )
                else:
                    new_server_data = {
                        "status": "offline",
                        "version": "unknown",
                        "timestamp": current_time,
                    }
            except Exception as e:
                logger.error(f"❌ Consolidated API: Failed to fetch server status: {e}")
                new_server_data = {
                    "status": "offline",
                    "version": "unknown",
                    "timestamp": current_time,
                }

        return new_user_data, new_server_data


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
