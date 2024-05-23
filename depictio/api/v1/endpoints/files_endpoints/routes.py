import collections
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter


from depictio.api.v1.configs.config import settings, logger
from depictio.api.v1.db import db
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.endpoints.workflow_endpoints.models import WorkflowRun
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
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
async def list_registered_files(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """

    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.user_id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)

    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
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
    current_user: str = Depends(get_current_user),
):
    """
    Scan the files and retrieve metadata.
    """
    logger.info("Scanning data collection")
    logger.info(workflow_id)
    logger.info(data_collection_id)

    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.user_id,
        workflow_id,
        data_collection_id,
    )

    logger.info(current_user)
    user_id = str(current_user.user_id)
    logger.info(user_id)

    for location in workflow.config.parent_runs_location:
        files = scan_files(run_location=location, run_id="Metadata", data_collection=data_collection)
        for file in files:
            file = file.mongo()
            existing_file = files_collection.find_one({"file_location": file["file_location"]})
            if not existing_file:
                file = File(**file)
                file.id = ObjectId()
                files_collection.insert_one(file.mongo())
            else:
                logger.info(f"File already exists: {file['file_location']}")
                file = File.from_mongo(existing_file)
                logger.info("from mongo", file)

    return {"message": f"Files successfully scanned and created for data_collection: {data_collection.id} of workflow: {workflow.id}"}


@files_endpoint_router.post("/scan/{workflow_id}/{data_collection_id}")
async def scan_data_collection(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    logger.info("Scanning data collection")
    logger.info(workflow_id)
    logger.info(data_collection_id)

    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.user_id,
        workflow_id,
        data_collection_id,
    )

    logger.info(current_user)
    user_id = str(current_user.user_id)
    logger.info(user_id)

    # Retrieve the workflow_config from the workflow
    locations = workflow.config.parent_runs_location

    logger.info(locations)

    # Scan the runs and retrieve the files

    new_tracks = []

    for location in locations:
        logger.info(location)
        runs_and_content = scan_runs(location, workflow.config, data_collection)
        runs_and_content = serialize_for_mongo(runs_and_content)

        # Check if the scan was successful and the result is a list of dictionaries
        if isinstance(runs_and_content, list) and all(isinstance(item, dict) for item in runs_and_content):
            return_dict = {workflow.id: collections.defaultdict(list)}
            # Sort the runs by location
            runs_and_content = sorted(runs_and_content, key=lambda x: x["run_location"])
            for run in runs_and_content:
                files = run.pop("files", [])

                # Insert the run into runs_collection and retrieve its id

                run = WorkflowRun(**run)

                existing_run = runs_collection.find_one({"run_tag": run.mongo()["run_tag"]})
                if existing_run:
                    logger.info(f"Run already exists: {existing_run}")
                    run_id = existing_run["_id"]
                    run = WorkflowRun.from_mongo(existing_run)

                else:
                    run.id = ObjectId()
                    inserted_run = runs_collection.insert_one(run.mongo())
                    run_id = inserted_run.inserted_id

                # Add run_id to each file before inserting
                for file in sorted(files, key=lambda x: x["file_location"]):
                    file = File(**file)
                    # logger.info(data_collection.config.type)

                    # if data_collection.config.type == "JBrowse2":
                    #     # logger.info(data_collection.config)
                    #     handle_jbrowse_tracks(file, user_id, workflow.id, data_collection)

                    # Check if the file already exists in the database

                    existing_file = files_collection.find_one({"file_location": file.mongo()["file_location"]})
                    if not existing_file:
                        file.id = ObjectId()
                        # If the file does not exist, add it to the database
                        files_collection.insert_one(file.mongo())
                    else:
                        logger.info(f"File already exists: {file.mongo()['file_location']}")
                        file = File.from_mongo(existing_file)

                    logger.info("File")
                    logger.info(file)

        return {"message": f"Files successfully scanned and created for data_collection: {data_collection.id} of workflow: {workflow.id}"}
    else:
        return {"Warning: runs_and_content is not a list of dictionaries."}


@files_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_files(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Delete all files from GridFS.
    """

    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.user_id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)
    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
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
