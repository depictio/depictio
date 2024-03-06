from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow



# def validate_workflow_and_collection(collection, workflow_id: str, data_collection_id: str = None):
def validate_workflow_and_collection(collection, user_id: str, workflow_id: str, data_collection_id: str = None):
    """
    Validates the existence of a workflow and a specific data collection within it.
    Raises HTTPException if the validation fails.
    
    :param workflow_id: The ID of the workflow.
    :param data_collection_id: The ID of the data collection.
    :param user_id: The ID of the current user.
    :param collection: The MongoDB collection object.
    :return: Tuple containing the workflow ObjectId and the data collection document.
    """
    user_oid = ObjectId(user_id)
    workflow_oid = ObjectId(workflow_id)
    print(data_collection_id)
    if data_collection_id:
        data_collection_oid = ObjectId(data_collection_id)

    # Construct the query to find the workflow
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
    }

    if data_collection_id:
        query["data_collections._id"] = data_collection_oid
    

    workflow_cursor = collection.find_one(query)
    # print(workflow_cursor)
    # print("\n\n\n")
    # print("validate_workflow_and_collection")
    # print(query)
    # print(workflow_cursor)


    workflow = Workflow.from_mongo(workflow_cursor)
    # print(workflow)
    # print("\n\n\n")

    if not workflow_cursor:
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )

    if data_collection_id:
        data_collection = next(
            (dc for dc in workflow.data_collections if dc.id == data_collection_oid),
            None
        )

        if data_collection is None:
            raise HTTPException(
                status_code=404,
                detail=f"Data collection with id {data_collection_oid} not found in the workflow.",
            )

        # return workflow_oid, data_collection_oid, workflow, data_collection
        return workflow_oid, data_collection_oid, workflow, data_collection, user_oid
    
    return workflow_oid, workflow
    # return workflow_oid, workflow, user_oid