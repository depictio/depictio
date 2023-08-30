import os
from fastapi import HTTPException
from fastapi import APIRouter
from typing import List

from depictio.fastapi_backend.configs.config import settings
from depictio.fastapi_backend.db import db
from depictio.fastapi_backend.configs.models import Workflow

# from modules.workflow_endpoints.models import Workflow

workflows_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]


@workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflows():
    # workflows_collection.drop()

    workflows_cursor = list(workflows_collection.find())
    for workflow in workflows_cursor:
        workflow["data_collection_ids"] = [
            str(oid) for oid in workflow["data_collection_ids"]
        ]

    if not workflows_cursor:
        raise HTTPException(status_code=404, detail="No workflows found.")

    return workflows_cursor


@workflows_endpoint_router.post("/create_workflow")
async def create_workflow(
    workflow: Workflow,
):
    workflows_collection.drop()
    data_collections_collection.drop()
    runs_collection.drop()
    files_collection.drop()

    existing_workflow = workflows_collection.find_one(
        {"workflow_id": workflow.workflow_id}
    )
    if existing_workflow:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow with name '{workflow.workflow_id}' already exists.",
        )

    # Extract and insert data_collections first to get their unique ids
    data_collection_ids = []
    for key, data_collection in workflow.data_collections.items():
        # Extract and insert config first to get its unique id
        data_collection_dict = (
            data_collection.dict()
            if hasattr(data_collection, "dict")
            else vars(data_collection)
        )

        data_collection_id = data_collections_collection.insert_one(
            data_collection_dict
        ).inserted_id
        data_collection_ids.append(data_collection_dict["data_collection_id"])

    # Now, insert the workflow, linking to the data_collection ids
    workflow_data = workflow.dict(exclude={"data_collections"})
    workflow_data["data_collection_ids"] = data_collection_ids

    result = workflows_collection.insert_one(workflow_data)

    return {"workflow_bid": str(result.inserted_id)}
