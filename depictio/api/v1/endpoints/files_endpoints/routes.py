import collections
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter


from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.jbrowse_endpoints.routes import handle_jbrowse_tracks
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection

# from depictio_models.models.base import convert_objectid_to_str
# from depictio.api.v1.endpoints.workflow_endpoints.models import WorkflowRun
# from depictio.api.v1.endpoints.files_endpoints.models import File

from depictio_models.models.base import convert_objectid_to_str
from depictio_models.models.workflows import WorkflowRun
from depictio_models.models.files import File

from depictio.api.v1.utils import (
    scan_files,
    scan_runs,
    serialize_for_mongo,
)


files_endpoint_router = APIRouter()

# Define the collections from the settings
data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db["users"]

# Define the MinIO endpoint and bucket name from the settings
endpoint_url = settings.minio.internal_endpoint
bucket_name = settings.minio.bucket


@files_endpoint_router.get("/list/{workflow_id}/{data_collection_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def list_registered_files(workflow_id: str, data_collection_id: str, current_user=Depends(get_current_user)):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """

    if not workflow_id or not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Both workflow_id and data_collection_id must be provided.",
        )

    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)

    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners._id": user_oid,
        "data_collections._id": data_collection_oid,
    }
    logger.info(query)
    if not workflows_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )

    query_files = {
        "data_collection._id": data_collection_oid,
    }
    files = list(files_collection.find(query_files))
    return convert_objectid_to_str(files)


@files_endpoint_router.post("/scan_metadata/{workflow_id}/{data_collection_id}")
async def scan_metadata(
    workflow_id: str,
    data_collection_id: str,
    current_user=Depends(get_current_user),
):
    """
    Scan the files and retrieve metadata.
    """

    if not workflow_id or not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Both workflow_id and data_collection_id must be provided.",
        )

    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.id,
        workflow_id,
        data_collection_id,
    )

    logger.info(current_user)
    user_id = str(current_user.id)
    logger.info(user_id)

    for location in workflow.config.parent_runs_location:
        files = scan_files(run_location=location, run_id="Metadata", data_collection=data_collection)
        for file in files:
            file = file.mongo()
            existing_file = files_collection.find_one({"file_location": file["file_location"]})
            if not existing_file:
                file["permissions"] = {
                    "owners": [{"id": user_oid, "email": current_user.email, "groups": current_user.groups}],
                    "viewers": [],
                }
                file = File(**file)
                file.id = ObjectId()
                files_collection.insert_one(file.mongo())
            else:
                logger.warning(f"File already exists: {file['file_location']}")
                file = File.from_mongo(existing_file)
                logger.debug(f"from mongo: {file}")

    return {"message": f"Files successfully scanned and created for data_collection: {data_collection.id} of workflow: {workflow.id}"}


@files_endpoint_router.post("/scan/{workflow_id}/{data_collection_id}")
async def scan_data_collection(
    workflow_id: str,
    data_collection_id: str,
    current_user=Depends(get_current_user),
):
    logger.info(f"Scanning data collection {data_collection_id} of workflow {workflow_id}")

    if not workflow_id or not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Both workflow_id and data_collection_id must be provided.",
        )

    if not current_user:
        raise HTTPException(status_code=400, detail="Current user not found.")

    logger.debug(f"Current user: {current_user}")

    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.id,
        workflow_id,
        data_collection_id,
    )

    logger.debug(f"Workflow: {workflow}")
    logger.debug(f"Data collection: {data_collection}")
    logger.debug(f"User: {current_user}")
    logger.debug(f"User OID: {user_oid}")
    logger.debug(f"Workflow OID: {workflow_oid}")
    logger.debug(f"Data collection OID: {data_collection_oid}")

    user_id = str(current_user.id)

    # Retrieve the workflow_config from the workflow
    locations = workflow.config.parent_runs_location

    logger.debug(f"Locations: {locations}")

    # Scan the runs and retrieve the files

    for location in locations:
        # logger.debug(f"Scanning location: {location}")
        runs_and_content = scan_runs(location, workflow.config, data_collection, workflow_oid)
        runs_and_content = serialize_for_mongo(runs_and_content)
        # logger.debug(f"Runs and content: {runs_and_content}")


        # Check if the scan was successful and the result is a list of dictionaries
        if isinstance(runs_and_content, list) and all(isinstance(item, dict) for item in runs_and_content):
            return_dict = {workflow.id: collections.defaultdict(list)}
            # Sort the runs by location
            runs_and_content = sorted(runs_and_content, key=lambda x: x["run_tag"])
            # logger.info(f"Runs and content: {runs_and_content}")
            for run in runs_and_content:
                files = run.pop("files", [])

                # Insert the run into runs_collection and retrieve its id

                run = WorkflowRun(**run)
                # logger.info(f"Run tag: {run.run_tag}")
                # logger.info(f"Files : {files}")
                # logger.info(f"Run: {run}")
                # logger.info(f"Run.mongo: {run.mongo()}")
                # logger.info(f"type(run.mongo()): {type(run.mongo())}")
                # logger.info(f"Run.mongo['workflow_id']: {run.mongo()['workflow_id']}")

                existing_run = runs_collection.find_one({"run_tag": run.mongo()["run_tag"], "workflow_id": run.mongo()["workflow_id"]})
                if existing_run:
                    logger.debug(f"Run already exists: {existing_run}")
                    run_id = existing_run["_id"]
                    run = WorkflowRun.from_mongo(existing_run)

                else:
                    run.id = ObjectId()
                    inserted_run = runs_collection.insert_one(run.mongo())
                    run_id = inserted_run.inserted_id

                # Add run_id to each file before inserting
                for file in sorted(files, key=lambda x: x["file_location"]):
                    file["permissions"] = {
                        "owners": [{"id": user_oid, "email": current_user.email, "groups": current_user.groups, "is_admin": current_user.is_admin}],
                        "viewers": [],
                    }

                    # logger.info(data_collection.config.type)

                    if data_collection.config.type == "JBrowse2":
                        # logger.info(data_collection.config)
                        handle_jbrowse_tracks(file, user_id, workflow.id, data_collection)

                    # Check if the file already exists in the database

                    # Assuming user_oid is the ObjectId of the current user

                    existing_file_query = {
                        "file_location": file["file_location"],
                        "data_collection.id": data_collection_oid,
                        "permissions.owners": {"$elemMatch": {"id": ObjectId(user_oid)}},
                    }

                    existing_file = files_collection.find_one(existing_file_query)

                    file = File(**file)

                    # logger.info(f"Existing file query: {existing_file_query}")
                    # logger.info(f"Existing file: {existing_file}")

                    if not existing_file:
                        logger.debug(f"File does not exist: {file.mongo()['file_location']} - Inserting...")
                        file.id = ObjectId()
                        # If the file does not exist, add it to the database
                        files_collection.insert_one(file.mongo())
                    else:
                        logger.warning(f"File already exists: {file.mongo()['file_location']}")
                        file = File.from_mongo(existing_file)

                    logger.debug(f"File: {file}")

        return {"message": f"Files successfully scanned and created for data_collection: {data_collection.id} of workflow: {workflow.id}"}
    else:
        return {"Warning: runs_and_content is not a list of dictionaries."}


@files_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_files(
    workflow_id: str,
    data_collection_id: str,
    current_user=Depends(get_current_user),
):
    """
    Delete all files from GridFS.
    """

    if not workflow_id or not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Both workflow_id and data_collection_id must be provided.",
        )

    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)
    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners._id": user_oid,
        "data_collections._id": data_collection_oid,
    }
    logger.info(query)
    if not workflows_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )

    # Query to find files associated with the data collection
    query_files = {"data_collection_id": data_collection_oid}

    # Batch delete the files
    delete_result = files_collection.delete_many(query_files)

    # Optionally, update the workflow document to reflect the deletion
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {"$pull": {"data_collections": {"_id": data_collection_oid}}},
    )

    return {"message": f"Deleted {delete_result.deleted_count} files successfully"}
