from bson import ObjectId
from fastapi import HTTPException

from depictio.api.pydantic_models import Workflow

def validate_workflow_and_collection(workflow_id: str, data_collection_id: str, user_id: str, collection):
    """
    Validates the existence of a workflow and a specific data collection within it.
    Raises HTTPException if the validation fails.
    
    :param workflow_id: The ID of the workflow.
    :param data_collection_id: The ID of the data collection.
    :param user_id: The ID of the current user.
    :param collection: The MongoDB collection object.
    :return: Tuple containing the workflow ObjectId and the data collection document.
    """
    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(user_id)

    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
        "data_collections._id": data_collection_oid,
    }

    workflow_cursor = collection.find_one(query)
    workflow = Workflow.from_mongo(workflow_cursor)

    if not workflow_cursor:
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )

    data_collection = next(
        (dc for dc in workflow.data_collections if dc.id == data_collection_oid),
        None
    )

    if data_collection is None:
        raise HTTPException(
            status_code=404,
            detail=f"Data collection with id {data_collection_oid} not found in the workflow.",
        )

    return workflow_oid, data_collection_oid, workflow, data_collection, user_oid