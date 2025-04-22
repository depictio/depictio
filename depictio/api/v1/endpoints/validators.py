from bson import ObjectId
from fastapi import HTTPException

# from depictio.models.models.base import convert_objectid_to_str
# from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection
# from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow

from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.workflows import Workflow


from depictio.api.v1.configs.custom_logging import logger
from depictio.api.v1.db import projects_collection

# TODO: check if still compliant with the new structure
def return_project_object(user_id: str, project_id: str, permissions: dict = None):
    """
    Validates the existence of a project.
    Raises HTTPException if the validation fails.
    """
    try:
        user_oid = ObjectId(user_id)
        project_oid = ObjectId(project_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not permissions:
        permissions = {
            "$or": [
                {"permissions.owners._id": user_id},
                {"permissions.viewers._id": user_id},
                {"permissions.viewers": "*"},  # This makes projects with "*" publicly accessible
            ],
        }

    project = projects_collection.find_one(
        {"_id": project_oid, **permissions},
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"No projects with id {project_id} found for the current user.",
        )

    return project_oid, project, user_oid


def validate_workflow_and_collection(collection, user_id: str, workflow_id: str, data_collection_id: str = None, permissions: dict = None):
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
    # workflow = collection.find_one(
    #     {"_id": workflow_oid, "permissions.owners._id": user_oid},
    # )

    if not permissions:
        permissions = {
            "$or": [
                {"permissions.owners._id": user_id},
                {"permissions.viewers._id": user_id},
                {"permissions.viewers": "*"},  # This makes workflows with "*" publicly accessible
            ],
        }

    query = {
        "_id": ObjectId(workflow_id),
        **permissions,
    }

    logger.info(f"Query: {query}")
    workflow = collection.find_one(query)
    logger.info(f"Workflow: {workflow}")

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
    dc_query = {
        "_id": ObjectId(workflow_id),
        # "$or": [
        #     {"permissions.owners._id": user_id},
        #     # {"permissions.viewers._id": user_id},
        #     # {"permissions.viewers": "*"},  # This makes workflows with "*" publicly accessible
        # ],
        "data_collections._id": data_collection_oid,  # Directly match the _id inside data_collections
    }

    logger.debug(f"Data collection query: {dc_query}")
    logger.debug(f"Data collection id: {data_collection_id}")
    logger.debug(f"Workflow id: {workflow_id}")
    logger.debug(f"User id: {user_id}")
    logger.debug(f"Data collection oid: {data_collection_oid}")
    logger.debug(f"Workflow oid: {workflow_oid}")

    # Using positional operator to return only the matching data collection from the array
    workflow_dc = collection.find_one(dc_query, {"data_collections.$": 1})

    if workflow_dc:
        logger.debug(f"workflow_dc: {workflow_dc}")

        data_collection = workflow_dc.get("data_collections", [])[0]  # The matched data collection
        logger.debug(f"Data collection: {data_collection}")

        # data_collection = collection.find_one(dc_query)
        logger.debug(f"Data collection: {data_collection}")
        # data_collection = data_collection.get("data_collections")[0]
        logger.debug(f"Data collection: {data_collection}")

        data_collection = convert_objectid_to_str(data_collection)
        data_collection = DataCollection(**data_collection)

        # Check if the data collection exists
        if not data_collection:
            raise HTTPException(
                status_code=404,
                detail=f"Data collection with id {data_collection_id} not found in the workflow.",
            )

    else:
        logger.error(f"No matching workflow found for workflow_id: {workflow_id} and data_collection_oid: {data_collection_oid}")
        data_collection = None

    return workflow_oid, data_collection_oid, workflow, data_collection, user_oid
