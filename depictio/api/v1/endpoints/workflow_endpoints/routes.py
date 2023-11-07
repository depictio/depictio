import os
from fastapi import HTTPException, Depends, APIRouter
from typing import List

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.configs.models import Workflow
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user


# from modules.workflow_endpoints.models import Workflow

workflows_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]
fschunks_collection = db["fs.chunks"]
fsfiles_collection = db["fs.files"]


@workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflows(current_user: str = Depends(get_current_user)    ):
    # workflows_collection.drop()

    workflows_cursor = list(workflows_collection.find())
    print(workflows_cursor)

    # Optionally convert the ObjectId's to strings if necessary
    for workflow in workflows_cursor:
        workflow["id"] = str(workflow["_id"])
        workflow["permissions"]["owners"] = [
            {key: str(value) if key == "user_id" else value for key, value in owner.items()}
            for owner in workflow["permissions"]["owners"]
        ]

    if not workflows_cursor:
        raise HTTPException(status_code=404, detail="No workflows found for the current user.")


    # for workflow in workflows_cursor:
    #     workflow["data_collection_ids"] = [
    #         str(oid) for oid in workflow["data_collection_ids"]
    #     ]

    # if not workflows_cursor:
    #     raise HTTPException(status_code=404, detail="No workflows found.")

    return workflows_cursor


@workflows_endpoint_router.post("/create_workflow")
async def create_workflow(
    workflow: Workflow,
    current_user: str = Depends(get_current_user)    
):
    print("\n\n\n")
    print(workflow)

    workflows_collection.drop()
    data_collections_collection.drop()
    runs_collection.drop()
    files_collection.drop()
    fschunks_collection.drop()
    fsfiles_collection.drop()

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
