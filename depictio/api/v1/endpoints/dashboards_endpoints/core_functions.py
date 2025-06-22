from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.models.models.base import convert_objectid_to_str


def load_dashboards_from_db(owner, admin_mode=False):
    logger.info("Loading dashboards from MongoDB")

    projection = {
        "_id": 1,
        "dashboard_id": 1,
        "version": 1,
        "title": 1,
        "permissions": 1,
        "last_saved_ts": 1,
        "project_id": 1,
    }
    if admin_mode:
        projection["stored_metadata"] = 1

    # Fetch all dashboards corresponding to owner (email address)
    # dashboards = list(dashboards_collection.find({"permissions.owners._id": ObjectId(owner)}, projection))

    if admin_mode:
        # List all dashboards for all users
        dashboards = list(dashboards_collection.find({}, projection))
        # Sort dashboards by title
        dashboards = sorted(dashboards, key=lambda x: x["title"])
    else:
        dashboards = list(
            dashboards_collection.find(
                {
                    "$or": [
                        {"permissions.owners._id": ObjectId(owner)},
                        {"permissions.viewers._id": ObjectId(owner)},
                    ]
                },
                projection,
            )
        )

    if not dashboards:
        logger.warning("No dashboards found.")
        dashboards = []

    # turn mongodb ObjectId to string
    dashboards = [convert_objectid_to_str(dashboard) for dashboard in dashboards]

    return {"dashboards": dashboards, "success": True}
