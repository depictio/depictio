from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import projects_collection, runs_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.users import User
from depictio.models.models.workflows import WorkflowRun

# Define the router
runs_endpoint_router = APIRouter()


@runs_endpoint_router.get("/list/{workflow_id}")
async def list_runs(workflow_id: str, current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not workflow_id:
        raise HTTPException(status_code=400, detail="Workflow ID is required to list runs.")
    workflow_oid = ObjectId(workflow_id)

    # Find the workflow by ID
    assert isinstance(workflow_oid, ObjectId)
    user_oid = ObjectId(current_user.id)

    query: dict = {"workflow_id": workflow_oid}
    # Admins (including the anonymous-admin used in single-user mode) bypass the
    # membership filter — they wouldn't appear in the run's permissions list.
    # The previous ``permissions.owners.is_admin`` check inspected a document
    # field instead of the caller, so it never reflected the real user.
    if not current_user.is_admin:
        query["$or"] = [
            {"permissions.owners._id": user_oid},  # User is an owner
            {"permissions.editors._id": user_oid},  # User is an editor
            {"permissions.viewers._id": user_oid},  # User is a viewer
            {"permissions.viewers": "*"},  # Publicly viewable
        ]

    # If permission is granted, retrieve all runs for the given workflow.
    runs_cursor = runs_collection.find(query)
    runs = list(runs_cursor)
    logger.info(f"Found {len(runs)} runs for workflow '{workflow_id}'.")

    return convert_objectid_to_str(runs)


@runs_endpoint_router.get("/get/{run_id}", response_model=WorkflowRun)
async def get_run(run_id: PyObjectId, current_user: User = Depends(get_current_user)):
    user_oid = ObjectId(current_user.id)

    query: dict = {"_id": run_id}
    # Admins bypass the membership filter; read-only access also extends to
    # editors/viewers and publicly viewable runs.
    if not current_user.is_admin:
        query["$or"] = [
            {"permissions.owners._id": user_oid},  # User is an owner
            {"permissions.editors._id": user_oid},  # User is an editor
            {"permissions.viewers._id": user_oid},  # User is a viewer
            {"permissions.viewers": "*"},  # Publicly viewable
        ]

    # Find the run by ID
    run = runs_collection.find_one(query)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    return WorkflowRun.from_mongo(run)


@runs_endpoint_router.delete("/delete/{run_id}")
async def delete_run(run_id: str, current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not run_id:
        raise HTTPException(status_code=400, detail="Run ID is required to delete a run.")
    run_oid = ObjectId(run_id)

    user_oid = ObjectId(current_user.id)

    # Deletion is a write operation: restrict to owners, with an admin bypass
    # based on the *caller* (not a document field, which the previous
    # ``permissions.owners.is_admin`` check incorrectly inspected).
    query: dict = {"_id": run_oid}
    if not current_user.is_admin:
        query["permissions.owners._id"] = user_oid

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
    runs: list[WorkflowRun]
    update: bool = False


@runs_endpoint_router.post("/upsert_batch")
async def create_run(
    payload: UpsertWorkflowRunBatchRequest, current_user=Depends(get_current_user)
):
    """Create or update workflow runs in batch."""
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if not payload.runs:
        raise HTTPException(status_code=400, detail="Run is required to create it.")

    workflow_id = payload.runs[0].workflow_id
    for run in payload.runs:
        if run.workflow_id != workflow_id:
            raise HTTPException(
                status_code=400, detail="All runs must belong to the same workflow."
            )

    run_tags = {run.run_tag for run in payload.runs}
    if len(run_tags) != len(payload.runs):
        raise HTTPException(status_code=400, detail="All runs must have unique run_tag.")

    user_oid = ObjectId(current_user.id)
    # Check if there is a project that contains the workflow.
    # Notice that since workflows are stored as subdocuments,
    # we use "workflows._id" to match the workflow's ObjectId.
    workflow_oid = ObjectId(workflow_id)
    # Upserting runs is a write operation: require project ownership, with an
    # admin bypass keyed on the *caller* (the previous ``permissions.owners.is_admin``
    # check inspected a document field, not the current user).
    project_query: dict = {"workflows._id": workflow_oid}
    if not current_user.is_admin:
        project_query["permissions.owners._id"] = user_oid
    project = projects_collection.find_one(project_query)

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
        run_obj = run
        run_data = run.mongo()

        existing_doc = runs_collection.find_one({"_id": run_obj.id}, {"scan_results": 1})
        existing_scan_results = existing_doc.get("scan_results", []) if existing_doc else []

        new_scan_results = [
            sr for sr in run_data.get("scan_results", []) if sr not in existing_scan_results
        ]

        if run_obj.run_tag in existing_run_tags:
            if payload.update:
                set_data = {k: v for k, v in run_data.items() if k != "scan_results"}
                op = UpdateOne(
                    {"_id": run_obj.id},
                    {
                        "$set": set_data,
                        "$push": {"scan_results": {"$each": new_scan_results}},
                    },
                )
            else:
                continue
        else:
            op = UpdateOne(
                {"_id": run_obj.id},
                {"$set": run_data},
                upsert=True,
            )

        operations.append(op)

    if not operations:
        return {"inserted_count": 0, "existing_count": len(payload.runs)}

    try:
        result = runs_collection.bulk_write(operations, ordered=False)

        if payload.update:
            return {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_count": result.upserted_count,
            }
        else:
            inserted_count = result.upserted_count
            existing_count = len(payload.runs) - inserted_count
            return {
                "inserted_count": inserted_count,
                "existing_count": existing_count,
            }
    except BulkWriteError as bwe:
        raise HTTPException(status_code=500, detail=bwe.details)
