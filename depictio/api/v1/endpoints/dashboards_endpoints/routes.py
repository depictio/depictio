import asyncio
import json
import uuid
from datetime import datetime
from uuid import UUID

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import load_dashboards_from_db
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import TokenBeanie, User, UserBeanie
from depictio.models.yaml_serialization import (
    validate_dashboard_yaml,
    yaml_to_dashboard_dict,
)

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

    logger.info("Starting dashboard permissions sync with projects")

    # Get all dashboards
    dashboards = list(dashboards_collection.find({}))
    synced_count = 0
    failed_count = 0
    failed_dashboards = []

    for dashboard in dashboards:
        try:
            dashboard_id = dashboard.get("dashboard_id")
            project_id = dashboard.get("project_id")

            if not project_id:
                logger.warning(f"Dashboard {dashboard_id} has no project_id, skipping")
                failed_count += 1
                failed_dashboards.append({"dashboard_id": dashboard_id, "reason": "No project_id"})
                continue

            # Get project
            project = projects_collection.find_one({"_id": ObjectId(project_id)})
            if not project:
                logger.warning(
                    f"Project {project_id} not found for dashboard {dashboard_id}, skipping"
                )
                failed_count += 1
                failed_dashboards.append(
                    {"dashboard_id": dashboard_id, "reason": "Project not found"}
                )
                continue

            # Update dashboard to match project visibility and permissions
            update_data = {
                "is_public": project.get("is_public", False),
                # Note: We keep the dashboard permissions structure but rely on project permissions for access control
            }

            dashboards_collection.update_one({"dashboard_id": dashboard_id}, {"$set": update_data})

            synced_count += 1
            logger.debug(f"Synced dashboard {dashboard_id} with project {project_id}")

        except Exception as e:
            logger.error(
                f"Failed to sync dashboard {dashboard.get('dashboard_id', 'unknown')}: {e}"
            )
            failed_count += 1
            failed_dashboards.append(
                {"dashboard_id": dashboard.get("dashboard_id"), "reason": str(e)}
            )

    logger.info(f"Dashboard sync completed: {synced_count} synced, {failed_count} failed")

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


@dashboards_endpoint_router.get("/get/{dashboard_id}", response_model=DashboardData)
async def get_dashboard(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Fetch dashboard data related to a dashboard ID.
    Now uses project-based permissions instead of dashboard-specific permissions.
    """

    logger.debug(f"Current user ID: {current_user.id}")

    # First check if dashboard exists
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Get project_id from dashboard
    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check project-based permissions (viewer level required for reading)
    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this dashboard."
        )

    dashboard_data = DashboardData.from_mongo(dashboard_data)
    logger.debug(f"Dashboard access granted via project permissions for project {project_id}")

    return dashboard_data


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
    logger.info(f"🚀 Dashboard init for dashboard {dashboard_id}")

    # 1. Fetch dashboard with permission check
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Get project_id from dashboard
    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check project-based permissions
    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this dashboard."
        )

    dashboard = DashboardData.from_mongo(dashboard_data)
    logger.debug("✅ Dashboard access granted via project permissions")

    # 2. Determine user permission level
    # Need to fetch project for permissions check (lightweight query)
    from depictio.api.v1.endpoints.projects_endpoints.utils import (
        get_project_with_delta_locations,
    )

    project_data = await get_project_with_delta_locations(project_id, current_user)

    user_permission_level = "viewer"  # Default
    permissions = project_data.get("permissions", {})
    owner_ids = [str(owner.get("_id", "")) for owner in permissions.get("owners", [])]
    editor_ids = [str(editor.get("_id", "")) for editor in permissions.get("editors", [])]

    # Convert current_user.id to string for comparison (it's an ObjectId)
    current_user_id_str = str(current_user.id)

    logger.info(
        f"🔐 Permission check for user {current_user_id_str}:\n"
        f"   - Project owner IDs: {owner_ids}\n"
        f"   - Project editor IDs: {editor_ids}"
    )

    if current_user_id_str in owner_ids:
        user_permission_level = "owner"
    elif current_user_id_str in editor_ids:
        user_permission_level = "editor"

    logger.info(f"   - Determined permission level: {user_permission_level}")

    # 3. Build dashboard-only response
    # Frontend will fetch project data separately via /projects/get/from_id/{project_id}
    response = {
        "dashboard": dashboard.model_dump(),
        "project_id": str(project_id),
        "user_permissions": {
            "level": user_permission_level,
            "can_edit": user_permission_level in ["owner", "editor"],
            "can_delete": user_permission_level == "owner",
        },
    }

    # 4. Sanitize response (convert ObjectIds to strings for JSON serialization)
    sanitized_response = convert_objectid_to_str(response)

    logger.info(f"✅ Dashboard init complete for {dashboard_id}")

    return sanitized_response


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

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")

    result = load_dashboards_from_db(
        owner=user_id, admin_mode=False, user=current_user, include_child_tabs=include_child_tabs
    )

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return result["dashboards"]


@dashboards_endpoint_router.get("/list_all")
async def list_all_dashboards(
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a list of dashboards for the current user.
    """

    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")
    logger.info(f"Current user: {current_user}")

    result = load_dashboards_from_db(owner=user_id, admin_mode=True)

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

    logger.info(f"Attempting to change dashboard visibility to: {_public_status}")
    logger.info(f"Current user: {current_user.email}")
    logger.info(f"Dashboard ID: {dashboard_id}")

    # Get dashboard to find project_id
    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    project_id = dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check if user has owner permission on the project (required for visibility changes)
    if not check_project_permission(project_id, current_user, "owner"):
        raise HTTPException(
            status_code=403, detail="Only project owners can change dashboard visibility."
        )

    # Update the project's visibility (this will affect all dashboards in the project)
    project_result = projects_collection.find_one_and_update(
        {"_id": ObjectId(project_id)},
        {"$set": {"is_public": _public_status}},
        return_document=True,
    )

    if not project_result:
        raise HTTPException(status_code=404, detail="Project not found.")

    # Update all dashboards in this project to match project visibility
    dashboards_update_result = dashboards_collection.update_many(
        {"project_id": ObjectId(project_id)},
        {"$set": {"is_public": _public_status}},
    )

    logger.info(f"Project visibility changed to: {_public_status}")
    logger.info(
        f"Updated {dashboards_update_result.modified_count} dashboards in project {project_id}"
    )

    return {
        "success": True,
        "message": f"Project and all its dashboards changed visibility to: {'public' if _public_status else 'private'}",
        "is_public": _public_status,
        "dashboards_updated": dashboards_update_result.modified_count,
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
    """

    new_name = data.get("new_name", None)
    if not new_name:
        raise HTTPException(status_code=400, detail="No new name provided.")

    logger.info(f"New name: {new_name}")
    logger.info(f"Dashboard ID: {dashboard_id} of type {type(dashboard_id)}")

    # Get dashboard to find project_id
    dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    project_id = dashboard.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check if user has editor permission on the project (required for editing)
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
        logger.info(f"Dashboard name updated successfully to '{new_name}'.")
        return {"message": f"Dashboard name updated successfully to '{new_name}'."}
    else:
        raise HTTPException(status_code=500, detail="Failed to update dashboard name.")


@dashboards_endpoint_router.post("/save/{dashboard_id}")
async def save_dashboard(
    dashboard_id: PyObjectId,
    data: DashboardData,
    current_user: User = Depends(get_current_user),
):
    """
    Check if an entry with the same dashboard_id exists, if not, insert, if yes, update.
    """

    # Additional check for anonymous users (though get_current_user should already prevent this)
    if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
        raise HTTPException(
            status_code=403,
            detail="Anonymous users cannot create or modify dashboards. Please login to continue.",
        )

    # logger.info(f"Dashboard data: {data}")

    # Check if dashboard exists first
    existing_dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})

    if existing_dashboard:
        # Dashboard exists - check project-based permissions for update
        project_id = existing_dashboard.get("project_id")
        if not project_id:
            raise HTTPException(
                status_code=500, detail="Dashboard is not associated with a project."
            )

        # Check if user has editor permission on the project (required for editing)
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
        # Dashboard doesn't exist - insert new (for duplication case)
        # Note: For new dashboards, permissions should be set during creation
        result = dashboards_collection.find_one_and_update(
            {"dashboard_id": dashboard_id},
            {"$set": data.mongo()},
            upsert=True,
            return_document=True,
        )

    # MongoDB should always return a document after an upsert operation
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
        logger.error("Failed to insert or update dashboard data.")
        # It's unlikely to reach this point due to upsert=True, but included for completeness
        raise HTTPException(status_code=404, detail="Failed to insert or update dashboard data.")


@dashboards_endpoint_router.get("/screenshot/{dashboard_id}")
async def screenshot_dashboard(
    dashboard_id: PyObjectId,
    # current_user: User = Depends(get_current_user),
):
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
# YAML Export/Import Endpoints
# ============================================================================


@dashboards_endpoint_router.get("/export/{dashboard_id}/yaml")
async def export_dashboard_to_yaml(
    dashboard_id: PyObjectId,
    include_metadata: bool = True,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Export a dashboard to YAML format.

    This endpoint allows exporting dashboards as YAML for:
    - Version control (git-friendly format)
    - Backup and restore
    - Template creation
    - Infrastructure as code workflows

    Args:
        dashboard_id: The dashboard ID to export
        include_metadata: Whether to include export metadata (timestamp, version)
        current_user: The authenticated user

    Returns:
        YAML file download response
    """
    # Check if dashboard exists
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Get project_id and check permissions
    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check project-based permissions (viewer level required for export)
    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to export this dashboard."
        )

    # Convert MongoDB document to DashboardData model, then to YAML
    dashboard = DashboardData.from_mongo(dashboard_data)
    yaml_content = dashboard.to_yaml(include_metadata=include_metadata)

    # Create filename from dashboard title
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in dashboard.title)
    filename = f"dashboard_{safe_title}_{str(dashboard_id)[:8]}.yaml"

    logger.info(f"Exported dashboard {dashboard_id} to YAML for user {current_user.email}")

    return Response(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@dashboards_endpoint_router.get("/export/{dashboard_id}/yaml/preview")
async def preview_dashboard_yaml(
    dashboard_id: PyObjectId,
    include_metadata: bool = False,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Preview a dashboard as YAML without downloading.

    Returns the YAML content as JSON for preview in the UI.

    Args:
        dashboard_id: The dashboard ID to preview
        include_metadata: Whether to include export metadata
        current_user: The authenticated user

    Returns:
        JSON with yaml_content field
    """
    # Check if dashboard exists
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Get project_id and check permissions
    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    # Check project-based permissions
    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to view this dashboard."
        )

    # Convert to YAML
    dashboard = DashboardData.from_mongo(dashboard_data)
    yaml_content = dashboard.to_yaml(include_metadata=include_metadata)

    return {
        "success": True,
        "dashboard_id": str(dashboard_id),
        "title": dashboard.title,
        "yaml_content": yaml_content,
    }


@dashboards_endpoint_router.post("/import/yaml")
async def import_dashboard_from_yaml(
    yaml_content: str,
    project_id: PyObjectId,
    current_user: User = Depends(get_current_user),
):
    """
    Import a dashboard from YAML content.

    Creates a new dashboard from the provided YAML configuration.
    A new dashboard_id will be generated, and the current user will be set as owner.

    Args:
        yaml_content: The YAML content defining the dashboard
        project_id: The project to create the dashboard in
        current_user: The authenticated user (will be set as owner)

    Returns:
        Created dashboard information including new dashboard_id
    """
    # Additional check for anonymous users
    if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
        raise HTTPException(
            status_code=403,
            detail="Anonymous users cannot import dashboards. Please login to continue.",
        )

    # Check if user has editor permission on the target project
    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to create dashboards in this project.",
        )

    # Validate YAML content
    is_valid, errors = validate_dashboard_yaml(yaml_content)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dashboard YAML: {'; '.join(errors)}",
        )

    # Parse YAML to dictionary
    try:
        dashboard_dict = yaml_to_dashboard_dict(yaml_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Generate new IDs for the imported dashboard
    new_dashboard_id = ObjectId()

    # Override/set required fields for import
    dashboard_dict["dashboard_id"] = new_dashboard_id
    dashboard_dict["project_id"] = ObjectId(project_id)
    dashboard_dict["version"] = 1
    dashboard_dict["last_saved_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Set current user as owner
    dashboard_dict["permissions"] = {
        "owners": [{"_id": ObjectId(current_user.id)}],
        "editors": [],
        "viewers": [],
    }

    # Generate new UUIDs for all components to avoid conflicts
    if "stored_metadata" in dashboard_dict:
        for component in dashboard_dict["stored_metadata"]:
            old_index = component.get("index")
            new_index = str(uuid.uuid4())
            component["index"] = new_index

            # Update layout data references if they exist
            for layout_key in [
                "left_panel_layout_data",
                "right_panel_layout_data",
                "stored_layout_data",
            ]:
                if layout_key in dashboard_dict:
                    for layout_item in dashboard_dict[layout_key]:
                        if layout_item.get("i") == old_index:
                            layout_item["i"] = new_index

    # Validate with Pydantic model
    try:
        dashboard = DashboardData.from_mongo(dashboard_dict)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Dashboard validation failed: {e}",
        ) from e

    # Insert into database
    result = dashboards_collection.insert_one(dashboard.mongo())

    if not result.inserted_id:
        raise HTTPException(status_code=500, detail="Failed to import dashboard.")

    logger.info(
        f"Imported dashboard from YAML: {dashboard.title} (ID: {new_dashboard_id}) "
        f"by user {current_user.email}"
    )

    return {
        "success": True,
        "message": "Dashboard imported successfully",
        "dashboard_id": str(new_dashboard_id),
        "title": dashboard.title,
        "project_id": str(project_id),
    }


@dashboards_endpoint_router.post("/import/yaml/file")
async def import_dashboard_from_yaml_file(
    file: UploadFile,
    project_id: PyObjectId,
    current_user: User = Depends(get_current_user),
):
    """
    Import a dashboard from an uploaded YAML file.

    Args:
        file: The uploaded YAML file
        project_id: The project to create the dashboard in
        current_user: The authenticated user

    Returns:
        Created dashboard information
    """
    # Validate file extension
    if not file.filename or not file.filename.endswith((".yaml", ".yml")):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Please upload a .yaml or .yml file.",
        )

    # Read file content
    try:
        content = await file.read()
        yaml_content = content.decode("utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read file: {e}",
        ) from e

    # Delegate to the main import endpoint
    return await import_dashboard_from_yaml(
        yaml_content=yaml_content,
        project_id=project_id,
        current_user=current_user,
    )


@dashboards_endpoint_router.post("/validate/yaml")
async def validate_dashboard_yaml_endpoint(
    yaml_content: str,
    current_user: User = Depends(get_current_user),
):
    """
    Validate dashboard YAML content without importing.

    Use this endpoint to check if YAML is valid before import.

    Args:
        yaml_content: The YAML content to validate
        current_user: The authenticated user

    Returns:
        Validation result with any errors found
    """
    is_valid, errors = validate_dashboard_yaml(yaml_content)

    if is_valid:
        # Also try to parse and check structure
        try:
            dashboard_dict = yaml_to_dashboard_dict(yaml_content)
            component_count = len(dashboard_dict.get("stored_metadata", []))

            return {
                "valid": True,
                "message": "Dashboard YAML is valid",
                "title": dashboard_dict.get("title", "Untitled"),
                "component_count": component_count,
            }
        except ValueError as e:
            return {
                "valid": False,
                "message": "Dashboard YAML has structural issues",
                "errors": [str(e)],
            }
    else:
        return {
            "valid": False,
            "message": "Dashboard YAML validation failed",
            "errors": errors,
        }


@dashboards_endpoint_router.put("/update/{dashboard_id}/from_yaml")
async def update_dashboard_from_yaml(
    dashboard_id: PyObjectId,
    yaml_content: str,
    current_user: User = Depends(get_current_user),
):
    """
    Update an existing dashboard from YAML content.

    This is a "switch to YAML" operation that replaces the dashboard
    configuration while preserving the dashboard_id and project association.

    Args:
        dashboard_id: The dashboard ID to update
        yaml_content: The new YAML configuration
        current_user: The authenticated user

    Returns:
        Updated dashboard information
    """
    # Check if dashboard exists
    existing = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not existing:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Check permissions
    project_id = existing.get("project_id")
    if not check_project_permission(project_id, current_user, "editor"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to update this dashboard."
        )

    # Validate YAML
    is_valid, errors = validate_dashboard_yaml(yaml_content)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dashboard YAML: {'; '.join(errors)}",
        )

    # Parse YAML
    try:
        dashboard_dict = yaml_to_dashboard_dict(yaml_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Preserve critical fields from existing dashboard
    dashboard_dict["dashboard_id"] = dashboard_id
    dashboard_dict["project_id"] = existing["project_id"]
    dashboard_dict["permissions"] = existing.get("permissions", {})
    dashboard_dict["is_public"] = existing.get("is_public", False)
    dashboard_dict["last_saved_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Increment version
    dashboard_dict["version"] = existing.get("version", 0) + 1

    # Validate with Pydantic
    try:
        dashboard = DashboardData.from_mongo(dashboard_dict)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Dashboard validation failed: {e}",
        ) from e

    # Update in database
    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id},
        {"$set": dashboard.mongo()},
        return_document=True,
    )

    if not result:
        raise HTTPException(status_code=500, detail="Failed to update dashboard.")

    logger.info(f"Updated dashboard {dashboard_id} from YAML by user {current_user.email}")

    return {
        "success": True,
        "message": "Dashboard updated from YAML successfully",
        "dashboard_id": str(dashboard_id),
        "title": dashboard.title,
        "version": dashboard.version,
    }
