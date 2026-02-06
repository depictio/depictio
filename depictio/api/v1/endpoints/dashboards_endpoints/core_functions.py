from typing import Any

from bson import ObjectId

from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.models.models.base import PyObjectId, convert_objectid_to_str


def sync_tab_family_permissions(
    parent_dashboard_id: PyObjectId,
    new_permissions: dict[str, Any] | None = None,
    new_is_public: bool | None = None,
) -> int:
    """Update all child tabs with parent's permissions.

    This function ensures that all child tabs of a main dashboard
    inherit the same permissions and visibility settings.

    Args:
        parent_dashboard_id: The ID of the parent (main tab) dashboard
        new_permissions: New permissions dict to apply (optional)
        new_is_public: New visibility status to apply (optional)

    Returns:
        int: Number of child tabs updated
    """
    update_fields: dict[str, Any] = {}

    if new_permissions is not None:
        update_fields["permissions"] = new_permissions
    if new_is_public is not None:
        update_fields["is_public"] = new_is_public

    if not update_fields:
        return 0

    result = dashboards_collection.update_many(
        {"parent_dashboard_id": ObjectId(parent_dashboard_id)},
        {"$set": update_fields},
    )
    return result.modified_count


def get_child_tabs(parent_dashboard_id: PyObjectId) -> list[dict[str, Any]]:
    """Get all child tabs for a parent dashboard, sorted by tab_order.

    Args:
        parent_dashboard_id: The ID of the parent (main tab) dashboard

    Returns:
        list: List of child tab documents sorted by tab_order
    """
    projection = {
        "_id": 1,
        "dashboard_id": 1,
        "title": 1,
        "tab_order": 1,
        "tab_icon": 1,
        "tab_icon_color": 1,
        "is_main_tab": 1,
        "parent_dashboard_id": 1,
        # Include icon fields for fallback inheritance
        "icon": 1,
        "icon_color": 1,
    }

    children = list(
        dashboards_collection.find(
            {"parent_dashboard_id": ObjectId(parent_dashboard_id)},
            projection,
        ).sort("tab_order", 1)
    )

    return [convert_objectid_to_str(child) for child in children]


def reorder_child_tabs(
    parent_dashboard_id: PyObjectId,
    tab_orders: list[dict[str, Any]],
) -> int:
    """Reorder child tabs by updating their tab_order values.

    Args:
        parent_dashboard_id: The ID of the parent (main tab) dashboard
        tab_orders: List of {dashboard_id, tab_order} dicts

    Returns:
        int: Number of tabs updated
    """
    updated_count = 0

    for tab_order in tab_orders:
        dashboard_id = tab_order.get("dashboard_id")
        new_order = tab_order.get("tab_order")

        if dashboard_id is None or new_order is None:
            continue

        # Verify the tab belongs to this parent
        result = dashboards_collection.update_one(
            {
                "dashboard_id": ObjectId(dashboard_id),
                "parent_dashboard_id": ObjectId(parent_dashboard_id),
            },
            {"$set": {"tab_order": new_order}},
        )
        updated_count += result.modified_count

    return updated_count


def get_parent_dashboard_title(dashboard_dict: dict) -> str | None:
    """Get the parent dashboard title for a child tab.

    Args:
        dashboard_dict: Dashboard data dictionary (must be a child tab)

    Returns:
        Parent dashboard title, or None if not found or not a child tab
    """
    if dashboard_dict.get("is_main_tab", True):
        return None

    parent_id = dashboard_dict.get("parent_dashboard_id")
    if not parent_id:
        return None

    parent_dashboard = dashboards_collection.find_one(
        {"dashboard_id": ObjectId(str(parent_id))},
        {"title": 1},
    )
    if not parent_dashboard:
        return None

    return parent_dashboard.get("title", "Dashboard")


def load_dashboards_from_db(owner, admin_mode=False, user=None, include_child_tabs=False):
    """Load dashboards from MongoDB with project-based permissions."""
    projection = {
        "_id": 1,
        "dashboard_id": 1,
        "version": 1,
        "title": 1,
        "subtitle": 1,
        "icon": 1,
        "icon_color": 1,
        "icon_variant": 1,
        "permissions": 1,
        "last_saved_ts": 1,
        "project_id": 1,
        "is_public": 1,
        # Tab-specific fields (needed for sidebar tab navigation)
        "is_main_tab": 1,
        "parent_dashboard_id": 1,
        "tab_order": 1,
        "main_tab_name": 1,
        "tab_icon": 1,
        "tab_icon_color": 1,
    }
    if admin_mode:
        projection["stored_metadata"] = 1

    if admin_mode:
        # List all dashboards for all users
        query = {}
        if not include_child_tabs:
            # Show only main tabs (backward compatible - default behavior)
            query["is_main_tab"] = {"$ne": False}

        dashboards = list(dashboards_collection.find(query, projection))
        # Sort dashboards by title
        dashboards = sorted(dashboards, key=lambda x: x["title"])
    else:
        # Check if user is anonymous - if so, only show public projects
        # Exception: in single-user mode, anonymous users have admin access to all projects
        from depictio.api.v1.configs.config import settings

        user_id = ObjectId(owner)

        if user and hasattr(user, "is_anonymous") and user.is_anonymous:
            if settings.auth.is_single_user_mode:
                # Single-user mode: anonymous user has admin access to all projects
                accessible_projects = list(
                    projects_collection.find(
                        {},
                        {"_id": 1},
                    )
                )
            else:
                # Anonymous users can only access admin-owned public projects
                # (reference/demo projects), not user-created public projects
                accessible_projects = list(
                    projects_collection.find(
                        {
                            "is_public": True,
                            "permissions.owners.is_admin": True,
                        },
                        {"_id": 1},
                    )
                )
        else:
            # Regular authenticated users can access projects based on permissions
            accessible_projects = list(
                projects_collection.find(
                    {
                        "$or": [
                            {"permissions.owners._id": user_id},
                            {"permissions.editors._id": user_id},
                            {"permissions.viewers._id": user_id},
                            {"permissions.viewers": {"$in": ["*"]}},
                            {"is_public": True},
                        ]
                    },
                    {"_id": 1},
                )
            )

        accessible_project_ids = [project["_id"] for project in accessible_projects]

        # Get dashboards belonging to accessible projects.
        # Non-admin users only see dashboards they own or that are public.
        # This prevents non-public dashboards (e.g. admin test dashboards)
        # from leaking to anonymous/temporary users via public projects.
        if not settings.auth.is_single_user_mode and user and not getattr(user, "is_admin", False):
            query: dict = {
                "project_id": {"$in": accessible_project_ids},
                "$or": [
                    {"permissions.owners._id": user_id},
                    {"is_public": True},
                ],
            }
        else:
            query: dict = {"project_id": {"$in": accessible_project_ids}}
        if not include_child_tabs:
            # Show only main tabs (backward compatible - default behavior)
            query["is_main_tab"] = {"$ne": False}

        dashboards = list(dashboards_collection.find(query, projection))

    dashboards = [convert_objectid_to_str(dashboard) for dashboard in dashboards]
    return {"dashboards": dashboards, "success": True}
