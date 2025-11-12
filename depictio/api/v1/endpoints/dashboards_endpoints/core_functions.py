from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.models.models.base import convert_objectid_to_str


def load_dashboards_from_db(owner, admin_mode=False, user=None, include_child_tabs=False):
    logger.info("Loading dashboards from MongoDB with project-based permissions")

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
        user_id = ObjectId(owner)

        if user and hasattr(user, "is_anonymous") and user.is_anonymous:
            # Anonymous users can only access public projects
            accessible_projects = list(
                projects_collection.find(
                    {"is_public": True},
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

        # Get all dashboards belonging to accessible projects
        query = {"project_id": {"$in": accessible_project_ids}}
        if not include_child_tabs:
            # Show only main tabs (backward compatible - default behavior)
            query["is_main_tab"] = {"$ne": False}

        dashboards = list(dashboards_collection.find(query, projection))

    if not dashboards:
        logger.warning("No dashboards found.")
        dashboards = []

    # turn mongodb ObjectId to string
    dashboards = [convert_objectid_to_str(dashboard) for dashboard in dashboards]

    return {"dashboards": dashboards, "success": True}
