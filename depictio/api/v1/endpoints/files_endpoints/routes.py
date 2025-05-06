from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.custom_logging import logger
from depictio.api.v1.db import db
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.files import File

files_endpoint_router = APIRouter()

# Define the collections from the settings
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db["users"]

# Define the MinIO endpoint and bucket name from the settings
endpoint_url = settings.minio.service_name
bucket_name = settings.minio.bucket


class UpsertFilesBatchRequest(BaseModel):
    files: list[File]
    update: bool = False


@files_endpoint_router.post("/upsert_batch")
async def create_file(payload: UpsertFilesBatchRequest, current_user=Depends(get_current_user)):
    """
    Create one or more files in the database using bulk upsert.

    Args:
        files (List[dict]): List of file dictionaries to process.
        update (bool, optional): If True, update an existing file; otherwise, insert only if not present.
        current_user: The current user (dependency injected).

    Returns:
        A dict summarizing the operation (inserted/updated counts).
    """
    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    operations = []
    for file in payload.files:
        file_obj = file
        file_data = file.mongo()
        # convert data_collection_id to PyObjectId
        file_data["data_collection_id"] = ObjectId(file_data["data_collection_id"])

        # Use a different update operator based on the `update` flag.
        if payload.update:
            # $set will update the file if it exists; upsert=True means it will insert if not found.
            op = UpdateOne({"_id": file_obj.id}, {"$set": file_data}, upsert=True)
        else:
            # $setOnInsert will only insert the file if it doesn't already exist.
            op = UpdateOne({"_id": file_obj.id}, {"$setOnInsert": file_data}, upsert=True)
        operations.append(op)

    try:
        # Perform the bulk upsert
        result = files_collection.bulk_write(operations, ordered=False)

        if payload.update:
            # When update=True, some files might be updated and some inserted.
            return {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_count": result.upserted_count,
            }
        else:
            # When update=False, only new files are inserted. Existing ones are not modified.
            inserted_count = result.upserted_count  # Count of newly inserted files
            existing_count = len(payload.files) - inserted_count
            if existing_count > 0:
                logger.error(f"{existing_count} file(s) already exist and were not updated.")
            return {
                "inserted_count": inserted_count,
                "existing_count": existing_count,
            }
    except BulkWriteError as bwe:
        # Return detailed bulk write error information
        raise HTTPException(status_code=500, detail=bwe.details)


@files_endpoint_router.get("/list/{data_collection_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def list_registered_files(data_collection_id: str, current_user=Depends(get_current_user)):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """

    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    if not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Data collection id must be provided.",
        )

    user_oid = ObjectId(current_user.id)
    target_data_collection_id = ObjectId(data_collection_id)
    pipeline = [
        {
            "$match": {
                "$or": [
                    {"permissions.owners._id": user_oid},  # User is an owner
                    {"permissions.owners.is_admin": True},  # User is an admin
                ]
            }
        },
        {
            "$match": {"data_collection_id": target_data_collection_id}
        },  # Match files with the specific data collection ID
    ]

    result = files_collection.aggregate(pipeline)
    # logger.info(f"Result : {result}")

    files = list(result)
    logger.info(f"Files : {files}")
    # files = [convert_objectid_to_str(file) for file in files]
    return convert_objectid_to_str(files)


@files_endpoint_router.delete("/delete/{file_id}")
async def delete_file(file_id: str, current_user=Depends(get_current_user)):
    """
    Delete a file from the database.
    """

    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    if not file_id:
        raise HTTPException(
            status_code=400,
            detail="File id must be provided.",
        )

    user_oid = ObjectId(current_user.id)
    target_file_id = ObjectId(file_id)
    query = {
        "_id": target_file_id,
        "$or": [
            {"permissions.owners._id": user_oid},  # User is an owner
            {"permissions.owners.is_admin": True},  # User is an admin
        ],
    }

    result = files_collection.delete_one(query)
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No file with id {file_id} found for the current user.",
        )

    return {"message": f"Deleted file with id {file_id} successfully"}
