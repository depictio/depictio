import os
from fastapi import HTTPException, Depends, APIRouter
from typing import List

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.models.base import PyObjectId
from depictio.api.v1.models.orm_models import (
    DataCollectionConfigORM,
    DataCollectionORM,
    PermissionORM,
    WorkflowConfigORM,
    WorkflowORM,
)
from depictio.api.v1.models.pydantic_models import Workflow
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user


# from modules.workflow_endpoints.models import Workflow

workflows_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]
fschunks_collection = db["fs.chunks"]
fsfiles_collection = db["fs.files"]
permissions_collection = db["permissions"]
workflow_config_collection = db["workflow_config"]
data_collection_config_collection = db["data_collection_config"]


@workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflows(current_user: str = Depends(get_current_user)):
    # Assuming the 'current_user' now holds a 'user_id' as an ObjectId after being parsed in 'get_current_user'

    user_id = current_user.user_id  # This should be the ObjectId

    # Find workflows where current_user is either an owner or a viewer
    query = {
        "$or": [
            {"permissions.owners.user_id": user_id},
            {"permissions.viewers.user_id": user_id},
        ]
    }
    workflows_cursor = workflows_collection.find(query)

    workflows = []
    for workflow in workflows_cursor:
        # Convert the workflow to a dict, and convert ObjectId's to strings
        workflow_dict = {
            "id": str(workflow["_id"]),
            # Include other necessary workflow fields here, converting ObjectId's to strings as necessary
        }
        workflows.append(workflow_dict)

    if not workflows:
        raise HTTPException(
            status_code=404, detail="No workflows found for the current user."
        )

    return workflows


@workflows_endpoint_router.post("/create_workflow")
async def create_workflow(
    workflow: Workflow, current_user: str = Depends(get_current_user)
):
    workflows_collection.drop()
    data_collections_collection.drop()
    runs_collection.drop()
    files_collection.drop()
    fschunks_collection.drop()
    fsfiles_collection.drop()
    permissions_collection.drop()
    workflow_config_collection.drop()
    data_collection_config_collection.drop()

    # First, handle the workflow config and get its ID
    workflow_config_orm = WorkflowConfigORM(
        parent_runs_location=workflow.workflow_config.parent_runs_location,
        workflow_version=workflow.workflow_config.workflow_version,
        config=workflow.workflow_config.config,
        runs_regex=workflow.workflow_config.runs_regex,
        workflow_id=workflow.id,
    )
    workflow_config_id = workflow_config_collection.insert_one(
        workflow_config_orm.dict(by_alias=True)
    ).inserted_id

    # Handle the permissions separately, as previously shown
    permission_orm = PermissionORM(
        owners=[PyObjectId(owner.user_id) for owner in workflow.permissions.owners],
        viewers=[PyObjectId(viewer.user_id) for viewer in workflow.permissions.viewers],
    )
    permission_id = permissions_collection.insert_one(
        permission_orm.dict(by_alias=True)
    ).inserted_id

    data_collections_ids = []
    # Iterate over Data collections referenced in the workflow
    for data_collection_key, data_collection in workflow.data_collections.items():
        # First, handle the data collection config and get its ID
        data_collection_config_orm = DataCollectionConfigORM(
            regex=data_collection.config.regex,
            format=data_collection.config.format,
            pandas_kwargs=data_collection.config.pandas_kwargs,
            keep_fields=data_collection.config.keep_fields,
        )
        data_collection_config_id = data_collection_config_collection.insert_one(
            data_collection_config_orm.dict(by_alias=True)
        ).inserted_id

        # Now handle the data collection itself
        data_collection_orm = DataCollectionORM(
            data_collection_id=data_collection.data_collection_id,
            description=data_collection.description,
            config=data_collection_config_id,
            workflow_id=workflow.id,
        )
        data_collection_id = data_collections_collection.insert_one(
            data_collection_orm.dict(by_alias=True)
        ).inserted_id
        data_collections_ids.append(data_collection_id)

    # Now create the WorkflowORM with the permission ID and workflow config ID
    workflow_orm = WorkflowORM(
        workflow_name=workflow.workflow_name,
        workflow_engine=workflow.workflow_engine,
        workflow_description=workflow.workflow_description,
        workflow_id=workflow.workflow_id,
        permissions=permission_id,
        data_collections_ids=data_collections_ids,
        workflow_config=workflow_config_id,  # This field would need to be added to your WorkflowORM model
    )
    workflow_id = workflows_collection.insert_one(workflow_orm.dict(by_alias=True))

    return {"workflow_bid": str(workflow_id.inserted_id)}
