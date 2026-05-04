import asyncio
import json
import uuid
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import yaml
from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response

from depictio.api.v1.celery_dispatch import offload_or_run
from depictio.api.v1.celery_tasks import build_figure_preview as build_figure_preview_task
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import (
    get_child_tabs,
    get_parent_dashboard_title,
    load_dashboards_from_db,
    reorder_child_tabs,
    sync_tab_family_permissions,
)
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_current_user,
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.filter_links import extend_filters_via_links
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData, DashboardDataLite
from depictio.models.models.users import TokenBeanie, User, UserBeanie

dashboards_endpoint_router = APIRouter()


@dashboards_endpoint_router.post("/sync_with_projects")
async def sync_dashboard_permissions_with_projects(
    current_user: User = Depends(get_current_user),
):
    """
    Sync all dashboard permissions and visibility with their parent projects.
    This endpoint helps migrate from dashboard-specific permissions to project-based permissions.
    Only admins can perform this operation.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Only administrators can sync dashboard permissions."
        )

    dashboards = list(dashboards_collection.find({}))
    synced_count = 0
    failed_count = 0
    failed_dashboards = []

    for dashboard in dashboards:
        try:
            dashboard_id = dashboard.get("dashboard_id")
            project_id = dashboard.get("project_id")

            if not project_id:
                failed_count += 1
                failed_dashboards.append({"dashboard_id": dashboard_id, "reason": "No project_id"})
                continue

            project = projects_collection.find_one({"_id": ObjectId(project_id)})
            if not project:
                failed_count += 1
                failed_dashboards.append(
                    {"dashboard_id": dashboard_id, "reason": "Project not found"}
                )
                continue

            update_data = {
                "is_public": project.get("is_public", False),
            }

            dashboards_collection.update_one({"dashboard_id": dashboard_id}, {"$set": update_data})
            synced_count += 1

        except Exception as e:
            logger.error(
                f"Failed to sync dashboard {dashboard.get('dashboard_id', 'unknown')}: {e}"
            )
            failed_count += 1
            failed_dashboards.append(
                {"dashboard_id": dashboard.get("dashboard_id"), "reason": str(e)}
            )

    return {
        "success": True,
        "synced_count": synced_count,
        "failed_count": failed_count,
        "failed_dashboards": failed_dashboards,
        "message": f"Synced {synced_count} dashboards with their projects. {failed_count} failures.",
    }


# Utility functions for project-based permission inheritance
def get_project_permissions_for_dashboard(dashboard_id: PyObjectId) -> dict | None:
    """
    Get project permissions for a dashboard by looking up the project_id.

    Args:
        dashboard_id: The dashboard ID to get project permissions for

    Returns:
        dict: Project data with permissions, or None if not found
    """
    # First get the dashboard to find its project_id
    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        return None

    project_id = dashboard.get("project_id")
    if not project_id:
        return None

    # Get the project with its permissions
    project = projects_collection.find_one({"_id": ObjectId(project_id)})
    return project


def check_project_permission(
    project_id: PyObjectId, user: User, required_permission: str = "viewer"
) -> bool:
    """
    Check if user has required permission on project.

    Args:
        project_id: The project ID to check permissions for
        user: The user to check permissions for
        required_permission: "owner", "editor", or "viewer"

    Returns:
        bool: True if user has required permission or project is public
    """
    if user.is_admin:
        return True

    project = projects_collection.find_one({"_id": ObjectId(project_id)})
    if not project:
        return False

    # In anonymous mode, anonymous users can only access public projects
    if hasattr(user, "is_anonymous") and user.is_anonymous:
        return project.get("is_public", False)

    # Check if project is public
    if project.get("is_public", False):
        return True

    user_id = ObjectId(user.id)
    permissions = project.get("permissions", {})

    # Check based on required permission level
    if required_permission == "owner":
        return any(owner.get("_id") == user_id for owner in permissions.get("owners", []))
    elif required_permission == "editor":
        # Editors can also access if they are owners
        return any(owner.get("_id") == user_id for owner in permissions.get("owners", [])) or any(
            editor.get("_id") == user_id for editor in permissions.get("editors", [])
        )
    else:  # viewer
        # Viewers can access if they are owners, editors, or viewers
        return (
            any(owner.get("_id") == user_id for owner in permissions.get("owners", []))
            or any(editor.get("_id") == user_id for editor in permissions.get("editors", []))
            or any(viewer.get("_id") == user_id for viewer in permissions.get("viewers", []))
            or "*" in permissions.get("viewers", [])
        )


def get_project_visibility(project_id: PyObjectId) -> bool:
    """
    Get project visibility status.

    Args:
        project_id: The project ID

    Returns:
        bool: True if project is public, False otherwise
    """
    project = projects_collection.find_one({"_id": ObjectId(project_id)})
    if not project:
        return False
    return project.get("is_public", False)


@dashboards_endpoint_router.get("/get/{dashboard_id}")
async def get_dashboard(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Fetch dashboard data related to a dashboard ID.
    Now uses project-based permissions instead of dashboard-specific permissions.
    For child tabs, includes parent_dashboard_title for header display.
    """
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this dashboard."
        )

    dashboard = DashboardData.from_mongo(dashboard_data)
    dashboard_dict = dashboard.model_dump()

    # For child tabs, fetch parent dashboard title for header display
    parent_title = get_parent_dashboard_title(dashboard_dict)
    if parent_title:
        dashboard_dict["parent_dashboard_title"] = parent_title

    # Surface the project's realtime config so the React viewer can decide
    # whether to mount the RealtimeIndicator. A project without
    # ``realtime.enabled = true`` should never show live-update UI.
    project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
    realtime_cfg = (project_doc or {}).get("realtime")
    if realtime_cfg:
        dashboard_dict["project_realtime"] = {
            "enabled": bool(realtime_cfg.get("enabled", False)),
            "debounce_ms": int(realtime_cfg.get("debounce_ms", 1000)),
        }
    else:
        dashboard_dict["project_realtime"] = {"enabled": False, "debounce_ms": 1000}

    # Fire-and-forget prewarm: if this dashboard has any MultiQC components,
    # dispatch a Celery task that pre-renders them all into Redis. The task
    # is idempotent (skips already-cached entries), so repeated GETs from
    # multiple users don't pile up real work — they each enqueue a task that
    # mostly no-ops. Cold viewer load drops from ~14 s to <1 s once warm.
    has_multiqc = any(
        m.get("component_type") == "multiqc" for m in (dashboard_data.get("stored_metadata") or [])
    )
    if has_multiqc:
        try:
            from depictio.dash.celery_app import prewarm_multiqc_dashboard

            prewarm_multiqc_dashboard.delay(str(dashboard_id))
        except Exception as e:
            logger.warning(f"get_dashboard: prewarm dispatch failed for {dashboard_id}: {e}")

    return convert_objectid_to_str(dashboard_dict)


@dashboards_endpoint_router.get("/init/{dashboard_id}")
async def init_dashboard(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Dashboard initialization endpoint - returns ONLY dashboard-specific data.

    Project-wide data (dc_configs, column_specs, delta_locations) should be
    fetched separately via /projects/get/from_id endpoint for better caching.

    Returns:
        dict: Dashboard-specific initialization data
            {
                "dashboard": DashboardData (layout, metadata, notes, title),
                "project_id": str,
                "user_permissions": {level, can_edit, can_delete}
            }
    """
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this dashboard."
        )

    dashboard = DashboardData.from_mongo(dashboard_data)

    from depictio.api.v1.endpoints.projects_endpoints.utils import (
        get_project_with_delta_locations,
    )

    project_data = await get_project_with_delta_locations(project_id, current_user)

    user_permission_level = "viewer"

    # In single user mode, always grant owner permissions
    if settings.auth.is_single_user_mode:
        user_permission_level = "owner"
        logger.info("✅ Single user mode: Granting owner permissions")
    else:
        # Multi-user mode: Check actual permissions
        permissions = project_data.get("permissions", {})
        owner_ids = [str(owner.get("_id", "")) for owner in permissions.get("owners", [])]
        editor_ids = [str(editor.get("_id", "")) for editor in permissions.get("editors", [])]
        current_user_id_str = str(current_user.id)

        if current_user_id_str in owner_ids:
            user_permission_level = "owner"
        elif current_user_id_str in editor_ids:
            user_permission_level = "editor"

        # Fallback: check dashboard-level permissions (covers demo/public mode where
        # users own dashboards they created but are not project-level owners)
        if user_permission_level == "viewer":
            dashboard_permissions = dashboard_data.get("permissions", {})
            dashboard_owner_ids = [
                str(o.get("_id", "")) if isinstance(o, dict) else str(o)
                for o in dashboard_permissions.get("owners", [])
            ]
            dashboard_editor_ids = [
                str(e.get("_id", "")) if isinstance(e, dict) else str(e)
                for e in dashboard_permissions.get("editors", [])
            ]
            if current_user_id_str in dashboard_owner_ids:
                user_permission_level = "owner"
                logger.info(
                    f"✅ Granting owner via dashboard-level permissions for user {current_user_id_str}"
                )
            elif current_user_id_str in dashboard_editor_ids:
                user_permission_level = "editor"
                logger.info(
                    f"✅ Granting editor via dashboard-level permissions for user {current_user_id_str}"
                )

    dashboard_dict = dashboard.model_dump()

    # For child tabs, fetch parent dashboard title for header display
    parent_title = get_parent_dashboard_title(dashboard_dict)
    if parent_title:
        dashboard_dict["parent_dashboard_title"] = parent_title

    response = {
        "dashboard": dashboard_dict,
        "project_id": str(project_id),
        "user_permissions": {
            "level": user_permission_level,
            "can_edit": user_permission_level in ["owner", "editor"],
            "can_delete": user_permission_level == "owner",
        },
    }

    return convert_objectid_to_str(response)


@dashboards_endpoint_router.get("/list")
async def list_dashboards(
    include_child_tabs: bool = False,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Fetch a list of dashboards for the current user.

    Args:
        include_child_tabs: If True, includes child tabs in addition to main dashboards.
                           If False (default), returns only main dashboards.
    """
    result = load_dashboards_from_db(
        owner=current_user.id,
        admin_mode=False,
        user=current_user,
        include_child_tabs=include_child_tabs,
    )

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return result["dashboards"]


@dashboards_endpoint_router.get("/list_all")
async def list_all_dashboards(
    current_user: User = Depends(get_current_user),
):
    """Fetch a list of all dashboards (admin only)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    result = load_dashboards_from_db(owner=current_user.id, admin_mode=True)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return result["dashboards"]


@dashboards_endpoint_router.post("/toggle_public_status/{dashboard_id}")
async def make_dashboard_public(
    dashboard_id: PyObjectId,
    params: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Toggle dashboard visibility. Dashboard visibility now inherits from project visibility.
    Only project owners can change project (and thus dashboard) visibility.
    """
    _public_status = params.get("is_public", None)
    if _public_status is None:
        return {
            "success": False,
            "message": "No public status provided. Use 'is_public' parameter.",
        }

    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    project_id = dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "owner"):
        raise HTTPException(
            status_code=403, detail="Only project owners can change dashboard visibility."
        )

    project_result = projects_collection.find_one_and_update(
        {"_id": ObjectId(project_id)},
        {"$set": {"is_public": _public_status}},
        return_document=True,
    )

    if not project_result:
        raise HTTPException(status_code=404, detail="Project not found.")

    dashboards_update_result = dashboards_collection.update_many(
        {"project_id": ObjectId(project_id)},
        {"$set": {"is_public": _public_status}},
    )

    # Also sync child tab permissions for any main tabs in this project
    # This ensures tab families have consistent permissions
    main_tabs = dashboards_collection.find(
        {"project_id": ObjectId(project_id), "is_main_tab": {"$ne": False}}
    )
    child_tabs_updated = 0
    for main_tab in main_tabs:
        child_tabs_updated += sync_tab_family_permissions(
            main_tab["dashboard_id"], new_is_public=_public_status
        )

    return {
        "success": True,
        "message": f"Project and all its dashboards changed visibility to: {'public' if _public_status else 'private'}",
        "is_public": _public_status,
        "dashboards_updated": dashboards_update_result.modified_count,
        "child_tabs_updated": child_tabs_updated,
    }


@dashboards_endpoint_router.post("/edit_name/{dashboard_id}")
async def edit_dashboard_name(
    dashboard_id: PyObjectId,
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Edit the name of a dashboard with the given dashboard ID.
    Now uses project-based permissions (editor level required).
    Deprecated: Use /edit/{dashboard_id} instead.
    """
    new_name = data.get("new_name", None)
    if not new_name:
        raise HTTPException(status_code=400, detail="No new name provided.")

    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    project_id = dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to edit this dashboard."
        )

    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id},
        {"$set": {"title": new_name}},
        return_document=True,
    )

    if result:
        return {"message": f"Dashboard name updated successfully to '{new_name}'."}
    else:
        raise HTTPException(status_code=500, detail="Failed to update dashboard name.")


@dashboards_endpoint_router.post("/edit/{dashboard_id}")
async def edit_dashboard(
    dashboard_id: PyObjectId,
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Edit a dashboard's properties (title, subtitle, icon, icon_color, workflow_system).

    Does NOT allow changing project_id. Uses project-based permissions (editor level required).

    Args:
        dashboard_id: The dashboard ID to edit.
        data: Dictionary with fields to update. Allowed fields:
            - title: Dashboard title (required if provided)
            - subtitle: Dashboard subtitle (optional)
            - icon: Icon identifier (optional)
            - icon_color: Icon color (optional)
            - workflow_system: Workflow system (optional)
    """
    # Allowed fields to update (project_id is explicitly NOT allowed)
    allowed_fields = {"title", "subtitle", "icon", "icon_color", "workflow_system"}
    update_data = {k: v for k, v in data.items() if k in allowed_fields}

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields provided for update.")

    # Validate title is not empty if provided
    if "title" in update_data and not update_data["title"]:
        raise HTTPException(status_code=400, detail="Dashboard title cannot be empty.")

    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    project_id = dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to edit this dashboard."
        )

    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id},
        {"$set": update_data},
        return_document=True,
    )

    if result:
        return {
            "message": "Dashboard updated successfully.",
            "updated_fields": list(update_data.keys()),
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to update dashboard.")


@dashboards_endpoint_router.post("/save/{dashboard_id}")
async def save_dashboard(
    dashboard_id: PyObjectId,
    data: DashboardData,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Check if an entry with the same dashboard_id exists, if not, insert, if yes, update."""
    # Allow anonymous users in single-user mode (they have admin privileges)
    if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
        if not settings.auth.is_single_user_mode:
            raise HTTPException(
                status_code=403,
                detail="Anonymous users cannot create or modify dashboards. Please login to continue.",
            )

    existing_dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})

    if existing_dashboard:
        project_id = existing_dashboard.get("project_id")
        if not project_id:
            raise HTTPException(
                status_code=500, detail="Dashboard is not associated with a project."
            )

        if not check_project_permission(project_id, current_user, "editor"):
            raise HTTPException(
                status_code=403, detail="You don't have permission to update this dashboard."
            )

        result = dashboards_collection.find_one_and_update(
            {"dashboard_id": dashboard_id},
            {"$set": data.mongo()},
            return_document=True,
        )
    else:
        result = dashboards_collection.find_one_and_update(
            {"dashboard_id": dashboard_id},
            {"$set": data.mongo()},
            upsert=True,
            return_document=True,
        )

    if result:
        message = (
            "Dashboard data updated successfully."
            if result.get("dashboard_id", None) == dashboard_id
            else "Dashboard data inserted successfully."
        )
        logger.info(message)

        # Convert dashboard_id to string to ensure proper JSON serialization
        dashboard_id_str = str(dashboard_id)

        # Auto-queue screenshot regeneration so /dashboards-beta and any
        # other listing surface picks up the latest dashboard state without
        # the user needing to navigate to the viewer first. Mirrors the
        # explicit `.delay(...)` call the Dash editor's save callback makes
        # at depictio/dash/layouts/save.py:367 — moving the dispatch here
        # means every client (Dash editor, React editor, the React component
        # builder's upsertComponent flow) gets screenshots queued by default.
        # Lazy import to keep API startup independent of the Dash worker
        # module, and a broad except so a Celery/broker outage never breaks
        # the save response itself.
        try:
            from depictio.dash.celery_app import generate_dashboard_screenshot_dual

            user_id = str(getattr(current_user, "id", "") or "")
            generate_dashboard_screenshot_dual.delay(dashboard_id_str, user_id)
            logger.debug(f"Queued screenshot regeneration for dashboard {dashboard_id_str}")
        except Exception as exc:  # noqa: BLE001 — non-fatal best-effort dispatch
            logger.warning(f"Could not queue screenshot for {dashboard_id_str}: {exc}")

        return {"message": message, "dashboard_id": dashboard_id_str}
    else:
        raise HTTPException(status_code=404, detail="Failed to insert or update dashboard data.")


# =============================================================================
# DEPRECATED ENDPOINT - USE /utils/screenshot-dash-fixed/{dashboard_id} INSTEAD
# =============================================================================
# This endpoint is no longer used by production code.
# The active screenshot endpoint is at /depictio/api/v1/utils/screenshot-dash-fixed/
# which uses component-based composite screenshots for better results.
# TODO: Remove in future cleanup PR after verifying no external dependencies
# =============================================================================
@dashboards_endpoint_router.get("/screenshot/{dashboard_id}")
async def screenshot_dashboard(
    dashboard_id: PyObjectId,
    # current_user: User = Depends(get_current_user),
):
    """DEPRECATED: Take a screenshot of a dashboard.

    This endpoint is deprecated. Use /utils/screenshot-dash-fixed/{dashboard_id}
    instead, which provides better component-based screenshots.
    """
    from playwright.async_api import async_playwright

    output_folder = "/app/depictio/dash/static/screenshots"  # Directly set to the desired path
    logger.info(f"Output folder: {output_folder}")
    # try:
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        # Set viewport size
        viewport_width = 1920
        viewport_height = 1080
        context = await browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height}
        )
        page = await context.new_page()

        # Navigate to Dash service
        logger.info(f"Navigating to Dash service at {settings.dash.internal_url}")
        await page.goto(settings.dash.internal_url, timeout=90000)

        # Wait for page to load
        # await page.wait_for_load_state("networkidle")
        logger.debug("Looking for user in the database...")
        current_user = await UserBeanie.find_one({"email": "admin@example.com"})

        # current_user = await UserBeanie.find_one({"email": "admin@example.com"})
        logger.debug(f"Current user: {current_user}")

        # Get all tokens for the current user
        logger.debug("Fetching tokens for the current user...")
        tokens = await TokenBeanie.find({"user_id": current_user.id}).to_list()
        logger.debug(f"Tokens found: {tokens}")

        # Log datetime.now() for debugging purposes
        logger.debug(f"Current datetime: {datetime.now()}")

        # Log refresh_expire_datetime for each token
        for token in tokens:
            logger.debug(
                f"Token ID: {token.id}, refresh_expire_datetime: {token.refresh_expire_datetime}"
            )

        # get the current user a functional token
        token = await TokenBeanie.find_one(
            {
                "user_id": current_user.id,
                # "token_lifetime": "short-lived",
                "refresh_expire_datetime": {"$gt": datetime.now()},
            }
        )
        logger.debug(f"Token: {token}")

        token_data = token.model_dump(exclude_none=True)
        logger.debug(f"Token data: {token_data}")
        token_data["_id"] = token_data.pop("id", None)
        token_data["logged_in"] = True
        logger.debug(f"Token: {token}")

        token_data_json = json.dumps(token_data)
        logger.debug(f"Token data: {token_data_json}")

        # Set data in the local storage
        await page.evaluate(
            f"""() => {{
            localStorage.setItem('local-store', '{token_data_json}');
        }}"""
        )
        # await asyncio.sleep(3600)  # Keeps the browser open for 1 hour

        await page.reload()

        await asyncio.sleep(3)  # Wait for the page to stabilize
        # dashboard_id = "6824cb3b89d2b72169309737"
        await page.goto(f"{settings.dash.internal_url}/dashboard/{dashboard_id}", timeout=90000)
        # await page.wait_for_load_state("networkidle")
        await page.reload()
        await asyncio.sleep(10)  # Wait for dashboard to fully load

        # Wait for dashboard components to render with proper dimensions
        try:
            await page.wait_for_function(
                """
                () => {
                    const components = document.querySelectorAll('.react-grid-item');
                    if (components.length === 0) return false;

                    // Check if at least one component has meaningful dimensions
                    for (let component of components) {
                        const rect = component.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            return true;
                        }
                    }
                    return false;
                }
            """,
                timeout=10000,
            )
            logger.info("✅ Dashboard components rendered with proper dimensions")
        except Exception as e:
            logger.warning(f"⚠️ Timeout waiting for components to render: {e}")

        # Component-based screenshot targeting (proven working approach)
        output_file = f"{output_folder}/{str(dashboard_id)}.png"
        try:
            components = await page.query_selector_all(".react-grid-item")
            logger.info(f"📸 Found {len(components)} dashboard components")

            if components and len(components) > 0:
                # Create composite view of all components
                composite_element = await page.evaluate(
                    """
                    () => {
                        const components = document.querySelectorAll('.react-grid-item');
                        if (components.length === 0) return null;

                        // Get bounding box of all components
                        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

                        components.forEach(component => {
                            const rect = component.getBoundingClientRect();
                            minX = Math.min(minX, rect.left);
                            minY = Math.min(minY, rect.top);
                            maxX = Math.max(maxX, rect.right);
                            maxY = Math.max(maxY, rect.bottom);
                        });

                        // Create an invisible div that encompasses all components
                        const container = document.createElement('div');
                        container.id = 'temp-screenshot-container';
                        container.style.position = 'absolute';
                        container.style.left = minX + 'px';
                        container.style.top = minY + 'px';
                        container.style.width = (maxX - minX) + 'px';
                        container.style.height = (maxY - minY) + 'px';
                        container.style.pointerEvents = 'none';
                        container.style.border = '2px solid transparent';
                        container.style.zIndex = '-1';

                        document.body.appendChild(container);

                        return {
                            width: maxX - minX,
                            height: maxY - minY,
                            componentCount: components.length,
                            bounds: { minX, minY, maxX, maxY }
                        };
                    }
                """
                )

                if composite_element:
                    logger.info(
                        f"📸 Component composite: {composite_element['width']:.0f}x{composite_element['height']:.0f} with {composite_element['componentCount']} components"
                    )

                    # Screenshot the composite area with 16:9 constraint if needed
                    temp_container = await page.query_selector("#temp-screenshot-container")
                    if temp_container:
                        await temp_container.screenshot(path=output_file)
                        logger.info(f"📸 Component composite screenshot saved to {output_file}")

                    # Clean up the temporary element
                    await page.evaluate(
                        "document.getElementById('temp-screenshot-container')?.remove()"
                    )
                else:
                    raise Exception("Failed to create composite element")
            else:
                raise Exception("No dashboard components found")

        except Exception as e:
            logger.warning(f"Component-based screenshot failed: {e}, trying fallback")
            # Fallback to AppShell main
            try:
                main_element = await page.query_selector(".mantine-AppShell-main")
                if main_element:
                    await main_element.screenshot(path=output_file)
                    logger.info("📸 AppShell main screenshot taken (fallback)")
                else:
                    # Final fallback to full page
                    await page.screenshot(path=output_file, full_page=True)
                    logger.info("📸 Full page screenshot taken (final fallback)")
            except Exception as fallback_e:
                logger.warning(f"All screenshot methods failed: {fallback_e}")
                await page.screenshot(path=output_file, full_page=True)

        await browser.close()
        logger.info(f"Screenshot saved to {output_file}")

        return {
            "success": True,
            "url": settings.dash.internal_url,
            "message": "Screenshot taken successfully",
            "screenshot_path": output_file,
            # "token": convert_objectid_to_str(token_data),
            # "user": current_user.model_dump(exclude_none=True),
        }

    # except Exception as e:
    #     return {
    #         "success": False,
    #         "url": settings.dash.internal_url,
    #         "error": str(e),
    #         "message": "Failed to take screenshot",
    #     }


@dashboards_endpoint_router.delete("/delete/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_current_user),
):
    """
    Delete a dashboard with the given dashboard ID.
    If the dashboard is a main tab, also delete all child tabs.
    """

    user_id = current_user.id

    # First, check if the dashboard exists and user has permission
    dashboard = dashboards_collection.find_one(
        {"dashboard_id": dashboard_id, "permissions.owners._id": user_id}
    )

    if not dashboard:
        raise HTTPException(
            status_code=404,
            detail=f"Dashboard with ID '{dashboard_id}' not found or access denied.",
        )

    # Check if this is a main tab - if so, delete all child tabs first
    child_tabs_deleted = 0
    if dashboard.get("is_main_tab", True):
        # Delete all child tabs
        child_result = dashboards_collection.delete_many({"parent_dashboard_id": dashboard_id})
        child_tabs_deleted = child_result.deleted_count
        logger.info(f"Deleted {child_tabs_deleted} child tabs for dashboard {dashboard_id}")

    # Delete the dashboard itself
    result = dashboards_collection.delete_one({"dashboard_id": dashboard_id})

    if result.deleted_count > 0:
        message = f"Dashboard with ID '{str(dashboard_id)}' deleted successfully."
        if child_tabs_deleted > 0:
            message += f" Also deleted {child_tabs_deleted} child tabs."
        return {"message": message, "child_tabs_deleted": child_tabs_deleted}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete dashboard.")


# ============================================================================
# Tab CRUD Endpoints
# ============================================================================


@dashboards_endpoint_router.patch("/tab/{dashboard_id}")
async def update_tab(
    dashboard_id: PyObjectId,
    data: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Update tab properties (title, icon, icon_color, main_tab_name).

    For main tabs, you can also update main_tab_name.
    For child tabs, you can update title, tab_icon, and tab_icon_color.

    Args:
        dashboard_id: The dashboard/tab ID to update
        data: Dictionary with fields to update:
            - title: New tab title (for child tabs or dashboard title for main tabs)
            - tab_icon: Icon name (e.g., "mdi:chart-bar")
            - tab_icon_color: Color for the icon
            - main_tab_name: Custom name for the main tab (main tabs only)

    Returns:
        Updated dashboard information
    """
    # Allow anonymous users in single-user mode (they have admin privileges)
    if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
        if not settings.auth.is_single_user_mode:
            raise HTTPException(
                status_code=403,
                detail="Anonymous users cannot modify tabs. Please login to continue.",
            )

    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        raise HTTPException(
            status_code=404, detail=f"Dashboard/tab with ID '{dashboard_id}' not found."
        )

    project_id = dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(status_code=403, detail="You don't have permission to edit this tab.")

    # Build update fields based on what was provided
    update_fields: dict[str, Any] = {}

    if "title" in data:
        update_fields["title"] = data["title"]
    if "tab_icon" in data:
        update_fields["tab_icon"] = data["tab_icon"]
    if "tab_icon_color" in data:
        update_fields["tab_icon_color"] = data["tab_icon_color"]

    # main_tab_name can only be set on main tabs
    if "main_tab_name" in data:
        if not dashboard.get("is_main_tab", True):
            raise HTTPException(
                status_code=400,
                detail="main_tab_name can only be set on main tabs, not child tabs.",
            )
        update_fields["main_tab_name"] = data["main_tab_name"]

    if not update_fields:
        raise HTTPException(status_code=400, detail="No valid fields provided for update.")

    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id},
        {"$set": update_fields},
        return_document=True,
    )

    if result:
        return {
            "success": True,
            "message": "Tab updated successfully.",
            "dashboard_id": str(dashboard_id),
            "updated_fields": list(update_fields.keys()),
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to update tab.")


@dashboards_endpoint_router.delete("/tab/{dashboard_id}")
async def delete_tab(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Delete a child tab.

    Main tabs cannot be deleted through this endpoint - use the regular
    /delete/{dashboard_id} endpoint which also deletes all child tabs.

    Args:
        dashboard_id: The child tab's dashboard ID to delete

    Returns:
        Success message with deleted tab info
    """
    # Allow anonymous users in single-user mode (they have admin privileges)
    if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
        if not settings.auth.is_single_user_mode:
            raise HTTPException(
                status_code=403,
                detail="Anonymous users cannot delete tabs. Please login to continue.",
            )

    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        raise HTTPException(status_code=404, detail=f"Tab with ID '{dashboard_id}' not found.")

    # Check if this is a main tab - if so, reject the delete
    if dashboard.get("is_main_tab", True):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete main tab through this endpoint. "
            "Use /delete/{dashboard_id} to delete the entire dashboard including all tabs.",
        )

    project_id = dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Tab is not associated with a project.")

    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this tab.")

    # Store parent dashboard ID for navigation after delete
    parent_dashboard_id = dashboard.get("parent_dashboard_id")
    tab_title = dashboard.get("title", "Untitled")

    result = dashboards_collection.delete_one({"dashboard_id": dashboard_id})

    if result.deleted_count > 0:
        return {
            "success": True,
            "message": f"Tab '{tab_title}' deleted successfully.",
            "deleted_dashboard_id": str(dashboard_id),
            "parent_dashboard_id": str(parent_dashboard_id) if parent_dashboard_id else None,
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to delete tab.")


@dashboards_endpoint_router.post("/tabs/reorder")
async def reorder_tabs(
    data: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Reorder child tabs by updating their tab_order values.

    Main tab always stays at position 0 and cannot be reordered.
    Only child tabs can be reordered.

    Args:
        data: Dictionary with:
            - parent_dashboard_id: The main tab's dashboard ID
            - tab_orders: List of {dashboard_id, tab_order} dicts

    Returns:
        Success message with count of updated tabs
    """
    # Allow anonymous users in single-user mode (they have admin privileges)
    if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
        if not settings.auth.is_single_user_mode:
            raise HTTPException(
                status_code=403,
                detail="Anonymous users cannot reorder tabs. Please login to continue.",
            )

    parent_dashboard_id = data.get("parent_dashboard_id")
    tab_orders = data.get("tab_orders", [])

    if not parent_dashboard_id:
        raise HTTPException(status_code=400, detail="parent_dashboard_id is required.")

    if not tab_orders:
        raise HTTPException(status_code=400, detail="tab_orders list is required.")

    # Verify parent dashboard exists and is a main tab
    parent_dashboard = dashboards_collection.find_one(
        {"dashboard_id": ObjectId(parent_dashboard_id)}
    )
    if not parent_dashboard:
        raise HTTPException(
            status_code=404, detail=f"Parent dashboard '{parent_dashboard_id}' not found."
        )

    if not parent_dashboard.get("is_main_tab", True):
        raise HTTPException(
            status_code=400,
            detail="The specified dashboard is not a main tab.",
        )

    project_id = parent_dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(status_code=403, detail="You don't have permission to reorder tabs.")

    # Perform the reorder
    updated_count = reorder_child_tabs(PyObjectId(parent_dashboard_id), tab_orders)

    return {
        "success": True,
        "message": f"Reordered {updated_count} tabs successfully.",
        "updated_count": updated_count,
    }


@dashboards_endpoint_router.get("/tabs/{parent_dashboard_id}")
async def get_tabs(
    parent_dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Get all tabs for a dashboard (main tab + child tabs).

    Returns the main tab and all child tabs sorted by tab_order.

    Args:
        parent_dashboard_id: The main tab's dashboard ID

    Returns:
        List of tabs with main tab first, then child tabs ordered by tab_order
    """
    # Get main tab
    main_tab = dashboards_collection.find_one({"dashboard_id": parent_dashboard_id})
    if not main_tab:
        raise HTTPException(status_code=404, detail=f"Dashboard '{parent_dashboard_id}' not found.")

    # Check if this is actually a main tab
    if not main_tab.get("is_main_tab", True):
        raise HTTPException(
            status_code=400,
            detail="The specified dashboard is not a main tab.",
        )

    project_id = main_tab.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to view this dashboard's tabs."
        )

    # Get child tabs
    child_tabs = get_child_tabs(parent_dashboard_id)

    # Build main tab entry - include icon and icon_color for main tab display
    main_tab_entry = {
        "dashboard_id": str(main_tab["dashboard_id"]),
        "title": main_tab.get("title", "Untitled"),
        "tab_order": 0,
        "is_main_tab": True,
        "main_tab_name": main_tab.get("main_tab_name"),
        "tab_icon": main_tab.get("tab_icon"),
        "tab_icon_color": main_tab.get("tab_icon_color"),
        # Dashboard's own icon and color (for main tab to inherit)
        "icon": main_tab.get("icon", "mdi:view-dashboard"),
        "icon_color": main_tab.get("icon_color", "orange"),
        # Workflow info for auto-color derivation
        "workflow_system": main_tab.get("workflow_system"),
        "workflow_catalog": main_tab.get("workflow_catalog"),
    }

    return {
        "success": True,
        "main_tab": main_tab_entry,
        "child_tabs": child_tabs,
        "total_count": 1 + len(child_tabs),
    }


@dashboards_endpoint_router.get("/get_component_data/{dashboard_id}/{component_id}")
async def get_component_data_endpoint(
    dashboard_id: PyObjectId,
    component_id: UUID,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Fetch component data related to a component ID using optimized MongoDB aggregation.

    This endpoint uses MongoDB aggregation pipeline to:
    1. Filter by dashboard_id and user permissions
    2. Filter the stored_metadata array to find only the specific component
    3. Return only the component data without loading the full dashboard
    """

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}, fetching component: {component_id}")

    # First check if dashboard exists and get project permissions
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Get project_id from dashboard and check project-based permissions
    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check project-based permissions (viewer level required for reading components)
    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this dashboard component."
        )

    # Optimized aggregation pipeline to fetch only the specific component
    pipeline = [
        # Stage 1: Match dashboard (permissions already verified above)
        {
            "$match": {
                "dashboard_id": dashboard_id,
            }
        },
        # Stage 2: Project only the filtered component from stored_metadata
        {
            "$project": {
                "_id": 1,
                "dashboard_id": 1,
                "component_metadata": {
                    "$filter": {
                        "input": "$stored_metadata",
                        "as": "metadata",
                        "cond": {"$eq": ["$$metadata.index", str(component_id)]},
                    }
                },
            }
        },
        # Stage 3: Unwind the component_metadata array to get single object
        {
            "$unwind": {
                "path": "$component_metadata",
                "preserveNullAndEmptyArrays": False,  # Skip if no matching component found
            }
        },
        # Stage 4: Replace root with just the component metadata
        {"$replaceRoot": {"newRoot": "$component_metadata"}},
    ]

    # Execute aggregation pipeline
    result = list(dashboards_collection.aggregate(pipeline))

    logger.debug(f"Aggregation result: {result}")

    if not result:
        logger.error(f"Component with ID {component_id} not found in dashboard {dashboard_id}.")
        raise HTTPException(
            status_code=404,
            detail=f"Component with ID '{component_id}' not found in dashboard.",
        )

    # Get the component metadata
    component_metadata = result[0]

    logger.debug(f"Component metadata found for ID {component_id}")

    # Convert ObjectIds to strings for JSON serialization
    component_metadata = convert_objectid_to_str(component_metadata)

    return component_metadata


@dashboards_endpoint_router.post("/bulk_component_data/{dashboard_id}")
def bulk_get_component_data_endpoint(
    dashboard_id: PyObjectId,
    request: dict,  # {"component_ids": [uuid1, uuid2, ...]}
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    PERFORMANCE OPTIMIZATION: Fetch multiple component data in a single request.

    Reduces HTTP overhead from N individual requests to 1 batch request.
    Expected performance improvement: ~70% for dashboard loading.

    Args:
        dashboard_id: Dashboard ID
        request: {"component_ids": [list of component UUIDs]}
        current_user: Current authenticated user

    Returns:
        Dict mapping component_id -> component_metadata
    """
    component_ids = request.get("component_ids", [])

    if not component_ids:
        return {}

    logger.info(
        f"🚀 BULK FETCH: Getting {len(component_ids)} components for dashboard {dashboard_id}"
    )

    # Check dashboard exists and permissions (same as individual endpoint)
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Get project_id and check permissions
    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check project permissions using existing function
    project_data = projects_collection.find_one({"_id": project_id})
    if not project_data:
        raise HTTPException(status_code=404, detail="Associated project not found.")

    # Verify user permissions for the project
    can_access = check_project_permission(project_id, current_user, "viewer")
    if not can_access:
        raise HTTPException(
            status_code=403, detail="Access denied: insufficient permissions for this project."
        )

    # Convert component_ids to strings for MongoDB query
    component_ids_str = [str(cid) for cid in component_ids]

    # Build optimized aggregation pipeline for bulk fetch
    pipeline = [
        # Stage 1: Match the dashboard
        {"$match": {"dashboard_id": dashboard_id}},
        # Stage 2: Filter stored_metadata for requested components
        {
            "$project": {
                "dashboard_id": 1,
                "bulk_components": {
                    "$filter": {
                        "input": "$stored_metadata",
                        "as": "metadata",
                        "cond": {"$in": ["$$metadata.index", component_ids_str]},
                    }
                },
            }
        },
        # Stage 3: Unwind to get individual components
        {
            "$unwind": {
                "path": "$bulk_components",
                "preserveNullAndEmptyArrays": False,
            }
        },
        # Stage 4: Group back by component index for easy lookup
        {
            "$group": {
                "_id": "$bulk_components.index",
                "component_data": {"$first": "$bulk_components"},
            }
        },
    ]

    # Execute aggregation pipeline
    results = list(dashboards_collection.aggregate(pipeline))

    # Convert to dict mapping component_id -> component_data
    bulk_data = {}
    for result in results:
        component_id = result["_id"]
        component_data = convert_objectid_to_str(result["component_data"])
        bulk_data[component_id] = component_data

    logger.info(f"✅ BULK SUCCESS: Retrieved {len(bulk_data)}/{len(component_ids)} components")

    # Log any missing components for debugging
    missing_ids = set(component_ids_str) - set(bulk_data.keys())
    if missing_ids:
        logger.warning(f"⚠️ Missing components: {missing_ids}")

    return bulk_data


# ============================================================================
# React viewer: bulk card value computation with filters
# ============================================================================


def _agg_value(col: Any, aggregation: str) -> Any:
    """Compute a scalar aggregation over a Polars Series.

    Covers the aggregations used by Depictio card components. Matches the
    subset of ``depictio.dash.modules.card_component.utils.compute_value``
    but avoids pulling any Dash imports into the FastAPI process.
    """
    agg = (aggregation or "").lower()
    try:
        if agg == "count":
            return int(col.drop_nulls().len())
        if agg in ("average", "mean"):
            mean = col.mean()
            return float(mean) if mean is not None else None
        if agg == "sum":
            s = col.sum()
            return float(s) if s is not None else None
        if agg == "median":
            m = col.median()
            return float(m) if m is not None else None
        if agg == "min":
            mn = col.min()
            return (
                float(mn) if isinstance(mn, (int, float)) else (str(mn) if mn is not None else None)
            )
        if agg == "max":
            mx = col.max()
            return (
                float(mx) if isinstance(mx, (int, float)) else (str(mx) if mx is not None else None)
            )
        if agg in ("std", "std_dev"):
            return float(col.std()) if col.std() is not None else None
        if agg in ("variance", "var"):
            return float(col.var()) if col.var() is not None else None
        if agg in ("nunique", "unique"):
            return int(col.n_unique())
        if agg == "range":
            mn, mx = col.min(), col.max()
            if mn is None or mx is None:
                return None
            return float(mx) - float(mn) if isinstance(mn, (int, float)) else None
        if agg == "mode":
            m = col.mode()
            return (
                None
                if len(m) == 0
                else (float(m[0]) if isinstance(m[0], (int, float)) else str(m[0]))
            )
    except Exception as e:
        logger.warning(f"Aggregation {agg!r} failed on column: {e}")
        return None
    return None


def _resolve_link_filters(
    filters: list[dict],
    target_dc_id: str,
    project_id: Any,
    access_token: str | None,
    component_type: str,
) -> list[dict]:
    """Append synthetic filters resolved via DC links to the React-supplied list.

    Mirrors what ``_extract_filters_for_image`` (and the Dash figure/table
    callbacks) do. Each React-supplied filter exposes ``metadata.dc_id``; we
    group them by source DC, fetch project metadata, and ask
    ``extend_filters_via_links`` to derive any extra filters that should apply
    to the target DC. The returned list is the original filters plus any link-
    resolved synthetic filters, all in the same payload shape that the existing
    ``filter_metadata`` builders consume.
    """
    if not filters or not target_dc_id or not project_id or not access_token:
        return list(filters)

    filters_by_dc: dict[str, list[dict]] = {}
    for f in filters:
        meta = f.get("metadata") or {}
        dc_id = str(meta.get("dc_id") or f.get("dc_id") or "")
        if not dc_id:
            continue
        entry = {
            "index": f.get("index"),
            "value": f.get("value"),
            "source": f.get("source") or meta.get("source"),
            "metadata": {
                "dc_id": dc_id,
                "column_name": meta.get("column_name") or f.get("column_name"),
                "interactive_component_type": meta.get("interactive_component_type")
                or f.get("interactive_component_type"),
                "selection_column": meta.get("selection_column"),
            },
        }
        filters_by_dc.setdefault(dc_id, []).append(entry)

    try:
        project_doc = projects_collection.find_one({"_id": ObjectId(str(project_id))})
    except Exception as e:
        logger.warning(f"link-resolve: project fetch failed for {project_id}: {e}")
        return list(filters)
    if not project_doc:
        return list(filters)

    project_metadata = {"project": convert_objectid_to_str(project_doc)}
    extra = extend_filters_via_links(
        target_dc_id=str(target_dc_id),
        filters_by_dc=filters_by_dc,
        project_metadata=project_metadata,
        access_token=access_token,
        component_type=component_type,
    )
    if not extra:
        return list(filters)

    flattened: list[dict] = []
    for ef in extra:
        meta = ef.get("metadata") or {}
        flattened.append(
            {
                "index": ef.get("index"),
                "value": ef.get("value"),
                "column_name": meta.get("column_name"),
                "interactive_component_type": meta.get("interactive_component_type")
                or "MultiSelect",
                "metadata": {
                    "dc_id": str(target_dc_id),
                    "column_name": meta.get("column_name"),
                    "interactive_component_type": meta.get("interactive_component_type")
                    or "MultiSelect",
                },
            }
        )
    return list(filters) + flattened


def _own_selection_values(filters: list[dict], component: dict, source: str) -> list | None:
    """Pluck the values for this component's own active selection, if any.

    The React viewer stores selection emits as filters with
    ``source="scatter_selection"|"table_selection"|"map_selection"`` and
    ``index`` set to the emitting component's index. When we re-render that
    component, we pass the matching values back as ``active_selection_values``
    so the figure/map re-highlights the user's selection.
    """
    target_idx = str(component.get("index"))
    for f in filters:
        if str(f.get("index")) != target_idx:
            continue
        if (f.get("source") or (f.get("metadata") or {}).get("source")) != source:
            continue
        value = f.get("value")
        if not value:
            return None
        return value if isinstance(value, list) else [value]
    return None


def _build_filter_metadata(filters: list[dict]) -> list[dict]:
    """Convert React filter payloads into the shape ``load_deltatable_lite`` expects.

    Skips entries that are missing a ``column_name`` or whose value is empty;
    those wouldn't survive ``process_metadata_and_filter`` anyway.

    Carries ``filter_expr`` through (top-level or under ``metadata``) so the
    server-side pipeline can AND the source's row-scoping expression alongside
    the user-supplied value.
    """
    out: list[dict] = []
    for f in filters:
        meta = f.get("metadata") or {}
        column_name = f.get("column_name") or meta.get("column_name")
        if not column_name or f.get("value") in (None, [], ""):
            continue
        entry: dict = {
            "interactive_component_type": f.get("interactive_component_type")
            or meta.get("interactive_component_type"),
            "column_name": column_name,
            "value": f.get("value"),
        }
        filter_expr = f.get("filter_expr") or meta.get("filter_expr")
        if filter_expr:
            entry["filter_expr"] = filter_expr
        out.append(entry)
    return out


@dashboards_endpoint_router.post("/bulk_compute_cards/{dashboard_id}")
def bulk_compute_cards(
    dashboard_id: PyObjectId,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
):
    """Compute card values with interactive filters applied.

    Called by the React viewer whenever the filter state changes. Dedupes
    Delta-table loads: multiple cards referencing the same (wf_id, dc_id, filter
    fingerprint) share one load. Returns a map keyed by component index.

    Request body:
        {
            "filters": [
                {"index": "...", "value": ..., "column_name": "...",
                 "interactive_component_type": "MultiSelect"},
                ...
            ],
            "component_ids": ["...", ...]   # optional; defaults to all cards
        }

    Response:
        {
            "values": {"<component_index>": <scalar or null>, ...},
            "secondary_values": {
                "<component_index>": {"<aggregation>": <scalar or null>, ...},
                ...
            },
            "aggregations": {"<component_index>": ["<aggregation>", ...], ...},
            "filter_applied": bool,
            "filter_count": int
        }

        ``secondary_values`` and ``aggregations`` are only populated for cards
        that declare ``aggregations`` in YAML (multi-metrics card).

    Notes:
        - Uses load_deltatable_lite with the same metadata format as Dash so
          the filter semantics match the Dash viewer exactly.
        - The Dash callback render_card_value_background in
          card_component/callbacks/core.py remains the source of truth for the
          edit path; this endpoint mirrors its math.
    """
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    filters = request.get("filters") or []
    requested_ids: list[str] | None = request.get("component_ids")

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    stored_metadata = dashboard_data.get("stored_metadata") or []

    # Collect card components (optionally filtered by component_ids)
    requested = set(requested_ids) if requested_ids else None
    cards = [
        m
        for m in stored_metadata
        if m.get("component_type") == "card"
        and (requested is None or str(m.get("index")) in requested)
    ]

    if not cards:
        return {"values": {}, "filter_applied": bool(filters), "filter_count": len(filters)}

    # Build init_data mapping for load_deltatable_lite to avoid per-card API calls
    init_data: dict[str, dict] = {}
    for m in cards:
        dc_id = str(m.get("dc_id"))
        if not dc_id or dc_id in init_data:
            continue
        dc_config = m.get("dc_config") or {}
        delta_loc = dc_config.get("delta_location")
        if not delta_loc:
            # Fallback: look up via deltatables_collection
            from depictio.api.v1.db import deltatables_collection

            dt = deltatables_collection.find_one({"data_collection_id": ObjectId(dc_id)})
            if dt:
                delta_loc = dt.get("delta_table_location")
        if delta_loc:
            init_data[dc_id] = {
                "delta_location": delta_loc,
                "dc_type": dc_config.get("type") or "table",
                "size_bytes": dc_config.get("size_bytes", 0),
            }

    # Filters are global (applied to any card whose DC contains the filter column).
    # The base list is what the React viewer sent. Per card we additionally
    # apply DC-link resolution so cards on a target DC pick up filters from
    # source DCs they're linked to (mirrors the Dash callback path via
    # extend_filters_via_links).
    base_filter_metadata = _build_filter_metadata(filters)

    # Dedupe Delta loads per (wf_id, dc_id). One load can serve N cards.
    df_cache: dict[tuple, Any] = {}
    # Per-DC precomputed aggregation specs cache (one DB hit per unique dc_id).
    # Mirrors `/deltatables/specs/{dc_id}` shape: {column: {aggregation: value}}.
    specs_cache: dict[str, dict] = {}
    values: dict[str, Any] = {}
    # Multi-metrics card: per-card map of secondary aggregation results.
    secondary_values: dict[str, dict[str, Any]] = {}
    aggregations_per_card: dict[str, list[str]] = {}

    has_filters = len(base_filter_metadata) > 0
    logger.debug(
        f"bulk_compute_cards: dashboard={dashboard_id} cards={len(cards)} "
        f"init_data_keys={list(init_data.keys())} filters={len(base_filter_metadata)}"
    )

    # Per-DC link-resolved filter cache so we only call the link API once per
    # target DC. The result already includes the original React-supplied
    # filters, so it can be passed straight to load_deltatable_lite.
    resolved_per_dc: dict[str, list[dict]] = {}

    def _resolved_filters_for(dc_id_str: str) -> list[dict]:
        if dc_id_str in resolved_per_dc:
            return resolved_per_dc[dc_id_str]
        merged = _resolve_link_filters(
            filters=filters,
            target_dc_id=dc_id_str,
            project_id=project_id,
            access_token=access_token,
            component_type="card",
        )
        resolved_per_dc[dc_id_str] = _build_filter_metadata(merged)
        return resolved_per_dc[dc_id_str]

    def _get_specs(dc_id_str: str) -> dict[str, dict]:
        """Return precomputed column aggregations as ``{column_name: specs_dict}``.

        The Mongo schema stores ``aggregation_columns_specs`` as a list of
        ``{name, type, description, specs}`` entries — flatten to a name-keyed
        dict for O(1) lookup. Also handle the legacy dict shape for safety.
        """
        if dc_id_str in specs_cache:
            return specs_cache[dc_id_str]
        from depictio.api.v1.db import deltatables_collection as _dt_coll

        dt = _dt_coll.find_one({"data_collection_id": ObjectId(dc_id_str)})
        agg_list = (dt or {}).get("aggregation") or []
        raw = (agg_list[-1] or {}).get("aggregation_columns_specs") if agg_list else None

        flat: dict[str, dict] = {}
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict) and entry.get("name"):
                    flat[entry["name"]] = entry.get("specs") or {}
        elif isinstance(raw, dict):
            flat = raw  # legacy

        specs_cache[dc_id_str] = flat
        return flat

    for card in cards:
        idx = str(card.get("index"))
        wf_id = card.get("wf_id")
        dc_id = card.get("dc_id")
        column = card.get("column_name")
        aggregation = card.get("aggregation")
        secondary_aggs_raw = card.get("aggregations") or []
        secondary_aggs = [a for a in secondary_aggs_raw if a and a != aggregation]
        if secondary_aggs:
            aggregations_per_card[idx] = secondary_aggs

        if not (wf_id and dc_id and column and aggregation):
            logger.warning(
                f"bulk_compute_cards: skipping {idx}: wf_id={wf_id} dc_id={dc_id} "
                f"column={column} aggregation={aggregation}"
            )
            values[idx] = None
            continue

        # Fast path (no filters): read precomputed aggregation from
        # aggregation_columns_specs. Mirrors what the Dash callback does via
        # compute_value's `cols_json` short-circuit. Avoids touching raw Delta
        # data — necessary for DCs whose Delta file has corrupted columns.
        if not has_filters:
            specs = _get_specs(str(dc_id))
            col_specs = specs.get(column) or {}
            specs_value = col_specs.get(aggregation)
            if specs_value is not None:
                values[idx] = (
                    float(specs_value) if isinstance(specs_value, (int, float)) else specs_value
                )
                logger.debug(
                    f"bulk_compute_cards: {idx} ({aggregation}/{column}) = {values[idx]} (specs)"
                )
                if secondary_aggs:
                    sec: dict[str, Any] = {}
                    all_specs_present = True
                    for sa in secondary_aggs:
                        sv = col_specs.get(sa)
                        if sv is None:
                            all_specs_present = False
                            break
                        sec[sa] = float(sv) if isinstance(sv, (int, float)) else sv
                    if all_specs_present:
                        secondary_values[idx] = sec
                        continue
                    # Fall through to slow path to compute secondary values
                else:
                    continue

        # Slow path: load Delta and compute. Required when filters change the
        # input set, or when the precomputed aggregation isn't available.
        # Cache key includes the filter signature so two cards on the same DC
        # with different (link-resolved) filter sets don't collide.
        card_filters = _resolved_filters_for(str(dc_id))
        filter_sig = tuple(
            sorted(
                (
                    str(fm.get("column_name")),
                    str(fm.get("interactive_component_type")),
                    repr(fm.get("value")),
                )
                for fm in card_filters
            )
        )
        cache_key = (str(wf_id), str(dc_id), filter_sig)
        df = df_cache.get(cache_key)
        if df is None:
            try:
                df = load_deltatable_lite(
                    workflow_id=ObjectId(str(wf_id)) if not isinstance(wf_id, ObjectId) else wf_id,
                    data_collection_id=str(dc_id),
                    metadata=card_filters if card_filters else None,
                    init_data=init_data,
                )
                logger.debug(
                    f"bulk_compute_cards: loaded {cache_key}: shape={df.shape if df is not None else None}"
                )
            except Exception as e:
                logger.warning(
                    f"bulk_compute_cards: DC load failed for {cache_key}: {e}", exc_info=True
                )
                values[idx] = None
                continue
            df_cache[cache_key] = df

        if column not in df.columns:
            logger.warning(
                f"bulk_compute_cards: column {column!r} not in df for {idx}; "
                f"available cols (first 10): {df.columns[:10]}"
            )
            values[idx] = None
            continue

        values[idx] = _agg_value(df[column], aggregation)
        logger.debug(f"bulk_compute_cards: {idx} ({aggregation}/{column}) = {values[idx]}")

        if secondary_aggs:
            sec_results: dict[str, Any] = {}
            for sa in secondary_aggs:
                sec_results[sa] = _agg_value(df[column], sa)
            secondary_values[idx] = sec_results

    return {
        "values": values,
        "secondary_values": secondary_values,
        "aggregations": aggregations_per_card,
        "filter_applied": len(base_filter_metadata) > 0,
        "filter_count": len(base_filter_metadata),
    }


# ============================================================================
# React viewer: figure rendering
# ============================================================================


@dashboards_endpoint_router.post("/render_figure/{dashboard_id}/{component_id}")
async def render_figure_endpoint(
    dashboard_id: PyObjectId,
    component_id: str,
    request: dict,
    response: Response,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
):
    """Render a Plotly figure component as JSON for the React viewer.

    Mirrors what `_process_single_figure` does in the Dash callback at
    ``depictio.dash.modules.figure_component.callbacks.core.py:676`` — loads
    the data collection, applies filters, calls `_create_figure_from_data`
    (UI mode) or `_process_code_mode_figure` (code mode), and returns the
    Plotly figure dict ready for ``react-plotly.js``.

    Heavy work (delta load + Plotly build) runs on Celery when
    `settings.celery.offload_rendering` is true. Reuses the
    `build_figure_preview` task — preview and render share the exact same
    code path on the worker.

    Request body:
        {"filters": [...], "theme": "light" | "dark"}

    Response:
        {"figure": <plotly fig dict>, "metadata": {visu_type, ...}}
    """
    filters = request.get("filters") or []
    theme = request.get("theme") or "light"

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    component = next(
        (
            m
            for m in (dashboard_data.get("stored_metadata") or [])
            if str(m.get("index")) == component_id and m.get("component_type") == "figure"
        ),
        None,
    )
    if component is None:
        raise HTTPException(status_code=404, detail=f"Figure component '{component_id}' not found.")

    wf_id = component.get("wf_id")
    dc_id = component.get("dc_id")
    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="Component missing wf_id/dc_id.")

    merged_filters = _resolve_link_filters(
        filters=filters,
        target_dc_id=str(dc_id),
        project_id=project_id,
        access_token=access_token,
        component_type="figure",
    )
    filter_metadata = _build_filter_metadata(merged_filters)

    # Build a JSON-safe payload for the task. ObjectIds in the component dict
    # are normalized to strings so the JSON serializer doesn't choke; the task
    # body re-coerces wf_id back to ObjectId for `load_deltatable_lite`.
    metadata = {
        "wf_id": str(wf_id),
        "dc_id": str(dc_id),
        "dc_config": convert_objectid_to_str(component.get("dc_config") or {}),
        "visu_type": component.get("visu_type", "scatter"),
        "dict_kwargs": component.get("dict_kwargs") or {},
        "mode": component.get("mode", "ui"),
        "code_content": component.get("code_content", ""),
        "selection_enabled": bool(component.get("selection_enabled", False)),
        "selection_column": component.get("selection_column"),
    }

    offload = settings.celery.offload_rendering
    response.headers["X-Celery-Path"] = "offloaded" if offload else "inline"

    payload = {"metadata": metadata, "filter_metadata": filter_metadata, "theme": theme}
    try:
        return await offload_or_run(
            build_figure_preview_task,
            (payload,),
            offload=offload,
            label=f"render_figure cid={component_id} dc={dc_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"render_figure: build failed for {component_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Figure render failed: {e}")


# ============================================================================
# React viewer: table data (lazy rows for AG Grid)
# ============================================================================


@dashboards_endpoint_router.post("/render_table/{dashboard_id}/{component_id}")
def render_table_endpoint(
    dashboard_id: PyObjectId,
    component_id: str,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
):
    """Return table rows + column definitions for the React viewer's AG Grid.

    Request body:
        {"filters": [...], "start": 0, "limit": 100}

    Response:
        {"columns": [{"field", "headerName", "type"}, ...],
         "rows":    [{...}, ...],
         "total":   <int>}
    """
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    filters = request.get("filters") or []
    start = int(request.get("start") or 0)
    limit = int(request.get("limit") or 100)
    limit = max(1, min(limit, 500))

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    component = next(
        (
            m
            for m in (dashboard_data.get("stored_metadata") or [])
            if str(m.get("index")) == component_id and m.get("component_type") == "table"
        ),
        None,
    )
    if component is None:
        raise HTTPException(status_code=404, detail=f"Table component '{component_id}' not found.")

    wf_id = component.get("wf_id")
    dc_id = component.get("dc_id")
    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="Component missing wf_id/dc_id.")

    merged_filters = _resolve_link_filters(
        filters=filters,
        target_dc_id=str(dc_id),
        project_id=project_id,
        access_token=access_token,
        component_type="table",
    )
    filter_metadata = _build_filter_metadata(merged_filters)

    dc_config = component.get("dc_config") or {}
    init_data: dict[str, dict] = {}
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        from depictio.api.v1.db import deltatables_collection

        dt = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if delta_loc:
        init_data[str(dc_id)] = {
            "delta_location": delta_loc,
            "dc_type": dc_config.get("type") or "table",
            "size_bytes": dc_config.get("size_bytes", 0),
        }

    try:
        df = load_deltatable_lite(
            workflow_id=ObjectId(str(wf_id)) if not isinstance(wf_id, ObjectId) else wf_id,
            data_collection_id=str(dc_id),
            metadata=filter_metadata or None,
            init_data=init_data,
        )
    except Exception as e:
        logger.error(f"render_table: DC load failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load data: {e}")

    total = df.height
    sliced = df.slice(start, limit)
    rows = sliced.to_dicts()

    columns = []
    for name, dtype in zip(df.columns, df.dtypes):
        type_str = str(dtype).lower()
        ag_type = (
            "numericColumn"
            if any(t in type_str for t in ("int", "float", "double"))
            else "textColumn"
        )
        columns.append({"field": name, "headerName": name, "type": ag_type})

    return {"columns": columns, "rows": rows, "total": total}


@dashboards_endpoint_router.post("/render_image_paths/{dashboard_id}/{component_id}")
def render_image_paths_endpoint(
    dashboard_id: PyObjectId,
    component_id: str,
    request: dict | None = Body(default=None),
    max: int | None = None,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
):
    """Return non-null values of an image component's ``image_column``.

    Request body (optional):
        {"filters": [...], "max": 50}

    The ``?max=`` query string is still honored as a backwards-compatible alias
    when callers don't supply a body. ``filters`` follows the same payload
    shape used by ``bulk_compute_cards``/``render_figure``/``render_table`` and
    can include selection-source filters (``source: "scatter_selection"``,
    ``"table_selection"``, ``"map_selection"``). Cross-DC link filters are
    applied via ``extend_filters_via_links`` so an image grid narrows when a
    linked DC is filtered (mirrors Dash ``_extract_filters_for_image``).
    """
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    body = request or {}
    filters = body.get("filters") or []
    body_max = body.get("max")
    chosen_max = body_max if body_max is not None else max
    limit = int(chosen_max) if chosen_max and int(chosen_max) > 0 else 50
    if limit > 500:
        limit = 500

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    component = next(
        (
            m
            for m in (dashboard_data.get("stored_metadata") or [])
            if str(m.get("index")) == component_id and m.get("component_type") == "image"
        ),
        None,
    )
    if component is None:
        raise HTTPException(status_code=404, detail=f"Image component '{component_id}' not found.")

    wf_id = component.get("wf_id")
    dc_id = component.get("dc_id")
    image_column = component.get("image_column")
    if not (wf_id and dc_id and image_column):
        raise HTTPException(status_code=400, detail="Component missing wf_id/dc_id/image_column.")

    merged_filters = _resolve_link_filters(
        filters=filters,
        target_dc_id=str(dc_id),
        project_id=project_id,
        access_token=access_token,
        component_type="image",
    )
    filter_metadata = _build_filter_metadata(merged_filters)

    dc_config = component.get("dc_config") or {}
    init_data: dict[str, dict] = {}
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        from depictio.api.v1.db import deltatables_collection

        dt = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if delta_loc:
        init_data[str(dc_id)] = {
            "delta_location": delta_loc,
            "dc_type": dc_config.get("type") or "table",
            "size_bytes": dc_config.get("size_bytes", 0),
        }

    try:
        df = load_deltatable_lite(
            workflow_id=ObjectId(str(wf_id)) if not isinstance(wf_id, ObjectId) else wf_id,
            data_collection_id=str(dc_id),
            metadata=filter_metadata or None,
            init_data=init_data,
        )
    except Exception as e:
        logger.error(f"render_image_paths: DC load failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load data: {e}")

    if image_column not in df.columns:
        raise HTTPException(
            status_code=400, detail=f"Column '{image_column}' missing from Delta table."
        )

    paths = df.select(image_column).drop_nulls().head(limit).to_series().to_list()
    return {
        "paths": [str(p) for p in paths],
        "filter_applied": bool(filter_metadata),
        "filter_count": len(filter_metadata),
    }


# ============================================================================
# React viewer: map rendering (Plotly px.scatter_map / density_map / choropleth_map)
# ============================================================================


@dashboards_endpoint_router.post("/render_map/{dashboard_id}/{component_id}")
def render_map_endpoint(
    dashboard_id: PyObjectId,
    component_id: str,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
):
    """Render a Plotly map component as JSON for the React viewer.

    Mirrors `render_figure_endpoint` but delegates to
    `depictio.dash.modules.map_component.utils.render_map`. The full map
    `stored_metadata` already carries every trigger_data field (map_type,
    lat_column, lon_column, color_column, geojson_*, etc.) — the Dash callback
    just rebuilds it from kwargs at create time — so we pass `component`
    directly as `trigger_data`. `render_map` reads what it needs via `.get()`.
    """
    from depictio.api.v1.deltatables_utils import load_deltatable_lite
    from depictio.dash.modules.map_component.utils import render_map

    filters = request.get("filters") or []
    theme = request.get("theme") or "light"

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    component = next(
        (
            m
            for m in (dashboard_data.get("stored_metadata") or [])
            if str(m.get("index")) == component_id and m.get("component_type") == "map"
        ),
        None,
    )
    if component is None:
        raise HTTPException(status_code=404, detail=f"Map component '{component_id}' not found.")

    wf_id = component.get("wf_id")
    dc_id = component.get("dc_id")
    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="Component missing wf_id/dc_id.")

    merged_filters = _resolve_link_filters(
        filters=filters,
        target_dc_id=str(dc_id),
        project_id=project_id,
        access_token=access_token,
        component_type="map",
    )
    filter_metadata = _build_filter_metadata(merged_filters)

    dc_config = component.get("dc_config") or {}
    init_data: dict[str, dict] = {}
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        from depictio.api.v1.db import deltatables_collection

        dt = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if delta_loc:
        init_data[str(dc_id)] = {
            "delta_location": delta_loc,
            "dc_type": dc_config.get("type") or "table",
            "size_bytes": dc_config.get("size_bytes", 0),
        }

    try:
        df = load_deltatable_lite(
            workflow_id=ObjectId(str(wf_id)) if not isinstance(wf_id, ObjectId) else wf_id,
            data_collection_id=str(dc_id),
            metadata=filter_metadata or None,
            init_data=init_data,
        )
    except Exception as e:
        logger.error(f"render_map: DC load failed for {dc_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load data: {e}")

    import plotly.io as pio

    if "mantine_light" not in pio.templates or "mantine_dark" not in pio.templates:
        try:
            import dash_mantine_components as dmc

            dmc.add_figure_templates()
        except Exception as e:
            logger.warning(f"render_map: failed to register mantine templates: {e}")

    selection_values = _own_selection_values(filters, component, source="map_selection")

    try:
        fig, data_info = render_map(
            df=df,
            trigger_data=component,
            theme=theme,
            existing_metadata=None,
            active_selection_values=selection_values,
            access_token=access_token,
        )

        if hasattr(fig, "to_json"):
            fig_dict = json.loads(fig.to_json())
        elif hasattr(fig, "to_plotly_json"):
            fig_dict = fig.to_plotly_json()
        else:
            fig_dict = fig

        if isinstance(fig_dict, dict) and "layout" in fig_dict:
            fig_dict["layout"].setdefault("uirevision", "persistent")

        return {
            "figure": fig_dict,
            "metadata": {
                "map_type": component.get("map_type", "scatter_map"),
                "filter_applied": bool(filter_metadata),
                "displayed_count": data_info.get("displayed_count"),
                "total_count": data_info.get("total_count"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"render_map: build failed for {component_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Map render failed: {e}")


# ============================================================================
# React viewer: JBrowse session URL
# ============================================================================


@dashboards_endpoint_router.post("/render_jbrowse/{dashboard_id}/{component_id}")
async def render_jbrowse_endpoint(
    dashboard_id: PyObjectId,
    component_id: str,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Synthesise the JBrowse 2 iframe URL for the React viewer.

    JBrowse 2 must be running at ``localhost:3000`` and its session config
    server at ``localhost:9010/sessions/...``; if either is unreachable,
    returns 503 (no silent fallback).
    """
    import httpx

    from depictio.api.v1.configs.config import API_BASE_URL

    JBROWSE_HOST = "http://localhost:3000"
    JBROWSE_SESSIONS_HOST = "http://localhost:9010"

    filters = request.get("filters") or []

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    component = next(
        (
            m
            for m in (dashboard_data.get("stored_metadata") or [])
            if str(m.get("index")) == component_id and m.get("component_type") == "jbrowse"
        ),
        None,
    )
    if component is None:
        raise HTTPException(
            status_code=404, detail=f"JBrowse component '{component_id}' not found."
        )

    wf_id = component.get("wf_id")
    dc_id = component.get("dc_id")
    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="Component missing wf_id/dc_id.")

    dc_config = component.get("dc_config") or {}
    jbrowse_params = dc_config.get("jbrowse_params") or {}
    assembly = jbrowse_params.get("assemblyName") or "hg38"
    default_loc = jbrowse_params.get("default_location") or "chr1:1-248956422"

    user_id = str(getattr(current_user, "id", "anonymous"))
    session = f"{user_id}_{dc_id}_lite.json"

    track_ids: list[str] = []
    filter_applied = bool(filters)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                last_status_resp = await client.get(
                    f"{API_BASE_URL}/depictio/api/v1/jbrowse/last_status"
                )
                if last_status_resp.status_code == 200:
                    last_status = last_status_resp.json()
                    assembly = last_status.get("assembly") or assembly
                    if last_status.get("loc"):
                        default_loc = last_status["loc"]
            except httpx.HTTPError as e:
                logger.warning(f"render_jbrowse: last_status unreachable: {e}")

            if filters:
                try:
                    map_resp = await client.get(
                        f"{API_BASE_URL}/depictio/api/v1/jbrowse/map_tracks_using_wildcards/"
                        f"{wf_id}/{dc_id}",
                    )
                    if map_resp.status_code == 200:
                        mapping = map_resp.json() or {}
                        dc_map = mapping.get(str(dc_id), {})
                        for f in filters:
                            col = f.get("column_name")
                            value = f.get("value")
                            if not col or value in (None, [], ""):
                                continue
                            values = value if isinstance(value, list) else [value]
                            col_map = dc_map.get(col, {})
                            for v in values:
                                tid = col_map.get(str(v))
                                if tid:
                                    track_ids.append(tid)
                except httpx.HTTPError as e:
                    logger.warning(f"render_jbrowse: map_tracks unreachable: {e}")

                if track_ids and len(track_ids) <= 100:
                    try:
                        filter_resp = await client.post(
                            f"{API_BASE_URL}/depictio/api/v1/jbrowse/filter_config",
                            json={
                                "tracks": track_ids,
                                "dashboard_id": str(dashboard_id),
                                "data_collection_id": str(dc_id),
                            },
                        )
                        if filter_resp.status_code == 200:
                            body = filter_resp.json() or {}
                            if body.get("session"):
                                session = body["session"]
                    except httpx.HTTPError as e:
                        logger.warning(f"render_jbrowse: filter_config unreachable: {e}")
    except Exception as e:
        logger.error(f"render_jbrowse: internal jbrowse routing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"JBrowse internal services unreachable: {e}",
        )

    qs = f"assembly={assembly}&loc={default_loc}"
    if track_ids and len(track_ids) <= 100:
        qs += f"&tracks={','.join(track_ids)}"
    iframe_url = f"{JBROWSE_HOST}?config={JBROWSE_SESSIONS_HOST}/sessions/{session}&{qs}"

    return {
        "iframe_url": iframe_url,
        "assembly": assembly,
        "location": default_loc,
        "tracks": track_ids or None,
        "metadata": {"filter_applied": filter_applied},
    }


# ============================================================================
# React viewer: MultiQC rendering
# ============================================================================


def _resolve_multiqc_sample_filter(
    dashboard_data: dict,
    component: dict,
    filters: list[dict],
) -> list[str]:
    """Resolve a list of dashboard interactive filters into a sample-name list.

    Mirrors the simple branch of ``patch_multiqc_plot_with_interactive_filtering``:
      - filters on the MultiQC DC's own ``sample`` column → values used directly
      - filters on a different metadata DC → load the metadata DC with the
        filters applied, take unique values of its ``sample`` column

    Returns an empty list when no resolvable filters are present. Logs but does
    not raise on metadata-DC load failures.
    """
    if not filters:
        return []

    wf_id = component.get("wf_id")
    if not wf_id:
        return []

    multiqc_dc_id_str = str(component.get("dc_id") or component.get("data_collection_id") or "")
    stored_meta_index = {
        str(m.get("index")): m for m in (dashboard_data.get("stored_metadata") or [])
    }

    metadata_dc_id: str | None = None
    direct_sample_values: list[str] = []
    indirect_filter_metadata: list[dict] = []

    for f in filters:
        value = f.get("value")
        if value in (None, [], ""):
            continue
        fdx = str(f.get("index") or "")
        comp_meta = stored_meta_index.get(fdx) or {}
        comp_dc = str(comp_meta.get("dc_id") or comp_meta.get("data_collection_id") or "")
        column_name = f.get("column_name") or comp_meta.get("column_name")

        if comp_dc == multiqc_dc_id_str and column_name == "sample":
            values_list = value if isinstance(value, list) else [value]
            direct_sample_values.extend(str(v) for v in values_list)
            continue

        if comp_dc and comp_dc != multiqc_dc_id_str:
            if metadata_dc_id is None:
                metadata_dc_id = comp_dc
            if comp_dc == metadata_dc_id:
                indirect_filter_metadata.append(
                    {
                        "interactive_component_type": f.get("interactive_component_type")
                        or comp_meta.get("interactive_component_type"),
                        "column_name": column_name,
                        "value": value,
                    }
                )

    selected_samples: list[str] = list(direct_sample_values)

    if metadata_dc_id and indirect_filter_metadata:
        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        try:
            meta_df = load_deltatable_lite(
                workflow_id=ObjectId(str(wf_id)) if not isinstance(wf_id, ObjectId) else wf_id,
                data_collection_id=str(metadata_dc_id),
                metadata=indirect_filter_metadata,
            )
            if meta_df is not None and not meta_df.is_empty():
                if "sample" in meta_df.columns:
                    selected_samples.extend(str(s) for s in meta_df["sample"].unique().to_list())
                else:
                    logger.warning(
                        f"_resolve_multiqc_sample_filter: metadata DC {metadata_dc_id} has no "
                        f"'sample' column; columns={meta_df.columns}"
                    )
        except Exception as e:
            logger.warning(
                f"_resolve_multiqc_sample_filter: filter resolution on DC {metadata_dc_id} "
                f"failed: {e}",
                exc_info=True,
            )

    return list(dict.fromkeys(selected_samples))


@dashboards_endpoint_router.post("/render_multiqc/{dashboard_id}/{component_id}")
def render_multiqc_endpoint(
    dashboard_id: PyObjectId,
    component_id: str,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Render a MultiQC Plotly figure as JSON for the React viewer.

    Wraps the pure ``create_multiqc_plot()`` helper in
    ``depictio.dash.modules.figure_component.multiqc_vis`` — same function the
    Dash callback uses. Reads ``selected_module``, ``selected_plot``,
    ``selected_dataset`` and ``s3_locations`` from the component's
    stored_metadata (with a DC-config fallback for ``s3_locations`` if missing,
    matching the Dash restoration path).

    Filters: applied via ``patch_multiqc_figures()`` after sample resolution.
    Filters that target a metadata DC different from the MultiQC DC are
    resolved by loading the metadata DC with the filters applied, then
    pulling the unique values of the ``sample`` join column. Filters that
    target the MultiQC DC's own ``sample`` column are used directly.
    """
    filters = request.get("filters") or []
    theme = request.get("theme") or "light"

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    component = next(
        (
            m
            for m in (dashboard_data.get("stored_metadata") or [])
            if str(m.get("index")) == component_id and m.get("component_type") == "multiqc"
        ),
        None,
    )
    if component is None:
        raise HTTPException(
            status_code=404, detail=f"MultiQC component '{component_id}' not found."
        )

    selected_module = component.get("selected_module")
    selected_plot = component.get("selected_plot")
    selected_dataset = component.get("selected_dataset")
    s3_locations = component.get("s3_locations") or []

    dc_id = component.get("dc_id") or component.get("data_collection_id")

    # Direct MongoDB lookup via the process-agnostic helper. It covers both:
    # (1) project_doc.workflows[].data_collections[].config.dc_specific_properties.s3_location
    # (2) multiqc_collection (deployed reports), queried by data_collection_id.
    # No HTTP loop-back, no token needed — both Dash's restore path and this
    # API route share the same resolution.
    if not s3_locations and dc_id:
        from depictio.dash.modules.multiqc_component.models import _fetch_s3_locations_from_dc

        s3_locations = _fetch_s3_locations_from_dc(str(dc_id), str(project_id))
        logger.info(
            f"render_multiqc: _fetch_s3_locations_from_dc"
            f"(dc={dc_id!s}, project={project_id!s})"
            f" → {len(s3_locations)} s3_location(s)"
        )

    if not selected_module or not selected_plot or not s3_locations:
        missing = []
        if not selected_module:
            missing.append("selected_module")
        if not selected_plot:
            missing.append("selected_plot")
        if not s3_locations:
            missing.append(
                f"s3_locations (dc_id={dc_id!s}; tried project_doc.workflows[]"
                f".data_collections[].config.dc_specific_properties.s3_location AND "
                f"multiqc_collection.find({{data_collection_id: '{dc_id!s}'}}) — "
                f"both empty)"
            )
        raise HTTPException(
            status_code=400,
            detail=f"MultiQC component is missing: {', '.join(missing)}.",
        )

    import plotly.io as pio

    if "mantine_light" not in pio.templates or "mantine_dark" not in pio.templates:
        try:
            import dash_mantine_components as dmc

            dmc.add_figure_templates()
        except Exception as e:
            logger.warning(f"render_multiqc: failed to register mantine templates: {e}")

    # Per-stage timing instrumentation. Stripped to a single TIMING log line
    # so it's easy to grep `docker logs` for per-stage cost on warm vs cold
    # requests. Drop once perf is satisfactory.
    import time as _time

    from depictio.api.cache import get_cache
    from depictio.dash.modules.figure_component.multiqc_vis import (
        create_multiqc_plot,
        generate_figure_cache_key,
    )

    t0 = _time.perf_counter()
    timings: dict[str, float] = {}

    try:
        selected_samples = _resolve_multiqc_sample_filter(dashboard_data, component, filters)
        timings["resolve_filter_ms"] = (_time.perf_counter() - t0) * 1000
        filter_applied = bool(selected_samples)
        filter_sig: str | None = None
        if filter_applied:
            sorted_samples = sorted({str(s) for s in selected_samples})
            filter_sig = "|".join(sorted_samples)

        cache = get_cache()
        filter_aware_key = generate_figure_cache_key(
            s3_locations,
            selected_module,
            selected_plot,
            selected_dataset,
            theme,
            filter_sig=filter_sig,
        )

        t1 = _time.perf_counter()
        cached = cache.get(filter_aware_key)
        timings["cache_get_ms"] = (_time.perf_counter() - t1) * 1000
        cache_hit = cached is not None

        if cached is not None:
            fig_dict = cached
        else:
            t2 = _time.perf_counter()
            fig = create_multiqc_plot(
                s3_locations=s3_locations,
                module=selected_module,
                plot=selected_plot,
                dataset_id=selected_dataset,
                theme=theme,
            )
            timings["create_plot_ms"] = (_time.perf_counter() - t2) * 1000

            t3 = _time.perf_counter()
            if hasattr(fig, "to_json"):
                fig_dict = json.loads(fig.to_json())
            else:
                fig_dict = fig
            timings["to_json_ms"] = (_time.perf_counter() - t3) * 1000

            if isinstance(fig_dict, dict) and "layout" in fig_dict:
                fig_dict["layout"].setdefault("uirevision", "persistent")

            if filter_applied:
                from depictio.dash.modules.multiqc_component.callbacks.core import (
                    patch_multiqc_figures,
                )

                t4 = _time.perf_counter()
                patched = patch_multiqc_figures([fig_dict], selected_samples)
                timings["patch_filter_ms"] = (_time.perf_counter() - t4) * 1000
                if patched:
                    fig_dict = patched[0]
                    if isinstance(fig_dict, dict):
                        fig_dict.setdefault("layout", {})
                        fig_dict["layout"]["_depictio_filter_applied"] = True

            try:
                t5 = _time.perf_counter()
                cache.set(filter_aware_key, fig_dict, ttl=7200)
                timings["cache_set_ms"] = (_time.perf_counter() - t5) * 1000
            except Exception as cache_err:
                logger.warning(f"render_multiqc: cache.set failed: {cache_err}")

        timings["total_ms"] = (_time.perf_counter() - t0) * 1000
        timings_str = " ".join(f"{k}={v:.1f}" for k, v in timings.items())
        logger.info(
            f"TIMING render_multiqc cid={component_id} hit={cache_hit} "
            f"filter={'y' if filter_applied else 'n'} {timings_str}"
        )

        return {
            "figure": fig_dict,
            "metadata": {
                "module": selected_module,
                "plot": selected_plot,
                "dataset_id": selected_dataset,
                "filter_applied": filter_applied,
                "selected_sample_count": len(selected_samples) if filter_applied else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"render_multiqc: build failed for {component_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MultiQC render failed: {e}")


@dashboards_endpoint_router.post("/render_multiqc_general_stats/{dashboard_id}/{component_id}")
def render_multiqc_general_stats_endpoint(
    dashboard_id: PyObjectId,
    component_id: str,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """JSON-safe payload for the React MultiQC General Statistics renderer.

    Wraps ``build_general_stats_payload()`` (the JSON-safe sibling of
    ``build_general_stats_content()``). Resolves ``s3_locations`` the same way
    the regular ``render_multiqc`` endpoint does, then converts the first
    location into a local parquet path via ``_get_local_path_for_s3`` (matching
    the Dash dispatcher in ``multiqc_component/callbacks/core.py``). Reuses the
    same Redis cache key shape so warm Dash sessions also warm the React route.
    """
    import hashlib

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")

    project_id = dashboard_data.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")

    component = next(
        (
            m
            for m in (dashboard_data.get("stored_metadata") or [])
            if str(m.get("index")) == component_id and m.get("component_type") == "multiqc"
        ),
        None,
    )
    if component is None:
        raise HTTPException(
            status_code=404, detail=f"MultiQC component '{component_id}' not found."
        )

    s3_locations = component.get("s3_locations") or []
    dc_id = component.get("dc_id") or component.get("data_collection_id")

    if not s3_locations and dc_id:
        from depictio.dash.modules.multiqc_component.models import _fetch_s3_locations_from_dc

        s3_locations = _fetch_s3_locations_from_dc(str(dc_id), str(project_id))

    if not s3_locations:
        raise HTTPException(
            status_code=400,
            detail=(
                f"MultiQC component is missing s3_locations (dc_id={dc_id!s}); "
                f"both stored_metadata and DC config lookup returned empty."
            ),
        )

    show_hidden = bool(request.get("show_hidden", True))
    filters = request.get("filters") or []

    selected_samples = _resolve_multiqc_sample_filter(dashboard_data, component, filters)

    # The violin figure built by `_create_violin_plot` uses the `mantine_light`
    # / `mantine_dark` Plotly templates. Register them on cold workers — same
    # guard the regular `render_multiqc_endpoint` uses just above.
    import plotly.io as pio

    if "mantine_light" not in pio.templates or "mantine_dark" not in pio.templates:
        try:
            import dash_mantine_components as dmc

            dmc.add_figure_templates()
        except Exception as e:
            logger.warning(
                f"render_multiqc_general_stats: failed to register mantine templates: {e}"
            )

    import time as _time

    _t0 = _time.perf_counter()
    timings: dict[str, float] = {}

    try:
        from depictio.api.cache import get_cache
        from depictio.dash.modules.figure_component.multiqc_vis import (
            _get_local_path_for_s3,
        )
        from depictio.dash.modules.multiqc_component.callbacks.core import (
            _normalize_multiqc_paths,
        )
        from depictio.dash.modules.multiqc_component.general_stats import (
            build_general_stats_payload,
        )

        normalized = _normalize_multiqc_paths(s3_locations)
        raw_path = normalized[0] if normalized else s3_locations[0]

        # React-side cache key — distinct from Dash's `multiqc:gs:` so the two
        # callers don't trample each other's payload shape. Filter signature is
        # part of the key so each filter combination caches independently.
        # Mtime stat removed — same rationale as the figure cache: it fired a
        # filesystem stat on every request (even cache hits) and any S3-cache
        # refresh cold-evicted the payload. TTL handles invalidation.
        filter_sig = "|".join(sorted(selected_samples)) if selected_samples else "all"
        cache_key_str = f"{raw_path}::{filter_sig}::general_stats_payload"
        cache_key = f"multiqc:gs_payload:{hashlib.sha256(cache_key_str.encode()).hexdigest()[:16]}"

        cache = get_cache()
        _t_get0 = _time.perf_counter()
        cached = cache.get(cache_key)
        timings["cache_get_ms"] = (_time.perf_counter() - _t_get0) * 1000
        cache_hit = cached is not None
        if cached is not None:
            timings["total_ms"] = (_time.perf_counter() - _t0) * 1000
            timings_str = " ".join(f"{k}={v:.1f}" for k, v in timings.items())
            logger.info(
                f"TIMING render_gs cid={component_id} hit=True "
                f"filter={'y' if selected_samples else 'n'} {timings_str}"
            )
            return cached

        _t_build0 = _time.perf_counter()
        parquet_path = _get_local_path_for_s3(raw_path)
        payload = build_general_stats_payload(
            parquet_path=parquet_path,
            show_hidden=show_hidden,
            selected_samples=selected_samples or None,
        )
        timings["build_payload_ms"] = (_time.perf_counter() - _t_build0) * 1000
        if selected_samples:
            payload["filter_applied"] = True
            payload["selected_sample_count"] = len(selected_samples)

        try:
            _t_set0 = _time.perf_counter()
            cache.set(cache_key, payload, ttl=7200)
            timings["cache_set_ms"] = (_time.perf_counter() - _t_set0) * 1000
        except Exception as cache_err:
            logger.warning(f"render_multiqc_general_stats: cache.set failed: {cache_err}")

        timings["total_ms"] = (_time.perf_counter() - _t0) * 1000
        timings_str = " ".join(f"{k}={v:.1f}" for k, v in timings.items())
        logger.info(
            f"TIMING render_gs cid={component_id} hit={cache_hit} "
            f"filter={'y' if selected_samples else 'n'} {timings_str}"
        )

        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"render_multiqc_general_stats: build failed for {component_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"MultiQC general_stats render failed: {e}")


# ============================================================================
# YAML Import Endpoint (CLI support)
# ============================================================================


def _resolve_workflow_tags(component: dict, project_id: PyObjectId | None = None) -> None:
    """Resolve workflow and data collection tags to MongoDB IDs.

    Searches the target project (or all projects as fallback) for matching
    workflows and data collections, updating the component dict in place
    with wf_id, dc_id, and dc_config.

    Args:
        component: Component dict to update in place.
        project_id: Target project ID. When provided, only searches this project
            (prevents resolving to the wrong project's DC IDs).
    """
    wf_tag = component.get("workflow_tag")
    dc_tag = component.get("data_collection_tag")

    if not wf_tag or component.get("wf_id"):
        return

    # Parse engine/name format (e.g., "python/iris_workflow")
    wf_name = wf_tag.split("/", 1)[1] if "/" in wf_tag else wf_tag

    # Search target project first, fall back to all projects
    if project_id:
        projects = [projects_collection.find_one({"_id": ObjectId(project_id)})]
        projects = [p for p in projects if p]
    else:
        projects = list(projects_collection.find())

    for proj in projects:
        for wf in proj.get("workflows", []):
            if wf.get("name") != wf_name and wf.get("workflow_tag") != wf_name:
                continue

            component["wf_id"] = wf["_id"]
            engine = wf.get("engine", {}).get("name", "unknown")
            component["wf_tag"] = f"{engine}/{wf.get('name', wf_name)}"

            # Resolve data collection within this workflow
            if dc_tag and not component.get("dc_id"):
                for dc in wf.get("data_collections", []):
                    if dc.get("data_collection_tag") == dc_tag:
                        component["dc_id"] = dc["_id"]
                        component["dc_config"] = {
                            "_id": dc["_id"],
                            "type": dc.get("type"),
                            "metatype": dc.get("metatype"),
                            "description": dc.get("description"),
                            "data_collection_tag": dc.get("data_collection_tag"),
                            "dc_specific_properties": dc.get("dc_specific_properties"),
                        }
                        break

            # Resolve geojson_dc_tag to geojson_dc_id (for choropleth map components)
            geojson_dc_tag = component.get("geojson_dc_tag")
            if geojson_dc_tag and not component.get("geojson_dc_id"):
                for dc in wf.get("data_collections", []):
                    if dc.get("data_collection_tag") == geojson_dc_tag:
                        component["geojson_dc_id"] = str(dc["_id"])
                        logger.debug(
                            f"Resolved geojson_dc_tag '{geojson_dc_tag}' "
                            f"to geojson_dc_id {dc['_id']}"
                        )
                        break

            return


def _regenerate_component_fields(component: dict) -> None:
    """Regenerate component fields from dc_config after tag resolution.

    For Image components: Regenerate s3_base_folder from dc_config.
    For MultiQC components: Additional regeneration handled in MultiQC models.
    """
    comp_type = component.get("component_type", "")

    # Image component: Regenerate s3_base_folder from DC config if not present
    if comp_type == "image" and not component.get("s3_base_folder"):
        dc_config = component.get("dc_config", {})
        dc_specific_props = dc_config.get("dc_specific_properties", {})
        s3_base_folder = dc_specific_props.get("s3_base_folder")
        if s3_base_folder:
            component["s3_base_folder"] = s3_base_folder
            logger.debug(
                f"Regenerated s3_base_folder for image component from DC config: {s3_base_folder}"
            )


def _regenerate_component_indices(dashboard_dict: dict) -> None:
    """Generate new UUIDs for UUID-like component indexes; preserve semantic ones."""
    if "stored_metadata" not in dashboard_dict:
        return

    layout_keys = ["left_panel_layout_data", "right_panel_layout_data", "stored_layout_data"]

    for component in dashboard_dict["stored_metadata"]:
        old_index = component.get("index", "")
        # Keep semantic indexes (e.g. "multiqc-sampling-date"); only replace UUID-like ones
        is_uuid_like = isinstance(old_index, str) and (
            old_index.count("-") >= 4 or len(old_index) > 30
        )
        if not is_uuid_like:
            continue

        new_index = str(uuid.uuid4())
        component["index"] = new_index

        for layout_key in layout_keys:
            for layout_item in dashboard_dict.get(layout_key, []):
                if layout_item.get("i") == f"box-{old_index}":
                    layout_item["i"] = f"box-{new_index}"


def _filter_unresolved_components(dashboard_dict: dict) -> None:
    """Remove components whose DC could not be resolved.

    Disabled for now: the file scanner (which removes DCs) is disabled,
    and the aggressive dc_id check was stripping valid components whose
    tags hadn't been resolved yet (the frontend resolves them at render time).
    """
    # TODO: Re-enable when file scanner is active, but use dc_tag validation
    # against the project instead of dc_id presence check.
    pass


def _import_multi_tab_dashboard(
    yaml_data: dict,
    project_id: PyObjectId,
    overwrite: bool,
    current_user: User,
) -> dict[str, Any]:
    """
    Import a multi-tab dashboard from YAML data with main_dashboard and tabs structure.

    Args:
        yaml_data: Parsed YAML dictionary with main_dashboard and tabs keys
        project_id: Target project ID
        overwrite: Whether to update existing dashboards with same titles
        current_user: Current authenticated user

    Returns:
        Import result with main dashboard ID and child tab IDs
    """
    main_dashboard_data = yaml_data.get("main_dashboard")
    tabs_data = yaml_data.get("tabs", [])

    if not main_dashboard_data:
        raise HTTPException(status_code=400, detail="Multi-tab YAML missing 'main_dashboard' key")

    # Import main dashboard first
    main_yaml = yaml.dump(main_dashboard_data, default_flow_style=False, allow_unicode=True)
    main_lite = DashboardDataLite.from_yaml(main_yaml)

    # Check for existing main dashboard
    existing_main = dashboards_collection.find_one(
        {"title": main_lite.title, "project_id": ObjectId(project_id)}
    )
    if existing_main and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Dashboard '{main_lite.title}' already exists in this project. "
            "Use --overwrite to update it.",
        )

    main_dashboard_dict = main_lite.to_full()
    main_dashboard_dict["is_main_tab"] = True  # Ensure it's marked as main tab

    # Set dashboard ID and project
    main_dashboard_id = existing_main["dashboard_id"] if existing_main else ObjectId()
    main_dashboard_dict["dashboard_id"] = main_dashboard_id
    main_dashboard_dict["_id"] = (
        main_dashboard_id  # CRITICAL: Ensure _id = dashboard_id for MongoDB
    )
    main_dashboard_dict["project_id"] = ObjectId(project_id)
    main_dashboard_dict["last_saved_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Set version and permissions
    if existing_main:
        main_dashboard_dict["version"] = existing_main.get("version", 1) + 1
        main_dashboard_dict["permissions"] = existing_main.get(
            "permissions",
            {"owners": [{"_id": ObjectId(current_user.id), "email": current_user.email}]},
        )
    else:
        main_dashboard_dict["version"] = 1
        main_dashboard_dict["permissions"] = {
            "owners": [{"_id": ObjectId(current_user.id), "email": current_user.email}],
            "editors": [],
            "viewers": [],
        }

    # Resolve tags and regenerate fields for main dashboard components
    for component in main_dashboard_dict.get("stored_metadata", []):
        _resolve_workflow_tags(component, project_id=project_id)
        _regenerate_component_fields(component)
    # Remove components whose DC was not found in the project (e.g. removed by file scanner)
    _filter_unresolved_components(main_dashboard_dict)
    _regenerate_component_indices(main_dashboard_dict)

    # Validate and insert/update main dashboard
    try:
        main_dashboard = DashboardData.from_mongo(main_dashboard_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Main dashboard validation failed: {e}") from e

    is_update = existing_main is not None
    if is_update and existing_main is not None:
        update_doc = main_dashboard.mongo()
        update_doc["_id"] = existing_main["_id"]
        result = dashboards_collection.replace_one({"_id": existing_main["_id"]}, update_doc)
        if result.modified_count == 0 and result.matched_count == 0:
            raise HTTPException(status_code=500, detail="Failed to update main dashboard.")
    else:
        result = dashboards_collection.insert_one(main_dashboard.mongo())
        if not result.inserted_id:
            raise HTTPException(status_code=500, detail="Failed to import main dashboard.")

    # Import child tabs
    imported_tabs = []
    for idx, tab_data in enumerate(tabs_data):
        tab_yaml = yaml.dump(tab_data, default_flow_style=False, allow_unicode=True)
        tab_lite = DashboardDataLite.from_yaml(tab_yaml)

        # Check for existing tab if overwrite is requested
        existing_tab = None
        if overwrite:
            existing_tab = dashboards_collection.find_one(
                {
                    "title": tab_lite.title,
                    "parent_dashboard_id": main_dashboard_id,
                    "project_id": ObjectId(project_id),
                }
            )

        tab_dashboard_dict = tab_lite.to_full()
        tab_dashboard_dict["is_main_tab"] = False
        tab_dashboard_dict["parent_dashboard_id"] = main_dashboard_id
        tab_dashboard_dict["tab_order"] = idx + 1  # Start from 1 (main tab is 0)

        # Set dashboard ID and project
        tab_dashboard_id = existing_tab["dashboard_id"] if existing_tab else ObjectId()
        tab_dashboard_dict["dashboard_id"] = tab_dashboard_id
        tab_dashboard_dict["_id"] = tab_dashboard_id  # CRITICAL: Ensure _id = dashboard_id
        tab_dashboard_dict["project_id"] = ObjectId(project_id)
        tab_dashboard_dict["last_saved_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Set version and permissions
        if existing_tab:
            tab_dashboard_dict["version"] = existing_tab.get("version", 1) + 1
            tab_dashboard_dict["permissions"] = existing_tab.get(
                "permissions",
                {"owners": [{"_id": ObjectId(current_user.id), "email": current_user.email}]},
            )
        else:
            tab_dashboard_dict["version"] = 1
            tab_dashboard_dict["permissions"] = {
                "owners": [{"_id": ObjectId(current_user.id), "email": current_user.email}],
                "editors": [],
                "viewers": [],
            }

        # Resolve tags and regenerate fields for tab components
        for component in tab_dashboard_dict.get("stored_metadata", []):
            _resolve_workflow_tags(component, project_id=project_id)
            _regenerate_component_fields(component)
        _filter_unresolved_components(tab_dashboard_dict)
        _regenerate_component_indices(tab_dashboard_dict)

        # Validate and insert/update tab
        try:
            tab_dashboard = DashboardData.from_mongo(tab_dashboard_dict)
        except Exception as e:
            logger.error(f"Tab validation failed for '{tab_lite.title}': {e}")
            continue

        tab_is_update = existing_tab is not None
        if tab_is_update and existing_tab is not None:
            update_doc = tab_dashboard.mongo()
            update_doc["_id"] = existing_tab["_id"]
            tab_result = dashboards_collection.replace_one({"_id": existing_tab["_id"]}, update_doc)
            if tab_result.modified_count == 0 and tab_result.matched_count == 0:
                logger.error(f"Failed to update tab '{tab_lite.title}'")
                continue
        else:
            tab_result = dashboards_collection.insert_one(tab_dashboard.mongo())
            if not tab_result.inserted_id:
                logger.error(f"Failed to import tab '{tab_lite.title}'")
                continue

        imported_tabs.append({"title": tab_lite.title, "dashboard_id": str(tab_dashboard_id)})

    action = "Updated" if is_update else "Imported"
    logger.info(
        f"{action} multi-tab dashboard: {main_dashboard.title} (ID: {main_dashboard_id}) "
        f"with {len(imported_tabs)} tabs by user {current_user.email}"
    )

    return {
        "success": True,
        "updated": is_update,
        "message": f"Multi-tab dashboard {'updated' if is_update else 'imported'} successfully",
        "dashboard_id": str(main_dashboard_id),
        "title": main_dashboard.title,
        "project_id": str(project_id),
        "tabs": imported_tabs,
        "dash_url": settings.dash.external_url,
    }


@dashboards_endpoint_router.post("/import/yaml")
async def import_dashboard_from_yaml(
    yaml_content: str = Body(..., media_type="text/plain"),
    project_id: PyObjectId | None = None,
    overwrite: bool = False,
    current_user: User = Depends(get_current_user),
):
    """
    Import a dashboard from YAML content.

    Supports both single dashboard and multi-tab dashboard formats:
    - Single: Standard YAML with title, components, etc.
    - Multi-tab: YAML with main_dashboard and tabs keys

    A new dashboard_id will be generated, and the current user will be set as owner.

    If `overwrite=True` and a dashboard with the same title exists in the project,
    the existing dashboard will be updated instead of creating a new one.

    Project identification:
    - If `project_id` is provided, uses that project directly
    - If `project_id` is not provided, extracts `project_tag` from YAML and
      looks up the project by name

    Args:
        yaml_content: The YAML content defining the dashboard(s)
        project_id: Optional project ID (if not provided, uses project_tag from YAML)
        overwrite: If True, update existing dashboard with same title (default: False)
        current_user: The authenticated user (will be set as owner)

    Returns:
        Created/updated dashboard information including dashboard_id
    """
    # Allow anonymous users in single-user mode (they have admin privileges)
    if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
        if not settings.auth.is_single_user_mode:
            raise HTTPException(
                status_code=403,
                detail="Anonymous users cannot import dashboards. Please login to continue.",
            )

    # Parse YAML to detect format
    try:
        yaml_data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}") from e

    # Detect multi-tab format
    if isinstance(yaml_data, dict) and "main_dashboard" in yaml_data:
        # Multi-tab format: {main_dashboard: {...}, tabs: [...]}

        # Resolve project_id from main_dashboard if not provided
        if project_id is None:
            main_data = yaml_data.get("main_dashboard", {})
            project_tag = main_data.get("project_tag")
            if not project_tag:
                raise HTTPException(
                    status_code=400,
                    detail="Either project_id parameter or project_tag in main_dashboard is required",
                )
            project = projects_collection.find_one({"name": project_tag})
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail=f"Project '{project_tag}' not found. "
                    "Make sure the project_tag matches an existing project name.",
                )
            project_id = project["_id"]

        if not check_project_permission(project_id, current_user, "editor"):
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to create dashboards in this project.",
            )

        return _import_multi_tab_dashboard(yaml_data, project_id, overwrite, current_user)

    # Single dashboard format
    try:
        lite = DashboardDataLite.from_yaml(yaml_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}") from e

    # Resolve project_id from YAML project_tag if not provided
    if project_id is None:
        if not lite.project_tag:
            raise HTTPException(
                status_code=400,
                detail="Either project_id parameter or project_tag in YAML is required",
            )
        project = projects_collection.find_one({"name": lite.project_tag})
        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Project '{lite.project_tag}' not found. "
                "Make sure the project_tag in your YAML matches an existing project name.",
            )
        project_id = project["_id"]

    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to create dashboards in this project.",
        )

    # Check for existing dashboard with same title
    existing_dashboard = dashboards_collection.find_one(
        {"title": lite.title, "project_id": ObjectId(project_id)}
    )
    if existing_dashboard and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Dashboard '{lite.title}' already exists in this project. "
            "Use --overwrite to update it.",
        )
    if existing_dashboard:
        logger.info(
            f"Found existing dashboard '{lite.title}' "
            f"(ID: {existing_dashboard['dashboard_id']}) - will update"
        )

    dashboard_dict = lite.to_full()

    # Handle tab relationships for child tabs
    if not lite.is_main_tab and lite.parent_dashboard_tag:
        # Find parent dashboard by title in the same project
        parent_dashboard = dashboards_collection.find_one(
            {
                "title": lite.parent_dashboard_tag,
                "project_id": ObjectId(project_id),
                "is_main_tab": {"$ne": False},
            }
        )
        if not parent_dashboard:
            raise HTTPException(
                status_code=400,
                detail=f"Parent dashboard '{lite.parent_dashboard_tag}' not found in this project. "
                "Import the main dashboard first, then import child tabs.",
            )
        dashboard_dict["parent_dashboard_id"] = parent_dashboard["dashboard_id"]
        dashboard_dict["is_main_tab"] = False

    # Set dashboard ID and project
    new_dashboard_id = existing_dashboard["dashboard_id"] if existing_dashboard else ObjectId()
    dashboard_dict["dashboard_id"] = new_dashboard_id
    dashboard_dict["project_id"] = ObjectId(project_id)
    dashboard_dict["last_saved_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Set version and permissions based on create vs update
    if existing_dashboard:
        dashboard_dict["version"] = existing_dashboard.get("version", 1) + 1
        dashboard_dict["permissions"] = existing_dashboard.get(
            "permissions",
            {"owners": [{"_id": ObjectId(current_user.id), "email": current_user.email}]},
        )
    else:
        dashboard_dict["version"] = 1
        dashboard_dict["permissions"] = {
            "owners": [{"_id": ObjectId(current_user.id), "email": current_user.email}],
            "editors": [],
            "viewers": [],
        }

    # Resolve tags to MongoDB IDs, regenerate fields from DC config, and regenerate component indices
    for component in dashboard_dict.get("stored_metadata", []):
        _resolve_workflow_tags(component, project_id=project_id)
        _regenerate_component_fields(
            component
        )  # Regenerate s3_base_folder, etc. after dc_config is populated
    _filter_unresolved_components(dashboard_dict)
    _regenerate_component_indices(dashboard_dict)

    try:
        dashboard = DashboardData.from_mongo(dashboard_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Dashboard validation failed: {e}") from e

    # Insert or update in database
    is_update = existing_dashboard is not None
    if is_update and existing_dashboard is not None:
        # Preserve the existing MongoDB _id to avoid immutable field error
        update_doc = dashboard.mongo()
        update_doc["_id"] = existing_dashboard["_id"]
        result = dashboards_collection.replace_one({"_id": existing_dashboard["_id"]}, update_doc)
        if result.modified_count == 0 and result.matched_count == 0:
            raise HTTPException(status_code=500, detail="Failed to update dashboard.")
    else:
        result = dashboards_collection.insert_one(dashboard.mongo())
        if not result.inserted_id:
            raise HTTPException(status_code=500, detail="Failed to import dashboard.")

    action = "Updated" if is_update else "Imported"
    logger.info(
        f"{action} dashboard from YAML: {dashboard.title} (ID: {new_dashboard_id}) "
        f"by user {current_user.email}"
    )

    return {
        "success": True,
        "updated": is_update,
        "message": f"Dashboard {'updated' if is_update else 'imported'} successfully",
        "dashboard_id": str(new_dashboard_id),
        "title": dashboard.title,
        "project_id": str(project_id),
        "dash_url": settings.dash.external_url,
    }


# ============================================================================
# YAML Endpoints (Simple Pydantic-based validation)
# These endpoints use DashboardDataLite for lightweight YAML validation
# ============================================================================


@dashboards_endpoint_router.get("/{dashboard_id}/yaml")
async def export_dashboard_as_yaml(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """Export dashboard as YAML.

    For main tabs with children: Returns a single YAML with nested structure.
    For standalone/child dashboards: Returns a single dashboard YAML.

    Multi-tab structure:
        main_dashboard:
            title: "Main Dashboard"
            components: [...]
        tabs:
            - title: "Tab 1"
              components: [...]

    Args:
        dashboard_id: The dashboard ID to export

    Returns:
        YAML content with application/x-yaml content type
    """
    # Find dashboard
    dashboard_doc = dashboards_collection.find_one({"dashboard_id": ObjectId(dashboard_id)})
    if not dashboard_doc:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Check permissions (read access)
    project_id = dashboard_doc.get("project_id")
    if project_id:
        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        is_public = project.get("is_public", False) if project else False
        project_name = project.get("name", "") if project else ""
    else:
        is_public = dashboard_doc.get("is_public", False)
        project_name = ""

    if not is_public and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if this is a main tab with child tabs
    is_main_tab = dashboard_doc.get("is_main_tab", True)
    child_tabs = []
    if is_main_tab:
        child_tabs_docs = list(
            dashboards_collection.find({"parent_dashboard_id": ObjectId(dashboard_id)}).sort(
                "tab_order", 1
            )
        )
        child_tabs = child_tabs_docs

    # Single dashboard export (no children or is a child tab itself)
    if not child_tabs and is_main_tab:
        # Enrich dashboard with workflow and data collection tags from MongoDB
        from depictio.models.yaml_serialization.utils import enrich_dashboard_with_tags

        enriched_dashboard = enrich_dashboard_with_tags(dashboard_doc)

        # Convert to DashboardDataLite for export
        lite = DashboardDataLite.from_full(enriched_dashboard)
        lite.project_tag = project_name
        yaml_content = lite.to_yaml()

        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{dashboard_doc.get("title", "dashboard")}.yaml"'
            },
        )

    # Multi-tab export: main dashboard + child tabs in single YAML
    multi_tab_dict: dict[str, Any] = {}

    # Enrich main dashboard with workflow and data collection tags
    from depictio.models.yaml_serialization.utils import enrich_dashboard_with_tags

    enriched_main_dashboard = enrich_dashboard_with_tags(dashboard_doc)

    # Export main dashboard — apply ordering, default stripping, and section sentinels
    main_lite = DashboardDataLite.from_full(enriched_main_dashboard)
    main_lite.project_tag = project_name
    main_dict = main_lite.model_dump(exclude_none=True, mode="json")
    DashboardDataLite._strip_dashboard_defaults(main_dict)
    for field in ["is_main_tab", "tab_order", "parent_dashboard_tag"]:
        main_dict.pop(field, None)
    if "components" in main_dict:
        main_dict["components"] = [
            DashboardDataLite._clean_component_for_yaml(c) for c in main_dict["components"]
        ]
    multi_tab_dict["main_dashboard"] = DashboardDataLite._build_ordered_dashboard_dict(main_dict)

    # Export child tabs
    tabs_list = []
    for child_doc in child_tabs:
        # Enrich child tab with workflow and data collection tags
        enriched_child = enrich_dashboard_with_tags(child_doc)

        child_lite = DashboardDataLite.from_full(enriched_child)
        child_lite.project_tag = project_name
        child_dict = child_lite.model_dump(exclude_none=True, mode="json")
        DashboardDataLite._strip_dashboard_defaults(child_dict)
        for field in ["is_main_tab", "parent_dashboard_tag", "project_tag"]:
            child_dict.pop(field, None)
        if "components" in child_dict:
            child_dict["components"] = [
                DashboardDataLite._clean_component_for_yaml(c) for c in child_dict["components"]
            ]
        tabs_list.append(DashboardDataLite._build_ordered_dashboard_dict(child_dict))

    if tabs_list:
        multi_tab_dict["tabs"] = tabs_list

    # Convert to YAML and inject section comment separators
    raw_yaml = yaml.dump(
        multi_tab_dict, default_flow_style=False, sort_keys=False, allow_unicode=True, indent=4
    )
    yaml_content = DashboardDataLite._apply_section_comments(raw_yaml)

    return Response(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{dashboard_doc.get("title", "dashboard")}.yaml"'
        },
    )


@dashboards_endpoint_router.get("/{dashboard_id}/yaml/family")
async def export_dashboard_family_as_yaml(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """Export dashboard family (main tab + all child tabs) as ZIP archive.

    Returns a ZIP file containing YAML files for the main dashboard and
    all its child tabs, preserving the tab hierarchy for re-import.

    Args:
        dashboard_id: The main dashboard ID to export

    Returns:
        ZIP file containing YAML files
    """
    import io
    import zipfile

    # Find main dashboard
    main_dashboard = dashboards_collection.find_one({"dashboard_id": ObjectId(dashboard_id)})
    if not main_dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Verify this is a main tab
    if not main_dashboard.get("is_main_tab", True):
        raise HTTPException(
            status_code=400,
            detail="The specified dashboard is a child tab. "
            "Use the parent dashboard ID for family export.",
        )

    # Check permissions (read access)
    project_id = main_dashboard.get("project_id")
    if project_id:
        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        is_public = project.get("is_public", False) if project else False
        project_name = project.get("name", "") if project else ""
    else:
        is_public = main_dashboard.get("is_public", False)
        project_name = ""

    if not is_public and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Get all child tabs
    child_tabs = list(
        dashboards_collection.find({"parent_dashboard_id": ObjectId(dashboard_id)}).sort(
            "tab_order", 1
        )
    )

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Export main dashboard
        main_lite = DashboardDataLite.from_full(main_dashboard)
        main_lite.project_tag = project_name
        main_yaml = main_lite.to_yaml()

        # Use sanitized filename
        main_title = main_dashboard.get("title", "dashboard").replace("/", "_").replace("\\", "_")
        zip_file.writestr(f"{main_title}.yaml", main_yaml)

        # Export each child tab
        for child in child_tabs:
            child_lite = DashboardDataLite.from_full(child)
            child_lite.project_tag = project_name
            child_lite.parent_dashboard_tag = main_dashboard.get("title", "")
            child_yaml = child_lite.to_yaml()

            child_title = child.get("title", "untitled").replace("/", "_").replace("\\", "_")
            zip_file.writestr(f"{child_title}.yaml", child_yaml)

    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{main_title}_family.zip"'},
    )


@dashboards_endpoint_router.post("/yaml/validate")
async def validate_yaml_content(
    yaml_content: str = Body(..., media_type="text/plain"),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Validate YAML content against DashboardDataLite schema.

    Uses Pydantic validation to check if the YAML content is valid.

    Args:
        yaml_content: YAML string to validate

    Returns:
        Validation result with is_valid flag and any errors
    """
    is_valid, errors = DashboardDataLite.validate_yaml(yaml_content)

    return {
        "valid": is_valid,
        "errors": errors,
    }


@dashboards_endpoint_router.get("/yaml/schema")
async def get_yaml_schema() -> dict[str, Any]:
    """Get JSON Schema for YAML validation.

    Returns the JSON Schema that describes valid dashboard YAML structure.
    Can be used for IDE autocompletion and external validation tools.

    Returns:
        JSON Schema for DashboardDataLite
    """
    return DashboardDataLite.model_json_schema()


# =============================================================================
# JSON Import/Export Endpoints (with Data Integrity Verification)
# =============================================================================


def _generate_schema_hash(columns: list[dict]) -> str:
    """Generate a hash from column specifications for integrity verification.

    Args:
        columns: List of column specs with 'name' and 'type' keys

    Returns:
        SHA-256 hash of the column schema
    """
    import hashlib

    # Sort columns by name for consistent hashing
    sorted_cols = sorted(columns, key=lambda x: x.get("name", ""))
    schema_str = "|".join(f"{c.get('name', '')}:{c.get('type', '')}" for c in sorted_cols)
    return f"sha256:{hashlib.sha256(schema_str.encode()).hexdigest()[:16]}"


def _extract_data_integrity_metadata(
    dashboard_doc: dict, project_doc: dict | None = None
) -> list[dict]:
    """Extract data integrity metadata from dashboard components.

    Collects schema information from data collections referenced by the dashboard.

    Args:
        dashboard_doc: The dashboard document from MongoDB
        project_doc: The project document (optional, fetched if not provided)

    Returns:
        List of data collection integrity entries
    """
    from depictio.api.v1.db import data_collections_collection

    data_integrity = []
    seen_collections = set()

    # Get stored_metadata which contains component configurations
    stored_metadata = dashboard_doc.get("stored_metadata", [])

    for component in stored_metadata:
        dc_id = component.get("data_collection_id")
        if not dc_id or dc_id in seen_collections:
            continue

        seen_collections.add(dc_id)

        # Fetch data collection details
        try:
            dc_doc = data_collections_collection.find_one({"_id": ObjectId(dc_id)})
            if not dc_doc:
                continue

            # Extract column specifications
            columns_specs = dc_doc.get("config", {}).get("columns_specs", [])
            columns = [{"name": col.get("name"), "type": col.get("dtype")} for col in columns_specs]

            integrity_entry = {
                "workflow_tag": dc_doc.get("workflow_tag", ""),
                "data_collection_tag": dc_doc.get("data_collection_tag", ""),
                "schema": {
                    "columns": columns,
                    "row_count": dc_doc.get("config", {}).get("row_count", 0),
                },
                "schema_hash": _generate_schema_hash(columns),
            }
            data_integrity.append(integrity_entry)

        except Exception as e:
            logger.warning(f"Failed to get integrity info for DC {dc_id}: {e}")
            continue

    return data_integrity


def _validate_data_collection_integrity(
    expected_collections: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Validate data collection integrity against expected schemas.

    Args:
        expected_collections: List of expected data collection entries with
            workflow_tag, data_collection_tag, and schema_hash.

    Returns:
        Tuple of (warnings list, integrity_checks list).
        Warnings include both errors (missing collections) and warnings (schema mismatch).
    """
    from depictio.api.v1.db import data_collections_collection

    warnings = []
    integrity_checks = []

    for expected_dc in expected_collections:
        workflow_tag = expected_dc.get("workflow_tag", "")
        dc_tag = expected_dc.get("data_collection_tag", "")
        expected_hash = expected_dc.get("schema_hash", "")

        dc_doc = data_collections_collection.find_one(
            {"workflow_tag": workflow_tag, "data_collection_tag": dc_tag}
        )

        check_result = {
            "workflow_tag": workflow_tag,
            "data_collection_tag": dc_tag,
            "found": dc_doc is not None,
            "schema_match": False,
        }

        if not dc_doc:
            warnings.append(
                {
                    "type": "missing_collection",
                    "message": f"Data collection '{workflow_tag}/{dc_tag}' not found",
                    "severity": "error",
                }
            )
        else:
            columns_specs = dc_doc.get("config", {}).get("columns_specs", [])
            columns = [{"name": col.get("name"), "type": col.get("dtype")} for col in columns_specs]
            current_hash = _generate_schema_hash(columns)
            check_result["schema_match"] = current_hash == expected_hash
            check_result["current_hash"] = current_hash
            check_result["expected_hash"] = expected_hash

            if current_hash != expected_hash:
                warnings.append(
                    {
                        "type": "schema_mismatch",
                        "message": f"Schema mismatch for '{workflow_tag}/{dc_tag}': expected {expected_hash}, found {current_hash}",
                        "severity": "warning",
                        "details": {
                            "expected_columns": expected_dc.get("schema", {}).get("columns", []),
                            "current_columns": columns,
                        },
                    }
                )

        integrity_checks.append(check_result)

    return warnings, integrity_checks


@dashboards_endpoint_router.get("/{dashboard_id}/json")
async def export_dashboard_as_json(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Export dashboard as JSON with data integrity metadata.

    Returns a JSON representation of the dashboard including:
    - Export metadata (version, timestamp, source)
    - Dashboard configuration (title, components, layout)
    - Data integrity information (collection schemas and hashes)

    Args:
        dashboard_id: The dashboard ID to export
        current_user: Current authenticated user

    Returns:
        JSON object with dashboard data and integrity metadata
    """
    dashboard_doc = dashboards_collection.find_one({"dashboard_id": ObjectId(dashboard_id)})
    if not dashboard_doc:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Get project info
    project_id = dashboard_doc.get("project_id")
    project_doc = None
    project_tag = ""
    if project_id:
        project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
        if project_doc:
            project_tag = project_doc.get("name", "")

    # Extract data integrity metadata
    data_integrity = _extract_data_integrity_metadata(dashboard_doc, project_doc)

    # Build export JSON structure
    export_data = {
        "_depictio_export_version": "1.0",
        "_export_timestamp": datetime.utcnow().isoformat() + "Z",
        "_export_source": {
            "dashboard_id": dashboard_id,
            "project_tag": project_tag,
        },
        "dashboard": {
            "title": dashboard_doc.get("title", ""),
            "subtitle": dashboard_doc.get("subtitle", ""),
            "is_main_tab": dashboard_doc.get("is_main_tab", True),
            "tab_order": dashboard_doc.get("tab_order", 0),
            "main_tab_name": dashboard_doc.get("main_tab_name"),
            "tab_icon": dashboard_doc.get("tab_icon"),
            "tab_icon_color": dashboard_doc.get("tab_icon_color"),
            "stored_metadata": dashboard_doc.get("stored_metadata", []),
            "stored_layout_data": dashboard_doc.get("stored_layout_data", []),
        },
        "_data_integrity": {
            "data_collections": data_integrity,
        },
    }

    # Convert all ObjectIds to strings for JSON serialization
    from depictio.models.models.base import convert_objectid_to_str

    return convert_objectid_to_str(export_data)


@dashboards_endpoint_router.post("/import/json")
async def import_dashboard_from_json(
    json_content: dict[str, Any],
    project_id: str | None = None,
    validate_integrity: bool = True,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Import a dashboard from JSON content with optional integrity validation.

    Creates a new dashboard from the provided JSON configuration.
    Optionally validates that data collection schemas match the export.

    Args:
        json_content: The JSON content defining the dashboard
        project_id: Target project ID (required if not in JSON)
        validate_integrity: Whether to validate data collection schemas (default: True)
        current_user: Current authenticated user

    Returns:
        Import result with dashboard ID and any validation warnings
    """
    # Validate export version
    export_version = json_content.get("_depictio_export_version")
    if not export_version:
        raise HTTPException(
            status_code=400, detail="Invalid JSON format: missing _depictio_export_version"
        )

    if export_version != "1.0":
        raise HTTPException(
            status_code=400, detail=f"Unsupported export version: {export_version}. Expected 1.0"
        )

    # Get dashboard data
    dashboard_data = json_content.get("dashboard")
    if not dashboard_data:
        raise HTTPException(status_code=400, detail="Invalid JSON format: missing dashboard data")

    # Resolve project ID
    if not project_id:
        # Try to get from export source
        export_source = json_content.get("_export_source", {})
        project_tag = export_source.get("project_tag")

        if project_tag:
            project_doc = projects_collection.find_one({"name": project_tag})
            if project_doc:
                project_id = str(project_doc["_id"])

    if not project_id:
        raise HTTPException(
            status_code=400,
            detail="project_id is required. Either provide it as a parameter or ensure project_tag in JSON matches an existing project.",
        )

    # Validate project exists and user has editor access
    project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
    if not project_doc:
        raise HTTPException(status_code=404, detail="Project not found")

    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to import dashboards to this project"
        )

    # Validate data integrity if requested
    validation_warnings: list[dict] = []
    if validate_integrity:
        integrity_data = json_content.get("_data_integrity", {})
        expected_collections = integrity_data.get("data_collections", [])
        validation_warnings, _ = _validate_data_collection_integrity(expected_collections)

        # Check for critical errors
        critical_errors = [w for w in validation_warnings if w.get("severity") == "error"]
        if critical_errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Import failed due to missing data collections",
                    "errors": critical_errors,
                },
            )

    # Generate new dashboard ID (using ObjectId like other dashboard creation endpoints)
    new_dashboard_id = ObjectId()

    # Build new dashboard document with all required fields
    new_dashboard = {
        "dashboard_id": new_dashboard_id,
        "project_id": ObjectId(project_id),
        "title": dashboard_data.get("title", "Imported Dashboard"),
        "subtitle": dashboard_data.get("subtitle", ""),
        "version": 1,
        "icon": dashboard_data.get("icon", "mdi:view-dashboard"),
        "icon_color": dashboard_data.get("icon_color", "orange"),
        "icon_variant": dashboard_data.get("icon_variant", "filled"),
        "workflow_system": dashboard_data.get("workflow_system", "none"),
        "notes_content": dashboard_data.get("notes_content", ""),
        "is_main_tab": dashboard_data.get("is_main_tab", True),
        "tab_order": dashboard_data.get("tab_order", 0),
        "main_tab_name": dashboard_data.get("main_tab_name"),
        "tab_icon": dashboard_data.get("tab_icon"),
        "tab_icon_color": dashboard_data.get("tab_icon_color"),
        "stored_metadata": dashboard_data.get("stored_metadata", []),
        "stored_layout_data": dashboard_data.get("stored_layout_data", []),
        "stored_children_data": dashboard_data.get("stored_children_data", []),
        "tmp_children_data": [],
        "stored_edit_dashboard_mode_button": [],
        "left_panel_layout_data": dashboard_data.get("left_panel_layout_data", []),
        "right_panel_layout_data": dashboard_data.get("right_panel_layout_data", []),
        "buttons_data": dashboard_data.get(
            "buttons_data",
            {
                "unified_edit_mode": True,
                "add_components_button": {"count": 0},
            },
        ),
        "stored_add_button": {"count": 0},
        "permissions": {
            "owners": [{"_id": ObjectId(str(current_user.id)), "email": current_user.email}],
            "viewers": [],
        },
        "is_public": project_doc.get("is_public", False),
        "last_saved_ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Insert dashboard
    try:
        dashboards_collection.insert_one(new_dashboard)
        logger.info(f"Imported dashboard: {new_dashboard['title']} (ID: {new_dashboard_id})")
    except Exception as e:
        logger.error(f"Failed to import dashboard: {e}")
        raise HTTPException(status_code=500, detail="Failed to import dashboard")

    return {
        "success": True,
        "message": "Dashboard imported successfully",
        "dashboard_id": str(new_dashboard_id),
        "title": new_dashboard["title"],
        "warnings": validation_warnings if validation_warnings else None,
    }


@dashboards_endpoint_router.post("/json/validate")
async def validate_json_import(
    json_content: dict[str, Any],
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Validate JSON import content without actually importing.

    Performs all validation checks and returns detailed results including:
    - Format validation
    - Project resolution
    - Data integrity checks

    Args:
        json_content: The JSON content to validate
        project_id: Target project ID (optional)
        current_user: Current authenticated user

    Returns:
        Validation result with is_valid flag and detailed warnings/errors
    """
    validation_result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "project_resolved": None,
        "integrity_checks": [],
    }

    # Check export version
    export_version = json_content.get("_depictio_export_version")
    if not export_version:
        validation_result["valid"] = False
        validation_result["errors"].append(
            {"field": "_depictio_export_version", "message": "Missing export version field"}
        )
    elif export_version != "1.0":
        validation_result["valid"] = False
        validation_result["errors"].append(
            {
                "field": "_depictio_export_version",
                "message": f"Unsupported version: {export_version}",
            }
        )

    # Check dashboard data
    dashboard_data = json_content.get("dashboard")
    if not dashboard_data:
        validation_result["valid"] = False
        validation_result["errors"].append(
            {"field": "dashboard", "message": "Missing dashboard data"}
        )
    elif not dashboard_data.get("title"):
        validation_result["warnings"].append(
            {"field": "dashboard.title", "message": "Dashboard title is empty"}
        )

    # Resolve project
    resolved_project = None
    if project_id:
        project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
        if project_doc:
            resolved_project = {"id": str(project_doc["_id"]), "name": project_doc.get("name")}
    else:
        export_source = json_content.get("_export_source", {})
        project_tag = export_source.get("project_tag")
        if project_tag:
            project_doc = projects_collection.find_one({"name": project_tag})
            if project_doc:
                resolved_project = {"id": str(project_doc["_id"]), "name": project_doc.get("name")}

    validation_result["project_resolved"] = resolved_project

    if not resolved_project:
        validation_result["valid"] = False
        validation_result["errors"].append(
            {"field": "project_id", "message": "Could not resolve target project"}
        )

    # Check data integrity using shared helper
    integrity_data = json_content.get("_data_integrity", {})
    expected_collections = integrity_data.get("data_collections", [])
    dc_warnings, integrity_checks = _validate_data_collection_integrity(expected_collections)

    validation_result["integrity_checks"] = integrity_checks

    # Convert warnings to validation result format
    for warning in dc_warnings:
        workflow_tag = (
            warning.get("message", "").split("'")[1] if "'" in warning.get("message", "") else ""
        )
        if warning.get("severity") == "error":
            validation_result["errors"].append(
                {"field": f"data_collection.{workflow_tag}", "message": "Data collection not found"}
            )
            validation_result["valid"] = False
        else:
            validation_result["warnings"].append(
                {
                    "field": f"data_collection.{workflow_tag}",
                    "message": "Schema has changed since export",
                }
            )

    return validation_result
