from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import projects_collection, runs_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.workflows import WorkflowRun

# Define the router
runs_endpoint_router = APIRouter()


@runs_endpoint_router.get("/list/{workflow_id}")
async def list_runs(workflow_id: str, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not workflow_id:
        raise HTTPException(status_code=400, detail="Workflow ID is required to list runs.")
    workflow_oid = ObjectId(workflow_id)

    # Find the workflow by ID
    assert isinstance(workflow_oid, ObjectId)
    user_oid = ObjectId(current_user.id)

    query = {
        "workflow_id": workflow_oid,
        "$or": [
            {"permissions.owners._id": user_oid},  # User is an owner
            {"permissions.owners.is_admin": True},  # User is an admin
        ],
    }

    # If permission is granted, retrieve all runs for the given workflow.
    runs_cursor = runs_collection.find(query)
    runs = list(runs_cursor)
    logger.info(f"Found {len(runs)} runs for workflow '{workflow_id}'.")

    return convert_objectid_to_str(runs)


@runs_endpoint_router.get("/get/{run_id}")
async def get_run(run_id: str, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not run_id:
        raise HTTPException(status_code=400, detail="Run ID is required to get a run.")
    run_oid = ObjectId(run_id)

    user_oid = ObjectId(current_user.id)

    query = {
        "_id": run_oid,
        "$or": [
            {"permissions.owners._id": user_oid},  # User is an owner
            {"permissions.owners.is_admin": True},  # User is an admin
        ],
    }

    # Find the run by ID
    run = runs_collection.find_one(query)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    return convert_objectid_to_str(run)


@runs_endpoint_router.delete("/delete/{run_id}")
async def delete_run(run_id: str, current_user: str = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not run_id:
        raise HTTPException(status_code=400, detail="Run ID is required to delete a run.")
    run_oid = ObjectId(run_id)

    user_oid = ObjectId(current_user.id)

    query = {
        "_id": run_oid,
        "$or": [
            {"permissions.owners._id": user_oid},  # User is an owner
            {"permissions.owners.is_admin": True},  # User is an admin
        ],
    }

    # Find the run by ID
    run = runs_collection.find_one(query)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    # Delete the run
    result = runs_collection.delete_one(query)

    return {
        "result": "deleted" if result.deleted_count == 1 else "not deleted",
        "message": f"Run '{run_id}' deleted.",
    }


class UpsertWorkflowRunBatchRequest(BaseModel):
    runs: list[dict]
    runs: list[WorkflowRun]
    update: bool = False


@runs_endpoint_router.post("/upsert_batch")
async def create_run(
    payload: UpsertWorkflowRunBatchRequest, current_user=Depends(get_current_user)
):
    # return
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if not payload.runs:
        raise HTTPException(status_code=400, detail="Run is required to create it.")

    # assert all runs share the same workflow ID
    # payload.runs = [WorkflowRun.from_mongo(run) for run in payload.runs]
    workflow_id = payload.runs[0].workflow_id
    for run in payload.runs:
        if run.workflow_id != workflow_id:
            raise HTTPException(
                status_code=400, detail="All runs must belong to the same workflow."
            )

    # assert all runs have unique run_tag
    run_tags = {run.run_tag for run in payload.runs}
    if len(run_tags) != len(payload.runs):
        raise HTTPException(status_code=400, detail="All runs must have unique run_tag.")

    # logger.info(f"Current user: {current_user}")
    # logger.info(f"Files: {payload.files}")

    user_oid = ObjectId(current_user.id)
    # Check if there is a project that contains the workflow.
    # Notice that since workflows are stored as subdocuments,
    # we use "workflows._id" to match the workflow's ObjectId.
    workflow_oid = ObjectId(workflow_id)
    project = projects_collection.find_one(
        {
            "workflows._id": workflow_oid,
            "$or": [
                {"permissions.owners._id": user_oid},
                {"permissions.owners.is_admin": True},
            ],
        }
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"User does not have permission on the project containing workflow '{workflow_id}'.",
        )

    # If permission is granted, retrieve all runs for the given workflow.
    runs_cursor = runs_collection.find({"workflow_id": workflow_oid})
    existing_runs = list(runs_cursor)
    existing_run_tags = {run["run_tag"] for run in existing_runs}

    operations = []
    for run in payload.runs:
        logger.info(f"Upserting run: {run.run_tag}")
        run_obj = run
        run_data = run.mongo()  # run_data is a dict representation of the run

        # Query the existing document (if it exists) to extract its current scan_results:
        existing_doc = runs_collection.find_one({"_id": run_obj.id}, {"scan_results": 1})
        existing_scan_results = existing_doc.get("scan_results", []) if existing_doc else []

        # Compute only the new scan results:
        # (This assumes that a simple equality comparison between dicts is sufficient.
        # You might need to customize this if the dicts differ only in field order or extra fields.)
        new_scan_results = [
            sr for sr in run_data.get("scan_results", []) if sr not in existing_scan_results
        ]

        if run_obj.run_tag in existing_run_tags:
            logger.info(f"Run with run_tag '{run_obj.run_tag}' already exists.")
            if payload.update:
                logger.info(f"Updating run: {run_obj.run_tag}")
                # Remove scan_results from the data that we use for a $set update.
                set_data = {k: v for k, v in run_data.items() if k != "scan_results"}
                op = UpdateOne(
                    {"_id": run_obj.id},
                    {
                        "$set": set_data,
                        "$push": {"scan_results": {"$each": new_scan_results}},
                    },
                )
            else:
                logger.info(
                    f"Skipping run: {run_obj.run_tag}. If you want to update, set 'update' to True."
                )

        else:
            # If the run does not exist, you might decide to insert it or handle it differently.
            # For example, you could add an InsertOne operation here.
            # For now, we'll just skip it.
            logger.info(f"Run with run_tag '{run_obj.run_tag}' does not exist. Creating it.")
            op = UpdateOne(
                {"_id": run_obj.id},
                {"$set": run_data},
                upsert=True,
            )

        operations.append(op)

    try:
        # Perform the bulk upsert
        result = runs_collection.bulk_write(operations, ordered=False)

        if payload.update:
            # When update=True, some files might be updated and some inserted.
            return {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_count": result.upserted_count,
            }
        else:
            # When update=False, only new runs are inserted. Existing ones are not modified.
            inserted_count = result.upserted_count  # Count of newly inserted files
            existing_count = len(payload.runs) - inserted_count
            if existing_count > 0:
                logger.error(f"{existing_count} runs(s) already exist and were not updated.")
            return {
                "inserted_count": inserted_count,
                "existing_count": existing_count,
            }
    except BulkWriteError as bwe:
        # Return detailed bulk write error information
        raise HTTPException(status_code=500, detail=bwe.details)
