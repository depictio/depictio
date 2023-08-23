import os
from fastapi import HTTPException
from fastapi import APIRouter
from typing import List

from configs.config import settings
from db import db
from configs.models import Workflow

# from modules.workflow_endpoints.models import Workflow

workflows_endpoint_router = APIRouter()

data_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]


@workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflows():
    # workflows_collection.drop()

    workflows_cursor = list(workflows_collection.find())

    if not workflows_cursor:
        raise HTTPException(status_code=404, detail="No workflows found.")

    return workflows_cursor


@workflows_endpoint_router.post("/create_workflow")
async def create_workflow(
    workflow: Workflow,
):
    workflows_collection.drop()
    
    expected_dir_name = f"{workflow.workflow_engine}--{workflow.workflow_name}"
    actual_dir_name = os.path.basename(workflow.workflow_config.parent_runs_location)

    if actual_dir_name != expected_dir_name:
        raise HTTPException(
            status_code=400,
            detail=f"The directory name '{actual_dir_name}' does not match the expected format '{expected_dir_name}'",
        )

    existing_workflow = workflows_collection.find_one(
        {"workflow_id": workflow.workflow_id}
    )
    if existing_workflow:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow with name '{workflow.workflow_id}' already exists.",
        )

    wf_dict = workflow.dict() if hasattr(workflow, "dict") else vars(workflow)
    print(wf_dict)
    # result = workflows_collection.insert_one(wf_dict)

    # return {"workflow_id": str(result.inserted_id)}
