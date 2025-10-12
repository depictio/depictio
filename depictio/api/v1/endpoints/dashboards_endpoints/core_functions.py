from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.models.models.base import convert_objectid_to_str


def load_dashboards_from_db(owner, admin_mode=False, user=None):
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
    }
    if admin_mode:
        projection["stored_metadata"] = 1

    if admin_mode:
        # List all dashboards for all users
        dashboards = list(dashboards_collection.find({}, projection))
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
        dashboards = list(
            dashboards_collection.find(
                {"project_id": {"$in": accessible_project_ids}},
                projection,
            )
        )

    if not dashboards:
        logger.warning("No dashboards found.")
        dashboards = []

    # turn mongodb ObjectId to string
    dashboards = [convert_objectid_to_str(dashboard) for dashboard in dashboards]

    return {"dashboards": dashboards, "success": True}
