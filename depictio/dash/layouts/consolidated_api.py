"""
Consolidated API Caching Layer

This module provides centralized API caching callbacks for the Depictio dashboard application,
eliminating redundant HTTP requests and improving performance through browser session storage.

Key Features:
- Async non-blocking HTTP requests using httpx.AsyncClient
- Browser session storage caching (persists across page navigation)
- Intelligent cache invalidation based on TTL and data changes
- Reduces 20+ redundant API calls per dashboard load

Managed dcc.Store Components:
1. server-status-cache (2 min TTL) - Server health and version info
2. project-metadata-store (10 min TTL) - Project data with MongoDB $lookup joins
3. dashboard-init-data (10 min TTL) - Dashboard metadata and component configurations

Cache Strategy:
- Server/project data fetched on authentication changes (local-store.data triggers)
- Dashboard metadata fetched on URL navigation (/dashboard/{id})
- Project metadata triggered by dashboard data changes (cascading cache population)
- Components read from caches to avoid individual API calls

Registered Apps:
- Dashboard Viewer App (pages/dashboard_viewer.py)
- Management App uses its own server-status-cache writer for consistency

Performance Impact:
- Eliminates redundant user/project fetches across components
- Non-blocking async HTTP keeps UI responsive
- Session storage survives page refreshes and app transitions
"""

import time

import httpx
from dash import Input, Output, State, no_update

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

# Cache TTL constants (in seconds)
DASHBOARD_CACHE_TTL = 600  # 10 minutes
PROJECT_CACHE_TTL = 600  # 10 minutes


def _is_cache_valid(
    cached_data: dict | None, cache_key_field: str, expected_key: str, ttl: int
) -> bool:
    """
    Check if cached data is still valid.

    Args:
        cached_data: Cached data dictionary with timestamp and cache key.
        cache_key_field: Field name containing the cache key (e.g., '_id').
        expected_key: Expected cache key value.
        ttl: Time-to-live in seconds.

    Returns:
        True if cache is valid (same key and within TTL), False otherwise.
    """
    if not cached_data:
        return False

    current_time = time.time()
    cache_timestamp = cached_data.get("timestamp", 0)
    cache_age = current_time - cache_timestamp

    # Navigate to nested field if needed (e.g., "dashboard._id" or "project._id")
    cached_key = cached_data
    for field in cache_key_field.split("."):
        if isinstance(cached_key, dict):
            cached_key = cached_key.get(field)
        else:
            cached_key = None
            break

    return str(cached_key) == str(expected_key) and cache_age < ttl


def _extract_dashboard_id(pathname: str) -> str | None:
    """
    Extract dashboard_id from URL pathname.

    Args:
        pathname: URL pathname (e.g., '/dashboard/abc123' or '/dashboard-edit/abc123').

    Returns:
        Dashboard ID string, or None if extraction fails.
    """
    if not pathname:
        return None

    try:
        if "/dashboard-edit/" in pathname:
            dashboard_id = pathname.split("/dashboard-edit/")[1].split("/")[0]
        elif "/dashboard/" in pathname:
            dashboard_id = pathname.split("/dashboard/")[1].split("/")[0]
        else:
            return None

        if not dashboard_id or dashboard_id in ("dashboard", "dashboard-edit"):
            return None
        return dashboard_id
    except (IndexError, ValueError):
        return None


def register_consolidated_api_callbacks(app):
    """Register consolidated API callbacks to reduce redundant requests."""

    # DISABLED: This callback was causing double updates to project-metadata-store during normal dashboard load.
    # The populate_project_metadata_from_dashboard callback (line 280) provides the same functionality with
    # better optimization (includes delta_locations via MongoDB $lookup).
    #
    # ISSUE: Both callbacks would fire during dashboard load:
    #   1. populate_project_metadata_from_dashboard (triggered by dashboard-init-data)
    #   2. consolidated_project_data (triggered by local-store)
    # This caused all consuming callbacks (cards, figures, interactive components) to re-render TWICE.
    #
    # SOLUTION: Keep only populate_project_metadata_from_dashboard which is specifically designed for
    # dashboard loads and includes more complete data. If token refresh scenarios need special handling,
    # that logic can be added to the remaining callback.
    #
    # # Use async callback for non-blocking API requests (better performance than background)
    # @app.callback(
    #     Output("project-metadata-store", "data"),
    #     [
    #         Input("local-store", "data"),
    #         # Removed Input("url", "pathname") to reduce callback triggers
    #         # Cache updates should only happen when token data changes, not on navigation
    #         # NOTE: Server status checks now handled by pure clientside callback (30s interval)
    #     ],
    #     [
    #         State("project-metadata-store", "data"),
    #         State(
    #             "url", "pathname"
    #         ),  # Moved pathname to State so we can access it but not trigger on it
    #     ],
    #     prevent_initial_call=False,
    #     # background=True,  # Disabled - using async instead for better performance
    # )
    # async def consolidated_project_data(local_store, cached_project, pathname):
    #     """
    #     Async callback that fetches project data with non-blocking HTTP requests.
    #
    #     Eliminates redundant project fetching across components with cached requests.
    #     Uses async HTTP clients so UI shows no "Loading..." and stays responsive.
    #
    #     NOTE: Server status is now handled entirely by clientside callback (sidebar.py)
    #     """
    #
    #         f"🚀 CONSOLIDATED CALLBACK TRIGGERED!!! - pathname: {pathname}, local_store: {bool(local_store)}"
    #     )
    #         f"🚀 CONSOLIDATED CALLBACK: local_store keys: {list(local_store.keys()) if local_store and isinstance(local_store, dict) else 'None or not dict'}"
    #     )
    #
    #     ctx = callback_context
    #     if ctx.triggered:
    #             f"🔧 CONSOLIDATED CALLBACK: All triggers: {[t['prop_id'] for t in ctx.triggered]}"
    #         )
    #
    #         # Only accept local-store changes (periodic status checks now clientside)
    #         trigger_id = ctx.triggered[0]["prop_id"]
    #         if trigger_id != "local-store.data":
    #             return cached_project
    #
    #     # Skip auth page
    #     if pathname == "/auth":
    #         return no_update
    #
    #     # Check if we have a valid token
    #     if not local_store or not local_store.get("access_token"):
    #         return None
    #
    #     access_token = local_store["access_token"]
    #     current_time = time.time()
    #
    #     # Check if project data needs updating (dashboard-specific, 10 minute cache)
    #     update_project = False
    #     dashboard_id = None
    #     if "/dashboard/" in pathname:
    #         dashboard_id = pathname.split("/")[-1]
    #         cache_key = f"project_{dashboard_id}"
    #
    #         if not cached_project or cached_project.get("cache_key") != cache_key:
    #             update_project = True
    #         elif (current_time - cached_project.get("timestamp", 0)) > 600:  # 10 min cache
    #             update_project = True
    #
    #     # If nothing needs updating, return cached data
    #     if not update_project:
    #         return cached_project
    #
    #     if update_project:
    #             f"🔄 Consolidated API: Will fetch project data for dashboard {dashboard_id}"
    #         )
    #
    #     async def fetch_project_data(token, dashboard_id):
    #         """Fetch project data with async HTTP client."""
    #         try:
    #
    #             async with httpx.AsyncClient(timeout=5) as client:
    #                 response = await client.get(
    #                     f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{dashboard_id}",
    #                     headers={"Authorization": f"Bearer {token}"},
    #                 )
    #
    #                 if response.status_code == 200:
    #                     project_data = response.json()
    #                     return {
    #                         "project": project_data,
    #                         "cache_key": f"project_{dashboard_id}",
    #                         "timestamp": current_time,
    #                     }
    #                 else:
    #                     return None
    #
    #         except Exception as e:
    #             return None
    #
    #     # Execute async tasks with await
    #     new_project_data = cached_project
    #
    #     if update_project and dashboard_id:
    #         try:
    #             project_result = await fetch_project_data(access_token, dashboard_id)
    #             if project_result:
    #                 new_project_data = project_result
    #         except Exception as e:
    #
    #     if update_project:
    #             f"🔧 CONSOLIDATED CALLBACK: Returning updated data - project: {bool(new_project_data)}"
    #         )
    #         return new_project_data
    #
    #     return cached_project

    # Dashboard initialization data callback (Cache 1: Dashboard metadata)
    @app.callback(
        Output("dashboard-init-data", "data"),
        [
            Input("url", "pathname"),
        ],
        [
            State("local-store", "data"),
            State("dashboard-init-data", "data"),
        ],
        prevent_initial_call=False,
    )
    async def populate_dashboard_init_data(pathname, local_store, cached_dashboard_data):
        """
        Populate dashboard-init-data store with dashboard metadata + component configs + permissions.

        Cache 1: Dashboard Metadata
        - Source: /dashboards/init/{dashboard_id} endpoint
        - Contains: Dashboard + stored_metadata (all components) + permissions
        - Session storage: Persists across page refreshes
        """
        dashboard_id = _extract_dashboard_id(pathname)
        if not dashboard_id:
            return no_update

        if not local_store or not local_store.get("access_token"):
            return no_update

        if _is_cache_valid(
            cached_dashboard_data, "dashboard._id", dashboard_id, DASHBOARD_CACHE_TTL
        ):
            cache_age = time.time() - cached_dashboard_data.get("timestamp", 0)
            logger.info(
                f"🔧 DASHBOARD-INIT: Using cached data for {dashboard_id} (age: {cache_age:.1f}s)"
            )
            return no_update

        access_token = local_store["access_token"]
        logger.debug(f"📡 DASHBOARD-INIT: Fetching dashboard metadata for {dashboard_id}")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/init/{dashboard_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    logger.warning(f"❌ DASHBOARD-INIT: Failed to fetch: {response.status_code}")
                    return no_update

                init_data = response.json()
                cached_data = {**init_data, "timestamp": time.time()}
                return cached_data

        except Exception as e:
            logger.error(f"❌ DASHBOARD-INIT: Exception while fetching: {e}")
            return no_update

    # Project metadata callback (Cache 2: Project + delta_locations)
    @app.callback(
        Output("project-metadata-store", "data", allow_duplicate=True),
        [
            Input("dashboard-init-data", "data"),
        ],
        [
            State("local-store", "data"),
            State("project-metadata-store", "data"),
        ],
        prevent_initial_call=True,
    )
    async def populate_project_metadata_from_dashboard(
        dashboard_init_data, local_store, cached_project
    ):
        """
        Populate project-metadata-store with full project + delta_locations (via MongoDB $lookup join).

        Cache 2: Project Metadata + S3 Locations
        - Source: /projects/get/from_id endpoint (MongoDB aggregation with delta_locations join)
        - Contains: Full project + workflows + data_collections with delta_location field
        - Session storage: 10-minute cache, shared across dashboards in same project
        - Triggered by dashboard-init-data changes (gets project_id from dashboard metadata)
        """
        if not dashboard_init_data:
            return no_update

        project_id = dashboard_init_data.get("project_id")
        if not project_id:
            logger.warning("❌ PROJECT-METADATA: No project_id in dashboard-init-data")
            return no_update

        if not local_store or not local_store.get("access_token"):
            return no_update

        if _is_cache_valid(cached_project, "project._id", project_id, PROJECT_CACHE_TTL):
            cache_age = time.time() - cached_project.get("timestamp", 0)
            logger.info(
                f"🔧 PROJECT-METADATA: Using cached data for project {project_id} (age: {cache_age:.1f}s)"
            )
            return no_update

        access_token = local_store["access_token"]
        logger.info(
            f"📡 PROJECT-METADATA: Fetching project metadata with delta_locations for {project_id}"
        )

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
                    params={"project_id": project_id},
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    logger.warning(f"❌ PROJECT-METADATA: Failed to fetch: {response.status_code}")
                    return no_update

                project_data = response.json()
                cached_data = {
                    "project": project_data,
                    "cache_key": f"project_{project_id}",
                    "timestamp": time.time(),
                }
                return cached_data

        except Exception as e:
            logger.error(f"❌ PROJECT-METADATA: Exception while fetching: {e}")
            return no_update
