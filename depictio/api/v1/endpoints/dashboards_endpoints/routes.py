from bson import ObjectId
from fastapi import HTTPException, APIRouter

from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.models import DashboardData
from depictio.api.v1.models.base import convert_objectid_to_str


dashboards_endpoint_router = APIRouter()


@dashboards_endpoint_router.get("/get/{dashboard_id}")
async def list_versions(
    dashboard_id: str,
    # current_user: str = Depends(get_current_user),
):
    """
    Fetch all entries related to a dashboard ID
    """
    dashboard_id = ObjectId(dashboard_id)
    # Get all entries related to a dashboard ID
    entries = dashboards_collection.find({"dashboard_id": dashboard_id})
    entries = [convert_objectid_to_str(entry) for entry in entries]
    return entries


@dashboards_endpoint_router.post("/save/{dashboard_id}")
async def save_dashboard(dashboard_id: str, data: DashboardData):
    """
    Check if an entry with the same dashboard_id exists, if not, insert, if yes, update.
    """
    data_dict = data.dict()

    # Attempt to find and update the document, or insert if it doesn't exist
    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id},
        {"$set": data_dict},
        upsert=True,
        return_document=True  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
    )

    # MongoDB should always return a document after an upsert operation
    if result:
        message = "Dashboard data updated successfully." if result.get("dashboard_id", None) == dashboard_id else "Dashboard data inserted successfully."
        return {"message": message, "dashboard_id": dashboard_id}
    else:
        # It's unlikely to reach this point due to upsert=True, but included for completeness
        raise HTTPException(status_code=404, detail="Failed to insert or update dashboard data.")