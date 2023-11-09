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
from depictio.api.v1.models.pydantic_models import (
    DataCollection,
    Permission,
    User,
    Workflow,
    WorkflowConfig,
)
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
users_collection = db["users"]


@workflows_endpoint_router.get("/get_workflows")
# @workflows_endpoint_router.get("/get_workflows", response_model=List[Workflow])
async def get_workflows(current_user: str = Depends(get_current_user)):
    # Assuming the 'current_user' now holds a 'user_id' as an ObjectId after being parsed in 'get_current_user'

    user_id = current_user.user_id  # This should be the ObjectId
    print(user_id)

    # {
    #   "_id": {
    #     "$oid": "654cf5bca31dc57726a046fb"
    #   },
    #   "owners": [
    #     {
    #       "$oid": "64a842842bf4fa7deaa3dbed"
    #     }
    #   ],
    #   "viewers": []
    # }

    # Find workflows where current_user is either an owner or a viewer
    # query = {"$or": [{"owners": user_id}, {"viewers": user_id}]}

    # permission_cursor = permissions_collection.find(query)
    # # Convert this to a PermissionORM object
    # permission_cursor = [PermissionORM(**doc) for doc in permission_cursor]
    # # Extract only _id fields from the PermissionORM objects
    # permission_cursor = [doc.id for doc in permission_cursor]

    # # retrieve workflows where permission_id matches the permission_id in the PermissionORM object
    # workflow_cursor = workflows_collection.find(
    #     {"permissions": {"$in": permission_cursor}}
    # )

    # # Convert this to a WorkflowORM object
    # workflow_cursor = [WorkflowORM(**doc) for doc in workflow_cursor]

    # # Retrieve the data collection for each workflow using the data_collection_id for each workflow and keep the structure
    # # of the workflow object
    # for workflow in workflow_cursor:
    #     data_collection_cursor = data_collections_collection.find(
    #         {"_id": {"$in": workflow.data_collections_ids}}
    #     )
    #     data_collection_cursor = [
    #         DataCollectionORM(**doc) for doc in data_collection_cursor
    #     ]

    #     # Convert the data_collection_cursor to a DataCollection object
    #     data_collection_cursor = [
    #         DataCollection(**doc.dict()) for doc in data_collection_cursor
    #     ]

    #     # Same for workflow config and permissions
    #     workflow_config_cursor = workflow_config_collection.find(
    #         {"_id": workflow.workflow_config}
    #     )
    #     workflow_config_cursor = [
    #         WorkflowConfigORM(**doc) for doc in workflow_config_cursor
    #     ]
    #     workflow_config_cursor = [
    #         WorkflowConfig(**doc) for doc in workflow_config_cursor
    #     ]

    #     owners = permissions_collection.find_one({"_id": workflow.permissions.owners})
    #     owners = [PyObjectId(owner.user_id) for owner in owners]

    #     # retrieve the corresponding users from the users collection
    #     owners = users_collection.find({"_id": {"$in": owners}})
    #     owners = [User(**doc) for doc in owners]

    #     viewers = permissions_collection.find_one({"_id": workflow.permissions.viewers})
    #     viewers = [PyObjectId(viewer.user_id) for viewer in viewers]

    #     # retrieve the corresponding users from the users collection
    #     viewers = users_collection.find({"_id": {"$in": viewers}})
    #     viewers = [User(**doc) for doc in viewers]

    #     workflow.permissions = Permission(owners=owners, viewers=viewers)

    #     new_workflow = Workflow(**workflow.dict(by_alias=True))
    #     new_workflow.data_collections = data_collection_cursor
    #     new_workflow.workflow_config = workflow_config_cursor[0]
    #     new_workflow.permissions = workflow.permissions

    #     print(new_workflow)
    # # Convert the workflow_cursor to a Workflow object

    # print(workflow_cursor)
    # exit()
    # return [doc for doc in cursor]

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

    # # First, handle the workflow config and get its ID
    # workflow_config_orm = WorkflowConfigORM(
    #     parent_runs_location=workflow.workflow_config.parent_runs_location,
    #     workflow_version=workflow.workflow_config.workflow_version,
    #     config=workflow.workflow_config.config,
    #     runs_regex=workflow.workflow_config.runs_regex,
    #     workflow_id=workflow.id,
    # )
    # workflow_config_id = workflow_config_collection.insert_one(
    #     workflow_config_orm.dict(by_alias=True)
    # ).inserted_id

    # # Handle the permissions separately, as previously shown
    # permission_orm = PermissionORM(
    #     owners=[PyObjectId(owner.user_id) for owner in workflow.permissions.owners],
    #     viewers=[PyObjectId(viewer.user_id) for viewer in workflow.permissions.viewers],
    # )
    # permission_id = permissions_collection.insert_one(
    #     permission_orm.dict(by_alias=True)
    # ).inserted_id

    # data_collections_ids = []
    # # Iterate over Data collections referenced in the workflow
    # for data_collection_key, data_collection in workflow.data_collections.items():
    #     # First, handle the data collection config and get its ID
    #     data_collection_config_orm = DataCollectionConfigORM(
    #         regex=data_collection.config.regex,
    #         format=data_collection.config.format,
    #         pandas_kwargs=data_collection.config.pandas_kwargs,
    #         keep_fields=data_collection.config.keep_fields,
    #     )
    #     data_collection_config_id = data_collection_config_collection.insert_one(
    #         data_collection_config_orm.dict(by_alias=True)
    #     ).inserted_id

    #     # Now handle the data collection itself
    #     data_collection_orm = DataCollectionORM(
    #         data_collection_id=data_collection.data_collection_id,
    #         description=data_collection.description,
    #         config=data_collection_config_id,
    #         workflow_id=workflow.id,
    #     )
    #     data_collection_id = data_collections_collection.insert_one(
    #         data_collection_orm.dict(by_alias=True)
    #     ).inserted_id
    #     data_collections_ids.append(data_collection_id)

    # # Now create the WorkflowORM with the permission ID and workflow config ID
    # workflow_orm = WorkflowORM(
    #     workflow_name=workflow.workflow_name,
    #     workflow_engine=workflow.workflow_engine,
    #     workflow_description=workflow.workflow_description,
    #     workflow_id=workflow.workflow_id,
    #     permissions=permission_id,
    #     data_collections_ids=data_collections_ids,
    #     workflow_config=workflow_config_id,  # This field would need to be added to your WorkflowORM model
    # )
    # workflow_id = workflows_collection.insert_one(workflow_orm.dict(by_alias=True))

    # return {"workflow_bid": str(workflow_id.inserted_id)}
