import asyncio
import json
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

import yaml
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

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
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
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
    permissions = project_data.get("permissions", {})
    owner_ids = [str(owner.get("_id", "")) for owner in permissions.get("owners", [])]
    editor_ids = [str(editor.get("_id", "")) for editor in permissions.get("editors", [])]
    current_user_id_str = str(current_user.id)

    if current_user_id_str in owner_ids:
        user_permission_level = "owner"
    elif current_user_id_str in editor_ids:
        user_permission_level = "editor"

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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
async def bulk_get_component_data_endpoint(
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
# YAML Import Endpoint (CLI support)
# ============================================================================


def _resolve_workflow_tags(component: dict) -> None:
    """Resolve workflow and data collection tags to MongoDB IDs.

    Searches projects for matching workflows and data collections,
    updating the component dict in place with wf_id, dc_id, and dc_config.
    """
    wf_tag = component.get("workflow_tag")
    dc_tag = component.get("data_collection_tag")

    if not wf_tag or component.get("wf_id"):
        return

    # Parse engine/name format (e.g., "python/iris_workflow")
    wf_name = wf_tag.split("/", 1)[1] if "/" in wf_tag else wf_tag

    for proj in projects_collection.find():
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
    """Generate new UUIDs for all components and update layout references."""
    if "stored_metadata" not in dashboard_dict:
        return

    layout_keys = ["left_panel_layout_data", "right_panel_layout_data", "stored_layout_data"]

    for component in dashboard_dict["stored_metadata"]:
        old_index = component.get("index")
        new_index = str(uuid.uuid4())
        component["index"] = new_index

        for layout_key in layout_keys:
            for layout_item in dashboard_dict.get(layout_key, []):
                if layout_item.get("i") == old_index:
                    layout_item["i"] = new_index


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

    # Check for existing main dashboard if overwrite is requested
    existing_main = None
    if overwrite:
        existing_main = dashboards_collection.find_one(
            {"title": main_lite.title, "project_id": ObjectId(project_id)}
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
        _resolve_workflow_tags(component)
        _regenerate_component_fields(component)
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
            _resolve_workflow_tags(component)
            _regenerate_component_fields(component)
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
    }


@dashboards_endpoint_router.post("/import/yaml")
async def import_dashboard_from_yaml(
    yaml_content: str,
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

    # Check for existing dashboard if overwrite is requested
    existing_dashboard = None
    if overwrite:
        existing_dashboard = dashboards_collection.find_one(
            {"title": lite.title, "project_id": ObjectId(project_id)}
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
        _resolve_workflow_tags(component)
        _regenerate_component_fields(
            component
        )  # Regenerate s3_base_folder, etc. after dc_config is populated
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
        # Convert to DashboardDataLite for export
        lite = DashboardDataLite.from_full(dashboard_doc)
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

    # Export main dashboard
    main_lite = DashboardDataLite.from_full(dashboard_doc)
    main_lite.project_tag = project_name
    main_dict = main_lite.model_dump(exclude_none=True, mode="json")

    # Remove tab-specific fields from main dashboard for cleaner export
    for field in ["is_main_tab", "tab_order", "parent_dashboard_tag"]:
        main_dict.pop(field, None)

    multi_tab_dict["main_dashboard"] = main_dict

    # Export child tabs
    tabs_list = []
    for child_doc in child_tabs:
        child_lite = DashboardDataLite.from_full(child_doc)
        child_lite.project_tag = project_name
        child_dict = child_lite.model_dump(exclude_none=True, mode="json")

        # Remove fields that are implicit in multi-tab structure
        for field in ["is_main_tab", "parent_dashboard_tag", "project_tag"]:
            child_dict.pop(field, None)

        tabs_list.append(child_dict)

    if tabs_list:
        multi_tab_dict["tabs"] = tabs_list

    # Convert to YAML
    yaml_content = yaml.dump(
        multi_tab_dict, default_flow_style=False, sort_keys=False, allow_unicode=True, indent=4
    )

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
    yaml_content: str,
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
