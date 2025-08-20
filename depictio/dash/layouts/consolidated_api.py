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
        ],
        [
            Input("local-store", "data"),
            Input("url", "pathname"),
        ],
        State("user-cache-store", "data"),
        State("server-status-cache", "data"),
        prevent_initial_call=False,
    )
    async def consolidated_user_and_server_data(local_store, pathname, cached_user, cached_server):
        """
        Async background callback that fetches user data and server status concurrently.

        This replaces 20+ individual api_call_fetch_user_from_token() calls across the app
        with a single cached request that all components can use.
        """
        import asyncio

        logger.info(
            f"🚀 CONSOLIDATED CALLBACK TRIGGERED!!! - pathname: {pathname}, local_store: {bool(local_store)}"
        )
        logger.info(
            f"🚀 CONSOLIDATED CALLBACK: local_store keys: {list(local_store.keys()) if local_store and isinstance(local_store, dict) else 'None or not dict'}"
        )

        ctx = callback_context
        if ctx.triggered:
            logger.info(f"🔧 CONSOLIDATED CALLBACK TRIGGER: {ctx.triggered[0]['prop_id']}")

        # Skip auth page
        if pathname == "/auth":
            logger.info("🔧 CONSOLIDATED CALLBACK: Skipping auth page")
            return no_update, no_update

        # Check if we have a valid token
        if not local_store or not local_store.get("access_token"):
            logger.info("🔧 CONSOLIDATED CALLBACK: No token found, returning None")
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

        # If nothing needs updating, return cached data
        if not update_user and not update_server:
            logger.info("🔧 CONSOLIDATED CALLBACK: Using cached data, no updates needed")
            return cached_user, cached_server

        logger.info(f"🔄 Consolidated API: Updating user={update_user}, server={update_server}")
        logger.info("🔧 CONSOLIDATED CALLBACK: About to start async tasks")

        async def fetch_user_data(token):
            """Fetch user data with optimized timeout."""
            try:
                logger.info("🔄 Consolidated API: Fetching user data (async)")

                # Use httpx.AsyncClient for proper async HTTP
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
                            "timestamp": current_time,
                        }
                    else:
                        logger.warning(f"User fetch failed: {response.status_code}")
                        return None

            except Exception as e:
                logger.error(f"❌ Consolidated API: Failed to fetch user data: {e}")
                return None

        async def fetch_server_status(token):
            """Fetch server status with optimized timeout."""
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

        # Execute tasks concurrently based on what needs updating
        tasks = []
        if update_user:
            tasks.append(fetch_user_data(access_token))
        if update_server:
            tasks.append(fetch_server_status(access_token))

        if tasks:
            # Run concurrent async requests
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            result_idx = 0
            new_user_data = cached_user
            new_server_data = cached_server

            if update_user:
                user_result = results[result_idx]
                if not isinstance(user_result, Exception) and user_result:
                    new_user_data = user_result
                    logger.info(
                        f"✅ Consolidated API: User data cached for {user_result['user']['email']}"
                    )
                elif isinstance(user_result, Exception):
                    logger.error(f"❌ User fetch exception: {user_result}")
                result_idx += 1

            if update_server:
                server_result = results[result_idx]
                if not isinstance(server_result, Exception):
                    new_server_data = server_result
                    logger.info(
                        f"✅ Consolidated API: Server status cached - {server_result['status']}"
                    )
                elif isinstance(server_result, Exception):
                    logger.error(f"❌ Server fetch exception: {server_result}")

            logger.info(
                f"🔧 CONSOLIDATED CALLBACK: Returning updated data - user: {bool(new_user_data)}, server: {bool(new_server_data)}"
            )
            return new_user_data, new_server_data

        logger.info("🔧 CONSOLIDATED CALLBACK: No tasks executed, returning cached data")
        return cached_user, cached_server

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
