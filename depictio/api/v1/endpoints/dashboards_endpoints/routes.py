from fastapi import Depends, HTTPException, APIRouter

from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.models import DashboardData
from depictio.api.v1.configs.logging import logger

from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

dashboards_endpoint_router = APIRouter()


@dashboards_endpoint_router.get("/get/{dashboard_id}")
async def get_dashboard(dashboard_id: str, current_user=Depends(get_current_user)):
    """
    Fetch dashboard data related to a dashboard ID.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user_id = current_user.id
    logger.info(f"Current user ID: {user_id}")

    # Find dashboards where current_user is either an owner or a viewer
    query = {
        "dashboard_id": str(dashboard_id),
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers.id": user_id},
        ],
    }

    dashboard_data = dashboards_collection.find_one(query)

    logger.info(f"Dashboard data: {dashboard_data}")

    dashboard_data = DashboardData.from_mongo(dashboard_data)
    logger.info(f"Dashboard data from mongo: {dashboard_data}")

    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found.")

    return dashboard_data

# /Users/tweber/Gits/depictio/dev/jup_nb/.jupyter/jupyter_notebook_config.py
@dashboards_endpoint_router.post("/save/{dashboard_id}")
async def save_dashboard(dashboard_id: str, data: dict, current_user=Depends(get_current_user)):
    """
    Check if an entry with the same dashboard_id exists, if not, insert, if yes, update.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    if not data:
        raise HTTPException(status_code=400, detail="No data provided to save.")

    user_id = current_user.id

    logger.info(f"Data to save: {data}")

    data = DashboardData.from_mongo(data)

    data_dict = data.mongo()
    # logger.info(f"Data to save: {data_dict}")

    # Attempt to find and update the document, or insert if it doesn't exist
    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
        {"$set": data_dict},
        upsert=True,
        return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
    )

    # MongoDB should always return a document after an upsert operation
    if result:
        message = "Dashboard data updated successfully." if result.get("dashboard_id", None) == dashboard_id else "Dashboard data inserted successfully."
        return {"message": message, "dashboard_id": dashboard_id}
    else:
        # It's unlikely to reach this point due to upsert=True, but included for completeness
        raise HTTPException(status_code=404, detail="Failed to insert or update dashboard data.")
