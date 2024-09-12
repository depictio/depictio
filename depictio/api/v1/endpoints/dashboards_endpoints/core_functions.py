from bson import ObjectId
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.models.base import convert_objectid_to_str


def load_dashboards_from_db(owner):
    logger.info("Loading dashboards from MongoDB")

    logger.info(f"owner: {owner}")
    projection = {"_id": 1, "dashboard_id": 1, "version": 1, "title": 1, "permissions": 1}

    # Fetch all dashboards corresponding to owner (email address)
    dashboards = list(dashboards_collection.find({"permissions.owners._id": ObjectId(owner)}, projection))

    if not dashboards:
        logger.info("No dashboards found.")
        dashboards = []

    logger.info(f"dashboards: {dashboards}")

    # turn mongodb ObjectId to string
    dashboards = [convert_objectid_to_str(dashboard) for dashboard in dashboards]

    return {"dashboards": dashboards, "success": True}
