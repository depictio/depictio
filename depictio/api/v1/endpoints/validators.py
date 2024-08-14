from bson import ObjectId
from fastapi import HTTPException
from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection

from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow
from depictio.api.v1.models.base import convert_objectid_to_str


def validate_workflow_and_collection(collection, user_id: str, workflow_id: str, data_collection_id: str = None):
    """
    Validates the existence of a workflow and a specific data collection within it.
    Raises HTTPException if the validation fails.
    """
    try:
        user_oid = ObjectId(user_id)
        workflow_oid = ObjectId(workflow_id)
        if data_collection_id:
            data_collection_oid = ObjectId(data_collection_id)

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Retrieve the workflow
    workflow = collection.find_one(
        {"_id": workflow_oid, "permissions.owners.id": user_oid},
    )

    # Check if the workflow exists
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_id} found for the current user.",
        )

    # Convert the workflow to a Workflow object
    workflow = convert_objectid_to_str(workflow)
    workflow = Workflow(**workflow)

    # If no data collection id is provided, return the workflow and user_oid
    if not data_collection_id:
        return workflow_oid, None, workflow, user_oid

    # Extract the correct data collection from the workflow's data_collections
    data_collection = collection.find_one({"_id": workflow_oid, "permissions.owners.id": user_oid}, {"data_collections": {"$elemMatch": {"_id": data_collection_oid}}})
    data_collection = data_collection.get("data_collections")[0]

    data_collection = convert_objectid_to_str(data_collection)
    data_collection = DataCollection(**data_collection)

    # Check if the data collection exists
    if not data_collection:
        raise HTTPException(
            status_code=404,
            detail=f"Data collection with id {data_collection_id} not found in the workflow.",
        )

    return workflow_oid, data_collection_oid, workflow, data_collection, user_oid
